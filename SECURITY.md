# Security Policy

2066 is a security-focused runtime: capability-gated authority, signed
identities, deterministic verification. Reports about the layers below
are genuinely valuable and will be taken seriously.

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.4.x   | yes       |
| < 1.4   | no        |

## Reporting a vulnerability

**Use GitHub's private vulnerability reporting** (Security tab → Report a
vulnerability) on `dansya-arsana/runtime-2066`, so details stay out of
public issues until a fix ships.

Please include: the affected component (parser / validator / interpreter /
plan VM / capabilities / sessions / MCP server / example apps), a minimal
reproducing `.ai` program or request, and the observed vs expected
behavior. Structured denials (E4xx authority errors) are intended
behavior — report them only if a denial is *bypassable*.

You will get an acknowledgement within 7 days and a fix or mitigation
timeline within 30. Coordinated disclosure: we ask for up to 90 days
before public detail; credit is yours unless you prefer otherwise.

## Scope

In scope: this repository (runtime, CLI, MCP server, example apps) and
the live demo at `https://dev-2066.arsana.cloud`. Out of scope: the
underlying hosting provider, social engineering, and denial of service
by volume.

## Design invariants worth attacking

If you can break any of these with a valid `.ai` program or a protocol
message, that is a critical report:

1. **Default deny** — no effect (filesystem, data, session) executes
   without a signed grant, ever.
2. **Determinism** — two conforming runs (either adapter) of one program
   hash and behave identically.
3. **Session integrity** — session tokens are unforgeable and fail
   closed; programs can verify but never mint them.
4. **Proposal integrity** — signed proposals merge deterministically or
   are rejected; no partial application.
