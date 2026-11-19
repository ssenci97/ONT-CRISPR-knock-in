#!/usr/bin/env python3
"""Serve the KNOCKIN-VAL console on localhost: submit samples, launch the pipeline, follow it and read the results."""
import argparse, datetime, fcntl, json, os, re, resource, shutil, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analysis, design, pipeline

###################################### constants
T0 = time.time()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARAM_YAML, NAME = f"{ROOT}/configs/param_configs.yaml", "gui_serve"
GUI, SCHEMA = f"{ROOT}/gui", f"{ROOT}/configs/sample_schema.json"
SAMPLES_TSV, SAMPLES_DIR = f"{ROOT}/configs/samples.tsv", f"{ROOT}/configs/samples"
EXAMPLES = f"{ROOT}/configs/examples"
STATIC = {"/": ("submit.html", "text/html"), "/submit.css": ("submit.css", "text/css"), "/submit.js": ("submit.js", "application/javascript")}
RESULTS = f"{ROOT}/results"
DEFAULT_SIF = f"{ROOT}/containers/ont-knockin-val.sif"
STEPS, LIVE = pipeline.STEPS, pipeline.LIVE
KV_BIN, PIPELINE = f"{ROOT}/.kv_bin", os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline.py")
FAILED = {"FAILED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL", "BOOT_FAIL", "DEADLINE", "PREEMPTED"}
RUNNING = {"RUNNING", "CONFIGURING", "COMPLETING"}
FASTQ_EXT = (".fastq", ".fastq.gz", ".fq", ".fq.gz")
KINDS = dict(fastq=FASTQ_EXT, fa=(".fa", ".fasta", ".fa.gz", ".fasta.gz"), xlsx=(".xlsx", ".xls"))
PARAMS = dict(host="127.0.0.1", port=8000)
LAUNCH = threading.Lock()

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

def read_yaml(p):
    try:
        import yaml; return yaml.safe_load(open(p)) or {}
    except Exception: return {}

def examples():
    out = []
    for n in sorted(os.listdir(EXAMPLES)) if os.path.isdir(EXAMPLES) else []:
        d = f"{EXAMPLES}/{n}"
        if not (os.path.exists(f"{d}/samples.tsv") and os.path.exists(f"{d}/param_configs.yaml")): continue
        m = read_yaml(f"{d}/meta.yaml")
        out.append(dict(name=n, short=n.removeprefix("example_"), title=m.get("title", n), credit=m.get("credit", ""),
                        params=read_yaml(f"{d}/param_configs.yaml"),
                        samples=[{k: v for k, v in r.items() if v} for r in tsv_rows(f"{d}/samples.tsv")]))
    return sorted(out, key=lambda e: e["short"])

def apply_example(name):
    if name not in {e["name"] for e in examples()}: return None
    if os.path.exists(PARAM_YAML): shutil.copy(PARAM_YAML, f"{PARAM_YAML}.bak")
    shutil.copy(f"{EXAMPLES}/{name}/param_configs.yaml", PARAM_YAML)
    log(f"example {name}: copied its param_configs.yaml over {os.path.relpath(PARAM_YAML, ROOT)} (previous kept as .bak)")
    return os.path.relpath(PARAM_YAML, ROOT)

def analyses():
    out = []
    for n in sorted(os.listdir(RESULTS)) if os.path.isdir(RESULTS) else []:
        p = f"{RESULTS}/{n}/inputs/analysis.json"
        if os.path.exists(p):
            try: d = json.load(open(p))
            except ValueError: continue
            st = json.load(open(run_state(n))) if os.path.exists(run_state(n)) else {}
            out.append(dict(name=n, created_at=d.get("created_at"), samples=d.get("samples", []),
                            started_at=st.get("started_at"), done=os.path.exists(f"{RESULTS}/{n}/summary_matrix.tsv"), group=st.get("group")))
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

def preflight(need_sheet):
    for a in analyses():
        if live_rows(a["name"]): return f"analysis {a['name']} is still running"
    if need_sheet and not os.path.exists(SAMPLES_TSV): return "no configs/samples.tsv -- submit samples first"
    rt = runtime()
    if not rt["sbatch"]: return "sbatch not found: start the console on the cluster login node"
    if not rt["apptainer"]: return "singularity not on PATH (module load singularity before starting the console)"
    return None

def launch(name, src=None, group=None, profile="savemem", nodes=()):
    rt = runtime()
    try: a_dir, new, errs = analysis.create(name, ROOT, src)
    except ValueError as e: return None, str(e)
    if errs: return None, errs
    cmd = ["python3", PIPELINE, name, "--root", ROOT, "--profile", profile] + (["--nodes", ",".join(nodes)] if nodes else [])
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
              submitted=sum(bool(r["jobid"]) for r in pipeline.read_jobs(name, ROOT)), node=next((r.get("node") for r in pipeline.read_jobs(name, ROOT) if r.get("node")), ""))
    if src: st["source"] = os.path.relpath(src, ROOT)
    if group: st["group"] = group
    st.update(profile=profile, nodes=sorted({r["node"] for r in pipeline.read_jobs(name, ROOT) if r.get("node")}))
    json.dump(st, open(run_state(name), "w"), indent=2)
    log(f"{'started' if new else 'resumed'} analysis {name}, {st['submitted']} job(s) submitted ({st['mode']})" + (f" from {st['source']}" if src else ""))
    return st, None

def check_profile(profile, nodes):
    if profile not in pipeline.PROFILES: return f"unknown agency profile {profile!r}"
    if any(not pipeline.NODE_RE.match(n) for n in nodes): return "invalid node name"
    if profile == "custom" and not 1 <= len(nodes) <= pipeline.PROFILES["custom"]: return f"Custom: tick 1 to {pipeline.PROFILES['custom']} nodes"
    if profile != "custom" and nodes: return f"{profile} picks its nodes itself; nodes are only for Custom"
    return None

def start_run(name, wanted=(), profile="savemem", nodes=()):
    err = check_profile(profile, nodes)
    if err: return None, err
    if not LAUNCH.acquire(blocking=False): return None, "a launch is already in progress: wait for it to finish"
    try: return start_locked(name, wanted, profile, list(nodes))
    finally: LAUNCH.release()

def start_locked(name, wanted, profile="savemem", nodes=()):
    if not wanted:
        err = preflight(True)
        return (None, err) if err else launch(name, profile=profile, nodes=nodes)
    known = {e["name"]: e for e in examples()}
    bad = [w for w in wanted if w not in known]
    if bad: return None, [f"unknown example {w}" for w in bad]
    if not analysis.NAME_RE.match(name or ""): return None, f"analysis name {name!r}: use letters, digits, _ . - (max 64)"
    err = preflight(False)
    if err: return None, err
    started, errors = [], {}
    for w in wanted:
        n = f"{name}_{known[w]['short']}"
        st, e = launch(n, f"{EXAMPLES}/{w}", name, profile, nodes)
        if st: started.append(st)
        else: errors[n] = e if isinstance(e, list) else [e]
    if not started: return None, [f"{n}: {m}" for n, ms in errors.items() for m in ms]
    return dict(analysis=started[0]["analysis"], group=name, members=[s["analysis"] for s in started], started=started, errors=errors), None

def stop_run(name):
    try: r = pipeline.stop(name, ROOT)
    except ValueError: return dict(stopped=False, cancelled=[], remaining=[])
    log(f"analysis {name}: cancelled {len(r['cancelled'])} job(s)" + (f", !! still live: {' '.join(r['remaining'])}" if r["remaining"] else ""))
    return dict(r, stopped=bool(r["cancelled"]))

def stop_all():
    out = {a["name"]: stop_run(a["name"]) for a in analyses()}
    return {n: r for n, r in out.items() if r["cancelled"] or r["remaining"]}

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

def members(name):
    al = analyses(); g = next((a["group"] for a in al if a["name"] == name), None)
    return [a for a in al if g and a["group"] == g]

def member_state(name):
    rows, sl = job_states(name); live = any(sl.get(r["jobid"]) in LIVE for r in rows); steps = step_state(name, rows, sl)
    return dict(name=name, outcome=outcome(name, live, steps, rows), progress=progress(steps), running=live)

def status(name):
    st = read_state(name) if name else {}
    rows, sl = job_states(name) if name else ([], {})
    live = [r for r in rows if sl.get(r["jobid"]) in LIVE]
    steps = step_state(name, rows, sl) if name else []
    return dict(runtime=runtime(), analyses=analyses(), analysis=name, state=st, running=bool(live), outcome=outcome(name, bool(live), steps, rows) if name else "idle",
                progress=progress(steps), queue=queue(live), steps=steps,
                node_log=tail(f"{RESULTS}/{name}/logs/node_pick.log", 20) if name else "", log=tail(run_log(name)) if name else "",
                group=[dict(member_state(a["name"]), group=a["group"]) for a in members(name)] if name else [])

###################################### performance
NODE_FMT = "NodeList:40,Partition:24,StateCompact:12,CPUsState:24,Memory:14,AllocMem:14,CPUsLoad:10"
PERF_FIELDS = "JobID,State,Elapsed,TotalCPU,MaxRSS,AllocCPUS,ReqMem,Submit,Start,End,NodeList"

def num(v, cast=float):
    try: return cast(v)
    except (TypeError, ValueError): return None

def when(v):
    try: return datetime.datetime.fromisoformat(v)
    except (TypeError, ValueError): return None

def ours_running():
    """Our RUNNING jobs from squeue, with the cores and memory each holds on its node."""
    rows = {r["jobid"]: dict(r, analysis=a["name"]) for a in analyses() for r in pipeline.read_jobs(a["name"], ROOT) if r.get("jobid")}
    ids, out = list(rows), []
    for i in range(0, len(ids), 200):
        for l in pipeline.sh(["squeue", "-h", "-j", ",".join(ids[i:i + 200]), "-o", "%i|%T|%P|%N|%C|%m"]):
            f = [x.strip() for x in l.split("|")]
            if len(f) < 6 or f[1] != "RUNNING" or f[0] not in rows: continue
            out.append(dict(jobid=f[0], analysis=rows[f[0]]["analysis"], key=rows[f[0]]["key"], partition=f[2].rstrip("*"), node=f[3], cpus=num(f[4], int) or 0, mem_mb=round(pipeline.mb(f[5]))))
    return out

def cluster():
    nodes = {}
    for l in pipeline.sh(["sinfo", "-N", "-h", "-O", NODE_FMT]):
        f = l.split()
        if len(f) < 6 or f[3].count("/") != 3: continue
        a, i, o, t = (num(x, int) or 0 for x in f[3].split("/"))
        n = nodes.setdefault(f[0], dict(node=f[0], partitions=[], state=f[2], cpus=t, alloc=a, idle=i, other=o, mem_mb=num(f[4], int) or 0, alloc_mb=int(num(f[5]) or 0), load=num(f[6]) if len(f) > 6 else None))
        if f[1].rstrip("*") not in n["partitions"]: n["partitions"].append(f[1].rstrip("*"))
    mine = ours_running()
    for n in nodes.values():
        here = [j for j in mine if j["node"] == n["node"]]
        n.update(ours_cpus=sum(j["cpus"] for j in here), ours_mb=sum(j["mem_mb"] for j in here), ours_jobs=[f"{j['analysis']}:{j['key']}" for j in here])
        n["fits_budget"] = n["state"].rstrip("*~#!%$@^-") in ("idle", "mix", "mixed") and n["idle"] >= pipeline.BUDGET_CPUS and n["mem_mb"] - n["alloc_mb"] >= pipeline.BUDGET_MEM_MB
    q = {}
    for l in pipeline.sh(["squeue", "-h", "-o", "%P|%T|%C"]):
        p, _, rest = l.partition("|"); st, _, c = rest.partition("|")
        d = q.setdefault(p.rstrip("*"), dict(running=0, pending=0, pending_cpus=0))
        if st == "RUNNING": d["running"] += 1
        elif st == "PENDING": d["pending"] += 1; d["pending_cpus"] += num(c, int) or 0
    parts = {}
    for n in nodes.values():
        for p in n["partitions"]:
            d = parts.setdefault(p, dict(partition=p, nodes=0, states={}, cpus=0, alloc=0, mem_mb=0, alloc_mb=0, fit=0, ours_cpus=0, ours_mb=0, ours_jobs=0))
            st = n["state"].rstrip("*~#!%$@^-")
            d["nodes"] += 1; d["states"][st] = d["states"].get(st, 0) + 1; d["fit"] += n["fits_budget"]
            for k in ("cpus", "alloc", "mem_mb", "alloc_mb"): d[k] += n[k]
    for p, d in parts.items(): d.update(q.get(p, dict(running=0, pending=0, pending_cpus=0)))
    for j in mine:
        d = parts.get(j["partition"])
        if d: d["ours_cpus"] += j["cpus"]; d["ours_mb"] += j["mem_mb"]; d["ours_jobs"] += 1
    return dict(nodes=sorted(nodes.values(), key=lambda n: (n["partitions"][0], n["node"])), partitions=sorted(parts.values(), key=lambda d: d["partition"]),
                budget=dict(cpus=pipeline.BUDGET_CPUS, mem_mb=pipeline.BUDGET_MEM_MB), available=bool(nodes),
                ours=dict(jobs=len(mine), cpus=sum(j["cpus"] for j in mine), mem_mb=sum(j["mem_mb"] for j in mine), nodes=sorted({j["node"] for j in mine}), analyses=sorted({j["analysis"] for j in mine})))

def job_perf():
    rows = [dict(r, analysis=a["name"]) for a in analyses() for r in pipeline.read_jobs(a["name"], ROOT) if r.get("jobid")]
    acct, ids = {}, [r["jobid"] for r in rows]
    for i in range(0, len(ids), 200):
        for l in pipeline.sh(["sacct", "-n", "-P", "-j", ",".join(ids[i:i + 200]), "-o", PERF_FIELDS]):
            f = l.split("|")
            if len(f) < 11: continue
            d = acct.setdefault(f[0].split(".")[0], dict(rss=0.0, cpu=0.0, elapsed=0.0))
            if "." not in f[0]: d.update(state=f[1].split()[0] if f[1].strip() else "", cpus=num(f[5], int), req=pipeline.mb(f[6]), submit=when(f[7]), start=when(f[8]), end=when(f[9]), node=f[10])
            d.update(rss=max(d["rss"], pipeline.mb(f[4])), cpu=max(d["cpu"], pipeline.to_min(f[3])), elapsed=max(d["elapsed"], pipeline.to_min(f[2])))
    jobs = []
    for r in rows:
        a = acct.get(r["jobid"])
        if not a or "state" not in a: continue
        a["rss"] = max(a["rss"], pipeline.log_usage(r.get("log"))[0])
        cpus, req = a["cpus"] or num(r.get("cpus"), int) or 1, num(r.get("mem_mb")) or a["req"] or 0
        el, rq_min = a["elapsed"], num(r.get("minutes"))
        jobs.append(dict(analysis=r["analysis"], key=r["key"], tool=pipeline.kind(r["key"]), jobid=r["jobid"], state=a["state"], node=a["node"] if a["node"] not in ("None assigned", "") else "",
                         cpus=cpus, req_mb=round(req), used_mb=round(a["rss"]), mem_eff=round(100 * a["rss"] / req, 1) if req and a["rss"] else None,
                         elapsed_min=round(el, 1), req_min=rq_min, time_eff=round(100 * el / rq_min, 1) if rq_min and el else None,
                         cpu_eff=round(100 * a["cpu"] / (el * cpus), 1) if el and a["cpu"] and a["state"] not in LIVE else None,
                         wait_min=round((a["start"] - a["submit"]).total_seconds() / 60, 1) if a["start"] and a["submit"] else None,
                         core_h=round(el * cpus / 60, 2), start=f"{a['start']:%F %T}" if a["start"] else "", end=f"{a['end']:%F %T}" if a["end"] else ""))
    med = lambda xs: (sorted(xs)[len(xs) // 2] if xs else None)
    def agg(group):
        out = {}
        for j in jobs: out.setdefault(j[group], []).append(j)
        return [dict(name=k, n=len(v), completed=sum(j["state"] == "COMPLETED" for j in v), failed=sum(j["state"] in FAILED - {"OUT_OF_MEMORY", "TIMEOUT"} for j in v),
                     oom=sum(j["state"] == "OUT_OF_MEMORY" for j in v), timeout=sum(j["state"] == "TIMEOUT" for j in v),
                     cpu_eff=med([j["cpu_eff"] for j in v if j["cpu_eff"] is not None]), mem_eff=med([j["mem_eff"] for j in v if j["mem_eff"] is not None]),
                     max_used_mb=max((j["used_mb"] for j in v), default=0), elapsed_min=med([j["elapsed_min"] for j in v if j["elapsed_min"]]),
                     wait_min=med([j["wait_min"] for j in v if j["wait_min"] is not None]), core_h=round(sum(j["core_h"] for j in v), 2),
                     first=min((j["start"] for j in v if j["start"]), default=""), last=max((j["end"] for j in v if j["end"]), default=""), nodes=sorted({j["node"] for j in v if j["node"]}))
                for k, v in sorted(out.items())]
    return dict(jobs=jobs, tools=agg("tool"), analyses=agg("analysis"))

def perf():
    for a in analyses():
        try: pipeline.fill_perf(a["name"], ROOT)
        except (OSError, ValueError) as e: log(f"!! perf metadata of {a['name']} not refreshed: {e}")
    return dict(at=f"{datetime.datetime.now():%F %T}", cluster=cluster(), runs=job_perf())

def params(): return read_yaml(PARAM_YAML)

###################################### design
PARAMS_LOCK = threading.Lock()
REGION_RE = re.compile(r"^([A-Za-z0-9_.]+):([0-9]+)\.\.([0-9]+):(1|-1)$")
SEQ_RE = re.compile(r"^[ACGT]+$")
ENSEMBL = "https://rest.ensembl.org/sequence/region/human"
RAW_REFS = f"{ROOT}/data/raw_refs"
PINS = f"{ROOT}/configs/refs.sha256"
MAX_SPAN = 1000000
MINUS = "−"
WINDOW = {}

def design_fields(): return {f["key"]: f for g in json.load(open(SCHEMA)).get("design", []) for f in g["fields"]}

def window_of(region):
    m = REGION_RE.match(str(region or ""))
    if not m: return None
    c, s, e, _ = m.groups()
    return dict(chrom=c, start=int(s), end=int(e), path=f"data/raw_refs/hg38_chr{c}_{s}_{e}.fa")

def cast(f, v):
    if f["type"] != "number": return str(v).strip().upper() if f.get("seq") else str(v).strip()
    if str(v).strip() == "": raise ValueError("empty")
    return float(v) if f.get("step") else int(v)

def merge(d):
    c = read_yaml(PARAM_YAML)
    for k, v in d.items():
        sec, key = k.split(".", 1); c.setdefault(sec, {})[key] = v
    return c

def repo_path(p): return p if os.path.isabs(p) else f"{ROOT}/{p}"

def check_design(v):
    fs, errs = design_fields(), []
    for k, x in v.items():
        f = fs[k]
        if f.get("seq") and x and not SEQ_RE.match(x): errs.append(f"{f['label']}: only A, C, G and T are allowed")
        if f.get("pattern") and x and not f.get("seq") and not re.match(f["pattern"], str(x)): errs.append(f"{f['label']}: {x!r} does not look like {f.get('help') or 'a valid value'}")
        if f["type"] == "number" and f.get("min") is not None and x < f["min"]: errs.append(f"{f['label']}: {x} is below {f['min']}")
        if f["type"] == "number" and f.get("max") is not None and x > f["max"]: errs.append(f"{f['label']}: {x} is above {f['max']}")
        if f.get("path") and x and (os.path.isabs(x) or ".." in x.split("/")): errs.append(f"{f['label']}: give a path inside the repo, without '..'")
    c = merge(v)
    for k, f in fs.items():
        sec, key = k.split(".", 1)
        if f.get("required") and not str(c.get(sec, {}).get(key) or "").strip(): errs.append(f"{f['label']}: required")
    r = window_of(c.get("refs", {}).get("region"))
    if not r:
        if not any(e.startswith("hg38 window:") for e in errs): errs.append("hg38 window: use the form 14:22540000..22560000:1")
    elif r["end"] <= r["start"]: errs.append("hg38 window: the end must be greater than the start")
    elif r["end"] - r["start"] > MAX_SPAN: errs.append(f"hg38 window: at most {MAX_SPAN:,} bp")
    fe, br = c.get("fetch", {}), c.get("build_refs", {})
    if fe.get("min_len") is not None and fe.get("max_len") is not None and fe["max_len"] <= fe["min_len"]: errs.append("read lengths: the longest must be greater than the shortest")
    ki = c.get("shared", {}).get("ki_min_insert_frac")
    if ki is not None and not 0 < ki <= 1 and not any(e.startswith("Minimum insert fraction") for e in errs): errs.append("minimum insert fraction: give a number above 0 and at most 1")
    if bool(br.get("donor_ki_fasta")) == bool(br.get("templates_xlsx")): errs.append("donor: give either a donor FASTA or a supplementary table, not both and not neither")
    bp = fe.get("bioproject")
    if bp and not pipeline.BP_RE.match(str(bp)): errs.append(f"BioProject: {bp!r} is not an accession")
    return errs

def write_params(d):
    try: import yaml
    except ImportError: return None, ["PyYAML is not installed on this host, so the design cannot be saved"]
    fs, vals, errs = design_fields(), {}, []
    for k, v in d.items():
        if k not in fs: errs.append(f"unknown parameter {k}"); continue
        try: vals[k] = cast(fs[k], v)
        except ValueError: errs.append(f"{fs[k]['label']}: {v!r} is not a number")
    errs = errs or check_design(vals)
    if errs: return None, errs
    r = window_of(merge(vals)["refs"]["region"])
    vals["build_refs.genomic_fasta"], vals["build_refs.genomic_start_1based"] = r["path"], r["start"]
    with PARAMS_LOCK:
        c = merge(vals)
        if os.path.exists(PARAM_YAML): shutil.copy(PARAM_YAML, f"{PARAM_YAML}.bak")
        yaml.safe_dump(c, open(f"{PARAM_YAML}.tmp", "w"), sort_keys=False, width=1 << 20)
        os.replace(f"{PARAM_YAML}.tmp", PARAM_YAML)
    log(f"design written to {os.path.relpath(PARAM_YAML, ROOT)} ({len(vals)} keys, previous kept as .bak)")
    return c, None

def window_text(path):
    full = repo_path(path)
    if not (os.path.isfile(full) and os.path.getsize(full)): return None, None
    st = os.stat(full); key = (full, st.st_mtime_ns, st.st_size)
    if WINDOW.get("key") != key: WINDOW.clear(); WINDOW.update(key=key, data=design.read_fasta(full))
    return WINDOW["data"]

def hit(hay, seq, rev=False):
    nd = design.rc(seq) if rev else seq
    i = hay.find(nd)
    if i >= 0: return i, 0
    try: return design.best_hit(hay, nd)
    except ValueError: return None, None

def pinned(path):
    for l in open(PINS) if os.path.exists(PINS) else []:
        f = l.split()
        if len(f) == 2 and f[1] == path: return f[0]
    return None

def round100(x): return int(round(x / 100.0) * 100)

def guide_state(out, wt, gd, off):
    try:
        gp, strand = design.guide_hit(wt, gd)
    except ValueError:
        (i, mm), (j, mm2) = hit(wt, gd), hit(wt, gd, True)
        best = min([(mm, i, "+"), (mm2, j, MINUS)], key=lambda x: (x[0] is None, x[0]))
        tail = f"; the closest match is at {best[1]:,} on {best[2]} with {best[0]} mismatch(es)" if best[0] is not None else ""
        out["fields"]["build_refs.guide"] = dict(state="err", msg="not in the amplicon" + tail)
        return None, None
    cut = design.cut_site(gp, len(gd), off if off is not None else 0, strand)
    shown = "+" if strand == "+" else MINUS
    out["fields"]["build_refs.guide"] = dict(state="ok", pos=gp, strand=strand, msg=f"found on the {shown} strand at {gp:,} of the amplicon; cut after {cut:,}")
    return gp, cut

def detect(d):
    fs, vals = design_fields(), {}
    for k, v in d.items():
        if k in fs:
            try: vals[k] = cast(fs[k], v)
            except ValueError: pass
    c = merge(vals)
    br, out = c.get("build_refs", {}), dict(fields={}, derived={}, suggest={}, warnings=[], errors=[], window={})
    say = lambda k, st, m, **kw: out["fields"].__setitem__(k, dict(state=st, msg=m, **kw))
    off, cp = br.get("cut_offset_from_guide_5p"), c.get("lungo", {}).get("cleavage_pos")
    if off is not None and cp is not None and off != cp + 1:
        say("lungo.cleavage_pos", "warn", f"usually one less than the cut offset ({off}), so {off - 1}")
    r = window_of(c.get("refs", {}).get("region"))
    if not r:
        say("refs.region", "err", "use the form 14:22540000..22560000:1")
        return out
    head, g = window_text(r["path"])
    out["window"] = dict(path=r["path"], cached=bool(g), bp=len(g or ""), region=f"{r['chrom']}:{r['start']}..{r['end']}:1", pinned=bool(pinned(r["path"])))
    out["suggest"].update({"build_refs.genomic_fasta": r["path"], "build_refs.genomic_start_1based": r["start"]})
    if not g:
        say("refs.region", "unknown", f"{r['path']} is not downloaded yet")
        return out
    ok_head = f"{r['chrom']}:{r['start']}:{r['end']}" in str(head or "").replace("GRCh38:", "")
    say("refs.region", "ok" if ok_head else "warn", f"{len(g):,} bp cached" if ok_head else f"the cached file says {head!r}, which is not this window: delete it and fetch it again")
    pf, pr, wt = str(br.get("primer_f_specific") or ""), str(br.get("primer_r_specific") or ""), None
    for k, seq, rev in (("build_refs.primer_f_specific", pf, False), ("build_refs.primer_r_specific", pr, True)):
        if not seq: say(k, "err", "required: it sets one end of the amplicon"); continue
        if not SEQ_RE.match(seq): say(k, "err", "only A, C, G and T are allowed"); continue
        i, mm = hit(g, seq, rev)
        if i is None: say(k, "err", "could not be searched in this window")
        elif mm: say(k, "err", f"not found; the closest match is at {i:,} with {mm} mismatch(es)", pos=i, mismatches=mm)
        else: say(k, "ok", f"found at {i:,} (hg38 {r['start'] + i:,})" + (", as reverse complement" if rev else ""), pos=i, mismatches=0)
    if all(out["fields"].get(k, {}).get("state") == "ok" for k in ("build_refs.primer_f_specific", "build_refs.primer_r_specific")):
        fi, ri = g.find(pf), g.find(design.rc(pr))
        if ri <= fi: out["errors"].append("the reverse primer lies before the forward primer in the window")
        else: _, _, wt = design.amplicon(g, pf, pr)
    gd, gp, cut = str(br.get("guide") or ""), None, None
    if not gd: say("build_refs.guide", "err", "required")
    elif not SEQ_RE.match(gd): say("build_refs.guide", "err", "only A, C, G and T are allowed")
    elif wt: gp, cut = guide_state(out, wt, gd, off)
    donor = tbl = None
    dk, tx, tt = str(br.get("donor_ki_fasta") or ""), str(br.get("templates_xlsx") or ""), str(br.get("template_title") or "")
    if dk and tx: out["errors"].append("give either a donor FASTA or a supplementary table, not both")
    if dk:
        if not os.path.isfile(repo_path(dk)): say("build_refs.donor_ki_fasta", "err", "no such file")
        else:
            donor = design.read_seq(repo_path(dk)); say("build_refs.donor_ki_fasta", "ok", f"{len(donor):,} bp donor allele")
    elif tx:
        if not os.path.isfile(repo_path(tx)): say("build_refs.templates_xlsx", "err", "no such file")
        else:
            try:
                ts = design.templates(repo_path(tx))
                say("build_refs.templates_xlsx", "ok", f"{len(ts)} template(s) in the table")
                if tt in ts:
                    tbl = ts[tt]; say("build_refs.template_title", "ok", f"full {len(tbl.get('full', '')):,} bp, arms {len(tbl.get('LHA', ''))}/{len(tbl.get('RHA', ''))} bp")
                else: say("build_refs.template_title", "err", "not a title in this table" + (f"; it holds {', '.join(list(ts)[:2])}" if ts else ""))
            except ImportError: say("build_refs.templates_xlsx", "unknown", "openpyxl is not installed here, so the table cannot be read; 02_refs reads it in the container (pip install --user openpyxl to check it now)")
            except (KeyError, OSError, ValueError) as e: say("build_refs.templates_xlsx", "err", f"cannot be read: {e}")
    if wt:
        s0 = r["start"] + g.find(pf)
        out["derived"].update(wt_len=len(wt), hg38=f"chr{r['chrom']}:{s0:,}-{s0 + len(wt) - 1:,}", guide_strand=None if gp is None else out["fields"]["build_refs.guide"].get("strand"), cut_site_0b=cut)
    if wt and (donor is not None or tbl):
        try:
            a = design.arms_donor(wt, donor, int(br.get("flank_bp") or 500)) if donor is not None else design.arms_table(wt, tbl)
            out["derived"].update(lha_len=len(a["t"]["LHA"]), rha_len=len(a["t"]["RHA"]), lha_mismatches=a["lmm"], rha_mismatches=a["rmm"],
                                  insert_len=len(a["ins"]), ki_len=len(a["ki"]), deleted_wt_bp=a["rp"] - a["s"])
            lo, hi = min(len(wt), len(a["ki"])), max(len(wt), len(a["ki"]))
            out["suggest"].update({"fetch.min_len": round100(0.8 * lo), "fetch.max_len": round100(1.2 * hi)})
            if a["lmm"] or a["rmm"]: out["warnings"].append(f"the homology arms do not match the window exactly ({a['lmm']}/{a['rmm']} mismatches), which is expected for PAM-blocking arms")
            if cut is not None and donor is not None and abs(a["s"] - cut) > 10: out["warnings"].append(f"the donor's left edge is {abs(a['s'] - cut):,} bp from the predicted cut: check the guide and the cut offset")
        except ValueError as e: out["errors"].append(str(e))
    return out

def fetch_window(region):
    r = window_of(region)
    if not r: return None, "hg38 window: use the form 14:22540000..22560000:1"
    full = repo_path(r["path"]); os.makedirs(os.path.dirname(full), exist_ok=True)
    fd = os.open(f"{RAW_REFS}/.lock", os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if os.path.isfile(full) and os.path.getsize(full): return dict(path=r["path"], cached=True, fetched=False), None
        url = f"{ENSEMBL}/{r['chrom']}:{r['start']}..{r['end']}:1?content-type=text/x-fasta"
        p = subprocess.run(["curl", "-sSf", "--max-time", "180", "-o", f"{full}.tmp", url], capture_output=True, text=True)
        if p.returncode:
            if os.path.exists(f"{full}.tmp"): os.remove(f"{full}.tmp")
            return None, f"Ensembl: {(p.stderr or 'download failed').strip()[-200:]}"
        got, want = analysis.sha256(f"{full}.tmp"), pinned(r["path"])
        if want and want != got:
            os.remove(f"{full}.tmp")
            return None, f"the download does not match configs/refs.sha256 ({got[:12]} vs {want[:12]}), so 02_refs would refuse it"
        os.replace(f"{full}.tmp", full)
    except OSError as e: return None, f"could not write {r['path']}: {e}"
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)
    log(f"fetched {r['path']} from Ensembl ({os.path.getsize(full)} bytes)")
    return dict(path=r["path"], cached=True, fetched=True, bp=len(window_text(r["path"])[1] or "")), None

def nodes():
    keep = ("node", "partitions", "state", "cpus", "idle", "mem_mb", "free_mb", "half_cpus", "half_mb", "usable")
    t = pipeline.node_table()
    return dict(nodes=[{k: n[k] for k in keep} for n in t if n["usable"]], max=pipeline.PROFILES["custom"], fraction=pipeline.NODE_FRACTION, available=bool(t))

def path_info(p, kind=""):
    ext, raw = KINDS.get(kind or "fastq", FASTQ_EXT), p or ""
    p = os.path.expanduser(raw)
    rel = bool(raw) and not os.path.isabs(p)
    if rel: p = f"{ROOT}/{p}"
    if not p: p = os.path.expanduser("~") + "/"
    show = (lambda f: os.path.relpath(f, ROOT)) if rel else (lambda f: f)
    out = dict(path=p, exists=os.path.exists(p), file=os.path.isfile(p), size=os.path.getsize(p) if os.path.isfile(p) else None, entries=[])
    d = p if p.endswith("/") else os.path.dirname(p)
    try:
        for e in sorted(os.scandir(d), key=lambda e: e.name)[:500]:
            if e.name.startswith("."): continue
            if e.is_dir(): out["entries"].append(show(os.path.join(d, e.name)) + "/")
            elif e.name.endswith(ext): out["entries"].append(show(os.path.join(d, e.name)))
    except OSError: pass
    return out

def results(name):
    out = dict(matrix=None, rows=[], classes=None, reads={}, meta={}, analysis_meta=None, group=[])
    if not name: return out
    out["group"] = [dict(name=a["name"], done=a["done"], group=a["group"]) for a in members(name)]
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
                try: j = json.load(open(f"{d}/{f}"))
                except ValueError: continue
                if f == "_analysis.json": out["analysis_meta"] = j
                else: out["meta"][f[:-5]] = j
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
        elif path == "/api/perf": self.send_json(200, perf())
        elif path == "/api/nodes": self.send_json(200, nodes())
        elif path == "/api/examples": self.send_json(200, dict(examples=examples()))
        elif path == "/api/path": self.send_json(200, path_info(self.query("p"), self.query("kind")))
        else: self.send_json(404, dict(error="not found"))
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/api/samples":
            errs = validate(body.get("samples", []))
            if errs: return self.send_json(400, dict(errors=errs))
            ex = (body.get("example") or "").strip()
            if ex and ex not in {e["name"] for e in examples()}: return self.send_json(400, dict(errors=[f"unknown example {ex}"]))
            out = save(body["samples"])
            return self.send_json(200, dict(out, params_yaml=apply_example(ex) if ex else None))
        if self.path == "/api/run":
            st, err = start_run((body.get("analysis") or "").strip(), [str(x) for x in body.get("examples") or []], str(body.get("profile") or "savemem"), [str(x) for x in body.get("nodes") or []])
            if err: return self.send_json(400, dict(errors=err if isinstance(err, list) else [err]))
            return self.send_json(200, st)
        if self.path == "/api/params":
            c, errs = write_params(body.get("design") or {})
            if errs: return self.send_json(400, dict(errors=errs))
            return self.send_json(200, dict(params=c, saved=os.path.relpath(PARAM_YAML, ROOT)))
        if self.path == "/api/detect": return self.send_json(200, detect(body.get("design") or {}))
        if self.path == "/api/fetch_window":
            w, err = fetch_window((body.get("region") or "").strip())
            if err: return self.send_json(400, dict(errors=[err]))
            return self.send_json(200, w)
        if self.path == "/api/stop": return self.send_json(200, stop_run((body.get("analysis") or "").strip()))
        if self.path == "/api/stop_all": return self.send_json(200, dict(analyses=stop_all()))
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
