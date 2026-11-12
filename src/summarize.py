#!/usr/bin/env python3
"""Collect knock-in % (ALPINE, CRISPRLungo) on all length-passing reads into results/summary*.tsv."""
import argparse, csv, datetime, glob, json, os, re, resource, time
import yaml
from tqdm import tqdm

###################################### constants
T0 = time.time()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "summarize"
OUT = RES = PARAM_YAML = SAMPLES_TSV = None
PARAMS = dict()
SHARED = dict(ki_min_insert_frac=0.8)
COLS = ["tool", "sample_id", "condition", "reads_in", "reads_used", "ki_reads", "ki_pct", "partial_reads", "partial_pct", "metric", "notes"]

###################################### helpers
def log(m): print(f"[PYTHON-INFO] {m}", flush=True)
def tsv(p): return list(csv.DictReader(open(p), delimiter="\t"))
def pct(a, b): return round(100.0 * a / b, 2) if b else None
def yaml_io(p, a):
    c = (yaml.safe_load(open(PARAM_YAML)) if os.path.exists(PARAM_YAML) else None) or {}
    p.update(c.get("shared", {}))
    if a.yaml_in: p.update(c.get(NAME, {})); log(f"params read from {PARAM_YAML} [{NAME}]")
    if a.yaml_out: c[NAME] = {k: v for k, v in p.items() if k not in SHARED}; yaml.safe_dump(c, open(PARAM_YAML, "w"), sort_keys=False); log(f"params written to {PARAM_YAML} [{NAME}]")
    return p

###################################### tool metrics
def alpine(sample_id, d, p):
    f = f"{RES}/ALPINE/{sample_id}/{sample_id}_read_classification.txt"
    if not os.path.exists(f): return None
    rows = list(csv.reader(open(f), delimiter="\t")); cnt = {}
    for k, v in zip(rows[0], rows[-1]):
        try: cnt[k] = int(float(v))
        except ValueError: pass
    n, k = sum(cnt.values()), sum(v for c, v in cnt.items() if c.upper().startswith("HDR"))
    part = sum(v for c, v in cnt.items() if c.upper().startswith("NON-HDR"))
    return dict(reads_used=n, ki_reads=k, ki_pct=pct(k, n), partial_reads=part, partial_pct=pct(part, n), metric=f"ALPINE HDR class (transgene >={p['ki_min_insert_frac']:.0%} of insert, both homology arms validated) / classified reads",
                notes=", ".join(f"{c} {pct(v, n)}%" for c, v in sorted(cnt.items(), key=lambda x: -x[1]) if v))

def union_len(spans):
    merged = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1] + 1: merged[-1][1] = max(merged[-1][1], b)
        else: merged.append([a, b])
    return sum(b - a + 1 for a, b in merged)

def lungo(sample_id, d, p):
    f = f"{RES}/CRISPRLungo/{sample_id}/results/read_classification.txt"
    if not os.path.exists(f): return None
    spans, cls = {}, {}
    for r in tsv(f):
        rid = re.sub(r"_split_\d+$", "", r["Read_id"])
        cls.setdefault(rid, r["Classification"])
        spans.setdefault(rid, []).extend((int(a), int(b)) for a, b in
            re.findall(r"CAR_insert_\d+to\d+inSeq_(\d+)to(\d+)inRef", r.get("Integration_info") or ""))
    need = p["ki_min_insert_frac"] * d["insert_len"]
    cov = {rid: union_len(s) for rid, s in spans.items()}
    cnt = {}
    for c in cls.values(): cnt[c] = cnt.get(c, 0) + 1
    n, k, part = len(cov), sum(c >= need for c in cov.values()), sum(0 < c < need for c in cov.values())
    return dict(reads_used=n, ki_reads=k, ki_pct=pct(k, n), partial_reads=part, partial_pct=pct(part, n), metric=f"reads whose CAR_insert integration covers >={p['ki_min_insert_frac']:.0%} of the insert (union of blocks) / classified reads",
                notes=", ".join(f"{c} {pct(v, n)}%" for c, v in sorted(cnt.items(), key=lambda x: -x[1])))

TOOLS = {"ALPINE": alpine, "CRISPRLungo": lungo}

def set_root(d):
    global OUT, RES, SAMPLES_TSV, PARAM_YAML
    OUT = RES = os.path.abspath(d)
    SAMPLES_TSV, PARAM_YAML = f"{OUT}/inputs/samples.tsv", f"{OUT}/inputs/params.yaml"

###################################### main
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--yaml-in", action="store_true"); ap.add_argument("--yaml-out", action="store_true")
    ap.add_argument("--analysis-dir", required=True); a = ap.parse_args(); set_root(a.analysis_dir)
    p = yaml_io({**SHARED, **PARAMS}, a); d = json.load(open(f"{OUT}/refs/design.json"))["design"]
    sub = {r["sample_id"]: r for sp in glob.glob(f"{OUT}/data/stats/*.tsv") for r in tsv(sp)}
    SAMPLES = {r["sample_id"]: r["condition"] for r in tsv(SAMPLES_TSV)}; out = []
    for tool, sample_id in tqdm([(t, s) for t in TOOLS for s in SAMPLES], desc="[PYTHON-INFO] summarize", disable=None):
        r = dict(tool=tool, sample_id=sample_id, condition=SAMPLES[sample_id], reads_in=sub.get(sample_id, {}).get("len_pass", ""))
        r.update(TOOLS[tool](sample_id, d, p) or dict(notes="missing output")); out.append(r)
    with open(f"{RES}/summary.tsv", "w") as fh:
        w = csv.DictWriter(fh, COLS, delimiter="\t", extrasaction="ignore"); w.writeheader(); [w.writerow({k: "" if r.get(k) is None else r.get(k, "") for k in COLS}) for r in out]
    ki = {(r["tool"], r["sample_id"]): r.get("ki_pct") for r in out}
    mx = "tool\t" + "\t".join(SAMPLES) + "\n" + "".join(t + "\t" + "\t".join("NA" if ki[(t, s)] is None else str(ki[(t, s)]) for s in SAMPLES) + "\n" for t in TOOLS)
    open(f"{RES}/summary_matrix.tsv", "w").write(mx)
    for l in mx.splitlines(): log("KI% " + l.replace("\t", " | "))
    log(f"{datetime.datetime.now():%F %T} | elapsed {time.time() - T0:.1f} s | max RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576:.2f} GB")

if __name__ == "__main__":
    main()
