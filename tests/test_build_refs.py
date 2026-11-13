"""build_refs.py: synthetic locus, template and guide -> WT/KI references and design.json."""
import json, os, random
import openpyxl
from conftest import load

def test_build(tmp_path, monkeypatch):
    m = load("build_refs"); random.seed(42); rnd = lambda n: "".join(random.choice("ACGT") for _ in range(n))
    left, pf, a, lha, gd, rha, b, pr, right = rnd(200), rnd(21), rnd(100), rnd(80), rnd(23), rnd(80), rnd(100), rnd(22), rnd(200)
    wt = pf + a + lha + gd + rha + b + m.rc(pr)
    os.makedirs(tmp_path / "raw"); open(tmp_path / "raw/g.fa", "w").write(">g\n" + left + wt + right + "\n")
    ins = rnd(300); wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Table S1"
    ws.append(["#", "title", "part", "x", "seq"]); ws.append([1, "T", "Full Sequence", None, lha + ins + rha])
    ws.append([None, None, "Left Homology Arm", None, lha]); ws.append([None, None, "Right Homology Arm", None, rha]); wb.save(tmp_path / "raw/t.xlsx")
    monkeypatch.setattr(m, "ROOT", str(tmp_path)); monkeypatch.setattr(m, "PARAM_YAML", str(tmp_path / "none.yaml"))
    monkeypatch.setattr(m, "PARAMS", dict(m.PARAMS, genomic_fasta="raw/g.fa", genomic_start_1based=1000, templates_xlsx="raw/t.xlsx", template_title="T",
                                          guide=gd, primer_f_specific=pf, primer_r_specific=pr, primer_f_full=pf, primer_r_full=pr))
    monkeypatch.setattr("sys.argv", ["build_refs.py"]); m.main()
    d = json.load(open(tmp_path / "refs/design.json"))
    assert d["amplicon"]["length"] == len(wt)
    assert d["design"]["insert_len"] == 300 and d["design"]["LHA_mismatches"] == 0 and d["design"]["RHA_mismatches"] == 0
    assert d["design"]["guide_strand"] == "+" and d["design"]["cut_site_0b"] == len(pf + a + lha) + 18
    ki = open(tmp_path / "refs/TRAC_KI.fa").read().split("\n")[1]
    assert ki == pf + a + lha + ins + rha + b + m.rc(pr)
    assert open(tmp_path / "refs/CAR_insert.fa").read().split("\n")[1] == ins

def test_build_from_donor_fasta(tmp_path, monkeypatch):
    m = load("build_refs"); random.seed(7); rnd = lambda n: "".join(random.choice("ACGT") for _ in range(n))
    left, pf, a, gd, skipped, b, pr, right = rnd(200), rnd(21), rnd(900), rnd(22), rnd(1500), rnd(900), rnd(22), rnd(200)
    wt = pf + a + gd + skipped + b + m.rc(pr)
    cut, tail = len(pf + a) + 11, len(pf + a + gd + skipped)
    other = lambda c: next(x for x in "ACGT" if x != c)
    cassette = other(wt[cut]) + rnd(298) + other(wt[tail - 1])
    ki = wt[:cut] + cassette + wt[tail:]
    os.makedirs(tmp_path / "raw"); open(tmp_path / "raw/g.fa", "w").write(">g\n" + left + wt + right + "\n")
    open(tmp_path / "raw/donor.fa", "w").write(">ki\n" + ki + "\n")
    monkeypatch.setattr(m, "ROOT", str(tmp_path)); monkeypatch.setattr(m, "PARAM_YAML", str(tmp_path / "none.yaml"))
    monkeypatch.setattr(m, "PARAMS", dict(m.PARAMS, genomic_fasta="raw/g.fa", genomic_start_1based=1000, templates_xlsx="",
                                          donor_ki_fasta="raw/donor.fa", flank_bp=500, guide=gd, cut_offset_from_guide_5p=11,
                                          primer_f_specific=pf, primer_r_specific=pr, primer_f_full=pf, primer_r_full=pr))
    monkeypatch.setattr("sys.argv", ["build_refs.py"]); m.main()
    d = json.load(open(tmp_path / "refs/design.json"))["design"]
    assert d["arms_from"] == "donor_ki_fasta"
    assert d["insert_len"] == len(cassette) and d["ki_len"] == len(ki)
    assert d["LHA_mismatches"] == 0 and d["RHA_mismatches"] == 0
    assert d["deleted_wt_bp_between_arms"] == len(gd) + len(skipped) - 11
    assert open(tmp_path / "refs/TRAC_KI.fa").read().split("\n", 1)[1].replace("\n", "") == ki
    assert open(tmp_path / "refs/CAR_insert.fa").read().split("\n", 1)[1].replace("\n", "") == cassette
