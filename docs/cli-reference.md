# CLI reference

All commands run from the repository root via the runtime package
(`python -m runtime ...`) or the wrapper (`bin/2066 ...`).

## run

```bash
python -m runtime run <program.ai> [--adapter tree|plan]
                     [--caps grants.json] [--require-signed]
                     [--db file.db] [--now iso-8601] [--json]
```

Validates and executes the program. Program output goes to stdout;
errors go to stderr.

| Flag | Meaning |
|---|---|
| `--adapter tree` | tree-walking interpreter (default). |
| `--adapter plan` | compiled-plan stack VM — an independent engine; identical results (Appendix F.3). |
| `--caps file` | attach the capability grant set. Signed envelopes are always verified fail-closed. **Without it, all effects are denied.** |
| `--require-signed` | refuse unsigned capability files. |
| `--db file` | attach the SQLite data plane (creates entity tables). **Without it, data operations are denied.** |
| `--now iso` | freeze the capability clock (deterministic expiry tests). |
| `--json` | machine-readable output on stdout. |

## validate

```bash
python -m runtime validate <program.ai> [--json]
```

Parse and validate only; prints `OK` or the structured error. No effects
can occur.

## repair

```bash
python -m runtime repair <program.ai> [--json]
```

Runs the mechanical repair loop: validates, applies the `cast` repairs it
itself prescribed (inserting `cast` nodes and rewiring inputs), and prints
the **canonical repaired program** to stdout — pipe it into `run`.
`replace` repairs need an author (the AI), so the loop stops and reports
when only those remain.

## hash

```bash
python -m runtime hash <program.ai> [--json]
```

Prints the program's canonical identity: `sha256:<hex>`. Insensitive to
comments, whitespace, field order, and declaration order — the same
program always hashes the same.

## effects

```bash
python -m runtime effects <program.ai> [--json]
```

Prints the static effect manifest — the sorted effect classes the program
can perform, including effects inherited through `call`. Run this
**before** executing anything untrusted: it states what authority
execution would need.

## export

```bash
python -m runtime export <program.ai> --target python|javascript
                         [--out file] [--library]
```

Lowers the validated program to standalone conventional source (§10).
Deterministic; header carries the canonical hash. `--library` (JavaScript)
omits main and exposes `globalThis.Calc2066`. Capability-gated effects
(`FILESYSTEM_*`, `DATA_*`) are refused — exported code runs outside the
authority plane.

## keygen

```bash
python -m runtime keygen <identity.json> [--id agent-A91] [--json]
```

Generates an ed25519 identity: `<identity.json>` (public) plus
`<stem>.key` (secret — never commit).

## sign-caps

```bash
python -m runtime sign-caps <caps.json> --agent <identity.json> --key <secret.json> [--out signed.json]
```

Signs a grants file. The signature covers scopes, limits, expiry, issuer,
and `issued_at` over the canonical JSON form.

## verify-caps

```bash
python -m runtime verify-caps <signed.json> [--json]
```

Verifies a signed grants file and prints issuer/subject/grant count.

## evidence

```bash
python -m runtime run <program.ai> --db n.db --caps c.json --evidence audit.jsonl
python -m runtime evidence <audit.jsonl> [--json]
```

With `--evidence`, every privileged action (data write) appends a
hash-chained record to the JSONL log: action, resource, subject, the
program's canonical hash, timestamp, and the previous record's hash.
`evidence <file>` verifies the chain — edited, deleted, or reordered
records are all detected (exit 1). No keys required: tamper-evidence by
construction.

## migrate

```bash
python -m runtime migrate <program.ai> --db <file.db> [--json]
```

Diffs the program's entity declarations against the database schema.
Additive steps (new table, new column) apply automatically with rows
preserved. Destructive steps (column removal, type change) are reported
with data-loss detail and **refused** (exit 1) — destructive migration is
a human decision, never an agent's (§25).

## propose / verify-proposal / merge

```bash
python -m runtime propose <new.ai> --base <base.ai> --agent <id.json> --key <secret.key> [--out p.json]
python -m runtime verify-proposal <p.json> --base <base.ai> [--json]
python -m runtime merge <base.ai> --proposals a.json,b.json [--out merged.ai] [--json]
```

The semantic mutation protocol (§29–§30): agents do not edit files — they
sign node-level diffs against the base program's canonical hash.
`verify-proposal` fails closed on bad signatures (E602), stale bases
(E601, "the graph moved; re-proose"), and malformed shapes (E604).
`merge` auto-merges disjoint changes (the result must re-validate —
invalid merges are rejected, never half-applied), dedupes identical
changes, and rejects same-unit conflicts naming the unit and both agents
(exit 1). Example: `examples/proposals/`.

## key-format / key-inspect / approve

```bash
python -m runtime key-format <disk> [--id human-1] [--force]   # PIN prompt
python -m runtime key-inspect <disk> [--json]
python -m runtime approve <caps.json> --key <disk> [--ttl-minutes 5] [--out signed.json]
```

Turn any removable disk — including an old flashdisk — into the human
approval object (KEY v1, [spec/hardware-key.md](../spec/hardware-key.md)):
non-destructive, PIN-encrypted ed25519 identity at `.2066key/`, 8 wrong
PINs destroy the secret. `approve` is §33: the human signs a grants file
as a delegation (`issued_by: human-…`), optionally with a short TTL —
then `run --caps signed.json --require-signed` executes the §84 flow:
denied → approved → allowed → expired → denied. Safety rails refuse the
system drive and home directory. Honest limits (bearer object,
best-effort attempt counting) are in the spec.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | parse or validation error (E1xx, E2xx) |
| 2 | runtime error (E3xx) |
| 3 | usage, IO, or trust failure (bad capability file, bad signature) |
| 4 | authority denial (E4xx) — the program ran, the policy said no |
