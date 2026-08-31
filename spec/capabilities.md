# spec/capabilities.md — Capability model (normative)

Actions (closed set): `filesystem.read`, `filesystem.write`,
`data.read`, `data.write`, `data.delete`, `net.request`.

1. No grant set ⇒ zero authority (default deny, E401).
2. Scopes: filesystem = path prefix; data = entity name; net =
   hostname (a grant on a domain covers its subdomains, nothing else).
3. Grants expire (`expires`, E402), may be size-capped
   (`max_bytes`, E403), revocable (revocation lists), hash-bound
   (delegations, E408), multisig (m-of-n in the signed payload), and
   issuer-pinned (trust stores).
4. Envelopes: ed25519-signed canonical payloads. Signed envelopes are
   always verified; unsigned envelopes are accepted ONLY in the
   development profile (SS44 transition; production/sovereign refuse).
5. No `*`, `admin`, or catch-all scopes will be added (SS46).
6. Delegation chains may only narrow (scope ⊆ parent, expiry ≤
   parent).

Programs declare required capabilities statically; runtime checks at
the effect boundary — both are visible to `2066 inspect`.
