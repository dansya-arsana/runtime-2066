/* 2066 Sales dashboard — a thin viewer over the verified engines.
   The server rejects nothing here that the programs didn't already
   enforce; the UI only renders what the runtime decided. */

let TOKEN = sessionStorage.getItem("2066salesToken") || "";

async function api(path, body) {
  const opts = body
    ? {method: "POST", headers: {"Content-Type": "application/json"},
       body: JSON.stringify(body)}
    : {};
  const res = await fetch(path, opts);
  return res.json();
}

function msg(id, text, ok) {
  const el = document.getElementById(id);
  el.textContent = text;
  el.className = "msg " + (ok ? "ok" : "err");
}

async function register() {
  const r = await api("/api/register", {
    username: val("username"), password: val("password")});
  if (r.token) { TOKEN = r.token; sessionStorage.setItem("2066salesToken", TOKEN); enter(); }
  else msg("auth-msg", r.result || r.error, false);
}

async function login() {
  const r = await api("/api/login", {
    username: val("username"), password: val("password")});
  if (r.token) { TOKEN = r.token; sessionStorage.setItem("2066salesToken", TOKEN); enter(); }
  else msg("auth-msg", r.result || r.error, false);
}

function enter() {
  document.getElementById("auth").hidden = true;
  document.getElementById("app").hidden = false;
  document.getElementById("who").textContent = "session active";
  refresh();
}

const val = id => document.getElementById(id).value.trim();

async function addBusiness() {
  const r = await api("/api/businesses", {token: TOKEN,
    name: val("b-name"), category: val("b-cat"), city: val("b-city"),
    phone: val("b-phone"), website: val("b-web"), tier: val("b-tier")});
  msg("auth-msg", r.result, r.result && r.result.startsWith("ok:"));
  refresh();
}

async function addOpp() {
  const r = await api("/api/opportunities", {token: TOKEN,
    business_id: val("o-bid"), title: val("o-title"), need: val("o-need"),
    value: val("o-value"), next_action: val("o-action")});
  refresh();
}

async function addActivity() {
  await api("/api/activities", {token: TOKEN, business_id: val("a-bid"),
    type: val("a-type"), notes: val("a-notes")});
  refresh();
}

async function addFollowup() {
  await api("/api/followups", {token: TOKEN, business_id: val("f-bid"),
    action: val("f-action"), due_date: val("f-due")});
  refresh();
}

async function advance(id, from) {
  const NEXT = {"new": ["qualified"], "qualified": ["proposal"],
                "proposal": ["won", "lost"]};
  const options = NEXT[from] || [];
  if (!options.length) return;
  const to = options.length === 1 ? options[0]
    : prompt("move to: " + options.join(" / "), options[0]);
  if (!to) return;
  await api("/api/opportunity-stage", {token: TOKEN, id: String(id),
    from_stage: from, to_stage: to});
  refresh();
}

async function doneFollowup(id) {
  await api("/api/followup-done", {token: TOKEN, id: String(id)});
  refresh();
}

const STAGE_STYLE = {new: "st-new", qualified: "st-qual",
                     proposal: "st-prop", won: "st-won", lost: "st-lost"};

function esc(s) { const d = document.createElement("div");
  d.textContent = s ?? ""; return d.innerHTML; }

async function refresh() {
  const board = await api("/api/board?token=" + encodeURIComponent(TOKEN));
  if (!board.businesses) return;

  const f = board.funnel;
  const max = Math.max(1, ...Object.values(f).map(Number));
  document.getElementById("funnel").innerHTML =
    ["businesses", "new", "qualified", "proposal", "won", "lost",
     "activities", "followups_open"].map(k => `
      <div class="frow"><span class="flabel">${k.replace(/_/g, " ")}</span>
        <div class="bar"><div style="width:${(Number(f[k]) / max) * 100}%"></div></div>
        <span class="fval">${f[k]}</span></div>`).join("");

  document.querySelector("#biz-table tbody").innerHTML =
    board.businesses.map(b => `<tr>
      <td>${b.id}</td><td>${esc(b.name)}</td><td>${esc(b.city)}</td>
      <td>${esc(b.category)}</td><td class="score">${b.score}</td>
      <td><span class="stage ${STAGE_STYLE[b.stage] || ""}">${esc(b.stage)}</span></td>
      <td><button class="mini" onclick="document.getElementById('o-bid').value='${b.id}';
           document.getElementById('a-bid').value='${b.id}';
           document.getElementById('f-bid').value='${b.id}'">use</button></td>
    </tr>`).join("");

  document.querySelector("#opp-table tbody").innerHTML =
    board.opportunities.map(o => `<tr>
      <td>${o.id}</td><td>${esc(o.title)}</td>
      <td><span class="stage ${STAGE_STYLE[o.stage] || ""}">${esc(o.stage)}</span></td>
      <td>${o.value}</td><td>${esc(o.next_action)}</td>
      <td><button class="mini" onclick="advance(${o.id}, '${o.stage}')">→</button></td>
    </tr>`).join("");

  document.getElementById("acts").innerHTML =
    board.activities.slice(-6).reverse()
      .map(a => `<div class="act"><b>${esc(a.type)}</b> ${esc(a.notes)}</div>`)
      .join("");

  document.querySelector("#fu-table tbody").innerHTML =
    board.followups.map((f2, i) => `<tr>
      <td>${esc(f2.action)}</td><td>${esc(f2.due)}</td>
      <td>${esc(f2.status)}</td>
      <td>${f2.status === "open"
            ? `<button class="mini" onclick="doneFollowup(${i + 1})">done</button>` : ""}</td>
    </tr>`).join("");
}

if (TOKEN) enter();
