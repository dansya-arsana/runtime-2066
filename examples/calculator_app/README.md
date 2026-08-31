# 2066 Calculator App

A real calculator with a polished dark-theme UI — and **zero calculator
logic written by hand**. The math engine is the 2066 semantic program
[engine.ai](engine.ai), compiled to JavaScript by the 2066 runtime and
loaded by the page. The HTML/CSS/JS around it is a presentation shell only.

```
engine.ai   (semantic program — the source of truth)
    │  python -m runtime export --target javascript --library
    ▼
engine.js   (generated, hash-stamped artifact)
    │  <script src="engine.js">
    ▼
index.html + app.js   (UI shell: display, keys, keyboard, error states)
```

## Run

Open `index.html` in any browser — no build step, no server needed.
Or serve it:

```bash
cd examples/calculator_app
python -m http.server 8617
# → http://localhost:8617
```

Features: chained operations, keyboard input (digits, `+ - * /`, Enter,
Esc, Backspace, %), sign toggle, percent, pending-operator highlight,
error states (division by zero, unknown operator — messages come from the
2066 engine), `aria-live` display and focus-visible keys.

## Rebuild the engine

`engine.js` is a generated artifact. After changing `engine.ai`,
recompile and commit:

```bash
python -m runtime export examples/calculator_app/engine.ai \
    --target javascript --library \
    --out examples/calculator_app/engine.js
```

The header of `engine.js` contains the canonical hash of `engine.ai`, so a
stale artifact is detectable (tested: `test_committed_engine_js_matches_engine_ai`).

## Same program, other backends

```bash
python -m runtime run examples/calculator_app/engine.ai              # self-test: 42.0
python -m runtime export examples/calculator_app/engine.ai --target python
```

One semantic program; Python and JavaScript are just backends.
