const $ = (s, r = document) => r.querySelector(s);
const state = { schema: null, params: {}, rows: [], example: false, stash: [] };

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
  renderInfo();
  toggleInfo(store.get("kv_info") !== "0");
  fill([]);
}

async function loadSaved() {
  const { samples } = await (await fetch("/api/samples")).json();
  fill(samples);
  state.stash = [];
  setExample(false);
  status(samples.length ? `${samples.length} saved sample(s) loaded from configs/samples.tsv` : "No saved samples.", false);
}

function setExample(on) {
  state.example = on;
  $("#example span").textContent = on ? "Hide example data" : "Show example data";
}

function toggleExample() {
  if (state.example) {
    fill(state.stash);
    state.stash = [];
    setExample(false);
    status("Example data hidden. Your previous entries were restored.", false);
    return;
  }
  state.stash = state.rows.map(read).filter((r) => Object.values(r).some((v) => v && v !== "0"));
  fill((state.schema.example || []).map((x) => ({ ...x })));
  setExample(true);
  status("Example data loaded: 5 public ONT runs (BioProject PRJNA1257358). Click again to hide them. Save to use them.", false);
}

async function submit() {
  const samples = state.rows.map(read);
  const res = await fetch("/api/samples", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ samples }) });
  const body = await res.json();
  if (!res.ok) return status("Not saved:\n  " + (body.errors || [body.error]).join("\n  "), true);
  status([`Saved ${body.n} sample(s).`, `  ${body.samples_tsv}`, ...body.sample_json.map((p) => `  ${p}`)].join("\n"), false);
}

function tab(name) {
  for (const b of document.querySelectorAll("nav button")) b.classList.toggle("on", b.dataset.tab === name);
  for (const id of ["samples", "run", "results"]) $(`#tab-${id}`).hidden = id !== name;
  if (name === "run") refreshStatus();
  if (name === "results") refreshResults();
}

function describeRuntime(rt) {
  const ok = (x) => (x ? "✓" : "✗");
  return `${rt.sif ? rt.sif.split("/").pop() : "image pulled on first run"} · snakemake ${ok(rt.snakemake)} · singularity ${ok(rt.apptainer)} · sbatch ${ok(rt.sbatch)} · get_best_node ${rt.node_pick ? "on" : "off"}`;
}

const currentAnalysis = () => $("#analysis").value.trim();
const badge = (s, text) => el("span", `badge ${s}`, text || s);

function fillPickers(list, running) {
  for (const sel of [$("#pick"), $("#pick-results")]) {
    const keep = sel.value;
    sel.textContent = "";
    sel.append(new Option(sel.id === "pick" ? "—" : "Analysis", ""));
    for (const a of list) sel.append(new Option(`${a.name}${a.done ? " ✓" : ""}${a.name === running ? " (running)" : ""}`, a.name));
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
    const st = s.failed ? "failed" : s.total && s.done === s.total ? "done" : s.running ? "running" : s.done ? "stopped" : "waiting";
    const pct = (n) => (s.total ? (100 * n) / s.total : 0);
    su.append(el("span", "step-name", s.step), badge(st, st === "stopped" ? "partial" : st),
      bar([["ok", pct(s.done)], ["bad", pct(s.failed)], ["run", pct(s.running)]], `${s.done}/${s.total}${s.failed ? ` · ${s.failed} failed` : ""}`));
    su.lastChild.style.flex = "1"; su.lastChild.style.marginTop = "0";
    const jobs = el("div", "jobs");
    for (const j of s.jobs) {
      const r = el("div", "job");
      r.append(badge(j.state), el("span", null, j.job), el("code", null, j.log), el("span", "when", j.updated || ""));
      if (j.tail) r.append(el("pre", null, j.tail));
      jobs.append(r);
    }
    d.append(su, jobs);
    if (s.failed) { d.open = true; d.classList.add("has-failed"); }
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
  $("#runtime").textContent = describeRuntime(s.runtime);
  const st = s.state || {}, rs = $("#run-state");
  rs.textContent = "";
  rs.append(badge(s.outcome));
  if (st.started_at) rs.append(el("strong", null, st.analysis), el("span", "muted", `started ${st.started_at} · ${(st.samples || []).length} samples · results/${st.analysis}/`));
  else if (name) rs.append(el("strong", null, name));
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

async function launch() {
  const analysis = currentAnalysis(), rs = $("#run-state");
  if (!analysis) { rs.textContent = ""; rs.append(badge("failed", "name required")); return; }
  const res = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ analysis }) });
  const body = await res.json();
  if (!res.ok) { rs.textContent = ""; rs.append(badge("failed", "not started"), el("span", null, (body.errors || ["failed"]).join("; "))); return; }
  refreshStatus();
}

async function refreshResults() {
  const name = $("#pick-results").value || currentAnalysis();
  const r = await (await fetch(`/api/results?analysis=${encodeURIComponent(name)}`)).json();
  const m = $("#matrix");
  m.textContent = "";
  if (!name || !r.matrix) m.append(el("p", "muted", "—"));
  else {
    const t = table(r.matrix[0], r.matrix.slice(1));
    t.querySelectorAll("tbody td:not(:first-child)").forEach((td) => td.classList.add("num"));
    m.append(t);
  }
  const box = $("#meta");
  box.textContent = "";
  const ids = Object.keys(r.meta);
  if (!ids.length) { box.append(el("p", "muted", "—")); return; }
  for (const id of ids) {
    const d = el("details"), su = el("summary", null, id);
    const rows = r.rows.filter((x) => x.sample_id === id).map((x) => `${x.tool}: ${x.ki_pct}% (${x.ki_reads}/${x.reads_used})`).join("  ·  ");
    if (rows) su.textContent = `${id} — ${rows}`;
    d.append(su, el("pre", null, JSON.stringify(r.meta[id], null, 2)));
    box.append(d);
  }
}

for (const b of document.querySelectorAll("nav button")) b.addEventListener("click", () => tab(b.dataset.tab));
$("#toggle-info").addEventListener("click", () => toggleInfo($("#info").hidden));
$("#example").addEventListener("click", toggleExample);
$("#add").addEventListener("click", () => add());
$("#reload").addEventListener("click", loadSaved);
$("#submit").addEventListener("click", submit);
$("#run-sbatch").addEventListener("click", launch);
$("#stop").addEventListener("click", async () => {
  await fetch("/api/stop", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ analysis: currentAnalysis() }) });
  refreshStatus();
});
$("#pick").addEventListener("change", () => { if ($("#pick").value) { $("#analysis").value = $("#pick").value; refreshStatus(); } });
$("#pick-results").addEventListener("change", refreshResults);
$("#refresh-results").addEventListener("click", refreshResults);
setInterval(() => { if ($("#auto").checked && !$("#tab-run").hidden) refreshStatus(); }, 5000);
init();
refreshStatus();
