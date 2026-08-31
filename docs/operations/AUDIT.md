# Audit Events (plan SS64-66)

What the runtime records today, and where:

| Event | Mechanism |
|---|---|
| capability denial / grant checks | structured E401/E402/E403 at every effect (deterministic, replayable) |
| data writes/deletes | DataPlane evidence hook (row counts, entity) — attach an EvidenceLog to get hash-chained records |
| privileged execution | effect manifest per program (`2066 inspect` / `effects`) — statically reviewable before any run |
| proposal submission/merge | signed proposals (E601-604) + deterministic merge |
| release installation | `2066 install-bundle` appends a `release.install` evidence event (what, which release, signature verdict) |
| key rotation / revocation | rotation.log + hash-chained revocation lists |

Privacy (SS65): evidence records metadata and hashes by default —
`detail` carries row counts and ids, not payloads. Payload logging is a
policy decision, never implicit.

Telemetry (SS66): none, in any profile. The core makes no outbound
calls; the only network the runtime can perform is a granted
`net.fetch` from a program.
