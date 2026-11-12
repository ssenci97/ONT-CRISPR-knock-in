#!/usr/bin/env python3
"""Single writer of per-sample run metadata: merge one step record into results/meta/<sample_id>.json."""
import datetime, fcntl, json, os, subprocess, sys

###################################### constants
ROOT = os.environ.get("KV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get("KV_OUT") or f"{ROOT}/results/default"
META_DIR = f"{OUT}/meta"
SUBMITTED_DIR = f"{OUT}/inputs/samples"

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
    e["containerized"] = bool(os.environ.get("KV_INSIDE"))
    e["tools"] = tool_commits()
    return e

def submitted(sample_id):
    p = f"{SUBMITTED_DIR}/{sample_id}.json"
    return json.load(open(p)) if os.path.exists(p) else {}

###################################### main
def main():
    sample_id, step, *kv = sys.argv[1:]
    os.makedirs(META_DIR, exist_ok=True); p = f"{META_DIR}/{sample_id}.json"
    with open(f"{p}.lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        d = json.load(open(p)) if os.path.exists(p) else {"sample_id": sample_id, "submitted": submitted(sample_id), "steps": {}}
        d["submitted"] = d.get("submitted") or submitted(sample_id)
        d["pipeline_commit"] = git_sha()
        d["environment"] = environment()
        rec = {k: scalar(v) for k, v in (x.split("=", 1) for x in kv)}
        rec["recorded_at"] = f"{datetime.datetime.now():%F %T}"
        for v in ("SLURM_JOB_ID", "SLURM_ARRAY_TASK_ID"):
            if os.environ.get(v): rec[v.lower()] = os.environ[v]
        d["steps"].setdefault(step, {}).update(rec)
        json.dump(d, open(f"{p}.tmp", "w"), indent=2, sort_keys=False)
        os.replace(f"{p}.tmp", p)

if __name__ == "__main__":
    main()
