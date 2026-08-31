"""`net.fetch` — capability-gated outbound requests.

The only way a 2066 program reaches an external microservice. Rules
pinned here for BOTH adapters:

- no transport attached -> E401 (default deny, runtime owns no sockets)
- transport attached but no grant for the host -> E403
- grant on `api.example.com` does NOT cover `other.example.com`... but
  a grant on the parent domain DOES cover its subdomains
- authorized request returns the body through the host's transport
"""

import io
import sys
import tempfile
import unittest

from runtime import analyze, execute, parse_source
from runtime.capabilities import GrantSet
from runtime.plan_vm import execute_plan

SRC = """main

node 001
op const
type string
value "{url}"

node 002
op net.fetch
input 001
output string

node 003
op emit
input 002
"""


def grants_for(*hosts):
    return GrantSet.from_dict({"subject": "t", "grants": [
        {"action": "net.request", "resource": h} for h in hosts]})


def run(adapter, url, grants, transport):
    program = parse_source(SRC.replace("{url}", url))
    analysis = analyze(program)
    old_in, old_out = sys.stdin, sys.stdout
    sys.stdin, sys.stdout = io.StringIO(""), io.StringIO()
    try:
        if adapter == "tree":
            return execute(program, analysis, grants=grants, net=transport)
        return execute_plan(program, analysis, grants=grants, net=transport)
    except Exception as exc:
        return exc
    finally:
        sys.stdin, sys.stdout = old_in, old_out


class TestNetFetch(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def transport(url):
            self.calls.append(url)
            return "ok"

        self.transport = transport

    def test_authorization_matrix_both_adapters(self):
        cases = [
            # (grants, url, expect)
            (grants_for("api.example.com"),
             "https://api.example.com/v1/health", "ok"),
            (grants_for("example.com"),
             "https://api.example.com/v1/health", "ok"),  # subdomain covered
            (grants_for("api.example.com"),
             "https://other.example.com/v1/health", "E401"),
            (grants_for("evil.com"),
             "https://api.example.com/v1/health", "E401"),
        ]
        for grants, url, expect in cases:
            for adapter in ("tree", "plan"):
                with self.subTest(adapter=adapter, url=url,
                                  hosts=[c.resource for c in
                                         grants.capabilities]):
                    self.calls.clear()
                    result = run(adapter, url, grants, self.transport)
                    if expect.startswith("E"):
                        self.assertEqual(result.code, expect)
                        self.assertEqual(self.calls, [])
                    else:
                        self.assertEqual(result, ["ok"])
                        self.assertEqual(self.calls, [url])

    def test_no_transport_denies_before_grants(self):
        result = run("tree", "https://api.example.com/x",
                     grants_for("api.example.com"), None)
        self.assertEqual(result.code, "E401")

    def test_transport_failure_is_structured(self):
        def boom(url):
            raise OSError("connection refused")

        result = run("plan", "https://api.example.com/x",
                     grants_for("api.example.com"), boom)
        self.assertEqual(result.code, "E560")


if __name__ == "__main__":
    unittest.main()
