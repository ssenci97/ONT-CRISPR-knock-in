const $ = (s, r = document) => r.querySelector(s);
const state = { schema: null, rows: [] };

function field(f, value) {
  const wrap = document.createElement("div");
  wrap.className = "field" + (f.type === "textarea" ? " wide" : "");
  const id = `${f.id}_${Math.random().toString(36).slice(2, 8)}`;
  const label = document.createElement("label");
  label.htmlFor = id;
  label.textContent = f.label;
  if (f.required) label.insertAdjacentHTML("beforeend", ' <span class="req">*</span>');
  let el;
  if (f.type === "select") {
    el = document.createElement("select");
    for (const o of f.options) el.add(new Option(o, o));
    el.value = value ?? f.default ?? f.options[0];
  } else if (f.type === "textarea") {
    el = document.createElement("textarea");
    el.value = value ?? "";
  } else {
    el = document.createElement("input");
    el.type = f.type;
    if (f.step) el.step = f.step;
    if (f.type === "checkbox") el.checked = ["1", "true", true, 1].includes(value);
    else el.value = value ?? f.default ?? "";
  }
  el.id = id;
  el.dataset.field = f.id;
  wrap.append(label, el);
  if (f.help) {
    const h = document.createElement("div");
    h.className = "hint";
    h.textContent = f.help;
    wrap.append(h);
  }
  return wrap;
}

function card(values = {}) {
  const node = $("#card").content.firstElementChild.cloneNode(true);
  const groups = $(".groups", node);
  for (const g of state.schema.groups) {
    const sec = document.createElement("div");
    sec.className = "group";
    const h = document.createElement("h3");
    h.textContent = g.name;
    sec.append(h);
    if (g.help) {
      const p = document.createElement("p");
      p.className = "help";
      p.textContent = g.help;
      sec.append(p);
    }
    const fields = document.createElement("div");
    fields.className = "fields";
    for (const f of g.fields) fields.append(field(f, values[f.id]));
    sec.append(fields);
    groups.append(sec);
  }
  const title = $(".title", node);
  const sid = $('[data-field="sample_id"]', node);
  const retitle = () => (title.textContent = sid.value.trim() || "New sample");
  sid.addEventListener("input", retitle);
  retitle();
  $('[data-act="del"]', node).addEventListener("click", () => {
    node.remove();
    state.rows = state.rows.filter((n) => n !== node);
  });
  $('[data-act="dup"]', node).addEventListener("click", () => {
    const v = read(node);
    v.sample_id = "";
    add(v);
  });
  return node;
}

function read(node) {
  const out = {};
  for (const el of node.querySelectorAll("[data-field]"))
    out[el.dataset.field] = el.type === "checkbox" ? (el.checked ? "1" : "0") : el.value.trim();
  return out;
}

function add(values) {
  const node = card(values);
  state.rows.push(node);
  $("#samples").append(node);
  return node;
}

function status(text, isError) {
  const el = $("#status");
  el.hidden = false;
  el.textContent = text;
  el.classList.toggle("err", !!isError);
}

async function load() {
  state.schema = await (await fetch("/api/schema")).json();
  document.title = state.schema.title;
  $("h1").textContent = state.schema.title;
  const { samples } = await (await fetch("/api/samples")).json();
  $("#samples").textContent = "";
  state.rows = [];
  if (samples.length) samples.forEach(add);
  else add();
  status(`${samples.length} sample(s) loaded from configs/samples.tsv`, false);
}

async function submit() {
  const samples = state.rows.map(read);
  const res = await fetch("/api/samples", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ samples }),
  });
  const body = await res.json();
  if (!res.ok) return status("Not saved:\n  " + (body.errors || [body.error]).join("\n  "), true);
  status(
    [
      `Saved ${body.n} sample(s).`,
      `  ${body.samples_tsv}`,
      ...body.sample_json.map((p) => `  ${p}`),
      body.arrays.length ? `  SLURM array set to 1-${body.n} in: ${body.arrays.join(", ")}` : "",
      "",
      "Next: bash slurms/run_all.sh --sbatch",
    ]
      .filter(Boolean)
      .join("\n"),
    false
  );
}


function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

function tab(name) {
  for (const b of document.querySelectorAll("nav button")) b.classList.toggle("on", b.dataset.tab === name);
  for (const id of ["samples", "run", "results"]) $(`#tab-${id}`).hidden = id !== name;
  if (name === "run") refreshStatus();
  if (name === "results") refreshResults();
}

function describeRuntime(rt) {
  const where = rt.engine === "apptainer" ? `apptainer · ${rt.sif}`
    : rt.engine === "podman" ? `podman · ${rt.image}`
    : "native (no container)";
  return `${where} · sbatch ${rt.sbatch ? "available" : "not found"}`;
}

async function refreshStatus() {
  const s = await (await fetch("/api/status")).json();
  $("#runtime").textContent = describeRuntime(s.runtime);
  const st = s.state || {};
  const badge = s.running ? '<span class="badge go">running</span>' : '<span class="badge idle">idle</span>';
  $("#run-state").innerHTML = st.started_at
    ? `${badge} started ${st.started_at} · ${st.mode} · ${st.engine} · ${(st.samples || []).length} samples`
    : `${badge} no run recorded yet`;
  const tb = $("#steps tbody");
  tb.textContent = "";
  for (const st2 of s.steps) {
    const tr = el("tr");
    tr.append(el("td", null, st2.step), el("td", "num", st2.logs), el("td", "num", st2.finished),
              el("td", null, st2.last || "—"), el("td", null, st2.updated || "—"));
    tb.append(tr);
  }
  $("#squeue").textContent = s.squeue || "—";
  $("#runlog").textContent = s.log || "—";
  return s;
}

async function launch(sbatch) {
  const res = await fetch("/api/run", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sbatch }),
  });
  const body = await res.json();
  if (!res.ok) { $("#run-state").textContent = (body.errors || ["failed"]).join("; "); return; }
  refreshStatus();
}

async function refreshResults() {
  const r = await (await fetch("/api/results")).json();
  const m = $("#matrix");
  if (!r.matrix) m.textContent = "not available yet — results/summary_matrix.tsv appears when 08_summary finishes";
  else {
    m.textContent = "";
    const t = el("table"), head2 = el("thead"), hr = el("tr");
    r.matrix[0].forEach((c) => hr.append(el("th", null, c)));
    head2.append(hr); t.append(head2);
    const tb = el("tbody");
    r.matrix.slice(1).forEach((row) => {
      const tr = el("tr");
      row.forEach((c, i) => tr.append(el("td", i ? "num" : null, c)));
      tb.append(tr);
    });
    t.append(tb); m.append(t);
  }
  const box = $("#meta");
  box.textContent = "";
  const ids = Object.keys(r.meta);
  if (!ids.length) { box.append(el("p", "lede", "no results/meta/*.json yet")); return; }
  for (const id of ids) {
    const d = el("details"), su = el("summary", null, id), meta = r.meta[id];
    const rows = r.rows.filter((x) => x.sample_id === id)
      .map((x) => `${x.tool}: ${x.ki_pct}% (${x.ki_reads}/${x.reads_used})`).join("  ·  ");
    if (rows) su.textContent = `${id} — ${rows}`;
    d.append(su, Object.assign(el("pre"), { textContent: JSON.stringify(meta, null, 2) }));
    box.append(d);
  }
}

for (const b of document.querySelectorAll("nav button")) b.addEventListener("click", () => tab(b.dataset.tab));
$("#run-sbatch").addEventListener("click", () => launch(true));
$("#run-local").addEventListener("click", () => launch(false));
$("#stop").addEventListener("click", async () => { await fetch("/api/stop", { method: "POST" }); refreshStatus(); });
$("#refresh-results").addEventListener("click", refreshResults);
setInterval(() => { if ($("#auto").checked && !$("#tab-run").hidden) refreshStatus(); }, 5000);

$("#add").addEventListener("click", () => add());
$("#reload").addEventListener("click", load);
$("#submit").addEventListener("click", submit);
load();
refreshStatus();
