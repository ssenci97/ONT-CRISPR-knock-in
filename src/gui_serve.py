#!/usr/bin/env python3
"""Serve the KNOCKIN-VAL console on localhost: submit samples, launch the pipeline, follow it and read the results."""
import argparse, datetime, json, os, resource, shutil, subprocess, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analysis, pipeline

###################################### constants
T0 = time.time()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARAM_YAML, NAME = f"{ROOT}/configs/param_configs.yaml", "gui_serve"
GUI, SCHEMA = f"{ROOT}/gui", f"{ROOT}/configs/sample_schema.json"
SAMPLES_TSV, SAMPLES_DIR = f"{ROOT}/configs/samples.tsv", f"{ROOT}/configs/samples"
STATIC = {"/": ("submit.html", "text/html"), "/submit.css": ("submit.css", "text/css"), "/submit.js": ("submit.js", "application/javascript")}
RESULTS = f"{ROOT}/results"
DEFAULT_SIF = f"{ROOT}/containers/ont-knockin-val.sif"
STEPS, LIVE = pipeline.STEPS, pipeline.LIVE
KV_BIN, PIPELINE = f"{ROOT}/.kv_bin", os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline.py")
FAILED = {"FAILED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL", "BOOT_FAIL", "DEADLINE", "PREEMPTED"}
RUNNING = {"RUNNING", "CONFIGURING", "COMPLETING"}
FASTQ_EXT = (".fastq", ".fastq.gz", ".fq", ".fq.gz")
PARAMS = dict(host="127.0.0.1", port=8000)

def run_log(name): return f"{RESULTS}/{name}/run.log"
def run_state(name): return f"{RESULTS}/{name}/run_state.json"

###################################### helpers
def log(m): print(f"[PYTHON-INFO] {m}", flush=True)
def yaml_io(p, a):
    try: import yaml
    except ImportError:
        log(f"!! PyYAML not installed: using built-in defaults, {PARAM_YAML} ignored")
        return p
    c = (yaml.safe_load(open(PARAM_YAML)) if os.path.exists(PARAM_YAML) else None) or {}
    if a.yaml_in: p.update(c.get(NAME, {})); log(f"params read from {PARAM_YAML} [{NAME}]")
    if a.yaml_out: c[NAME] = p; yaml.safe_dump(c, open(PARAM_YAML, "w"), sort_keys=False); log(f"params written to {PARAM_YAML} [{NAME}]")
    return p

###################################### persistence
def columns(): return json.load(open(SCHEMA))["sheet_columns"]

def tsv_rows(p):
    rows = [l.rstrip("\n").split("\t") for l in open(p) if l.strip()]
    return [dict(zip(rows[0], r)) for r in rows[1:]]

def load_samples():
    if not os.path.exists(SAMPLES_TSV): return []
    rows = [l.rstrip("\n").split("\t") for l in open(SAMPLES_TSV) if l.strip()]
    head, out = rows[0], []
    for r in rows[1:]:
        d = dict(zip(head, r)); p = f"{SAMPLES_DIR}/{d['sample_id']}.json"
        if os.path.exists(p): d.update({k: v for k, v in json.load(open(p)).items() if k not in d})
        out.append(d)
    return out

validate = analysis.validate

def analyses():
    out = []
    for n in sorted(os.listdir(RESULTS)) if os.path.isdir(RESULTS) else []:
        p = f"{RESULTS}/{n}/inputs/analysis.json"
        if os.path.exists(p):
            try: d = json.load(open(p))
            except ValueError: continue
            st = json.load(open(run_state(n))) if os.path.exists(run_state(n)) else {}
            out.append(dict(name=n, created_at=d.get("created_at"), samples=d.get("samples", []),
                            started_at=st.get("started_at"), done=os.path.exists(f"{RESULTS}/{n}/summary_matrix.tsv")))
    return out

def save(samples):
    cols = columns(); os.makedirs(SAMPLES_DIR, exist_ok=True)
    with open(SAMPLES_TSV, "w") as fh:
        fh.write("\t".join(cols) + "\n")
        for s in samples:
            fh.write("\t".join(analysis.tier(s) if c == "control_tier" else str(s.get(c, "") or "") for c in cols) + "\n")
    written = []
    for s in samples:
        d = {k: v for k, v in s.items() if v not in ("", None)}
        d["submitted_at"] = f"{datetime.datetime.now():%F %T}"
        p = f"{SAMPLES_DIR}/{d['sample_id']}.json"; json.dump(d, open(p, "w"), indent=2); written.append(os.path.relpath(p, ROOT))
    log(f"wrote {os.path.relpath(SAMPLES_TSV, ROOT)} ({len(samples)} samples) and {len(written)} sample json files")
    return dict(samples_tsv=os.path.relpath(SAMPLES_TSV, ROOT), sample_json=written, n=len(samples))

###################################### environment
LOGIN_SKIP = {"PWD", "OLDPWD", "SHLVL", "_", "PS1"}

def login_env(cmd):
    try: r = subprocess.run(["bash", "-lc", f"{cmd} >/dev/null 2>&1; env -0"], capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired): return {}
    return dict(kv.split("=", 1) for kv in r.stdout.decode("utf-8", "replace").split("\0") if "=" in kv)

def adopt(env):
    for k, v in env.items():
        if k not in LOGIN_SKIP and not k.startswith("BASH_FUNC_") and os.environ.get(k) != v: os.environ[k] = v

def prepend_path(d): os.environ["PATH"] = f"{d}:{os.environ.get('PATH', '')}"

def ensure_singularity():
    if shutil.which("singularity"): return
    log("loading singularity (module load singularity)")
    adopt(login_env("module load singularity"))
    if not shutil.which("singularity") and shutil.which("apptainer"):
        os.makedirs(KV_BIN, exist_ok=True)
        if not os.path.exists(f"{KV_BIN}/singularity"): os.symlink(shutil.which("apptainer"), f"{KV_BIN}/singularity")
        prepend_path(KV_BIN)
    log(f"singularity: {shutil.which('singularity') or '!! still missing'}")

def node_pick(): return os.environ.get("NODE_PICK", "1") != "0" and bool(shutil.which("sbatch"))

###################################### run
def runtime():
    sif = os.environ.get("KV_SIF") or (DEFAULT_SIF if os.path.exists(DEFAULT_SIF) else None)
    return dict(sif=sif, image=sif, sbatch=bool(shutil.which("sbatch")), node_pick=node_pick(),
                apptainer=shutil.which("singularity"), engine="apptainer" if sif else "apptainer (pull on first run)")

def read_state(name):
    p = run_state(name)
    return json.load(open(p)) if os.path.exists(p) else {}

def job_states(name):
    rows = pipeline.read_jobs(name, ROOT)
    return rows, pipeline.slurm_states([r["jobid"] for r in rows])

def live_rows(name):
    rows, st = job_states(name)
    return [r for r in rows if st.get(r["jobid"]) in LIVE]

def start_run(name):
    for a in analyses():
        if live_rows(a["name"]): return None, f"analysis {a['name']} is still running"
    if not os.path.exists(SAMPLES_TSV): return None, "no configs/samples.tsv -- submit samples first"
    rt = runtime()
    if not rt["sbatch"]: return None, "sbatch not found: start the console on the cluster login node"
    if not rt["apptainer"]: return None, "singularity not on PATH (module load singularity before starting the console)"
    try: a_dir, new, errs = analysis.create(name, ROOT)
    except ValueError as e: return None, str(e)
    if errs: return None, errs
    cmd = ["python3", PIPELINE, name, "--root", ROOT]
    with open(run_log(name), "a") as fh:
        fh.write(f"\n===== {datetime.datetime.now():%F %T} {' '.join(cmd)} =====\n"); fh.flush()
        try: rc = subprocess.run(cmd, cwd=ROOT, env=dict(os.environ, KV_ROOT=ROOT), stdout=fh, stderr=subprocess.STDOUT, timeout=600).returncode
        except subprocess.TimeoutExpired: rc = -1; fh.write("[PYTHON-INFO] !! pipeline.py timed out after 600 s\n")
    sec = last_section(name)
    if rc:
        bad = [l.split("!!", 1)[1].strip() for l in sec.splitlines() if "!!" in l]
        return None, bad or [l for l in sec.splitlines() if l.strip()][-5:]
    st = dict(analysis=name, mode="slurm", node_pick=rt["node_pick"], started_at=f"{datetime.datetime.now():%F %T}",
              engine=rt["engine"], image=rt["sif"], new=new, samples=json.load(open(f"{a_dir}/inputs/analysis.json"))["samples"],
              submitted=sum(bool(r["jobid"]) for r in pipeline.read_jobs(name, ROOT)))
    json.dump(st, open(run_state(name), "w"), indent=2)
    log(f"{'started' if new else 'resumed'} analysis {name}, {st['submitted']} job(s) submitted ({st['mode']})")
    return st, None

def stop_run(name):
    n = pipeline.stop(name, ROOT)
    if n: log(f"analysis {name}: cancelled {n} job(s)")
    return n > 0

def tail(path, n=40):
    if not os.path.exists(path): return ""
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END); size = fh.tell(); fh.seek(max(0, size - 65536))
        return "\n".join(fh.read().decode("utf-8", "replace").splitlines()[-n:])

def last_section(name):
    t = open(run_log(name), errors="replace").read() if os.path.exists(run_log(name)) else ""
    return t[t.rfind("\n===== ") + 1:] if "\n===== " in t else t

def job_state(job, by, st, jobid):
    if pipeline.is_done(job, by): return "done"
    s = st.get(jobid, "") if jobid else ""
    if s == "PENDING": return "waiting"
    if s in RUNNING: return "running"
    if s in FAILED: return "failed"
    if s.startswith("CANCELLED"): return "cancelled"
    return "stopped" if os.path.exists(job["log"]) else "waiting"

def step_state(name, rows, st):
    try: jobs = pipeline.plan(name, ROOT)
    except (ValueError, OSError, KeyError, RuntimeError): return []
    by, ids, out = {j["key"]: j for j in jobs}, {r["key"]: r["jobid"] for r in rows}, []
    for step in STEPS:
        L = []
        for j in (j for j in jobs if j["step"] == step):
            s, lg = job_state(j, by, st, ids.get(j["key"])), j["log"]; has = os.path.exists(lg)
            L.append(dict(job=j["label"], state=s, log=os.path.relpath(lg, ROOT), updated=f"{datetime.datetime.fromtimestamp(os.path.getmtime(lg)):%F %T}" if has else None,
                          tail=tail(lg, 15) if s in ("failed", "stopped", "cancelled") else ""))
        count = lambda k: sum(r["state"] == k for r in L)
        out.append(dict(step=step, total=len(L), done=count("done"), failed=count("failed"), cancelled=count("cancelled"), running=count("running"), jobs=L))
    return out

def progress(steps):
    total, done = sum(s["total"] for s in steps), sum(s["done"] for s in steps)
    return dict(done=done, total=total, pct=round(100 * done / total, 1)) if total else None

def queue(live):
    if not live or not shutil.which("squeue"): return []
    r = subprocess.run(["squeue", "-h", "-j", ",".join(x["jobid"] for x in live), "-o", "%i|%j|%T|%M|%P|%R"], capture_output=True, text=True)
    label, keys = {x["jobid"]: x["label"] for x in live}, ("job", "rule", "state", "time", "partition", "where")
    return [dict(zip(keys, l.split("|", 5)), rule=label.get(l.split("|")[0].strip(), l.split("|")[1])) for l in r.stdout.splitlines() if l.count("|") >= 5]

def outcome(name, running, steps, rows):
    if running: return "running"
    states = {j["state"] for s in steps for j in s["jobs"]}
    summ = [j for s in steps if s["step"] == STEPS[-1] for j in s["jobs"]]
    if os.path.exists(f"{RESULTS}/{name}/summary_matrix.tsv") and summ and all(j["state"] == "done" for j in summ): return "done"
    if states & {"failed", "cancelled"}: return "failed"
    return "stopped" if rows or last_section(name).strip() else "idle"

def status(name):
    st = read_state(name) if name else {}
    rows, sl = job_states(name) if name else ([], {})
    live = [r for r in rows if sl.get(r["jobid"]) in LIVE]
    steps = step_state(name, rows, sl) if name else []
    return dict(runtime=runtime(), analyses=analyses(), analysis=name, state=st, running=bool(live), outcome=outcome(name, bool(live), steps, rows) if name else "idle",
                progress=progress(steps), queue=queue(live), steps=steps,
                node_log=tail(f"{RESULTS}/{name}/logs/node_pick.log", 20) if name else "", log=tail(run_log(name)) if name else "")

def params():
    try:
        import yaml; return yaml.safe_load(open(PARAM_YAML)) or {}
    except Exception: return {}

def path_info(p):
    p = os.path.expanduser(p or "")
    if not p: p = os.path.expanduser("~") + "/"
    out = dict(path=p, exists=os.path.exists(p), file=os.path.isfile(p), size=os.path.getsize(p) if os.path.isfile(p) else None, entries=[])
    d = p if p.endswith("/") else os.path.dirname(p)
    try:
        for e in sorted(os.scandir(d), key=lambda e: e.name)[:500]:
            if e.name.startswith("."): continue
            if e.is_dir(): out["entries"].append(os.path.join(d, e.name) + "/")
            elif e.name.endswith(FASTQ_EXT): out["entries"].append(os.path.join(d, e.name))
    except OSError: pass
    return out

def results(name):
    out = dict(matrix=None, rows=[], classes=None, reads={}, meta={})
    if not name: return out
    a = f"{RESULTS}/{name}"
    m = f"{a}/summary_matrix.tsv"
    if os.path.exists(m): out["matrix"] = [l.split("\t") for l in open(m).read().strip().splitlines()]
    s = f"{a}/summary.tsv"
    if os.path.exists(s): out["rows"] = tsv_rows(s)
    c = f"{a}/summary_classes.tsv"
    if os.path.exists(c): out["classes"] = tsv_rows(c)
    d = f"{a}/meta"
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.endswith(".json"):
                try: out["meta"][f[:-5]] = json.load(open(f"{d}/{f}"))
                except ValueError: pass
    for sid, j in out["meta"].items():
        f = (j.get("steps") or {}).get("01_fetch") or {}
        if "raw_reads" in f: out["reads"][sid] = dict(raw_reads=f.get("raw_reads"), len_pass=f.get("len_pass"))
    st = f"{a}/data/stats"
    for f in sorted(os.listdir(st)) if os.path.isdir(st) else []:
        for r in tsv_rows(f"{st}/{f}") if f.endswith(".tsv") else []: out["reads"][r["sample_id"]] = dict(raw_reads=r.get("raw_reads"), len_pass=r.get("len_pass"))
    return out

###################################### server
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a): log(f"{self.address_string()} {fmt % a}")
    def send_json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def query(self, k):
        return (parse_qs(urlparse(self.path).query).get(k) or [""])[0]
    def do_GET(self):
        path = urlparse(self.path).path
        if path in STATIC:
            name, ctype = STATIC[path]; b = open(f"{GUI}/{name}", "rb").read()
            self.send_response(200); self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        elif path == "/api/schema": self.send_json(200, json.load(open(SCHEMA)))
        elif path == "/api/samples": self.send_json(200, dict(samples=load_samples()))
        elif path == "/api/status": self.send_json(200, status(self.query("analysis")))
        elif path == "/api/results": self.send_json(200, results(self.query("analysis")))
        elif path == "/api/params": self.send_json(200, params())
        elif path == "/api/path": self.send_json(200, path_info(self.query("p")))
        else: self.send_json(404, dict(error="not found"))
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/api/samples":
            errs = validate(body.get("samples", []))
            if errs: return self.send_json(400, dict(errors=errs))
            return self.send_json(200, save(body["samples"]))
        if self.path == "/api/run":
            st, err = start_run((body.get("analysis") or "").strip())
            if err: return self.send_json(400, dict(errors=err if isinstance(err, list) else [err]))
            return self.send_json(200, st)
        if self.path == "/api/stop": return self.send_json(200, dict(stopped=stop_run((body.get("analysis") or "").strip())))
        self.send_json(404, dict(error="not found"))

###################################### main
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--yaml-in", action="store_true"); ap.add_argument("--yaml-out", action="store_true")
    p = yaml_io(dict(PARAMS), ap.parse_args())
    for k, v in p.items(): log(f"param {k}={v}")
    ensure_singularity()
    srv =ThreadingHTTPServer((p["host"], int(p["port"])), Handler)
    rt = runtime()
    log(f"runtime {rt['engine']}" + (f" ({rt['sif'] or rt['image']})" if rt['sif'] or rt['image'] else "") + f", sbatch {'yes' if rt['sbatch'] else 'no'}, node pick {'on' if rt['node_pick'] else 'off'}")
    if os.environ.get("KV_INSIDE"): log("warning: running inside the container; sbatch will not be reachable")
    if not rt["apptainer"]: log("!! singularity not on PATH: runs will be refused (module load singularity)")
    log(f"console at http://{p['host']}:{p['port']}/  (ctrl-c to stop)")
    try: srv.serve_forever()
    except KeyboardInterrupt: log("stopped")
    finally: srv.server_close()
    log(f"{datetime.datetime.now():%F %T} | elapsed {time.time() - T0:.1f} s | max RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576:.2f} GB")

if __name__ == "__main__":
    main()
