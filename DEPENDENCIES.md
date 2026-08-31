# DEPENDENCIES.md

Per master roadmap Appendix A.3: every dependency is recorded with its
license, purpose, security boundary, replacement plan, and offline viability.
No dependency may become a hidden constitutional authority.

## Runtime dependencies

| Field | Value |
|---|---|
| project | Python (CPython) standard library only |
| version | Python 3.14.4 (any ≥3.12 works; no version-specific features used) |
| license | PSF License (permissive) |
| purpose | host runtime for the reference interpreter (parser, validator, adapters, CLI, tests) |
| security boundary | pure computation on untrusted `.ai` files; effects only behind capability grants |
| replacement plan | port the `runtime/` package to Rust (roadmap §79 candidate) behind the existing module boundaries |
| offline viability | fully offline; stdlib only |

Third-party Python packages:

| Field | Value |
|---|---|
| project | [PyInstaller](https://pyinstaller.org) (build tool only) |
| version | 6.22.2 |
| license | PyInstaller is GPL-2.0 with a bootloader exception — **output binaries are unencumbered** (the exception explicitly permits proprietary/free use of frozen apps; we ship MIT-licensed code anyway) |
| purpose | freeze the runtime into `bin/2066.exe` — a standalone binary needing no Python on the target machine (`build/entry.py`, UTF-8 streams pinned) |
| security boundary | build-time packaging only; never imported by the runtime at execution time |
| replacement plan | the real long-term answer is the Rust port (§79) with a static binary; PyInstaller is the bridge |
| offline viability | local build; no runtime network use |

| Field | Value |
|---|---|
| project | [cryptography](https://github.com/pyca/cryptography) |
| version | 50.0.1 (already present in environment; no install performed) |
| license | Apache-2.0 OR BSD-3-Clause (both on roadmap Appendix A.3 approved list) |
| purpose | ed25519 keygen/sign/verify for agent identity and signed capability grants (spec/identity.md) — adopted 2026-08-30 |
| security boundary | signing only; it never executes programs and never holds authority — the runtime verifies, policy decides |
| replacement plan | isolated behind `runtime/identity.py` (the Identity ABI, roadmap §64): algorithm-tagged, so libsodium/PyNaCl (also present) or a Rust port can replace it without touching callers |
| offline viability | installed locally; no network use at runtime |

Research decision (Appendix G spike, 2026-08-30): `cryptography` and
`pynacl` were both already installed; hand-rolling ed25519 was rejected —
a pure-Python crypto implementation is the one dependency worse than a
real one. Everything else remains stdlib-only (tests use `unittest`).

## Bootstrap decision record

Master roadmap §79: *"Architecture first. Implementation language second."*
and §14: *"The first prototype may use an existing runtime underneath."*

Decision (2026-08-30): bootstrap the V0 semantics as a dependency-free
Python package to validate the canonical representation, deterministic
validation, structured errors, and direct execution with zero build
friction. Rust remains the candidate for components 2066 genuinely owns
(verifier, capability runtime, WASI boundary), to be introduced when the
§102 bootstrap comparison (custom interpreter vs WASI-backed vs existing
semantic-runtime adapter) is performed.

## Open primitives under evaluation (not yet dependencies)

Tracked from master roadmap Appendix A/B — study before build (Appendix G):

- WebAssembly + WASI — sandbox/host boundary (no ambient authority)
- AIKernel — deterministic semantic runtime reference
- Foundgine — semantic data planning / provider model
- AGF standards — governance vocabulary
- FIDO2 security keys — human hardware approval
