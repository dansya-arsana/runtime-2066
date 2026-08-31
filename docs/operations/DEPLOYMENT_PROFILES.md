# Deployment Profiles (plan SS21, SS43)

| | A — development | B — production | C — sovereign |
|---|---|---|---|
| unsigned grants | allowed (explicit default) | **rejected** | **rejected** |
| flag | `--profile development` (default) | `--profile production` | `--profile sovereign` |
| debug surfaces | verbose errors | verbose errors (audit on) | restricted logs |
| network egress | per-grant hosts | per-grant hosts | offline by design; bundles only |
| updates | git / pip | signed release + SBOM | **signed offline bundle** (`2066 bundle`) |
| telemetry | none | none | none |
| keys | throwaway dev keys | RELEASE-keyed grants | HUMAN_AUTHORITY key, multisig for critical acts |

Rules (SS21): security never depends on an environment variable; the
profile is an explicit flag; production and sovereign fail closed on
unsigned authority (tested in tests/runtime/test_packages.py).

Key separation (SS43): never reuse one human key across
development/test/production/sovereign. Profiles imply distinct key
purposes: DEV_KEY, TEST_KEY, RELEASE_KEY, ORG_ROOT_KEY,
HUMAN_AUTHORITY_KEY.

Sovereign operation (SS23-24): `2066 bundle` + `2066 verify-bundle` +
`2066 install-bundle --agent <release identity>` — verify signature,
verify every hash, install, evidence record. No maintainer, cloud,
DNS, or vendor needs to be reachable.
