#!/usr/bin/env python3
"""Serve the KNOCKIN-VAL console on localhost: submit samples, launch the pipeline, follow it and read the results."""
import argparse, datetime, json, os, resource, shutil, signal, subprocess, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analysis

###################################### constants
T0 = time.time()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARAM_YAML, NAME = f"{ROOT}/configs/param_configs.yaml", "gui_serve"
GUI, SCHEMA = f"{ROOT}/gui", f"{ROOT}/configs/sample_schema.json"
SAMPLES_TSV, SAMPLES_DIR = f"{ROOT}/configs/samples.tsv", f"{ROOT}/configs/samples"
STATIC = {"/": ("submit.html", "text/html"), "/submit.css": ("submit.css", "text/css"), "/submit.js": ("submit.js", "application/javascript")}
RESULTS = f"{ROOT}/results"
DEFAULT_SIF = f"{ROOT}/containers/ont-knockin-val.sif"
STEPS = ["01_fetch", "02_refs", "03_alpine", "04_lungo", "05_summary"]
PARAMS = dict(host="127.0.0.1", port=8000, profile="profiles/slurm")

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
            fh.write("\t".join("1" if c == "control" and str(s.get(c)) in ("1", "true", "True") else
                               "0" if c == "control" else str(s.get(c, "") or "") for c in cols) + "\n")
    written = []
    for s in samples:
        d = {k: v for k, v in s.items() if v not in ("", None)}
        d["submitted_at"] = f"{datetime.datetime.now():%F %T}"
        p = f"{SAMPLES_DIR}/{d['sample_id']}.json"; json.dump(d, open(p, "w"), indent=2); written.append(os.path.relpath(p, ROOT))
    log(f"wrote {os.path.relpath(SAMPLES_TSV, ROOT)} ({len(samples)} samples) and {len(written)} sample json files")
    return dict(samples_tsv=os.path.relpath(SAMPLES_TSV, ROOT), sample_json=written, n=len(samples))

###################################### run
def runtime():
    sif = os.environ.get("KV_SIF") or (DEFAULT_SIF if os.path.exists(DEFAULT_SIF) else None)
    return dict(sif=sif, image=sif, sbatch=bool(shutil.which("sbatch")), snakemake=shutil.which("snakemake"),
                apptainer=shutil.which("singularity"), engine="apptainer" if sif else "apptainer (pull on first run)")

def read_state(name):
    p = run_state(name)
    return json.load(open(p)) if os.path.exists(p) else {}

def alive(pid):
    if not pid: return False
    try: os.waitpid(pid, os.WNOHANG)
    except OSError: pass
    try:
        with open(f"/proc/{pid}/stat") as fh: state = fh.read().rsplit(")", 1)[1].split()[0]
    except OSError: return False
    return state != "Z"

def start_run(name, sbatch):
    for a in analyses():
        st = read_state(a["name"])
        if st.get("pid") and alive(st["pid"]): return None, f"analysis {a['name']} is still running"
    if not os.path.exists(SAMPLES_TSV): return None, "no configs/samples.tsv -- submit samples first"
    rt = runtime()
    if sbatch and not rt["sbatch"]: return None, "sbatch not found on this machine"
    if not rt["snakemake"]: return None, "snakemake not on PATH (conda activate kv_snakemake; create it once with conda env create -f envs/snakemake.yml)"
    if not rt["apptainer"]: return None, "singularity not on PATH (module load singularity before starting the console)"
    try: a_dir, new, errs = analysis.create(name, ROOT)
    except ValueError as e: return None, str(e)
    if errs: return None, errs
    env = dict(os.environ)
    cmd = ["snakemake", "--profile", Handler.profile if sbatch else "profiles/local",
           "--directory", ROOT, "--config", f"analysis={name}"]
    with open(run_log(name), "a") as fh:
        fh.write(f"\n===== {datetime.datetime.now():%F %T} {' '.join(cmd)} =====\n"); fh.flush()
        pr = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
    st = dict(analysis=name, pid=pr.pid, mode="sbatch" if sbatch else "local", started_at=f"{datetime.datetime.now():%F %T}",
              engine=rt["engine"], image=rt["sif"], new=new,
              samples=json.load(open(f"{a_dir}/inputs/analysis.json"))["samples"])
    json.dump(st, open(run_state(name), "w"), indent=2)
    log(f"{'started' if new else 'resumed'} analysis {name}, pid {pr.pid} ({st['mode']})")
    return st, None

def stop_run(name):
    st = read_state(name)
    if not st.get("pid") or not alive(st["pid"]): return False
    try: os.kill(st["pid"], signal.SIGINT)
    except OSError: return False
    log(f"analysis {name}: run pid {st['pid']} stopped"); return True

def tail(path, n=40):
    if not os.path.exists(path): return ""
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END); size = fh.tell(); fh.seek(max(0, size - 65536))
        return "\n".join(fh.read().decode("utf-8", "replace").splitlines()[-n:])

def step_state(name):
    out = []
    for step in STEPS:
        d = f"{RESULTS}/{name}/logs/{step}"
        files = sorted((f"{d}/{f}" for f in os.listdir(d)), key=os.path.getmtime) if os.path.isdir(d) else []
        files = [f for f in files if not f.endswith(".bench.tsv")]
        done = sum(1 for f in files if "elapsed" in tail(f, 3))
        out.append(dict(step=step, logs=len(files), finished=done,
                        last=os.path.basename(files[-1]) if files else None,
                        updated=f"{datetime.datetime.fromtimestamp(os.path.getmtime(files[-1])):%F %T}" if files else None))
    return out

def status(name):
    st = read_state(name) if name else {}
    running = bool(st.get("pid") and alive(st["pid"]))
    q = ""
    if st.get("mode") == "sbatch" and shutil.which("squeue"):
        r = subprocess.run(["squeue", "--me", "-o", "%.10i %.12j %.2t %.10M %R"], capture_output=True, text=True)
        q = r.stdout.strip()
    return dict(runtime=runtime(), analyses=analyses(), analysis=name, state=st, running=running, squeue=q,
                steps=step_state(name) if name else [], log=tail(run_log(name)) if name else "")

def results(name):
    out = dict(matrix=None, rows=[], meta={})
    if not name: return out
    a = f"{RESULTS}/{name}"
    m = f"{a}/summary_matrix.tsv"
    if os.path.exists(m): out["matrix"] = [l.split("\t") for l in open(m).read().strip().splitlines()]
    s = f"{a}/summary.tsv"
    if os.path.exists(s): out["rows"] = tsv_rows(s)
    d = f"{a}/meta"
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.endswith(".json"):
                try: out["meta"][f[:-5]] = json.load(open(f"{d}/{f}"))
                except ValueError: pass
    return out

###################################### server
class Handler(BaseHTTPRequestHandler):
    profile = PARAMS["profile"]
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
        else: self.send_json(404, dict(error="not found"))
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/api/samples":
            errs = validate(body.get("samples", []))
            if errs: return self.send_json(400, dict(errors=errs))
            return self.send_json(200, save(body["samples"]))
        if self.path == "/api/run":
            st, err = start_run((body.get("analysis") or "").strip(), bool(body.get("sbatch")))
            if err: return self.send_json(400, dict(errors=err if isinstance(err, list) else [err]))
            return self.send_json(200, st)
        if self.path == "/api/stop": return self.send_json(200, dict(stopped=stop_run((body.get("analysis") or "").strip())))
        self.send_json(404, dict(error="not found"))

###################################### main
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--yaml-in", action="store_true"); ap.add_argument("--yaml-out", action="store_true")
    p = yaml_io(dict(PARAMS), ap.parse_args())
    for k, v in p.items(): log(f"param {k}={v}")
    Handler.profile = p["profile"]
    srv = ThreadingHTTPServer((p["host"], int(p["port"])), Handler)
    rt = runtime()
    log(f"runtime {rt['engine']}" + (f" ({rt['sif'] or rt['image']})" if rt['sif'] or rt['image'] else "") + f", sbatch {'yes' if rt['sbatch'] else 'no'}")
    if os.environ.get("KV_INSIDE"): log("warning: running inside the container; sbatch will not be reachable")
    if not rt["snakemake"]: log("!! snakemake not on PATH: runs will be refused (conda activate kv_snakemake)")
    if not rt["apptainer"]: log("!! singularity not on PATH: runs will be refused (module load singularity)")
    log(f"console at http://{p['host']}:{p['port']}/  (ctrl-c to stop)")
    try: srv.serve_forever()
    except KeyboardInterrupt: log("stopped")
    finally: srv.server_close()
    log(f"{datetime.datetime.now():%F %T} | elapsed {time.time() - T0:.1f} s | max RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576:.2f} GB")

if __name__ == "__main__":
    main()
