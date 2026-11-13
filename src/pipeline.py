#!/usr/bin/env python3
"""Plan, submit and track the KNOCKIN-VAL jobs of an analysis on SLURM: files on disk decide what runs, no workflow engine."""
import argparse, csv, datetime, fcntl, getpass, glob, json, os, re, resource, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analysis

###################################### constants
T0 = time.time()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEPS = ["01_fetch", "02_refs", "03_alpine", "04_lungo", "05_summary"]
LIVE = {"PENDING", "RUNNING", "CONFIGURING", "COMPLETING", "SUSPENDED"}
FASTQ_EXT = (".fastq", ".fastq.gz", ".fq", ".fq.gz")
BP_RE = re.compile(r"^[A-Za-z0-9]+$")
FOOTER = re.compile(r"\| elapsed [0-9]")
COLS = ["key", "step", "label", "jobid", "log", "node", "cpus", "mem_mb", "minutes", "in_bytes"]
RES = dict(ena=(1, 1000, 15), download=(8, 16000, 720), filter=(8, 8000, 240), refs=(1, 4000, 60), alpine=(16, 64000, 1440), lungo=(16, 64000, 1440), summary=(1, 4000, 30))
PARTITION, BUDGET_CPUS, BUDGET_MEM_MB = "GENOA", 32, 256000
MEM_MIN, MEM_MAX, TIME_MIN, TIME_MAX, SAFETY = 1000, BUDGET_MEM_MB, 15, 2880, 1.5
MAX_JOBS, MAX_USER_JOBS, STOP_WAIT, STOP_PAUSE = 100, 200, 120, 2
REF_FILES = ("TRAC_WT.fa", "TRAC_KI.fa", "CAR_insert.fa", "alpine/ref.fa", "alpine/config.tsv", "design.json")

###################################### helpers
def log(m): print(f"[PYTHON-INFO] {m}", flush=True)
def size(p): return os.path.getsize(p) if os.path.isfile(p) else 0
def mtime(p): return os.path.getmtime(p)

def image_ref(root):
    return open(f"{root}/containers/images.env").read().split("KV_IMAGE_REF=")[1].split()[0]

def image(root):
    sif = f"{root}/containers/ont-knockin-val.sif"
    return os.environ.get("KV_SIF") or (sif if os.path.exists(sif) else f"docker://{image_ref(root)}")

def load_params(path, root):
    try: import yaml
    except ImportError:
        cmd = 'command -v singularity >/dev/null || module load singularity; singularity exec --cleanenv --bind "$1" "$2" python3 -c "import json, sys, yaml; print(json.dumps(yaml.safe_load(open(sys.argv[1]))))" "$3"'
        r = subprocess.run(["bash", "-lc", cmd, "bash", root, image(root), path], capture_output=True, text=True)
        if r.returncode: raise RuntimeError(f"PyYAML missing and the image fallback failed: {r.stderr.strip()[-300:]}")
        return json.loads(r.stdout.strip().splitlines()[-1])
    return yaml.safe_load(open(path))

def kind(key): return key if key in RES else key.split("_")[0]

def sh(cmd, timeout=30):
    try: return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.splitlines()
    except (OSError, subprocess.SubprocessError): return []

def outside(path, root):
    r = os.path.realpath(root)
    return [d for d in dict.fromkeys([os.path.dirname(path), os.path.dirname(os.path.realpath(path))]) if not (d == r or d.startswith(r + "/"))]

###################################### plan
def plan(name, root=ROOT):
    analysis.analysis_dir(name, root)
    a, inp = f"results/{name}", f"results/{name}/inputs"
    if not os.path.exists(f"{root}/{inp}/samples.tsv"): raise ValueError(f"{inp}/samples.tsv missing: create the analysis first with python3 src/analysis.py {name}")
    P = load_params(f"{root}/{inp}/params.yaml", root)
    samples = {r["sample_id"]: r for r in csv.DictReader(open(f"{root}/{inp}/samples.tsv"), delimiter="\t") if r["sample_id"]}
    ctrl = analysis.control_sample(samples)
    if not samples: raise ValueError(f"{inp}/samples.tsv has no samples")
    if not ctrl: raise ValueError(f"{inp}/samples.tsv: no sample has control_tier mock or no_donor (CRISPRLungo needs one)")
    bad = [s for s in samples if not analysis.ID_RE.match(s)] + [r for r in (x.get("srr") for x in samples.values()) if r and not analysis.SRR_RE.match(r)]
    if bad or not BP_RE.match(str(P["fetch"]["bioproject"])): raise ValueError(f"invalid sample id, run accession or bioproject: {bad or P['fetch']['bioproject']}")
    def submitted(s):
        p = f"{root}/{inp}/samples/{s}.json"
        return json.load(open(p)) if os.path.exists(p) else {}
    local = {s: r.get("fastq_path") or submitted(s).get("fastq_path") or "" for s, r in samples.items()}
    runs = list(dict.fromkeys(r.get("srr") for s, r in samples.items() if r.get("srr") and not local[s]))
    refs = [f"{a}/refs/{f}" for f in REF_FILES]
    frac, ab = P["shared"]["ki_min_insert_frac"], lambda p: f"{root}/{p}"
    jobs = []
    def add(key, step, label, kind, script, args, outputs, logp, deps=(), shared=False, binds=(), inputs=()):
        c, m, t = RES[kind]
        jobs.append(dict(key=key, inputs=[x if os.path.isabs(x) else ab(x) for x in inputs], step=step, label=label, script=f"src/{script}", args=[str(x) for x in args], outputs=[ab(o) for o in outputs], log=ab(logp), cpus=c, mem_mb=m, minutes=t, deps=list(dict.fromkeys(deps)), shared=shared, binds=list(binds)))
    if runs:
        meta, ena = f"data/meta/{P['fetch']['bioproject']}_ena.tsv", f"ena_{P['fetch']['bioproject']}"
        add(ena, STEPS[0], "ena filereport", "ena", "ena.sh", [P["fetch"]["bioproject"], meta], [meta], f"{a}/logs/01_fetch/ena.log", shared=True)
        for r in runs: add(f"download_{r}", STEPS[0], f"download {r}", "download", "download.sh", [r, meta, f"data/raw/{r}.fastq.gz", "{cpus}"], [f"data/raw/{r}.fastq.gz"], f"{a}/logs/01_fetch/download_{r}.log", [ena], True, inputs=[meta])
    for s, r in samples.items():
        raw = local[s] or f"data/raw/{r['srr']}.fastq.gz"
        add(f"filter_{s}", STEPS[0], f"filter {s}", "filter", "filter.sh", [s, r.get("srr") or "local", raw, f"{a}/data/{s}.fastq.gz", f"{a}/data/stats/{s}.tsv", P["fetch"]["min_len"], P["fetch"]["max_len"], "{cpus}"],
            [f"{a}/data/{s}.fastq.gz", f"{a}/data/stats/{s}.tsv"], f"{a}/logs/01_fetch/filter_{s}.log", [] if local[s] else [f"download_{r['srr']}"], binds=outside(local[s], root) if local[s] else [], inputs=[raw])
    add("refs", STEPS[1], "refs", "refs", "refs.sh", [], [f"{a}/refs/{f}" for f in REF_FILES], f"{a}/logs/02_refs/refs.log")
    for s in samples:
        add(f"alpine_{s}", STEPS[2], f"alpine {s}", "alpine", "alpine.sh", [s, f"{a}/data/{s}.fastq.gz", f"{a}/ALPINE/{s}", P["alpine"]["primer_check_length"], P["alpine"]["data_type"], frac, "{cpus}", "{mem_mb}"],
            [f"{a}/ALPINE/{s}/{s}_read_classification.txt"], f"{a}/logs/03_alpine/{s}.log", [f"filter_{s}", "refs"], inputs=[f"{a}/data/{s}.fastq.gz"] + refs)
    for s in samples:
        add(f"lungo_{s}", STEPS[3], f"lungo {s}", "lungo", "lungo.sh", [s, f"{a}/data/{s}.fastq.gz", f"{a}/data/{ctrl}.fastq.gz", ctrl, f"{a}/CRISPRLungo", P["lungo"]["cleavage_pos"], P["lungo"]["window"], "{cpus}"],
            [f"{a}/CRISPRLungo/{s}/results/read_classification.txt"], f"{a}/logs/04_lungo/{s}.log", [f"filter_{s}", f"filter_{ctrl}", "refs"], inputs=[f"{a}/data/{s}.fastq.gz", f"{a}/data/{ctrl}.fastq.gz"] + refs)
    deps = [j["key"] for st in ("alpine", "lungo", "filter") for j in jobs if j["key"].startswith(st + "_")] + ["refs"]
    add("summary", STEPS[4], "summary", "summary", "summary.sh", [], [f"{a}/summary.tsv", f"{a}/summary_matrix.tsv", f"{a}/summary_classes.tsv"], f"{a}/logs/05_summary/summary.log", deps, inputs=[o for j in jobs if j["key"] in deps for o in j["outputs"]])
    check_paths(jobs, name, root)
    return jobs

def check_paths(jobs, name, root):
    base, errs = os.path.realpath(root), []
    for j in jobs:
        ok = [f"{base}/results/{name}/"] + ([f"{base}/data/raw/", f"{base}/data/meta/"] if j["shared"] else [])
        errs += [f"{os.path.relpath(p, root)} resolves to {os.path.realpath(p)}, outside the analysis results dir" for p in j["outputs"] + [j["log"]] if not os.path.realpath(p).startswith(tuple(ok))]
    if errs: raise ValueError(f"unsafe output paths ({len(errs)}): " + "; ".join(errs[:3]))

###################################### state
def is_done(job, jobs_by_key):
    if not job["outputs"] or any(size(o) == 0 for o in job["outputs"]): return False
    if not job["shared"]:
        if not os.path.isfile(job["log"]): return False
        tail = [l for l in open(job["log"], errors="replace").read().splitlines() if l.strip()][-5:]
        if not any(FOOTER.search(l) for l in tail): return False
    if job["shared"]: return True
    newest = max((mtime(o) for d in job["deps"] for o in jobs_by_key[d]["outputs"] if os.path.exists(o)), default=0)
    return all(mtime(o) >= newest for o in job["outputs"])

def todo(name, root=ROOT):
    jobs = plan(name, root); by = {j["key"]: j for j in jobs}; run = set()
    for j in jobs:
        if not is_done(j, by) or (not j["shared"] and any(d in run for d in j["deps"])): run.add(j["key"])
    return jobs, run

###################################### safety
def verify_inputs(name, root):
    inp = f"{root}/results/{name}/inputs"
    meta = json.load(open(f"{inp}/analysis.json")) if os.path.exists(f"{inp}/analysis.json") else {}
    if "checksums" not in meta: log(f"!! {name} was frozen before checksums existed: inputs cannot be verified"); return
    for rel, want in meta["checksums"].items():
        if not os.path.isfile(f"{inp}/{rel}") or analysis.sha256(f"{inp}/{rel}") != want: raise ValueError(f"frozen input {inp}/{rel} changed or is missing since the analysis was created: create a new analysis instead of editing frozen inputs")
    for p, w in meta.get("fastq", {}).items():
        st = os.stat(p) if os.path.isfile(p) else None
        if not st or st.st_size != w["size"] or st.st_mtime != w["mtime"]: raise ValueError(f"local FASTQ {p} changed size/mtime or is missing since the analysis was created: create a new analysis")

def preflight(jobs, run):
    made, errs = {o for j in jobs if j["key"] in run for o in j["outputs"]}, []
    for j in jobs:
        if j["key"] not in run: continue
        for p in j["inputs"]:
            local = j["key"].startswith("filter_") and not any(p == o for k in jobs for o in k["outputs"])
            if local and not (os.path.isabs(p) and os.path.isfile(p) and p.endswith(FASTQ_EXT)): errs.append(f"{j['key']}: {p} must be an absolute regular FASTQ file ({', '.join(FASTQ_EXT)})")
            elif p not in made and not (size(p) and os.access(p, os.R_OK)): errs.append(f"{j['key']}: missing or empty input {p}")
    if errs: raise ValueError("pre-flight failed, nothing submitted:\n  " + "\n  ".join(errs))

def live_ids(rows):
    st = slurm_states([r["jobid"] for r in rows])
    return [r for r in rows if st.get(r["jobid"]) in LIVE]

def busy(name, jobs, run, root):
    own = live_ids(read_jobs(name, root))
    if own: raise RuntimeError(f"{name} still has live jobs ({', '.join(r['jobid'] + ' ' + r['key'] for r in own)}): stop them first (--stop)")
    keys = {j["key"] for j in jobs if j["shared"] and j["key"] in run}
    others = [r for p in glob.glob(f"{root}/results/*/jobs.tsv") if os.path.basename(os.path.dirname(p)) != name for r in read_jobs(os.path.basename(os.path.dirname(p)), root) if r["key"] in keys]
    live = live_ids(others)
    if live: raise RuntimeError(f"another analysis has live shared jobs writing the same cache files: {', '.join(r['jobid'] + ' ' + r['key'] for r in live)}")

###################################### sizing
def mb(v):
    m = re.match(r"^([0-9.]+)([KMGT]?)", v or "")
    return float(m.group(1)) * {"": 1e-6, "K": 1e-3, "M": 1, "G": 1024, "T": 1048576}[m.group(2)] if m else 0.0

def to_min(v):
    d, _, t = (v or "").rpartition("-"); p = [float(x) for x in t.split(":") if x.replace(".", "").isdigit()]
    if not p: return 0.0
    while len(p) < 3: p.insert(0, 0.0)
    return (float(d) if d else 0.0) * 1440 + p[0] * 60 + p[1] + p[2] / 60

def usage(ids):
    out = {}
    for i in range(0, len(ids), 200):
        for l in sh(["sacct", "-n", "-P", "-j", ",".join(ids[i:i + 200]), "-o", "JobID,State,MaxRSS,Elapsed"]):
            f = l.split("|")
            if len(f) < 4: continue
            d = out.setdefault(f[0].split(".")[0], dict(state="", rss=0.0, minutes=0.0))
            if "." not in f[0]: d["state"] = f[1].split()[0] if f[1].strip() else ""
            d.update(rss=max(d["rss"], mb(f[2])), minutes=max(d["minutes"], to_min(f[3])))
    return out

def history(root):
    rows = [r for p in glob.glob(f"{root}/results/*/jobs.tsv") for r in read_jobs(os.path.basename(os.path.dirname(p)), root) if r.get("jobid") and r.get("mem_mb")]
    use, out = usage([r["jobid"] for r in rows]), {}
    for r in rows:
        u = use.get(r["jobid"])
        if u: out.setdefault(kind(r["key"]), []).append(dict(u, mem_mb=float(r["mem_mb"]), minutes_req=float(r.get("minutes") or 0), in_bytes=float(r.get("in_bytes") or 0)))
    return out

def size_job(j, obs):
    c, m0, t0 = RES[kind(j["key"])]
    inb = sum(size(p) for p in j["inputs"])
    ok = [o for o in obs if o["state"] == "COMPLETED" and o["rss"] > 0]
    scale = lambda o: max(1.0, inb / o["in_bytes"]) if o["in_bytes"] and inb else 1.0
    mem = SAFETY * max(o["rss"] * scale(o) for o in ok) + 512 if ok else m0
    t = 2 * max(o["minutes"] * scale(o) for o in ok) + 10 if ok else t0
    mem = max([mem] + [2 * o["mem_mb"] for o in obs if o["state"] == "OUT_OF_MEMORY"])
    t = max([t] + [2 * o["minutes_req"] for o in obs if o["state"] == "TIMEOUT"])
    j.update(cpus=c, mem_mb=int(min(MEM_MAX, max(MEM_MIN, mem))), minutes=int(min(TIME_MAX, max(TIME_MIN, t))), in_bytes=inb,
             sized=f"learned from {len(ok)} finished run(s)" if ok else "default (no finished run yet)")

def lanes(jobs):
    w = max(j["cpus"] for j in jobs); n = max(1, BUDGET_CPUS // w)
    load, tail, out = [0.0] * n, [""] * n, {}
    for j in jobs:
        k = min(range(n), key=load.__getitem__); out[j["key"]] = tail[k]; tail[k] = j["key"]; load[k] += j["minutes"]
    return n, w, out

def pick_node(jobs, n, w, root):
    big = [max(j["cpus"] for j in jobs), max(j["mem_mb"] for j in jobs)]
    tries = [(n * w, min(BUDGET_MEM_MB, sum(sorted((j["mem_mb"] for j in jobs), reverse=True)[:n]))), tuple(big)]
    for c, m in dict.fromkeys(tries):
        try: r = subprocess.run([f"{root}/src/node_pick.sh", str(c), str(m), str(max(j["minutes"] for j in jobs))], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError): continue
        out = r.stdout.split()
        if len(out) == 2: return out[0], out[1], f"asked {c} cpus {m // 1000} GB free -> {out[0]} ({out[1]}) {r.stderr.strip()}"
    return "", PARTITION, f"no node has {big[0]} cpus {big[1] // 1000} GB free now: jobs queue on {PARTITION} without a node pin"

###################################### guards
def user_live():
    return len(sh(["squeue", "-h", "-u", getpass.getuser(), "-o", "%i"]))

def tagged(name):
    return [l.split("|")[0] for l in sh(["squeue", "-h", "-u", getpass.getuser(), "-o", "%i|%k"]) if l.split("|", 1)[-1].startswith(f"kv:{name}:")]

def guard(n):
    if n > MAX_JOBS: raise ValueError(f"this launch would submit {n} jobs, above the limit of {MAX_JOBS}: split the samples into smaller analyses")
    live = user_live()
    if live + n > MAX_USER_JOBS: raise RuntimeError(f"you already have {live} jobs in the SLURM queue; {n} more would pass the limit of {MAX_USER_JOBS}: wait or stop some")

###################################### submit
def sbatch_env(root, name, img, binds, outs):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SLURM_", "SBATCH_"))}
    env.update(KV_ROOT=os.path.realpath(root), KV_ANALYSIS=name, KV_IMAGE=img, KV_BINDS=",".join(binds), KV_OUTPUTS=":".join(outs))
    return env

def submit(name, root=ROOT, dry_run=False):
    if dry_run:
        verify_inputs(name, root); jobs, run = todo(name, root); preflight(jobs, run)
        return [dict(j, state="would-run" if j["key"] in run else "done", jobid="") for j in jobs]
    d = analysis.analysis_dir(name, root); os.makedirs(f"{root}/results", exist_ok=True)
    if os.path.realpath(d) != f"{os.path.realpath(root)}/results/{name}": raise ValueError(f"{d} resolves to {os.path.realpath(d)}, outside the repo results/")
    os.makedirs(d, exist_ok=True)
    lock = open(f"{d}/.lock", "w")
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: raise RuntimeError(f"another launch of {name} is in progress")
    try: return launch(name, root)
    finally: lock.close()

def launch(name, root):
    _, _, errs = analysis.create(name, root)
    if errs: raise ValueError("; ".join(errs))
    verify_inputs(name, root)
    jobs, run = todo(name, root)
    preflight(jobs, run); busy(name, jobs, run, root)
    d, img, ids, out = f"{root}/results/{name}", image(root), {}, []
    if os.path.exists(f"{d}/.stop"): os.remove(f"{d}/.stop")
    todo_jobs = [j for j in jobs if j["key"] in run]
    if todo_jobs: guard(len(todo_jobs))
    hist = history(root) if todo_jobs else {}
    for j in todo_jobs: size_job(j, hist.get(kind(j["key"]), []))
    n, w, prev = lanes(todo_jobs) if todo_jobs else (1, 1, {})
    node, part, why = pick_node(todo_jobs, n, w, root) if todo_jobs and os.environ.get("NODE_PICK", "1") != "0" else ("", PARTITION, "node pick off")
    plog = [f"[PYTHON-INFO] {datetime.datetime.now():%F %T} launch {name}: {len(todo_jobs)} job(s) in {n} lane(s) of {w} cpus (budget {BUDGET_CPUS} cpus {BUDGET_MEM_MB // 1000} GB), {why}"] + [f"[PYTHON-INFO]   {j['key']}: {j['cpus']} cpus {j['mem_mb']} MB {j['minutes']} min ({j['sized']})" for j in todo_jobs]
    os.makedirs(f"{d}/logs", exist_ok=True); open(f"{d}/logs/node_pick.log", "a").write("\n".join(plog) + "\n")
    for l in plog[:1]: log(l.split("] ", 1)[1])
    for j in jobs:
        if j["key"] not in run: out.append(dict(j, state="done", jobid="", node="")); continue
        if os.path.exists(f"{d}/.stop"):
            if ids: subprocess.run(["scancel"] + list(ids.values()), capture_output=True)
            write_jobs(name, root, out); raise RuntimeError(f"stopped while submitting: {len(ids)} submitted job(s) cancelled")
        for p in [os.path.dirname(o) for o in j["outputs"]] + [os.path.dirname(j["log"])]: os.makedirs(p, exist_ok=True)
        dep, after = [ids[x] for x in j["deps"] if x in ids], ids.get(prev.get(j["key"], ""), "")
        when = ",".join(([f"afterok:{':'.join(dep)}"] if dep else []) + ([f"afterany:{after}"] if after and after not in dep else []))
        args = [a.format(cpus=j["cpus"], mem_mb=j["mem_mb"]) if a in ("{cpus}", "{mem_mb}") else a for a in j["args"]]
        cmd = ["sbatch", "--parsable", "-J", f"kv_{name}_{j['key']}", "-p", part] + (["-w", node] if node else []) + ["-N", "1", "-c", str(j["cpus"]), f"--mem={j['mem_mb']}", "-t", str(j["minutes"]),
            "-o", j["log"], "--kill-on-invalid-dep=yes", "--comment", f"kv:{name}:{j['key']}"] + ([f"--dependency={when}"] if when else []) + [f"{root}/src/kv_job.sh", j["script"]] + args
        r = subprocess.run(cmd, capture_output=True, text=True, env=sbatch_env(root, name, img, j["binds"], j["outputs"]))
        jid = r.stdout.strip().split(";")[0] if r.returncode == 0 else ""
        if not jid:
            if ids: subprocess.run(["scancel"] + list(ids.values()), capture_output=True)
            raise RuntimeError(f"sbatch failed for {j['key']}: {(r.stderr or r.stdout).strip()}")
        ids[j["key"]] = jid; out.append(dict(j, state="submitted", jobid=jid, node=node)); write_jobs(name, root, out)
    write_jobs(name, root, out)
    return out

def write_jobs(name, root, out):
    p = f"{root}/results/{name}/jobs.tsv"
    with open(f"{p}.tmp", "w") as f:
        f.write("\t".join(COLS) + "\n")
        for j in out: f.write("\t".join(str(j.get(c, "")) for c in COLS) + "\n")
    os.replace(f"{p}.tmp", p)

def read_jobs(name, root=ROOT):
    p = f"{root}/results/{name}/jobs.tsv"
    return list(csv.DictReader(open(p), delimiter="\t")) if os.path.exists(p) else []

def slurm_states(jobids):
    ids, st = [i for i in jobids if i], {}
    if not ids: return st
    for l in sh(["squeue", "-h", "-j", ",".join(ids), "-o", "%i|%T"]):
        i, _, s = l.partition("|"); st[i.strip()] = s.strip()
    rest = [i for i in ids if i not in st]
    for l in sh(["sacct", "-n", "-X", "-P", "-j", ",".join(rest), "-o", "JobID,State"]) if rest else []:
        i, _, s = l.partition("|"); st[i.strip()] = s.split()[0] if s.strip() else ""
    return st

def stop(name, root=ROOT):
    d = analysis.analysis_dir(name, root)
    if not os.path.isdir(d): return dict(cancelled=[], remaining=[])
    open(f"{d}/.stop", "w").close()
    lock, t = open(f"{d}/.lock", "w"), time.time()
    while True:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); break
        except OSError:
            if time.time() - t > STOP_WAIT: break
            time.sleep(0.5)
    try:
        ids = sorted({j["jobid"] for j in read_jobs(name, root) if j["jobid"]} | set(tagged(name)))
        alive = lambda xs: (lambda st: [i for i in xs if st.get(i) in LIVE])(slurm_states(xs))
        live = first = alive(ids)
        for k in range(3):
            if not live: break
            subprocess.run(["scancel"] + live, capture_output=True)
            time.sleep(STOP_PAUSE * k)
            live = alive(live)
        return dict(cancelled=sorted(set(first) - set(live)), remaining=live)
    finally:
        if os.path.exists(f"{d}/.stop"): os.remove(f"{d}/.stop")
        lock.close()

###################################### main
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("analysis_name"); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--stop", action="store_true"); ap.add_argument("--root", default=ROOT, help=argparse.SUPPRESS)
    a = ap.parse_args()
    try:
        if a.stop:
            r = stop(a.analysis_name, a.root)
            log(f"cancelled {len(r['cancelled'])} job(s)" + (f"; !! still live after 3 scancel rounds: {' '.join(r['remaining'])}" if r["remaining"] else ""))
        else:
            out = submit(a.analysis_name, a.root, a.dry_run)
            for j in out: log(f"{j['key']}: {'submitted ' + j['jobid'] if j['state'] == 'submitted' else j['state']}")
            n = lambda s: sum(j["state"] == s for j in out)
            log(f"{len(out)} jobs: {n('done')} done, {n('submitted')} submitted, {n('would-run')} would run")
    except (ValueError, RuntimeError) as e: sys.exit(f"[PYTHON-INFO] !! {e}")
    log(f"{datetime.datetime.now():%F %T} | elapsed {time.time() - T0:.1f} s | max RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576:.2f} GB")

if __name__ == "__main__":
    main()
