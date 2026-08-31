# spec/canonicalization.md — Canonical form (normative)

One canonical text per program (spec source: runtime/serialize.py;
property tests P1/P2 pin it):

1. Entities sorted by name, columns in declared order.
2. Main nodes sorted by ascending numeric id.
3. Functions sorted by name; a function's nodes sorted by numeric id.
4. Node fields in fixed order: op, index, type, value, mode, callee,
   input, output.
5. Literals re-rendered canonically: strings re-quoted with escapes
   (`\" \ \n \t`), f64 shortest round-trip (`42.0` stays `42.0`),
   i64 decimal, bool `true/false`, bytes lowercase hex.
6. Blocks joined by blank lines; file ends with a newline. Comments and
   source formatting are NOT canonical content.

Identity: `program_hash = "sha256:" + SHA-256(canonical UTF-8)`.
Formatting changes never change identity; any semantic change always
does. The conformance corpus (protocol/conformance/) freezes identity
for every shipped program.
