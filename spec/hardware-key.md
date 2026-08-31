# spec/hardware-key.md — 2066 KEY v1: any disk as a human authority key

Status: normative for M9 (software-defined hardware preparation).
Implements roadmap §31–§33 posture with today's ubiquitous hardware: any
removable disk — including an old flashdisk — becomes the physical human
approval object. Non-destructive: files already on the disk are untouched.

## Threat model — read this first

Honest guarantees, no marketing:

| Property | Status |
|---|---|
| Secret at rest | PIN-encrypted (HKDF-SHA256 → AES-256-GCM). Copying the file yields ciphertext; wrong PIN never yields a seed. |
| Bearer property | **Possession = authority.** Like a house key: stealing the disk defeats it. A flashdisk has no secure element — full-disk imaging plus offline brute-force of a weak PIN is possible. Use a long PIN. |
| Attempt limiting | Best-effort: 8 wrong PINs destroy the secret. An attacker who images the disk first can restore the counter — documented limitation, not a hidden claim. |
| The upgrade path | The envelope is identical to what a secure element exposes (identity + signing). Phase 10 (FIDO2/secure-element keys) presents the same interface; callers never change. |

## Directory layout (created on the disk)

```text
<disk>/.2066key/
    KEYFORMAT      "2066KEY1" + version + created + agent_id (plain text)
    identity.json  {agent_id, algorithm: ed25519, public_key, created}
    secret.enc     salt(16) ‖ nonce(12) ‖ AESGCM(HKDF(pin, salt))(seed_hex)
    attempts       decimal wrong-PIN counter (reset on success)
```

The key's identity is a normal 2066 ed25519 identity — anything the
identity system verifies (grant signatures, proposals) works unchanged.

## CLI

```bash
# format any disk (interactive PIN prompt; existing files untouched)
python -m runtime key-format E:/ --id human-ronel

# inspect (public info + attempt counter)
python -m runtime key-inspect E:/

# §33 approval: sign a grants file as the human, with a short TTL
python -m runtime approve wanted.json --key E:/ --ttl-minutes 5 --out signed.json
python -m runtime run program.ai --caps signed.json --require-signed
```

Safety rails: refuses the system drive, the home directory, and
non-removable roots unless `--force`; refuses missing paths.
`--pin` exists for scripting/tests — interactive prompts are the default.

## The §84 flow, achieved in software

1. Agent requests an effect → **E401 DENIED** (no capability).
2. Human inserts the key disk and runs `approve` (PIN unlock) → a
   signed delegation with `issued_by: human-<id>` and `expires` set.
3. Agent runs under the approved grant → **allowed** (`--require-signed`).
4. Past expiry → **E402 DENIED** (verify with `--now`).

Tampering with the approved file breaks the signature and refuses the
whole grant set — approval authority cannot be widened after the fact.

## What this is preparation FOR

- Phase 10: the same CLI over a real secure element (FIDO2 HMAC-secret
  or a 2066-branded key); only `runtime/keydisk.py` swaps.
- Phase 11: multisig — m-of-n key disks required to approve widening
  grants (GrantSet extension).
- Phase 12: delegation chains — approved grants record the human
  issuer, enabling "which human delegated what, to whom, for how long".
