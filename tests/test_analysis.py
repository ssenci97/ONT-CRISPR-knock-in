"""analysis.py: sample-sheet validation and the one-time freeze of results/<analysis_name>/inputs."""
import json, os
import pytest
from conftest import ROOT, load

a = load("analysis")

def repo(tmp_path, sheet, samples=None):
    os.makedirs(tmp_path / "configs/samples")
    (tmp_path / "configs/samples.tsv").write_text(sheet)
    (tmp_path / "configs/param_configs.yaml").write_text("shared:\n  ki_min_insert_frac: 0.8\n")
    for sid, d in (samples or {}).items(): (tmp_path / f"configs/samples/{sid}.json").write_text(json.dumps(d))
    return str(tmp_path)

SHEET = "sample_id\tsrr\tcondition\tcontrol\nA\tSRR1\tmock\t1\nB\tSRR2\tki\t0\n"

def test_freeze_then_resume(tmp_path):
    r = repo(tmp_path, SHEET, {"A": {"operator": "sam"}})
    d, new, errs = a.create("run1", r)
    assert new and errs == [] and d == f"{r}/results/run1"
    assert open(f"{d}/inputs/samples.tsv").read() == SHEET
    assert json.load(open(f"{d}/inputs/samples/A.json"))["operator"] == "sam"
    assert json.load(open(f"{d}/inputs/analysis.json"))["samples"] == ["A", "B"]
    (tmp_path / "configs/samples.tsv").write_text(SHEET.replace("SRR2", "SRR9"))
    d2, new2, errs2 = a.create("run1", r)
    assert (d2, new2, errs2) == (d, False, [])
    assert "SRR9" not in open(f"{d}/inputs/samples.tsv").read()

def test_second_analysis_is_separate(tmp_path):
    r = repo(tmp_path, SHEET)
    a.create("run1", r); a.create("run2", r)
    assert sorted(os.listdir(f"{r}/results")) == ["run1", "run2"]

def test_example_source_ignores_saved_sample_json(tmp_path):
    r = repo(tmp_path, SHEET, {"A": {"operator": "sam", "fastq_path": "/nope.fastq"}})
    src = tmp_path / "ex"; src.mkdir()
    (src / "samples.tsv").write_text(SHEET.replace("SRR2", "SRR7")); (src / "param_configs.yaml").write_text("fetch:\n  bioproject: X\n")
    d, new, errs = a.create("ex1", r, str(src))
    assert new and errs == []
    assert "SRR7" in open(f"{d}/inputs/samples.tsv").read() and "bioproject: X" in open(f"{d}/inputs/params.yaml").read()
    assert os.listdir(f"{d}/inputs/samples") == [] and json.load(open(f"{d}/inputs/analysis.json"))["source"] == "ex"

def test_bad_sheet_is_refused(tmp_path):
    r = repo(tmp_path, "sample_id\tsrr\tcondition\tcontrol\nA\tSRR1\tmock\t0\n")
    d, new, errs = a.create("run1", r)
    assert not new and any("control" in e for e in errs)
    assert not os.path.exists(f"{d}/inputs")

@pytest.mark.parametrize("name", ["", "../escape", "a/b", "x" * 65, "-bad"])
def test_bad_names_rejected(name):
    with pytest.raises(ValueError): a.analysis_dir(name)

def test_validate():
    ok = [{"sample_id": "A", "srr": "SRR1", "condition": "c", "control": "1"}]
    assert a.validate(ok) == []
    assert a.validate([]) == ["the sample sheet is empty"]
    assert any("control" in e for e in a.validate([dict(ok[0], control="0")]))
    assert any("duplicate" in e for e in a.validate(ok + ok))
    assert any("sample_id" in e for e in a.validate([dict(ok[0], sample_id="../x")]))
    assert any("accession" in e for e in a.validate([dict(ok[0], srr="foo")]))
    assert any("fastq_path" in e for e in a.validate([dict(ok[0], srr="", fastq_path="relative.fq")]))
    assert any("fastq_path" in e for e in a.validate([dict(ok[0], srr="", fastq_path="/no/such/file")]))

def test_control_tiers():
    row = {"sample_id": "A", "srr": "SRR1", "condition": "c"}
    assert a.tier(row) == "treated"
    assert a.tier(dict(row, control="1")) == "mock"
    assert a.tier(dict(row, control_tier="no_donor")) == "no_donor"
    assert a.tier(dict(row, control_tier="no_donor", control="1")) == "no_donor"
    assert a.validate([dict(row, control_tier="mock")]) == []
    assert a.validate([dict(row, control_tier="no_donor")]) == []
    assert any("control_tier" in e for e in a.validate([dict(row, control_tier="treated")]))
    assert any("one of" in e for e in a.validate([dict(row, control_tier="nonsense")]))

def test_control_sample_prefers_mock_whatever_the_row_order():
    treated = {"control_tier": "treated"}
    nod, mock = {"control_tier": "no_donor"}, {"control_tier": "mock"}
    assert a.control_sample({"A": treated, "B": nod, "C": mock}) == "C"
    assert a.control_sample({"A": mock, "B": nod}) == "A"
    assert a.control_sample({"A": treated, "B": nod}) == "B"
    assert a.control_sample({"A": treated}) is None
    assert a.control_sample({"A": treated, "B": {"control": "1"}}) == "B"
