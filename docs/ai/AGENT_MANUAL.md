# 2066 Agent Authoring Manual

You are authoring programs in **2066**, an AI-native semantic language.
Programs are graphs in canonical text (`.ai` files), validated before
execution. This manual is complete: with it you can generate valid
programs on the first attempt. Machine-readable reference:
`python -m runtime reference` (also `docs/ai/reference.json`).

## Workflow — always, in this order

1. **DRAFT** the `.ai` program (grammar below).
2. **`python -m runtime effects p.ai --json`** — the authority manifest.
   If it lists anything beyond `PURE`/`SYSTEM`, you need grants (`--caps`)
   and possibly `--db`. Never assume authority exists; it is default deny.
3. **`python -m runtime validate p.ai`** — must print `OK` before you
   claim success.
4. **`python -m runtime run p.ai --json`** — execute.
5. On E1xx/E2xx: fix using `expected`/`received`/`allowed_repairs`.
   On E401: you lack authority — do not retry; report the required
   manifest to the human. **Never fabricate grant files.**

## Rules

- One canonical form per construct — no syntax alternatives.
- The graph is a DAG; the call graph is acyclic; **everything evaluates**
  — `branch` selects values, it does not skip computation. Because of
  this, guard effectful writes with `when <bool-node>` on
  `data.insert`/`data.update`/`data.delete`: a false guard is a verified
  no-op (returns 0, zero rows). No loops, no recursion. Lists are values (from
  `data.list`), consumed via `list.length`/`list.get`/`list.join` — there
  is no iteration construct.
- No implicit coercion: `cast` is the only conversion.
- All arithmetic operands must be the same type.
- Failure is always a structured error with a stable code; `--json` gives
  you `{code, node, operation, expected, received, allowed_repairs}`.

## Program headers (optional)

`format-version 1` must match the runtime. `protocol 0.2` declares the
protocol you target — incompatible runtimes refuse (E109) rather than
misread. Omit both for portable V0 programs.

## Grammar

```text
program   := (entity | node_block | func | "main")*
entity    := "entity" NAME "{" column+ "}"          column := NAME TYPE [unique]
node_block:= "node" ID "\n" field_line+            ID := digits, globally unique
func      := "func" NAME node_block+                # exactly one "return" inside
field     := ("op"|"type"|"value"|"output"|"mode"|"callee"|"index"|"entity"|
              "column"|"where"|"set"|"algorithm"|"when") VALUE
            | "input" ID+                           # all inputs on one line
```

- One field per line; each field at most once per node. Field order is
  irrelevant; node ids compare as written, order by numeric value.
- Scopes: nodes before `func`/after `main` are main. `emit` only in main;
  `param`/`return` only in functions.
- `#` comments; blank lines ignored.

## Types

`bool` (`true`/`false`) · `i64` (decimal, −2⁶³…2⁶³−1) · `f64` (needs `.` or
exponent; renders shortest round-trip, `42.0` stays `42.0`) · `string`
(double-quoted, escapes `\" \\ \n \t`) · `bytes` (`0x` + hex pairs) ·
`null`. Arithmetic: i64 truncating division, ÷0=E301, overflow=E302;
f64 IEEE total. Renders: `42.0` stays `42.0`, bool `true/false`, bytes
lowercase hex.

## Operations (30 — complete table)

| op | inputs → output | required fields | effect | notes |
|---|---|---|---|---|
| `const` | — → declared type | `type` `value` | PURE | literal |
| `copy` | any → same | — | PURE | optional `output` |
| `add` `subtract` `multiply` `divide` | 2 same-type (i64\|f64) → same | — | PURE | ÷0 E301, overflow E302, f64 IEEE |
| `compare` | 2 same-type → bool | `mode` (eq ne lt le gt ge) | PURE | ordered modes: i64/f64/string |
| `branch` | bool, T, T → T | — | PURE | pure select |
| `cast` | any → declared `output` | — | PURE | pairs: i64⇄f64, string→i64/f64, i64/f64/bool→string; E303/E304 |
| `call` | args → return | `callee` | PURE* | *inherits callee effects |
| `param` | — → declared type | `type` `index` | PURE | func only |
| `return` | 1 → same | — | PURE | func only, exactly one |
| `emit` | 1 → prints | — | SYSTEM | main only, batch channel |
| `concat` | 2 strings → string | — | PURE | build strings via chains |
| `system.read` | — → string | — | SYSTEM | one stdin line; EOF → `""` |
| `system.write` | string → i64 chars | — | SYSTEM | immediate, no newline |
| `crypto.digest` | string → hex string | `algorithm` (sha256) | PURE | |
| `filesystem.read` | path → contents | — | FILESYSTEM_READ | cap: `filesystem.read` |
| `filesystem.write` | path, content → i64 bytes | — | FILESYSTEM_WRITE | cap: `filesystem.write` |
| `data.insert` | column values (declared order) → i64 rowid | `entity` | DATA_WRITE | cap: `data.write`; needs `--db` |
| `data.count` | where value → i64 | `entity` `where` | DATA_READ | cap: `data.read` |
| `data.select` | where value → column value | `entity` `column` `where` | DATA_READ | cap: `data.read`; absent → type default |
| `data.update` | new, where → i64 rows | `entity` `set` `where` | DATA_WRITE | cap: `data.write` |
| `data.delete` | where value → i64 rows | `entity` `where` | DATA_WRITE | cap: **`data.delete`** (read ≠ delete); optional `when` guard |
| `net.fetch` | URL string → body string | — | NETWORK | outbound GET; host must be allowlisted by a `net.request` grant (parent domain covers subdomains); host supplies transport; failure E560 |
| `session.verify` | token string → i64 subject_id | — | IDENTITY | needs `--session-key`; E406 forged, E407 expired; **programs cannot mint tokens** |
| `data.list` | where value → list\<col type\> | `entity` `column` `where` | DATA_READ | cap: `data.read`; all matching rows, id order; needs `--db` |
| `list.length` | list → i64 | — | PURE | |
| `list.get` | list, i64 → element | — | PURE | E308 out of range |
| `list.join` | list\<string\>, sep → string | — | PURE | build display strings |

Multi-value selects (operators, states): use a priority cascade of
`branch` — `res = branch is_A a_val (branch is_B b_val (branch is_C ...))`
— see `examples/calculator.ai`.

## Entities & data

```text
entity note {
id identity
owner_id i64
title string
}
```

First column must be `id identity`; types: identity|bool|i64|f64|string.
Column order is semantic for `data.insert` (values bind positionally).
Run with `--db file.db` (else E401) and grants per entity+action.

## Error codes

E101 statement outside block · E102 bad field · E103 missing field ·
E104 duplicate node id · E105 bad literal · E106 unknown type ·
E107 malformed header · E108 empty program · E109 bad func decl ·
E201 unknown op · E202 unknown/cross-scope input · E203 type mismatch ·
E204 cycle · E205 output mismatch · E206 no output channel · E207 arity ·
E208 bad compare mode · E210 unknown callee · E211 call arity ·
E212 recursion · E214 wrong scope · E215 missing return · E216 bad param
indexes · E301 ÷0 · E302 i64 overflow · E303 f64→i64 unrepresentable ·
E304 bad string→number · E305 filesystem IO · E308 list index out of
range · E401 no capability · E402 expired · E403 over limit · E410 resource budget exceeded (deterministic) ·
E406 session token invalid · E407 session expired · E408 delegation
bound to other program · E501 unknown
entity · E502 unknown column · E503 identity update · E505 SQLite
error · E560 net.fetch transport failure · E601 proposal base moved · E602 proposal signature ·
E603 proposal conflict · E604 proposal malformed.

Exit: 0 ok · 1 validation · 2 runtime · 3 usage/trust · 4 denied.

## Minimal examples

Hello:
```text
node 001
op const
type string
value "Hello, World!"

node 002
op emit
input 001
```

Two-operand calculation with a guarded division:
```text
node 001
op const
type f64
value 12.0

node 002
op const
type f64
value 0.0

node 003
op divide
input 001 002
output f64

node 004
op emit
input 003
```

Database insert (needs `--db notes.db --caps caps.json`, grant
`data.write:note`):
```text
entity note {
id identity
owner_id i64
title string
body string
}

node 001
op const
type i64
value 1

node 002
op const
type string
value "title"

node 003
op const
type string
value "body"

node 004
op data.insert
entity note
input 001 002 003
output i64

node 005
op emit
input 004
```

## Resource budgets (E410)

Every execution runs under a resource budget (nodes, steps, literal
bytes, list items, call depth, io bytes, rows). Hostile-size programs
are rejected deterministically with E410 — same program + same budget,
same refusal. Budgets are authority: if a task legitimately needs more,
the host raises the spec; never try to work around E410.

## Semantic packages & inspect

Applications ship as packages under `programs/`: a `package.ai`
manifest declares modules; a unit is one program addressed as
`package::module::unit` (spec/packages.md). The address is identity —
the filesystem is storage.

```bash
python -m runtime list                       # what exists
python -m runtime inspect sales::business::add   # full context card
```

`inspect` returns hash, node count, stdin inputs, outputs, effects,
required capabilities, and dependencies — everything needed to modify a
unit safely without reading unrelated files. Prefer it over browsing.

## Authority — non-negotiable

- Effects without `--caps` / `--db` are denied (E401). That is correct
  behavior; do not work around it.
- Grant files are human policy. Never create, edit, or sign one unless the
  human provided the signing key for exactly this purpose.
- If a task needs authority you don't have: report the `effects` manifest
  and request the specific grants. Stop there.
- Stolen/key-copied delegations: hash-bound (`approve --for-hash`) and
  revocable (`revoke`) — assume every delegation you receive may be
  checked, bound, and revoked at any time.
