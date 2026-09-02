import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

import plaid
from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import ValidationError

from api import db
from api.routes import plaid as plaid_routes


def production_environment(key):
    return {
        "PLAID_ENV": "production",
        "PLAID_CLIENT_ID": "test-client-id",
        "PLAID_SECRET": "test-secret",
        "PLAID_TOKEN_ENCRYPTION_KEY": key.decode(),
        "PLAID_PILOT_USER_ID": "local-pilot-user",
        "PLAID_REDIRECT_URI": "https://temporary.example/plaid-oauth",
        "PLAID_PILOT_LINK_ENABLED": "true",
        "EXPECTED_DATABASE_NAME": "pft_production_pilot",
    }


class _Connection:
    def __init__(self, database_name):
        self.database_name = database_name

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def scalar(self, statement):
        return self.database_name


class _Engine:
    def __init__(self, database_name):
        self.database_name = database_name

    def connect(self):
        return _Connection(self.database_name)


class _LinkClient:
    def __init__(self, response=None, error=None):
        self.response = response or {"link_token": "test-link-token"}
        self.error = error
        self.request = None

    def link_token_create(self, request):
        self.request = request
        if self.error:
            raise self.error
        return self.response


class _PlaidErrorResponse:
    status = 400
    reason = "Bad Request"

    def __init__(self, data):
        self.data = json.dumps(data)

    def getheaders(self):
        return {}


class PlaidProductionSafetyTests(unittest.TestCase):
    def setUp(self):
        self.key = Fernet.generate_key()

    def test_production_tokens_are_encrypted_and_round_trip(self):
        with patch.dict(os.environ, production_environment(self.key), clear=True):
            first = plaid_routes.encrypt_access_token("access-production-test")
            second = plaid_routes.encrypt_access_token("access-production-test")

            self.assertTrue(first.startswith(plaid_routes.ENCRYPTED_TOKEN_PREFIX))
            self.assertNotEqual(first, second)
            self.assertNotIn("access-production-test", first)
            self.assertEqual(
                plaid_routes.decrypt_access_token(first),
                "access-production-test",
            )

    def test_production_rejects_plaintext_and_wrong_key(self):
        environment = production_environment(self.key)
        with patch.dict(os.environ, environment, clear=True):
            encrypted = plaid_routes.encrypt_access_token("access-production-test")
            with self.assertRaisesRegex(RuntimeError, "not encrypted"):
                plaid_routes.decrypt_access_token("access-production-test")

        environment["PLAID_TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(RuntimeError, "cannot be decrypted"):
                plaid_routes.decrypt_access_token(encrypted)

    def test_sandbox_token_behavior_is_unchanged(self):
        with patch.dict(os.environ, {"PLAID_ENV": "sandbox"}, clear=True):
            self.assertEqual(
                plaid_routes.encrypt_access_token("access-sandbox-test"),
                "access-sandbox-test",
            )
            self.assertEqual(
                plaid_routes.decrypt_access_token("access-sandbox-test"),
                "access-sandbox-test",
            )

    def test_production_configuration_requires_https_and_valid_key(self):
        environment = production_environment(self.key)
        with patch.dict(os.environ, environment, clear=True):
            plaid_routes.validate_runtime_configuration()

        environment["PLAID_REDIRECT_URI"] = "http://127.0.0.1:3000/plaid-oauth"
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(RuntimeError, "must use HTTPS"):
                plaid_routes.validate_runtime_configuration()

        environment["PLAID_REDIRECT_URI"] = "https://temporary.example/plaid-oauth"
        environment["PLAID_TOKEN_ENCRYPTION_KEY"] = "not-a-fernet-key"
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(RuntimeError, "missing or invalid"):
                plaid_routes.validate_runtime_configuration()

    def test_exchange_body_is_typed(self):
        with self.assertRaises(ValidationError):
            plaid_routes.PublicTokenExchange(public_token="")
        with self.assertRaises(ValidationError):
            plaid_routes.PublicTokenExchange(
                public_token="public-production-test",
                institution_id="not-an-institution-id",
                institution_name="American Express",
            )

    def test_blank_link_institution_name_is_rejected_before_plaid_call(self):
        body = plaid_routes.PublicTokenExchange(
            public_token="public-production-test",
            institution_id="ins_10",
            institution_name="   ",
        )
        with (
            patch.dict(os.environ, production_environment(self.key), clear=True),
            patch.object(plaid_routes, "get_client") as get_client,
        ):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(plaid_routes.exchange_public_token(body))
        self.assertEqual(error.exception.status_code, 422)
        get_client.assert_not_called()

    def test_production_link_is_disabled_by_default(self):
        environment = production_environment(self.key)
        environment["PLAID_PILOT_LINK_ENABLED"] = "false"
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(plaid_routes.create_link_token())
        self.assertEqual(error.exception.status_code, 403)

    def test_existing_production_item_blocks_exchange_before_plaid_call(self):
        body = plaid_routes.PublicTokenExchange(
            public_token="public-production-test",
            institution_id="ins_56",
            institution_name="Chase",
        )
        with (
            patch.dict(os.environ, production_environment(self.key), clear=True),
            patch.object(
                plaid_routes,
                "_institution_exists",
                AsyncMock(return_value=True),
            ),
            patch.object(plaid_routes, "get_client") as get_client,
        ):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(plaid_routes.exchange_public_token(body))
        self.assertEqual(error.exception.status_code, 409)
        get_client.assert_not_called()

    def test_link_token_uses_stable_user_and_oauth_redirect(self):
        client = _LinkClient()
        with (
            patch.dict(os.environ, production_environment(self.key), clear=True),
            patch.object(plaid_routes, "get_client", return_value=client),
        ):
            result = asyncio.run(plaid_routes.create_link_token())

        request = client.request.to_dict()
        self.assertEqual(result, "test-link-token")
        self.assertEqual(request["user"]["client_user_id"], "local-pilot-user")
        self.assertEqual(
            request["redirect_uri"],
            "https://temporary.example/plaid-oauth",
        )
        self.assertEqual(request["transactions"]["days_requested"], 730)
        self.assertNotIn("institution_id", request)

    def test_sandbox_link_keeps_random_user_and_has_no_redirect(self):
        client = _LinkClient()
        environment = {
            "PLAID_ENV": "sandbox",
            "PLAID_CLIENT_ID": "test-client-id",
            "PLAID_SECRET": "test-secret",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(plaid_routes, "get_client", return_value=client),
        ):
            result = asyncio.run(plaid_routes.create_link_token())

        request = client.request.to_dict()
        self.assertEqual(result, "test-link-token")
        self.assertNotEqual(request["user"]["client_user_id"], "local-pilot-user")
        self.assertNotIn("redirect_uri", request)
        self.assertNotIn("transactions", request)

    def test_sandbox_helper_remains_blocked_in_production(self):
        with patch.dict(os.environ, production_environment(self.key), clear=True):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(plaid_routes.create_sandbox_public_token())
        self.assertEqual(error.exception.status_code, 403)

    def test_plaid_errors_are_sanitized(self):
        plaid_secret = "secret-value-that-must-not-be-logged"
        access_token = "access-production-token-that-must-not-be-logged"
        public_token = "public-production-token-that-must-not-be-logged"
        response = _PlaidErrorResponse(
            {
                "error_type": "INVALID_REQUEST",
                "error_code": "INVALID_FIELD",
                "display_message": "The redirect URI is not registered.",
                "request_id": "request-id-123",
                "access_token": access_token,
                "public_token": public_token,
                "secret": plaid_secret,
            }
        )
        client = _LinkClient(error=plaid.ApiException(http_resp=response))
        environment = production_environment(self.key)
        environment["PLAID_SECRET"] = plaid_secret
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(plaid_routes, "get_client", return_value=client),
            self.assertLogs(plaid_routes.logger, level="WARNING") as logs,
        ):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(plaid_routes.create_link_token())
        self.assertEqual(error.exception.status_code, 502)
        self.assertEqual(error.exception.detail, "Plaid request failed")
        log_output = "\n".join(logs.output)
        self.assertIn("error_type='INVALID_REQUEST'", log_output)
        self.assertIn("error_code='INVALID_FIELD'", log_output)
        self.assertIn("message='The redirect URI is not registered.'", log_output)
        self.assertIn("request_id='request-id-123'", log_output)
        self.assertNotIn(plaid_secret, log_output)
        self.assertNotIn(access_token, log_output)
        self.assertNotIn(public_token, log_output)


class DatabaseGuardTests(unittest.TestCase):
    def test_database_name_mismatch_aborts(self):
        with (
            patch.dict(
                os.environ,
                {
                    "PLAID_ENV": "production",
                    "EXPECTED_DATABASE_NAME": "pft_production_pilot",
                },
                clear=True,
            ),
            patch.object(db, "engine", _Engine("pft")),
        ):
            with self.assertRaisesRegex(RuntimeError, "safety check failed"):
                asyncio.run(db.verify_database_name())

    def test_database_name_match_passes(self):
        with (
            patch.dict(
                os.environ,
                {
                    "PLAID_ENV": "production",
                    "EXPECTED_DATABASE_NAME": "pft_production_pilot",
                },
                clear=True,
            ),
            patch.object(db, "engine", _Engine("pft_production_pilot")),
        ):
            asyncio.run(db.verify_database_name())


if __name__ == "__main__":
    unittest.main()
