"""M5 owner-auth feasibility: Supabase access-token verification (Auth design §6, P3-2 = PyJWT).

Feasibility prototype only, not the M6 integration: nothing here is mounted in
api.main. Rules:
- keys only from the configured JWKS URL; jku/x5u/jwk headers are never used;
- ES256 only (HS256, none, RS256, ES384 are rejected before key lookup);
- unknown kid: refetch the JWKS at most once per 60 s, then fail closed;
- iss, aud=authenticated, exp, iat required (leeway 30 s), nbf honoured;
- sub must equal the configured owner subject, aal must be aal2 and
  is_anonymous must be present and false.
Status 401 means "not a valid token"; 403 means "valid token, not the owner
or not aal2".

CLI (read-only, public endpoint): python -m experiments.m5_cloud.auth_probe jwks --project-ref REF
"""
from dataclasses import dataclass
import json
import sys
import threading
import time
import urllib.request

import jwt

ALGORITHM = "ES256"
REFETCH_SECONDS = 60
LEEWAY_SECONDS = 30


class AuthError(Exception):
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status = status
        self.reason = reason


@dataclass(frozen=True)
class AuthConfig:
    project_ref: str
    owner_sub: str

    @property
    def issuer(self):
        return f"https://{self.project_ref}.supabase.co/auth/v1"

    @property
    def jwks_url(self):
        return self.issuer + "/.well-known/jwks.json"


def fetch_jwks(url, timeout=10):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}),
                                timeout=timeout) as response:
        return json.loads(response.read())


class OwnerTokenVerifier:
    def __init__(self, config, *, fetch=fetch_jwks, clock=time.monotonic):
        self.config = config
        self._fetch = fetch
        self._clock = clock
        self._keys = {}
        self._fetched_at = None
        self._fetch_failed = False
        self._lock = threading.Lock()
        self.fetches = 0

    def _refresh(self):
        self.fetches += 1
        self._fetched_at = self._clock()
        try:
            keys = {}
            for entry in self._fetch(self.config.jwks_url).get("keys", []):
                # Only P-256 signing keys can verify ES256; anything else is ignored.
                if entry.get("kty") == "EC" and entry.get("crv") == "P-256" and entry.get("alg", ALGORITHM) == ALGORITHM \
                        and entry.get("use", "sig") == "sig" and isinstance(entry.get("kid"), str):
                    keys[entry["kid"]] = jwt.PyJWK(entry, algorithm=ALGORITHM).key
        except Exception:
            # Preserve usable cached keys, but do not mislabel an outage as a bad token.
            self._fetch_failed = True
            raise AuthError(503, "auth keys unavailable") from None
        self._keys = keys
        self._fetch_failed = False

    def _key(self, kid):
        # Callers run in worker threads: one lock covers check, refresh and lookup, so a caller
        # never sees the refetch throttle already set over a key cache that is still empty.
        with self._lock:
            if kid not in self._keys and (self._fetched_at is None
                                          or self._clock() - self._fetched_at >= REFETCH_SECONDS):
                self._refresh()
            if kid not in self._keys:
                if self._fetch_failed:
                    raise AuthError(503, "auth keys unavailable")
                raise AuthError(401, "unknown signing key")
            return self._keys[kid]

    def verify(self, authorization):
        if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
            raise AuthError(401, "bearer token required")
        token = authorization.removeprefix("Bearer ").strip()
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise AuthError(401, "malformed token") from None
        if header.get("alg") != ALGORITHM:
            raise AuthError(401, "algorithm rejected")
        kid = header.get("kid")
        if not isinstance(kid, str):
            raise AuthError(401, "key id required")
        key = self._key(kid)
        try:
            claims = jwt.decode(token, key, algorithms=[ALGORITHM], audience="authenticated",
                                issuer=self.config.issuer, leeway=LEEWAY_SECONDS,
                                options={"require": ["exp", "iat", "iss", "aud", "sub"]})
        except jwt.PyJWTError as exc:
            raise AuthError(401, type(exc).__name__) from None
        if claims["sub"] != self.config.owner_sub:
            raise AuthError(403, "not the owner")
        if claims.get("is_anonymous") is not False:
            raise AuthError(403, "anonymous or unknown session")
        if claims.get("aal") != "aal2":
            raise AuthError(403, "aal2 required")
        return claims


def describe_jwks(project_ref):
    config = AuthConfig(project_ref=project_ref, owner_sub="unused")
    keys = fetch_jwks(config.jwks_url).get("keys", [])
    summary = [{name: key.get(name) for name in ("kid", "kty", "crv", "alg", "use")} for key in keys]
    return {"kind": "m5_auth_jwks", "jwks_url": config.jwks_url, "keys": summary,
            "all_es256_p256": bool(keys) and all(k.get("kty") == "EC" and k.get("crv") == "P-256"
                                                 and k.get("alg") == ALGORITHM for k in keys),
            "symmetric_keys_published": any(k.get("kty") == "oct" for k in keys)}


if __name__ == "__main__":
    if sys.argv[1:2] == ["jwks"] and sys.argv[2:3] == ["--project-ref"]:
        print(json.dumps(describe_jwks(sys.argv[3]), indent=2))
    else:
        raise SystemExit(__doc__)
