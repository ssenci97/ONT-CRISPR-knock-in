"""gui_serve: the HTTP API creates one analysis per run, scopes results to it and refuses a second run."""
import json, os, shutil, time, urllib.error, urllib.request
import pytest
from conftest import ROOT, load

g = load("gui_serve")
SHEET = "sample_id\tsrr\tcondition\tcontrol\nA\tSRR1\tmock\t1\nB\tSRR2\tki\t0\n"

@pytest.fixture
def server(tmp_path, monkeypatch):
    for d in ("configs/samples", "results"): os.makedirs(tmp_path / d)
    (tmp_path / "configs/samples.tsv").write_text(SHEET)
    (tmp_path / "configs/param_configs.yaml").write_text("shared:\n  ki_min_insert_frac: 0.8\n")
    shutil.copy(f"{ROOT}/configs/sample_schema.json", tmp_path / "configs/sample_schema.json")
    bin = tmp_path / "bin"; bin.mkdir()
    (bin / "snakemake").write_text("#!/bin/sh\necho ran \"$@\"\nsleep 5\n"); (bin / "snakemake").chmod(0o755)
    for t in ("singularity", "sbatch"): (bin / t).write_text("#!/bin/sh\nexit 0\n"); (bin / t).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin}:{os.environ['PATH']}")
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
    for a in g.analyses(): g.stop_run(a["name"])
    srv.shutdown()

def post(url, **body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try: return json.load(urllib.request.urlopen(req)), 200
    except urllib.error.HTTPError as e: return json.load(e), e.code

def get(url): return json.load(urllib.request.urlopen(url))

def test_run_creates_and_scopes_an_analysis(server):
    base, tmp = server
    st, code = post(f"{base}/api/run", analysis="run_one", sbatch=False)
    assert code == 200 and st["analysis"] == "run_one" and st["new"]
    a = tmp / "results/run_one"
    assert (a / "inputs/samples.tsv").read_text() == SHEET
    assert json.load(open(a / "inputs/analysis.json"))["samples"] == ["A", "B"]
    s = get(f"{base}/api/status?analysis=run_one")
    assert s["running"] and [x["name"] for x in s["analyses"]] == ["run_one"]
    assert [x["step"] for x in s["steps"]] == g.STEPS
    assert "ran" in s["log"]

def test_second_run_is_refused_while_one_is_live(server):
    base, _ = server
    post(f"{base}/api/run", analysis="run_one", sbatch=False)
    body, code = post(f"{base}/api/run", analysis="run_two", sbatch=False)
    assert code == 400 and "still running" in body["errors"][0]

def test_bad_sheet_and_bad_name_are_refused(server):
    base, tmp = server
    (tmp / "configs/samples.tsv").write_text(SHEET.replace("mock\t1", "mock\t0"))
    body, code = post(f"{base}/api/run", analysis="run_bad", sbatch=False)
    assert code == 400 and any("control" in e for e in body["errors"])
    assert not (tmp / "results/run_bad/inputs").exists()
    body, code = post(f"{base}/api/run", analysis="../escape", sbatch=False)
    assert code == 400

def test_results_are_read_per_analysis(server):
    base, tmp = server
    post(f"{base}/api/run", analysis="run_one", sbatch=False)
    a = tmp / "results/run_one"
    (a / "summary_matrix.tsv").write_text("tool\tA\nALPINE\t1.5\n")
    (a / "summary.tsv").write_text("tool\tsample_id\tki_pct\nALPINE\tA\t1.5\n")
    os.makedirs(a / "meta"); json.dump({"sample_id": "A"}, open(a / "meta/A.json", "w"))
    r = get(f"{base}/api/results?analysis=run_one")
    assert r["matrix"] == [["tool", "A"], ["ALPINE", "1.5"]] and r["meta"]["A"]["sample_id"] == "A"
    assert get(f"{base}/api/results?analysis=nope")["matrix"] is None

def test_snakemake_env_is_found_without_activation(tmp_path, monkeypatch):
    env_bin = tmp_path / ".conda/envs/kv_snakemake/bin"; env_bin.mkdir(parents=True)
    (env_bin / "snakemake").write_text("#!/bin/sh\nexit 0\n"); (env_bin / "snakemake").chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path)); monkeypatch.setenv("PATH", "/usr/bin:/bin")
    for k in ("CONDA_EXE", "MAMBA_EXE", "CONDA_PREFIX"): monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(g, "find_conda", lambda: None)
    g.ensure_snakemake()
    assert shutil.which("snakemake") == str(env_bin / "snakemake")
