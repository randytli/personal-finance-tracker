"""M5 owner-auth probe: deployed negative matrix, A5 samples and cleanup (design §5.2–§5.3).

Run by the OWNER in their own terminal, never through an agent. Refuses non-TTY stdin and an
existing --out file. Secrets (Vercel bypass value, password, TOTP codes, the synthetic sb_secret
key) are read with getpass and stay in memory; the evidence records statuses, error labels,
request IDs, counters and timings, never tokens.

  python -m experiments.m5_cloud.auth_api_matrix matrix  --api-url URL --wrong-owner-url URL --out FILE
  python -m experiments.m5_cloud.auth_api_matrix samples --api-url URL --auth-url URL --out FILE
  python -m experiments.m5_cloud.auth_api_matrix cleanup --out FILE
"""
import argparse
import base64
import getpass
import json
import math
import os
import re
import secrets
import statistics
import sys
import time
import uuid

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec

REF = "acyghoemtdrilsdszolq"
AUTH = f"https://{REF}.supabase.co/auth/v1"
PUBLISHABLE = "sb_publishable_cBTZ7SPZICiMJd1_YTRpkQ_qR7MwzPg"  # Public by design.
API_HOST_PREFIX = "pft-m5-auth-api-20261009-"
PREVIEW_URL_RE = re.compile(
    rf"https://{re.escape(API_HOST_PREFIX)}[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.vercel\.app/?")
NONOWNER_PREFIX, NONOWNER_DOMAIN = "m5-nonowner-", "@example.invalid"
PROBE_HEADERS = ("x-probe-request-id", "x-probe-instance", "x-probe-db-connections",
                 "x-probe-session-checks", "x-probe-data-queries")
BODY_FIELDS = ("aal", "session_check", "identity_ok", "seconds_until_exp", "timings_ms")


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def claims_of(token):
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def forged(real_token):
    """Tokens that differ from a real one only in algorithm, key or signature (cases D3-D8)."""
    header, payload, signature = real_token.split(".")
    claims, kid = claims_of(real_token), jwt.get_unverified_header(real_token)["kid"]
    local = ec.generate_private_key(ec.SECP256R1())
    tampered = b64(json.dumps({**claims, "exp": claims["exp"] + 1}).encode())
    none_header = b64(json.dumps({"alg": "none", "typ": "JWT", "kid": kid}).encode())
    return {
        "D3_malformed": "not-a-jwt",
        "D4_alg_none": f"{none_header}.{payload}.",
        "D5_hs256": jwt.encode(claims, secrets.token_bytes(32), algorithm="HS256", headers={"kid": kid}),
        "D6_unknown_kid": jwt.encode(claims, local, algorithm="ES256",
                                     headers={"kid": "m5-local-" + uuid.uuid4().hex}),
        "D7_forged_signature": jwt.encode(claims, local, algorithm="ES256", headers={"kid": kid}),
        "D8_tampered_payload": f"{header}.{tampered}.{signature}",
    }


def record(response, started=None):
    try:
        body = response.json()
    except ValueError:
        body = None
    body = body if isinstance(body, dict) else {}
    entry = {"status": response.status_code,
             "error": body.get("error") if isinstance(body.get("error"), str) else None}
    for name in PROBE_HEADERS:
        entry[name.removeprefix("x-probe-").replace("-", "_")] = response.headers.get(name)
    for name in BODY_FIELDS:
        if name in body:
            entry[name] = body[name]
    if started is not None:
        entry["client_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return entry


def is_temporary(email):
    return (isinstance(email, str) and email.startswith(NONOWNER_PREFIX) and email.endswith(NONOWNER_DOMAIN)
            and len(email) == len(NONOWNER_PREFIX) + 12 + len(NONOWNER_DOMAIN))


def _stats(values):
    values = sorted(values)
    if not values:
        return None
    return {"n": len(values), "p50": statistics.median(values),
            "p95": values[math.ceil(0.95 * len(values)) - 1], "max": values[-1]}


def summarize(runs):
    ok = [run for run in runs if run["status"] == 200]
    return {"n": len(runs), "non_200": len(runs) - len(ok),
            "status_429": sum(run["status"] == 429 for run in runs),
            "client_ms": _stats([run["client_ms"] for run in ok]),
            **{f"{name}_ms": _stats([run["timings_ms"][name] for run in ok])
               for name in ("total", "connect", "session_check", "data")},
            "note": "p95 of about 30 samples is a sample statistic, not a stable tail estimate"}


class TerminalIO:
    def secret(self, prompt):
        return getpass.getpass(prompt)

    def ask(self, prompt):
        return input(prompt)

    def code(self, prompt="Current 6-digit TOTP code: "):
        return getpass.getpass(prompt).strip().replace(" ", "")

    def tty(self, text):
        with open("/dev/tty", "w") as stream:
            stream.write(text + "\n")

    def sleep(self, seconds):
        time.sleep(seconds)


class Supabase:
    def __init__(self, client):
        self.client = client

    def call(self, method, path, *, bearer=None, apikey=PUBLISHABLE, body=None):
        headers = {"apikey": apikey}
        if bearer:
            headers["Authorization"] = "Bearer " + bearer
        response = self.client.request(method, AUTH + path, headers=headers, json=body)
        try:
            data = response.json()
        except ValueError:
            data = {}
        return response.status_code, data

    def sign_in(self, email, password):
        return self.call("POST", "/token?grant_type=password", body={"email": email, "password": password})

    def refresh(self, refresh_token):
        return self.call("POST", "/token?grant_type=refresh_token", body={"refresh_token": refresh_token})

    def logout(self, access):
        return self.call("POST", "/logout?scope=global", bearer=access, body={})[0]

    def owner_session(self, email, password, io):
        status, session = self.sign_in(email, password)
        if status != 200:
            raise SystemExit(f"owner sign-in failed: {status}")
        _, user = self.call("GET", "/user", bearer=session["access_token"])
        factor = next((f for f in user.get("factors") or []
                       if f.get("factor_type") == "totp" and f.get("status") == "verified"), None)
        if factor is None:
            raise SystemExit("no verified TOTP factor: run auth_owner_flow flow first")
        code = io.code()
        _, challenge = self.call("POST", f"/factors/{factor['id']}/challenge",
                                 bearer=session["access_token"], body={})
        status, upgraded = self.call("POST", f"/factors/{factor['id']}/verify", bearer=session["access_token"],
                                     body={"challenge_id": challenge.get("id"), "code": code})
        if status != 200:
            raise SystemExit(f"TOTP verify failed: {status}")
        return upgraded


class Api:
    def __init__(self, client, bypass):
        self.client, self.bypass = client, bypass

    def get(self, base, path="/probe/whoami", authorization=None):
        headers = {"x-vercel-protection-bypass": self.bypass}
        if authorization is not None:
            headers["authorization"] = authorization
        started = time.perf_counter()
        return record(self.client.get(base.rstrip("/") + path, headers=headers), started)


def _revocation(api, url, bearer, revoke):
    before = api.get(url, authorization=bearer)
    action = revoke()
    after = api.get(url, authorization=bearer)
    valid = before["status"] == 200 and (before.get("seconds_until_exp") or 0) > 120
    return {"before": before, "after": after, "valid_procedure": valid}, action


def matrix(evidence, args, io, client):
    bypass = io.secret("Vercel automation-bypass value for the API project: ")
    secret_key = io.secret("Synthetic project sb_secret key: ")
    if not secret_key.startswith("sb_secret_"):
        raise SystemExit("sb_secret key required")
    email = io.ask("Owner email (synthetic project): ").strip()
    password = io.secret("Current owner password: ")
    supabase, api = Supabase(client), Api(client, bypass)
    cases = evidence["cases"] = {}
    evidence["ping"] = {"api": api.get(args.api_url, "/probe/ping"),
                        "wrong_owner": api.get(args.wrong_owner_url, "/probe/ping")}
    # D9 first: an aal1 session is revoked as soon as another session completes MFA (F5).
    status, aal1 = supabase.sign_in(email, password)
    if status != 200:
        raise SystemExit(f"owner sign-in failed: {status}")
    cases["D9_owner_aal1"] = api.get(args.api_url, authorization="Bearer " + aal1["access_token"])
    nonowner, temp_password = NONOWNER_PREFIX + uuid.uuid4().hex[:12] + NONOWNER_DOMAIN, secrets.token_urlsafe(24)
    status, created = supabase.call("POST", "/admin/users", apikey=secret_key,
                                    body={"email": nonowner, "password": temp_password, "email_confirm": True})
    evidence["nonowner_create_status"] = status
    try:
        status, other = supabase.sign_in(nonowner, temp_password)
        cases["D10_non_owner"] = (api.get(args.api_url, authorization="Bearer " + other["access_token"])
                                  if status == 200 else {"status": None, "error": f"non-owner sign-in {status}"})
    finally:
        if isinstance(created, dict) and created.get("id"):
            evidence["nonowner_delete_status"] = supabase.call(
                "DELETE", f"/admin/users/{created['id']}", apikey=secret_key)[0]
    t2 = supabase.owner_session(email, password, io)
    bearer = "Bearer " + t2["access_token"]
    cases["D1_no_authorization"] = api.get(args.api_url)
    cases["D2_non_bearer"] = api.get(args.api_url, authorization="Basic " + b64(b"owner:x"))
    for name, token in forged(t2["access_token"]).items():
        cases[name] = api.get(args.api_url, authorization="Bearer " + token)
    cases["D15_unknown_path"] = api.get(args.api_url, "/probe/nope", authorization=bearer)
    cases["D11_owner_aal2"] = api.get(args.api_url, authorization=bearer)
    case, status = _revocation(api, args.api_url, bearer, lambda: supabase.logout(t2["access_token"]))
    cases["D12_after_sign_out"] = {**case, "sign_out_status": status}
    t3 = supabase.owner_session(email, password, io)
    new_password = io.secret("NEW owner password (long, unique; store it now): ")
    user_id = claims_of(t3["access_token"])["sub"]
    case, status = _revocation(api, args.api_url, "Bearer " + t3["access_token"], lambda: supabase.call(
        "PUT", f"/admin/users/{user_id}", apikey=secret_key, body={"password": new_password})[0])
    cases["D13_after_password_change"] = {**case, "password_change_status": status}
    t4 = supabase.owner_session(email, new_password, io)
    bearer4 = "Bearer " + t4["access_token"]
    cases["D16_wrong_owner_deployment"] = api.get(args.wrong_owner_url, authorization=bearer4)
    wait = claims_of(t4["access_token"])["exp"] + 35 - time.time()
    io.tty(f"Waiting {max(0, int(wait))} s for natural expiry (D14)...")
    io.sleep(max(0.0, wait))
    cases["D14_expired"] = api.get(args.api_url, authorization=bearer4)
    status, refreshed = supabase.refresh(t4["refresh_token"])
    evidence["final_sign_out_status"] = (supabase.logout(refreshed["access_token"]) if status == 200
                                         else f"refresh {status}")


def samples(evidence, args, io, client, count=30):
    bypass = io.secret("Vercel automation-bypass value for the API project: ")
    email = io.ask("Owner email (synthetic project): ").strip()
    password = io.secret("Current owner password: ")
    supabase, api = Supabase(client), Api(client, bypass)
    session = supabase.owner_session(email, password, io)
    bearer = "Bearer " + session["access_token"]
    for mode, url in (("db", args.api_url), ("auth", args.auth_url)):
        runs = [api.get(url, authorization=bearer) for _ in range(count + 1)]
        evidence[mode] = {"first": runs[0], "warm": runs[1:], "summary": summarize(runs[1:])}
    evidence["sign_out_status"] = supabase.logout(session["access_token"])


def cleanup(evidence, args, io, client):
    secret_key = io.secret("Synthetic project sb_secret key: ")
    if not secret_key.startswith("sb_secret_"):
        raise SystemExit("sb_secret key required")
    supabase = Supabase(client)
    status, listed = supabase.call("GET", "/admin/users?page=1&per_page=1000", apikey=secret_key)
    users = listed.get("users", []) if isinstance(listed, dict) else []
    doomed = [user for user in users if is_temporary(user.get("email"))]
    evidence["list_status"] = status
    evidence["deleted"] = [supabase.call("DELETE", f"/admin/users/{user['id']}", apikey=secret_key)[0]
                           for user in doomed]
    evidence["remaining_users"] = len(users) - len(doomed)


COMMANDS = {"matrix": (matrix, ("api_url", "wrong_owner_url")),
            "samples": (samples, ("api_url", "auth_url")),
            "cleanup": (cleanup, ())}


def main(argv=None, io=None, client=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--api-url")
    parser.add_argument("--wrong-owner-url")
    parser.add_argument("--auth-url")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if not sys.stdin.isatty():
        raise SystemExit("Run this in your own terminal, not through an agent.")
    if os.path.exists(args.out):
        raise SystemExit(f"{args.out} already exists; choose a new file name so earlier evidence is kept.")
    command, required = COMMANDS[args.command]
    for name in required:
        # Match the original input so normalization cannot hide ports or path components.
        if not PREVIEW_URL_RE.fullmatch(getattr(args, name) or ""):
            raise SystemExit(f"--{name.replace('_', '-')} must be an https preview URL of pft-m5-auth-api-20261009")
    evidence = {"kind": "m5_auth_probe_" + args.command, "project_ref": REF, "started_unix": int(time.time())}
    try:
        with (client or httpx.Client(timeout=20.0)) as http:
            command(evidence, args, io or TerminalIO(), http)
    finally:
        with open(args.out, "w") as stream:
            json.dump(evidence, stream, indent=2)
        print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
