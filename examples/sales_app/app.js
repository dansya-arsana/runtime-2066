/* 2066 Sales dashboard — a thin viewer over the verified engines.
   The server rejects nothing here that the programs didn't already
   enforce; this file only renders what the runtime decided. */

let TOKEN = sessionStorage.getItem("2066salesToken") || "";
let MODE = "login";
let BOARD = null;

const $ = id => document.getElementById(id);
const esc = s => {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
};

/* ---------- auth ---------- */
function toggleMode() {
  MODE = MODE === "login" ? "register" : "login";
  $("auth-btn").textContent = MODE === "login" ? "Sign in" : "Create account";
  $("mode-label").textContent = MODE === "login" ? "sign in mode" : "register mode";
  $("auth-msg").textContent = "";
}

function authSubmit(e) {
  e.preventDefault();
  const btn = $("auth-btn");
  btn.disabled = true;
  api(`/api/${MODE}`, {username: val("username"), password: val("password")})
    .then(r => {
      if (r.token) {
        TOKEN = r.token;
        sessionStorage.setItem("2066salesToken", TOKEN);
        enter();
      } else {
        showMsg(r.result || r.error || "failed", false);
      }
    })
    .finally(() => btn.disabled = false);
  return false;
}

function showMsg(text, ok) {
  const el = $("auth-msg");
  el.textContent = text;
  el.classList.toggle("ok", !!ok);
}

function enter() {
  $("auth").hidden = true;
  $("app").hidden = false;
  $("who").textContent = `signed in as ${val("username") || "you"}`;
  refresh();
}

function logout() {
  sessionStorage.removeItem("2066salesToken");
  location.reload();
}

/* ---------- api ---------- */
async function api(path, body) {
  const opts = body
    ? {method: "POST", headers: {"Content-Type": "application/json"},
       body: JSON.stringify(body)}
    : {};
  try {
    return await fetch(path, opts).then(r => r.json());
  } catch {
    return {error: "network error"};
  }
}

const val = id => $(id).value.trim();

/* ---------- toasts ---------- */
function toast(text, kind) {
  const el = document.createElement("div");
  el.className = `toast ${kind || ""}`;
  el.textContent = text;
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), 3800);
}

/* ---------- modals ---------- */
function openModal(id) {
  $(id).hidden = false;
  const first = $(id).querySelector("input, select");
  if (first) first.focus();
}
function closeModal(id) { $(id).hidden = true; }
document.addEventListener("keydown", e => {
  if (e.key === "Escape")
    document.querySelectorAll(".overlay").forEach(o => o.hidden = true);
});
document.addEventListener("click", e => {
  if (e.target.classList?.contains("overlay")) e.target.hidden = true;
});

function populateBizSelects() {
  const opts = (BOARD?.businesses || [])
    .map(b => `<option value="${b.id}">${esc(b.name)} (#${b.id})</option>`)
    .join("");
  ["o-bid", "a-bid", "f-bid"].forEach(id => $(id).innerHTML = opts);
}

/* ---------- actions ---------- */
async function addBusiness() {
  const r = await api("/api/businesses", {token: TOKEN,
    name: val("b-name"), category: val("b-cat") || "business",
    city: val("b-city"), phone: val("b-phone"),
    website: val("b-web"), tier: val("b-tier")});
  if (r.result?.startsWith("ok:")) {
    toast(`business added — score computed by biz_add.ai`, "ok");
    closeModal("modal-biz");
    ["b-name", "b-cat", "b-city", "b-phone", "b-web"].forEach(i => $(i).value = "");
    refresh();
  } else toast(r.result || r.error, "err");
}

async function addOpp() {
  const r = await api("/api/opportunities", {token: TOKEN,
    business_id: val("o-bid"), title: val("o-title"), need: val("o-need"),
    value: val("o-value") || "0", next_action: val("o-action")});
  if (r.result?.startsWith("ok:")) {
    toast("opportunity created at stage new", "ok");
    closeModal("modal-opp");
    ["o-title", "o-need", "o-value", "o-action"].forEach(i => $(i).value = "");
    refresh();
  } else toast(r.result || r.error, "err");
}

async function addActivity() {
  const r = await api("/api/activities", {token: TOKEN,
    business_id: val("a-bid"), type: val("a-type") || "note",
    notes: val("a-notes")});
  if (r.result?.startsWith("ok:")) {
    toast("activity logged", "ok");
    closeModal("modal-act");
    ["a-type", "a-notes"].forEach(i => $(i).value = "");
    refresh();
  } else toast(r.result || r.error, "err");
}

async function addFollowup() {
  const r = await api("/api/followups", {token: TOKEN,
    business_id: val("f-bid"), action: val("f-action"),
    due_date: val("f-due")});
  if (r.result?.startsWith("ok:")) {
    toast("follow-up scheduled", "ok");
    closeModal("modal-fu");
    ["f-action", "f-due"].forEach(i => $(i).value = "");
    refresh();
  } else toast(r.result || r.error, "err");
}

const NEXT = {new: ["qualified"], qualified: ["proposal"],
              proposal: ["won", "lost"]};

async function advance(id, from) {
  const options = NEXT[from] || [];
  if (!options.length) { toast("terminal stage — won/lost cannot move", "err"); return; }
  const to = options.length === 1 ? options[0]
    : prompt(`advance to: ${options.join(" / ")}?`, options[0]);
  if (!to) return;
  const r = await api("/api/opportunity-stage", {token: TOKEN,
    id: String(id), from_stage: from, to_stage: to});
  if (r.result?.startsWith("ok:")) {
    toast(`stage moved to ${to} — enforced by opp_stage.ai`, "ok");
    refresh();
  } else toast(r.result || r.error, "err");
}

async function doneFollowup(id) {
  const r = await api("/api/followup-done", {token: TOKEN, id: String(id)});
  if (r.result?.startsWith("ok:")) { toast("follow-up closed", "ok"); refresh(); }
  else toast(r.result || r.error, "err");
}

async function discoverOSM() {
  const city = prompt("discover businesses in which city?", "Bandung");
  if (!city) return;
  const category = prompt("which category?", "cafe");
  if (!category) return;
  toast(`querying OpenStreetMap for ${category} in ${city}…`);
  const r = await api("/api/discover", {token: TOKEN, city, category, limit: 8});
  if (r.added !== undefined) {
    toast(`OSM: ${r.added} accepted, ${r.rejected} rejected by the engines`,
          r.added ? "ok" : "err");
    refresh();
  } else toast(r.error || "discovery failed", "err");
}

/* ---------- render ---------- */
const STAGE_CLASS = {new: "st-new", qualified: "st-qualified",
                     proposal: "st-proposal", won: "st-won", lost: "st-lost",
                     open: "st-open", done: "st-done"};
const STAGE_COLOR = {new: "#2563eb", qualified: "#b45309",
                     proposal: "#7c3aed", won: "#16a34a", lost: "#dc2626"};

function emptyFor(tableId, rows) {
  const el = document.querySelector(
    `.empty[data-empty-for="${tableId}"]`);
  if (el) el.classList.toggle("show", rows === 0);
}

async function refresh() {
  BOARD = await api("/api/board?token=" + encodeURIComponent(TOKEN));
  if (!BOARD || !BOARD.funnel) return;
  populateBizSelects();

  // KPIs
  const f = BOARD.funnel;
  const open = Number(f.new) + Number(f.qualified) + Number(f.proposal);
  const kpis = [
    ["Businesses", f.businesses, "discovered + added"],
    ["Open deals", open, "new + qualified + proposal"],
    ["Won", f.won, "closed successfully"],
    ["Follow-ups due", f.followups_open, "awaiting action", true],
  ];
  $("kpis").innerHTML = kpis.map(([l, v, note, accent]) => `
    <div class="kpi ${accent ? "accent" : ""}">
      <div class="k-label">${l}</div>
      <div class="k-value">${esc(v)}</div>
      <div class="k-note">${note}</div>
    </div>`).join("");

  // funnel stacked bar + legend
  const stages = ["new", "qualified", "proposal", "won", "lost"];
  const total = stages.reduce((a, s) => a + Number(f[s]), 0) || 1;
  $("funnel-bar").innerHTML = stages.map(s => {
    const n = Number(f[s]);
    return n === 0 ? "" :
      `<div class="seg" style="width:${(n / total) * 100}%;background:${STAGE_COLOR[s]}">${n}</div>`;
  }).join("") || `<div class="seg" style="width:100%;color:var(--faint)">empty pipeline</div>`;
  $("funnel-legend").innerHTML = stages.map(s =>
    `<span class="lg"><span class="dot" style="background:${STAGE_COLOR[s]}"></span>${s} · ${f[s]}</span>`).join("");

  // opportunities
  const oppRows = BOARD.opportunities || [];
  document.querySelector("#opp-table tbody").innerHTML = oppRows.map(o => `
    <tr>
      <td><span class="cell-main">${esc(o.title)}</span><br>
          <span class="cell-dim">deal #${o.id}</span></td>
      <td><span class="stage ${STAGE_CLASS[o.stage] || ""}">${o.stage}</span></td>
      <td>${o.value}</td>
      <td class="cell-dim">${esc(o.next_action)}</td>
      <td><button class="btn sm" onclick="advance(${o.id}, '${o.stage}')">advance →</button></td>
    </tr>`).join("");
  emptyFor("opp-table", oppRows.length);

  // businesses
  const bizRows = BOARD.businesses || [];
  document.querySelector("#biz-table tbody").innerHTML = bizRows.map(b => `
    <tr>
      <td><span class="cell-main">${esc(b.name)}</span><br>
          <span class="cell-dim">${esc(b.category)} · ${esc(b.stage)}</span></td>
      <td class="cell-dim">${esc(b.city)}</td>
      <td><span class="score-badge">${b.score}</span></td>
      <td><button class="btn sm ghost" title="create opportunity for this business"
            onclick="openModal('modal-opp');
                    document.getElementById('o-bid').value='${b.id}'">deal →</button></td>
    </tr>`).join("");
  emptyFor("biz-table", bizRows.length);

  // follow-ups (ids come from fu_ids.ai — real row ids, not positions)
  const fuRows = BOARD.followups || [];
  document.querySelector("#fu-table tbody").innerHTML = fuRows.map(x => `
    <tr>
      <td class="cell-main">${esc(x.action)}</td>
      <td class="cell-dim">${esc(x.due)}</td>
      <td><span class="stage ${STAGE_CLASS[x.status] || ""}">${x.status}</span></td>
      <td>${x.status === "open"
            ? `<button class="btn sm" onclick="doneFollowup(${x.id})">done</button>` : ""}</td>
    </tr>`).join("");
  emptyFor("fu-table", fuRows.length);

  // activities timeline (newest first)
  const acts = (BOARD.activities || []).slice(-8).reverse();
  $("acts").innerHTML = acts.map(a => `
    <li><span class="t-type">${esc(a.type)}</span>
        <span class="t-notes">${esc(a.notes)}</span></li>`).join("");
  emptyFor("acts", acts.length);
}

/* ---------- tabs + integrations ---------- */
function showTab(e, id) {
  e.preventDefault();
  document.querySelectorAll(".tab").forEach(t => t.hidden = t.id !== id);
  document.querySelectorAll(".nav-link").forEach(a =>
    a.classList.toggle("active", a.dataset.tab === id));
  if (id === "tab-integrations") loadIntegrations();
}

async function loadIntegrations() {
  const r = await api("/api/integrations");
  const live = r.live || {};
  const cron = r.cron || {};
  const up = (live.verdict || "").includes("UP");
  $("integration-list").innerHTML = `
    <div class="svc">
      <div>
        <div class="svc-name">sales-api <span class="cell-dim">· dev-api.arsana.cloud</span></div>
        <div class="cell-dim">real backend of the production sales machine — called by <code>api_health.ai</code></div>
      </div>
      <span class="stage ${up ? "st-won" : "st-lost"}">${esc(live.verdict || "checking…")}</span>
    </div>`;
  const when = cron.checked_at ? new Date(cron.checked_at + "Z").toLocaleString() : null;
  $("cron-info").innerHTML = cron.verdict
    ? `<div class="svc"><div>
         <div class="svc-name">last cron run</div>
         <div class="cell-dim">${esc(when)} (UTC) · verdict: <b>${esc(cron.verdict)}</b></div>
       </div></div>`
    : `<div class="empty show"><b>No cron run recorded yet</b>
       <span>the host crontab writes here every 5 minutes via cron_check.py</span></div>`;
}

if (TOKEN) enter();
