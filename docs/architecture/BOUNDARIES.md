# Architecture Boundaries — 2066

> Normative for contributors and agents. Enforced by
> `tests/architecture/test_boundaries.py` (import analysis + layer
> classification + bundle-sync); violated tests fail the suite.
> Companion plan: `../2066_NEXT_DEVELOPMENT_HIGH_ASSURANCE_HARDENING_PLAN.md` (§5, §37, §87).

## The one rule

Dependencies point **inward only**:

```text
apps/  →  runtime/  →  core semantics
        (adapters)     (pure, effect-free)
```

Never the reverse. The semantic core decides; adapters perform what the
core authorized; apps are presentation and hosting. Nothing under
`runtime/` may import `apps`, `examples`, or `tests`.

## Layer map (current repository)

| Layer | Modules | May import | May never import |
|---|---|---|---|
| **Core (functional, pure)** | `errors`, `types`, `parser`, `serialize`, `hashing`, `validator`, `airef`, `packages` | stdlib pure parts, each other | `sqlite3`, `urllib`/`http`/`socket`, `subprocess`, any app code |
| **Execution** | `ops`, `interpreter`, `plan_vm`, `export`, `repair`, `capabilities` | core + adapter interfaces passed in explicitly (`DataPlane`, transports as callables) | app code; no hidden globals |
| **Adapters (imperative shell)** | `data` (SQLite), `fsops`, `identity`, `session`, `evidence`, `revocation`, `keydisk`, `multisig`, `delegation`, `pinning`, `reputation`, `proposals`, `redteam`, `fuzzer` | core, host stdlib (sqlite3, cryptography) | apps |
| **Apps (presentation/hosting)** | `apps/sales/*`, `examples/*`, `runtime/cli` | everything inward | — |

Key properties already true and now test-enforced:

- **The runtime owns no sockets** — `net.fetch` receives a host-supplied
  transport callable; the core never imports network machinery.
- **Time and randomness are injected** (`now=None` → default deny on
  expiring authority; the fuzzer seeds explicitly), never ambient.
- **No global mutable state** in execution: `execute()` takes an
  explicit context (grants, db, sessions, net); nothing is read from
  module globals.

## Top-level layout (hardening plan §7, applied to this repo)

```text
programs/     semantic packages (package::module::unit) — IDENTITY
apps/         application shells (HTTP servers, cron, UI) — hosting
policies/     capability grants by deployment stage — human policy
protocol/     conformance corpus + frozen canonical hashes
runtime/      the Python implementation (core + execution + adapters)
examples/     language examples and demos (not applications of record)
spec/         normative language specification
tests/        unit / conformance / architecture / determinism / ...
docs/         architecture, AI manual, operations
benchmarks/   measurement
```

The root stays boring: subsystems, normative documents, build metadata.
No production `.ai` programs, keys, databases, or scratch scripts at the
root — enforced by `.gitignore` (secrets) and the corpus coverage test
(every shipped program must be frozen in `protocol/conformance/corpus.json`).

## Known, documented exceptions

1. **`runtime/mcp_server.py`** — an app shell living inside the package
   so `pip install runtime-2066` provides the `2066-mcp` console script
   with bundled tool programs (`runtime/programs/`). Imports inward
   only; the bundled programs are test-enforced byte-identical to their
   canonical sources. To be moved to `apps/mcp` when the wheel grows a
   data-files layout.
2. **`examples/notes_app`** — second demo app still file-addressed;
   migration to a semantic package follows sales (next hardening cycle).

## Adapter independence question (§14)

Every adapter must answer: *can we delete and replace it without
changing canonical `.ai` semantics?*

- SQLite → PostgreSQL: replace `runtime/data.py`; programs unchanged.
- HTTP/HTTPS transport: swap the injected `net` callable; program hash
  unchanged.
- Python/JS exports: disposable artifacts, never the source of truth.
- The two in-runtime adapters (tree, plan) already prove the property
  pairwise on every corpus program (determinism suite).

## Change classification (§83)

Editing `programs/**` is an APPLICATION change (normal proposals).
Editing adapters: ADAPTER change (review). Editing `runtime/{core,
execution}`: RUNTIME change (security + compatibility review + corpus
green). Anything touching canonical hashes: PROTOCOL event — re-freeze
the corpus deliberately, never silently.
