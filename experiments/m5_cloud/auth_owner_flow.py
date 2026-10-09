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
  recover-v2 hardened recovery order (acceptance F1): needs PFT_M5_SECRET_KEY and a verified
             factor. Keeps two simulated attacker sessions (A1 aal1, A2 aal2) and probes both
             after each step: admin password change -> owner signs in with the new password
             and signs out globally -> admin deletes ALL factors. Then checks that A1 can no
             longer enrol a factor. Afterwards run `flow` again to re-enrol TOTP.
  revocation follow-up to recover-v2 (needs PFT_M5_SECRET_KEY, run while no factor exists):
             U2 does a global sign-out from one session end another? U1 does the admin
             password change end a password-only (aal1) session? U3 can that session still
             enrol a factor afterwards? Afterwards run `flow` to enrol TOTP.
  negatives  wrong password, admin API with the publishable key, and (only if sign-ups are
             disabled) sign-up and anonymous sign-in attempts.

The evidence file must not exist yet, so a rerun never overwrites an earlier attempt.
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


def probe(session):
    """Is this session still usable? /user with its access token, then a refresh.

    A successful refresh replaces the session's tokens so later probes use the newest ones."""
    status, payload = call("GET", "/user", bearer=session["access_token"])
    result = {"user": [status, None if status == 200 else error_label(payload)]}
    status, payload = call("POST", "/token?grant_type=refresh_token",
                           body={"refresh_token": session["refresh_token"]})
    result["refresh"] = [status, None if status == 200 else error_label(payload)]
    if status == 200:
        session.update(access_token=payload["access_token"], refresh_token=payload["refresh_token"])
    return result


def admin_factors(secret, user_id):
    status, listed = call("GET", f"/admin/users/{user_id}/factors", apikey=secret)
    if status == 200 and isinstance(listed, list):
        return status, listed
    status, user = call("GET", f"/admin/users/{user_id}", apikey=secret)
    return status, (user.get("factors") or []) if status == 200 else []


def recover_v2(record):
    secret = os.environ.get("PFT_M5_SECRET_KEY", "")
    if not secret.startswith("sb_secret_"):
        raise SystemExit("Set PFT_M5_SECRET_KEY (synthetic project secret key) in this terminal only.")
    started = time.monotonic()

    def step(name, **values):
        record[name] = {"t_s": round(time.monotonic() - started, 1), **values}

    email = input("Owner email (synthetic project): ").strip()
    current = getpass.getpass("Current owner password: ")
    # Two simulated attacker sessions: A1 stays password-only (aal1), A2 is raised to aal2.
    status_a1, a1 = sign_in(email, current)
    status_a2, a2 = sign_in(email, current)
    record["attacker_sign_in_status"] = [status_a1, status_a2]

    def abort(reason, session):
        # Nothing has been changed yet; end the simulated sessions so none is left behind.
        record["error"] = reason
        record["cleanup_global_sign_out_status"] = call(
            "POST", "/logout?scope=global", bearer=session["access_token"], body={})[0]

    if status_a1 != 200 or status_a2 != 200:
        record["error"] = error_label(a1 if status_a1 != 200 else a2)
        if 200 in (status_a1, status_a2):
            abort(record["error"], a1 if status_a1 == 200 else a2)
        return
    user_id = a1["user"]["id"]
    verifier = OwnerTokenVerifier(AuthConfig(project_ref=REF, owner_sub=user_id))
    _, factor, _ = verified_totp(a2["access_token"])
    if factor is None:
        abort("no verified TOTP factor: run flow first", a1)
        return
    code = getpass.getpass("Current 6-digit TOTP code (raises A2 to aal2): ").strip().replace(" ", "")
    status, challenge = call("POST", f"/factors/{factor['id']}/challenge", bearer=a2["access_token"], body={})
    status, upgraded = call("POST", f"/factors/{factor['id']}/verify", bearer=a2["access_token"],
                            body={"challenge_id": challenge.get("id"), "code": code})
    record["a2_verify_status"] = status
    if status != 200:
        abort(error_label(upgraded), a1)
        return
    a2.update(access_token=upgraded["access_token"], refresh_token=upgraded["refresh_token"])
    record["a1_token_check"] = check(verifier, a1["access_token"])
    record["a2_token_check"] = check(verifier, a2["access_token"])
    step("before", a1=probe(a1), a2=probe(a2))

    new_password = getpass.getpass("New owner password (long, unique): ")
    status, _ = call("PUT", f"/admin/users/{user_id}", apikey=secret, body={"password": new_password})
    step("after_admin_password_change", admin_status=status, old_password_sign_in=sign_in(email, current)[0],
         a1=probe(a1), a2=probe(a2))

    owner_status, owner = sign_in(email, new_password)
    logout_status = None
    if owner_status == 200:
        logout_status = call("POST", "/logout?scope=global", bearer=owner["access_token"], body={})[0]
    step("after_owner_global_sign_out", owner_sign_in=owner_status, logout_status=logout_status,
         a1=probe(a1), a2=probe(a2), owner=probe(owner) if owner_status == 200 else None)

    status, factors = admin_factors(secret, user_id)
    deleted = [[f.get("factor_type"), f.get("status"),
                call("DELETE", f"/admin/users/{user_id}/factors/{f['id']}", apikey=secret)[0]] for f in factors]
    step("after_admin_delete_all_factors", list_status=status, deleted=deleted, a1=probe(a1), a2=probe(a2))

    # F1 attack path: with no verified factor left, can the old aal1 session enrol its own?
    status, enrolled = call("POST", "/factors", bearer=a1["access_token"],
                            body={"factor_type": "totp", "friendly_name": "pft-m5-attacker-" + uuid.uuid4().hex[:8]})
    record["a1_enrol_after_recovery"] = [status, None if status == 200 else error_label(enrolled)]
    if status == 200:
        record["a1_enrolled_factor_cleanup_status"] = call(
            "DELETE", f"/admin/users/{user_id}/factors/{enrolled['id']}", apikey=secret)[0]
    # Documented limit (F2): an unexpired access token still passes stateless verification.
    try:
        claims = verifier.verify("Bearer " + a2["access_token"])
        record["a2_access_token_stateless_after_recovery"] = {
            "accepted": True, "aal": claims.get("aal"), "seconds_until_exp": claims["exp"] - int(time.time())}
    except AuthError as exc:
        record["a2_access_token_stateless_after_recovery"] = {"accepted": False, "status": exc.status,
                                                              "reason": exc.reason}
    # Leave no live session behind if any step failed to revoke one.
    for session in (a2, a1):
        if call("GET", "/user", bearer=session["access_token"])[0] == 200:
            record["cleanup_global_sign_out_status"] = call(
                "POST", "/logout?scope=global", bearer=session["access_token"], body={})[0]
            break
    status, factors = admin_factors(secret, user_id)
    record["factors_after"] = [status, len(factors)]


def revocation(record):
    secret = os.environ.get("PFT_M5_SECRET_KEY", "")
    if not secret.startswith("sb_secret_"):
        raise SystemExit("Set PFT_M5_SECRET_KEY (synthetic project secret key) in this terminal only.")
    email = input("Owner email (synthetic project): ").strip()
    current = getpass.getpass("Current owner password: ")
    # U2: two password-only sessions; one signs out globally, the other is probed.
    status_a, a = sign_in(email, current)
    status_o, o = sign_in(email, current)
    record["u2_sign_in_status"] = [status_a, status_o]
    if status_a != 200 or status_o != 200:
        record["error"] = error_label(a if status_a != 200 else o)
        for status, session in ((status_a, a), (status_o, o)):
            if status == 200:
                record["cleanup_global_sign_out_status"] = call(
                    "POST", "/logout?scope=global", bearer=session["access_token"], body={})[0]
        return
    user_id = a["user"]["id"]
    _, _, factors = verified_totp(a["access_token"])
    record["totp_factors_before"] = len(factors)
    record["u2_other_session_before"] = probe(a)
    record["u2_global_sign_out_status"] = call("POST", "/logout?scope=global", bearer=o["access_token"], body={})[0]
    record["u2_other_session_after"] = probe(a)
    record["u2_signing_session_after"] = probe(o)
    # U1: a fresh password-only session, then the admin password change.
    status, a1 = sign_in(email, current)
    record["u1_sign_in_status"] = status
    if status != 200:
        record["error"] = error_label(a1)
        return
    record["u1_before"] = probe(a1)
    new_password = getpass.getpass("New owner password (long, unique): ")
    record["u1_admin_password_change_status"] = call(
        "PUT", f"/admin/users/{user_id}", apikey=secret, body={"password": new_password})[0]
    record["u1_after_password_change"] = probe(a1)
    # U3: no verified factor exists, so a surviving session could enrol one (the F1 path).
    status, enrolled = call("POST", "/factors", bearer=a1["access_token"],
                            body={"factor_type": "totp", "friendly_name": "pft-m5-attacker-" + uuid.uuid4().hex[:8]})
    record["u3_enrol_attempt"] = [status, None if status == 200 else error_label(enrolled)]
    if status == 200:
        record["u3_cleanup_delete_status"] = call(
            "DELETE", f"/admin/users/{user_id}/factors/{enrolled['id']}", apikey=secret)[0]
    record["old_password_sign_in_status"] = sign_in(email, current)[0]
    status, owner = sign_in(email, new_password)
    record["new_password_sign_in_status"] = status
    # Leave no live session behind: any probe session that survived, then the owner's own.
    for name, session in (("u2_other", a), ("a1", a1), ("owner", owner if status == 200 else None)):
        if session and call("GET", "/user", bearer=session["access_token"])[0] == 200:
            record[f"cleanup_{name}_global_sign_out_status"] = call(
                "POST", "/logout?scope=global", bearer=session["access_token"], body={})[0]
    status, factors = admin_factors(secret, user_id)
    record["factors_after"] = [status, len(factors)]


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
    parser.add_argument("command", choices=["flow", "recover", "recover-v2", "revocation", "negatives"])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if not sys.stdin.isatty():
        raise SystemExit("Run this in your own terminal, not through an agent.")
    if os.path.exists(args.out):
        raise SystemExit(f"{args.out} already exists; choose a new file name so earlier evidence is kept.")
    record = {"kind": "m5_owner_auth_" + args.command, "project_ref": REF,
              "started_unix": int(time.time())}
    try:
        {"flow": flow, "recover": recover, "recover-v2": recover_v2, "revocation": revocation,
         "negatives": negatives}[args.command](record)
    finally:
        with open(args.out, "w") as stream:
            json.dump(record, stream, indent=2)
        print(json.dumps(record, indent=2))
