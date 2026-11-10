// expconfig web trial. Two views of one configuration, kept by the server:
//   /                the table (and Checks, Read back, Apply)
//   /?view=diagram   the wiring diagram, meant for its own window
// Every open page polls the server's version and redraws when anything changes, so
// several windows (or several people) stay in step. Selecting a cell in one window
// outlines the matching part in the other (BroadcastChannel).

const VIEW = new URLSearchParams(location.search).get("view") === "diagram" ? "diagram" : "table";
// The diagram is now the React page; an old ?view=diagram window (or bookmark) goes there.
if (VIEW === "diagram") location.replace("/diagram");
const $ = (id) => document.getElementById(id);
const SVGNS = "http://www.w3.org/2000/svg";
const channel = "BroadcastChannel" in window ? new BroadcastChannel("expconfig") : null;

let state = null;
let selected = { ai: null, key: null };

// ---- server --------------------------------------------------------------

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

async function act(path, body) {
  try {
    show(await api(path, body));
  } catch (err) {
    toast(err.message, true);
  }
}

async function poll() {
  try {
    const { version } = await api("/api/version");
    if (!state || version !== state.version) show(await api("/api/state"));
  } catch (err) {
    $("status").textContent = "server not reachable";
  }
}

function toast(text, bad = false) {
  const t = $("toast");
  t.textContent = text;
  t.className = bad ? "bad" : "";
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), bad ? 6000 : 3000);
}

// ---- selection shared between windows -----------------------------------

function select(ai, key, broadcast = true) {
  selected = { ai, key };
  if (VIEW === "table") markTable(); else markDiagram();
  if (broadcast && channel) channel.postMessage({ type: "select", ai, key });
}

if (channel) channel.onmessage = (ev) => { if (ev.data.type === "select") select(ev.data.ai, ev.data.key, false); };

// ---- popup editor (table cells and diagram parts) ------------------------

async function edit(ai, key, x, y) {
  const col = state.table.columns.find((c) => c.key === key);
  const row = state.table.rows.find((r) => r.ai === ai);
  if (!col || !row || !row.cells[key].edit) return;
  const current = row.cells[key].text;
  const { options, free } = await api(`/api/choices?key=${encodeURIComponent(key)}`);
  const p = $("popup");
  p.innerHTML = "";
  const title = document.createElement("div");
  title.className = "title";
  title.textContent = `AI ${ai}: ${col.title}`;
  p.append(title);
  const choose = (v) => { close(); act("/api/cell", { ai, key, value: String(v) }); };
  if (free || !options.length) {
    const input = document.createElement("input");
    input.value = current;
    input.placeholder = "type a value, Enter to apply";
    input.onkeydown = (e) => { if (e.key === "Enter") choose(input.value); if (e.key === "Escape") close(); };
    p.append(input);
    setTimeout(() => { input.focus(); input.select(); });
  }
  for (const o of options.slice(0, 60)) {
    const d = document.createElement("div");
    d.className = "opt" + (String(o) === current ? " on" : "");
    d.textContent = o === "" ? "(none)" : o;
    d.onclick = () => choose(o);
    p.append(d);
  }
  p.hidden = false;
  p.style.left = Math.min(x, innerWidth - p.offsetWidth - 8) + "px";
  p.style.top = Math.min(y, innerHeight - p.offsetHeight - 8) + "px";
  setTimeout(() => document.addEventListener("pointerdown", outside, true));
  function outside(e) { if (!p.contains(e.target)) close(); }
  function close() { p.hidden = true; document.removeEventListener("pointerdown", outside, true); }
}

// ---- table view ------------------------------------------------------------

function show(s) {
  state = s;
  $("status").textContent = s.status + (s.idn ? `   |   ${s.idn}` : "");
  if (VIEW === "table") drawTable(); else drawDiagram();
}

function drawTable() {
  const e = state.experiment, ins = state.instruments;
  $("experiment").innerHTML = dl({ Sample: e.sample, Device: e.device, User: e.user, Station: e.station,
                                   Description: e.description, Pads: e.pads });
  $("instruments").innerHTML = dl({ "Krohn-Hite": ins.kh.join(", "), "Lock-in": ins.lockin,
                                    Channels: `${state.table.rows.length} AI` });
  const { columns, rows, groups } = state.table;
  const t = $("channels");
  t.innerHTML = "";
  const thead = t.createTHead();
  const gr = thead.insertRow();
  gr.className = "groups";
  let i = 0;
  while (i < columns.length) {   // the group header: one cell per run of columns
    let j = i;
    while (j < columns.length && columns[j].group === columns[i].group) j++;
    const th = document.createElement("th");
    th.colSpan = j - i;
    th.textContent = columns[i].group;
    th.style.background = groups[columns[i].group] || "#f3f3f3";
    gr.append(th);
    i = j;
  }
  const hr = thead.insertRow();
  for (const c of columns) {
    const th = document.createElement("th");
    th.textContent = c.title;
    th.title = c.tip;
    hr.append(th);
  }
  const body = t.createTBody();
  for (const r of rows) {
    const tr = body.insertRow();
    tr.dataset.ai = r.ai;
    for (const c of columns) {
      const cell = r.cells[c.key];
      const td = tr.insertCell();
      td.textContent = cell.text;
      td.dataset.key = c.key;
      td.style.background = groups[c.group] || "#fff";
      const tips = [cell.why, cell.issue && `[${cell.issue.code}] ${cell.issue.message}`, cell.mismatch, c.tip];
      td.title = tips.filter(Boolean).join("\n");
      td.classList.toggle("edit", cell.edit);
      td.classList.toggle("derived", !cell.edit);
      td.classList.toggle("why", !!cell.why);
      if (cell.issue) td.classList.add(cell.issue.error ? "error" : "warn");
      else if (cell.mismatch) td.classList.add("mismatch");
      if (["ext_gain", "lockin_gain", "out_gain", "out_offset"].includes(c.key)) td.classList.add("num");
      if (["channel", "ai", "ao", "kh", "plus", "minus"].includes(c.key)) td.classList.add("center");
      td.onclick = (ev) => { select(r.ai, c.key); edit(r.ai, c.key, ev.clientX, ev.clientY); };
    }
  }
  const list = $("issues");
  list.innerHTML = "";
  for (const i of state.issues) {
    const li = document.createElement("li");
    li.className = i.error ? "error" : "note";
    li.textContent = `${i.error ? "Error" : "Note"} [${i.code}] ${i.ai != null ? "AI " + i.ai : ""}: ${i.message}`;
    if (i.ai != null) li.onclick = () => select(i.ai, null);
    list.append(li);
  }
  if (!state.issues.length) list.innerHTML = "<li>No problems found.</li>";
  markTable();
}

function dl(o) {
  const esc = (v) => String(v ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
  return "<dl>" + Object.entries(o).map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("") + "</dl>";
}

function markTable() {
  for (const tr of document.querySelectorAll("#channels tbody tr")) {
    tr.classList.toggle("selected", Number(tr.dataset.ai) === selected.ai);
    for (const td of tr.cells) td.classList.toggle("current",
      Number(tr.dataset.ai) === selected.ai && td.dataset.key === selected.key);
  }
}

// ---- diagram view ----------------------------------------------------------

let diagramVersion = -1;
let zoom = 1;

async function drawDiagram() {
  if (diagramVersion !== state.version) {
    diagramVersion = state.version;
    $("diagram").innerHTML = await (await fetch(`/api/diagram.svg?v=${state.version}`)).text();
  }
  const d = state.diagram;
  const o = $("overlay");
  o.setAttribute("viewBox", `0 0 ${d.width} ${d.height}`);
  o.innerHTML = "";
  const rect = (b, cls) => {
    const r = document.createElementNS(SVGNS, "rect");
    r.setAttribute("x", b[0]); r.setAttribute("y", b[1]);
    r.setAttribute("width", b[2]); r.setAttribute("height", b[3]);
    r.setAttribute("rx", 4);
    r.setAttribute("class", cls);
    return r;
  };
  const tip = (el, text) => {
    const t = document.createElementNS(SVGNS, "title");
    t.textContent = text;
    el.append(t);
  };
  for (const s of d.spots) {
    const r = rect(s.box, "spot");
    r.dataset.ai = s.ai; r.dataset.key = s.key;
    tip(r, s.tip.replace("double-click: edit in the table", "the table follows"));
    r.onclick = (ev) => { select(s.ai, s.key); edit(s.ai, s.key, ev.clientX, ev.clientY); };
    o.append(r);
  }
  for (const s of d.slots) {
    const r = rect(s.box, "slot");
    r.dataset.port = JSON.stringify(s.port);
    o.append(r);
  }
  for (const s of d.pads) {
    const r = rect(s.box, "pad");
    r.dataset.port = JSON.stringify(s.port);
    r.dataset.pad = "1";
    tip(r, s.tip);
    r.onpointerdown = (ev) => startDrag(ev, r, s);
    o.append(r);
  }
  for (const s of d.ports) {
    const c = document.createElementNS(SVGNS, "circle");
    c.setAttribute("cx", s.box[0] + s.box[2] / 2);
    c.setAttribute("cy", s.box[1] + s.box[3] / 2);
    c.setAttribute("r", s.box[2] / 2);
    c.setAttribute("class", "port");
    c.dataset.port = JSON.stringify(s.port);
    tip(c, s.tip);
    c.onpointerdown = (ev) => startDrag(ev, c, s);
    c.oncontextmenu = (ev) => {
      ev.preventDefault();
      if (!["kh+", "kh-"].includes(s.port[0])) return;
      if (confirm(`Disconnect the KH ${s.port[0] === "kh+" ? "+" : "−"} input of AI ${s.port[1]}?`))
        act("/api/disconnect", { port: s.port });
    };
    o.append(c);
  }
  markDiagram();
}

function markDiagram() {
  const o = $("overlay");
  o.querySelectorAll(".band").forEach((b) => b.remove());
  o.querySelectorAll(".spot").forEach((r) => r.classList.toggle("current",
    Number(r.dataset.ai) === selected.ai && r.dataset.key === selected.key));
  if (selected.ai == null || !state) return;
  const mine = state.diagram.spots.filter((s) => s.ai === selected.ai);
  if (!mine.length) return;
  const top = Math.min(...mine.map((s) => s.box[1])) - 4;
  const bottom = Math.max(...mine.map((s) => s.box[1] + s.box[3])) + 4;
  const band = document.createElementNS(SVGNS, "rect");
  band.setAttribute("class", "band");
  band.setAttribute("x", 0); band.setAttribute("y", top);
  band.setAttribute("width", state.diagram.width); band.setAttribute("height", bottom - top);
  o.prepend(band);
}

function toSvg(ev) {
  const o = $("overlay");
  const pt = o.createSVGPoint();
  pt.x = ev.clientX; pt.y = ev.clientY;
  return pt.matrixTransform(o.getScreenCTM().inverse());
}

function startDrag(ev, el, src) {
  if (ev.button !== 0) return;
  ev.preventDefault();
  const o = $("overlay");
  const isPad = el.dataset.pad === "1";
  // Light up where this can go: pad slots for a carried pad, every other end for a wire.
  o.querySelectorAll("[data-port]").forEach((t) => {
    if (t === el) return t.classList.add("from");
    if (isPad ? t.classList.contains("slot") : !t.classList.contains("slot")) t.classList.add("candidate");
  });
  let moving;
  if (isPad) {
    moving = document.createElementNS(SVGNS, "g");
    moving.setAttribute("class", "ghost");
    const [, , w, h] = src.box;
    moving.innerHTML = `<rect width="${w}" height="${h}" rx="4"></rect>` +
      `<text x="${w / 2}" y="${h / 2 + 4}" text-anchor="middle">${src.port[0] === "gnd" ? "GND" : src.port[1]}</text>`;
  } else {
    moving = document.createElementNS(SVGNS, "line");
    moving.setAttribute("class", "drag-line");
    const c = { x: src.box[0] + src.box[2] / 2, y: src.box[1] + src.box[3] / 2 };
    moving.setAttribute("x1", c.x); moving.setAttribute("y1", c.y);
    moving.setAttribute("x2", c.x); moving.setAttribute("y2", c.y);
  }
  o.append(moving);
  const move = (e) => {
    const p = toSvg(e);
    if (isPad) moving.setAttribute("transform", `translate(${p.x - src.box[2] / 2},${p.y - src.box[3] / 2})`);
    else { moving.setAttribute("x2", p.x); moving.setAttribute("y2", p.y); }
  };
  const up = (e) => {
    document.removeEventListener("pointermove", move);
    document.removeEventListener("pointerup", up);
    moving.remove();
    const target = document.elementsFromPoint(e.clientX, e.clientY)
      .find((t) => t !== el && t.dataset && t.dataset.port && t.classList.contains("candidate"));
    o.querySelectorAll(".candidate, .from").forEach((t) => t.classList.remove("candidate", "from"));
    if (target) act("/api/connect", { a: src.port, b: JSON.parse(target.dataset.port) });
  };
  document.addEventListener("pointermove", move);
  document.addEventListener("pointerup", up);
}

function setZoom(z) {
  zoom = Math.min(3, Math.max(0.5, z));
  $("diagram-wrap").style.width = `${zoom * 100}%`;
}

// ---- start -----------------------------------------------------------------

if (VIEW === "diagram") {
  document.title = "Wiring - expconfig";
  $("title").textContent = "Wiring";
  $("table-view").hidden = true;
  $("table-actions").hidden = true;
  $("diagram-view").hidden = false;
  $("diagram-actions").hidden = false;
  $("fit").onclick = () => setZoom(1);
  $("diagram-view").addEventListener("wheel", (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    setZoom(zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15));
  }, { passive: false });
  document.addEventListener("keydown", (e) => { if (e.key === "0" && !e.target.closest("input")) setZoom(1); });
} else {
  const openDiagram = () => window.open("/diagram", "expconfig-wiring", "width=760,height=900");
  $("open-diagram").onclick = openDiagram;
  $("readback").onclick = () => act("/api/readback", {});
  $("apply").onclick = () => act("/api/apply", {});
  document.addEventListener("keydown", (e) => {
    if (e.key.toLowerCase() === "d" && !e.ctrlKey && !e.altKey && !e.target.closest("input")) openDiagram();
  });
}

poll();
setInterval(poll, 1500);
