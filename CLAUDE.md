# CLAUDE.md — 2066 Project Guide

> **Last updated: 2026-08-31 (night) — hardening cycle H0–H4 done:
> semantic packages (`2066 list`/`inspect`), repo boundaries
> (programs/apps/policies/protocol), production profile, frozen
> conformance corpus. 353 tests green. Baseline tag:
> prototype-v1.1-snapshot.**
>
> **Stages A-D COMPLETE + VPS battle-test pass done.** Found and fixed
> live: MCP session tools were structurally dead (no verifier/mint
> attached); engine stdin race under parallel load (5/12 failures ->
> 12/12); SessionRegistry RMW race; missing WAL/busy-timeout; restart
> wiped db+keys (now volumes). Standalone battery:
> benchmarks/standalone.py (determinism replay, check speed ~0.2-0.5ms,
> fuzzer 300 mutants 0 crashes). Remote MCP demo:
> examples/mcp/remote_session.py (PC agent -> ssh -> VPS stdio MCP).
> Remaining: Stage E (economy), transport (App. E), public hardening.

## What this is

2066 is an AI-native semantic execution runtime at `E:\Genesis\2066`.
AI agents author `.ai` semantic programs; a deterministic runtime
validates, executes, and enforces capability-based authority. The thesis:
**AI intelligence ≠ AI authority** — models propose, verification decides.

## Quick orientation

```bash
cd E:\Genesis\2066

# run a program
python -m runtime run examples/hello.ai

# agent fast-path: validate + effects + hash in one call
python -m runtime check examples/calculator.ai --json

# full test suite (335 tests, ~25s)
python -m unittest discover

# machine-readable language reference for AI agents
python -m runtime reference > docs/ai/reference.json
```

## Working rules (AGENTS.md summary)

1. Use the **job-done skill** (`~/.agents/skills/job-done/`) — goal in,
   evidence block out, no process narration.
2. **Never claim done without evidence**: canonical hash, green suite,
   byte-identical diff, or verified artifact.
3. **Never fabricate grant files**; denials (exit 4) are correct — report
   the manifest, don't retry.
4. Conventional languages are **generated artifacts**; the semantic
   program is the source of truth.
5. Docs for AI agents: `docs/ai/AGENT_MANUAL.md` (one-file manual) +
   `docs/ai/reference.json` (machine-readable, drift-tested).

## Repository layout

```
E:\Genesis\2066\
├── runtime/                    # the semantic core (29 modules, ~7.3k lines)
│   ├── parser.py               # .ai grammar → Program
│   ├── validator.py            # deterministic type/structure checking
│   ├── interpreter.py          # tree-walking adapter
│   ├── plan_vm.py              # compiled-plan stack VM adapter
│   ├── ops.py                  # shared operation semantics (both adapters)
│   ├── types.py                # 6 primitive types, canonical rendering
│   ├── errors.py               # structured error protocol (43+ codes)
│   ├── serialize.py            # canonical form + format-version header
│   ├── hashing.py              # SHA-256 program identity
│   ├── repair.py               # mechanical cast-repair loop
│   ├── export.py               # Python + JavaScript export backends
│   ├── capabilities.py         # grant sets, scope matching, signed/multisig envelopes
│   ├── identity.py             # ed25519 agent identity + signing
│   ├── keydisk.py              # KEY v1: any flashdisk as human authority (+ rotation)
│   ├── pinning.py              # trust-store issuer pinning
│   ├── session.py              # signed session tokens + registry
│   ├── revocation.py           # hash-bound delegations + revocation chain
│   ├── multisig.py             # m-of-n signed envelopes
│   ├── delegation.py           # chained delegations (human → agent → sub-agent)
│   ├── data.py                 # SQLite data plane (runtime-written SQL)
│   ├── fsops.py                # capability-gated filesystem effects
│   ├── evidence.py             # hash-chained tamper-evident audit
│   ├── proposals.py            # signed graph diffs + deterministic merge
│   ├── reputation.py           # Phase 14: evidence-based reputation ledger
│   ├── redteam.py              # Phase 15: 5-gate proposal verification
│   ├── fuzzer.py               # Phase 15: program mutation fuzzer
│   ├── airef.py                # machine-readable reference generator
│   └── cli/                    # CLI package (main.py, commands.py, args.py)
├── spec/                       # normative specs (graph, instructions, types, errors, identity, hardware-key, key-copying)
├── docs/                       # human docs (tutorial, language-ref, operations, CLI, capabilities, capability-matrix, philosophy, job-done, index)
│   └── ai/                     # agent docs (AGENT_MANUAL.md + reference.json)
├── tests/runtime/              # 28 test files, 335 tests
├── examples/
│   ├── hello.ai                # canonical hello world
│   ├── calculator.ai           # interactive 4-op calculator (stdin/stdout)
│   ├── calculator_app/         # browser app: 2066 engine compiled to JS
│   ├── calculator_page.ai      # generates styled HTML via capability-gated write
│   ├── compound_interest*.ai   # §81 demo with error injection + repair
│   ├── file_read.ai            # §82 capability demo
│   ├── notes_app/              # full-stack app: auth + SQLite + sessions
│   ├── proposals/              # §83 multi-agent merge demo
│   └── mcp/                    # MCP server (6 tools from .ai programs)
├── benchmarks/                 # runtime/authoring/verification benchmarks
├── bin/2066.exe                # standalone frozen binary (no host toolchain)
├── WHITEPAPER.md               # project white paper (11 sections)
├── AUDIT.md                    # security audit findings + fixes
├── CONSTITUTION.md             # the 10 laws
├── THREAT_MODEL.md             # per-milestone threat posture
├── ROADMAP.md                  # milestone progress tracker
├── README.md                   # entry point with quickstart
└── CLAUDE.md                   # this file
```

## Milestone status — ALL STAGES A–D COMPLETE

| Stage | Milestones | Status |
|---|---|---|
| **A Foundation** | M0 hello world, M1 V0+repair, M2 canonical IR+dual adapters, M3 capabilities | ✅ |
| **B Useful Runtime** | M4a identity, M4cd calculator app, M5 full-stack notes, M6 sessions+evidence | ✅ |
| **C Human Trust** | M9 any-disk keys, M10 hardening (pinning/revocation/versioning), M12 multisig+delegation+rotation | ✅ |
| **D Open Network** | M7 proposals+merge, M11 MCP server, M12 reputation+redteam+fuzzer | ✅ |
| Audit | Adversarial pass: 3 loopholes fixed, agent loop 3.1× faster | ✅ |
| **E Machine Economy** | Compute credits, treasury, payment adapters | ⬜ not started |
| **F Genesis** | Hash constitution+spec+runtime → root manifest, governance | ⬜ not started |
| **G Physical** | IoT, robotics, machine economy | ⬜ not started |

### Detailed milestone list

| # | What it delivered | Tests added |
|---|---|---|
| M0 | Hello world, interpreter, parser, validator, structured errors | 43 |
| M1 | V0 complete: call/return, cast, repair loop, §81 demo | 38 |
| M2 | Canonical IR + hashing, dual adapters (tree + plan VM), §102 comparison | 17 |
| M3 | Effects + capabilities (§82 demo beats), default deny | 36 |
| M4a | Agent identity (ed25519), signed grants, tamper-evident | 21 |
| M4c-d | Calculator app (JS export), styled HTML, stress test | 25 |
| M5 | Full-stack notes app: SQLite, auth, ownership, browser-verified | 18 |
| M6 | Session tokens, persistent runtime (21× faster), migrations, evidence chain | 35 |
| M7 | Multi-agent proposals + deterministic merge (§83 demo) | 14 |
| M8 | List values (`data.list`, `list.length/get/join`) | 11 |
| M9 | Any-disk human keys (§84 software beats) | 14 |
| M10 | Trust-store pinning, session revocation, runtime self-hash, format versioning | 15 |
| M11 | MCP server (6 tools, 13 protocol checks) | 13 |
| M12/D | Reputation ledger, red-team pipeline, fuzzer | 26 |
| M12/C | Multisig CLI, delegation chain, key rotation | 29 |
| Audit | 3 security loopholes found + fixed, `check` fast-path | 3 |

## Key files to read for context

| Need | Read |
|---|---|
| The language grammar | `spec/graph.md` |
| Every operation (29 ops) | `spec/instructions.md` or `docs/operations.md` |
| Error codes (43+) | `spec/errors.md` |
| How authority works | `spec/identity.md` + `spec/hardware-key.md` + `spec/key-copying.md` |
| The philosophy | `docs/philosophy.md` + `WHITEPAPER.md` |
| What we can/can't do | `docs/capability-matrix.md` |
| How to author .ai programs | `docs/ai/AGENT_MANUAL.md` |
| Security posture | `THREAT_MODEL.md` + `AUDIT.md` |

## CLI command reference

```bash
# core
python -m runtime run <p.ai> [--adapter tree|plan] [--caps caps.json]
                           [--db file.db] [--session-key id.json] [--json]
python -m runtime validate <p.ai>
python -m runtime repair <p.ai>                    # mechanical cast-repair loop
python -m runtime check <p.ai> [--json]           # validate+effects+hash, one call
python -m runtime hash <p.ai>                     # canonical SHA-256 identity
python -m runtime effects <p.ai>                  # what authority does it need?
python -m runtime export <p.ai> --target python|javascript [--library] [--out f]

# authority
python -m runtime keygen <id.json> [--id name] [--trust-store issuers.json]
python -m runtime sign-caps <caps.json> --agent <id.json> --key <id.key>
python -m runtime verify-caps <signed.json>
python -m runtime key-format <disk> [--id human-1] [--pin 1234]
python -m runtime key-inspect <disk>
python -m runtime key-rotate <disk> --pin <old> --new-pin <new>
python -m runtime approve <caps.json> --key <disk> [--ttl-minutes 5] [--for-hash H]
python -m runtime approve <caps.json> --multisig 2-of-3 --key d1 --key d2 --key d3 --pin 1234
python -m runtime delegate <parent.json> --agent <id.json> --key <id.key> --subject <sub> [--ttl-minutes 30]
python -m runtime chain <delegated.json> [--revocations rev.jsonl]

# data + audit
python -m runtime migrate <p.ai> --db <file.db>
python -m runtime evidence <log.jsonl>            # verify hash chain
python -m runtime revoke <signed.json> --revocations <rev.jsonl>

# multi-agent
python -m runtime propose <new.ai> --base <base.ai> --agent <id.json> --key <id.key>
python -m runtime merge <base.ai> --proposals a.json,b.json [--out merged.ai]
python -m runtime verify-proposal <p.json> --base <base.ai>

# Stage D: reputation + red team
python -m runtime redteam <p.json> --base <base.ai> [--reputation rep.jsonl]
python -m runtime reputation <rep.jsonl> [--agent agent-A]

# maintenance
python -m runtime reference                        # machine-readable docs for AI
python -m runtime digest                           # runtime self-hash (S9)
python -m runtime selftest                         # quick health check
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | parse/validation (E1xx, E2xx) or proposal trust (E6xx) |
| 2 | runtime error (E3xx, E5xx data) |
| 3 | usage, IO, or trust failure |
| 4 | authority denial (E4xx) — the program ran, the policy said no |

## What's NOT done yet

- **Stage E (machine economy)**: compute credits, treasury, payment
  adapters — the economic layer for self-sustaining agents
- **Stage F (Genesis)**: hash constitution+spec+runtime into root
  manifest, distributed governance, root key ceremony
- **Stage G (physical world)**: IoT adapters, robot controllers, machine
  economy
- **Transport layer** (Appendix E): signed semantic messages over LAN /
  offline bundles — no networking yet
- **Iteration/loops**: termination-preserving bounded constructs
- **WASI adapter**: deferred with trigger (Phase 4–5 capability boundary)
- **FIDO2 hardware**: needs a physical security key plugged in

## Key benchmarks (benchmarks/RESULTS.md)

| Metric | Value |
|---|---|
| Exported JavaScript execution | 0.09 ms (10k ops) |
| Exported Python execution | 1.08 ms |
| Native JS (V8) | 0.01 ms |
| 2066 interpreter (tree) | 4.7 ms |
| Agent revision cycle (check) | 81 ms (3.1× faster than 3 spawns) |
| Full verification suite | 335 tests in ~25s |
| Authoring token cost | ~9× hand-written Python (579 vs 65 tokens) |
| Notes app request latency | 0.9 ms (persistent runtime) |

## Skills installed

- `~/.agents/skills/job-done/` — goal-in, evidence-block-out working mode
  (persisted across sessions; also see `AGENTS.md` at workspace root)
