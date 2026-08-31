"""Net transport policy (review item 5 / spec/netpolicy.md).

The reference enforcement must refuse: forbidden address classes
(DNS-rebinding to loopback/private/metadata), redirects (new,
unauthorized destinations), and oversized responses — before any bytes
reach the semantic layer (which adds its own E410 io budget).
"""

import http.server
import threading
import unittest
from unittest import mock

from runtime.netpolicy import (PolicyViolation, default_transport,
                               guarded_transport)


class TestAddressPolicy(unittest.TestCase):
    def test_rebind_to_loopback_refused_before_connect(self):
        calls = []
        inner = lambda url: calls.append(url) or "exfiltrated"  # noqa: E731
        transport = guarded_transport(inner)
        with mock.patch("runtime.netpolicy.socket.getaddrinfo",
                        return_value=[(2, 1, 6, "", ("127.0.0.1", 0))]):
            with self.assertRaises(PolicyViolation) as ctx:
                transport("https://trusted.example.com/health")
        self.assertIn("forbidden address class", str(ctx.exception))
        self.assertEqual(calls, [], "refusal must happen pre-connection")

    def test_metadata_endpoint_refused(self):
        transport = guarded_transport(lambda url: "x")
        for ip in ("169.254.169.254", "10.0.0.5", "192.168.1.1",
                   "fd00::1", "fe80::1"):
            with self.subTest(ip=ip):
                with mock.patch("runtime.netpolicy.socket.getaddrinfo",
                                return_value=[(2, 1, 6, "", (ip, 0))]):
                    with self.assertRaises(PolicyViolation):
                        transport("https://trusted.example.com/x")

    def test_public_address_passes_to_inner(self):
        inner = lambda url: "ok-body"  # noqa: E731
        transport = guarded_transport(inner)
        with mock.patch("runtime.netpolicy.socket.getaddrinfo",
                        return_value=[(2, 1, 6, "", ("93.184.216.34", 0))]):
            self.assertEqual(
                transport("https://trusted.example.com/health"), "ok-body")

    def test_response_cap_enforced(self):
        transport = guarded_transport(lambda url: "x" * 100,
                                      max_bytes=10)
        with mock.patch("runtime.netpolicy.socket.getaddrinfo",
                        return_value=[(2, 1, 6, "", ("93.184.216.34", 0))]):
            with self.assertRaises(PolicyViolation):
                transport("https://trusted.example.com/big")


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://attacker.example/x")
            self.end_headers()
            return
        body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class TestDefaultTransport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever,
                         daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_redirect_refused(self):
        transport = default_transport()
        with self.assertRaises(PolicyViolation) as ctx:
            transport(f"http://127.0.0.1:{self.port}/redirect")
        self.assertIn("redirect", str(ctx.exception).lower())

    def test_normal_fetch_works_with_allow_private(self):
        # loopback is explicitly allowed here BECAUSE the test server is
        # local — the same escape hatch is documented for testing only
        transport = guarded_transport(default_transport(),
                                      allow_private=True)
        self.assertEqual(
            transport(f"http://127.0.0.1:{self.port}/ok"),
            '{"status":"ok"}')


if __name__ == "__main__":
    unittest.main()
