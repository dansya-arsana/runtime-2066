# The Job Done Protocol

The 2066 human↔agent interaction contract (roadmap §94–§96, realized).

## Principle

The human states **intent** and receives **outcomes**. The agent works in
2066 (semantic programs, verified artifacts); the human reads neither the
prompting nor the programs unless they ask. Understanding is available on
demand — never required in advance.

Trust does not come from the human following the work. It comes from what
the runtime already proves: deterministic validation, canonical hashes,
capability walls, tamper-evident evidence. A job is not "probably fine" —
it verified, or it failed with a structured error.

## The report format

Every completed task ends with exactly this block — nothing more:

```text
JOB DONE
goal:     <one line, the human's own words>
status:   done | failed (<error code>)
evidence: <hash | test count green | artifact path>
cost:     <time / tokens if notable>
```

Optional lines when they change decisions: `grants:` (authority used),
`effects:` (manifest), `notes:` (one line, only if the human must decide
something).

## Rules for the agent

1. No narration of process. No "let me...", no status updates, no
   explanations of approach. Work, verify, report the block.
2. Never claim done without evidence: a green suite, a canonical hash, a
   verified artifact, or a browser-verified result.
3. If the task needs authority the agent lacks, the block becomes
   `status: blocked` + the `effects:` manifest and the exact grant
   requested. Stop there.
4. If verification fails and cannot be repaired, report `failed` with the
   error code. Never ship around a red test.
5. Explain only on request ("why?" gets a full answer — on demand).

## Rules for the human

- State the goal in one line. Read one block back.
- Audit whenever you want: `python -m runtime hash`, `evidence verify`,
  the test suite — the receipts are always there, but *you* choose when.
- Change your mind by stating a new goal; agents re-propose against the
  graph (M7), nothing is silently overwritten.

## Why this is safe here (and not elsewhere)

Anywhere else, "just give me the final output" means trusting the agent's
self-report. Here the self-report is checkable by machine: same program →
same hash → same behavior, and privileged actions leave hash-chained
evidence. "Job done" is a claim anyone can verify in milliseconds
(§4.8 — verification is cheaper than trust).
