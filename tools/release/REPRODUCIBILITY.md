# Reproducible build record (hardening plan SS27)

**Result (2026-08-31): REPRODUCIBLE.** Same source tree + pinned
`SOURCE_DATE_EPOCH` ⇒ byte-identical wheel.

## Procedure

```bash
SOURCE_DATE_EPOCH=1789920000 pip wheel . --no-deps --no-build-isolation -w out1
SOURCE_DATE_EPOCH=1789920000 pip wheel . --no-deps --no-build-isolation -w out2
sha256sum out1/*.whl out2/*.whl   # identical
```

## Measured

```
runtime_2066-1.4.1-py3-none-any.whl
sha256 51e4adc10b7d6a6ccb0affbc6ef598b3a7e60768f2d17b595f17b17df48025b5
```

(setuptools honors SOURCE_DATE_EPOCH for the archive timestamps; the
sdist was not re-tested this cycle — wheel only, flag `--no-build-
isolation` keeps the local pinned toolchain.)

## Release procedure (SS27 + SS28, tied together)

1. `python -m unittest discover` — suite green.
2. Build wheel with pinned `SOURCE_DATE_EPOCH`; record hash (above).
3. `python -m runtime sbom --out sbom.json` — SPDX 2.3.
4. `python -m runtime release --out release.json --agent id --key key`
   — hashes runtime tree + spec + conformance corpus, signs it.
5. Publish wheel + `release.json` + `sbom.json`; users run
   `python -m runtime verify-release release.json --agent id` and the
   tree they run is proven file-by-file against the signature.
