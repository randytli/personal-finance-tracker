"""Offline tests for the owner-run M5 auth probe script (design §5.2–§5.3, Review Focus 5).

The end-to-end test drives the real script against fakes of Supabase Auth and the probe API;
the evidence must hold no token, password or secret.
"""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch
import uuid

import httpx
import jwt

from experiments.m5_cloud import auth_api_matrix as script
from experiments.m5_cloud.auth_api_probe import Settings, create_app
from experiments.m5_cloud.auth_probe import AuthConfig, AuthError, OwnerTokenVerifier
from tests.m5_auth_support import OWNER, REF, FakeEngine, asgi_client, ec_key, mint, public_jwk

API_HOST = "pft-m5-auth-api-20261009-db-pft2.vercel.app"
AUTH_HOST = "pft-m5-auth-api-20261009-auth-pft2.vercel.app"
WRONG_HOST = "pft-m5-auth-api-20261009-wrong-pft2.vercel.app"
BYPASS = "b" * 32
SECRET = "sb_secret_fake"
OWNER_EMAIL = "owner@example.invalid"


class ForgedTokenTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.key = ec_key()
        self.verifier = OwnerTokenVerifier(AuthConfig(project_ref=REF, owner_sub=OWNER),
                                           fetch=lambda url: {"keys": [public_jwk(self.key, "kid-1")]})
        self.real = mint(self.key)

    def test_each_forgery_fails_for_its_intended_reason(self):
        expected = {"D3_malformed": "malformed token", "D4_alg_none": "algorithm rejected",
                    "D5_hs256": "algorithm rejected", "D6_unknown_kid": "unknown signing key",
                    "D7_forged_signature": "InvalidSignatureError",
                    "D8_tampered_payload": "InvalidSignatureError"}
        forged = script.forged(self.real)
        self.assertEqual(set(forged), set(expected))
        for name, token in forged.items():
            with self.subTest(name):
                with self.assertRaises(AuthError) as caught:
                    self.verifier.verify("Bearer " + token)
                self.assertEqual((caught.exception.status, caught.exception.reason), (401, expected[name]))

    async def test_forgeries_against_the_local_app_never_reach_the_database(self):
        engine = FakeEngine()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as http:
            app = create_app(Settings(REF, OWNER, "postgresql+asyncpg://unused", "db", "sb_publishable_test"),
                             verifier=self.verifier, engine=engine, http=http, instance="local")
            async with asgi_client(app) as client:
                for name, token in script.forged(self.real).items():
                    with self.subTest(name):
                        response = await client.get("/probe/whoami", headers={"authorization": "Bearer " + token})
                        self.assertEqual(response.status_code, 401)
        self.assertEqual(engine.connections, [])


class HelperTests(unittest.TestCase):
    def test_record_keeps_only_non_secret_fields(self):
        response = httpx.Response(200, json={"aal": "aal2", "access_token": "x" * 40, "seconds_until_exp": 200},
                                  headers={"x-probe-request-id": "r1", "set-cookie": "a=b"})
        entry = script.record(response)
        self.assertEqual(entry["status"], 200)
        self.assertEqual(entry["request_id"], "r1")
        self.assertNotIn("x" * 40, json.dumps(entry))

    def test_is_temporary_matches_only_script_users(self):
        self.assertTrue(script.is_temporary("m5-nonowner-0123456789ab@example.invalid"))
        for email in ("owner@example.invalid", "m5-nonowner-0123456789ab@example.com",
                      "m5-nonowner-short@example.invalid", None, "x-m5-nonowner-0123456789ab@example.invalid"):
            with self.subTest(email):
                self.assertFalse(script.is_temporary(email))

    def test_summarize_reports_sample_statistics_and_criteria(self):
        good = {"status": 200, "error": None,
                "timings_ms": {"total": 1.0, "connect": 1.0, "session_check": 2.0, "data": 1.0}}
        runs = [{**good, "class": "cold_candidate", "client_ms": 99.0},
                *({**good, "class": "warm", "client_ms": float(i)} for i in range(1, 31))]
        summary = script.summarize(runs)
        self.assertEqual((summary["n"], summary["warm"], summary["cold_candidates"]), (31, 30, 1))
        self.assertEqual(summary["warm_ms"]["client_ms"]["p95"], 29.0)
        self.assertEqual(summary["cold_candidate_ms"]["client_ms"]["max"], 99.0)
        self.assertTrue(summary["criteria_met"])
        self.assertIn("sample statistic", summary["note"])
        summary = script.summarize(runs + [{"status": 429, "error": None, "class": "warm", "client_ms": 1.0}])
        self.assertEqual(summary["status_429"], 1)
        self.assertFalse(summary["criteria"]["no_status_429"])
        self.assertFalse(summary["criteria_met"])


class FakeIO:
    def __init__(self, cloud):
        self.cloud = cloud
        self.lines = []

    def secret(self, prompt):
        for marker, value in (("bypass", BYPASS), ("sb_secret", SECRET),
                              ("NEW owner password", "new-password"), ("owner password", "old-password")):
            if marker in prompt:
                return value
        raise AssertionError(prompt)

    def ask(self, prompt):
        return OWNER_EMAIL

    def code(self, prompt=""):
        return "123456"

    def tty(self, text):
        self.lines.append(text)

    def sleep(self, seconds):
        self.cloud.offset += seconds


class FakeCloud:
    """Supabase Auth on the project host and the probe API on preview hosts, in memory."""

    def __init__(self):
        self.key = ec_key()
        self.offset = 0.0
        self.passwords = {OWNER_EMAIL: (OWNER, "old-password")}
        self.sessions, self.tokens, self.refresh_tokens = {}, {}, {}
        self.issued, self.deleted = [], []
        self.users, self.list_status, self.delete_fail = [], 200, set()   # admin user listing
        self.list_body = None   # when set, every listing page returns this body as is
        self.whoami_calls, self.faults = 0, {}   # n-th whoami call -> "timeout", "no timings" or a status
        self.instance = lambda request, call: "instance-1"

    def issue(self, session_id):
        session = self.sessions[session_id]
        access = mint(self.key, sub=session["user"], aal=session["aal"], session_id=session_id,
                      exp=int(time.time()) + 300)
        refresh = uuid.uuid4().hex
        self.tokens[access] = self.refresh_tokens[refresh] = session_id
        self.issued += [access, refresh]
        return {"access_token": access, "refresh_token": refresh}

    def live(self, access):
        session_id = self.tokens.get(access)
        return session_id if session_id in self.sessions else None

    def handle(self, request):
        body = json.loads(request.content) if request.content else {}
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        if request.url.host == f"{REF}.supabase.co":
            return self.auth(request, body, bearer)
        if request.headers.get("x-vercel-protection-bypass") != BYPASS:
            return httpx.Response(401)
        return self.api(request, bearer)

    def auth(self, request, body, bearer):
        path, grant = request.url.path.removeprefix("/auth/v1"), request.url.params.get("grant_type")
        admin = request.headers.get("apikey", "").startswith("sb_secret_")
        if path == "/token" and grant == "password":
            user = self.passwords.get(body["email"])
            if not user or user[1] != body["password"]:
                return httpx.Response(400, json={"error_code": "invalid_credentials"})
            session_id = str(uuid.uuid4())
            self.sessions[session_id] = {"user": user[0], "aal": "aal1"}
            return httpx.Response(200, json=self.issue(session_id))
        if path == "/token" and grant == "refresh_token":
            session_id = self.refresh_tokens.get(body["refresh_token"])
            if session_id not in self.sessions:
                return httpx.Response(400, json={"error_code": "refresh_token_not_found"})
            return httpx.Response(200, json=self.issue(session_id))
        if path == "/user":
            if not self.live(bearer):
                return httpx.Response(403)
            return httpx.Response(200, json={"id": OWNER, "factors": [
                {"id": "f1", "factor_type": "totp", "status": "verified"}]})
        if path == "/factors/f1/challenge":
            return httpx.Response(200, json={"id": "c1"})
        if path == "/factors/f1/verify":
            session_id = self.live(bearer)
            if not session_id or body.get("code") != "123456":
                return httpx.Response(422)
            self.sessions[session_id]["aal"] = "aal2"
            return httpx.Response(200, json=self.issue(session_id))
        if path == "/logout":
            session_id = self.live(bearer)
            if not session_id:
                return httpx.Response(403)
            user = self.sessions[session_id]["user"]
            self.sessions = {k: v for k, v in self.sessions.items() if v["user"] != user}
            return httpx.Response(204)
        if path == "/admin/users" and admin and request.method == "POST":
            user_id = str(uuid.uuid4())
            self.passwords[body["email"]] = (user_id, body["password"])
            return httpx.Response(200, json={"id": user_id, "email": body["email"]})
        if path == "/admin/users" and admin and request.method == "GET":
            if self.list_status != 200:
                return httpx.Response(self.list_status, json={})
            if self.list_body is not None:
                return httpx.Response(200, json=self.list_body)
            # Pages of at most 50, whatever per_page asks for: the script must page through.
            page, size = int(request.url.params["page"]), min(int(request.url.params["per_page"]), 50)
            listed = [user for user in self.users
                      if not (isinstance(user, dict) and user.get("id") in self.deleted)]
            return httpx.Response(200, json={"users": listed[(page - 1) * size:page * size]})
        if path.startswith("/admin/users/") and admin:
            target = path.rsplit("/", 1)[1]
            if request.method == "DELETE":
                if target in self.delete_fail:
                    return httpx.Response(500, json={})
                self.deleted.append(target)
                return httpx.Response(200, json={})
            if request.method == "PUT":
                self.passwords[OWNER_EMAIL] = (OWNER, body["password"])
                self.sessions = {k: v for k, v in self.sessions.items() if v["user"] != target}
                return httpx.Response(200, json={})
        return httpx.Response(404)

    def api(self, request, bearer):
        headers = {"x-probe-request-id": uuid.uuid4().hex, "x-probe-db-connections": "0"}
        if request.url.path == "/probe/ping":
            return httpx.Response(200, json={"kind": "m5_auth_ping"}, headers=headers)
        if request.url.path != "/probe/whoami":
            return httpx.Response(404, json={"error": "not found"}, headers=headers)
        self.whoami_calls += 1
        headers["x-probe-instance"] = self.instance(request, self.whoami_calls)
        fault = self.faults.get(self.whoami_calls)
        if fault == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if fault == "interrupt":
            raise KeyboardInterrupt
        if isinstance(fault, int):
            return httpx.Response(fault, json={"error": "injected"}, headers=headers)
        if not request.headers.get("authorization", "").startswith("Bearer ") or bearer not in self.tokens:
            return httpx.Response(401, json={"error": "rejected"}, headers=headers)
        claims = jwt.decode(bearer, options={"verify_signature": False})
        if claims["exp"] + 30 < time.time() + self.offset:
            return httpx.Response(401, json={"error": "ExpiredSignatureError"}, headers=headers)
        if request.url.host == WRONG_HOST or claims["sub"] != OWNER:
            return httpx.Response(403, json={"error": "not the owner"}, headers=headers)
        if claims["aal"] != "aal2":
            return httpx.Response(403, json={"error": "aal2 required"}, headers=headers)
        if not self.live(bearer):
            return httpx.Response(401, json={"error": "session revoked"}, headers=headers)
        body = {"aal": "aal2", "session_check": "auth" if request.url.host == AUTH_HOST else "db",
                "identity_ok": True, "seconds_until_exp": int(claims["exp"] - time.time() - self.offset),
                "timings_ms": {"total": 1.0, "connect": 0.2, "session_check": 0.3, "data": 0.2}}
        if fault == "no timings":
            del body["timings_ms"]
        if isinstance(fault, tuple):   # ("timings", value): every timing set to value, sent as raw JSON
            body["timings_ms"] = dict.fromkeys(body["timings_ms"], fault[1])
            return httpx.Response(200, headers={**headers, "content-type": "application/json"},
                                  content=json.dumps(body).encode())
        return httpx.Response(200, headers=headers, json=body)


class ScriptFlowTests(unittest.TestCase):
    def run_script(self, argv, cloud, raises=None, match="", client_class=httpx.Client):
        """Run the script against the fakes and return its evidence, also when it must raise `raises`."""
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sys, "stdin", types.SimpleNamespace(isatty=lambda: True)), \
                contextlib.redirect_stdout(io.StringIO()):
            out = Path(directory) / "evidence.json"
            run = lambda: script.main([*argv, "--out", str(out)], io=FakeIO(cloud),
                                      client=client_class(transport=httpx.MockTransport(cloud.handle)))
            if raises is None:
                run()
            else:
                with self.assertRaisesRegex(raises, match):
                    run()
            return json.loads(out.read_text())

    def samples(self, cloud, **expected):
        return self.run_script(["samples", "--api-url", f"https://{API_HOST}/",
                                "--auth-url", f"https://{AUTH_HOST}/"], cloud, **expected)

    def test_samples_classify_by_instance_until_30_warm(self):
        cloud = FakeCloud()
        # db: instance db-a, then db-b appears at call 21 (scale-out); auth: its own instance.
        cloud.instance = lambda request, call: (
            "auth-a" if request.url.host == AUTH_HOST else "db-b" if call >= 21 and call % 2 else "db-a")
        evidence = self.samples(cloud)
        self.assertEqual([run["class"] for run in evidence["db"]["samples"]],
                         ["cold_candidate", *["warm"] * 19, "cold_candidate", *["warm"] * 11])
        for mode, (n, cold) in (("db", (32, 2)), ("auth", (31, 1))):
            summary = evidence[mode]["summary"]
            self.assertEqual((summary["n"], summary["warm"], summary["cold_candidates"]), (n, 30, cold), mode)
            self.assertEqual(summary["warm_ms"]["total_ms"]["n"], 30)
            self.assertTrue(summary["criteria_met"], mode)
        self.assertIs(evidence["criteria_met"], True)
        self.assertEqual(evidence["sign_out_status"], 204)
        dumped = json.dumps(evidence)
        for value in cloud.issued + [BYPASS, "old-password", OWNER_EMAIL]:
            self.assertNotIn(value, dumped)

    def test_samples_record_failures_and_do_not_claim_success(self):
        cloud = FakeCloud()
        cloud.faults = {3: "timeout", 5: 503, 7: 429, 9: "no timings"}
        evidence = self.samples(cloud)
        db = evidence["db"]["summary"]
        self.assertEqual((db["timeouts"], db["status_5xx"], db["status_429"], db["invalid_200"]), (1, 1, 1, 1))
        self.assertEqual((db["n"], db["warm"]), (35, 30))
        self.assertEqual(evidence["db"]["samples"][2]["error"], "timeout")
        self.assertEqual(evidence["db"]["samples"][8]["invalid"], "timings invalid")
        self.assertFalse(db["criteria_met"])
        self.assertTrue(evidence["auth"]["summary"]["criteria_met"])
        self.assertIs(evidence["criteria_met"], False)
        self.assertEqual(evidence["sign_out_status"], 204)

    def test_samples_stop_at_their_limits_and_fail_the_criteria(self):
        cloud = FakeCloud()
        cloud.instance = lambda request, call: f"instance-{call}"   # never the same instance twice
        evidence = self.samples(cloud)
        for mode in ("db", "auth"):
            summary = evidence[mode]["summary"]
            self.assertEqual((summary["n"], summary["warm"], summary["cold_candidates"]), (60, 0, 60), mode)
            self.assertFalse(summary["criteria"]["warm_at_least_30"])
        self.assertIs(evidence["criteria_met"], False)
        cloud = FakeCloud()
        cloud.faults = {1: "timeout", 2: "timeout", 3: "timeout"}
        evidence = self.samples(cloud)
        self.assertEqual((evidence["db"]["summary"]["n"], evidence["db"]["summary"]["timeouts"]), (3, 3))
        self.assertTrue(evidence["auth"]["summary"]["criteria_met"])
        self.assertIs(evidence["criteria_met"], False)

    def test_samples_reject_non_finite_negative_and_boolean_timings(self):
        for value in (float("nan"), float("inf"), -1.0, True):
            with self.subTest(value=value):
                cloud = FakeCloud()
                cloud.faults = {2: ("timings", value)}
                evidence = self.samples(cloud)
                self.assertEqual(evidence["db"]["samples"][1]["invalid"], "timings invalid")
                summary = evidence["db"]["summary"]
                self.assertEqual((summary["invalid_200"], summary["warm"], summary["n"]), (1, 30, 32))
                self.assertFalse(summary["criteria_met"])
                self.assertIs(evidence["criteria_met"], False)

    def test_samples_treat_an_empty_instance_id_as_missing(self):
        cloud = FakeCloud()
        cloud.instance = lambda request, call: "" if call == 2 else "instance-1"
        evidence = self.samples(cloud)
        entry = evidence["db"]["samples"][1]
        self.assertEqual((entry["class"], entry["invalid"]), ("unclassified", "instance missing"))
        self.assertIs(evidence["criteria_met"], False)

    def test_samples_aborted_after_measuring_never_claim_success(self):
        cloud = FakeCloud()
        original = cloud.auth

        def auth(request, body, bearer):
            if request.url.path == "/auth/v1/logout":
                raise KeyboardInterrupt
            return original(request, body, bearer)

        cloud.auth = auth
        evidence = self.samples(cloud, raises=KeyboardInterrupt)
        self.assertTrue(all(evidence[mode]["summary"]["criteria_met"] for mode in ("db", "auth")))
        self.assertEqual((evidence["completed"], evidence["criteria_met"]), (False, False))
        self.assertEqual(evidence["sign_out_status"], "not finished")

    def test_failure_after_the_command_returns_clears_success(self):
        class FailingClose(httpx.Client):
            def __exit__(self, *exc):
                super().__exit__(*exc)
                raise RuntimeError("close failed")

        evidence = self.samples(FakeCloud(), raises=RuntimeError, client_class=FailingClose)
        self.assertEqual((evidence["completed"], evidence["aborted_by"], evidence["criteria_met"]),
                         (False, "RuntimeError", False))
        self.assertEqual(evidence["sign_out_status"], 204)

    def test_interrupted_samples_keep_partial_evidence_and_sign_out(self):
        cloud = FakeCloud()
        cloud.faults = {5: "interrupt"}
        evidence = self.samples(cloud, raises=KeyboardInterrupt)
        self.assertEqual(len(evidence["db"]["samples"]), 4)
        self.assertNotIn("summary", evidence["db"])
        self.assertEqual((evidence["completed"], evidence["criteria_met"]), (False, False))
        self.assertEqual(evidence["sign_out_status"], 204)

    def test_matrix_end_to_end_against_fakes(self):
        cloud = FakeCloud()
        evidence = self.run_script(["matrix", "--api-url", f"https://{API_HOST}/",
                                    "--wrong-owner-url", f"https://{WRONG_HOST}/"], cloud)
        cases = evidence["cases"]
        for name in ("D1_no_authorization", "D2_non_bearer", "D3_malformed", "D4_alg_none", "D5_hs256",
                     "D6_unknown_kid", "D7_forged_signature", "D8_tampered_payload", "D14_expired"):
            self.assertEqual(cases[name]["status"], 401, name)
        self.assertEqual(cases["D9_owner_aal1"]["status"], 403)
        self.assertEqual(cases["D10_non_owner"]["status"], 403)
        self.assertEqual(cases["D11_owner_aal2"]["status"], 200)
        self.assertEqual(cases["D15_unknown_path"]["status"], 404)
        self.assertEqual(cases["D16_wrong_owner_deployment"]["status"], 403)
        for name, action in (("D12_after_sign_out", "sign_out_status"),
                             ("D13_after_password_change", "password_change_status")):
            case = cases[name]
            self.assertEqual((case["before"]["status"], case["after"]["status"]), (200, 401), name)
            self.assertEqual(case["after"]["error"], "session revoked")
            self.assertTrue(case["valid_procedure"], name)
            self.assertIn(case[action], (200, 204))
        self.assertEqual(len(cloud.deleted), 1)
        self.assertEqual(evidence["final_sign_out_status"], 204)
        self.assertIs(evidence["completed"], True)
        dumped = json.dumps(evidence)
        for value in cloud.issued + [BYPASS, SECRET, "old-password", "new-password", OWNER_EMAIL]:
            self.assertNotIn(value, dumped)

    def test_cleanup_deletes_only_temporary_users_across_pages(self):
        cloud = FakeCloud()
        temporary = [{"id": f"t{i}", "email": f"m5-nonowner-{i:012d}@example.invalid"} for i in range(55)]
        cloud.users = [{"id": "u1", "email": OWNER_EMAIL},
                       {"id": "u3", "email": "m5-nonowner-0123456789ab@example.com"}, *temporary]
        evidence = self.run_script(["cleanup"], cloud)
        self.assertEqual(sorted(cloud.deleted), sorted(user["id"] for user in temporary))
        self.assertEqual((evidence["remaining_users"], evidence["remaining_temporary_users"]), (2, 0))

    def test_cleanup_counts_users_again_after_a_failed_delete(self):
        cloud = FakeCloud()
        cloud.users = [{"id": "u1", "email": OWNER_EMAIL},
                       {"id": "u2", "email": "m5-nonowner-0123456789ab@example.invalid"}]
        cloud.delete_fail = {"u2"}
        evidence = self.run_script(["cleanup"], cloud)
        self.assertEqual(evidence["deleted"], [500])
        self.assertEqual((evidence["remaining_users"], evidence["remaining_temporary_users"]), (2, 1))

    def test_cleanup_listing_failure_reports_no_count(self):
        cloud = FakeCloud()
        cloud.list_status = 500
        evidence = self.run_script(["cleanup"], cloud, raises=SystemExit, match="listing users failed: 500")
        self.assertNotIn("remaining_users", evidence)
        self.assertIs(evidence["completed"], False)

    def test_cleanup_rejects_malformed_listings_before_counting(self):
        rows = {"empty row": [{}], "missing email": [{"id": "u1"}], "empty id": [{"id": "", "email": None}],
                "numeric id": [{"id": 5, "email": OWNER_EMAIL}], "numeric email": [{"id": "u1", "email": 5}],
                "not a dict": ["u1"]}
        for name, users in rows.items():
            with self.subTest(name):
                cloud = FakeCloud()
                cloud.users = users
                evidence = self.run_script(["cleanup"], cloud, raises=SystemExit, match="malformed user list")
                self.assertNotIn("remaining_users", evidence)
                self.assertEqual(cloud.deleted, [])
        for name, body in {"users not a list": {"users": "u1"}, "no users key": {"aud": "authenticated"},
                           "not an object": ["u1"]}.items():
            with self.subTest(name):
                cloud = FakeCloud()
                cloud.list_body = body
                evidence = self.run_script(["cleanup"], cloud, raises=SystemExit, match="malformed user list")
                self.assertNotIn("remaining_users", evidence)

    def test_cleanup_keeps_users_without_email(self):
        cloud = FakeCloud()
        cloud.users = [{"id": "u1", "email": OWNER_EMAIL}, {"id": "u2", "email": None}, {"id": "u3", "email": ""}]
        evidence = self.run_script(["cleanup"], cloud)
        self.assertEqual(cloud.deleted, [])
        self.assertEqual((evidence["remaining_users"], evidence["remaining_temporary_users"]), (3, 0))

    def test_output_is_reserved_before_any_prompt_and_kept_on_abort(self):
        cloud, test = FakeCloud(), self

        class InterruptedIO(FakeIO):
            def secret(self, prompt):
                # Reserved before the first prompt, so a run started now with the same name is refused.
                test.assertTrue(out.exists())
                with test.assertRaisesRegex(SystemExit, "already exists"):
                    script.main(["cleanup", "--out", str(out)])
                raise KeyboardInterrupt

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sys, "stdin", types.SimpleNamespace(isatty=lambda: True)), \
                contextlib.redirect_stdout(io.StringIO()):
            out = Path(directory) / "evidence.json"
            with self.assertRaises(KeyboardInterrupt):
                script.main(["cleanup", "--out", str(out)], io=InterruptedIO(cloud),
                            client=httpx.Client(transport=httpx.MockTransport(cloud.handle)))
            evidence = json.loads(out.read_text())
        self.assertEqual((evidence["completed"], evidence["aborted_by"]), (False, "KeyboardInterrupt"))

    def test_refuses_existing_output_and_non_tty(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "evidence.json"
            out.write_text("{}")
            with patch.object(sys, "stdin", types.SimpleNamespace(isatty=lambda: True)):
                with self.assertRaisesRegex(SystemExit, "already exists"):
                    script.main(["cleanup", "--out", str(out)])
            with patch.object(sys, "stdin", types.SimpleNamespace(isatty=lambda: False)):
                with self.assertRaisesRegex(SystemExit, "own terminal"):
                    script.main(["cleanup", "--out", str(Path(directory) / "new.json")])

    def test_rejects_non_probe_urls(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sys, "stdin", types.SimpleNamespace(isatty=lambda: True)):
            with self.assertRaisesRegex(SystemExit, "preview URL"):
                script.main(["samples", "--api-url", "https://evil.example/", "--auth-url",
                             f"https://{API_HOST}/", "--out", str(Path(directory) / "x.json")])

    def test_preview_url_pin_rejects_lookalikes_and_url_components_before_io(self):
        good = f"https://{API_HOST}/"
        bad = [
            "https://pft-m5-auth-api-20261009-x.evil.example/",
            "https://pft-m5-auth-api-20261009-db.vercel.app.attacker.tld/",
            f"http://{API_HOST}/", f"https://u:p@{API_HOST}/",
            f"https://@{API_HOST}/", f"https://{API_HOST}:443/",
            f"https://{API_HOST}:8443/", f"https://{API_HOST}/?a=1",
            f"https://{API_HOST}/?", f"https://{API_HOST}/#fragment",
            f"https://{API_HOST}/#", f"https://{API_HOST}/probe/whoami",
            f"https://{API_HOST}/x/../", f"https://{API_HOST}/%2f",
            "https://pft-m5-auth-api-20261009-.vercel.app/", "", "not a URL",
        ]
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sys, "stdin", types.SimpleNamespace(isatty=lambda: True)):
            for command, required in (("matrix", ("api_url", "wrong_owner_url")),
                                      ("samples", ("api_url", "auth_url"))):
                for field in required:
                    for index, url in enumerate(bad):
                        with self.subTest(command=command, field=field, url=url):
                            out = Path(directory) / f"{command}-{field}-{index}.json"
                            values = dict.fromkeys(required, good)
                            values[field] = url
                            argv = [command, "--out", str(out)]
                            for name, value in values.items():
                                argv += ["--" + name.replace("_", "-"), value]
                            with patch.dict(script.COMMANDS, {command: (unittest.mock.Mock(), required)}), \
                                    contextlib.redirect_stdout(io.StringIO()):
                                with self.assertRaisesRegex(SystemExit, "preview URL"):
                                    script.main(argv)
                            self.assertFalse(out.exists())

    def test_preview_url_pin_accepts_root_with_or_without_slash(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sys, "stdin", types.SimpleNamespace(isatty=lambda: True)):
            for index, suffix in enumerate(("", "/")):
                out = Path(directory) / f"{index}.json"
                command = unittest.mock.Mock()
                with patch.dict(script.COMMANDS, {"samples": (command, ("api_url", "auth_url"))}), \
                        contextlib.redirect_stdout(io.StringIO()):
                    script.main(["samples", "--api-url", f"https://{API_HOST}{suffix}",
                                 "--auth-url", f"https://{WRONG_HOST}{suffix}", "--out", str(out)])
                command.assert_called_once()
