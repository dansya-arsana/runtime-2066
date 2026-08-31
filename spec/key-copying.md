# spec/key-copying.md — Attack analysis: "the attacker copied my key"

The question this spec answers: *an attacker obtains a copy of the key
(the disk, the files, or an image of it) — now what?*

Answer depends on **which key**, because the system has three kinds, and
each fails differently:

| Key kind | Secret at rest | Copy alone defeats it? | Mitigation in v1.1 |
|---|---|---|---|
| Human key disk (KEY v1) | ed25519 seed, PIN-encrypted (HKDF→AES-256-GCM) | **No** — needs the PIN | 8-strike self-destruct, TTL delegations, hash-bound delegations (this spec) |
| Server session key | ed25519 seed on the app host | **Yes, if host is owned** | host compromise is out of scope for the token layer; rotate via re-key |
| Agent identity keys | ed25519 seed files | **Yes** | same treatment as human keys — recommended: move them onto key disks |

## The attack, precisely

Attacker images the flashdisk (or copies `.2066key/`). They hold:
`identity.json` (public — worthless), `secret.enc` (AES-GCM ciphertext),
`attempts` (a counter they can restore).

What they **cannot** do with the copy alone:
- derive the seed without the PIN (AES-GCM + HKDF: no shortcut);
- sign anything (signing needs the seed).

What they **can** do:
1. **Offline brute-force the PIN.** No lockout survives imaging — the
   counter is on their copy. A 4-digit PIN falls in minutes; a 12-char
   passphrase is centuries. PIN strength is the real gate.
2. **Restore the counter** on their copy — the 8-strike self-destruct
   only protects the physical disk if they use *it*, not the image.
3. **Wait.** They already hold a valid delegation file if they stole
   one, until it expires — expiry is the mitigation that always works.
4. **Use the original disk** if they stole the physical object itself.

## Defenses, in layers — what exists and what this spec adds

### Layer 1 (exists): TTL — time is the ultimate revocation
Every human-approved delegation carries `expires`. A stolen approval
dies on its own. Maximum exposure = TTL. Rule: delegation TTLs are
short (minutes); long-lived authority stays on the disk.

### Layer 2 (this spec): hash-bound approvals — copy gains nothing new
`approve --for-hash` binds a delegation to **one canonical program
hash**. The token/grant verifies only against that exact artifact. A
copied key can approve *something*, but the something is fixed,
inspectable, and already published in the evidence chain before
approval. A copied key cannot approve "whatever I want later."

### Layer 3 (this spec): revocation list — kill stolen grants early
`revoke <signed.json|token-id>` publishes the grant/token id to a
revocation file the runtime checks at load and at `session.verify`.
Revocations are themselves hash-chained. Copy the key, steal a
delegation — one revoke command kills the delegation everywhere the
revocation file reached. This closes the "logout is theater" gap for
delegations.

### Layer 4 (this spec): the master key is NOT on the disk — split trust
The deepest fix for copying: the flashdisk should not carry a secret
that *is* the authority. It carries a **factor**. Two-factor approval:
the effective signing key is derived from
`HKDF(disk_secret ‖ host_pinned_secret)` — the disk alone (copied) and
the host alone (attacked) each compute a useless key. Possession +
environment = authority. Cost: approval requires both the disk and the
pinned host. This is the honest software-only approximation of what a
secure element gives you for free (key use without key extraction).

### Layer 5 (future, Phase 10): secure elements
FIDO2/secure-element keys hold the seed in hardware; copies of the
filesystem contain no secret at all. The KEY v1 envelope is designed so
this swaps in behind the same interface.

## Migration / compatibility

- `revoke` and `--for-hash` are additive CLI + library changes; old
  delegations remain valid until expiry (their ids simply never appear
  in the revocation file).
- Two-factor approval is a *new key format flag* (`key-format
  --split-trust`), opt-in, and changes nothing for existing disks.

## Residual risk — stated, not hidden

- Weak PINs die to offline brute-force on a stolen image. Nothing
  software-side fixes a 4-digit PIN; the spec's answer is Layer 2 +
  Layer 3 bounding *what* a stolen key can approve and for *how long*.
- The revocation file must reach every verifier (distribution problem —
  solvable later with the transport layer; solvable today by shipping
  it with deployments).
- A fully-owned host can suppress revocations it receives. Host
  compromise remains the boundary of the whole token layer.
