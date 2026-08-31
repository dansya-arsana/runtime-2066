# Changelog

## [unreleased] — hardening cycle H0–H4 (plan §85–§89)

### Added
- **Semantic packages (H3)**: `package::module::unit` addressing,
  `package.ai` manifests, `runtime/packages.py`, `2066 list`,
  `2066 inspect` (full semantic context card: hash, nodes, inputs,
  outputs, effects, capabilities, dependencies) — agents no longer
  browse the filesystem to understand programs.
- **Production profile (H4)**: `--profile production` makes unsigned
  grants always rejected (fail closed); development stays the default.
- **Conformance corpus**: `protocol/conformance/corpus.json` freezes
  28 program hashes; suite fails on drift or unlisted programs.
- **Architecture boundaries**: layer map + import-analysis test
  (`tests/architecture/`); core proven free of storage/network/process
  imports; bundle-sync test for wheel-bundled programs.
- SECURITY.md, CHANGELOG.md, spec/packages.md,
  docs/architecture/BOUNDARIES.md.

### Changed
- Repository layout: sales application → `programs/sales/` (semantic
  package), grants → `policies/deployment/`, app shell → `apps/sales/`.
  **All 17 canonical hashes proven identical across the move** (H1).
- `examples/notes_app` remains a demo app (documented exception).

### Fixed
- (prior cycle) `when`-guarded effects, engine stdin race, MCP session
  layer, WAL/busy-timeout — see git log.

### Baseline
- Tag `prototype-v1.1-snapshot` = reference oracle for this cycle.
