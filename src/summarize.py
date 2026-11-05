#!/usr/bin/env python3
"""Collect real-data knock-in % (ALPINE, CRISPRLungo, CRISPResso2) into results/summary_real*.tsv."""
import argparse, csv, datetime, glob, json, os, re, resource, time
import yaml
from tqdm import tqdm

###################################### constants
T0 = time.time()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES, PARAM_YAML, NAME = f"{ROOT}/results", f"{ROOT}/configs/param_configs.yaml", "summarize"
SAMPLES = {"Mock_r1": "mock_electroporated", "NoDonor_r1": "rnp_no_donor", "dsDNA_r1": "rnp_dsDNA_donor", "ssDNA_r1": "rnp_ssDNA_donor", "ssCTS_r1": "rnp_ssCTS_donor"}
PARAMS = dict(lungo_min_insert_frac=0.8)
COLS = ["tool", "label", "condition", "reads_in", "reads_used", "ki_reads", "ki_pct", "metric", "notes"]

###################################### helpers
def log(m): print(f"[PYTHON-INFO] {m}", flush=True)
def tsv(p): return list(csv.DictReader(open(p), delimiter="\t"))
def pct(a, b): return round(100.0 * a / b, 2) if b else None
def yaml_io(p, a):
    c = (yaml.safe_load(open(PARAM_YAML)) if os.path.exists(PARAM_YAML) else None) or {}
    if a.yaml_in: p.update(c.get(NAME, {})); log(f"params read from {PARAM_YAML} [{NAME}]")
    if a.yaml_out: c[NAME] = p; yaml.safe_dump(c, open(PARAM_YAML, "w"), sort_keys=False); log(f"params written to {PARAM_YAML} [{NAME}]")
    return p

###################################### tool metrics
def alpine(label, d, p):
    hits = [h for h in glob.glob(f"{RES}/real/ALPINE/{label}/**/{label}_read_classification.txt", recursive=True) if "/cwl_local/" not in h]
    if not hits: return None
    rows = list(csv.reader(open(hits[0]), delimiter="\t")); cnt = {}
    for k, v in zip(rows[0], rows[-1]):
        try: cnt[k] = int(float(v))
        except ValueError: pass
    n, k = sum(cnt.values()), sum(v for c, v in cnt.items() if c.upper().startswith("HDR"))
    return dict(reads_used=n, ki_reads=k, ki_pct=pct(k, n), metric="HDR class / classified reads",
                notes=", ".join(f"{c} {pct(v, n)}%" for c, v in sorted(cnt.items(), key=lambda x: -x[1])[:5] if v))

def lungo(label, d, p):
    f = f"{RES}/real/CRISPRLungo/{label}/results/read_classification.txt"
    if not os.path.exists(f): return None
    rows, cls, k = tsv(f), {}, 0
    for r in rows:
        cls[r["Classification"]] = cls.get(r["Classification"], 0) + 1
        k += max([int(b) - int(a) + 1 for a, b in re.findall(r"inSeq_(\d+)to(\d+)inRef", r.get("Integration_info") or "")] or [0]) >= p["lungo_min_insert_frac"] * d["insert_len"]
    n = len(rows)
    return dict(reads_used=n, ki_reads=k, ki_pct=pct(k, n), metric=f"integration matching >={p['lungo_min_insert_frac']:.0%} of CAR insert / classified reads",
                notes=", ".join(f"{c} {pct(v, n)}%" for c, v in sorted(cls.items(), key=lambda x: -x[1])[:5]))

def crispresso(label, d, p):
    f = f"{RES}/real/CRISPResso2/CRISPResso_on_{label}/CRISPResso_quantification_of_editing_frequency.txt"
    if not os.path.exists(f): return None
    rows = tsv(f); n, rin = int(rows[0]["Reads_aligned_all_amplicons"]), int(rows[0]["Reads_in_input"])
    k = sum(int(r["Reads_aligned"]) for r in rows if r["Amplicon"] == "HDR"); wt = next(r for r in rows if r["Amplicon"] != "HDR")
    return dict(reads_used=n, ki_reads=k, ki_pct=pct(k, n), metric="HDR-amplicon reads / aligned reads",
                notes=f"input {rin}, aligned {n} ({pct(n, rin)}%), WT-assigned modified {float(wt['Modified%']):.1f}%")

TOOLS = {"ALPINE": alpine, "CRISPRLungo": lungo, "CRISPResso2": crispresso}

###################################### main
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--yaml-in", action="store_true"); ap.add_argument("--yaml-out", action="store_true")
    p = yaml_io(dict(PARAMS), ap.parse_args()); d = json.load(open(f"{ROOT}/refs/design.json"))["design"]
    sp = f"{ROOT}/data/real/subsample_stats.tsv"; sub = {r["label"]: r for r in tsv(sp)} if os.path.exists(sp) else {}
    out = []
    for tool, label in tqdm([(t, s) for t in TOOLS for s in SAMPLES], desc="[PYTHON-INFO] summarize", disable=None):
        r = dict(tool=tool, label=label, condition=SAMPLES[label], reads_in=sub.get(label, {}).get("subsampled", ""))
        r.update(TOOLS[tool](label, d, p) or dict(notes="missing output")); out.append(r)
    with open(f"{RES}/summary_real.tsv", "w") as fh:
        w = csv.DictWriter(fh, COLS, delimiter="\t", extrasaction="ignore"); w.writeheader(); [w.writerow({k: "" if r.get(k) is None else r.get(k, "") for k in COLS}) for r in out]
    ki = {(r["tool"], r["label"]): r.get("ki_pct") for r in out}
    mx = "tool\t" + "\t".join(SAMPLES) + "\n" + "".join(t + "\t" + "\t".join("NA" if ki[(t, s)] is None else str(ki[(t, s)]) for s in SAMPLES) + "\n" for t in TOOLS)
    open(f"{RES}/summary_real_matrix.tsv", "w").write(mx)
    for l in mx.splitlines(): log("KI% " + l.replace("\t", " | "))
    log(f"{datetime.datetime.now():%F %T} | elapsed {time.time() - T0:.1f} s | max RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576:.2f} GB")

if __name__ == "__main__":
    main()
