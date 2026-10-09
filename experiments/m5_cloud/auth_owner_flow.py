"""M5 owner-auth feasibility on the synthetic project, run by the OWNER in their own terminal.

Never run this through an agent chat: it refuses to start unless stdin is a TTY,
writes the TOTP enrolment secret only to /dev/tty, and records only status codes,
claim names and booleans in the evidence file (no tokens, passwords or secrets).

Subcommands (python -m experiments.m5_cloud.auth_owner_flow <cmd> --out FILE):
  flow       password sign-in (aal1 must be refused) -> TOTP enrol or verify (a wrong code on a
             fresh challenge must be refused) -> aal2 accepted -> refresh -> global sign-out
             -> old refresh token refused
  recover    trusted-machine recovery (P3-3): needs PFT_M5_SECRET_KEY in the environment.
             Signs in, deletes the TOTP factor with the admin API, checks the session is gone,
             sets a new password, checks old password refused and new one accepted.
             Afterwards run `flow` again to re-enrol TOTP.
  negatives  wrong password, admin API with the publishable key, and (only if sign-ups are
             disabled) sign-up and anonymous sign-in attempts.
"""
import argparse
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

from experiments.m5_cloud.auth_probe import AuthConfig, AuthError, OwnerTokenVerifier

REF = "acyghoemtdrilsdszolq"
BASE = f"https://{REF}.supabase.co/auth/v1"
PUBLISHABLE = "sb_publishable_cBTZ7SPZICiMJd1_YTRpkQ_qR7MwzPg"  # Public by design.


def call(method, path, *, body=None, bearer=None, apikey=PUBLISHABLE):
    headers = {"apikey": apikey, "Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    request = urllib.request.Request(BASE + path, method=method, headers=headers,
                                     data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, {}


def error_label(payload):
    return payload.get("error_code") or payload.get("code") or payload.get("error") or payload.get("msg")


def tty(text):
    with open("/dev/tty", "w") as stream:
        stream.write(text + "\n")


def check(verifier, token):
    try:
        claims = verifier.verify("Bearer " + token)
        return {"accepted": True, "aal": claims.get("aal"), "lifetime_s": claims["exp"] - claims["iat"],
                "claim_names": sorted(claims)}
    except AuthError as exc:
        return {"accepted": False, "status": exc.status, "reason": exc.reason}


def sign_in(email, password):
    return call("POST", "/token?grant_type=password", body={"email": email, "password": password})


def verified_totp(token):
    status, user = call("GET", "/user", bearer=token)
    factors = [f for f in user.get("factors") or [] if f.get("factor_type") == "totp"]
    return user.get("id"), next((f for f in factors if f.get("status") == "verified"), None), factors


def flow(record):
    email = input("Owner email (synthetic project): ").strip()
    status, session = sign_in(email, getpass.getpass("Owner password: "))
    record["password_sign_in_status"] = status
    if status != 200:
        record["error"] = error_label(session)
        return
    owner_sub = session["user"]["id"]
    verifier = OwnerTokenVerifier(AuthConfig(project_ref=REF, owner_sub=owner_sub))
    record["aal1_token_check"] = check(verifier, session["access_token"])
    _, factor, factors = verified_totp(session["access_token"])
    record["totp_factors_before"] = len(factors)
    if factor is None:
        status, enrolled = call("POST", "/factors", bearer=session["access_token"],
                                body={"factor_type": "totp", "friendly_name": "pft-m5-" + uuid.uuid4().hex[:8]})
        record["enroll_status"] = status
        if status != 200:
            record["error"] = error_label(enrolled)
            return
        tty("\nAdd this TOTP secret to your authenticator (shown only here):\n  "
            + enrolled["totp"]["uri"] + "\n")
        factor = {"id": enrolled["id"]}
    # Read the code before creating any challenge: a slow authenticator setup expired the
    # challenge in the first 2026-10-08 attempt (mfa_challenge_expired).
    code = getpass.getpass("Current 6-digit TOTP code: ").strip().replace(" ", "")
    wrong_code = f"{(int(code) + 500000) % 1000000:06d}" if code.isdigit() else "000000"
    status, challenge = call("POST", f"/factors/{factor['id']}/challenge", bearer=session["access_token"], body={})
    status, wrong = call("POST", f"/factors/{factor['id']}/verify", bearer=session["access_token"],
                         body={"challenge_id": challenge.get("id"), "code": wrong_code})
    record["fresh_challenge_wrong_code_status"] = [status, error_label(wrong)]
    status, challenge = call("POST", f"/factors/{factor['id']}/challenge", bearer=session["access_token"], body={})
    record["challenge_status"] = status
    status, upgraded = call("POST", f"/factors/{factor['id']}/verify", bearer=session["access_token"],
                            body={"challenge_id": challenge.get("id"), "code": code})
    record["verify_status"] = status
    if status != 200:
        record["error"] = error_label(upgraded)
        return
    record["aal2_token_check"] = check(verifier, upgraded["access_token"])
    status, wrong = call("POST", f"/factors/{factor['id']}/verify", bearer=session["access_token"],
                         body={"challenge_id": challenge.get("id"), "code": "000000"})
    record["reused_challenge_wrong_code_status"] = [status, error_label(wrong)]
    status, refreshed = call("POST", "/token?grant_type=refresh_token",
                             body={"refresh_token": upgraded["refresh_token"]})
    record["refresh_status"] = status
    record["refreshed_token_check"] = check(verifier, refreshed["access_token"]) if status == 200 else None
    old_refresh = upgraded["refresh_token"]
    status, _ = call("POST", "/token?grant_type=refresh_token", body={"refresh_token": old_refresh})
    record["rotated_refresh_token_reuse_status"] = status
    access = refreshed.get("access_token", upgraded["access_token"])
    status, _ = call("POST", "/logout?scope=global", bearer=access, body={})
    record["logout_status"] = status
    status, payload = call("POST", "/token?grant_type=refresh_token",
                           body={"refresh_token": refreshed.get("refresh_token", old_refresh)})
    record["refresh_after_logout"] = [status, error_label(payload)]
    status, payload = call("GET", "/user", bearer=access)
    record["get_user_with_old_access_token_after_logout"] = [status, error_label(payload)]
    # Stateless verification still accepts an unexpired access token after sign-out (documented).
    record["stateless_check_of_old_access_token_after_logout"] = check(verifier, access)


def recover(record):
    secret = os.environ.get("PFT_M5_SECRET_KEY", "")
    if not secret.startswith("sb_secret_"):
        raise SystemExit("Set PFT_M5_SECRET_KEY (synthetic project secret key) in this terminal only.")
    email = input("Owner email (synthetic project): ").strip()
    status, session = sign_in(email, getpass.getpass("Current owner password: "))
    record["password_sign_in_status"] = status
    if status != 200:
        record["error"] = error_label(session)
        return
    user_id = session["user"]["id"]
    _, factor, factors = verified_totp(session["access_token"])
    record["verified_totp_before"] = factor is not None
    if factor is not None:
        status, _ = call("DELETE", f"/admin/users/{user_id}/factors/{factor['id']}", apikey=secret)
        record["admin_delete_factor_status"] = status
        status, payload = call("POST", "/token?grant_type=refresh_token",
                               body={"refresh_token": session["refresh_token"]})
        record["refresh_after_factor_deletion"] = [status, error_label(payload)]
    new_password = getpass.getpass("New owner password (long, unique): ")
    old_password = getpass.getpass("Repeat the CURRENT password to prove it is refused afterwards: ")
    status, _ = call("PUT", f"/admin/users/{user_id}", apikey=secret, body={"password": new_password})
    record["admin_set_password_status"] = status
    record["old_password_sign_in_status"] = sign_in(email, old_password)[0]
    status, payload = sign_in(email, new_password)
    record["new_password_sign_in_status"] = status
    if status == 200:
        _, factor, _ = verified_totp(payload["access_token"])
        record["verified_totp_after"] = factor is not None
        call("POST", "/logout?scope=global", bearer=payload["access_token"], body={})


def negatives(record):
    status, settings = call("GET", "/settings")
    record["settings"] = {"disable_signup": settings.get("disable_signup"),
                          "anonymous_users": (settings.get("external") or {}).get("anonymous_users")}
    email = input("Owner email (synthetic project): ").strip()
    status, payload = sign_in(email, "wrong-" + uuid.uuid4().hex)
    record["wrong_password"] = [status, error_label(payload)]
    status, payload = call("GET", "/admin/users")
    record["admin_api_with_publishable_key"] = [status, error_label(payload)]
    if settings.get("disable_signup") is True:
        status, payload = call("POST", "/signup", body={"email": f"m5-{uuid.uuid4().hex[:8]}@example.com",
                                                        "password": uuid.uuid4().hex + "Aa1!"})
        record["signup_attempt"] = [status, error_label(payload)]
        status, payload = call("POST", "/signup", body={})
        record["anonymous_sign_in_attempt"] = [status, error_label(payload)]
    else:
        record["signup_attempt"] = "skipped: sign-ups are still enabled (would create a user)"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["flow", "recover", "negatives"])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if not sys.stdin.isatty():
        raise SystemExit("Run this in your own terminal, not through an agent.")
    record = {"kind": "m5_owner_auth_" + args.command, "project_ref": REF,
              "started_unix": int(time.time())}
    try:
        {"flow": flow, "recover": recover, "negatives": negatives}[args.command](record)
    finally:
        with open(args.out, "w") as stream:
            json.dump(record, stream, indent=2)
        print(json.dumps(record, indent=2))
