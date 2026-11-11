#!/usr/bin/env python3
"""Serve the KNOCKIN-VAL console on localhost: submit samples, launch the pipeline, follow it and read the results."""
import argparse, datetime, json, os, re, resource, shutil, signal, subprocess, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

###################################### constants
T0 = time.time()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARAM_YAML, NAME = f"{ROOT}/configs/param_configs.yaml", "gui_serve"
GUI, SCHEMA = f"{ROOT}/gui", f"{ROOT}/configs/sample_schema.json"
SAMPLES_TSV, SAMPLES_DIR = f"{ROOT}/configs/samples.tsv", f"{ROOT}/configs/samples"
ARRAY_STEPS = ["slurms/03_fetch.sh", "slurms/05_alpine.sh", "slurms/06_lungo.sh", "slurms/07_crispresso.sh"]
STATIC = {"/": ("submit.html", "text/html"), "/submit.css": ("submit.css", "text/css"), "/submit.js": ("submit.js", "application/javascript")}
RESULTS, LOGS = f"{ROOT}/results", f"{ROOT}/logs"
RUN_LOG, RUN_STATE = f"{RESULTS}/run.log", f"{RESULTS}/run_state.json"
DEFAULT_SIF = f"{ROOT}/containers/ont-knockin-val.sif"
STEPS = ["01_clone", "02_envs", "03_fetch", "04_build_refs", "05_alpine", "06_lungo", "07_crispresso", "08_summary"]
PARAMS = dict(host="127.0.0.1", port=8000, sync_arrays=1)
ID_RE = re.compile(r"^[A-Za-z0-9_]+$")

###################################### helpers
def log(m): print(f"[PYTHON-INFO] {m}", flush=True)
def yaml_io(p, a):
    import yaml
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

def validate(samples):
    seen, errs = set(), []
    for i, s in enumerate(samples, 1):
        sid = (s.get("sample_id") or "").strip()
        if not ID_RE.match(sid): errs.append(f"row {i}: sample_id {sid!r} must be letters, digits or underscore")
        if sid in seen: errs.append(f"row {i}: duplicate sample_id {sid!r}")
        seen.add(sid)
        if not (s.get("condition") or "").strip(): errs.append(f"row {i}: condition is required")
        if not (s.get("srr") or "").strip() and not (s.get("fastq_path") or "").strip():
            errs.append(f"row {i}: give either an SRA run accession or a local FASTQ path")
    if samples and not any(str(s.get("control")) in ("1", "true", "True") for s in samples):
        errs.append("at least one sample must be marked as negative control (CRISPRLungo needs it)")
    return errs

def sync_arrays(n):
    changed = []
    for rel in ARRAY_STEPS:
        p = f"{ROOT}/{rel}"; s = open(p).read()
        new = re.sub(r"(#SBATCH --array=1-)\d+", lambda m: m.group(1) + str(n), s, count=1)
        if new != s: open(p, "w").write(new); changed.append(rel)
    return changed

def save(samples, sync):
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
    arrays = sync_arrays(len(samples)) if sync else []
    log(f"wrote {os.path.relpath(SAMPLES_TSV, ROOT)} ({len(samples)} samples) and {len(written)} sample json files")
    if arrays: log(f"array size set to 1-{len(samples)} in {', '.join(arrays)}")
    return dict(samples_tsv=os.path.relpath(SAMPLES_TSV, ROOT), sample_json=written, arrays=arrays, n=len(samples))

###################################### run
def runtime():
    sif, image = os.environ.get("KV_SIF"), os.environ.get("KV_IMAGE")
    if not sif and not image and os.path.exists(DEFAULT_SIF): sif = DEFAULT_SIF
    return dict(sif=sif, image=image, sbatch=bool(shutil.which("sbatch")),
                engine="apptainer" if sif else ("podman" if image else "native"))

def read_state():
    return json.load(open(RUN_STATE)) if os.path.exists(RUN_STATE) else {}

def alive(pid):
    if not pid: return False
    try: os.waitpid(pid, os.WNOHANG)
    except OSError: pass
    try:
        with open(f"/proc/{pid}/stat") as fh: state = fh.read().rsplit(")", 1)[1].split()[0]
    except OSError: return False
    return state != "Z"

def start_run(sbatch):
    st = read_state()
    if st.get("pid") and alive(st["pid"]): return None, "a run is already in progress"
    if not os.path.exists(SAMPLES_TSV): return None, "no configs/samples.tsv -- submit samples first"
    os.makedirs(RESULTS, exist_ok=True)
    rt = runtime()
    if sbatch and not rt["sbatch"]: return None, "sbatch not found on this machine"
    env = dict(os.environ)
    if rt["sif"]: env["KV_SIF"] = rt["sif"]
    cmd = ["bash", "slurms/run_all.sh"] + (["--sbatch"] if sbatch else [])
    with open(RUN_LOG, "a") as fh:
        fh.write(f"\n===== {datetime.datetime.now():%F %T} {' '.join(cmd)} ({rt['engine']}) =====\n"); fh.flush()
        pr = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
    st = dict(pid=pr.pid, mode="sbatch" if sbatch else "local", started_at=f"{datetime.datetime.now():%F %T}",
              engine=rt["engine"], image=rt["sif"] or rt["image"], samples=[r["sample_id"] for r in load_samples()])
    json.dump(st, open(RUN_STATE, "w"), indent=2)
    log(f"run started pid {pr.pid} ({st['mode']}, {st['engine']})")
    return st, None

def stop_run():
    st = read_state()
    if not st.get("pid") or not alive(st["pid"]): return False
    try: os.killpg(os.getpgid(st["pid"]), signal.SIGTERM)
    except OSError: return False
    log(f"run pid {st['pid']} stopped"); return True

def tail(path, n=40):
    if not os.path.exists(path): return ""
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END); size = fh.tell(); fh.seek(max(0, size - 65536))
        return "\n".join(fh.read().decode("utf-8", "replace").splitlines()[-n:])

def step_state():
    out = []
    for name in STEPS:
        d = f"{LOGS}/{name}"
        files = sorted((f"{d}/{f}" for f in os.listdir(d)), key=os.path.getmtime) if os.path.isdir(d) else []
        done = sum(1 for f in files if "elapsed" in tail(f, 3))
        out.append(dict(step=name, logs=len(files), finished=done,
                        last=os.path.basename(files[-1]) if files else None,
                        updated=f"{datetime.datetime.fromtimestamp(os.path.getmtime(files[-1])):%F %T}" if files else None))
    return out

def status():
    st = read_state()
    running = bool(st.get("pid") and alive(st["pid"]))
    q = ""
    if st.get("mode") == "sbatch" and shutil.which("squeue"):
        r = subprocess.run(["squeue", "--me", "-o", "%.10i %.12j %.2t %.10M %R"], capture_output=True, text=True)
        q = r.stdout.strip()
    return dict(runtime=runtime(), state=st, running=running, squeue=q, steps=step_state(), log=tail(RUN_LOG))

def results():
    out = dict(matrix=None, rows=[], meta={})
    m = f"{RESULTS}/summary_matrix.tsv"
    if os.path.exists(m): out["matrix"] = [l.split("\t") for l in open(m).read().strip().splitlines()]
    s = f"{RESULTS}/summary.tsv"
    if os.path.exists(s): out["rows"] = tsv_rows(s)
    d = f"{RESULTS}/meta"
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.endswith(".json"):
                try: out["meta"][f[:-5]] = json.load(open(f"{d}/{f}"))
                except ValueError: pass
    return out

###################################### server
class Handler(BaseHTTPRequestHandler):
    sync = True
    def log_message(self, fmt, *a): log(f"{self.address_string()} {fmt % a}")
    def send_json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path in STATIC:
            name, ctype = STATIC[self.path]; b = open(f"{GUI}/{name}", "rb").read()
            self.send_response(200); self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        elif self.path == "/api/schema": self.send_json(200, json.load(open(SCHEMA)))
        elif self.path == "/api/samples": self.send_json(200, dict(samples=load_samples()))
        elif self.path == "/api/status": self.send_json(200, status())
        elif self.path == "/api/results": self.send_json(200, results())
        else: self.send_json(404, dict(error="not found"))
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/api/samples":
            errs = validate(body.get("samples", []))
            if errs: return self.send_json(400, dict(errors=errs))
            return self.send_json(200, save(body["samples"], Handler.sync))
        if self.path == "/api/run":
            st, err = start_run(bool(body.get("sbatch")))
            return self.send_json(400, dict(errors=[err])) if err else self.send_json(200, st)
        if self.path == "/api/stop": return self.send_json(200, dict(stopped=stop_run()))
        self.send_json(404, dict(error="not found"))

###################################### main
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--yaml-in", action="store_true"); ap.add_argument("--yaml-out", action="store_true")
    p = yaml_io(dict(PARAMS), ap.parse_args())
    for k, v in p.items(): log(f"param {k}={v}")
    Handler.sync = bool(int(p["sync_arrays"]))
    srv = ThreadingHTTPServer((p["host"], int(p["port"])), Handler)
    rt = runtime()
    log(f"runtime {rt['engine']}" + (f" ({rt['sif'] or rt['image']})" if rt['sif'] or rt['image'] else "") + f", sbatch {'yes' if rt['sbatch'] else 'no'}")
    if os.environ.get("KV_INSIDE"): log("warning: running inside the container; sbatch will not be reachable")
    log(f"console at http://{p['host']}:{p['port']}/  (ctrl-c to stop)")
    try: srv.serve_forever()
    except KeyboardInterrupt: log("stopped")
    finally: srv.server_close()
    log(f"{datetime.datetime.now():%F %T} | elapsed {time.time() - T0:.1f} s | max RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576:.2f} GB")

if __name__ == "__main__":
    main()
