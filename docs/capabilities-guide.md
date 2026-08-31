# Capabilities guide

Effects (files, data) require **capabilities**: runtime-held grants that
programs can see neither nor change. The runtime decides; the model
proposes. This guide shows how to grant, scope, sign, and verify
authority.

## 1. Default deny

Run any effectful program without `--caps` and it is denied:

```bash
python -m runtime run examples/file_read.ai
# ERROR E401 ... no capability system attached; effects require
# explicit grants (default deny)    (exit code 4)
```

No grants = zero authority. There is no flag that grants "everything".

## 2. Grant files

A grant file is JSON, loaded at process start with `--caps`:

```json
{
  "subject": "agent-A91",
  "grants": [
    {
      "id": "incoming-read",
      "action": "filesystem.read",
      "resource": "examples/incoming",
      "max_bytes": 65536,
      "expires": "2036-01-01T00:00:00Z"
    },
    {"action": "data.read",  "resource": "note"},
    {"action": "data.write", "resource": "note"}
  ]
}
```

| Field | Applies to | Meaning |
|---|---|---|
| `action` | all | one of `filesystem.read`, `filesystem.write`, `data.read`, `data.write`, `data.delete` |
| `resource` | all | path scope (filesystem) or entity name (data) |
| `expires` | all | ISO-8601; expired grants deny with E402 |
| `max_bytes` | filesystem/data | size limit; exceeding denies with E403 |
| `id` | all | optional label |

Rules that matter:

- **Scope matching is component-wise.** `examples/incoming` covers
  `examples/incoming/a.txt` but NOT `examples/incoming.txt`, and never
  the parent. Relative scopes resolve against the working directory.
- **`data.delete` is a separate action** — `data.read:note` cannot delete
  (§24), no matter what the program computes.
- **Write limits are checked before writing.** A denied write leaves the
  disk untouched.
- **Denials are exit code 4** with a structured E401/E402/E403 error —
  supervising agents can distinguish "policy said no" from crashes.

## 3. Signed grants (tamper-evident authority)

Anyone who can edit an unsigned JSON file can widen access. Fix: sign it.

```bash
# one-time: generate an issuer identity (agent.json + agent.key)
python -m runtime keygen agent.json --id issuer-1

# sign the grants file
python -m runtime sign-caps caps.json \
    --agent agent.json --key agent.key --out caps.signed.json

# verify before use
python -m runtime verify-caps caps.signed.json

# run, requiring signed grants
python -m runtime run program.ai --caps caps.signed.json --require-signed
```

The signature covers the entire payload. Editing a scope, raising a
limit, or touching a timestamp makes verification fail — the runtime
refuses the **whole file** (exit 3), never a partial load. `--require-signed`
additionally refuses unsigned files outright; keep secrets (`agent.key`)
off any machine that shouldn't mint authority.

## 4. Databases

Attach SQLite with `--db`:

```bash
python -m runtime run notes_register.ai --db notes.db --caps caps.json
```

Entity tables are created automatically from the program's `entity`
declarations. Data operations are checked per action and per entity:
`{"action": "data.read", "resource": "note"}` allows reading notes but
not users, and never deleting anything (that's `data.delete`).

## 5. Audit before you run

Ask what authority a program *would* need, without executing it:

```bash
python -m runtime effects program.ai
# FILESYSTEM_READ
# PURE
# SYSTEM
```

`call` inherits callee effects, so the manifest is complete even for
programs with functions. A manifest requiring nothing beyond `PURE` and
`SYSTEM` cannot touch your disk — by construction.

## 6. Threat-model honesty

Current known gaps (see [THREAT_MODEL.md](../THREAT_MODEL.md)): unsigned
grants are still accepted by default (use `--require-signed`), path
normalization is not symlink-aware, and computation has no resource
limits yet. The standing rule: no operation ships with ambient authority —
if it has an effect, it has a capability requirement, in both engines,
with denial tests.
