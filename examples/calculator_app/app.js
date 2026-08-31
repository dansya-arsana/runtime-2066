/* 2066 Calculator — UI shell.
 *
 * Every button and key press funnels into Calc2066.calculate(a, b, op),
 * which was compiled from engine.ai by the 2066 runtime. This shell owns
 * only presentation state: what is on screen, never what the math means.
 */
(function () {
  "use strict";

  var expression = document.getElementById("expression");
  var reading = document.getElementById("reading");
  var display = document.querySelector(".display");

  var state = {
    lhs: null,        // stored operand (number)
    op: null,         // pending operator: + - * /
    entry: "0",       // what the user is typing
    justEvaluated: false,
    error: false,
  };

  function render() {
    var pendingExpr = state.lhs !== null && state.op
      ? formatNumber(state.lhs) + " " + prettyOp(state.op)
      : "\u00a0";
    expression.textContent = state.error ? "\u00a0" : pendingExpr;
    reading.textContent = state.error ? state.entry : formatNumber(Number(state.entry));
    display.classList.toggle("is-error", state.error);
    document.querySelectorAll(".key--op").forEach(function (button) {
      button.classList.toggle("is-pending",
        !state.error && state.op === button.dataset.op && state.lhs !== null);
    });
  }

  function prettyOp(op) {
    return { "*": "\u00d7", "/": "\u00f7" }[op] || op;
  }

  function formatNumber(n) {
    if (state.error) return n;
    if (!isFinite(n)) return "Not a number";
    var s = String(n);
    return s.length > 14 ? Number(n).toPrecision(12).replace(/\.?0+$/, "") : s;
  }

  function setError(message) {
    state.error = true;
    state.entry = message;
    render();
  }

  function clearAll() {
    state.lhs = null;
    state.op = null;
    state.entry = "0";
    state.justEvaluated = false;
    state.error = false;
    render();
  }

  function inputDigit(d) {
    if (state.error) clearAll();
    if (state.justEvaluated) {
      state.entry = "0";
      state.justEvaluated = false;
    }
    if (state.op !== null && state.lhs !== null && !state.editingRhs) {
      state.entry = "0";
      state.editingRhs = true;
    }
    state.entry = state.entry === "0" ? d : state.entry + d;
    render();
  }

  function inputDecimal() {
    if (state.error) clearAll();
    if (state.justEvaluated) { state.entry = "0"; state.justEvaluated = false; }
    if (state.op !== null && state.lhs !== null && !state.editingRhs) {
      state.entry = "0";
      state.editingRhs = true;
    }
    if (state.entry.indexOf(".") === -1) state.entry += ".";
    render();
  }

  function backspace() {
    if (state.error) { clearAll(); return; }
    if (state.justEvaluated) { clearAll(); return; }
    state.entry = state.entry.length > 1 ? state.entry.slice(0, -1) : "0";
    render();
  }

  function negate() {
    if (state.error) return;
    if (state.entry !== "0") state.entry = state.entry.charAt(0) === "-"
      ? state.entry.slice(1) : "-" + state.entry;
    render();
  }

  function percent() {
    if (state.error) return;
    state.entry = String(Number(state.entry) / 100);
    render();
  }

  function setOperator(op) {
    if (state.error) clearAll();
    var current = Number(state.entry);
    // chain: 2 + 3 + ... evaluates the pending step first
    if (state.lhs !== null && state.op !== null && state.editingRhs) {
      var intermediate = Calc2066.calculate(state.lhs, current, state.op);
      if (isEngineError(intermediate)) { setError(intermediate); return; }
      state.lhs = Number(intermediate);
    } else {
      state.lhs = current;
    }
    state.op = op;
    state.entry = String(state.lhs);
    state.editingRhs = false;
    state.justEvaluated = false;
    render();
  }

  function equals() {
    if (state.error) return;
    if (state.lhs === null || state.op === null) return;
    var rhs = Number(state.entry);
    var result = Calc2066.calculate(state.lhs, rhs, state.op);
    expression.textContent = formatNumber(state.lhs) + " "
      + prettyOp(state.op) + " " + formatNumber(rhs) + " =";
    if (isEngineError(result)) {
      setError(result);
      state.lhs = null;
      state.op = null;
      return;
    }
    state.entry = String(Number(result));
    state.lhs = null;
    state.op = null;
    state.editingRhs = false;
    state.justEvaluated = true;
    render();
  }

  function isEngineError(resultText) {
    return resultText === "Cannot divide by zero"
      || resultText === "Unsupported operator";
  }

  function onKey(event) {
    var key = event.key;
    if (/^[0-9]$/.test(key)) { inputDigit(key); return; }
    if (key === ".") { inputDecimal(); return; }
    if (key === "+" || key === "-" || key === "*" || key === "/") {
      setOperator(key); return;
    }
    if (key === "Enter" || key === "=") { event.preventDefault(); equals(); return; }
    if (key === "Escape") { clearAll(); return; }
    if (key === "Backspace") { backspace(); return; }
    if (key === "%") { percent(); return; }
  }

  document.querySelector(".keys").addEventListener("click", function (event) {
    var button = event.target.closest("button.key");
    if (!button) return;
    if (button.dataset.digit) inputDigit(button.dataset.digit);
    else if (button.dataset.op) setOperator(button.dataset.op);
    else if (button.dataset.action === "decimal") inputDecimal();
    else if (button.dataset.action === "equals") equals();
    else if (button.dataset.action === "clear") clearAll();
    else if (button.dataset.action === "backspace") backspace();
    else if (button.dataset.action === "negate") negate();
    else if (button.dataset.action === "percent") percent();
  });

  document.addEventListener("keydown", onKey);

  render();
})();
