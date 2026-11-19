"""design.py: the shared derivation finds the primers, guide and arms, and refuses what build_refs would refuse."""
import random
import pytest
from conftest import load

m = load("design")

def locus(seed=11):
    random.seed(seed); rnd = lambda n: "".join(random.choice("ACGT") for _ in range(n))
    left, pf, a, gd, skipped, b, pr, right = rnd(200), rnd(21), rnd(400), rnd(22), rnd(600), rnd(400), rnd(22), rnd(200)
    wt = pf + a + gd + skipped + b + m.rc(pr)
    cut, tail = len(pf + a) + 11, len(pf + a + gd + skipped)
    other = lambda c: next(x for x in "ACGT" if x != c)
    cassette = other(wt[cut]) + rnd(298) + other(wt[tail - 1])
    return dict(g=left + wt + right, wt=wt, ki=wt[:cut] + cassette + wt[tail:], cassette=cassette, pf=pf, pr=pr, gd=gd, cut=cut, left=left)

def params(L, **kw):
    return dict(primer_f_specific=L["pf"], primer_r_specific=L["pr"], guide=L["gd"], cut_offset_from_guide_5p=11,
                genomic_start_1based=1000, flank_bp=500, **kw)

def test_derive_from_a_donor_fasta():
    L = locus()
    d = m.derive(L["g"], params(L), donor=L["ki"])
    assert d["wt"] == L["wt"] and d["ki"] == L["ki"] and d["ins"] == L["cassette"]
    assert d["src"] == "donor_ki_fasta" and d["strand"] == "+" and d["cut"] == L["cut"]
    assert d["gs"] == 1000 + len(L["left"]) and d["lmm"] == 0 and d["rmm"] == 0

def test_derive_from_a_template_table():
    L = locus(3)
    lha, rha = L["wt"][100:180], L["wt"][-180:-100]
    tbl = dict(LHA=lha, RHA=rha, full=lha + "ACGT" * 50 + rha)
    d = m.derive(L["g"], params(L), tbl=tbl)
    assert d["src"] == "templates_xlsx" and d["ins"] == "ACGT" * 50 and d["lmm"] == 0 and d["rmm"] == 0

def test_missing_primers_and_guide_raise():
    L = locus()
    with pytest.raises(ValueError, match="primers not found"):
        m.derive(L["g"], params(L, **{}) | dict(primer_f_specific="A" * 30), donor=L["ki"])
    with pytest.raises(ValueError, match="guide"):
        m.derive(L["g"], params(L) | dict(guide="A" * 22), donor=L["ki"])

def test_a_donor_equal_to_the_wild_type_is_refused():
    L = locus()
    with pytest.raises(ValueError, match="WT-flanked"):
        m.arms_donor(L["wt"], L["wt"], 500)

def test_best_hit_is_exact_then_tolerant_then_refuses_a_huge_window():
    assert m.best_hit("AAACGTAAA", "ACGT") == (2, 0)
    assert m.best_hit("AAACGTAAA", "ACGA") == (2, 1)
    with pytest.raises(ValueError, match="too large"):
        m.best_hit("A" * (m.MAX_SCAN_BP + 1), "ACGT")

def test_read_fasta_keeps_the_header_and_joins_the_sequence(tmp_path):
    p = tmp_path / "w.fa"; p.write_text(">chromosome:GRCh38:14:1:9:1\nacgt\nACGT\n")
    assert m.read_fasta(str(p)) == ("chromosome:GRCh38:14:1:9:1", "ACGTACGT")
