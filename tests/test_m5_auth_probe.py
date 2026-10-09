"""M5 owner-auth feasibility: negative-test matrix for the token verifier (Auth design §6).

Keys are generated per test; the JWKS fetch is injected. Needs PyJWT, which
is not an application dependency before M6, so the module skips without it.
"""
import base64
import hashlib
import hmac
import json
import time
import unittest

try:
    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec, rsa
    from experiments.m5_cloud.auth_probe import AuthConfig, AuthError, OwnerTokenVerifier
except ImportError:  # pragma: no cover - environment without PyJWT
    jwt = None

OWNER = "11111111-2222-3333-4444-555555555555"
REF = "acyghoemtdrilsdszolq"


def ec_key():
    return ec.generate_private_key(ec.SECP256R1())


def public_jwk(private, kid):
    entry = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private.public_key()))
    return {**entry, "kid": kid, "alg": "ES256", "use": "sig"}


@unittest.skipIf(jwt is None, "PyJWT not installed (M6 dependency)")
class OwnerTokenVerifierTests(unittest.TestCase):
    def setUp(self):
        self.config = AuthConfig(project_ref=REF, owner_sub=OWNER)
        self.key = ec_key()
        self.jwks = {"keys": [public_jwk(self.key, "kid-1")]}
        self.now = [1000.0]
        self.verifier = OwnerTokenVerifier(self.config, fetch=lambda url: self.fetched(url),
                                           clock=lambda: self.now[0])
        self.urls = []

    def fetched(self, url):
        self.urls.append(url)
        return self.jwks

    def token(self, *, key=None, kid="kid-1", alg="ES256", headers=None, **claims):
        now = int(time.time())
        payload = {"iss": self.config.issuer, "aud": "authenticated", "sub": OWNER, "iat": now,
                   "exp": now + 600, "aal": "aal2", "is_anonymous": False, "role": "authenticated", **claims}
        payload = {name: value for name, value in payload.items() if value is not None}
        return "Bearer " + jwt.encode(payload, key or self.key, algorithm=alg,
                                      headers={"kid": kid, **(headers or {})})

    def rejected(self, status, authorization):
        with self.assertRaises(AuthError) as caught:
            self.verifier.verify(authorization)
        self.assertEqual(caught.exception.status, status, caught.exception.reason)
        return caught.exception.reason

    def test_owner_aal2_token_is_accepted_from_configured_jwks_only(self):
        claims = self.verifier.verify(self.token())
        self.assertEqual((claims["sub"], claims["aal"]), (OWNER, "aal2"))
        self.assertEqual(self.urls, [f"https://{REF}.supabase.co/auth/v1/.well-known/jwks.json"])

    def test_missing_malformed_and_wrong_scheme(self):
        for value in (None, "", "Bearer", "Bearer not.a.jwt", "Basic abc", self.token().removeprefix("Bearer ")):
            self.rejected(401, value)

    def test_time_claims(self):
        now = int(time.time())
        self.rejected(401, self.token(exp=now - 60))  # expired beyond leeway
        self.rejected(401, self.token(iat=now + 3600, exp=now + 7200))  # issued in the future
        self.rejected(401, self.token(nbf=now + 3600))
        self.rejected(401, self.token(exp=None))
        self.rejected(401, self.token(iat=None))
        self.verifier.verify(self.token(exp=now - 10))  # within 30 s leeway

    def test_issuer_and_audience_are_exact(self):
        self.rejected(401, self.token(iss="https://evil.supabase.co/auth/v1"))
        self.rejected(401, self.token(iss=self.config.issuer + "/"))
        self.rejected(401, self.token(aud="anon"))
        self.rejected(401, self.token(aud=None))

    def test_algorithm_confusion_and_none_are_rejected_before_key_lookup(self):
        public_pem = self.key.public_key().public_bytes(serialization.Encoding.PEM,
                                                        serialization.PublicFormat.SubjectPublicKeyInfo)
        now = int(time.time())
        claims = {"iss": self.config.issuer, "aud": "authenticated", "sub": OWNER, "iat": now, "exp": now + 600,
                  "aal": "aal2", "is_anonymous": False}
        # PyJWT refuses to sign HS256 with a PEM, so forge it by hand, as an attacker would.
        def b64(data):
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
        signing_input = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "kid-1"}).encode()) + "." + \
            b64(json.dumps(claims).encode())
        hs = signing_input + "." + b64(hmac.new(public_pem, signing_input.encode(), hashlib.sha256).digest())
        self.assertEqual(self.rejected(401, "Bearer " + hs), "algorithm rejected")
        unsigned = jwt.encode(claims, None, algorithm="none", headers={"kid": "kid-1"})
        self.assertEqual(self.rejected(401, "Bearer " + unsigned), "algorithm rejected")
        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.assertEqual(self.rejected(401, self.token(key=rsa_key, alg="RS256")), "algorithm rejected")
        p384 = ec.generate_private_key(ec.SECP384R1())
        self.assertEqual(self.rejected(401, self.token(key=p384, alg="ES384")), "algorithm rejected")
        self.assertEqual(self.urls, [])  # No JWKS fetch for any of these.

    def test_forged_signature_and_attacker_key_headers_are_ignored(self):
        attacker = ec_key()
        forged = self.token(key=attacker, headers={"jku": "https://evil.example/jwks.json",
                                                   "jwk": public_jwk(attacker, "kid-1")})
        self.rejected(401, forged)
        self.assertTrue(all("evil" not in url for url in self.urls))

    def test_unknown_kid_refetches_at_most_once_per_minute(self):
        self.verifier.verify(self.token())
        self.rejected(401, self.token(key=ec_key(), kid="kid-unknown"))
        self.assertEqual(len(self.urls), 1)  # Fetched seconds ago: no refetch.
        self.now[0] += 61
        self.rejected(401, self.token(key=ec_key(), kid="kid-unknown"))
        self.assertEqual(len(self.urls), 2)
        self.rejected(401, self.token(key=ec_key(), kid="kid-other"))
        self.assertEqual(len(self.urls), 2)

    def test_rotated_key_is_picked_up_after_the_refetch_window(self):
        self.verifier.verify(self.token())
        rotated = ec_key()
        self.jwks = {"keys": [public_jwk(self.key, "kid-1"), public_jwk(rotated, "kid-2")]}
        self.now[0] += 61
        self.verifier.verify(self.token(key=rotated, kid="kid-2"))
        self.jwks = {"keys": [public_jwk(rotated, "kid-2")]}  # Old key withdrawn.
        self.now[0] += 61
        self.verifier.verify(self.token(key=rotated, kid="kid-2"))
        self.assertEqual(self.verifier._keys.keys(), {"kid-1", "kid-2"})  # Cache refreshes only on unknown kid.

    def test_owner_pin_aal2_and_anonymous(self):
        self.assertEqual(self.rejected(403, self.token(sub="99999999-0000-0000-0000-000000000000")), "not the owner")
        self.assertEqual(self.rejected(403, self.token(aal="aal1")), "aal2 required")
        self.assertEqual(self.rejected(403, self.token(aal=None)), "aal2 required")
        self.assertEqual(self.rejected(403, self.token(is_anonymous=True)), "anonymous or unknown session")
        self.assertEqual(self.rejected(403, self.token(is_anonymous=None)), "anonymous or unknown session")
        self.rejected(401, self.token(sub=None))

    def test_non_signing_and_non_p256_jwks_entries_are_ignored(self):
        other = ec.generate_private_key(ec.SECP384R1())
        entry = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(other.public_key()))
        self.jwks = {"keys": [{**entry, "kid": "kid-1"}, {"kty": "oct", "k": "c2VjcmV0", "kid": "kid-1"}]}
        self.rejected(401, self.token())
