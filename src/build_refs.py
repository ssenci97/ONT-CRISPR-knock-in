#!/usr/bin/env python3
"""Build WT/KI amplicon references, design.json and ALPINE inputs for the TRAC CD19-CAR (AsCas12a) dataset."""
import argparse, datetime, json, os, resource, sys, time
import openpyxl, yaml

###################################### constants
T0 = time.time()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARAM_YAML = f"{ROOT}/configs/param_configs.yaml"
NAME = "build_refs"
COMP = str.maketrans("ACGTNacgtn", "TGCANtgcan")
PARAMS = dict(
    genomic_fasta="data/raw_refs/hg38_chr14_22540000_22560000.fa", genomic_start_1based=22540000,
    templates_xlsx="data/raw_refs/supp/mmc2.xlsx", template_title="TRAC CD19-CAR HDR template for editing with AsCas12a",
    guide="GAGTCTCTCAGCTGGTACACGGC", cut_offset_from_guide_5p=18,
    primer_f_full="TTTCTGTTGGTGCTGATATTGCTTCAATCACTGCTGTGTCCCT", primer_r_full="ACTTGCCTGTCGCTCTATCTTCTCCCACCCCAGACCTCCTAGTT",
    primer_f_specific="TTCAATCACTGCTGTGTCCCT", primer_r_specific="TCCCACCCCAGACCTCCTAGTT", outdir="refs")

###################################### helpers
def log(m): print(f"[PYTHON-INFO] {m}", flush=True)
def rc(s): return s.translate(COMP)[::-1]
def read_seq(p): return "".join(l.strip() for l in open(p) if not l.startswith(">")).upper()
def write_fasta(p, recs):
    with open(p, "w") as fh:
        for n, s in recs: fh.write(f">{n}\n{s}\n")
def templates(p):
    out, cur, keys = {}, None, {"Full Sequence": "full", "Left Homology Arm": "LHA", "Right Homology Arm": "RHA"}
    for row in openpyxl.load_workbook(p, read_only=True)["Table S1"].iter_rows(min_row=2, values_only=True):
        _, title, part, _, seq = (list(row) + [None] * 5)[:5]
        if title: cur = title.strip(); out[cur] = {}
        if cur and part and seq and part.strip() in keys: out[cur][keys[part.strip()]] = str(seq).replace(" ", "").upper()
    return out
def best_hit(hay, nd):
    i = hay.find(nd)
    if i >= 0: return i, 0
    return min(((j, sum(a != b for a, b in zip(hay[j:j + len(nd)], nd))) for j in range(len(hay) - len(nd) + 1)), key=lambda x: x[1])
def yaml_io(p, a):
    c = (yaml.safe_load(open(PARAM_YAML)) if os.path.exists(PARAM_YAML) else None) or {}
    if a.yaml_in: p.update(c.get(NAME, {})); log(f"params read from {PARAM_YAML} [{NAME}]")
    if a.yaml_out: c[NAME] = p; yaml.safe_dump(c, open(PARAM_YAML, "w"), sort_keys=False); log(f"params written to {PARAM_YAML} [{NAME}]")
    return p

###################################### main
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--yaml-in", action="store_true"); ap.add_argument("--yaml-out", action="store_true")
    p = yaml_io(dict(PARAMS), ap.parse_args()); os.chdir(ROOT); o = p["outdir"]; os.makedirs(f"{o}/alpine", exist_ok=True)
    g = read_seq(p["genomic_fasta"]); f, r = p["primer_f_specific"].upper(), p["primer_r_specific"].upper(); fs, rs = g.find(f), g.find(rc(r))
    if fs < 0 or rs < 0: sys.exit("[PYTHON-INFO] primers not found in genomic window")
    wt, gs = g[fs:rs + len(r)], p["genomic_start_1based"] + fs
    t, gd = templates(p["templates_xlsx"])[p["template_title"]], p["guide"].upper()
    gp, strand = (wt.find(gd), "+") if wt.find(gd) >= 0 else (wt.find(rc(gd)), "-")
    if gp < 0: sys.exit(f"[PYTHON-INFO] guide {gd} not in WT amplicon")
    off = p["cut_offset_from_guide_5p"]; cut = gp + off if strand == "+" else gp + len(gd) - off
    (lp, lmm), (rp, rmm) = best_hit(wt, t["LHA"]), best_hit(wt, t["RHA"])
    ins = t["full"][len(t["LHA"]):len(t["full"]) - len(t["RHA"])]; ki = wt[:lp] + t["full"] + wt[rp + len(t["RHA"]):]; s = lp + len(t["LHA"])
    write_fasta(f"{o}/TRAC_WT.fa", [("TRAC_WT", wt)]); write_fasta(f"{o}/TRAC_KI.fa", [("TRAC_KI", ki)]); write_fasta(f"{o}/CAR_insert.fa", [("CAR_insert", ins)])
    write_fasta(f"{o}/alpine/ref.fa", [("WT_TRAC", wt), ("Ref_HDR_CD19", ki)])
    with open(f"{o}/alpine/config.tsv", "w") as fh:
        fh.write("#AAV_Vector\tRef_Name\tRef_Type\tITR1_start\tITR1_end\tgene_start\tgene_end\tITR2_start\tITR2_end\n"
                 f"CD19\tWT_TRAC\tWT\tNA\tNA\t{cut}\t{cut + 1}\tNA\tNA\nCD19\tRef_HDR_CD19\tHDR\tNA\tNA\t{s + 1}\t{s + len(ins)}\tNA\tNA\n")
    d = {"amplicon": {"name": "TRAC_WT", "length": len(wt), "hg38": f"chr14:{gs}-{gs + len(wt) - 1}", "primer_f": f, "primer_r": r,
                      "primer_f_full": p["primer_f_full"], "primer_r_full": p["primer_r_full"]},
         "design": {"template_title": p["template_title"], "guide": gd, "guide_strand": strand, "guide_start_0b": gp, "cut_site_0b": cut,
                    "LHA_wt_0b": [lp, lp + len(t["LHA"])], "LHA_mismatches": lmm, "RHA_wt_0b": [rp, rp + len(t["RHA"])], "RHA_mismatches": rmm,
                    "deleted_wt_bp_between_arms": rp - s, "insert_len": len(ins), "ki_len": len(ki), "insert_in_ki_0b": [s, s + len(ins)],
                    "LHA_seq": t["LHA"], "RHA_seq": t["RHA"]}}
    json.dump(d, open(f"{o}/design.json", "w"), indent=2)
    log(f"WT {len(wt)} bp ({d['amplicon']['hg38']}), guide {strand} at {gp}, cut after {cut}, arms mismatches {lmm}/{rmm}, insert {len(ins)} bp, KI {len(ki)} bp")
    log(f"{datetime.datetime.now():%F %T} | elapsed {time.time() - T0:.1f} s | max RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576:.2f} GB")

if __name__ == "__main__":
    main()
