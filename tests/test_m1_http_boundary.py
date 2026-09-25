"""Exact Host/Origin rules for the local web and private HTTPS proxy chain."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.datastructures import Headers

from api.main import _authority, _origin, boundary_config, local_request_boundary


CONFIG = {
    "PFT_STRICT_LOCAL_HTTP": "true",
    "PFT_ALLOWED_HOSTS": "api:8000,127.0.0.1:8000,localhost:8000",
    "PFT_ALLOWED_ORIGINS": (
        "http://127.0.0.1:3000,http://localhost:3000,https://pft-host.tailc4d964.ts.net"
    ),
}


class AuthorityParsingTests(unittest.TestCase):
    def test_exact_host_and_ipv6_parsing(self):
        self.assertEqual(_authority("API:8000"), ("api", 8000))
        self.assertEqual(_authority("[::1]:8000"), ("::1", 8000))
        self.assertEqual(_origin("https://PC.tailnet.ts.net"),
                         ("https", "pc.tailnet.ts.net", 443))
        for value in ("api:bad", "api:0", "api:65536", "api:", "::1:8000",
                      "api/path", "api@evil.test", "api,evil.test", "*.ts.net",
                      "api.", " api:8000"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _authority(value)

    def test_origin_rejects_non_origin_forms(self):
        for value in ("null", "", "https://*.ts.net", "https://pc.tailnet.ts.net/",
                      "https://pc.tailnet.ts.net/path", "https://user@pc.tailnet.ts.net",
                      "https://pc.tailnet.ts.net?x=1", "file://pc.tailnet.ts.net",
                      "https://pc.tailnet.ts.net:bad"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _origin(value)

    def test_missing_or_invalid_configuration_fails_closed(self):
        for changes in ({"PFT_ALLOWED_HOSTS": ""},
                        {"PFT_ALLOWED_HOSTS": "api:8000,*.ts.net"},
                        {"PFT_ALLOWED_ORIGINS": ""},
                        {"PFT_ALLOWED_ORIGINS": "https://*.ts.net"}):
            with self.subTest(changes=changes), patch.dict(os.environ, {**CONFIG, **changes}, clear=True):
                with self.assertRaises(ValueError):
                    boundary_config()

    def test_legacy_single_origin_is_accepted_explicitly(self):
        with patch.dict(os.environ, {
            "PFT_ALLOWED_HOSTS": "api:8000",
            "PFT_ALLOWED_ORIGIN": "http://127.0.0.1:3000",
        }, clear=True):
            _, origins = boundary_config()
        self.assertEqual(origins, {("http", "127.0.0.1", 3000)})


class BoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def check(self, method, host, origin=None, **extra_headers):
        headers = {"host": host, **extra_headers}
        if origin is not None:
            headers["origin"] = origin
        next_handler = AsyncMock(return_value=SimpleNamespace(status_code=204))
        with patch.dict(os.environ, CONFIG, clear=True):
            response = await local_request_boundary(
                SimpleNamespace(method=method, headers=headers), next_handler)
        return response.status_code, next_handler.await_count

    async def test_local_and_phone_write_origins(self):
        for origin in ("http://127.0.0.1:3000", "http://localhost:3000",
                       "https://pft-host.tailc4d964.ts.net"):
            with self.subTest(origin=origin):
                self.assertEqual(await self.check("POST", "api:8000", origin), (204, 1))

    async def test_missing_null_and_hostile_write_origins(self):
        for origin in (None, "null", "https://evil.ts.net",
                       "https://randy-pc.tailc4d964.ts.net", "http://pc.tailnet.ts.net",
                       "https://pc.tailnet.ts.net.evil.test"):
            with self.subTest(origin=origin):
                self.assertEqual(await self.check("POST", "api:8000", origin), (403, 0))

    async def test_get_head_options_and_health_probe_need_allowed_host(self):
        for method in ("GET", "HEAD", "OPTIONS"):
            self.assertEqual(await self.check(method, "api:8000"), (204, 1))
            self.assertEqual(await self.check(method, "127.0.0.1:8000"), (204, 1))
            self.assertEqual(await self.check(method, "pc.tailnet.ts.net"), (400, 0))
            self.assertEqual(await self.check(method, "evil.test"), (400, 0))

    async def test_forwarded_headers_do_not_grant_trust(self):
        self.assertEqual(await self.check(
            "POST", "evil.test", "https://pc.tailnet.ts.net",
            **{"x-forwarded-host": "api:8000", "x-forwarded-proto": "https"}), (400, 0))
        self.assertEqual(await self.check(
            "POST", "api:8000", "https://evil.test",
            **{"x-forwarded-host": "pc.tailnet.ts.net", "x-forwarded-proto": "https"}), (403, 0))

    async def test_malformed_host_does_not_reach_handler(self):
        for host in ("", "api:bad", "api:8000,evil.test", "api@evil.test", "[::1"):
            with self.subTest(host=host):
                self.assertEqual(await self.check("GET", host), (400, 0))

    async def test_duplicate_host_header_is_rejected(self):
        request = SimpleNamespace(method="GET", headers=Headers(raw=[
            (b"host", b"api:8000"), (b"host", b"evil.test")]))
        next_handler = AsyncMock()
        with patch.dict(os.environ, CONFIG, clear=True):
            response = await local_request_boundary(request, next_handler)
        self.assertEqual(response.status_code, 400)
        next_handler.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
