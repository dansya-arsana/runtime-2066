# 2066 Constitution

Derived from master roadmap §4 and Appendix C.6. These are non-negotiable
principles; every phase must preserve them. Version: 0.1 (Milestone 1).

## Laws

1. **No AI is trusted.** An AI agent is an untrusted proposer. It may request
   actions; it may never become the final authority for privileged execution.
2. **No implicit human global authority.** Human identities are scoped too;
   a login never implies root across every resource.
3. **Every side effect is explicit.** Pure computation and external effects
   are distinguishable at the representation level.
4. **Privileges are capabilities.** Authority is expressed as scoped
   capability objects (`action:resource`), never as ambient power.
5. **Capabilities are scoped.** Who, what action, which resource, how much,
   how long, under what conditions.
6. **No permanent agent authority by default.** Grants are short-lived.
7. **Every privileged action is attributable.** Identity, capability,
   resource, policy result, time, result, signature, provenance.
8. **Verification is cheaper than trust.** Proposals pass verification, not
   reputation gates.
9. **No undefined behavior.** Operations have documented, deterministic
   semantics (see SPEC.md).
10. **Conventional source code is not the source of truth.** The semantic
    graph is. Generated languages are artifacts.

## Invariants (absolute)

```text
agents cannot mint their own authority
privileged effects require capabilities
capability widening requires external authority
unsigned privileged mutation cannot execute
critical evidence cannot silently disappear
```

## Reuse-first principle (roadmap §1, §6, Appendix A)

ADOPT OR ADAPT before REIMPLEMENT. A primitive is replaced only when it
demonstrably violates the trust model, licensing, offline viability, or
cannot express 2066 capabilities. Every dependency is recorded in
DEPENDENCIES.md and must remain replaceable behind stable interfaces.

## Current status against the laws

Milestone 4a enforces laws 3–6 and 9–10 as before (deterministic semantics,
explicit capability-gated effects, scoped expiring grants), and strengthens
laws 1 and 7: grants can now carry ed25519 issuer signatures verified
fail-closed at load, so authority is attributable and tamper-evident.
Unsigned grant acceptance remains a transition default (`--require-signed`
refuses it). Law 2 (scoped human authority) and hardware-backed issuance
arrive with Phase 10; law 8's full verify-over-trust pipeline is the repair
loop plus validator plus signature verification today.

## Protocol versioning

The protocol (semantics, canonical identity, error namespace,
capability model) versions independently of any runtime. Programs may
declare `protocol <x.y>`; incompatible runtimes must refuse them, never
guess. Changing a canonical hash or an error code is a protocol event —
deliberate, reviewed, migrated — never a refactor side effect.

