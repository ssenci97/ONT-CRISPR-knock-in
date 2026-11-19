#!/usr/bin/env python3
"""Build WT/KI amplicon references, design.json and ALPINE inputs for the TRAC CD19-CAR (AsCas12a) dataset."""
import argparse, datetime, json, os, resource, sys, time
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from design import derive, rc, read_seq, templates

###################################### constants
T0 = time.time()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARAM_YAML = f"{ROOT}/configs/param_configs.yaml"
NAME = "build_refs"
PARAMS = dict(
    genomic_fasta="data/raw_refs/hg38_chr14_22540000_22560000.fa", genomic_start_1based=22540000,
    templates_xlsx="data/raw_refs/supp/mmc2.xlsx", template_title="TRAC CD19-CAR HDR template for editing with AsCas12a",
    guide="GAGTCTCTCAGCTGGTACACGGC", cut_offset_from_guide_5p=18,
    primer_f_full="TTTCTGTTGGTGCTGATATTGCTTCAATCACTGCTGTGTCCCT", primer_r_full="ACTTGCCTGTCGCTCTATCTTCTCCCACCCCAGACCTCCTAGTT",
    primer_f_specific="TTCAATCACTGCTGTGTCCCT", primer_r_specific="TCCCACCCCAGACCTCCTAGTT", donor_ki_fasta="", flank_bp=500, out_dir="refs")

###################################### helpers
def log(m): print(f"[PYTHON-INFO] {m}", flush=True)
def write_fasta(p, recs):
    with open(p, "w") as fh:
        for n, s in recs: fh.write(f">{n}\n{s}\n")
def yaml_io(p, a):
    c = (yaml.safe_load(open(PARAM_YAML)) if os.path.exists(PARAM_YAML) else None) or {}
    if a.yaml_in: p.update(c.get(NAME, {})); log(f"params read from {PARAM_YAML} [{NAME}]")
    if a.yaml_out: c[NAME] = p; yaml.safe_dump(c, open(PARAM_YAML, "w"), sort_keys=False); log(f"params written to {PARAM_YAML} [{NAME}]")
    return p
def template(p):
    ts = templates(p["templates_xlsx"])
    if p["template_title"] not in ts: raise ValueError(f"template_title {p['template_title']!r} not in {p['templates_xlsx']}")
    return ts[p["template_title"]]

###################################### main
def main():
    global PARAM_YAML
    ap = argparse.ArgumentParser(); ap.add_argument("--yaml-in", action="store_true"); ap.add_argument("--yaml-out", action="store_true")
    ap.add_argument("--params"); ap.add_argument("--out-dir"); a = ap.parse_args()
    if a.params: PARAM_YAML = os.path.abspath(a.params)
    os.chdir(ROOT); p = yaml_io(dict(PARAMS), a)
    o = os.path.abspath(a.out_dir) if a.out_dir else p["out_dir"]; os.makedirs(f"{o}/alpine", exist_ok=True)
    try: d = derive(read_seq(p["genomic_fasta"]), p, read_seq(p["donor_ki_fasta"]) if p["donor_ki_fasta"] else None, None if p["donor_ki_fasta"] else template(p))
    except ValueError as e: sys.exit(f"[PYTHON-INFO] {e}")
    wt, ki, ins, t, cut, s = d["wt"], d["ki"], d["ins"], d["t"], d["cut"], d["s"]
    write_fasta(f"{o}/TRAC_WT.fa", [("TRAC_WT", wt)]); write_fasta(f"{o}/TRAC_KI.fa", [("TRAC_KI", ki)]); write_fasta(f"{o}/CAR_insert.fa", [("CAR_insert", ins)])
    write_fasta(f"{o}/alpine/ref.fa", [("WT_TRAC", wt), ("Ref_HDR_CD19", ki)])
    with open(f"{o}/alpine/config.tsv", "w") as fh:
        fh.write("#AAV_Vector\tRef_Name\tRef_Type\tITR1_start\tITR1_end\tgene_start\tgene_end\tITR2_start\tITR2_end\n"
                 f"CD19\tWT_TRAC\tWT\tNA\tNA\t{cut}\t{cut + 1}\tNA\tNA\nCD19\tRef_HDR_CD19\tHDR\tNA\tNA\t{s + 1}\t{s + len(ins)}\tNA\tNA\n")
    dj = {"amplicon": {"name": "TRAC_WT", "length": len(wt), "hg38": f"chr14:{d['gs']}-{d['gs'] + len(wt) - 1}", "primer_f": d["f"], "primer_r": d["r"],
                       "primer_f_full": p["primer_f_full"], "primer_r_full": p["primer_r_full"]},
          "design": {"template_title": p["template_title"], "arms_from": d["src"], "guide": d["gd"], "guide_strand": d["strand"], "guide_start_0b": d["gp"], "cut_site_0b": cut,
                     "LHA_wt_0b": [d["lp"], d["lp"] + len(t["LHA"])], "LHA_mismatches": d["lmm"], "RHA_wt_0b": [d["rp"], d["rp"] + len(t["RHA"])], "RHA_mismatches": d["rmm"],
                     "deleted_wt_bp_between_arms": d["rp"] - s, "insert_len": len(ins), "ki_len": len(ki), "insert_in_ki_0b": [s, s + len(ins)],
                     "LHA_seq": t["LHA"], "RHA_seq": t["RHA"]}}
    json.dump(dj, open(f"{o}/design.json", "w"), indent=2)
    log(f"WT {len(wt)} bp ({dj['amplicon']['hg38']}), guide {d['strand']} at {d['gp']}, cut after {cut}, arms mismatches {d['lmm']}/{d['rmm']}, insert {len(ins)} bp, KI {len(ki)} bp")
    log(f"{datetime.datetime.now():%F %T} | elapsed {time.time() - T0:.1f} s | max RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576:.2f} GB")

if __name__ == "__main__":
    main()
