# Language reference

Complete reference for 2066 v0.8. The normative contracts are the
[specifications](../spec/); this page is the user-facing consolidation.

## 1. Programs

A `.ai` file is UTF-8 text containing, in any order:

- **entity declarations** — semantic database tables;
- **node blocks** — the executable graph (main scope);
- **function declarations** — named subgraphs with their own node blocks.

Blank lines and `#` comments are ignored. Each non-blank line is a header
or exactly one field. Unknown constructs are structured errors, never
warnings.

### Canonical form and identity

Layout (whitespace, comments, field order, declaration order) is a *view*.
The runtime canonicalizes programs — fixed field order, sorted nodes and
functions, re-rendered literals — and the canonical form's SHA-256 is the
program's identity:

```bash
python -m runtime hash program.ai
# sha256:e6e0db153dac5968b2b21ef80f44a76d49f142f36dcc3ce827b044d726494ded
```

Two sources with the same hash are the same program, whatever text they
were written as. Use `python -m runtime repair` to output the canonical
form of a repaired program.

### Program headers (optional)

```text
format-version 1
protocol 0.2
```

`format-version` must match the runtime's file format (E109). `protocol`
declares the protocol semver the program targets; a runtime outside the
compatible range refuses to run it (E109) — never silently misreads it
(plan §30).

## 2. Nodes

```text
node <id>
<field> <value>          # one field per line
```

- `node_id`: digit string (`001`), globally unique across all scopes.
- Fields (each at most once per node):
  - `op` (required) — operation name
  - `input` — one or more input node ids, on one line
  - `output` — declared result type
  - op-specific: `type`, `value`, `mode`, `callee`, `entity`, `column`,
    `where`, `set`, `algorithm`

Example:

```text
node 003
op multiply
input 001 002
output i64
```

## 3. Scopes

- Nodes before any `func` header belong to **main**.
- `func <name>` opens a function scope; `main` returns to the main scope.
- Node ids are globally unique across scopes.
- Functions must contain exactly one `return`; parameter indexes are
  `0..k-1`.
- `emit` is legal only in main; `param`/`return` only inside functions.

```text
func name
node 101
op param
index 0
type i64
...

main

node 001
...
```

## 4. Entities

```text
entity note {
id identity
owner_id i64
title string
body string
}
```

- First column must be `id identity`; exactly one identity column.
- Column types: `identity`, `bool`, `i64`, `f64`, `string`; optional
  `unique` modifier.
- The runtime creates the SQLite table; all SQL is runtime-generated with
  bound parameters. Programs reference columns by name; unknown names are
  validation errors.
- Column order is semantic for `data.insert` (values bind positionally).

## 5. Types

| Type | Literal example | Renders as |
|---|---|---|
| `bool` | `true` | `true` / `false` |
| `i64` | `-7` | decimal, range −2⁶³…2⁶³−1 |
| `f64` | `1.05` | shortest round-trip decimal (`42.0`, `0.30000000000000004`) |
| `string` | `"line\nbreak"` | raw characters |
| `bytes` | `0xDEADbeef` | `0x` + lowercase hex |
| `null` | `null` | `null` |

Guarantees:

- **i64 overflow is an error** (E302), never silent wraparound; i64
  division truncates toward zero; division by zero is E301.
- **f64 is IEEE 754**, total: `1.0/0.0 → inf`, `0.0/0.0 → nan`.
- **No implicit coercion.** `cast` is the only conversion; string→number
  casts accept canonical literals (f64 casts also accept integer form).
  Failures are E303/E304.
- `bool` and `i64` are disjoint even if a host language conflates them.

## 6. Execution

- Nodes evaluate in a deterministic topological order (ties by numeric id);
  function calls evaluate callees-first; the call graph must be acyclic.
- **Everything evaluates** — `branch` selects values but does not skip
  computation. Guard side effects by making both arms safe.
- Output channels: `emit` (batch, ordered by node id) and `system.write`
  (immediate). At least one is required in main.
- Data operations require a database (`--db`) and matching capability
  grants (`--caps`); both default to deny.

## 7. Errors

Every failure is a structured record — stable code, node, operation,
`expected`/`received`, and repair suggestions:

```text
ERROR E203

node: 003
operation: add

expected:
  input[1]: i64

received:
  input[1]: string

allowed_repairs:
  - cast node 002 -> i64
```

Families: E1xx parse · E2xx validation · E3xx runtime · E4xx authority
denial · E5xx data. Exit codes: 0 ok, 1 validation, 2 runtime, 3
usage/trust, 4 denied. Full table: [spec/errors.md](../spec/errors.md).
`--json` makes every output machine-readable for repair loops.

## 8. Guarantees

- **Deterministic** — same program ⇒ byte-identical output and errors.
- **Total** — no undefined behavior anywhere, including division, casts,
  cycles, and malformed programs (all structured errors).
- **Terminating** — DAG scopes, acyclic call graph.
- **Authority-bounded** — effects only behind capabilities; programs
  cannot mint or widen authority.

Not (yet) in the language: loops, collections, string interpolation,
network/process effects. See [ROADMAP.md](../ROADMAP.md).

## 9. Effectful operations beyond data

- `net.fetch` (NETWORK effect): outbound GET on the input URL string →
  body string. Egress is an allowlist: a `net.request` grant names the
  hostname (a grant on a parent domain covers its subdomains). The
  host supplies the transport; the runtime owns no sockets. Failures
  are E560.
- **Guarded writes** — `data.insert` / `data.update` / `data.delete`
  accept `when <bool-node>`: a false guard is a verified no-op (0
  rows, no effect). Because `branch` is eager, guards are THE way to
  make denied mutations impossible, not hidden in untaken arms.
- Session tokens: `session.verify` (IDENTITY effect) — programs
  verify, only hosts mint.

