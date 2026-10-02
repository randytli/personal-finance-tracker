"""Backup object stores for the PFT backup runner. Standard library only.

A backup is one named point made of several encrypted assets. Every store
gives the same guarantees:

- ``put`` succeeds only after every asset has been read back and its SHA-256
  matches the local file;
- ``list`` returns only complete, verified points;
- a failed ``put`` leaves no listed point behind.

``GitHubReleaseStore`` maps a point to one release in a dedicated private
repository. It creates a **draft**, uploads the assets, reads each one back,
and only then publishes the release. Drafts are never listed, so a crash
mid-upload cannot look like a backup. ``LocalDirectoryStore`` follows the same
contract for local tests and for the owner's offline secondary copy.
"""
import calendar
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

POINT_NAME = re.compile(r"pft-backup-(\d{8}T\d{6}Z)-([a-f0-9]{16})")
ASSET_NAME = re.compile(r"[a-z][a-z0-9.]{0,40}\.age")
CHUNK = 1024 * 1024
API_VERSION = "2022-11-28"


class StoreError(RuntimeError):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _check_point(name, assets=None):
    if not POINT_NAME.fullmatch(name):
        raise StoreError("invalid backup point name")
    for asset in assets or ():
        if not ASSET_NAME.fullmatch(asset):
            raise StoreError("invalid asset name")


class LocalDirectoryStore:
    """One subdirectory per point. A point is published by renaming a fully
    written and re-hashed staging directory, so it appears atomically."""

    def __init__(self, root):
        self.root = Path(root)
        if not self.root.is_dir() or self.root.is_symlink():
            raise StoreError("store root must be an existing real directory")

    def put(self, name, files):
        _check_point(name, files)
        final = self.root / name
        if final.exists():
            raise StoreError("backup point already exists")
        staging = Path(tempfile.mkdtemp(prefix=".upload-", dir=self.root))
        try:
            result = {}
            for asset, path in sorted(files.items()):
                expected = sha256_file(path)
                with open(path, "rb") as data, (staging / asset).open("xb") as output:
                    shutil.copyfileobj(data, output, CHUNK)
                    output.flush()
                    os.fsync(output.fileno())
                if sha256_file(staging / asset) != expected:
                    raise StoreError("readback hash mismatch")
                result[asset] = {"sha256": expected, "size": (staging / asset).stat().st_size}
            os.rename(staging, final)
            return result
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def list(self):
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and POINT_NAME.fullmatch(p.name))

    def get(self, name, destination):
        _check_point(name)
        destination = Path(destination)
        out = {}
        for asset in sorted((self.root / name).iterdir()):
            target = destination / asset.name
            with asset.open("rb") as data, target.open("xb") as output:
                shutil.copyfileobj(data, output, CHUNK)
            out[asset.name] = target
        return out

    def delete(self, name):
        _check_point(name)
        shutil.rmtree(self.root / name)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class GitHubReleaseStore:
    """Releases in one private repository, via the REST API.

    Endpoints (docs.github.com/en/rest/releases): create release, upload
    release asset (``upload_url``), get release asset with
    ``Accept: application/octet-stream`` (answered by a redirect to storage),
    update release, list releases, delete release, delete tag reference.

    The token is only ever sent to the configured API and upload hosts.
    Asset downloads follow the storage redirect manually **without**
    ``Authorization``, so the token never reaches a third host.
    """

    def __init__(self, repository, token, *, api_url="https://api.github.com",
                 upload_host="uploads.github.com", timeout=120):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository or ""):
            raise StoreError("repository must be owner/name")
        if not token:
            raise StoreError("GitHub token is required")
        self.repository = repository
        self._token = token
        self.api_url = api_url.rstrip("/")
        self.trusted_hosts = {urllib.parse.urlsplit(self.api_url).netloc, upload_host}
        self.timeout = timeout
        self._opener = urllib.request.build_opener(_NoRedirect)

    # -- HTTP

    def _request(self, method, url, *, body=None, content_type=None, accept="application/vnd.github+json",
                 expect=(200, 201, 204), data_path=None):
        if urllib.parse.urlsplit(url).netloc not in self.trusted_hosts:
            raise StoreError("refusing to send the token to an untrusted host")
        headers = {"Authorization": f"Bearer {self._token}", "Accept": accept,
                   "X-GitHub-Api-Version": API_VERSION, "User-Agent": "pft-backup-runner"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        elif data_path is not None:
            data = Path(data_path).read_bytes()
            headers["Content-Type"] = content_type or "application/octet-stream"
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            response = self._opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in expect:
                return exc  # e.g. 302 for asset downloads
            raise StoreError(f"GitHub API {method} returned {exc.code}") from None
        if response.status not in expect:
            raise StoreError(f"GitHub API {method} returned {response.status}")
        return response

    def _json(self, method, path, **kwargs):
        response = self._request(method, f"{self.api_url}/repos/{self.repository}{path}", **kwargs)
        raw = response.read()
        return json.loads(raw) if raw else None

    def _releases(self):
        page, releases = 1, []
        while True:
            batch = self._json("GET", f"/releases?per_page=100&page={page}")
            releases.extend(batch)
            if len(batch) < 100:
                return releases
            page += 1

    def _download(self, asset_id, destination):
        response = self._request("GET", f"{self.api_url}/repos/{self.repository}/releases/assets/{asset_id}",
                                 accept="application/octet-stream", expect=(200, 302))
        if getattr(response, "code", None) == 302 or getattr(response, "status", None) == 302:
            location = response.headers["Location"]
            if urllib.parse.urlsplit(location).scheme not in ("https", "http"):
                raise StoreError("unexpected asset redirect")
            # Storage URLs are pre-signed: send no credentials there.
            response = urllib.request.urlopen(urllib.request.Request(
                location, headers={"Accept": "application/octet-stream",
                                   "User-Agent": "pft-backup-runner"}), timeout=self.timeout)
        with response, open(destination, "xb") as output:
            shutil.copyfileobj(response, output, CHUNK)

    # -- store contract

    def put(self, name, files):
        _check_point(name, files)
        if any(r["tag_name"] == name for r in self._releases()):
            raise StoreError("backup point already exists")
        release = self._json("POST", "/releases", body={"tag_name": name, "name": name, "draft": True,
                                                         "body": "PFT encrypted backup point (age)."})
        try:
            upload = release["upload_url"].split("{", 1)[0]
            result = {}
            for asset, path in sorted(files.items()):
                expected = sha256_file(path)
                created = json.loads(self._request(
                    "POST", f"{upload}?{urllib.parse.urlencode({'name': asset})}",
                    data_path=path, content_type="application/octet-stream").read())
                if created.get("digest") not in (None, f"sha256:{expected}"):
                    raise StoreError("server-side asset digest mismatch")
                with tempfile.TemporaryDirectory() as scratch:
                    copy = Path(scratch) / asset
                    self._download(created["id"], copy)
                    if sha256_file(copy) != expected:
                        raise StoreError("readback hash mismatch")
                result[asset] = {"sha256": expected, "size": created.get("size")}
            # Publishing is the commit point: only now does the point exist.
            self._json("PATCH", f"/releases/{release['id']}", body={"draft": False})
            return result
        except BaseException:
            try:
                self._json("DELETE", f"/releases/{release['id']}")
            except StoreError:
                pass  # a leftover draft is never listed; the next run removes stale drafts
            raise

    def list(self):
        return sorted(r["tag_name"] for r in self._releases()
                      if not r["draft"] and POINT_NAME.fullmatch(r["tag_name"] or ""))

    def get(self, name, destination):
        _check_point(name)
        matches = [r for r in self._releases() if r["tag_name"] == name and not r["draft"]]
        if len(matches) != 1:
            raise StoreError("backup point not found")
        out = {}
        for asset in sorted(matches[0]["assets"], key=lambda a: a["name"]):
            if not ASSET_NAME.fullmatch(asset["name"]):
                continue
            target = Path(destination) / asset["name"]
            self._download(asset["id"], target)
            out[asset["name"]] = target
        return out

    def delete(self, name):
        _check_point(name)
        for release in self._releases():
            if release["tag_name"] == name:
                self._json("DELETE", f"/releases/{release['id']}")
        try:
            self._json("DELETE", f"/git/refs/tags/{name}", expect=(204,))
        except StoreError:
            pass  # drafts never created the tag

    def remove_stale_drafts(self, older_than_seconds=86400, now=None):
        """Delete drafts left by crashed runs. They were never listed."""
        now = now or time.time()
        removed = []
        for release in self._releases():
            if release["draft"] and POINT_NAME.fullmatch(release["tag_name"] or ""):
                created = calendar.timegm(time.strptime(release["created_at"], "%Y-%m-%dT%H:%M:%SZ"))
                if now - created > older_than_seconds:
                    self._json("DELETE", f"/releases/{release['id']}")
                    removed.append(release["tag_name"])
        return removed
