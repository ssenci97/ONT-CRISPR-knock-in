"""gui_serve: the HTTP API creates one analysis per run, scopes results to it and refuses a second run."""
import json, os, shutil, time, urllib.error, urllib.request
import pytest
from conftest import ROOT, load

g = load("gui_serve")
SHEET = "sample_id\tsrr\tcondition\tcontrol\nA\tSRR1\tmock\t1\nB\tSRR2\tki\t0\n"

FAKE_SBATCH = """#!/bin/sh
n=$(cat "$0.n" 2>/dev/null || echo 100); n=$((n+1)); echo $n > "$0.n"; echo $n
"""
FAKE_SQUEUE = """#!/usr/bin/env python3
import os, sys
a, d = sys.argv, os.path.dirname(os.path.abspath(sys.argv[0]))
want = a[a.index("-j") + 1].split(",") if "-j" in a else []
full = "%j" in a[a.index("-o") + 1]
for l in open(f"{d}/live") if os.path.exists(f"{d}/live") else []:
    i, _, st = l.strip().partition("|")
    if i in want: print(f"{i}|kv_job_{i}|{st}|0:01|GENOA|node1" if full else f"{i}|{st}")
"""
FAKE_SACCT = """#!/bin/sh
cat "$(dirname "$0")/sacct.txt" 2>/dev/null
exit 0
"""
FAKE_SCANCEL = """#!/bin/sh
echo "$@" >> "$(dirname "$0")/scancel.log"
"""

@pytest.fixture
def server(tmp_path, monkeypatch):
    for d in ("configs/samples", "results", "containers"): os.makedirs(tmp_path / d)
    (tmp_path / "configs/samples.tsv").write_text(SHEET)
    shutil.copy(f"{ROOT}/configs/param_configs.yaml", tmp_path / "configs/param_configs.yaml")
    shutil.copy(f"{ROOT}/configs/sample_schema.json", tmp_path / "configs/sample_schema.json")
    shutil.copy(f"{ROOT}/containers/images.env", tmp_path / "containers/images.env")
    bin = tmp_path / "bin"; bin.mkdir()
    for t, body in dict(singularity="#!/bin/sh\nexit 0\n", sbatch=FAKE_SBATCH, squeue=FAKE_SQUEUE, sacct=FAKE_SACCT, scancel=FAKE_SCANCEL).items():
        (bin / t).write_text(body); (bin / t).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin}:{os.environ['PATH']}")
    monkeypatch.setenv("NODE_PICK", "0")
    for k, v in dict(ROOT=str(tmp_path), RESULTS=str(tmp_path / "results"), GUI=f"{ROOT}/gui",
                     SCHEMA=str(tmp_path / "configs/sample_schema.json"), SAMPLES_TSV=str(tmp_path / "configs/samples.tsv"),
                     SAMPLES_DIR=str(tmp_path / "configs/samples"), DEFAULT_SIF=str(tmp_path / "none.sif")).items():
        monkeypatch.setattr(g, k, v)
    monkeypatch.setattr(g.analysis, "ROOT", str(tmp_path))
    from http.server import ThreadingHTTPServer
    import threading
    srv = ThreadingHTTPServer(("127.0.0.1", 0), g.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", tmp_path
    srv.shutdown()

def jobs_tsv(tmp, name="run_one"):
    rows = [l.split("\t") for l in (tmp / f"results/{name}/jobs.tsv").read_text().splitlines()[1:]]
    return {r[0]: r[3] for r in rows}

def set_live(tmp, ids, state="RUNNING"): (tmp / "bin/live").write_text("".join(f"{i}|{state}\n" for i in ids))

def post(url, **body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try: return json.load(urllib.request.urlopen(req)), 200
    except urllib.error.HTTPError as e: return json.load(e), e.code

def get(url): return json.load(urllib.request.urlopen(url))

def test_run_creates_and_scopes_an_analysis(server):
    base, tmp = server
    st, code = post(f"{base}/api/run", analysis="run_one")
    assert code == 200 and st["analysis"] == "run_one" and st["new"]
    a = tmp / "results/run_one"
    assert (a / "inputs/samples.tsv").read_text() == SHEET
    assert json.load(open(a / "inputs/analysis.json"))["samples"] == ["A", "B"]
    s = get(f"{base}/api/status?analysis=run_one")
    ids = jobs_tsv(tmp)
    assert st["submitted"] == len(ids) and all(ids.values()) and "filter_A" in ids and "summary" in ids
    set_live(tmp, ids.values())
    s = get(f"{base}/api/status?analysis=run_one")
    assert s["running"] and [x["name"] for x in s["analyses"]] == ["run_one"]
    assert [x["step"] for x in s["steps"]] == g.STEPS
    assert "pipeline.py run_one" in s["log"] and len(s["queue"]) == len(ids) and s["queue"][0]["rule"]
    assert s["progress"]["done"] == 0 and s["progress"]["total"] == len(ids) and s["outcome"] == "running"

def test_second_run_is_refused_while_one_is_live(server):
    base, tmp = server
    post(f"{base}/api/run", analysis="run_one")
    set_live(tmp, jobs_tsv(tmp).values())
    body, code = post(f"{base}/api/run", analysis="run_two")
    assert code == 400 and "still running" in body["errors"][0]

def test_bad_sheet_and_bad_name_are_refused(server):
    base, tmp = server
    (tmp / "configs/samples.tsv").write_text(SHEET.replace("mock\t1", "mock\t0"))
    body, code = post(f"{base}/api/run", analysis="run_bad")
    assert code == 400 and any("control" in e for e in body["errors"])
    assert not (tmp / "results/run_bad/inputs").exists()
    body, code = post(f"{base}/api/run", analysis="../escape")
    assert code == 400

def test_results_are_read_per_analysis(server):
    base, tmp = server
    post(f"{base}/api/run", analysis="run_one")
    a = tmp / "results/run_one"
    (a / "summary_matrix.tsv").write_text("tool\tA\nALPINE\t1.5\n")
    (a / "summary.tsv").write_text("tool\tsample_id\tki_pct\nALPINE\tA\t1.5\n")
    os.makedirs(a / "meta"); json.dump({"sample_id": "A"}, open(a / "meta/A.json", "w"))
    r = get(f"{base}/api/results?analysis=run_one")
    assert r["matrix"] == [["tool", "A"], ["ALPINE", "1.5"]] and r["meta"]["A"]["sample_id"] == "A"
    assert get(f"{base}/api/results?analysis=nope")["matrix"] is None

def test_progress_counts_done_failed_and_cancelled(server):
    base, tmp = server
    post(f"{base}/api/run", analysis="run_one")
    a, ids = tmp / "results/run_one", jobs_tsv(tmp)
    for d in ("data/stats", "logs/01_fetch", "logs/03_alpine"): os.makedirs(a / d, exist_ok=True)
    (a / "data/A.fastq.gz").write_text("x\n"); (a / "data/stats/A.tsv").write_text("x\n")
    (a / "logs/01_fetch/filter_A.log").write_text("[SLURM-INFO] 2026 | elapsed 00:00:01\n")
    (a / "logs/03_alpine/B.log").write_text("boom\n")
    (tmp / "bin/sacct.txt").write_text(f"{ids['alpine_B']}|FAILED\n{ids['lungo_A']}|CANCELLED\n{ids['lungo_B']}|CANCELLED by 1\n")
    s = get(f"{base}/api/status?analysis=run_one")
    steps = {x["step"]: x for x in s["steps"]}
    assert steps["01_fetch"]["total"] == 5 and steps["01_fetch"]["done"] == 1
    assert steps["03_alpine"]["failed"] == 1 and steps["03_alpine"]["total"] == 2
    assert steps["04_lungo"]["cancelled"] == 2
    states = {j["job"]: j["state"] for x in s["steps"] for j in x["jobs"]}
    assert states["filter A"] == "done" and states["alpine B"] == "failed" and states["lungo A"] == "cancelled" and states["refs"] == "waiting"
    assert "boom" in {j["job"]: j["tail"] for j in steps["03_alpine"]["jobs"]}["alpine B"]
    assert s["progress"] == {"done": 1, "total": len(ids), "pct": round(100 / len(ids), 1)} and s["outcome"] == "failed" and not s["running"]

def test_tampered_frozen_input_is_refused_with_the_pipeline_message(server):
    base, tmp = server
    post(f"{base}/api/run", analysis="run_one")
    (tmp / "results/run_one/inputs/samples.tsv").write_text(SHEET + "C\tSRR3\tki\t0\n")
    body, code = post(f"{base}/api/run", analysis="run_one")
    assert code == 400 and any("changed" in e for e in body["errors"])

def test_stop_calls_scancel(server):
    base, tmp = server
    post(f"{base}/api/run", analysis="run_one")
    body, code = post(f"{base}/api/stop", analysis="run_one")
    assert code == 200 and body["stopped"]
    assert set((tmp / "bin/scancel.log").read_text().split()) == set(jobs_tsv(tmp).values())
    assert post(f"{base}/api/stop", analysis="nope")[0]["stopped"] is False

def test_path_lists_fastq_and_dirs(server):
    base, tmp = server
    (tmp / "reads").mkdir(); (tmp / "reads/a.fastq.gz").write_text("@r\nA\n+\nI\n"); (tmp / "reads/x.txt").write_text("")
    r = get(f"{base}/api/path?p={tmp}/reads/")
    assert r["entries"] == [f"{tmp}/reads/a.fastq.gz"]
    r = get(f"{base}/api/path?p={tmp}/reads/a.fastq.gz")
    assert r["file"] and r["size"] > 0

def test_run_is_refused_without_sbatch(server, monkeypatch):
    base, _ = server
    monkeypatch.setattr(g, "runtime", lambda: dict(sbatch=False, apptainer="x", sif=None, engine="", node_pick=False))
    body, code = post(f"{base}/api/run", analysis="run_one")
    assert code == 400 and "sbatch" in body["errors"][0]
