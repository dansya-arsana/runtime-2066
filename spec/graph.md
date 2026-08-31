# spec/graph.md — Program Format and Node Model

## File grammar

A `.ai` file is UTF-8 text: node blocks in one or more **scopes**. Blank
lines and `#` comments (outside string literals) are ignored. Each
non-blank line is a header or exactly one field.

```ebnf
program     = { node_block } , { func_section } ;
func_section = "func" , func_name , { node_block } , { "main" , { node_block } } ;
node_block  = node_header , { field_line } ;
node_header = "node" , node_id ;
field_line  = ( "op" | "type" | "value" | "output" | "mode" | "callee" | "index" ) , value ;
            | "input" , node_id , { node_id } ;
node_id     = digit , { digit } ;
func_name   = ( letter | "_" ) , { letter | digit | "_" } ;
```

Rules:

- Node ids are digit strings (`001`, `042`) compared **exactly as written**;
  ordering uses their numeric value. Ids are **globally unique** across all
  scopes.
- `func <name>` opens a function scope; nodes after it belong to that
  function. The bare header `main` returns to the main scope. Nodes before
  any `func` belong to main.
- A field appears at most once per block (`input` included — list all
  inputs on one line).
- Fields may appear in any order within a block; order is never semantic
  (the canonical serializer emits them in a fixed order).
- Any statement before the first header is error **E101**; an empty program
  is **E108**.

## Node fields

| Field    | Meaning                              | Used by                         |
|----------|--------------------------------------|---------------------------------|
| `op`     | operation name (required, all nodes) | all                             |
| `type`   | declared type of a `const`/`param`   | `const`, `param`                |
| `value`  | canonical literal                    | `const`                         |
| `input`  | 0–3 input node ids (call: one per argument) | all except `const`, `param` |
| `output` | declared result type                 | required: arithmetic, compare, branch, cast, call; optional: `copy`; forbidden: `const`, `param`, `emit`, `return` |
| `mode`   | comparison mode                      | `compare`                       |
| `callee` | called function name                 | `call`                          |
| `index`  | parameter position (0-based)         | `param`                         |

Deviations are structured errors: unknown/extra field **E102**, missing
field **E103**, unknown type **E106**, bad literal **E105**, bad mode **E208**,
malformed header **E107**, malformed/duplicate function **E109**.

## Scope rules

- `emit` is legal **only in main**; `param`/`return` **only inside
  functions** (violations: **E214**).
- A function must contain exactly one `return` (**E215**) whose param
  indexes are exactly `0..k-1` (**E216**).
- Inputs may only reference nodes in the **same** scope (**E202**).
- The function call graph must be acyclic (**E212**); combined with DAG
  bodies (**E204**) this guarantees every program terminates.

## Graph properties (validated, in this order)

1. Per-node structure, per scope (main first, functions in declaration
   order): op known (**E201**), fields legal, arity exact (**E207**),
   literal/mode/type valid, scope placement legal (**E214**), function
   shape (**E215**, **E216**).
2. Every `call` targets an existing function (**E210**) with matching
   argument count (**E211**).
3. The call graph is acyclic (**E212**); the callee-before-caller order is
   recorded.
4. Every `input` references a node in the same scope (**E202**).
5. Each scope is a DAG (**E204**, reported with the cycle path).
6. Types infer without conflict (**E203**) and declared `output`s match
   (**E205**).
7. Main contains at least one `emit` (**E206**).

The **first** error in this order is reported; all others are suppressed.

## Execution and output

- Nodes evaluate in a deterministic topological order; ties break by numeric
  node id. Functions evaluate callees-first; calls bind arguments to params
  positionally. There are no loops and no recursion, so every program
  terminates.
- `emit` is the sole output channel (main only). Its value is printed as
  one line.
- Multiple `emit` nodes print in ascending numeric node id order — never in
  declaration order.
- Canonical value renderings (see spec/types.md): `i64` decimal, `f64`
  shortest round-trip decimal, `bool` `true`/`false`, `string` raw,
  `bytes` `0x` + lowercase hex, `null` `null`.

## Canonical serialization and program identity

`serialize_program` emits main nodes **by ascending node id**, then each
function **by name**, each function's nodes by ascending id. Within a
block, fields are emitted in the fixed order
`op, index, type, value, mode, callee, input, output`, and literals are
re-rendered in canonical form (`+5` → `5`, `1.50` → `1.5`, `0xDE` →
`0xde`, strings re-escaped). Declaration order, comments, whitespace, and
field order are views — the canonical form erases them, so serializing is
idempotent: `serialize(parse(serialize(p))) == serialize(p)`.

The canonical form is the **primary artifact** (roadmap §15): its SHA-256
(`program_hash`, `python -m runtime hash <file>`) is the program's
identity for signatures, provenance, and reproducibility. Two sources with
the same hash are the same program, whatever text they were written as.
