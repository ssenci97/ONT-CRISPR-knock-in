"""Workflow wiring: shell syntax, the DAG per analysis, the native-run refusal and the container guard."""
import csv, glob, os, re, shutil, subprocess
import pytest
from conftest import ROOT, load

SMK = shutil.which("snakemake")
V = int((subprocess.run([SMK, "--version"], capture_output=True, text=True).stdout or "0").split(".")[0]) if SMK else 0
needs = pytest.mark.skipif(V < 8, reason="needs snakemake >= 8 (conda env create -f envs/snakemake.yml)")
N = sum(1 for r in csv.DictReader(open(f"{ROOT}/configs/samples.tsv"), delimiter="\t") if r["sample_id"])

@pytest.mark.parametrize("script", sorted(glob.glob(f"{ROOT}/src/*.sh") + glob.glob(f"{ROOT}/containers/*.sh")))
def test_bash_syntax(script):
    subprocess.run(["bash", "-n", script], check=True)

def fake_path(tmp_path):
    b = tmp_path / "bin"; b.mkdir(exist_ok=True)
    for t in ("apptainer", "singularity", "sbatch", "squeue", "sinfo", "sacct", "scontrol"):
        (b / t).write_text("#!/bin/sh\necho 'apptainer version 1.3.4'\n"); (b / t).chmod(0o755)
    return dict(os.environ, PATH=f"{b}:{os.environ['PATH']}")

def dry(tmp_path, *extra, analysis="t_dag"):
    load("analysis").create(analysis, ROOT)
    r = subprocess.run([SMK, "-n", "--forceall", "-s", f"{ROOT}/Snakefile", "--config", f"analysis={analysis}", *extra],
                       capture_output=True, text=True, cwd=ROOT, env=fake_path(tmp_path))
    return r, r.stdout + r.stderr

@pytest.fixture(autouse=True)
def clean():
    yield
    for d in glob.glob(f"{ROOT}/results/t_*"): shutil.rmtree(d, ignore_errors=True)

@needs
def test_dag(tmp_path):
    r, out = dry(tmp_path, "--sdm", "apptainer")
    assert r.returncode == 0, out
    c = dict(re.findall(r"^(\w+)\s+(\d+)\b", out, re.M))
    assert [c.get(k) for k in ("filter", "alpine", "lungo", "refs", "summary")] == [str(N)] * 3 + ["1", "1"]

@needs
def test_outputs_live_under_the_analysis(tmp_path):
    _, out = dry(tmp_path, "--sdm", "apptainer", analysis="t_scope")
    produced = [f.strip() for m in re.findall(r"^\s+(?:output|log|benchmark): (.+)$", out, re.M) for f in m.split(",")]
    assert produced, out
    allowed = ("results/t_scope/", "data/raw/", "data/meta/")
    stray = sorted({p for p in produced if not p.startswith(allowed)})
    assert stray == [], f"outputs outside results/t_scope: {stray}"

@needs
def test_refuses_to_run_natively(tmp_path):
    r, out = dry(tmp_path)
    assert r.returncode != 0 and "refusing to run natively" in out, out

@needs
def test_refuses_unknown_analysis(tmp_path):
    r = subprocess.run([SMK, "-n", "-s", f"{ROOT}/Snakefile", "--sdm", "apptainer", "--config", "analysis=t_nope"],
                       capture_output=True, text=True, cwd=ROOT, env=fake_path(tmp_path))
    assert r.returncode != 0 and "create the analysis first" in r.stdout + r.stderr

@needs
@pytest.mark.parametrize("profile", ["profiles/slurm", "profiles/local"])
def test_profiles(tmp_path, profile):
    r, out = dry(tmp_path, "--profile", profile)
    assert r.returncode == 0, out
    assert dict(re.findall(r"^(\w+)\s+(\d+)\b", out, re.M)).get("summary") == "1"

@pytest.mark.parametrize("script", ["refs.sh", "alpine.sh", "lungo.sh", "filter.sh", "download.sh"])
def test_scripts_refuse_outside_the_container(script, tmp_path):
    r = subprocess.run(["bash", f"{ROOT}/src/{script}"], capture_output=True, text=True,
                       env=dict(os.environ, KV_OUT=str(tmp_path), TOOLS=str(tmp_path)))
    assert r.returncode != 0 and "refusing to run outside the container" in r.stdout + r.stderr
