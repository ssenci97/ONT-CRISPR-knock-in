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
d="$(dirname "$0")"; echo "$@" >> "$d/scancel.log"
for i in "$@"; do sed -i "/^$i|/d" "$d/live" 2>/dev/null; done; true
"""

@pytest.fixture
def server(tmp_path, monkeypatch):
    for d in ("configs/samples", "results", "containers"): os.makedirs(tmp_path / d)
    (tmp_path / "configs/samples.tsv").write_text(SHEET)
    shutil.copy(f"{ROOT}/configs/param_configs.yaml", tmp_path / "configs/param_configs.yaml")
    shutil.copy(f"{ROOT}/configs/sample_schema.json", tmp_path / "configs/sample_schema.json")
    shutil.copy(f"{ROOT}/containers/images.env", tmp_path / "containers/images.env")
    shutil.copytree(f"{ROOT}/configs/examples", tmp_path / "configs/examples")
    bin = tmp_path / "bin"; bin.mkdir()
    for t, body in dict(singularity="#!/bin/sh\nexit 0\n", sbatch=FAKE_SBATCH, squeue=FAKE_SQUEUE, sacct=FAKE_SACCT, scancel=FAKE_SCANCEL).items():
        (bin / t).write_text(body); (bin / t).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin}:{os.environ['PATH']}")
    monkeypatch.setenv("NODE_PICK", "0")
    for k, v in dict(ROOT=str(tmp_path), RESULTS=str(tmp_path / "results"), GUI=f"{ROOT}/gui",
                     SCHEMA=str(tmp_path / "configs/sample_schema.json"), SAMPLES_TSV=str(tmp_path / "configs/samples.tsv"),
                     SAMPLES_DIR=str(tmp_path / "configs/samples"), EXAMPLES=str(tmp_path / "configs/examples"), DEFAULT_SIF=str(tmp_path / "none.sif")).items():
        monkeypatch.setattr(g, k, v)
    monkeypatch.setattr(g.analysis, "ROOT", str(tmp_path))
    monkeypatch.setattr(g.pipeline, "STOP_PAUSE", 0)
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

def test_examples_are_listed_by_short_name(server):
    base, _ = server
    ex = get(f"{base}/api/examples")["examples"]
    assert [e["short"] for e in ex] == ["arcus", "nitulescu"] and all(e["samples"] and e["title"] for e in ex)

def test_all_examples_launch_one_analysis_each(server):
    base, tmp = server
    names = [e["name"] for e in get(f"{base}/api/examples")["examples"]]
    body, code = post(f"{base}/api/run", analysis="ex", examples=names)
    assert code == 200 and body["errors"] == {} and [s["analysis"] for s in body["started"]] == ["ex_arcus", "ex_nitulescu"]
    for n in names:
        a, src = tmp / f"results/ex_{n.removeprefix('example_')}", tmp / f"configs/examples/{n}"
        assert (a / "inputs/params.yaml").read_text() == (src / "param_configs.yaml").read_text()
        assert (a / "inputs/samples.tsv").read_text() == (src / "samples.tsv").read_text()
        assert json.load(open(a / "inputs/analysis.json"))["source"] == f"configs/examples/{n}"
        assert all(jobs_tsv(tmp, a.name).values())
        assert json.load(open(a / "run_state.json"))["group"] == "ex"
    assert (tmp / "configs/samples.tsv").read_text() == SHEET
    assert body["group"] == "ex" and body["members"] == ["ex_arcus", "ex_nitulescu"]
    for n in body["members"]:
        g = get(f"{base}/api/status?analysis={n}")["group"]
        assert [m["name"] for m in g] == ["ex_arcus", "ex_nitulescu"] and all(m["group"] == "ex" and m["progress"]["total"] for m in g)
    assert {a["name"]: a["group"] for a in get(f"{base}/api/status")["analyses"]} == {"ex_arcus": "ex", "ex_nitulescu": "ex"}

def test_group_results_list_every_member_and_each_keeps_its_own_report(server):
    base, tmp = server
    post(f"{base}/api/run", analysis="ex", examples=["example_arcus", "example_nitulescu"])
    (tmp / "results/ex_arcus/summary_matrix.tsv").write_text("tool\ta1\nALPINE\t2.0\n")
    (tmp / "results/ex_nitulescu/summary_matrix.tsv").write_text("tool\tn1\nALPINE\t7.0\n")
    ra, rn = (get(f"{base}/api/results?analysis=ex_{s}") for s in ("arcus", "nitulescu"))
    assert ra["matrix"] == [["tool", "a1"], ["ALPINE", "2.0"]] and rn["matrix"] == [["tool", "n1"], ["ALPINE", "7.0"]]
    assert ra["group"] == rn["group"] == [dict(name="ex_arcus", done=True, group="ex"), dict(name="ex_nitulescu", done=True, group="ex")]

def test_single_run_has_no_group(server):
    base, tmp = server
    post(f"{base}/api/run", analysis="run_one")
    assert get(f"{base}/api/status?analysis=run_one")["group"] == [] and get(f"{base}/api/results?analysis=run_one")["group"] == []
    assert "group" not in json.load(open(tmp / "results/run_one/run_state.json"))

def test_unknown_example_and_live_run_refuse_all(server):
    base, tmp = server
    body, code = post(f"{base}/api/run", analysis="ex", examples=["example_nope"])
    assert code == 400 and body["errors"] == ["unknown example example_nope"]
    post(f"{base}/api/run", analysis="run_one")
    set_live(tmp, jobs_tsv(tmp).values())
    body, code = post(f"{base}/api/run", analysis="ex", examples=["example_arcus", "example_nitulescu"])
    assert code == 400 and "still running" in body["errors"][0] and not (tmp / "results/ex_arcus").exists()

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
    assert r["classes"] is None and r["reads"] == {}
    (a / "summary_classes.tsv").write_text("tool\tsample_id\tcategory\tclass\treads\tpct\nALPINE\tA\tFull knock-in\tHDR\t3\t1.5\n")
    os.makedirs(a / "data/stats", exist_ok=True); (a / "data/stats/A.tsv").write_text("sample_id\trun\traw_reads\tlen_pass\nA\tSRR1\t10\t8\n")
    r = get(f"{base}/api/results?analysis=run_one")
    assert r["classes"][0]["category"] == "Full knock-in" and r["reads"]["A"] == dict(raw_reads="10", len_pass="8")
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
    set_live(tmp, jobs_tsv(tmp).values(), "PENDING")
    body, code = post(f"{base}/api/stop", analysis="run_one")
    assert code == 200 and body["stopped"] and body["remaining"] == []
    assert set((tmp / "bin/scancel.log").read_text().split()) == set(jobs_tsv(tmp).values())
    assert post(f"{base}/api/stop", analysis="nope")[0]["stopped"] is False

def test_stop_all_cancels_every_analysis(server):
    base, tmp = server
    post(f"{base}/api/run", analysis="ex", examples=["example_arcus", "example_nitulescu"])
    ids = list(jobs_tsv(tmp, "ex_arcus").values()) + list(jobs_tsv(tmp, "ex_nitulescu").values())
    set_live(tmp, ids)
    body, _ = post(f"{base}/api/stop_all")
    assert set(body["analyses"]) == {"ex_arcus", "ex_nitulescu"} and not (tmp / "bin/live").read_text().strip()

def test_second_launch_refused_while_one_is_submitting(server):
    base, _ = server
    assert g.LAUNCH.acquire(blocking=False)
    try: body, code = post(f"{base}/api/run", analysis="run_one")
    finally: g.LAUNCH.release()
    assert code == 400 and "in progress" in body["errors"][0]

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

FAKE_SINFO = """#!/bin/sh
echo "genoa01 GENOA* mix 16/48/0/64 512000 100000 3.20"
echo "genoa02 GENOA idle 0/64/0/64 512000 0 0.01"
echo "thin001 THIN alloc 24/0/0/24 768000 700000 23.9"
"""

def test_perf_reports_nodes_and_job_efficiency_without_user_data(server):
    base, tmp = server
    (tmp / "bin/sinfo").write_text(FAKE_SINFO); (tmp / "bin/sinfo").chmod(0o755)
    post(f"{base}/api/run", analysis="run_one")
    jid = jobs_tsv(tmp)["alpine_A"]
    (tmp / "bin/sacct.txt").write_text(f"{jid}|COMPLETED|01:00:00|08:00:00||16|64000M|2026-11-14T10:00:00|2026-11-14T10:30:00|2026-11-14T11:30:00|genoa01\n"
                                       f"{jid}.batch||01:00:00|08:00:00|16G||||||\n")
    p = get(f"{base}/api/perf")
    c, parts = p["cluster"], {x["partition"]: x for x in p["cluster"]["partitions"]}
    assert [n["node"] for n in c["nodes"]] == ["genoa01", "genoa02", "thin001"] and parts["GENOA"]["fit"] == 2 and parts["THIN"]["fit"] == 0
    assert parts["GENOA"]["cpus"] == 128 and parts["GENOA"]["alloc"] == 16
    j = next(x for x in p["runs"]["jobs"] if x["key"] == "alpine_A")
    assert (j["cpu_eff"], j["mem_eff"], j["wait_min"], j["core_h"], j["node"]) == (50.0, 51.2, 30.0, 16.0, "genoa01")
    assert p["runs"]["tools"][0]["name"] == "alpine" and p["runs"]["analyses"][0]["core_h"] == 16.0
    assert "user" not in json.dumps(c).lower()

def test_agency_profile_is_checked_and_recorded(server):
    base, tmp = server
    for profile, nodes, msg in (("turbo", [], "unknown agency profile"), ("custom", [], "tick 1 to 4"), ("custom", ["n1", "n2", "n3", "n4", "n5"], "tick 1 to 4"),
                                ("custom", ["bad name"], "invalid node"), ("savemem", ["n1"], "only for Custom")):
        body, code = post(f"{base}/api/run", analysis="run_one", profile=profile, nodes=nodes)
        assert code == 400 and msg in body["errors"][0] and not (tmp / "results/run_one").exists()
    st, code = post(f"{base}/api/run", analysis="run_one", profile="processive")
    assert code == 200 and json.load(open(tmp / "results/run_one/run_state.json"))["profile"] == "processive"
    assert "--profile processive" in (tmp / "results/run_one/run.log").read_text()

def test_nodes_lists_only_usable_nodes_with_their_half(server):
    base, tmp = server
    (tmp / "bin/sinfo").write_text("#!/bin/sh\nprintf 'n1 GENOA idle 0/64/0/64 512000 0\\nn2 GENOA drain 0/64/0/64 512000 0\\ndgx1 DGX idle 0/64/0/64 512000 0\\n'\n"); (tmp / "bin/sinfo").chmod(0o755)
    r = get(f"{base}/api/nodes")
    assert r["max"] == 4 and r["available"] and [n["node"] for n in r["nodes"]] == ["n1"] and r["nodes"][0]["half_cpus"] == 32

def test_analysis_level_metadata_is_not_a_sample(server):
    base, tmp = server
    post(f"{base}/api/run", analysis="run_one")
    m = tmp / "results/run_one/meta"; os.makedirs(m)
    json.dump({"sample_id": "A", "steps": {}}, open(m / "A.json", "w")); json.dump({"analysis": "run_one", "steps": {"refs": {"perf": {"jobid": "1"}}}}, open(m / "_analysis.json", "w"))
    r = get(f"{base}/api/results?analysis=run_one")
    assert list(r["meta"]) == ["A"] and r["analysis_meta"]["steps"]["refs"]["perf"]["jobid"] == "1"
