# Tutorial — learn 2066 by building

This tutorial walks from hello world to a database-backed application.
Every snippet is a complete, runnable `.ai` file. Run them from the
repository root:

```bash
python -m runtime run myprogram.ai
```

## 1. Hello world

A 2066 program is a graph of **nodes**. Each node has an id, an operation,
and inputs. This program computes a constant and prints it:

```text
node 001
op const
type string
value "Hello, World!"

node 002
op emit
input 001
```

- `node 001` opens a block. Ids are digit strings, unique across the file.
- `op const` with `type`/`value` defines a literal.
- `op emit` is the batch output channel — it prints its input.

## 2. Arithmetic

Compute `10 × 5` (the language's "first proof of concept"):

```text
node 001
op const
type i64
value 10

node 002
op const
type i64
value 5

node 003
op multiply
input 001 002
output i64

node 004
op emit
input 003
```

→ `50`

Rules to internalize now:

- Operands must already share a type. `i64` + `f64` is a validation error
  with a suggested repair — **there is no implicit coercion**. Convert
  explicitly with `cast`.
- Data flows through `input`. The graph is a DAG: no cycles, so every
  program terminates.

Try breaking it on purpose: change node 002's type to `string` and run —
you get a structured, machine-usable error:

```text
ERROR E203
node: 003
operation: multiply
expected:
  input[1]: i64
received:
  input[1]: string
allowed_repairs:
  - cast node 002 -> i64
  - replace node 002
```

## 3. Decisions: `compare` + `branch`

There are no `if` statements. Comparison produces a `bool`; `branch` is a
pure value select — pick one of two values based on a condition:

```text
node 001
op const
type i64
value 100

node 002
op const
type i64
value 42

node 003
op compare
mode gt
input 001 002
output bool

node 004
op const
type string
value "greater"

node 005
op const
type string
value "not greater"

node 006
op branch
input 003 004 005
output string

node 007
op emit
input 006
```

→ `greater`

**Important:** *all* nodes evaluate — `branch` only selects. Write
programs whose unused paths are safe (see the calculator's
division-by-zero guard in `examples/calculator.ai`).

## 4. Functions

`func` declares a named subgraph with parameters and one `return`.
Calls bind arguments positionally. Recursion is rejected by design —
every program is guaranteed to terminate.

```text
func double
node 101
op param
index 0
type i64

node 102
op add
input 101 101
output i64

node 103
op return
input 102

main

node 001
op const
type i64
value 21

node 002
op call
callee double
input 001
output i64

node 003
op emit
input 002
```

→ `42`

## 5. Strings and crypto

`concat` builds strings (chains compose documents); `crypto.digest`
hashes deterministically:

```text
node 001
op const
type string
value "2066:"

node 002
op const
type string
value "demo"

node 003
op concat
input 001 002
output string

node 004
op crypto.digest
algorithm sha256
input 003
output string

node 005
op emit
input 004
```

## 6. Interactive I/O

`system.write` prints immediately (no newline); `system.read` reads one
stdin line. `examples/calculator.ai` builds a full interactive calculator
from these — with guarded division done via `compare`/`branch`.

```bash
printf "12\n+\n3.5\n" | python -m runtime run examples/calculator.ai
```

## 7. Effects: files, with capabilities

Effects require **capability grants** — runtime-held, never visible to the
program. Without `--caps`, every effect is denied (default deny):

```text
node 001
op const
type string
value "examples/incoming/note.txt"

node 002
op filesystem.read
input 001
output string

node 003
op emit
input 002
```

```bash
python -m runtime run program.ai --caps caps.json   # allowed if scoped
python -m runtime run program.ai                    # ERROR E401: denied
```

A grant on `examples/incoming` covers `examples/incoming/a.txt` but never
`examples/README.md`. See the [Capabilities guide](capabilities-guide.md).

## 8. The database

Declare entities; the runtime compiles them to SQLite and writes all SQL
itself — values are always bound parameters, so injection strings are
inert data:

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
value "groceries"

node 003
op const
type string
value "milk, eggs"

node 004
op data.insert
entity note
input 001 002 003
output i64

node 005
op emit
input 004
```

```bash
# caps.json — grants the write action on the note entity:
# {"subject":"t","grants":[{"action":"data.write","resource":"note"}]}
python -m runtime run program.ai --db notes.db --caps caps.json
# → 1   (the new row id)
```

Each data operation needs a separate capability action — `data.read`
cannot delete (`data.delete` is its own action; §24 of the master
roadmap).

## 9. Compile it to a conventional language

The graph is the asset; conventional code is a generated artifact:

```bash
python -m runtime export program.ai --target python --out program.py
python -m runtime export program.ai --target javascript --library --out engine.js
```

Exported code carries the program's canonical hash. Capability-gated
effects refuse to export — they must keep running inside the runtime's
authority plane.

## Where to go next

- [Operations reference](operations.md) — every built-in operation.
- [Capabilities guide](capabilities-guide.md) — grant files, signing, scoping.
- `examples/` — the calculator app and the full-stack notes app.
