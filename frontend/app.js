/* PULSE console.
   One WebSocket in, one board render out. No polling: the whole point of the
   product is that state changes on its own, and polling makes that feel laggy. */

let STATE = null, OPEN = null;

const $ = (s) => document.querySelector(s);
const esc = (s) => (s || "").replace(/[&<>"]/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ---------------- socket ---------------- */
let POLLING = false;

function poll() {
  if (!POLLING) return;
  fetch("/api/board").then(r => r.json())
    .then(d => { STATE = d; render(); })
    .catch(() => {});
  setTimeout(poll, 1000);
}

/* WebSocket is the intended transport. If it is unavailable — an environment
   without the websockets extra, a proxy that strips upgrades — we fall back to
   polling rather than showing an empty board. Same principle as the rest of
   PULSE: degrade, do not die. */
function connect() {
  let ws;
  try {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
  } catch (_) { POLLING = true; poll(); return; }

  const fallback = setTimeout(() => {
    if (!STATE) { POLLING = true; poll(); }
  }, 2500);

  ws.onmessage = (e) => { clearTimeout(fallback); POLLING = false; STATE = JSON.parse(e.data); render(); };
  ws.onerror = () => { if (!POLLING) { POLLING = true; poll(); } };
  ws.onclose = () => { if (!POLLING) setTimeout(connect, 1500); };
}
connect();

async function post(url) { await fetch(url, { method: "POST" }); }

/* ---------------- sparkline ---------------- */
function spark(trace, alert) {
  if (!trace || trace.length < 2) return `<span class="pill">—</span>`;
  const w = 86, h = 24, lo = 0, hi = 100;
  const pts = trace.map((v, i) => {
    const x = (i / (trace.length - 1)) * w;
    const y = h - ((v - lo) / (hi - lo)) * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const col = alert ? "#FF3B5C" : "#A100FF";
  const last = trace[trace.length - 1];
  const ly = h - ((last - lo) / (hi - lo)) * h;
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.8"
      stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${w}" cy="${ly.toFixed(1)}" r="2.4" fill="${col}"/></svg>`;
}

/* ---------------- render ---------------- */
function render() {
  if (!STATE) return;
  $("#clock").textContent = STATE.clock;

  document.querySelectorAll("[data-speed]").forEach(b =>
    b.classList.toggle("on", ({ "1x": 1, "10x": 10, "60x": 60, "180x": 180 })[b.dataset.speed] === STATE.speed));
  $("#pause").textContent = STATE.running ? "PAUSE" : "RESUME";

  renderInbound();
  renderRows();
  renderCapacity();
  renderAgreement();
  renderEvents();
  renderModel();
  if (OPEN) renderDrawer(OPEN);
}

function renderInbound() {
  const box = $("#inbound");
  if (!STATE.inbound.length) {
    box.innerHTML = `<div class="empty">No inbound ambulances. Layer 0 is idle — most walk-in patients generate no pre-arrival signal at all, and PULSE falls through to door-time scoring.</div>`;
    return;
  }
  box.innerHTML = STATE.inbound.map(p => {
    const pr = p.prior;
    let said = esc(p.transcript || "");
    if (pr && pr.spans && pr.spans.length) {
      let out = "", cur = 0;
      pr.spans.forEach(s => {
        out += esc(p.transcript.slice(cur, s.start)) + `<mark>${esc(s.text)}</mark>`;
        cur = s.end;
      });
      said = out + esc(p.transcript.slice(cur));
    }
    return `<div class="amb">
      <div style="flex:1">
        <div class="who">${esc(p.display_id)} · age ${p.age} <span class="eta">· ETA ${p.eta_min} min</span></div>
        ${p.transcript ? `<div class="said">“${said}”</div>` : ""}
        ${pr ? `<div class="acts">${pr.actions.map(a => `<span>✓ ${esc(a)}</span>`).join("")}</div>` : ""}
      </div>
      ${pr ? `<div class="priorbox"><div class="pv">${pr.prior}</div>
        <div class="pl">PROVISIONAL · ${pr.confidence.toUpperCase()}</div></div>` : ""}
    </div>`;
  }).join("");
}

function renderRows() {
  const rows = STATE.rows;
  $("#boardCount").textContent =
    `${rows.filter(r => r.status === "waiting").length} waiting · ${rows.filter(r => r.status === "in-treatment").length} in treatment`;

  $("#rows").innerHTML = rows.map(r => {
    const alert = r.pending && r.assigned_esi;      // an escalation awaiting the nurse
    const shown = r.assigned_esi || r.esi;
    const cls = r.assigned_esi ? shown : "none";
    let act;
    if (r.status === "in-treatment") act = `<span class="pill">IN TREATMENT</span>`;
    else if (r.pending) act = `<button class="mini act" data-open="${r.id}">REVIEW</button>`;
    else act = `<button class="mini ok" data-admit="${r.id}">MOVE TO BED</button>`;

    return `<div class="row ${alert ? "alert" : ""} ${r.status === "in-treatment" ? "treat" : ""}" data-open="${r.id}">
      <div><div class="pid">${esc(r.display_id)}</div><div class="page">age ${r.age} · ${esc(r.arrival_mode)}</div></div>
      <div class="comp">${esc(r.complaint)}</div>
      <div class="esi ${cls}">${r.assigned_esi ? shown : "—"}</div>
      <div class="ari" style="color:${r.ari >= 68 ? "#FF3B5C" : r.ari >= 40 ? "#FFA828" : "#12D08A"}">${r.ari}</div>
      <div>${spark(r.trace, r.trend && r.trend.rising)}</div>
      <div class="wait">${Math.round(r.waited)}m</div>
      <div class="rowact">${act}</div>
    </div>`;
  }).join("");
}

function renderCapacity() {
  const beds = STATE.capacity.beds, base = { "Acute majors": 3, "Fast track": 4 };
  $("#cap").innerHTML = Object.entries(beds).map(([k, v]) => {
    const max = base[k] || 1, pct = Math.min(100, (v / max) * 100);
    const cls = v === 0 ? "none" : v <= max * 0.34 ? "low" : "";
    return `<div class="cline"><span class="nm">${esc(k)}</span>
      <span class="bar"><i class="${cls}" style="width:${pct}%"></i></span>
      <span class="n">${v}/${max}</span></div>`;
  }).join("") + `<div class="cline" style="margin-top:6px">
    <span class="nm" style="color:var(--dim)">Staff on shift</span>
    <span class="n">${STATE.capacity.staff_on}</span></div>`;
}

function renderAgreement() {
  const a = STATE.agreement;
  $("#agreeRate").textContent = a.rate === null ? "—" : `${Math.round(a.rate * 100)}%`;
  $("#agreeTxt").textContent = a.total === 0
    ? "No decisions yet. In a real pilot PULSE runs in shadow mode until this number is trusted."
    : `${a.accepted} accepted of ${a.total} recommendations this shift.`;
}

function renderEvents() {
  $("#events").innerHTML = STATE.events.length
    ? STATE.events.map(e => `<div class="ev ${esc(e.kind)}">
        <span class="t">${esc(e.at)}</span><span class="x">${esc(e.text)}</span></div>`).join("")
    : `<div class="empty">Shift just started.</div>`;
}

function renderModel() {
  const m = STATE.model;
  $("#model").innerHTML = `
    <div class="mstat"><div class="v">${m.roc_auc}</div><div class="k">ROC-AUC</div></div>
    <div class="mstat"><div class="v">${(m.sensitivity * 100).toFixed(1)}%</div><div class="k">sensitivity <span style="color:#6D558C">(ESI: 65.9%)</span></div></div>
    <div class="mstat"><div class="v">${(m.undertriage_rate * 100).toFixed(1)}%</div><div class="k">under-triage <span style="color:#6D558C">(ESI: 3.3%)</span></div></div>
    <div class="mstat"><div class="v">${m.n_test.toLocaleString()}</div><div class="k">held-out encounters</div></div>`;
}

/* ---------------- drawer ---------------- */
function renderDrawer(id) {
  const r = STATE.rows.find(x => x.id === id);
  if (!r) return;
  OPEN = id;
  $("#drawer").classList.add("on");
  $("#scrim").classList.add("on");
  $("#dTag").textContent = `${r.arrival_mode.toUpperCase()} · WAITING ${Math.round(r.waited)} MIN`;
  $("#dName").textContent = `${r.display_id} · age ${r.age}`;

  const V = r.vitals || {};
  const vitalDef = [
    ["HR", "heart_rate", "bpm", v => v > 110 || v < 50],
    ["BP", "systolic_bp", "mmHg", v => v < 100],
    ["SpO₂", "spo2", "%", v => v < 93],
    ["RR", "resp_rate", "/min", v => v > 22],
    ["DBP", "diastolic_bp", "mmHg", v => v < 60],
    ["TEMP", "temperature", "°C", v => v > 38 || v < 35.5],
  ];
  const vitalsHtml = vitalDef.map(([k, key, u, bad]) => {
    const v = V[key];
    if (v === undefined || v === null)
      return `<div class="vc missing"><div class="k">${k}</div><div class="v">not taken</div></div>`;
    return `<div class="vc ${bad(v) ? "bad" : ""}"><div class="k">${k}</div>
      <div class="v">${v}<span style="font-size:9px;color:#6D558C"> ${u}</span></div></div>`;
  }).join("");

  const maxAbs = Math.max(...r.drivers.map(d => Math.abs(d.contribution)), 0.01);
  const driversHtml = r.drivers.length ? r.drivers.map(d => `
    <div class="bar2"><div class="lb"><span>${esc(d.label)} ${d.value ?? ""}</span>
      <span>${d.direction === "raises" ? "+" : ""}${d.contribution.toFixed(2)}</span></div>
    <div class="tk"><i class="${d.direction === "lowers" ? "neg" : ""}"
      style="width:${(Math.abs(d.contribution) / maxAbs * 100).toFixed(0)}%"></i></div></div>`).join("")
    : `<div class="note">Not enough vitals recorded to attribute a score.</div>`;

  let complaint = esc(r.complaint);
  if (r.spans && r.spans.length) {
    let out = "", cur = 0;
    r.spans.forEach(s => {
      out += esc(r.complaint.slice(cur, s.start)) + `<mark title="${esc(s.label)}">${esc(s.text)}</mark>`;
      cur = s.end;
    });
    complaint = out + esc(r.complaint.slice(cur));
  }

  const trendHtml = r.trend && r.trend.reason
    ? `<div class="sec"><h4>LAYER 4 · DETERIORATION ENGINE</h4>
        <div class="quote" style="border-left-color:${r.trend.rising ? "#FF3B5C" : "#A100FF"}">
          ${r.trend.trace ? r.trend.trace.map(v => `<b>${v}</b>`).join(" → ") + "<br>" : ""}
          ${esc(r.trend.reason)}</div></div>` : "";

  const gate = r.pending ? `
    <div class="gate">
      <div class="g">● HUMAN DECISION GATE</div>
      <div class="rec">PULSE recommends<br>
        <b>ESI ${r.esi}</b> — ${r.confidence} confidence<br>
        <b>${esc(r.routing.pathway)}</b><br>
        <b>${esc(r.routing.specialty)}</b>${r.routing.specialist_available ? "" : " — page required"}</div>
      ${r.routing.notes.length ? `<div class="note">${r.routing.notes.map(esc).join(" · ")}</div>` : ""}
      <div class="gbtns">
        <button class="acc" data-decide="${r.id}|accept">ACCEPT</button>
        <button class="ovr" data-decide="${r.id}|override">OVERRIDE</button>
      </div>
      <div class="note">Overrides are logged. PULSE never sets acuity itself.</div>
    </div>`
    : `<div class="gate" style="border-color:rgba(18,208,138,.4);background:rgba(18,208,138,.05)">
        <div class="g" style="color:#12D08A">● NO OPEN RECOMMENDATION</div>
        <div class="rec">Assigned <b>ESI ${r.assigned_esi || "—"}</b> by the nurse.<br>
          Routed to <b>${esc(r.pathway)}</b>.<br>
          PULSE continues re-scoring while this patient waits.</div></div>`;

  $("#dBody").innerHTML = `
    <div class="sec"><h4>PRESENTING COMPLAINT · LAYER 2 EXTRACTION</h4>
      <div class="quote">${complaint}</div></div>
    ${r.prior ? `<div class="sec"><h4>LAYER 0 · PRE-ARRIVAL PRIOR</h4>
      <div class="quote" style="border-left-color:#FFA828">Prior <b>${r.prior.prior}</b>
      (${r.prior.confidence} confidence, provisional). Superseded on arrival —
      it now contributes a decayed fraction of the fused score.</div></div>` : ""}
    <div class="sec"><h4>VITALS · ${r.vitals_present} OF 6 RECORDED</h4>
      <div class="vgrid">${vitalsHtml}</div>
      ${r.vitals_present < 3 ? `<div class="note">Fewer than three vitals recorded — PULSE flags this score as extrapolated rather than returning a confident-looking number.</div>` : ""}
    </div>
    <div class="sec"><h4>ARRIVAL RISK INDEX · ${r.ari} → ESI ${r.esi}</h4>
      ${driversHtml}
      <div class="note">Exact SHAP contributions from the Layer 1 model, not a proxy.</div>
    </div>
    ${trendHtml}
    <div class="sec">${gate}</div>`;
}

function closeDrawer() {
  OPEN = null;
  $("#drawer").classList.remove("on");
  $("#scrim").classList.remove("on");
}

/* ---------------- events ---------------- */
document.addEventListener("click", async (e) => {
  const openEl = e.target.closest("[data-open]");
  const admitEl = e.target.closest("[data-admit]");
  const decideEl = e.target.closest("[data-decide]");
  const speedEl = e.target.closest("[data-speed]");

  if (decideEl) {
    e.stopPropagation();
    const [id, action] = decideEl.dataset.decide.split("|");
    const url = action === "override"
      ? `/api/decide/${id}/override?esi=III` : `/api/decide/${id}/accept`;
    await post(url);
    return;
  }
  if (admitEl) { e.stopPropagation(); await post(`/api/admit/${admitEl.dataset.admit}`); return; }
  if (openEl) { renderDrawer(openEl.dataset.open); return; }
  if (speedEl) { await post(`/api/control/speed?value=${speedEl.dataset.speed}`); return; }
  if (e.target.id === "pause") { await post("/api/control/pause"); return; }
  if (e.target.id === "reset") { closeDrawer(); await post("/api/control/reset"); return; }
  if (e.target.id === "dClose" || e.target.id === "scrim") closeDrawer();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
