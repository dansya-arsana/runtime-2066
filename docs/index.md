# 2066 Documentation

Welcome to the official documentation for **2066**, an AI-native semantic
execution language. 2066 programs are graphs — authored by humans or AI
agents — that a deterministic runtime validates, executes, and compiles to
conventional languages. Authority lives in capabilities, never in the
model that proposed the program.

**Version:** 0.8.0 · **Status:** Milestone 5 (full-stack: data + auth)

## Where to start

| Document | What it covers |
|---|---|
| [Tutorial](tutorial.md) | Learn 2066 by building: hello world → arithmetic → functions → branches → effects → a database-backed app. Start here. |
| [Language reference](language-reference.md) | The complete language: programs, entities, functions, types, statements, semantics, error model. |
| [Operations reference](operations.md) | Every built-in operation — like a standard-library reference: inputs, outputs, capability requirements, examples. |
| [CLI reference](cli-reference.md) | Every `python -m runtime` command and flag. |
| [Capabilities guide](capabilities-guide.md) | How-to: grant authority, sign grant files, scope effects, run apps safely. |
| [Capability matrix](capability-matrix.md) | Honest table: what 2066 can and cannot do vs conventional languages, measured. |
| [Philosophy](philosophy.md) | Why the language exists: trust over tokens, breaking the revise–pentest–burn loop. |

## For AI agents

| Document | What it covers |
|---|---|
| [Agent authoring manual](ai/AGENT_MANUAL.md) | **Start here.** One complete, token-efficient file: grammar, all 24 operations, all error codes, the validate→repair→run workflow, and authority rules. |
| [Machine reference](ai/reference.json) | The full language reference as JSON, generated from the live runtime (`python -m runtime reference`). Never stale — a test regenerates and compares on every run. |

## Normative specifications

The documentation above is the user-facing view. The normative contracts
live in [../spec/](../spec/): [graph](../spec/graph.md) (file grammar),
[instructions](../spec/instructions.md) (operation semantics),
[types](../spec/types.md), [errors](../spec/errors.md), and
[identity](../spec/identity.md). When documentation and specification
disagree, the specification wins — and please open an issue.

## The 60-second version

```bash
cd 2066
python -m runtime run examples/hello.ai          # → Hello, World!
printf "12\n+\n3.5\n" | python -m runtime run examples/calculator.ai
python -m runtime hash examples/hello.ai         # canonical identity
python -m unittest discover                      # 210 deterministic tests
```

A 2066 program is a semantic graph in canonical text form:

```text
node 001
op const
type string
value "Hello, World!"

node 002
op emit
input 001
```

No variables, no syntax sugar, no ambiguity — one canonical way to write
each construct, validated before execution, compiled to Python or
JavaScript when you want a conventional artifact.
