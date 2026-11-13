"""Pipeline driver: job plan, DAG submission through fake SLURM tools, file-based done check, safety refusals, kv_job.sh output verification and the CLI."""
import fcntl, glob, gzip, os, shutil, subprocess, sys
import pytest, yaml
from conftest import ROOT, load

pl = load("pipeline")
N = "t"
ENA = f"ena_{yaml.safe_load(open(f'{ROOT}/configs/param_configs.yaml'))['fetch']['bioproject']}"
FOOTER = "[SLURM-INFO] 2026-11-12 10:00:00 | elapsed 00:00:01 | max RSS 0.10 GB\n"
SHEET = "sample_id\tsrr\tcondition\tcontrol\tfastq_path\nA\tSRR1000001\tmock\t1\t\nB\tSRR1000002\ttreated\t0\t\nC\t\ttreated\t0\t{fq}\n"
FAKES = {
    "sbatch": '''#!/bin/bash
n=$(( $(cat "$FAKE/count" 2>/dev/null || echo 0) + 1 )); echo $n > "$FAKE/count"
[ "$n" = "$(cat "$FAKE/fail_at" 2>/dev/null)" ] && { echo "boom" >&2; exit 1; }
id=$((1000 + n)); prev=""; ok=0
for a in "$@"; do [ "$prev" = "-o" ] && [ -d "$(dirname "$a")" ] && ok=1; prev=$a; done
{ printf '%s\\t%s' "$id" "$ok"; printf '\\t%s' "$@"; echo; } >> "$FAKE/calls.tsv"
env > "$FAKE/env_$id.txt"; echo "$id"
''',
    "squeue": '#!/bin/bash\ncat "$FAKE/squeue.txt" 2>/dev/null; true\n',
    "sacct": '#!/bin/bash\ncat "$FAKE/sacct.txt" 2>/dev/null; true\n',
    "scancel": '#!/bin/bash\necho "$@" >> "$FAKE/scancel.txt"\n',
    "singularity": '#!/bin/bash\nshift\nwhile [[ "$1" == --* ]]; do [ "$1" = --bind ] && shift; shift; done\nshift\nexec "$@"\n',
}

class Env:
    def __init__(self, tmp, monkeypatch):
        self.tmp, self.root, self.fake = tmp, tmp / "root", tmp / "fake"
        self.fq = tmp / "fq" / "c.fastq.gz"
        for d in (self.root / "configs" / "samples", self.root / "containers", self.fake / "bin", self.fq.parent): d.mkdir(parents=True)
        with gzip.open(self.fq, "wt") as f: f.write("@r\nACGT\n+\nIIII\n")
        for f in ("configs/param_configs.yaml", "containers/images.env", "configs/sample_schema.json"): shutil.copy(f"{ROOT}/{f}", self.root / f)
        (self.root / "configs" / "samples.tsv").write_text(SHEET.format(fq=self.fq))
        for k, v in FAKES.items():
            (self.fake / "bin" / k).write_text(v); (self.fake / "bin" / k).chmod(0o755)
        for k, v in dict(PATH=f"{self.fake}/bin:{os.environ['PATH']}", FAKE=str(self.fake), NODE_PICK="0", KV_SIF="/x/fake.sif", SLURM_JOB_ID="9", SBATCH_PARTITION="X").items(): monkeypatch.setenv(k, v)
        pl.analysis.create(N, str(self.root))
    @property
    def r(self): return str(self.root)
    def calls(self):
        p = self.fake / "calls.tsv"
        rows = [l.split("\t") for l in p.read_text().splitlines()] if p.exists() else []
        return [dict(id=c[0], odir=c[1], argv=c[2:], key=c[c.index("-J") + 1].removeprefix(f"kv_{N}_")) for c in rows]
    def put(self, name, text):
        (self.fake / name).write_text(text)
    def fake_done(self, skip=()):
        for j in pl.plan(N, self.r):
            for o in j["outputs"]:
                os.makedirs(os.path.dirname(o), exist_ok=True)
                if o.endswith(".gz"): gzip.open(o, "wt").write("x\n")
                else: open(o, "w").write("x\n")
                os.utime(o, (1.7e9, 1.7e9))
            if not j["shared"]:
                os.makedirs(os.path.dirname(j["log"]), exist_ok=True); open(j["log"], "w").write("work\n" + FOOTER)
    def states(self):
        return {j["key"]: j["state"] for j in pl.submit(N, self.r, dry_run=True)}
    def rerun(self):
        return {k for k, s in self.states().items() if s == "would-run"}

@pytest.fixture
def e(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)

def keys(e): return {j["key"]: j for j in pl.plan(N, e.r)}

###################################### plan
def test_plan_counts(e):
    c = {}
    for k in keys(e): c[k.split("_")[0]] = c.get(k.split("_")[0], 0) + 1
    assert c == dict(ena=1, download=2, filter=3, refs=1, alpine=3, lungo=3, summary=1)
    assert "download_SRR1000003" not in keys(e) and "download_SRR1000001" in keys(e)

def test_plan_deps(e):
    k = keys(e)
    assert k["download_SRR1000001"]["deps"] == [ENA] and k["filter_A"]["deps"] == ["download_SRR1000001"] and k["filter_C"]["deps"] == []
    assert k["alpine_B"]["deps"] == ["filter_B", "refs"]
    assert set(k["lungo_B"]["deps"]) == {"filter_B", "filter_A", "refs"}
    assert set(k["summary"]["deps"]) == set(k) - {"summary", ENA} - {x for x in k if x.startswith("download")}

def test_plan_paths_and_resources(e):
    for j in keys(e).values():
        ok = (f"{e.r}/results/{N}/",) + ((f"{e.r}/data/raw/", f"{e.r}/data/meta/") if j["shared"] else ())
        assert all(p.startswith(ok) for p in j["outputs"] + [j["log"]]), j["key"]
        assert (j["cpus"], j["mem_mb"], j["minutes"]) == pl.RES[j["key"].split("_")[0]]
    a = keys(e)["alpine_A"]
    assert (a["cpus"], a["mem_mb"], a["minutes"]) == (32, 128000, 1440)

def test_plan_local_fastq_is_bound(e):
    assert keys(e)["filter_C"]["binds"] == [str(e.fq.parent)]

###################################### submit
def test_fresh_submit(e):
    out = pl.submit(N, e.r)
    calls, plan = e.calls(), pl.plan(N, e.r)
    assert [c["key"] for c in calls] == [j["key"] for j in plan] and len(calls) == 14
    ids = {c["key"]: c["id"] for c in calls}
    for c, j in zip(calls, plan):
        dep = [a for a in c["argv"] if a.startswith("--dependency=")]
        want = [ids[d] for d in j["deps"]]
        assert dep == ([f"--dependency=afterok:{':'.join(want)}"] if want else []), j["key"]
        assert c["odir"] == "1"
        assert all(os.path.isdir(os.path.dirname(o)) for o in j["outputs"])
        env = dict(l.split("=", 1) for l in (e.fake / f"env_{c['id']}.txt").read_text().splitlines() if "=" in l)
        assert not [k for k in env if k.startswith(("SLURM_", "SBATCH_"))]
        assert env["KV_ROOT"] == os.path.realpath(e.r) and env["KV_ANALYSIS"] == N and env["KV_IMAGE"] == "/x/fake.sif"
        assert env["KV_OUTPUTS"] == ":".join(j["outputs"])
    assert all(o["state"] == "submitted" for o in out)
    rows = (e.root / "results" / N / "jobs.tsv").read_text().splitlines()
    assert rows[0] == "key\tstep\tlabel\tjobid\tlog" and len(rows) == 15

def test_resources_reach_sbatch(e):
    pl.submit(N, e.r)
    a = next(c["argv"] for c in e.calls() if c["key"] == "alpine_A")
    assert a[a.index("-c") + 1] == "32" and "--mem=128000" in a and a[a.index("-t") + 1] == "1440"

###################################### done check
def test_all_done_submits_nothing(e):
    e.fake_done()
    assert e.rerun() == set()
    out = pl.submit(N, e.r)
    assert e.calls() == [] and {o["state"] for o in out} == {"done"}

def test_zero_byte_output_reruns_downstream(e):
    e.fake_done(); open(keys(e)["filter_B"]["outputs"][0], "w").close()
    assert e.rerun() == {"filter_B", "alpine_B", "lungo_B", "summary"}

def test_log_without_footer_reruns(e):
    e.fake_done(); open(keys(e)["alpine_A"]["log"], "w").write("work\n")
    assert e.rerun() == {"alpine_A", "summary"}

def test_shared_jobs_done_by_output_alone(e):
    e.fake_done()
    k = keys(e)
    assert not os.path.exists(k[ENA]["log"]) and not os.path.exists(k["download_SRR1000001"]["log"])
    assert e.states()[ENA] == "done" and e.states()["download_SRR1000001"] == "done"

def test_ena_rerun_does_not_resubmit_existing_downloads(e):
    e.fake_done(); os.remove(keys(e)[ENA]["outputs"][0])
    assert e.rerun() == {ENA}
    pl.submit(N, e.r)
    assert [c["key"] for c in e.calls()] == [ENA]

def test_newer_upstream_output_reruns_downstream(e):
    e.fake_done(); os.utime(keys(e)["refs"]["outputs"][-1], (1.8e9, 1.8e9))
    assert e.rerun() == {"alpine_A", "alpine_B", "alpine_C", "lungo_A", "lungo_B", "lungo_C", "summary"}

def test_dry_run_changes_nothing(e):
    out = pl.submit(N, e.r, dry_run=True)
    assert {o["state"] for o in out} == {"would-run"} and e.calls() == []
    assert not (e.root / "results" / N / "jobs.tsv").exists()

###################################### safety
def test_tampered_frozen_samples_refused(e):
    with open(e.root / "results" / N / "inputs" / "samples.tsv", "a") as f: f.write("D\tSRR1000009\tx\t0\t\n")
    for dry in (False, True):
        with pytest.raises(ValueError, match="changed or is missing"): pl.submit(N, e.r, dry_run=dry)
    assert e.calls() == []

def test_changed_local_fastq_refused(e):
    os.utime(e.fq, (1.5e9, 1.5e9))
    for dry in (False, True):
        with pytest.raises(ValueError, match="local FASTQ"): pl.submit(N, e.r, dry_run=dry)
    assert e.calls() == []

def test_preflight_lists_missing_inputs(e):
    jobs = pl.plan(N, e.r)
    with pytest.raises(ValueError) as x: pl.preflight(jobs, {"filter_A", "alpine_A"})
    assert "data/raw/SRR1000001.fastq.gz" in str(x.value) and "alpine_A" in str(x.value)

def test_preflight_rejects_non_fastq_local_input(e, monkeypatch):
    bad = e.fq.parent / "c.txt"; bad.write_bytes(e.fq.read_bytes())
    (e.root / "configs" / "samples.tsv").write_text(SHEET.format(fq=bad))
    shutil.rmtree(e.root / "results" / N); pl.analysis.create(N, e.r)
    for dry in (False, True):
        with pytest.raises(ValueError, match="pre-flight failed"): pl.submit(N, e.r, dry_run=dry)
    assert e.calls() == []

def test_symlinked_logs_dir_refused(e):
    out = e.tmp / "elsewhere"; out.mkdir()
    os.symlink(out, e.root / "results" / N / "logs")
    with pytest.raises(ValueError, match="outside"): pl.submit(N, e.r)
    assert e.calls() == [] and os.listdir(out) == []

def test_concurrent_launch_refused(e):
    with open(e.root / "results" / N / ".lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        with pytest.raises(RuntimeError, match="in progress"): pl.submit(N, e.r)
    assert e.calls() == []

def write_jobs(e, name, key, jobid):
    d = e.root / "results" / name; d.mkdir(parents=True, exist_ok=True)
    (d / "jobs.tsv").write_text(f"key\tstep\tlabel\tjobid\tlog\n{key}\ts\tl\t{jobid}\t/x\n")

def test_own_live_job_refused(e):
    write_jobs(e, N, "filter_A", "55"); e.put("squeue.txt", "55|RUNNING\n")
    with pytest.raises(RuntimeError, match="live jobs"): pl.submit(N, e.r)
    assert e.calls() == []

def test_finished_own_job_allows_relaunch(e):
    write_jobs(e, N, "filter_A", "55"); e.put("sacct.txt", "55|COMPLETED\n")
    assert len(pl.submit(N, e.r)) == 14

def test_other_analysis_live_shared_job_refused(e):
    write_jobs(e, "other", ENA, "77"); e.put("squeue.txt", "77|PENDING\n")
    with pytest.raises(RuntimeError, match="another analysis"): pl.submit(N, e.r)
    assert e.calls() == []

def test_other_analysis_live_private_job_allowed(e):
    write_jobs(e, "other", "alpine_A", "77"); e.put("squeue.txt", "77|PENDING\n")
    assert len(pl.submit(N, e.r)) == 14

def test_failed_sbatch_cancels_submitted_and_keeps_jobs_tsv(e):
    e.put("fail_at", "3")
    with pytest.raises(RuntimeError, match="sbatch failed"): pl.submit(N, e.r)
    assert (e.fake / "scancel.txt").read_text().split() == ["1001", "1002"]
    rows = (e.root / "results" / N / "jobs.tsv").read_text().splitlines()
    assert [r.split("\t")[3] for r in rows[1:]] == ["1001", "1002"]

@pytest.mark.parametrize("dry", [False, True])
def test_invalid_analysis_name_refused(e, dry):
    with pytest.raises(ValueError, match="analysis name"): pl.submit("../x", e.r, dry_run=dry)
    assert e.calls() == []

def test_stop_cancels_jobs_from_jobs_tsv(e):
    pl.submit(N, e.r)
    assert pl.stop(N, e.r) == 14
    assert (e.fake / "scancel.txt").read_text().split() == [str(1001 + i) for i in range(14)]

###################################### kv_job.sh
STEP = '''#!/bin/bash
set -e
case "$1" in
  good) echo hi > "$KV_OUT/ok.txt"; echo x | gzip > "$KV_OUT/ok.gz";;
  empty) : > "$KV_OUT/ok.txt";;
  corrupt) echo notgz > "$KV_OUT/ok.gz";;
  fail) exit 7;;
  args) printf %s "$2" > "$KV_OUT/arg.txt"; echo hi > "$KV_OUT/ok.txt";;
esac
'''

def kv(e, mode, outs=("ok.txt",), *extra):
    out = e.root / "results" / "k"; out.mkdir(parents=True, exist_ok=True)
    (e.root / "src").mkdir(exist_ok=True); (e.root / "src" / "step.sh").write_text(STEP)
    env = dict(os.environ, KV_ROOT=e.r, KV_ANALYSIS="k", KV_IMAGE="fake.sif", KV_OUTPUTS=":".join(f"{out}/{o}" for o in outs))
    r = subprocess.run(["bash", f"{ROOT}/src/kv_job.sh", "src/step.sh", mode, *extra], capture_output=True, text=True, env=env)
    return r, r.stdout + r.stderr, out

def test_kv_job_good_outputs(e):
    r, o, _ = kv(e, "good", ("ok.txt", "ok.gz"))
    assert r.returncode == 0 and "outputs verified: 2" in o

@pytest.mark.parametrize("mode,outs", [("empty", ("ok.txt",)), ("corrupt", ("ok.gz",)), ("good", ("ok.txt", "nope.txt")), ("none", ("ok.txt",))])
def test_kv_job_bad_outputs(e, mode, outs):
    r, o, _ = kv(e, mode, outs)
    assert r.returncode == 1 and "output check failed" in o

def test_kv_job_propagates_step_exit_code(e):
    r, o, _ = kv(e, "fail")
    assert r.returncode == 7 and "outputs verified" not in o

def test_kv_job_keeps_arguments_intact(e):
    arg = "a b $HOME `x` 'q'"
    r, o, out = kv(e, "args", ("ok.txt",), arg)
    assert r.returncode == 0, o
    assert (out / "arg.txt").read_text() == arg

###################################### CLI
def cli(e, *a):
    return subprocess.run([sys.executable, f"{ROOT}/src/pipeline.py", *a, "--root", e.r], capture_output=True, text=True)

def test_cli_dry_run(e):
    r = cli(e, N, "--dry-run")
    assert r.returncode == 0, r.stderr
    assert f"{ENA}: would-run" in r.stdout and "14 jobs: 0 done, 0 submitted, 14 would run" in r.stdout and "| elapsed" in r.stdout

def test_cli_refusal_exits_nonzero(e):
    for name in ("../x", "nope"):
        r = cli(e, name, "--dry-run")
        assert r.returncode != 0 and "!!" in r.stderr
