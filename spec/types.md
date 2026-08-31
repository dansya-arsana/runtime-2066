# spec/types.md — Primitive Types and Literals

Six primitive types (roadmap §11). Nothing else exists in V0.

| Type | Literal grammar | Canonical rendering (emit / JSON) |
|------|-----------------|-----------------------------------|
| `bool` | `true` \\| `false` | `true` \\| `false` |
| `i64` | `[+-]?[0-9]+`, range −2⁶³ … 2⁶³−1 | decimal digits |
| `f64` | decimal with `.` and/or exponent; `inf`/`nan` literals are **not** expressible | shortest round-trip decimal (`3.75`, `inf`, `-inf`, `nan`) |
| `string` | double-quoted; escapes `\"` `\\` `\n` `\t` only | raw characters |
| `bytes` | `0x` + hex byte pairs (case-insensitive input) | `0x` + lowercase hex |
| `null` | `null` | `null` |

## i64 semantics (no undefined behavior, roadmap §4.9)

- `add`/`subtract`/`multiply`/`divide` results outside −2⁶³ … 2⁶³−1 raise a
  deterministic runtime error **E302** (`i64 overflow`). There is **no
  wraparound**; silent wrapping would hide agent bugs.
- `divide` truncates toward zero (C-style): `-7 / 2 = -3`, `7 / -2 = -3`.
- Division by zero raises **E301**.

## f64 semantics

- IEEE 754 double precision, deterministic per operation.
- Division by zero follows IEEE: `1.0/0.0 = inf`, `-1.0/0.0 = -inf`,
  `0.0/0.0 = nan` (Python would raise; 2066 is total).
- Rendering uses the shortest decimal string that round-trips — the same
  canonical form produced by Ryu/Grisu-style formatters in any language.

## Coercion

None. Operations that need numeric operands require both inputs to be the
**same** numeric type; `i64`/`f64` mixing is error **E203** with explicit
`cast` repairs. Future `cast` operations will be the only conversion path.

## Type of a runtime value

`bool` is disjoint from `i64` even though an implementation language might
represent one as the other; `compare` and `branch` reject `bool` operands
where numbers are required, and vice versa for ordered comparisons.
