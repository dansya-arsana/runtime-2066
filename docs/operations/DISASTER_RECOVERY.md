# Disaster Recovery (plan SS61-63)

| Event | Recovery |
|---|---|
| lost machine | reinstall from signed release; `2066 restore` the backup bundle; verify release + corpus |
| lost database | restore latest `2066 backup` bundle (hash-verified); re-run `2066 evidence` on restored chain |
| lost human key | sovereign: multisig threshold (m-of-n) re-issues authority; single-key deployments: revoke the lost key's delegations, issue from a surviving ORG_ROOT key |
| corrupted evidence | `2066 evidence <log>` pinpoints the broken event; last checkpoint before it remains provable; full-log deletion is the known single-machine limit (SS52: replicate checkpoints before open networks) |
| failed migration | migrations are additive-only by policy; restore pre-migration backup; destructive steps require human approval |
| runtime rollback | reinstall prior signed release; conformance corpus proves program compatibility (`protocol 0.2` header refuses mismatches) |
| protocol downgrade attempt | programs declaring `protocol 0.2` refuse to run on older runtimes (E109) |

Backup discipline: `2066 backup` excludes secrets by default; keys are
re-issued, never restored from casual backups.
