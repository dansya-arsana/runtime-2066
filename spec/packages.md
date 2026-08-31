# spec/packages.md — Semantic Packages (normative)

> Status: normative for the `2066` prototype, hardening cycle H3.
> Machine surface: `2066 list`, `2066 inspect <address>`,
> `runtime.packages.PackageStore`.

## 1. Identity

A program's identity is its **canonical hash** — never its filename.
Packaging layers a hierarchical semantic address on top:

```text
PACKAGE :: MODULE :: UNIT        e.g.  sales::business::add
```

All three parts MUST be identifiers (`isidentifier()`). Addresses
containing path characters (`..`, `/`, `\`, `:` beyond the separators)
are invalid and MUST be rejected before any filesystem use — resolution
is by lookup in a declared manifest, not by path joining of untrusted
input.

The filesystem path of a unit is **storage detail**. Moving or renaming
storage MUST NOT change any hash (verified live during the H1 move:
17/17 hashes identical).

## 2. Package manifest — `package.ai`

One manifest per package, at the package root:

```text
package <identifier>          # required, exactly once
version <version>             # optional, default 0.0.0
module <identifier>           # repeatable; declaration order preserved
```

`#` starts a comment; blank lines ignored; one field per line.

Rules (fail closed):

1. Unknown fields are errors.
2. Every declared module MUST exist as a directory containing at least
   one `.ai` unit.
3. Every directory under the package root containing `.ai` files MUST be
   declared (no undeclared modules — the manifest is authoritative).
4. A unit is `<package-root>/<module>/<unit>.ai`; the unit's semantic
   name is the file stem.
5. The manifest file itself is NOT a program and is not hashed as one.

## 3. Unit loading

`store.unit(address)`:

1. Parse the address (3 identifier parts) — else structured refusal.
2. Resolve the package by manifest; unknown package/module/unit errors
   MUST name what exists ("declared: core", "have: hello, note_add").
3. Read, parse, and validate the program; a unit that does not validate
   is not loadable (its error surfaces with the semantic address).
4. Cache by address; the unit's `hash` equals `program_hash` of its
   content.

## 4. Derived unit metadata (`2066 inspect`)

| Field | Derivation |
|---|---|
| `hash` | canonical program hash |
| `node_count` | nodes in main + all functions |
| `inputs` | count of `system.read` nodes in main topological order |
| `outputs` | `system.write` presence + emit count |
| `effects` | `program_effects` (static effect manifest) |
| `capabilities` | per effectful op: `action[:scope]`; data scopes are entity names; net scopes are hostnames when the URL is a const, else `<runtime url>`; `session.verify` → host-attached verifier |
| `dependencies` | entities used, session-verifier use, const egress hosts |
| `callers` | none — units are self-contained graphs in protocol 0.2 |

## 5. Conformance

`protocol/conformance/corpus.json` freezes the canonical hash of every
shipped program, packaged or example. The suite fails on any drift and
on any unlisted program. Re-freezing is a deliberate, reviewed act —
never a side effect of refactoring.

## 6. Resource identity (plan SS47)

Semantic identity is location-free: a resource is
`<package>::<entity>::<row>` (e.g. `sales::business::12`), never a URL
or path. Transports (LAN/Tor/offline, M10+) resolve WHERE a resource is
reachable; they can never change WHAT it is (ADR-006).
