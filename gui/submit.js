const $ = (s, r = document) => r.querySelector(s);
const state = { schema: null, params: {}, rows: [], examples: [], example: "", launched: null, profile: "savemem", nodes: [] };

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = text;
  return n;
}
function icon(name) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("class", "ic");
  const u = document.createElementNS("http://www.w3.org/2000/svg", "use");
  u.setAttribute("href", `#i-${name}`);
  s.append(u);
  return s;
}
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
};
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const human = (b) => (b > 1e9 ? `${(b / 1e9).toFixed(2)} GB` : b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.round(b / 1e3)} kB`);

function table(head, rows, valCols = []) {
  const wrap = el("div", "tbl"), t = el("table"), th = el("thead"), hr = el("tr"), tb = el("tbody");
  head.forEach((h) => hr.append(el("th", null, h)));
  th.append(hr);
  rows.forEach((r) => {
    const tr = el("tr");
    r.forEach((c, i) => tr.append(el("td", valCols.includes(i) ? "val" : null, c)));
    tb.append(tr);
  });
  t.append(th, tb); wrap.append(t);
  return wrap;
}

function rich(tag, text, cls) {
  const n = el(tag, cls);
  String(text).split("`").forEach((part, i) => n.append(i % 2 ? el("code", null, part) : document.createTextNode(part)));
  return n;
}

function paramValue(key) {
  const [sec, first] = key.split(" ")[0].split(".");
  const out = [];
  for (const k of key.split(" / ").map((x, i) => (i ? x.trim() : first))) {
    const v = (state.params[sec] || {})[k];
    if (v !== undefined) out.push(String(v));
  }
  return out.join(" / ") || "—";
}

function renderInfo() {
  const info = state.schema.info || {}, box = $("#info");
  box.textContent = "";
  box.append(el("h2", null, "Inputs and parameters"),
    el("p", null, "What each input is, which step reads it, and how every variable in configs/param_configs.yaml maps to the original tool arguments. Values are the current ones; each analysis freezes its own copy in results/<analysis>/inputs/params.yaml."));
  box.append(el("h4", null, "Input data types"));
  const ui = el("ul", "vars");
  for (const x of info.inputs || []) {
    const li = el("li"), head = el("div", "var-head");
    head.append(rich("strong", x.name), rich("span", x.format, "fmt"));
    li.append(head, rich("p", x.use));
    ui.append(li);
  }
  box.append(ui);
  box.append(el("h4", null, "Variables"));
  const ul = el("ul", "vars");
  for (const x of info.params || []) {
    const li = el("li"), head = el("div", "var-head");
    head.append(el("code", "key", x.key));
    const v = paramValue(x.key);
    if (v !== "—") head.append(el("span", "eq", "="), el("code", "val", v));
    li.append(head, rich("p", x.meaning), rich("p", `Step: ${x.used_by} · Original argument: ${x.arg}`, "where"));
    ul.append(li);
  }
  box.append(ul);
  box.append(el("h4", null, "Original command lines"));
  for (const c of info.commands || []) {
    box.append(el("p", null, `${c.step} · ${c.tool}`), el("pre", "cmd", c.cmd));
  }
}

function toggleInfo(show) {
  $("#info").hidden = !show;
  $("#toggle-info span").textContent = show ? "Hide info" : "Show info";
  store.set("kv_info", show ? "1" : "0");
}

function field(f, value) {
  const wrap = el("div", "field" + (f.type === "textarea" ? " wide" : ""));
  const id = `${f.id}_${Math.random().toString(36).slice(2, 8)}`;
  const label = el("label", null, f.label);
  label.htmlFor = id;
  if (f.required) label.insertAdjacentHTML("beforeend", ' <span class="req">*</span>');
  let input;
  if (f.type === "select") {
    input = el("select");
    for (const o of f.options) input.add(new Option(o, o));
    input.value = value || f.default || f.options[0];
  } else if (f.type === "textarea") {
    input = el("textarea");
    input.value = value ?? "";
  } else if (f.type === "checkbox") {
    input = el("input", "tick");
    input.type = "checkbox";
    input.checked = ["1", "true", true, 1].includes(value);
  } else {
    input = el("input");
    input.type = f.type;
    if (f.step) input.step = f.step;
    input.value = value ?? f.default ?? "";
  }
  input.id = id;
  input.dataset.field = f.id;
  if (f.help && f.type !== "checkbox") input.placeholder = f.help;
  if (f.type === "checkbox") {
    const c = el("label", "check"); c.append(input, document.createTextNode(f.help || ""));
    wrap.append(label, c);
  } else wrap.append(label, input);
  return wrap;
}

function pathField(f, value) {
  const wrap = field(f, value), input = $("input", wrap), hint = el("p", "hint");
  const dl = el("datalist"); dl.id = `${input.id}_dl`; input.setAttribute("list", dl.id); input.autocomplete = "off";
  const check = debounce(async () => {
    const r = await (await fetch(`/api/path?p=${encodeURIComponent(input.value.trim())}`)).json();
    dl.textContent = "";
    r.entries.slice(0, 200).forEach((e) => dl.append(new Option(e)));
    const v = input.value.trim();
    hint.className = "hint";
    input.classList.remove("bad");
    if (!v) hint.textContent = "Type an absolute path; folders and FASTQ files are suggested.";
    else if (r.file) { hint.textContent = `✓ found · ${human(r.size)}`; hint.classList.add("ok"); }
    else if (r.exists) hint.textContent = "Folder: keep typing to pick a FASTQ file.";
    else { hint.textContent = "✗ no such file on the cluster"; hint.classList.add("err"); input.classList.add("bad"); }
  }, 250);
  input.addEventListener("input", check);
  input.addEventListener("focus", check);
  wrap.append(dl, hint);
  if (value) check();
  return wrap;
}

function sourceGroup(g, values) {
  const sec = el("div", "group"), head = el("div", "group-head"), seg = el("div", "seg small"), fields = el("div", "fields");
  head.append(el("h4", null, g.name), seg);
  const local = g.fields.find((f) => f.id === "fastq_path"), sra = g.fields.find((f) => f.id === "srr");
  const fLocal = pathField(local, values.fastq_path), fSra = field(sra, values.srr);
  fields.append(fLocal, fSra);
  const modes = { local: ["Local file", "folder", fLocal, "srr"], sra: ["SRA", "cloud", fSra, "fastq_path"] };
  const set = (m, clear) => {
    for (const [k, [, , node, other]] of Object.entries(modes)) {
      node.hidden = k !== m;
      if (k === m && clear) { const o = $(`[data-field="${other}"]`, fields); o.value = ""; o.dispatchEvent(new Event("input")); }
    }
    for (const b of seg.children) b.classList.toggle("on", b.dataset.mode === m);
  };
  for (const [k, [label, ic]] of Object.entries(modes)) {
    const b = el("button"); b.type = "button"; b.dataset.mode = k; b.append(icon(ic), document.createTextNode(label));
    b.addEventListener("click", () => set(k, true));
    seg.append(b);
  }
  set(values.srr && !values.fastq_path ? "sra" : "local", false);
  sec.append(head, fields);
  return sec;
}

function card(values = {}) {
  const node = $("#card").content.firstElementChild.cloneNode(true);
  const groups = $(".groups", node);
  const extra = el("details", "extra"), names = [];
  for (const g of state.schema.groups) {
    if (g.source) { groups.append(sourceGroup(g, values)); continue; }
    const sec = el("div", "group"), fields = el("div", "fields");
    sec.append(el("h4", null, g.name));
    for (const f of g.fields) fields.append(field(f, values[f.id]));
    sec.append(fields);
    if (g.optional) { extra.append(sec); names.push(g.name.toLowerCase()); } else groups.append(sec);
  }
  if (names.length) {
    const su = el("summary");
    su.append(el("span", "extra-title", "Optional details"), el("span", "extra-sub", `${names.join(", ")} · provenance only, not used by the tools`));
    extra.prepend(su);
    groups.append(extra);
  }
  const title = $(".title", node), sid = $('[data-field="sample_id"]', node);
  const retitle = () => (title.textContent = sid.value.trim() || "New sample");
  sid.addEventListener("input", retitle);
  retitle();
  $('[data-act="del"]', node).addEventListener("click", () => {
    node.remove();
    state.rows = state.rows.filter((n) => n !== node);
  });
  $('[data-act="dup"]', node).addEventListener("click", () => add({ ...read(node), sample_id: "" }));
  return node;
}

function read(node) {
  const out = {};
  for (const e of node.querySelectorAll("[data-field]"))
    out[e.dataset.field] = e.type === "checkbox" ? (e.checked ? "1" : "0") : e.value.trim();
  return out;
}

function add(values) {
  const node = card(values);
  state.rows.push(node);
  $("#samples").append(node);
  return node;
}

function fill(samples) {
  $("#samples").textContent = "";
  state.rows = [];
  (samples.length ? samples : [{}]).forEach(add);
}

function status(text, isError) {
  const s = $("#status");
  s.hidden = false;
  s.textContent = text;
  s.classList.toggle("err", !!isError);
}

async function init() {
  state.schema = await (await fetch("/api/schema")).json();
  state.params = await (await fetch("/api/params")).json();
  const exr = await fetch("/api/examples");
  state.examples = exr.ok ? (await exr.json()).examples || [] : [];
  const sel = $("#example");
  sel.append(new Option("Example: —", ""));
  for (const e of state.examples) sel.append(new Option(`${e.short} — ${e.title}`, e.name));
  if (state.examples.length > 1) sel.append(new Option(`All examples (${state.examples.map((e) => e.short).join(", ")})`, "all"));
  sel.addEventListener("change", () => pickExample(sel.value));
  renderInfo();
  toggleInfo(store.get("kv_info") !== "0");
  fill([]);
  if (location.hash === "#perf") togglePerf(true);
  if (!exr.ok) status("No examples: this console server is older than the page (/api/examples not found). Stop it (ctrl-c) and start python3 src/gui_serve.py again.", true);
}

async function loadSaved() {
  const { samples } = await (await fetch("/api/samples")).json();
  fill(samples);
  setExample("");
  status(samples.length ? `${samples.length} saved sample(s) loaded from configs/samples.tsv` : "No saved samples.", false);
}

function setExample(name) {
  state.example = name;
  $("#example").value = name;
  const all = name === "all";
  for (const id of ["#submit", "#add"]) $(id).disabled = all;
  renderRunNote();
}

const allNames = (base) => state.examples.map((e) => `${base || "<name>"}_${e.short}`);

function renderRunNote() {
  const n = $("#run-note");
  n.hidden = state.example !== "all";
  n.textContent = n.hidden ? "" : `All examples selected: Run on SLURM launches ${allNames(currentAnalysis()).join(", ")}, one analysis per example with its own parameters.`;
}

function lock(node, tag) {
  for (const e of node.querySelectorAll("input, select, textarea, button")) e.disabled = true;
  $(".title", node).after(el("span", "badge tag", tag));
}

function pickExample(name) {
  if (!name) return clearSamples();
  if (name === "all") {
    $("#samples").textContent = "";
    state.rows = [];
    for (const e of state.examples) for (const x of e.samples) lock(add({ ...x }), e.short);
    setExample("all");
    return status(`All examples: ${state.examples.map((e) => e.short).join(", ")}. Each one runs as its own analysis with its own parameters, read as-is from configs/examples/<folder>/, so these cards are read-only and nothing is saved here. Go to Run, type a base name and click Run on SLURM: it launches ${allNames("").join(", ")}.\n\n${state.examples.map((e) => e.credit).join("\n\n")}`, false);
  }
  const ex = state.examples.find((e) => e.name === name);
  fill(ex.samples.map((x) => ({ ...x })));
  setExample(ex.name);
  status(`${ex.credit}\n\nSave to use them: saving also replaces configs/param_configs.yaml with this example's (the previous one is kept as configs/param_configs.yaml.bak). Clear empties the cards.`, false);
}

function clearSamples() {
  fill([]);
  setExample("");
  status("Cards cleared. Nothing is saved until you click Save samples.", false);
}

async function submit() {
  const samples = state.rows.map(read);
  const res = await fetch("/api/samples", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ samples, example: state.example }) });
  const body = await res.json();
  if (!res.ok) return status("Not saved:\n  " + (body.errors || [body.error]).join("\n  "), true);
  const lines = [`Saved ${body.n} sample(s).`, `  ${body.samples_tsv}`, ...body.sample_json.map((p) => `  ${p}`)];
  if (body.params_yaml) {
    lines.push(`Parameters of example ${state.example} copied to ${body.params_yaml} (previous one kept as ${body.params_yaml}.bak).`);
    state.params = await (await fetch("/api/params")).json();
    renderInfo();
    setExample("");
  }
  status(lines.join("\n"), false);
}

function tab(name) {
  if (state.perf) togglePerf(false);
  state.tab = name;
  for (const b of document.querySelectorAll("nav button")) b.classList.toggle("on", b.dataset.tab === name);
  for (const id of ["samples", "run", "results"]) $(`#tab-${id}`).hidden = id !== name;
  if (name === "run") refreshStatus();
  if (name === "results") refreshResults();
}

function describeRuntime(rt) {
  const ok = (x) => (x ? "✓" : "✗");
  return `${rt.sif ? rt.sif.split("/").pop() : "image pulled on first run"} · singularity ${ok(rt.apptainer)} · sbatch ${ok(rt.sbatch)} · get_best_node ${rt.node_pick ? "on" : "off"}`;
}

const currentAnalysis = () => $("#analysis").value.trim();
const badge = (s, text) => el("span", `badge ${s}`, text || s);

function fillPickers(list, running) {
  for (const sel of [$("#pick"), $("#pick-results")]) {
    const keep = sel.value;
    sel.textContent = "";
    sel.append(new Option(sel.id === "pick" ? "—" : "Analysis", ""));
    for (const a of list) sel.append(new Option(`${a.name}${a.group ? ` (group ${a.group})` : ""}${a.done ? " ✓" : ""}${a.name === running ? " (running)" : ""}`, a.name));
    sel.value = keep;
  }
}

function bar(parts, label) {
  const w = el("div", "bar-wrap"), b = el("div", "bar");
  for (const [cls, pct] of parts) { const i = el("i", cls); i.style.width = `${pct}%`; b.append(i); }
  w.append(b, el("span", "bar-label", label));
  return w;
}

function renderSteps(steps) {
  const box = $("#steps");
  box.textContent = "";
  if (!steps.length) { box.append(el("p", "muted item", "Pick or name an analysis.")); return; }
  for (const s of steps) {
    const d = el("details"), su = el("summary");
    const st = s.failed || s.cancelled ? "failed" : s.total && s.done === s.total ? "done" : s.running ? "running" : s.done ? "stopped" : "waiting";
    const pct = (n) => (s.total ? (100 * n) / s.total : 0);
    su.append(el("span", "step-name", s.step), badge(st, st === "stopped" ? "partial" : st),
      bar([["ok", pct(s.done)], ["bad", pct(s.failed + (s.cancelled || 0))], ["run", pct(s.running)]], `${s.done}/${s.total}${s.failed ? ` · ${s.failed} failed` : ""}${s.cancelled ? ` · ${s.cancelled} cancelled` : ""}`));
    su.lastChild.style.flex = "1"; su.lastChild.style.marginTop = "0";
    const jobs = el("div", "jobs");
    for (const j of s.jobs) {
      const r = el("div", "job");
      r.append(badge(j.state), el("span", null, j.job), el("code", null, j.log), el("span", "when", j.updated || ""));
      if (j.tail) r.append(el("pre", null, j.tail));
      jobs.append(r);
    }
    d.append(su, jobs);
    if (s.failed || s.cancelled) { d.open = true; d.classList.add("has-failed"); }
    box.append(d);
  }
}

function renderQueue(q, running) {
  const box = $("#squeue");
  box.textContent = "";
  if (!q.length) { box.append(el("p", "muted item", running ? "No jobs of this run in the queue right now." : "—")); return; }
  const wrap = el("div", "item");
  wrap.append(table(["Job", "Rule", "State", "Time", "Partition", "Node / reason"], q.map((x) => [x.job, x.rule, x.state, x.time, x.partition, x.where])));
  box.append(wrap);
}

async function refreshStatus() {
  const name = currentAnalysis();
  const s = await (await fetch(`/api/status?analysis=${encodeURIComponent(name)}`)).json();
  fillPickers(s.analyses || [], s.running ? (s.state || {}).analysis : null);
  if (name && [...$("#pick").options].some((o) => o.value === name)) $("#pick").value = name;
  $("#runtime").textContent = describeRuntime(s.runtime);
  const st = s.state || {}, rs = $("#run-state");
  rs.textContent = "";
  rs.append(badge(s.outcome));
  const where = (st.nodes || []).length ? ` · ${st.nodes.length > 1 ? "nodes" : "node"} ${st.nodes.join(", ")}` : st.node ? ` · node ${st.node}` : "";
  if (st.started_at) rs.append(el("strong", null, st.analysis), el("span", "muted", `started ${st.started_at} · ${(st.samples || []).length} samples · ${{ savemem: "SaveMem", processive: "Processive", custom: "Custom" }[st.profile] || "SaveMem"}${where} · results/${st.analysis}/`));
  else if (name) rs.append(el("strong", null, name));
  renderGroup(s.group || [], name);
  const ov = $("#overall");
  ov.hidden = !s.progress;
  if (s.progress) {
    ov.querySelector("i").style.width = `${s.progress.pct}%`;
    ov.querySelector("i").className = s.outcome === "failed" ? "bad" : s.outcome === "done" ? "ok" : "";
    ov.querySelector(".bar-label").textContent = `${s.progress.done} of ${s.progress.total} jobs · ${s.progress.pct}%`;
  }
  $("#run-sbatch").disabled = s.running;
  $("#stop").disabled = !s.running;
  renderSteps(s.steps || []);
  renderQueue(s.queue || [], s.running);
  $("#nodelog").textContent = s.node_log || "—";
  $("#runlog").textContent = s.log || "—";
  return s;
}

const memberBar = (m) => ({ done: "ok", failed: "bad", running: "run" })[m.outcome] || "low";

function renderGroup(members, current) {
  const box = $("#group"), errs = Object.entries((state.launched || {}).errors || {});
  box.textContent = "";
  box.hidden = members.length < 2 && !errs.length;
  if (box.hidden) return;
  if (members.length) box.append(el("p", "muted group-note", `Group ${members[0].group}: ${members.length} analyses launched together. Pick one to follow its steps below.`));
  for (const m of members) {
    const b = el("button", "member"), p = m.progress, on = m.name === current;
    b.type = "button"; b.setAttribute("aria-pressed", String(on));
    b.append(badge(m.outcome), el("span", "member-name", m.name), bar([[memberBar(m), p ? p.pct : 0]], p ? `${p.done} of ${p.total} jobs` : "no jobs"));
    b.addEventListener("click", () => { $("#analysis").value = m.name; renderRunNote(); refreshStatus(); });
    box.append(b);
  }
  for (const [n, e] of errs) { const r = el("div", "member"); r.append(badge("failed", "not started"), el("span", "member-name", n), el("span", null, e.join("; "))); box.append(r); }
}

const PROFILES = {
  savemem: "One node, never more than half of it and at most 32 cores / 64 GB. The gentlest choice for the shared cluster.",
  processive: "Up to 2 nodes of the same partition, at most half of each. The second node is added only when more jobs could run in parallel than fit on the first.",
  custom: "Tick 1 to 4 of the nodes that are free now (most available first). At most half of each is used, and only as many nodes as the parallel jobs need.",
};

function setProfile(p) {
  state.profile = PROFILES[p] ? p : "savemem";
  store.set("kv_profile", state.profile);
  for (const b of document.querySelectorAll("#profile button")) { const on = b.dataset.p === state.profile; b.classList.toggle("on", on); b.setAttribute("aria-checked", String(on)); }
  $("#profile-help").textContent = PROFILES[state.profile];
  $("#nodes").hidden = state.profile !== "custom";
  if (state.profile === "custom") loadNodes();
}

async function loadNodes() {
  const box = $("#nodes"), r = await (await fetch("/api/nodes")).json();
  box.textContent = "";
  if (!r.available) { box.append(el("p", "muted", "sinfo shows no nodes here: start the console on the cluster login node.")); return; }
  const free = new Set(r.nodes.map((n) => n.node));
  state.nodes = state.nodes.filter((n) => free.has(n));
  const full = state.nodes.length >= r.max;
  box.append(el("p", "muted agency-help", `${state.nodes.length} of at most ${r.max} nodes ticked. Each node gives at most ${Math.round(r.fraction * 100)}% of its cores and memory.`));
  if (!r.nodes.length) box.append(el("p", "muted", "No node is idle or mixed right now."));
  for (const n of r.nodes) {
    const on = state.nodes.includes(n.node), b = el("button", "member node-opt");
    b.type = "button"; b.setAttribute("aria-pressed", String(on)); b.disabled = full && !on;
    b.append(el("span", "node-tick", on ? "☑" : "☐"), badge(n.state === "idle" ? "done" : "running", n.state === "idle" ? "idle" : "mixed"), el("span", "member-name", `${n.node} · ${n.partitions.join(", ")}`),
      el("span", "node-free", `${n.idle} of ${n.cpus} cores free · ${gb(n.free_mb)} of ${gb(n.mem_mb)} free · at most ${n.half_cpus} cores / ${gb(n.half_mb)}`));
    b.addEventListener("click", () => { state.nodes = on ? state.nodes.filter((x) => x !== n.node) : [...state.nodes, n.node]; store.set("kv_nodes", JSON.stringify(state.nodes)); loadNodes(); });
    box.append(b);
  }
}

async function launch() {
  const analysis = currentAnalysis(), rs = $("#run-state");
  if (!analysis) { rs.textContent = ""; rs.append(badge("failed", "name required")); return; }
  if (state.profile === "custom" && !state.nodes.length) { rs.textContent = ""; rs.append(badge("failed", "tick at least one node")); return; }
  const examples = state.example === "all" ? state.examples.map((e) => e.name) : [];
  const btn = $("#run-sbatch"); btn.disabled = true;
  rs.textContent = ""; rs.append(badge("waiting", "submitting…"));
  let res, body;
  try { res = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ analysis, examples, profile: state.profile, nodes: state.profile === "custom" ? state.nodes : [] }) }); body = await res.json(); }
  finally { btn.disabled = false; }
  if (!res.ok) { rs.textContent = ""; rs.append(badge("failed", "not started"), el("span", null, (body.errors || ["failed"]).join("; "))); return; }
  state.launched = body.started ? { group: body.group, errors: body.errors || {} } : null;
  if (body.started) $("#analysis").value = body.analysis;
  await refreshStatus();
}

const pfmt = (v, d = 0) => (v === null || v === undefined ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
const gb = (mb) => (mb ? `${pfmt(mb / 1024, mb < 10240 ? 1 : 0)} GB` : "—");

function mini(pct, label, good = [60, 100]) {
  const w = el("span", "mini"), b = el("span", "bar"), i = el("i");
  const p = pct === null || pct === undefined ? null : Math.max(0, Math.min(100, pct));
  i.style.width = `${p ?? 0}%`;
  i.className = p === null ? "low" : pct > good[1] ? "bad" : pct >= good[0] ? "ok" : pct >= good[0] / 3 ? "warn" : "low";
  b.append(i); w.append(b, el("em", null, label ?? (p === null ? "—" : `${pfmt(pct)}%`)));
  return w;
}

function grid(head, rows) {
  const wrap = el("div", "tbl"), t = el("table"), th = el("thead"), hr = el("tr"), tb = el("tbody");
  head.forEach((h) => hr.append(el("th", null, h)));
  th.append(hr);
  for (const r of rows) {
    const tr = el("tr");
    for (const c of r) {
      const td = el("td");
      if (c instanceof Node) td.append(c); else if (c && typeof c === "object") { td.textContent = c.text; td.className = c.cls || ""; } else td.textContent = c ?? "—";
      tr.append(td);
    }
    tb.append(tr);
  }
  t.append(th, tb); wrap.append(t);
  return wrap;
}

function togglePerf(on) {
  state.perf = on;
  document.documentElement.dataset.theme = on ? "dark" : "light";
  $("#perf-toggle").setAttribute("aria-pressed", String(on));
  $("nav.seg").hidden = on;
  $("#tab-perf").hidden = !on;
  for (const id of ["samples", "run", "results"]) $(`#tab-${id}`).hidden = on || id !== (state.tab || "samples");
  if (on) refreshPerf();
}

function renderParts(c) {
  const box = $("#perf-parts");
  box.textContent = "";
  if (!c.available) { box.append(el("p", "muted", "sinfo not available here: start the console on the cluster login node.")); return; }
  box.append(grid(["Partition", "Nodes", "States", "CPUs allocated", "Memory allocated", "Jobs run / wait", "Waiting CPUs", "Fit one analysis"],
    c.partitions.map((p) => [p.partition, pfmt(p.nodes), Object.entries(p.states).map(([k, v]) => `${v} ${k}`).join(" · "),
      mini(p.cpus ? (100 * p.alloc) / p.cpus : null, `${pfmt(p.alloc)} / ${pfmt(p.cpus)}`, [0, 85]), mini(p.mem_mb ? (100 * p.alloc_mb) / p.mem_mb : null, `${gb(p.alloc_mb)} / ${gb(p.mem_mb)}`, [0, 85]),
      `${pfmt(p.running)} / ${pfmt(p.pending)}`, pfmt(p.pending_cpus), p.fit ? `${p.fit} node(s)` : { text: "none now", cls: "state-bad" }])));
}

function renderNodes(c, ours) {
  const box = $("#perf-nodes");
  box.textContent = "";
  if (!c.available) { box.append(el("p", "muted", "—")); return; }
  const by = {};
  for (const n of c.nodes) (by[n.partitions[0]] = by[n.partitions[0]] || []).push(n);
  for (const [p, nodes] of Object.entries(by)) {
    const blk = el("div", "part-block"), g = el("div", "nodes");
    blk.append(el("h4", null, `${p} · ${nodes.length} node(s)`));
    for (const n of nodes) {
      const st = n.state.replace(/[*~#!%$@^-]+$/, ""), d = el("div", `node${n.fits_budget ? " fit" : ""}${/down|drain|fail|maint|unk/.test(st) ? " down" : ""}${ours.has(n.node) ? " ours" : ""}`);
      d.title = `${n.node} (${n.partitions.join(", ")}) ${n.state}: ${n.alloc}/${n.cpus} CPUs allocated, ${gb(n.alloc_mb)} / ${gb(n.mem_mb)} memory, load ${pfmt(n.load, 1)}`;
      const cb = el("div", "bar"), ci = el("i"), mb = el("div", "bar"), mi = el("i");
      ci.style.width = `${n.cpus ? (100 * n.alloc) / n.cpus : 0}%`; mi.style.width = `${n.mem_mb ? (100 * n.alloc_mb) / n.mem_mb : 0}%`; mi.className = "run";
      cb.append(ci); mb.append(mi);
      const l1 = el("div", "lab"), l2 = el("div", "lab");
      l1.append(el("span", null, "CPU"), el("span", null, `${n.idle} free / ${n.cpus}`));
      l2.append(el("span", null, "MEM"), el("span", null, `${gb(n.mem_mb - n.alloc_mb)} free`));
      d.append(el("b", null, n.node), el("span", "st", `${st} · load ${pfmt(n.load, 1)}`), cb, l1, mb, l2);
      g.append(d);
    }
    blk.append(g); box.append(blk);
  }
}

function renderRuns(r) {
  const jobs = r.jobs, done = jobs.filter((j) => j.elapsed_min > 0), med = (xs) => { xs = xs.filter((x) => x !== null && x !== undefined).sort((a, b) => a - b); return xs.length ? xs[Math.floor(xs.length / 2)] : null; };
  const k = $("#perf-kpi");
  k.textContent = "";
  for (const [v, l] of [[pfmt(jobs.reduce((a, j) => a + j.core_h, 0), 1), "core-hours used"], [pfmt(jobs.length), "jobs in sacct"],
    [med(done.map((j) => j.cpu_eff)) === null ? "—" : `${pfmt(med(done.map((j) => j.cpu_eff)))}%`, "median CPU efficiency"],
    [med(done.map((j) => j.mem_eff)) === null ? "—" : `${pfmt(med(done.map((j) => j.mem_eff)))}%`, "median memory used / asked"],
    [med(jobs.map((j) => j.wait_min)) === null ? "—" : `${pfmt(med(jobs.map((j) => j.wait_min)), 1)} min`, "median queue wait"],
    [pfmt(jobs.filter((j) => ["OUT_OF_MEMORY", "TIMEOUT"].includes(j.state)).length), "out of memory / time"]]) {
    const c = el("div", "kpi"); c.append(el("b", null, v), el("span", null, l)); k.append(c);
  }
  const bad = (n) => (n ? { text: pfmt(n), cls: "state-bad" } : "0");
  $("#perf-tools").textContent = "";
  $("#perf-tools").append(r.tools.length ? grid(["Tool", "Jobs", "OK", "Failed", "OOM", "Timeout", "CPU eff.", "Mem used / asked", "Peak mem", "Median run", "Median wait", "Core-h"],
    r.tools.map((t) => [t.name, pfmt(t.n), pfmt(t.completed), bad(t.failed), bad(t.oom), bad(t.timeout), mini(t.cpu_eff), mini(t.mem_eff), gb(t.max_used_mb), t.elapsed_min ? `${pfmt(t.elapsed_min, 1)} min` : "—", t.wait_min !== null ? `${pfmt(t.wait_min, 1)} min` : "—", pfmt(t.core_h, 1)])) : el("p", "muted", "No finished jobs in sacct yet."));
  $("#perf-analyses").textContent = "";
  $("#perf-analyses").append(r.analyses.length ? grid(["Analysis", "Jobs", "OK", "Failed", "CPU eff.", "Mem used / asked", "Core-h", "First start", "Last end", "Nodes"],
    r.analyses.map((a) => [a.name, pfmt(a.n), pfmt(a.completed), bad(a.failed + a.oom + a.timeout), mini(a.cpu_eff), mini(a.mem_eff), pfmt(a.core_h, 1), a.first || "—", a.last || "—", a.nodes.join(", ") || "—"])) : el("p", "muted", "—"));
  const sel = $("#perf-filter"), keep = sel.value;
  sel.textContent = ""; sel.append(new Option("All analyses", ""));
  for (const a of r.analyses) sel.append(new Option(a.name, a.name));
  sel.value = keep;
  const shown = jobs.filter((j) => !sel.value || j.analysis === sel.value);
  $("#perf-jobs").textContent = "";
  $("#perf-jobs").append(shown.length ? grid(["Analysis", "Job", "State", "Node", "CPUs", "CPU eff.", "Memory used / asked", "Time used / asked", "Wait", "Core-h"],
    shown.map((j) => [j.analysis, j.key, ["COMPLETED", "RUNNING", "PENDING"].includes(j.state) ? j.state : { text: j.state, cls: "state-bad" }, j.node || "—", pfmt(j.cpus),
      mini(j.cpu_eff), mini(j.mem_eff, `${gb(j.used_mb)} / ${gb(j.req_mb)}`), mini(j.time_eff, `${pfmt(j.elapsed_min)} / ${pfmt(j.req_min)} min`, [5, 100]),
      j.wait_min !== null ? `${pfmt(j.wait_min, 1)} min` : "—", pfmt(j.core_h, 2)])) : el("p", "muted", "—"));
}

async function refreshPerf() {
  $("#perf-at").textContent = "loading…";
  const p = await (await fetch("/api/perf")).json();
  state.perfData = p;
  $("#perf-at").textContent = `updated ${p.at}`;
  $("#perf-budget").textContent = `${p.cluster.budget.cpus} CPUs + ${gb(p.cluster.budget.mem_mb)} free`;
  renderParts(p.cluster);
  renderNodes(p.cluster, new Set(p.runs.jobs.filter((j) => ["RUNNING", "PENDING"].includes(j.state) && j.node).map((j) => j.node)));
  renderRuns(p.runs);
}

const UNCL = "Unclassified";
const GROUPS = ["Full knock-in", "Partial knock-in", "Unedited", "Small indel", "Large / structural", "Other", UNCL];
const GROUP_COLORS = ["#1f5f4f", "#e0a526", "#c7c7cc", "#0071e3", "#c46aa6", "#8e8e93", "#6d6d72"];
const SERIES = ["#1f5f4f", "#e0a526", "#0071e3", "#c46aa6", "#9c3a00", "#8ec9f0", "#4b2a7b"];
const DIMS = { sample: "Sample", tool: "Tool", outcome: "Outcome" };
const VALUES = { reads: "Reads", classified: "% of classified reads", len_pass: "% of length-passing reads", raw: "% of raw reads" };
const PRESETS = {
  "All samples, one plot": { panel: "none", row: "sample", color: "outcome", bars: "stacked" },
  "One plot per sample": { panel: "sample", row: "tool", color: "outcome", bars: "stacked" },
  "One plot per outcome": { panel: "outcome", row: "sample", color: "tool", bars: "grouped" },
  "Compare samples": { panel: "tool", row: "outcome", color: "sample", bars: "grouped" },
};
const SVG_FONT = "-apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif";
const fmt = (n) => Number(n).toLocaleString("en-US");
const pctTxt = (p) => (p === 0 ? "0%" : p < 0.01 ? "<0.01%" : `${p < 1 ? p.toFixed(2) : p.toFixed(1)}%`);
const CH = { r: null, o: { samples: null, tools: null, outcomes: null, detail: "groups", value: "classified", panel: "tool", row: "sample", color: "outcome", bars: "stacked", labels: "value", sort: "sheet", shared: true, funnel: false, unclassified: false } };
try { Object.assign(CH.o, JSON.parse(store.get("kv_chart") || "{}")); } catch {}

function chartData(r, detail, withUnc) {
  const used = {}, unc = {}, val = {}, cat = {}, outs = [];
  for (const x of r.rows) {
    used[`${x.tool}|${x.sample_id}`] = Number(x.reads_used) || 0;
    unc[`${x.tool}|${x.sample_id}`] = Number(x.unclassified_reads) || 0;
  }
  const samples = [...new Set([...(r.matrix ? r.matrix[0].slice(1) : []), ...r.rows.map((x) => x.sample_id)])];
  const tools = [...new Set(r.rows.map((x) => x.tool))];
  for (const x of r.classes || []) {
    if (!withUnc && x.category === UNCL) continue;
    const o = detail === "groups" ? x.category : x.class;
    if (!outs.includes(o)) outs.push(o);
    cat[o] = x.category;
    const k = `${x.tool}|${x.sample_id}|${o}`; val[k] = (val[k] || 0) + Number(x.reads);
  }
  const groups = GROUPS.filter((g) => withUnc || g !== UNCL);
  const order = detail === "groups" ? groups : outs.sort((a, b) => GROUPS.indexOf(cat[a]) - GROUPS.indexOf(cat[b]));
  const reads = (s) => r.reads[s] || ((r.meta[s] || {}).steps || {})["01_fetch"] || {};
  const denom = (t, s, mode) => (mode === "classified" ? used[`${t}|${s}`] + (withUnc ? unc[`${t}|${s}`] || 0 : 0) : Number(reads(s)[mode === "raw" ? "raw_reads" : "len_pass"]) || 0);
  return { samples, tools, outcomes: order, groups, cat, reads, used, get: (t, s, o) => val[`${t}|${s}|${o}`] || 0, denom };
}

function saveChart() { store.set("kv_chart", JSON.stringify(CH.o)); }

function chip(label, on, onChange, color) {
  const l = el("label", "chip"), c = el("input");
  c.type = "checkbox"; c.checked = on; c.addEventListener("change", () => onChange(c.checked));
  l.append(c);
  if (color) { const sw = el("i", "sw"); sw.style.background = color; l.append(sw); }
  l.append(document.createTextNode(label));
  return l;
}

function seg(options, value, onPick) {
  const s = el("div", "seg small");
  for (const [k, label] of Object.entries(options)) {
    const b = el("button", k === value ? "on" : null, label); b.type = "button";
    b.addEventListener("click", () => onPick(k)); s.append(b);
  }
  return s;
}

function pick(options, value, onPick) {
  const s = el("select", "inline");
  for (const [k, label] of Object.entries(options)) s.append(new Option(label, k));
  s.value = value; s.addEventListener("change", () => onPick(s.value));
  return s;
}

function ctlRow(label, ...kids) {
  const r = el("div", "ctl-row"); r.append(el("span", "ctl-lab", label));
  const b = el("div", "ctl-body"); b.append(...kids); r.append(b);
  return r;
}

function setDim(slot, dim) {
  const o = CH.o, slots = ["panel", "row", "color"], prev = o[slot];
  const other = slots.find((s) => s !== slot && o[s] === dim);
  o[slot] = dim;
  if (other) o[other] = prev === "none" && other !== "panel" ? Object.keys(DIMS).find((d) => !slots.some((s) => o[s] === d)) : prev;
  if (o.color !== "outcome") o.bars = "grouped";
}

function seriesColors(full, o, keys) {
  if (o.color === "outcome" && o.detail === "groups") return keys.map((k) => ({ fill: GROUP_COLORS[GROUPS.indexOf(k)], hatch: k === "Other" || k === UNCL }));
  return keys.map((k) => { const i = Math.max(0, full.indexOf(k)); return { fill: SERIES[i % SERIES.length], hatch: i >= SERIES.length }; });
}

function renderControls() {
  const box = $("#chart-ctl"), o = CH.o, r = CH.r;
  box.textContent = "";
  if (!r || !r.classes) { box.hidden = true; return; }
  box.hidden = false;
  const d = chartData(r, o.detail, o.unclassified);
  const sel = (k, all) => { if (!o[k]) o[k] = [...all]; o[k] = o[k].filter((x) => all.includes(x)); if (!o[k].length) o[k] = [...all]; return o[k]; };
  const ss = sel("samples", d.samples), ts = sel("tools", d.tools), os = sel(`outcomes_${o.detail}`, d.outcomes);
  const redraw = () => { saveChart(); renderControls(); renderChart(); };
  const toggle = (k, x, on, all) => { const cur = new Set(o[k]); on ? cur.add(x) : cur.delete(x); o[k] = all.filter((y) => cur.has(y)); redraw(); };
  const allNone = (k, all) => {
    const w = el("span", "ctl-links"), a = el("button", "link", "all"), n = el("button", "link", "none");
    a.type = n.type = "button";
    a.addEventListener("click", () => { o[k] = [...all]; redraw(); });
    n.addEventListener("click", () => { o[k] = all.slice(0, 1); redraw(); });
    w.append(a, n); return w;
  };
  const presets = el("div", "ctl-presets");
  for (const [name, p] of Object.entries(PRESETS)) {
    const b = el("button", "pill plain small", name); b.type = "button";
    b.addEventListener("click", () => { Object.assign(o, p); redraw(); });
    presets.append(b);
  }
  const full = { sample: d.samples, tool: d.tools, outcome: d.outcomes }, sw = (dim, list) => (o.color === dim ? seriesColors(full[dim], o, list).map((c) => c.fill) : []);
  const sCol = sw("sample", d.samples), tCol = sw("tool", d.tools), outColors = sw("outcome", d.outcomes);
  box.append(
    ctlRow("Quick layouts", presets),
    ctlRow("Samples", ...d.samples.map((s, i) => chip(s, ss.includes(s), (on) => toggle("samples", s, on, d.samples), sCol[i])), allNone("samples", d.samples)),
    ctlRow("Tools", ...d.tools.map((t, i) => chip(t, ts.includes(t), (on) => toggle("tools", t, on, d.tools), tCol[i]))),
    ctlRow("Outcomes", seg({ groups: `${d.groups.length} groups`, classes: "Tool classes" }, o.detail, (v) => { o.detail = v; redraw(); }),
      ...d.outcomes.map((x, i) => chip(x, os.includes(x), (on) => toggle(`outcomes_${o.detail}`, x, on, d.outcomes), outColors[i])), allNone(`outcomes_${o.detail}`, d.outcomes)),
    ctlRow("Values", pick(VALUES, o.value, (v) => { o.value = v; redraw(); }),
      el("span", "ctl-lab inline", "Labels"), seg(o.value === "reads" ? { value: "Count", none: "None" } : { value: "Value", both: "Count + %", none: "None" }, o.labels === "both" && o.value === "reads" ? "value" : o.labels, (v) => { o.labels = v; redraw(); })),
    ctlRow("Layout",
      el("span", "ctl-lab inline", "Panels"), pick({ none: "None (one plot)", ...DIMS }, o.panel, (v) => { setDim("panel", v); redraw(); }),
      el("span", "ctl-lab inline", "Rows"), pick(DIMS, o.row, (v) => { setDim("row", v); redraw(); }),
      el("span", "ctl-lab inline", "Colour"), pick(DIMS, o.color, (v) => { setDim("color", v); redraw(); })),
    ctlRow("Bars",
      seg(o.color === "outcome" ? { stacked: "Stacked", grouped: "Side by side" } : { grouped: "Side by side" }, o.bars, (v) => { o.bars = v; redraw(); }),
      el("span", "ctl-lab inline", "Sort"), seg({ sheet: "Sheet order", value: "Largest first" }, o.sort, (v) => { o.sort = v; redraw(); }),
      chip("Same scale in all panels", o.shared, (on) => { o.shared = on; redraw(); }),
      chip("Read filtering panel", o.funnel, (on) => { o.funnel = on; redraw(); }),
      chip("Include unclassified reads", o.unclassified, (on) => { o.unclassified = on; redraw(); })),
  );
}

function chartModel() {
  const o = CH.o, r = CH.r, d = chartData(r, o.detail, o.unclassified);
  const S = o.samples, T = o.tools, O = o[`outcomes_${o.detail}`] || d.outcomes;
  const lists = { sample: S, tool: T, outcome: O }, left = Object.keys(DIMS).find((k) => k !== o.row && k !== o.color && k !== o.panel);
  const cells = [];
  for (const t of T) for (const s of S) for (const x of O) {
    const v = { sample: s, tool: t, outcome: x }, reads = d.get(t, s, x), den = o.value === "reads" ? null : d.denom(t, s, o.value);
    const cls = d.denom(t, s, "classified");
    cells.push({ panel: o.panel === "none" ? "" : v[o.panel], row: left ? `${v[o.row]} · ${v[left]}` : v[o.row], series: v[o.color], reads,
      value: o.value === "reads" ? reads : den ? (100 * reads) / den : 0, pctCls: cls ? (100 * reads) / cls : 0, t, s, x });
  }
  const rowKeys = left ? lists[o.row].flatMap((a) => lists[left].map((b) => `${a} · ${b}`)) : [...lists[o.row]];
  const panels = (o.panel === "none" ? [""] : lists[o.panel]).map((p) => {
    let rows = rowKeys.map((k) => ({ key: k, cells: lists[o.color].map((c) => cells.find((x) => x.panel === p && x.row === k && x.series === c)).filter(Boolean) }));
    rows = rows.filter((x) => x.cells.length);
    if (o.sort === "value") rows.sort((a, b) => b.cells.reduce((s, c) => s + c.value, 0) - a.cells.reduce((s, c) => s + c.value, 0));
    return { title: p, rows };
  });
  if (o.funnel) {
    const keys = ["Raw reads", "Length-passing", ...T.map((t) => `${t} classified`)];
    const rows = S.map((s) => {
      const raw = Number(d.reads(s).raw_reads) || 0, n = [raw, Number(d.reads(s).len_pass) || 0, ...T.map((t) => d.denom(t, s, "classified"))];
      return { key: s, cells: n.map((k, i) => ({ series: keys[i], reads: k, value: o.value === "reads" ? k : raw ? (100 * k) / raw : 0, pctCls: raw ? (100 * k) / raw : 0 })) };
    });
    panels.push({ title: o.value === "reads" ? "Read filtering" : "Read filtering (% of raw reads)", rows, funnel: keys });
  }
  return { panels, series: lists[o.color], full: { sample: d.samples, tool: d.tools, outcome: d.outcomes }[o.color], d };
}

let measureCtx;
function textW(s, size = 13) {
  measureCtx = measureCtx || document.createElement("canvas").getContext("2d");
  measureCtx.font = `${size}px ${SVG_FONT}`;
  return measureCtx.measureText(s).width;
}

function niceMax(v) {
  v = +v.toFixed(6);
  if (v <= 0) return 1;
  const e = 10 ** Math.floor(Math.log10(v)), f = v / e, n = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return n * e;
}

function renderChart() {
  const box = $("#chart"), o = CH.o;
  box.textContent = "";
  if (!CH.r || !CH.r.classes) {
    box.append(el("p", "muted", CH.r && CH.r.matrix ? "No summary_classes.tsv for this analysis yet: run it again from the Run tab (only 05_summary is resubmitted)." : "—"));
    return;
  }
  const { panels, series, full } = chartModel(), stacked = o.bars === "stacked" && o.color === "outcome";
  const NS = "http://www.w3.org/2000/svg", W = 960, PAD = 16, BAR = stacked ? 20 : 13, ROWGAP = stacked ? 10 : 12;
  const unit = o.value === "reads" ? "" : "%", lab = (c) => (o.labels === "none" ? "" : !unit ? fmt(c.reads) : o.labels === "both" ? `${fmt(c.reads)} · ${pctTxt(c.value)}` : pctTxt(c.value));
  const allRows = panels.flatMap((p) => p.rows);
  const LABW = Math.min(260, Math.max(80, ...allRows.map((r) => textW(r.key))) + 12);
  const total = (r) => ({ reads: r.cells.reduce((s, c) => s + c.reads, 0), value: r.cells.reduce((s, c) => s + c.value, 0), pctCls: r.cells.reduce((s, c) => s + c.pctCls, 0) });
  const VALW = o.labels === "none" ? 16 : Math.max(60, ...allRows.flatMap((r) => (stacked ? [total(r)] : r.cells)).map((c) => textW(lab(c), 12))) + 14;
  const X0 = PAD + LABW, XW = W - X0 - VALW - PAD;
  const rowMax = (p) => Math.max(0, ...p.rows.map((r) => (stacked && !p.funnel ? r.cells.reduce((s, c) => s + c.value, 0) : Math.max(0, ...r.cells.map((c) => c.value)))));
  const globalMax = niceMax(Math.max(...panels.filter((p) => !p.funnel).map(rowMax), 0));
  const svg = document.createElementNS(NS, "svg"), mk = (tag, attrs, parent = svg) => { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); parent.append(n); return n; };
  const txt = (s, attrs, parent) => { const t = mk("text", { "font-family": SVG_FONT, ...attrs }, parent); t.textContent = s; return t; };
  const defs = mk("defs", {});
  const colorOf = (keys) => seriesColors(full, o, keys).map((c, i) => {
    if (!c.hatch) return c.fill;
    const id = `hatch-${i}`, pat = mk("pattern", { id, width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, defs);
    mk("rect", { width: 6, height: 6, fill: c.fill }, pat); mk("line", { x1: 0, y1: 0, x2: 0, y2: 6, stroke: "#ffffff", "stroke-width": 2.5 }, pat);
    return `url(#${id})`;
  });
  let y = PAD;
  const legend = (keys, fills) => {
    let x = PAD;
    for (let i = 0; i < keys.length; i++) {
      const w = 22 + textW(keys[i], 13) + 18;
      if (x + w > W - PAD) { x = PAD; y += 22; }
      mk("rect", { x, y: y + 2, width: 14, height: 14, rx: 3, fill: fills[i] });
      txt(keys[i], { x: x + 20, y: y + 14, "font-size": 13, fill: "#1d1d1f" });
      x += w;
    }
    y += 30;
  };
  const mainFills = colorOf(series);
  legend(series, mainFills);
  for (const p of panels) {
    const fills = p.funnel ? p.funnel.map((_, i) => ["#6e6e73", "#a1a1a6", ...SERIES][i]) : mainFills, keys = p.funnel || series;
    if (p.funnel) { y += 8; legend(keys, fills); }
    const pStacked = stacked && !p.funnel, max = p.funnel ? niceMax(rowMax(p)) : o.shared ? globalMax : niceMax(rowMax(p));
    if (p.title) { txt(p.title, { x: PAD, y: y + 15, "font-size": 15, "font-weight": 600, fill: "#1d1d1f" }); y += 26; }
    const top = y, sx = (v) => (XW * Math.max(0, v)) / max;
    const rowH = (r) => (pStacked ? BAR : r.cells.length * (BAR + 2) - 2) + ROWGAP;
    const h = p.rows.reduce((s, r) => s + rowH(r), 0) + 4;
    for (let k = 0; k <= 4; k++) {
      const gx = X0 + (XW * k) / 4, v = (max * k) / 4;
      mk("line", { x1: gx, x2: gx, y1: top, y2: top + h, stroke: k ? "#ececf0" : "#8e8e93", "stroke-width": 1 });
      txt(unit ? `${+v.toFixed(2)}%` : fmt(+v.toFixed(0)), { x: gx, y: top + h + 15, "font-size": 11.5, fill: "#4f4f54", "text-anchor": k ? (k === 4 ? "end" : "middle") : "start" });
    }
    y = top + ROWGAP / 2;
    for (const r of p.rows) {
      const hh = rowH(r) - ROWGAP;
      txt(r.key, { x: X0 - 10, y: y + hh / 2 + 4.5, "font-size": 13, fill: "#1d1d1f", "text-anchor": "end" });
      if (pStacked) {
        let x = X0;
        r.cells.forEach((c) => {
          const w = sx(c.value), i = keys.indexOf(c.series);
          if (c.reads > 0) {
            const g = mk("g", {}), rect = mk("rect", { x, y, width: Math.max(w - 1, 1.5), height: BAR, fill: fills[i] }, g);
            const t = mk("title", {}, rect); t.textContent = `${r.key} · ${c.series}\n${fmt(c.reads)} reads${unit ? ` · ${pctTxt(c.pctCls)} of classified` : ""}`;
            if (o.labels !== "none" && !fills[i].startsWith("url") && w > textW(lab(c), 11) + 8) txt(lab(c), { x: x + w / 2, y: y + BAR / 2 + 4, "font-size": 11, "text-anchor": "middle", fill: ["#e0a526", "#c7c7cc", "#8ec9f0"].includes(c.fill || fills[i]) ? "#1d1d1f" : "#ffffff", "pointer-events": "none" }, g);
          }
          x += w;
        });
        if (o.labels !== "none") txt(lab(total(r)), { x: x + 6, y: y + BAR / 2 + 4.5, "font-size": 12, fill: "#4f4f54" });
      } else {
        r.cells.forEach((c, j) => {
          const yy = y + j * (BAR + 2), w = sx(c.value), i = keys.indexOf(c.series);
          const rect = mk("rect", { x: X0, y: yy, width: c.reads > 0 ? Math.max(w, 1.5) : 0, height: BAR, rx: 2, fill: fills[i] });
          const t = mk("title", {}, rect); t.textContent = `${r.key} · ${c.series}\n${fmt(c.reads)} reads${unit ? ` · ${pctTxt(c.pctCls)} of ${p.funnel ? "raw" : "classified"}` : ""}`;
          if (o.labels !== "none") txt(lab(c), { x: X0 + w + 6, y: yy + BAR / 2 + 4, "font-size": 11.5, fill: "#4f4f54" });
        });
      }
      y += rowH(r);
    }
    y = top + h + 36;
    if (!p.funnel) txt(o.value === "reads" ? "Reads" : VALUES[o.value], { x: X0 + XW / 2, y: y, "font-size": 12, fill: "#4f4f54", "text-anchor": "middle" });
    y += 26;
  }
  svg.setAttribute("viewBox", `0 0 ${W} ${y}`); svg.setAttribute("width", W); svg.setAttribute("height", y);
  svg.setAttribute("xmlns", NS); svg.setAttribute("class", "chart-svg"); svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `Read outcomes: ${VALUES[o.value]}`);
  mk("rect", { x: 0, y: 0, width: W, height: y, fill: "#ffffff" }).parentNode.prepend(svg.lastChild);
  const bar = el("div", "toolbar chart-dl");
  for (const [k, f] of Object.entries({ SVG: downloadSvg, PNG: downloadPng, TSV: downloadTsv })) {
    const b = el("button", "pill plain small", `Download ${k}`); b.type = "button"; b.addEventListener("click", () => f(svg)); bar.append(b);
  }
  box.append(bar, svg);
}

function chartName(ext) { return `${$("#pick-results").value || currentAnalysis() || "knockin-val"}_read_outcomes.${ext}`; }
function saveBlob(blob, name) { const a = el("a"); a.href = URL.createObjectURL(blob); a.download = name; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000); }
function downloadSvg(svg) { saveBlob(new Blob([new XMLSerializer().serializeToString(svg)], { type: "image/svg+xml" }), chartName("svg")); }
function downloadPng(svg) {
  const img = new Image(), w = +svg.getAttribute("width"), h = +svg.getAttribute("height");
  img.onload = () => { const c = document.createElement("canvas"); c.width = w * 3; c.height = h * 3; const x = c.getContext("2d"); x.scale(3, 3); x.drawImage(img, 0, 0); c.toBlob((b) => saveBlob(b, chartName("png"))); };
  img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(new XMLSerializer().serializeToString(svg))}`;
}
function downloadTsv() {
  const { panels } = chartModel(), out = [["panel", "row", "series", "reads", CH.o.value === "reads" ? "reads" : VALUES[CH.o.value]]];
  for (const p of panels) for (const r of p.rows) for (const c of r.cells) out.push([p.title, r.key, c.series, c.reads, CH.o.value === "reads" ? c.reads : c.value.toFixed(4)]);
  saveBlob(new Blob([out.map((r) => r.join("\t")).join("\n") + "\n"], { type: "text/tab-separated-values" }), chartName("tsv"));
}

async function refreshResults() {
  const name = $("#pick-results").value || currentAnalysis();
  const getResults = async (n) => (await fetch(`/api/results?analysis=${encodeURIComponent(n)}`)).json();
  const r = await getResults(name);
  const pr = $("#pick-results");
  if (name && [...pr.options].some((o) => o.value === name)) pr.value = name;
  const m = $("#matrix"), grp = r.group || [];
  m.textContent = "";
  const matrix = (mx) => {
    const t = table(mx[0], mx.slice(1));
    t.querySelectorAll("tbody td:not(:first-child)").forEach((td) => td.classList.add("num"));
    return t;
  };
  if (grp.length > 1) {
    const chips = el("div", "group-pick");
    chips.append(el("span", "ctl-lab inline", `Group ${grp[0].group}, charts and samples for:`));
    for (const g of grp) {
      const b = el("button", "chip", `${g.done ? "✓" : "○"} ${g.name} · ${g.done ? "report ready" : "no report yet"}`);
      b.type = "button"; b.setAttribute("aria-pressed", String(g.name === name));
      b.addEventListener("click", () => { pr.value = g.name; refreshResults(); });
      chips.append(b);
    }
    m.append(chips);
    const all = await Promise.all(grp.map((g) => (g.name === name ? r : getResults(g.name))));
    grp.forEach((g, i) => {
      m.append(el("h4", "member-head", g.name));
      m.append(all[i].matrix ? matrix(all[i].matrix) : el("p", "muted", `No report yet: open ${g.name} in the Run tab to see its steps.`));
    });
  } else if (!name || !r.matrix) m.append(el("p", "muted", "—"));
  else m.append(matrix(r.matrix));
  CH.r = r; renderControls(); renderChart();
  const box = $("#meta");
  box.textContent = "";
  const ids = Object.keys(r.meta);
  if (r.analysis_meta) { const d = el("details"); d.append(el("summary", null, "Analysis-level jobs (downloads, references, summary): performance"), el("pre", null, JSON.stringify(r.analysis_meta, null, 2))); box.append(d); }
  if (!ids.length) { if (!r.analysis_meta) box.append(el("p", "muted", "—")); return; }
  for (const id of ids) {
    const d = el("details"), su = el("summary", null, id);
    const rows = r.rows.filter((x) => x.sample_id === id).map((x) => `${x.tool}: ${x.ki_pct}% (${x.ki_reads}/${x.reads_used})`).join("  ·  ");
    if (rows) su.textContent = `${id} — ${rows}`;
    d.append(su, el("pre", null, JSON.stringify(r.meta[id], null, 2)));
    box.append(d);
  }
}

for (const b of document.querySelectorAll("nav button")) b.addEventListener("click", () => tab(b.dataset.tab));
$("#perf-toggle").addEventListener("click", () => togglePerf(!state.perf));
$("#perf-refresh").addEventListener("click", refreshPerf);
$("#perf-filter").addEventListener("change", () => state.perfData && renderRuns(state.perfData.runs));
setInterval(() => { if (state.perf && $("#perf-auto").checked) refreshPerf(); }, 30000);
$("#toggle-info").addEventListener("click", () => toggleInfo($("#info").hidden));
$("#clear").addEventListener("click", clearSamples);
$("#add").addEventListener("click", () => add());
$("#reload").addEventListener("click", loadSaved);
$("#submit").addEventListener("click", submit);
$("#run-sbatch").addEventListener("click", launch);
for (const b of document.querySelectorAll("#profile button")) b.addEventListener("click", () => setProfile(b.dataset.p));
try { state.nodes = JSON.parse(store.get("kv_nodes") || "[]"); } catch { state.nodes = []; }
setProfile(store.get("kv_profile") || "savemem");
$("#analysis").addEventListener("input", renderRunNote);
function stopReport(rs, results) {
  for (const [n, r] of Object.entries(results)) {
    rs.append(el("span", "muted", `${n}: ${r.cancelled.length} cancelled`));
    if (r.remaining.length) rs.append(badge("failed", `${n} still live`), el("span", null, `scancel ${r.remaining.join(" ")}`));
  }
}
$("#stop").addEventListener("click", async () => {
  const b = $("#stop"); b.disabled = true;
  const r = await (await fetch("/api/stop", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ analysis: currentAnalysis() }) })).json();
  await refreshStatus();
  stopReport($("#run-state"), { [currentAnalysis()]: r });
});
$("#stop-all").addEventListener("click", async () => {
  if (!confirm("Cancel every live SLURM job of every analysis?")) return;
  const b = $("#stop-all"); b.disabled = true;
  const r = await (await fetch("/api/stop_all", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })).json();
  b.disabled = false;
  await refreshStatus();
  const rs = $("#run-state");
  if (!Object.keys(r.analyses).length) rs.append(el("span", "muted", "no live jobs found"));
  stopReport(rs, r.analyses);
});
$("#pick").addEventListener("change", () => { if ($("#pick").value) { $("#analysis").value = $("#pick").value; renderRunNote(); refreshStatus(); } });
$("#pick-results").addEventListener("change", refreshResults);
$("#refresh-results").addEventListener("click", refreshResults);
setInterval(() => { if ($("#auto").checked && !$("#tab-run").hidden) refreshStatus(); }, 5000);
init();
refreshStatus();
