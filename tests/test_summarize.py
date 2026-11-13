"""summarize.py: knock-in % from fixture ALPINE and CRISPRLungo outputs in one analysis directory."""
import json, os, subprocess, sys
from conftest import ROOT

def write(p, s):
    os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(s)

def setup(d, sheet):
    write(f"{d}/inputs/samples.tsv", sheet)
    write(f"{d}/inputs/params.yaml", "shared:\n  ki_min_insert_frac: 0.8\nsummarize: {}\n")
    write(f"{d}/refs/design.json", json.dumps({"design": {"insert_len": 100}}))

def run(d):
    subprocess.run([sys.executable, f"{ROOT}/src/summarize.py", "--analysis-dir", d], check=True, capture_output=True)
    return [l.split("\t") for l in open(f"{d}/summary_matrix.tsv").read().split("\n") if l]

def test_matrix(tmp_path):
    d = str(tmp_path / "results" / "run1")
    setup(d, "sample_id\tsrr\tcondition\tcontrol\nA\tSRR1\tmock\t1\nB\tSRR2\tki\t0\n")
    write(f"{d}/data/stats/A.tsv", "sample_id\trun\traw_reads\tlen_pass\nA\tSRR1\t10\t8\n")
    write(f"{d}/ALPINE/A/A_read_classification.txt", "WT\tHDR\n9\t1\n")
    write(f"{d}/ALPINE/B/B_read_classification.txt", "WT\tHDR_CD19\tPartial\n2\t6\t2\n")
    hdr = "Read_id\tClassification\tIntegration_info\n"
    write(f"{d}/CRISPRLungo/A/results/read_classification.txt", hdr + "r1\tWT\t\nr2\tWT\t\n")
    write(f"{d}/CRISPRLungo/B/results/read_classification.txt", hdr +
          "r1\tKI\tCAR_insert_1to50inSeq_1to50inRef\nr1_split_1\tKI\tCAR_insert_1to40inSeq_51to90inRef\n"
          "r2\tKI\tCAR_insert_1to50inSeq_1to50inRef\nr3\tWT\t\nr4\tWT\t\n")
    rows = run(d)
    assert rows[0] == ["tool", "A", "B"]
    assert rows[1] == ["ALPINE", "10.0", "60.0"]
    assert rows[2] == ["CRISPRLungo", "0.0", "25.0"]
    s = {(r[0], r[1]): r for r in (l.split("\t") for l in open(f"{d}/summary.tsv").read().split("\n")[1:] if l)}
    assert s[("CRISPRLungo", "B")][7:9] == ["1", "25.0"]
    assert s[("ALPINE", "B")][7] == "0"
    c = [l.split("\t") for l in open(f"{d}/summary_classes.tsv").read().split("\n")[1:] if l]
    g = {}
    for t, sid, cat, _, n, _ in c: g[(t, sid, cat)] = g.get((t, sid, cat), 0) + int(n)
    assert g[("ALPINE", "B", "Full knock-in")] == 6 and g[("ALPINE", "B", "Unedited")] == 2 and g[("ALPINE", "B", "Other")] == 2
    assert g[("CRISPRLungo", "B", "Full knock-in")] == 1 and g[("CRISPRLungo", "B", "Partial knock-in")] == 1 and g[("CRISPRLungo", "B", "Unedited")] == 2
    assert sum(v for (t, sid, _), v in g.items() if (t, sid) == ("CRISPRLungo", "B")) == int(s[("CRISPRLungo", "B")][4])

def test_category_mapping():
    import importlib.util
    spec = importlib.util.spec_from_file_location("summarize", f"{ROOT}/src/summarize.py"); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    want = {"HDR-CD19": 0, "Non-HDR-without-ITR": 1, "Unmodified-with-SNP": 2, "WT": 2, "DEL/INS-small": 3, "Sub": 3, "LargeIns": 4, "DEL/INS-large": 4, "INV": 4, "ComplexWithLargeMut": 4, "Unclassified": 5}
    assert {c: m.CATEGORIES.index(m.category(c)) for c in want} == want

def test_missing_output_is_na(tmp_path):
    d = str(tmp_path / "results" / "run1")
    setup(d, "sample_id\tsrr\tcondition\tcontrol\nA\tSRR1\tmock\t1\n")
    assert run(d) == [["tool", "A"], ["ALPINE", "NA"], ["CRISPRLungo", "NA"]]
