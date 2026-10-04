"""Exercise CI's local fixture exception without permitting arbitrary sockets."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading
import unittest
from urllib.request import build_opener, ProxyHandler

from scripts.ci_backend_tests import isolated_network


class NetworkIsolationTests(unittest.TestCase):
    def test_live_fixture_allowed_and_closed_fixture_rejected(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"synthetic")

            def log_message(self, *args):
                pass

        with isolated_network():
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            address = server.server_address
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                opener = build_opener(ProxyHandler({}))
                with opener.open(f"http://{address[0]}:{address[1]}", timeout=3) as response:
                    self.assertEqual(response.read(), b"synthetic")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
            with socket.socket() as sock, self.assertRaisesRegex(AssertionError, "forbidden"):
                sock.connect(address)

    def test_unregistered_loopback_and_external_connections_rejected(self):
        with isolated_network():
            for address in (("127.0.0.1", 5432), ("127.0.0.1", 55440), ("192.0.2.1", 443)):
                for method in ("connect", "connect_ex"):
                    with self.subTest(address=address, method=method), socket.socket() as sock:
                        with self.assertRaisesRegex(AssertionError, "forbidden"):
                            getattr(sock, method)(address)

    def test_wildcard_server_binding_rejected(self):
        with isolated_network(), self.assertRaisesRegex(AssertionError, "loopback"):
            ThreadingHTTPServer(("0.0.0.0", 0), BaseHTTPRequestHandler)
