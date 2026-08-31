# spec/effects.md — Effect classes (normative)

Static per-op classification (source of truth: validator.EFFECT_OF;
rendered by `2066 inspect` / `2066 effects`):

| Class | Meaning | Authority required |
|---|---|---|
| PURE | arithmetic/logic/casts/lists | none |
| SYSTEM | stdin/stdout channel | none (host channel) |
| IDENTITY | session.verify | host-attached verifier |
| FILESYSTEM_READ / _WRITE | file effects | filesystem.* grant, path-scoped |
| DATA_READ / _WRITE | semantic data ops | data.read/write/delete per entity |
| NETWORK | net.fetch | net.request grant, hostname-scoped |

Rules: `call` inherits callee effects transitively; effects are a
super-set bound (a program that CAN effect X declares X); guards
(`when`) gate WRITE execution but do not remove the effect from the
manifest — authority is still required to attempt.
