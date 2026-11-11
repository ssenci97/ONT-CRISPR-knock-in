#!/usr/bin/env python3
"""Collect knock-in % (ALPINE, CRISPRLungo) on all length-passing reads into results/summary*.tsv."""
import argparse, csv, datetime, glob, json, os, re, resource, time
import yaml
from tqdm import tqdm

###################################### constants
T0 = time.time()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES, PARAM_YAML, NAME = f"{ROOT}/results", f"{ROOT}/configs/param_configs.yaml", "summarize"
SAMPLES_TSV = f"{ROOT}/configs/samples.tsv"
PARAMS = dict()
SHARED = dict(ki_min_insert_frac=0.8)
COLS = ["tool", "sample_id", "condition", "reads_in", "reads_used", "ki_reads", "ki_pct", "metric", "notes"]

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
    hits = [h for h in glob.glob(f"{RES}/ALPINE/{sample_id}/**/{sample_id}_read_classification.txt", recursive=True) if "/cwl_local/" not in h]
    if not hits: return None
    rows = list(csv.reader(open(hits[0]), delimiter="\t")); cnt = {}
    for k, v in zip(rows[0], rows[-1]):
        try: cnt[k] = int(float(v))
        except ValueError: pass
    n, k = sum(cnt.values()), sum(v for c, v in cnt.items() if c.upper().startswith("HDR"))
    return dict(reads_used=n, ki_reads=k, ki_pct=pct(k, n), metric=f"ALPINE HDR class (transgene >={p['ki_min_insert_frac']:.0%} of insert, both homology arms validated) / classified reads",
                notes=", ".join(f"{c} {pct(v, n)}%" for c, v in sorted(cnt.items(), key=lambda x: -x[1])[:5] if v))

def lungo(sample_id, d, p):
    f = f"{RES}/CRISPRLungo/{sample_id}/results/read_classification.txt"
    if not os.path.exists(f): return None
    reads, cls = {}, {}
    for r in tsv(f):
        rid = re.sub(r"_split_\d+$", "", r["Read_id"]); cls[r["Classification"]] = cls.get(r["Classification"], 0) + 1
        span = max([int(b) - int(a) + 1 for a, b in re.findall(r"CAR_insert_\d+to\d+inSeq_(\d+)to(\d+)inRef", r.get("Integration_info") or "")] or [0])
        reads[rid] = reads.get(rid, False) or span >= p["ki_min_insert_frac"] * d["insert_len"]
    n, k = len(reads), sum(reads.values())
    return dict(reads_used=n, ki_reads=k, ki_pct=pct(k, n), metric=f"reads with CAR_insert integration >={p['ki_min_insert_frac']:.0%} of insert / classified reads (split segments merged)",
                notes=", ".join(f"{c} {pct(v, n)}%" for c, v in sorted(cls.items(), key=lambda x: -x[1])[:5]))

TOOLS = {"ALPINE": alpine, "CRISPRLungo": lungo}

###################################### main
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--yaml-in", action="store_true"); ap.add_argument("--yaml-out", action="store_true")
    p = yaml_io({**SHARED, **PARAMS}, ap.parse_args()); d = json.load(open(f"{ROOT}/refs/design.json"))["design"]
    sp = f"{ROOT}/data/read_stats.tsv"; sub = {r["sample_id"]: r for r in tsv(sp)} if os.path.exists(sp) else {}
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
