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
[ "$n" = "$(cat "$FAKE/stop_at" 2>/dev/null)" ] && touch "$KV_ROOT/results/$KV_ANALYSIS/.stop"
id=$((1000 + n)); prev=""; ok=0
for a in "$@"; do [ "$prev" = "-o" ] && [ -d "$(dirname "$a")" ] && ok=1; prev=$a; done
{ printf '%s\\t%s' "$id" "$ok"; printf '\\t%s' "$@"; echo; } >> "$FAKE/calls.tsv"
env > "$FAKE/env_$id.txt"; echo "$id"
''',
    "squeue": '#!/bin/bash\ncase "$*" in *"%i|%k"*) cat "$FAKE/squeue_k.txt" 2>/dev/null;; *) cat "$FAKE/squeue.txt" 2>/dev/null;; esac; true\n',
    "sacct": '#!/bin/bash\ncat "$FAKE/sacct.txt" 2>/dev/null; true\n',
    "scancel": '#!/bin/bash\necho "$@" >> "$FAKE/scancel.txt"\n[ -e "$FAKE/stuck" ] || for i in "$@"; do sed -i "/^$i|/d" "$FAKE/squeue.txt" 2>/dev/null; done; true\n',
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
        monkeypatch.setattr(pl, "STOP_PAUSE", 0)
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
    assert (a["cpus"], a["mem_mb"], a["minutes"]) == (4, 8000, 1440)

def test_plan_local_fastq_is_bound(e):
    assert keys(e)["filter_C"]["binds"] == [str(e.fq.parent)]

###################################### submit
def test_fresh_submit(e):
    out = pl.submit(N, e.r)
    calls, plan = e.calls(), pl.plan(N, e.r)
    assert sorted(c["key"] for c in calls) == sorted(j["key"] for j in plan) and len(calls) == 14
    ids, by = {c["key"]: c["id"] for c in calls}, {j["key"]: j for j in plan}
    for c in calls:
        j = by[c["key"]]
        dep = {k: v.split(":") for k, _, v in (x.partition(":") for a in c["argv"] if a.startswith("--dependency=") for x in a.removeprefix("--dependency=").split(","))}
        want = [ids[d] for d in j["deps"]]
        assert dep.get("afterok", []) == want and not set(dep.get("afterany", [])) & set(want), j["key"]
        assert c["odir"] == "1"
        assert all(os.path.isdir(os.path.dirname(o)) for o in j["outputs"])
        env = dict(l.split("=", 1) for l in (e.fake / f"env_{c['id']}.txt").read_text().splitlines() if "=" in l)
        assert not [k for k in env if k.startswith(("SLURM_", "SBATCH_"))]
        assert env["KV_ROOT"] == os.path.realpath(e.r) and env["KV_ANALYSIS"] == N and env["KV_IMAGE"] == "/x/fake.sif"
        assert env["KV_OUTPUTS"] == ":".join(j["outputs"])
    assert all(o["state"] == "submitted" for o in out)
    rows = (e.root / "results" / N / "jobs.tsv").read_text().splitlines()
    assert rows[0] == "\t".join(pl.COLS) and len(rows) == 15

def test_resources_reach_sbatch(e):
    pl.submit(N, e.r)
    a = next(c["argv"] for c in e.calls() if c["key"] == "alpine_A")
    assert a[a.index("-c") + 1] == "4" and "--mem=8000" in a and a[a.index("-t") + 1] == "1440"
    assert a[a.index("-p") + 1] == "GENOA" and a[a.index("-N") + 1] == "1" and a[a.index("--comment") + 1] == f"kv:{N}:alpine_A"
    assert a[-2:] == ["4", "8000"]

def sized(e):
    jobs = pl.plan(N, e.r)
    for j in jobs: pl.size_job(j, [])
    return jobs

def test_schedule_tokens_keep_the_ceiling_whatever_the_run_times(e):
    jobs = sized(e); nodes = [pl.ceiling("", "GENOA", None)]
    sch = pl.schedule(jobs, nodes)
    by, holders = {j["key"]: j for j in jobs}, {}
    for k in sch["order"]:
        j = by[k]
        assert len(sch["held"][k]) >= j["cpus"] and len(sch["held"][k]) * nodes[0]["mb_per_token"] >= j["mem_mb"]
        for t in sch["held"][k]:
            if t in holders: assert holders[t] in sch["prev"][k]
            holders[t] = k
    assert len(holders) <= pl.BUDGET_CPUS and set(sch["order"]) == set(by)

def test_schedule_launches_early_and_in_parallel(e):
    sch = pl.schedule(sized(e), [pl.ceiling("", "GENOA", None)])
    assert sch["start"]["refs"] == 0 and sch["prev"]["refs"] == [] and pl.peak(sch) >= 5
    assert sch["start"]["summary"] == max(sch["start"].values())

def test_submission_follows_the_schedule_and_waits_only_on_token_holders(e):
    pl.submit(N, e.r)
    calls = e.calls(); ids = {c["key"]: c["id"] for c in calls}; pos = {c["key"]: i for i, c in enumerate(calls)}
    for c in calls:
        dep = [a for a in c["argv"] if a.startswith("--dependency=")]
        for part in (dep[0].removeprefix("--dependency=").split(",") if dep else []):
            for i in part.split(":")[1:]: assert pos[next(k for k, v in ids.items() if v == i)] < pos[c["key"]]
    log = (e.root / "results" / N / "logs/node_pick.log").read_text()
    assert "(budget 32 cpus 64 GB)" in log and "= 32 tokens of 1 cpu + 2.0 GB" in log and "refs: 1 cpus" in log and "starts ~0 min" in log

def test_too_many_jobs_refused_before_any_sbatch(e, monkeypatch):
    monkeypatch.setattr(pl, "MAX_JOBS", 5)
    with pytest.raises(ValueError, match="limit of 5"): pl.submit(N, e.r)
    assert e.calls() == []

def test_full_user_queue_refused(e, monkeypatch):
    monkeypatch.setattr(pl, "MAX_USER_JOBS", 20)
    e.put("squeue.txt", "".join(f"{900 + i}|RUNNING\n" for i in range(10)))
    with pytest.raises(RuntimeError, match="already have 10 jobs"): pl.submit(N, e.r)
    assert e.calls() == []

def test_sizing_learns_from_finished_and_oom_jobs(e):
    d = e.root / "results/other"; d.mkdir(parents=True)
    (d / "jobs.tsv").write_text("\t".join(pl.COLS) + "\nalpine_X\ts\tl\t77\t/x\t\t16\t64000\t1440\t0\nlungo_X\ts\tl\t78\t/x\t\t16\t64000\t1440\t0\n")
    e.put("sacct.txt", "77|COMPLETED|||\n77.batch||2048M|00:10:00\n78|OUT_OF_MEMORY||00:05:00\n")
    pl.submit(N, e.r)
    a = {c["key"]: c["argv"] for c in e.calls()}
    assert "--mem=3072" in a["alpine_A"] and a["alpine_A"][a["alpine_A"].index("-t") + 1] == "30"
    log = (e.root / "results" / N / "logs/node_pick.log").read_text()
    assert "--mem=32000" in a["lungo_A"] and "peak 2.0 GB (sacct MaxRSS" in log and "best of 1 run(s)" in log and "capped at 32 GB" in log

def test_sizing_triangulates_log_peak_and_input_size(e):
    d = e.root / "results/other"; (d / "logs").mkdir(parents=True)
    (d / "logs/a.log").write_text("[SLURM-INFO] work\n[SLURM-INFO] 2026-11-14 10:00:00 | elapsed 00:20:00 | max RSS 4.00 GB\n")
    (d / "jobs.tsv").write_text("\t".join(pl.COLS) + f"\nfilter_X\ts\tl\t77\t{d}/logs/a.log\t\t8\t8000\t240\t{os.path.getsize(e.fq) / 2}\n")
    pl.submit(N, e.r)
    a = {c["key"]: c["argv"] for c in e.calls()}
    assert "--mem=10752" in a["filter_C"] and a["filter_C"][a["filter_C"].index("-t") + 1] == "90"
    assert "peak 4.0 GB (log cgroup peak" in (e.root / "results" / N / "logs/node_pick.log").read_text()

def test_sizing_prefers_sacct_rss_over_the_cache_inflated_log_peak(e):
    d = e.root / "results/other"; (d / "logs").mkdir(parents=True)
    (d / "logs/a.log").write_text("[SLURM-INFO] 2026-11-14 10:00:00 | elapsed 00:20:00 | max RSS 9.00 GB\n")
    (d / "jobs.tsv").write_text("\t".join(pl.COLS) + f"\nalpine_X\ts\tl\t77\t{d}/logs/a.log\t\t16\t8000\t1440\t0\n")
    e.put("sacct.txt", "77|COMPLETED|||01:00:00|16\n77.batch||2048M|00:20:00||\n")
    pl.submit(N, e.r)
    a = {c["key"]: c["argv"] for c in e.calls()}
    assert "--mem=3072" in a["alpine_A"] and "peak 2.0 GB (sacct MaxRSS" in (e.root / "results" / N / "logs/node_pick.log").read_text()

def test_sizing_learns_cores_down_and_up_from_cpu_use(e):
    d = e.root / "results/other"; d.mkdir(parents=True)
    (d / "jobs.tsv").write_text("\t".join(pl.COLS) + "\nalpine_X\ts\tl\t77\t/x\t\t4\t8000\t1440\t0\nlungo_X\ts\tl\t78\t/x\t\t4\t8000\t1440\t0\n")
    e.put("sacct.txt", "77|COMPLETED|||01:00:00|4\n77.batch||2048M|01:00:00||\n78|COMPLETED|||07:48:00|4\n78.batch||2048M|02:00:00||\n")
    pl.submit(N, e.r)
    a = {c["key"]: c["argv"] for c in e.calls()}
    assert a["alpine_A"][a["alpine_A"].index("-c") + 1] == "2" and a["lungo_A"][a["lungo_A"].index("-c") + 1] == "8"
    log = (e.root / "results" / N / "logs/node_pick.log").read_text()
    assert "cpus 4 -> 2: at most 1.0 cores used" in log and "cpus 4 -> 8: a run kept its 4 cores busy" in log

def test_done_jobs_keep_their_history_row_on_relaunch(e):
    pl.submit(N, e.r); first = {c["key"]: c["id"] for c in e.calls()}; e.fake_done(); os.remove(keys(e)["alpine_A"]["outputs"][0])
    pl.submit(N, e.r)
    rows = {r["key"]: r for r in pl.read_jobs(N, e.r)}
    assert rows["filter_A"]["jobid"] == first["filter_A"] and rows["filter_A"]["mem_mb"] == "2000" and rows["alpine_A"]["jobid"] != first["alpine_A"]

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
    ids = [str(1001 + i) for i in range(14)]
    e.put("squeue.txt", "".join(f"{i}|PENDING\n" for i in ids))
    assert pl.stop(N, e.r) == dict(cancelled=ids, remaining=[])
    assert (e.fake / "scancel.txt").read_text().split() == ids and not (e.root / "results" / N / ".stop").exists()

def test_stop_also_sweeps_tagged_jobs_missing_from_jobs_tsv(e):
    e.put("squeue_k.txt", f"555|kv:{N}:alpine_A\n556|kv:{N}x:alpine_A\n557|kv:other:x\n")
    e.put("squeue.txt", "555|RUNNING\n556|RUNNING\n557|RUNNING\n")
    assert pl.stop(N, e.r) == dict(cancelled=["555"], remaining=[])

def test_stop_reports_jobs_that_survive_scancel(e):
    pl.submit(N, e.r); e.put("stuck", ""); e.put("squeue.txt", "1001|RUNNING\n")
    assert pl.stop(N, e.r) == dict(cancelled=[], remaining=["1001"])
    assert (e.fake / "scancel.txt").read_text().split() == ["1001"] * 3

def test_stop_during_submit_cancels_what_was_submitted(e):
    e.put("stop_at", "3")
    with pytest.raises(RuntimeError, match="stopped while submitting: 3"): pl.submit(N, e.r)
    assert (e.fake / "scancel.txt").read_text().split() == ["1001", "1002", "1003"] and len(e.calls()) == 3

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

###################################### node_pick.sh
FAKE_SINFO = '''#!/bin/bash
case "$*" in
  *"%P %l"*) printf 'GENOA* 2-00:00:00\\nDGX 6-06:00:00\\nSHORT 01:00:00\\n';;
  *) printf 'genoa01 GENOA mix 56/8/0/64 512000 100000\\ngenoa02 GENOA mix 16/48/0/64 512000 200000\\ngenoa03 GENOA drain 0/64/0/64 512000 0\\n';;
esac
'''

def test_node_pick_finds_a_node_with_the_budget_free(tmp_path):
    (tmp_path / "sinfo").write_text(FAKE_SINFO); (tmp_path / "sinfo").chmod(0o755)
    run = lambda *a: subprocess.run([f"{ROOT}/src/node_pick.sh", *a], capture_output=True, text=True, env=dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}"))
    r = run("32", "256000", "1440")
    assert r.stdout.split() == ["genoa02", "GENOA"] and "genoa02" in r.stderr
    assert run("64", "1000", "1440").stdout.strip() == ""

###################################### agency profiles
FAKE_SINFO_4 = '''#!/bin/bash
case "$*" in
  *"%P %l"*) printf 'GENOA* 2-00:00:00\\nTHIN 12:00:00\\n';;
  *) printf 'genoa01 GENOA mix 56/8/0/64 512000 100000\\ngenoa02 GENOA mix 16/48/0/64 512000 200000\\ngenoa03 GENOA drain 0/64/0/64 512000 0\\ngenoa04 GENOA idle 0/64/0/64 512000 0\\nthin01 THIN idle 0/24/0/24 96000 0\\n';;
esac
'''

def nodes_env(e, monkeypatch):
    (e.fake / "bin" / "sinfo").write_text(FAKE_SINFO_4); (e.fake / "bin" / "sinfo").chmod(0o755)
    (e.root / "src").mkdir(exist_ok=True)
    for f in ("node_pick.sh", "best_node.sh"): shutil.copy(f"{ROOT}/src/{f}", e.root / "src" / f)
    monkeypatch.setenv("NODE_PICK", "1")

def wide(monkeypatch): monkeypatch.setattr(pl, "RES", {**pl.RES, "alpine": (16, 8000, 1440), "lungo": (16, 8000, 1440)})

def pins(e): return {c["key"]: c["argv"][c["argv"].index("-w") + 1] if "-w" in c["argv"] else "" for c in e.calls()}

def test_width_is_the_widest_level_of_the_dag(e):
    assert pl.width(pl.plan(N, e.r)) == 5

def test_savemem_stays_on_one_node_within_the_project_budget(e, monkeypatch):
    nodes_env(e, monkeypatch)
    pl.submit(N, e.r)
    assert set(pins(e).values()) == {"genoa04"}
    log = (e.root / "results" / N / "logs/node_pick.log").read_text()
    assert "[savemem]" in log and "node genoa04 GENOA: at most 32 cpus 64 GB = 32 tokens" in log

def test_processive_adds_a_second_node_of_the_same_partition_only_when_useful(e, monkeypatch):
    nodes_env(e, monkeypatch); wide(monkeypatch)
    pl.submit(N, e.r, profile="processive")
    assert set(pins(e).values()) == {"genoa04", "genoa02"}
    log = (e.root / "results" / N / "logs/node_pick.log").read_text()
    assert "second node genoa02" in log and "parallel width 5" in log and "thin01" not in log

def test_processive_stays_on_one_node_when_the_jobs_fit(e, monkeypatch):
    nodes_env(e, monkeypatch)
    pl.submit(N, e.r, profile="processive")
    assert set(pins(e).values()) == {"genoa04"}

def test_processive_with_one_wide_enough_node_uses_one(e, monkeypatch):
    nodes_env(e, monkeypatch)
    monkeypatch.setattr(pl, "RES", {k: (1, 1000, 15) for k in pl.RES})
    pl.submit(N, e.r, profile="processive")
    assert len(set(pins(e).values())) == 1

def test_custom_uses_only_the_ticked_nodes_and_only_as_many_as_needed(e, monkeypatch):
    nodes_env(e, monkeypatch); wide(monkeypatch)
    pl.submit(N, e.r, profile="custom", picked=["genoa04", "genoa02", "genoa01", "thin01"])
    used = set(pins(e).values())
    assert used <= {"genoa04", "genoa02", "genoa01"} and "thin01" not in used and len(used) == 3
    a = next(c["argv"] for c in e.calls() if pins(e)[c["key"]] == "genoa04")
    assert a[a.index("-p") + 1] == "GENOA"

@pytest.mark.parametrize("picked", [[], ["genoa03"], ["nope"], ["genoa01", "genoa02", "genoa04", "thin01", "genoa01"]])
def test_custom_refuses_bad_node_lists(e, monkeypatch, picked):
    nodes_env(e, monkeypatch)
    with pytest.raises(ValueError): pl.submit(N, e.r, profile="custom", picked=picked)
    assert not e.calls()

def test_unknown_profile_refused(e):
    with pytest.raises(ValueError): pl.submit(N, e.r, profile="turbo")

###################################### performance metadata
def test_jobs_carry_their_metadata_target_and_ask(e):
    pl.submit(N, e.r)
    ids = {c["key"]: c["id"] for c in e.calls()}
    env = dict(l.split("=", 1) for l in (e.fake / f"env_{ids['alpine_A']}.txt").read_text().splitlines() if "=" in l)
    assert env["KV_META_TARGET"] == "A" and env["KV_META_STEP"] == "03_alpine"
    ask = __import__("json").loads(env["KV_ASK"])
    assert ask["cpus"] == 4 and ask["mem_mb"] == 8000 and "default" in ask["why"]
    env = dict(l.split("=", 1) for l in (e.fake / f"env_{ids['refs']}.txt").read_text().splitlines() if "=" in l)
    assert env["KV_META_TARGET"] == "_analysis" and env["KV_META_STEP"] == "refs"

@pytest.mark.parametrize("mode,rc", [("good", 0), ("fail", 7)])
def test_kv_job_writes_a_perf_record_next_to_the_sample_metadata(e, monkeypatch, mode, rc):
    import json
    for k, v in dict(KV_META_TARGET="A", KV_META_STEP="03_alpine", KV_IN_BYTES="412", SLURM_JOB_ID="4711", KV_ASK=json.dumps(dict(cpus=1, mem_mb=1000, time_min=60, why="default 1/1"))).items(): monkeypatch.setenv(k, v)
    (e.root / "src").mkdir(exist_ok=True); shutil.copy(f"{ROOT}/src/sample_meta.py", e.root / "src")
    r, o, out = kv(e, mode)
    assert r.returncode == rc and "perf metadata: meta/A.json" in o
    perf = json.load(open(out / "meta/A.json"))["steps"]["03_alpine"]["perf"]
    assert perf["jobid"] == "4711" and perf["asked"]["cpus"] == 1 and perf["used"]["exit"] == rc and perf["used"]["in_bytes"] == 412
    assert isinstance(perf["used"]["elapsed_s"], int) and perf["started"] and perf["ended"] and perf["sacct"] is None

def test_fill_perf_adds_sacct_view_and_covers_jobs_that_died_before_writing(e):
    import json
    pl.submit(N, e.r)
    ids = {c["key"]: c["id"] for c in e.calls()}
    meta = e.root / "results" / N / "meta"
    pl.sample_meta.update_perf(str(meta), "A", "03_alpine", dict(jobid=ids["alpine_A"], used=dict(exit=0)), str(e.root / "results" / N))
    e.put("sacct.txt", f"{ids['alpine_A']}|COMPLETED|00:50:00|00:30:00|0|16|32000M|2026-11-14T09:00:00|2026-11-14T09:00:30\n{ids['alpine_A']}.batch|COMPLETED|00:50:00|00:30:00|8192M|16||||\n"
                       f"{ids['lungo_B']}|OUT_OF_MEMORY|00:10:00|00:05:00|0|16|32000M|2026-11-14T09:00:00|2026-11-14T09:01:00\n{ids['refs']}|RUNNING|00:00:01|00:00:01|0|1|4000M|2026-11-14T09:00:00|2026-11-14T09:00:01\n")
    pl.fill_perf(N, e.r)
    a = json.load(open(meta / "A.json"))["steps"]["03_alpine"]["perf"]
    assert a["used"] == dict(exit=0) and a["sacct"]["state"] == "COMPLETED" and a["sacct"]["max_rss_gb"] == 8.0
    assert a["sacct"]["cpu_eff"] == round(100 * 50 / (30 * 16), 1) and a["sacct"]["mem_eff"] == 102.4 and a["sacct"]["wait_min"] == 0.5
    b = json.load(open(meta / "B.json"))["steps"]["04_lungo"]["perf"]
    assert b["sacct"]["state"] == "OUT_OF_MEMORY" and b["asked"]["mem_mb"] == 8000 and b["used"] is None
    assert not (meta / "_analysis.json").exists() or "refs" not in json.load(open(meta / "_analysis.json"))["steps"]

def test_custom_skips_nodes_whose_half_is_below_the_widest_job(e, monkeypatch):
    nodes_env(e, monkeypatch); wide(monkeypatch)
    pl.submit(N, e.r, profile="custom", picked=["thin01", "genoa04"])
    assert set(pins(e).values()) == {"genoa04"}
    assert "skipped thin01" in (e.root / "results" / N / "logs/node_pick.log").read_text()

def test_custom_with_only_too_small_nodes_is_refused(e, monkeypatch):
    nodes_env(e, monkeypatch); wide(monkeypatch)
    with pytest.raises(ValueError, match="widest job"): pl.submit(N, e.r, profile="custom", picked=["thin01"])
    assert not e.calls()
