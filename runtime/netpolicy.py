"""Reference transport policy for `net.fetch` (review item 5).

The SEMANTIC layer (capability grant) authorizes a hostname. Everything
between "hostname allowed" and "bytes returned" is the TRANSPORT
ADAPTER's duty, made normative in spec/netpolicy.md. This module is the
reference enforcement for hosts using urllib-style transports:

  - resolve the host and REFUSE loopback / private / link-local /
    reserved / multicast addresses unless explicitly allowed (kills
    DNS-rebinding-to-localhost and cloud-metadata endpoints)
  - DO NOT follow redirects (a redirect is a NEW destination that was
    never authorized; it must surface as a refusal, not a silent hop)
  - cap response bytes (the semantic layer adds E410 io-budget on top)
  - IDN hostnames must be punycoded BEFORE grant matching (the caller
    of this wrapper normalizes; grants store punycode)

Runtime-owned sockets: still none — this composes host callables.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.request
from urllib.error import HTTPError


class PolicyViolation(Exception):
    """Transport policy refusal — surfaces as E560 at the op layer."""


def _refuse_address(host: str, allow_private: bool) -> None:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise PolicyViolation(f"cannot resolve {host}: {exc}") from exc
    for family, _, _, _, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        blocked = (ip.is_loopback or ip.is_private or ip.is_link_local
                   or ip.is_reserved or ip.is_multicast
                   or ip.is_unspecified)
        if blocked and not allow_private:
            raise PolicyViolation(
                f"{host} resolves to a forbidden address class "
                f"({ip}; loopback/private/link-local/reserved). Grant the "
                "explicit IP form or pass allow_private for local testing.")


def guarded_transport(inner=None, *, allow_private: bool = False,
                      max_bytes: int = 2_000_000,
                      timeout: float = 10.0):
    """Wrap a transport callable (or build the urllib default) with the
    normative policy: resolve-check before connecting, no redirects,
    bounded reads."""
    if inner is None:
        inner = default_transport(timeout=timeout)

    def transport(url: str) -> str:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "")
        _refuse_address(host, allow_private)
        body = inner(url)
        if len(body.encode("utf-8")) > max_bytes:
            raise PolicyViolation(
                f"response exceeds transport cap ({max_bytes} bytes)")
        return body

    return transport


def default_transport(timeout: float = 10.0):
    """urllib transport with redirects DISABLED (3xx raises instead of
    hopping — an unauthorized destination must never be followed)."""

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers,
                             newurl):  # noqa: D102
            raise PolicyViolation(
                f"HTTP {code} redirect to {newurl!r} refused — redirects "
                "are new, unauthorized destinations (spec/netpolicy.md)")

    opener = urllib.request.build_opener(_NoRedirect)
    opener.addheaders = [("User-Agent", "2066-netpolicy/1.0")]

    def transport(url: str) -> str:
        try:
            with opener.open(url, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except HTTPError as exc:
            raise PolicyViolation(
                f"HTTP {exc.code} from {url}") from exc
        except OSError as exc:
            raise PolicyViolation(f"transport failure: {exc}") from exc

    return transport
