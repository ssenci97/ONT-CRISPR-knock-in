#!/usr/bin/env python3
"""Single writer of run metadata in results/<analysis>/meta/: per-sample <sample_id>.json and analysis-level _analysis.json, step records and their perf records."""
import datetime, fcntl, json, os, socket, subprocess, sys

###################################### constants
ROOT = os.environ.get("KV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get("KV_OUT") or f"{ROOT}/results/default"
META_DIR = f"{OUT}/meta"
SUBMITTED_DIR = f"{OUT}/inputs/samples"
ANALYSIS = "_analysis"
PERF = dict(jobid=None, node=None, partition=None, asked=None, used=None, started=None, ended=None, sacct=None)

###################################### helpers
def scalar(v):
    try: return json.loads(v)
    except ValueError: return v

def git_sha():
    try: return subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or None
    except OSError: return None

def tool_commits():
    tools = os.environ.get("TOOLS", f"{ROOT}/tools")
    out = {}
    for name in ("ALPINE", "CRISPRLungo"):
        d = f"{tools}/{name}"
        if not os.path.isdir(f"{d}/.git"): continue
        r = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True)
        if r.returncode == 0: out[name] = r.stdout.strip()
    return out

def environment():
    e = {k.lower(): os.environ[k] for k in ("KV_SIF", "KV_IMAGE") if os.environ.get(k)}
    e["containerized"] = bool(os.environ.get("APPTAINER_CONTAINER") or os.environ.get("SINGULARITY_CONTAINER") or os.path.isdir("/.singularity.d"))
    e["tools"] = tool_commits()
    return e

def submitted(sample_id, out=OUT):
    p = f"{out}/inputs/samples/{sample_id}.json"
    return json.load(open(p)) if os.path.exists(p) else {}

def new_doc(target, out):
    return {"analysis": os.path.basename(out), "steps": {}} if target == ANALYSIS else {"sample_id": target, "submitted": submitted(target, out), "steps": {}}

def write(meta_dir, target, change, out=OUT):
    """Locked read-modify-write of meta_dir/<target>.json with an atomic replace."""
    os.makedirs(meta_dir, exist_ok=True); p = f"{meta_dir}/{target}.json"
    with open(f"{p}.lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        d = json.load(open(p)) if os.path.exists(p) else new_doc(target, out)
        d.setdefault("steps", {}); change(d)
        json.dump(d, open(f"{p}.tmp", "w"), indent=2, sort_keys=False)
        os.replace(f"{p}.tmp", p)

def update_perf(meta_dir, target, step, patch, out=OUT):
    """Merge patch into steps.<step>.perf; a record of an older job id is replaced, not merged."""
    def change(d):
        s = d["steps"].setdefault(step, {}); old = s.get("perf") or {}
        if old.get("jobid") and patch.get("jobid") and str(old["jobid"]) != str(patch["jobid"]): old = {}
        s["perf"] = {**PERF, **old, **patch}
    write(meta_dir, target, change, out)

def cgroup_peak_gb():
    try: rel = next(l.split(":", 2)[2].strip() for l in open("/proc/self/cgroup") if l.startswith("0::"))
    except (OSError, StopIteration): rel = ""
    for f in (f"/sys/fs/cgroup{rel}/memory.peak", "/sys/fs/cgroup/memory.peak", "/sys/fs/cgroup/memory/memory.max_usage_in_bytes"):
        try: return round(int(open(f).read().strip()) / 1073741824, 2)
        except (OSError, ValueError): continue
    return None

def job_perf(kv):
    """The perf record kv_job.sh writes when a job ends: what was asked and what was used."""
    ask = scalar(os.environ.get("KV_ASK", "null"))
    used = dict(in_bytes=int(os.environ.get("KV_IN_BYTES") or 0), elapsed_s=kv.get("elapsed_s"), max_rss_gb=cgroup_peak_gb(), exit=kv.get("exit"))
    return dict(jobid=os.environ.get("SLURM_JOB_ID"), node=socket.gethostname(), partition=os.environ.get("SLURM_JOB_PARTITION"),
                asked=ask if isinstance(ask, dict) else None, used=used, started=kv.get("started"), ended=kv.get("ended"))

###################################### main
def main():
    if sys.argv[1:2] == ["--perf"]:
        target, step, *kv = sys.argv[2:]
        update_perf(META_DIR, target, step, job_perf({k: scalar(v) for k, v in (x.split("=", 1) for x in kv)}))
        return
    sample_id, step, *kv = sys.argv[1:]
    def change(d):
        d["submitted"] = d.get("submitted") or submitted(sample_id)
        d["pipeline_commit"] = git_sha()
        d["environment"] = environment()
        rec = {k: scalar(v) for k, v in (x.split("=", 1) for x in kv)}
        rec["recorded_at"] = f"{datetime.datetime.now():%F %T}"
        for v in ("SLURM_JOB_ID", "SLURM_ARRAY_TASK_ID"):
            if os.environ.get(v): rec[v.lower()] = os.environ[v]
        d["steps"].setdefault(step, {}).update(rec)
    write(META_DIR, sample_id, change)

if __name__ == "__main__":
    main()
