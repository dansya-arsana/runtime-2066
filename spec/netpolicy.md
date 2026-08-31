# spec/netpolicy.md — Transport duties for `net.fetch` (normative)

The capability grant authorizes a **hostname**. Everything between
"hostname allowed" and "bytes returned" is the transport adapter's
duty. A conformant transport MUST:

1. **Resolve-once, then connect** — resolve the granted hostname and
   connect to what was resolved; the name must not be re-resolved
   mid-flight (basic rebinding resistance).
2. **Refuse forbidden address classes** — loopback (127/8, ::1),
   private (RFC1918, ULA), link-local (169.254/16, fe80::/10 — includes
   cloud metadata endpoints), reserved, multicast, unspecified. A grant
   naming such an address explicitly (IP-literal resource) is the only
   way to reach it; `allow_private` exists for local testing only.
3. **Never follow redirects** — an HTTP redirect names a NEW
   destination that was never authorized. 3xx surfaces as a policy
   refusal (E560 at the op layer). Chained redirects are equally
   refused.
4. **Normalize IDN before matching** — hostnames must be punycoded
   before grant comparison; a grant stores the punycode form. Mixed
   Unicode/punycode confusables do not create new authority.
5. **Bound the response** — transports cap bytes; the semantic layer
   additionally counts fetched bodies against the execution budget
   (`max_io_bytes`, canonical E410).
6. **Bound the wait** — transports enforce a timeout; wall-clock
   limits are host-side (never part of deterministic semantics).
7. **TLS policy is deployment policy** — production profiles SHOULD
   verify certificates; sovereign profiles MAY pin. The semantic layer
   only ever sees body text.

The runtime core still owns no sockets: this document binds transport
ADAPTERS, and `runtime/netpolicy.py` is the reference enforcement
(compose it into the host-supplied `net` callable). A transport that
violates any duty is a non-conformant adapter (backend classification,
ADR-006).
