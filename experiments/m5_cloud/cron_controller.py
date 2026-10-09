"""M5 cron acceptance: authentication negatives against the deployed preview (synthetic only).

Signs locally with the private HMAC key and sends the private automation-bypass
header; neither value is printed. Prints status codes and response error labels.

Usage: python -m experiments.m5_cloud.cron_controller --private DIR --url https://...vercel.app/trigger
"""
import argparse
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid

from api import trigger_auth

AUDIENCE = "pft-jobs-m5-synthetic"
BODY = b'{"kind":"tick"}'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def send(url, headers, body=BODY):
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "x-pft-delivery-source": "controller", **headers})
    started = time.perf_counter()
    try:
        with opener.open(request, timeout=60) as response:
            status, payload = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, payload = error.code, error.read()
    try:
        parsed = json.loads(payload)
        label = parsed.get("error") or parsed.get("status")
    except ValueError:
        label = "non-json"
    return {"status": status, "label": label, "client_s": round(time.perf_counter() - started, 3)}


def signature(key, *, audience=AUDIENCE, ts=None, path="/trigger"):
    return trigger_auth.sign(key, audience=audience, key_id="v1", timestamp=ts or int(time.time()),
                             nonce=uuid.uuid4().hex, method="POST", path=path, payload={"kind": "tick"})


def run(private, url):
    key = (private / "m5_trigger_key_v1").read_text().strip().encode()
    bypass = {"x-vercel-protection-bypass": (private / "m5_vercel_bypass").read_text().strip()}
    header = trigger_auth.HEADER
    valid = signature(key)
    cases = [
        ("no_signature", bypass),
        ("wrong_secret", {**bypass, header: signature(b"w" * 64)}),
        ("wrong_audience", {**bypass, header: signature(key, audience="pft-jobs-production")}),
        ("stale_timestamp", {**bypass, header: signature(key, ts=int(time.time()) - 400)}),
        ("no_bypass_valid_signature", {header: signature(key)}),
        ("valid", {**bypass, header: valid}),
        ("replay_of_valid", {**bypass, header: valid}),
    ]
    results = [{"case": name, **send(url, headers)} for name, headers in cases]
    results.append({"case": "tampered_body", **send(url, {**bypass, header: signature(key)},
                                                     body=b'{"kind":"backup"}')})
    return {"kind": "m5_cron_auth_negatives", "url": url, "results": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.private, args.url), indent=2))
