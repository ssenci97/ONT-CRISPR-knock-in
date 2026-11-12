#!/usr/bin/env python3
"""Serve the KNOCKIN-VAL console on localhost: submit samples, launch the pipeline, follow it and read the results."""
import argparse, datetime, json, os, re, resource, shutil, signal, subprocess, sys, time
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
SHIM, KV_BIN = f"{ROOT}/src/sbatch_pick.sh", f"{ROOT}/.kv_bin"
FASTQ_EXT = (".fastq", ".fastq.gz", ".fq", ".fq.gz")
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

###################################### environment
SNAKEMAKE_ENV, SNAKEMAKE_YML, LOCAL_ENV = "kv_snakemake", f"{ROOT}/envs/snakemake.yml", f"{ROOT}/.kv_env"
LOGIN_SKIP = {"PWD", "OLDPWD", "SHLVL", "_", "PS1"}

def login_env(cmd):
    try: r = subprocess.run(["bash", "-lc", f"{cmd} >/dev/null 2>&1; env -0"], capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired): return {}
    return dict(kv.split("=", 1) for kv in r.stdout.decode("utf-8", "replace").split("\0") if "=" in kv)

def adopt(env):
    for k, v in env.items():
        if k not in LOGIN_SKIP and not k.startswith("BASH_FUNC_") and os.environ.get(k) != v: os.environ[k] = v

def prepend_path(d): os.environ["PATH"] = f"{d}:{os.environ.get('PATH', '')}"

def find_conda():
    home = os.path.expanduser("~")
    for c in [os.environ.get("CONDA_EXE"), os.environ.get("MAMBA_EXE"), shutil.which("conda"), shutil.which("mamba")] + \
             [f"{home}/{b}/bin/conda" for b in ("miniforge3", "mambaforge", "miniconda3", "anaconda3", ".local/miniforge3")]:
        if c and os.path.isfile(c) and os.access(c, os.X_OK): return c
    c = login_env("true").get("CONDA_EXE")
    return c if c and os.path.isfile(c) else None

def quick_prefixes(conda):
    home = os.path.expanduser("~")
    out = [LOCAL_ENV, f"{home}/.conda/envs/{SNAKEMAKE_ENV}"]
    if os.environ.get("CONDA_PREFIX"): out.append(f"{os.environ['CONDA_PREFIX'].split('/envs/')[0]}/envs/{SNAKEMAKE_ENV}")
    if conda: out.append(f"{os.path.dirname(os.path.dirname(conda))}/envs/{SNAKEMAKE_ENV}")
    try:
        import yaml
        rc = yaml.safe_load(open(f"{home}/.condarc")) if os.path.exists(f"{home}/.condarc") else {}
        out += [f"{os.path.expanduser(d)}/{SNAKEMAKE_ENV}" for d in (rc or {}).get("envs_dirs", [])]
    except Exception: pass
    return out

def conda_prefixes(conda):
    log("asking conda for its env list (can take a minute on a shared filesystem)")
    try:
        r = subprocess.run([conda, "env", "list", "--json"], capture_output=True, text=True, timeout=300)
        return [p for p in json.loads(r.stdout).get("envs", []) if os.path.basename(p) == SNAKEMAKE_ENV]
    except (OSError, ValueError, subprocess.TimeoutExpired): log("!! conda env list failed or timed out"); return []

def with_snakemake(prefixes): return next((p for p in prefixes if os.access(f"{p}/bin/snakemake", os.X_OK)), None)

def ensure_singularity():
    if shutil.which("singularity"): return
    log("loading singularity (module load singularity)")
    adopt(login_env("module load singularity"))
    if not shutil.which("singularity") and shutil.which("apptainer"):
        os.makedirs(KV_BIN, exist_ok=True)
        if not os.path.exists(f"{KV_BIN}/singularity"): os.symlink(shutil.which("apptainer"), f"{KV_BIN}/singularity")
        prepend_path(KV_BIN)
    log(f"singularity: {shutil.which('singularity') or '!! still missing'}")

def ensure_snakemake():
    if shutil.which("snakemake"): return
    log(f"looking for the {SNAKEMAKE_ENV} conda env")
    conda = find_conda()
    hit = with_snakemake(quick_prefixes(conda)) or (with_snakemake(conda_prefixes(conda)) if conda else None)
    if not hit and conda:
        log(f"not found: creating it at {os.path.relpath(LOCAL_ENV, ROOT)} from {os.path.relpath(SNAKEMAKE_YML, ROOT)} (several minutes, only the first time)")
        subprocess.run([conda, "env", "create", "-p", LOCAL_ENV, "-f", SNAKEMAKE_YML])
        hit = with_snakemake([LOCAL_ENV])
    if hit: prepend_path(f"{hit}/bin")
    elif not conda: log("!! no conda found (looked at CONDA_EXE, PATH, ~/miniforge3, ~/miniconda3, ~/anaconda3, login shell)")
    log(f"snakemake: {shutil.which('snakemake') or '!! still missing'}")

def ensure_node_pick():
    if os.environ.get("NODE_PICK", "1") != "1": log("node pick off (NODE_PICK=0): jobs go to the profile partition"); return
    if not shutil.which("sbatch"): return
    os.makedirs(KV_BIN, exist_ok=True); link = f"{KV_BIN}/sbatch"
    if os.path.islink(link) and os.readlink(link) != SHIM: os.remove(link)
    if not os.path.lexists(link): os.symlink(SHIM, link)
    if os.path.dirname(shutil.which("sbatch")) != KV_BIN: prepend_path(KV_BIN)
    log(f"node pick on: sbatch -> {os.path.relpath(SHIM, ROOT)} (get_best_node per job)")

def node_pick(): return os.path.realpath(shutil.which("sbatch") or "") == SHIM

###################################### run
def runtime():
    sif = os.environ.get("KV_SIF") or (DEFAULT_SIF if os.path.exists(DEFAULT_SIF) else None)
    return dict(sif=sif, image=sif, sbatch=bool(shutil.which("sbatch")), node_pick=node_pick(), snakemake=shutil.which("snakemake"),
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

def start_run(name):
    for a in analyses():
        st = read_state(a["name"])
        if st.get("pid") and alive(st["pid"]): return None, f"analysis {a['name']} is still running"
    if not os.path.exists(SAMPLES_TSV): return None, "no configs/samples.tsv -- submit samples first"
    rt = runtime()
    if not rt["sbatch"]: return None, "sbatch not found: start the console on the cluster login node"
    if not rt["snakemake"]: return None, "snakemake not on PATH (conda activate kv_snakemake; create it once with conda env create -f envs/snakemake.yml)"
    if not rt["apptainer"]: return None, "singularity not on PATH (module load singularity before starting the console)"
    try: a_dir, new, errs = analysis.create(name, ROOT)
    except ValueError as e: return None, str(e)
    if errs: return None, errs
    env = dict(os.environ, KV_ANALYSIS=name, KV_ROOT=ROOT)
    cmd = ["snakemake", "--profile", Handler.profile,
           "--directory", ROOT, "--config", f"analysis={name}"]
    with open(run_log(name), "a") as fh:
        fh.write(f"\n===== {datetime.datetime.now():%F %T} {' '.join(cmd)} =====\n"); fh.flush()
        pr = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
    st = dict(analysis=name, pid=pr.pid, mode="slurm", node_pick=rt["node_pick"], started_at=f"{datetime.datetime.now():%F %T}",
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

def last_section(name):
    t = open(run_log(name), errors="replace").read() if os.path.exists(run_log(name)) else ""
    return t[t.rfind("\n===== ") + 1:] if "\n===== " in t else t

def sheet(name):
    inp = f"{RESULTS}/{name}/inputs"
    if not os.path.exists(f"{inp}/samples.tsv"): return [], {}
    rows = analysis.read_sheet(f"{inp}/samples.tsv")
    for r in rows:
        p = f"{inp}/samples/{r['sample_id']}.json"
        if os.path.exists(p): r.update({k: v for k, v in json.load(open(p)).items() if not r.get(k)})
    try:
        import yaml; P = yaml.safe_load(open(f"{inp}/params.yaml")) or {}
    except Exception: P = {}
    return rows, P

def planned_jobs(name):
    A = f"{RESULTS}/{name}"; rows, P = sheet(name)
    L = lambda step, f: f"{A}/logs/{step}/{f}.log"
    runs = sorted({r["srr"] for r in rows if r.get("srr") and not r.get("fastq_path")})
    jobs = {s: [] for s in STEPS}
    if runs and P.get("fetch", {}).get("bioproject"):
        jobs["01_fetch"].append(("ena", f"{ROOT}/data/meta/{P['fetch']['bioproject']}_ena.tsv", L("01_fetch", "ena"), False))
    jobs["01_fetch"] += [(f"download {r}", f"{ROOT}/data/raw/{r}.fastq.gz", L("01_fetch", f"download_{r}"), True) for r in runs]
    ids = [r["sample_id"] for r in rows]
    jobs["01_fetch"] += [(f"filter {s}", f"{A}/data/stats/{s}.tsv", L("01_fetch", f"filter_{s}"), True) for s in ids]
    jobs["02_refs"] = [("refs", f"{A}/refs/design.json", L("02_refs", "refs"), True)]
    jobs["03_alpine"] = [(f"alpine {s}", f"{A}/ALPINE/{s}/{s}_read_classification.txt", L("03_alpine", s), True) for s in ids]
    jobs["04_lungo"] = [(f"lungo {s}", f"{A}/CRISPRLungo/{s}/results/read_classification.txt", L("04_lungo", s), True) for s in ids]
    jobs["05_summary"] = [("summary", f"{A}/summary_matrix.tsv", L("05_summary", "summary"), True)]
    return jobs

def failed_logs(section):
    out, inside = set(), False
    for l in section.splitlines():
        if l.startswith("Error in rule "): inside = True
        elif inside and l.strip().startswith("log:"): out.add(os.path.normpath(os.path.join(ROOT, l.split("log:", 1)[1].split()[0]))); inside = False
        elif inside and not l.startswith(" "): inside = False
    return out

def step_state(name, running):
    failed, out = failed_logs(last_section(name)), []
    for step, jobs in planned_jobs(name).items():
        rows = []
        for label, output, lg, footer in jobs:
            has_log = os.path.exists(lg)
            if os.path.exists(output) and (not footer or not has_log or "elapsed" in tail(lg, 3)): st = "done"
            elif os.path.normpath(lg) in failed: st = "failed"
            elif has_log and running: st = "running"
            elif has_log: st = "stopped"
            else: st = "waiting"
            rows.append(dict(job=label, state=st, log=os.path.relpath(lg, ROOT),
                             updated=f"{datetime.datetime.fromtimestamp(os.path.getmtime(lg)):%F %T}" if has_log else None,
                             tail=tail(lg, 15) if st in ("failed", "stopped") else ""))
        count = lambda k: sum(r["state"] == k for r in rows)
        out.append(dict(step=step, total=len(rows), done=count("done"), failed=count("failed"), running=count("running"), jobs=rows))
    return out

def progress(section):
    m = re.findall(r"(\d+) of (\d+) steps \((\d+(?:\.\d+)?)%\) done", section)
    return dict(done=int(m[-1][0]), total=int(m[-1][1]), pct=float(m[-1][2])) if m else None

def queue(section):
    m = re.findall(r"SLURM run ID: ([0-9a-f-]+)", section)
    if not m or not shutil.which("squeue"): return []
    r = subprocess.run(["squeue", "--me", "-h", "-n", m[-1], "-o", "%i|%k|%T|%M|%P|%R"], capture_output=True, text=True)
    keys = ("job", "rule", "state", "time", "partition", "where")
    return [dict(zip(keys, l.split("|", 5)), rule=l.split("|")[1].replace("rule_", "").replace("_wildcards_", " ")) for l in r.stdout.splitlines() if l.count("|") >= 5]

def outcome(name, running, section):
    if running: return "running"
    if os.path.exists(f"{RESULTS}/{name}/summary_matrix.tsv"): return "done"
    if not section.strip(): return "idle"
    return "failed" if re.search(r"^(Error|WorkflowError|Exiting because)", section, re.M) else "stopped"

def status(name):
    st = read_state(name) if name else {}
    running = bool(st.get("pid") and alive(st["pid"]))
    sec = last_section(name) if name else ""
    return dict(runtime=runtime(), analyses=analyses(), analysis=name, state=st, running=running, outcome=outcome(name, running, sec) if name else "idle",
                progress=progress(sec), queue=queue(sec) if running else [], steps=step_state(name, running) if name else [],
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
    Handler.profile = p["profile"]
    ensure_singularity(); ensure_snakemake(); ensure_node_pick()
    srv =ThreadingHTTPServer((p["host"], int(p["port"])), Handler)
    rt = runtime()
    log(f"runtime {rt['engine']}" + (f" ({rt['sif'] or rt['image']})" if rt['sif'] or rt['image'] else "") + f", sbatch {'yes' if rt['sbatch'] else 'no'}, node pick {'on' if rt['node_pick'] else 'off'}")
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
