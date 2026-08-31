# spec/errors.md — Structured Error Protocol

Errors are designed for agents, not humans (roadmap §13): stable codes,
machine-checkable fields, and repair suggestions that a repair loop can act
on. The same invalid program always produces the same error — determinism
is what makes automatic repair possible.

## Error codes

| Code | Phase | Meaning |
|------|-------|---------|
| E101 | parse | statement outside any node block |
| E102 | parse | invalid field: unknown, duplicate, empty, or not allowed for this op |
| E103 | parse | missing required field (`op`, `type`, `value`, `mode`, `output`, `callee`, `index`) |
| E104 | parse | duplicate node id (global across scopes) |
| E105 | parse | literal not valid for its declared type |
| E106 | parse | unknown type name |
| E107 | parse | malformed header (node id or `main` with arguments) |
| E108 | parse | empty program (no node blocks) |
| E109 | parse | malformed or duplicate `func` declaration |
| E201 | validate | unknown operation |
| E202 | validate | `input` references an unknown or cross-scope node |
| E203 | validate | type mismatch (with `expected` / `received` / `allowed_repairs`); includes illegal cast pairs and call argument mismatches |
| E204 | validate | dependency cycle within a scope |
| E205 | validate | declared `output` type disagrees with inferred type |
| E206 | validate | main contains no `emit` node |
| E207 | validate | input arity mismatch |
| E208 | validate | unknown `compare` mode |
| E210 | validate | `call` references an unknown function |
| E211 | validate | call argument count does not match function params |
| E212 | validate | function call cycle (recursion) |
| E214 | validate | operation not allowed in this scope (`emit` in function; `param`/`return` in main) |
| E215 | validate | function must contain exactly one `return` |
| E216 | validate | function param indexes must be exactly 0..k-1 |
| E301 | runtime | division by zero (i64) |
| E302 | runtime | i64 overflow |
| E303 | runtime | f64 value not representable as i64 in `cast` |
| E304 | runtime | string not parseable as a number in `cast` |
| E305 | runtime | filesystem IO error (missing/unreadable/undecodable) |
| E401 | authority | denied: no capability grants this action on this resource |
| E402 | authority | denied: applicable capability has expired |
| E403 | authority | denied: capability size limit exceeded |
| E501 | runtime | unknown entity in a `data.*` operation |
| E502 | runtime | unknown column in a `data.*` operation |
| E503 | runtime | the identity column cannot be updated |
| E505 | runtime | SQLite error (constraint violation, malformed use) |
| E401 | authority | denied: no capability grants this action on this resource |
| E402 | authority | denied: applicable capability has expired |
| E403 | authority | denied: capability size limit exceeded |

## Text format (default, matches roadmap §13)

```text
ERROR E203

node: 003
operation: add

expected:
  input[0]: i64
  input[1]: i64

received:
  input[0]: i64
  input[1]: string

allowed_repairs:
  - cast node 002 -> i64
  - replace node 002
```

Sections (`node`, `operation`, `line`, `expected`, `received`, `detail`,
`allowed_repairs`) appear only when applicable. Rendering is deterministic.

## JSON format (`--json`)

The same error as one JSON object on stderr (keys sorted, nulls omitted):

```json
{"allowed_repairs": ["cast node 002 -> i64", "replace node 002"],
 "code": "E203", "expected": {"input[0]": "i64", "input[1]": "i64"},
 "node": "003", "operation": "add",
 "received": {"input[0]": "i64", "input[1]": "string"}}
```

Success output in `--json` mode: `{"ok": true}` for `validate`,
`{"emits": [...], "ok": true}` for `run`. For `repair`:
`{"applied": [...], "emits": [...], "ok": true, "program": "...", "rounds": 1}`.

## Repair loop

`python -m runtime repair <file>` writes the **canonical repaired program**
to stdout (composable: pipe it into `run`) and diagnostics to stderr.
Only `cast` repairs are applied mechanically; `replace` repairs require an
author, so the loop stops and reports when only those remain. Exit codes
below carry the final state; `--json` adds `applied`, `rounds`, `program`,
and `emits`/`error` to the payload.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | executed / validated / repaired |
| 1 | parse or validation error (E1xx, E2xx) |
| 2 | runtime error (E3xx) |
| 3 | usage or IO error |
| 4 | authority denial (E4xx) — the program ran, the policy said no |

Program output goes to stdout only; errors go to stderr only.

## Namespace policy (plan SS33)

Codes are protocol: changing one is a compatibility event. Current
families: E1xx parse/canonical · E2xx typing/graph · E3xx runtime
value · E4xx authority · E5xx data+storage+network (E501-505 storage,
E560 transport) · E6xx proposals. The plan's finer split (E7xx storage,
E8xx transport, E9xx evidence) is a FUTURE major-version remap with
migration aliases — not applied now, precisely because codes are
protocol.
