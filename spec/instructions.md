# spec/instructions.md — V0 Instruction Set

V0 has **13 operations**. The pure core mirrors roadmap §11:
`const copy add subtract multiply divide compare branch emit` (M0), plus
`call param return` (§11's call/return, completed in M1) and `cast` (the
executable form of §13 repair hints). Types: `bool`, `i64`, `f64`,
`string`, `bytes`, `null` (spec/types.md). All operations except `emit`
are pure. (Roadmap §80's "10 or fewer operations" described the first
30-day slice; M0 satisfied it with 9.)

## Ops

| Op | Scope | Inputs | Output | Extra fields | Semantics |
|----|-------|--------|--------|--------------|-----------|
| `const` | any | 0 | declared `type` | `type`, `value` | Yields the literal. |
| `copy` | any | 1 | input type | — | Identity; explicit dataflow node. |
| `add` | any | 2 | i64\\|f64 | — | `a + b`, same-type operands only. |
| `subtract` | any | 2 | i64\\|f64 | — | `a − b`. |
| `multiply` | any | 2 | i64\\|f64 | — | `a × b`. |
| `divide` | any | 2 | i64\\|f64 | — | i64: truncated toward zero; ÷0 ⇒ **E301**; overflow ⇒ **E302**. f64: IEEE 754 (÷0 ⇒ ±inf / nan). |
| `compare` | any | 2 | bool | `mode` | `mode` ∈ `eq ne lt le gt ge`. `eq`/`ne`: any same-type pair. Ordered modes: i64, f64, string (codepoint order) only. |
| `branch` | any | 3 | type of arms | — | Pure select: `input[1]` if `input[0]` (bool) else `input[2]`. Arms must share one type. |
| `cast` | any | 1 | declared `output` | — | Explicit conversion; legal pairs below. Failures are runtime errors **E303**/**E304**. |
| `call` | any | one per param | function return type | `callee` | Invoke a named function; arguments bind to params positionally. |
| `param` | func | 0 | declared `type` | `type`, `index` | The `index`-th argument of the enclosing call. |
| `return` | func | 1 | input type | — | Exactly one per function; yields the call's value. |
| `emit` | main | 1 | — | — | Program output channel (see spec/graph.md). |
| `filesystem.read` | any | 1 (path: string) | string | — | Read a UTF-8 file. Requires capability `filesystem.read:<scope>` covering the normalized path. |
| `filesystem.write` | any | 2 (path, content: string) | i64 (bytes written) | — | Write UTF-8 bytes. Requires capability `filesystem.write:<scope>`; scope, expiry, and `max_bytes` are checked **before** anything is written. |
| `system.read` | any | 0 | string | — | One line from stdin (no trailing newline). EOF yields `""` — total, not an error. Implicitly granted. |
| `system.write` | any | 1 (text: string) | i64 (chars written) | — | Immediate stdout write (no newline added). Implicitly granted. This is the interactive output channel; `emit` is the batch channel. |
| `concat` | any | 2 (string) | string | — | String concatenation (roadmap Phase 3 `string.concat`). The only way to build strings; chains compose documents. |
| `crypto.digest` | any | 1 (string) | string | `algorithm` | Hex digest (`sha256` in V1). Deterministic — used for password hashing in the auth demo. |
| `data.insert` | any | one per non-identity column, in declaration order | i64 (row id) | `entity` | Insert a row. Requires `data.write:<entity>`. |
| `data.count` | any | 1 (where value) | i64 | `entity`, `where` | Count rows matching `where`-column = value. Requires `data.read:<entity>`. |
| `data.select` | any | 1 (where value) | column's type | `entity`, `column`, `where` | First matching row's column (defaults when absent: `0`/`0.0`/`""`/`false`). Requires `data.read:<entity>`. |
| `data.update` | any | 2 (new value, where value) | i64 (rows) | `entity`, `set`, `where` | Requires `data.write:<entity>`. |
| `data.delete` | any | 1 (where value) | i64 (rows) | `entity`, `where` | Requires `data.delete:<entity>` — a **separate action** from read (§24). |
| `concat` | any | 2 (string) | string | — | String concatenation (roadmap Phase 3 `string.concat`). The only way to build strings; chains compose documents. |

## Effects and capabilities (Phase 3–4)

Every operation declares its effect (roadmap §4.3, Appendix C.2):

```text
PURE            const copy add subtract multiply divide compare branch cast call param return concat crypto.digest
SYSTEM          emit system.read system.write   (implicit grant: the process stdio channels)
FILESYSTEM_READ   filesystem.read              (capability required)
FILESYSTEM_WRITE  filesystem.write             (capability required)
DATA_READ         data.count data.select       (capability required)
DATA_WRITE        data.insert data.update data.delete  (capability required)
```

### Semantic data runtime (§22–§24)

Entities are declared in the program (`entity user { ... }`, first column
`id identity`) and compiled by the runtime to SQLite tables. The AI never
writes SQL: column names are grammar-validated identifiers, every value is
a bound `?` parameter (injection strings are inert data), and each
operation is capability-checked per entity and action — `data.read` cannot
delete (§24). Attach a database with `--db <file>`; without it, data
operations are denied like every other effect.

`program_effects` (CLI: `python -m runtime effects <file>`) computes the
static manifest — the sorted unique effect set, with `call` nodes
inheriting their callee's effects transitively. This answers "what
authority would executing this program need?" **before** running it.

### Enforcement model (roadmap §17–§20)

- The runtime holds the grant set, loaded once at process start from a JSON
  file (`--caps`). The instruction set contains **no operation** that can
  create, read, widen, or revoke a capability — agents cannot mint
  authority.
- **Default deny**: executing an effectful operation with no capability
  system attached is denied (`--caps` omitted means zero authority).
- A grant is `{action, resource, id?, expires?, max_bytes?}`. Scope match
  is component-wise prefix on normalized absolute paths: a grant on
  `/incoming` covers `/incoming/a.txt` but not `/incoming.txt` nor `/etc`.
  Relative scopes resolve against the runtime's working directory at load.
- Denials are structured errors: **E401** no applicable grant, **E402**
  expired, **E403** size limit exceeded (exit code 4). Write limits are
  enforced before any bytes hit the disk. `--now <iso>` freezes the
  capability clock for deterministic tests.
- Computation remains deterministic; only the authority plane is
  time-based (by construction — expiry requires a clock).

## Cast rules

Legal conversions (everything else is a validation error **E203** with
detail `no cast from X to Y`):

| Target | Legal sources | Runtime semantics |
|--------|---------------|-------------------|
| `f64` | `i64`, `string` | exact widening / canonical literal parse (**E304** if unparseable); the string form accepts **both** f64 and i64 canonical forms (`"12"` converts like `12.0` — user input is friendlier than program literals) |
| `i64` | `f64`, `string` | truncate toward zero, must be representable (**E303**); canonical integer literal parse (**E304**) |
| `string` | `i64`, `f64`, `bool` | canonical rendering (spec/types.md) |
| same type | itself | identity |

String→number casts accept exactly what the corresponding literal grammar
accepts — nothing more.

## Type rules

- Operands must already share a type; **there is no implicit coercion**
  (one canonical path per operation, roadmap §8). `i64` + `f64` is a
  deterministic **E203** with cast/replace repairs, not a silent promotion.
  `cast` is the only conversion path.
- A declared `output` that disagrees with the inferred type is **E205**.
- Call argument types must equal the callee's declared param types exactly
  (**E203** with cast repairs per argument).

## Repair loop (roadmap §13, §80)

```text
generate → validate → reject → explain structurally → repair → validate → execute
```

`allowed_repairs` entries of the form `cast node <id> -> <type>` are
**mechanically executable**: `python -m runtime repair` inserts a `cast`
node and rewires the mismatched input slots, then re-validates (bounded
rounds). `replace node <id>` entries remain AI-authored hints — the runtime
cannot invent new intent. The repaired program is emitted in canonical
serialized form.

## Deliberate non-features of V0

- No variables, no loops, no recursion (graphs are DAGs, call graph is
  acyclic — termination is guaranteed).
- No string concatenation, no collections.
- No effects of any kind; `emit` is the only channel that leaves the graph.
