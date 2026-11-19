#!/usr/bin/env python3
"""Shared knock-in design derivation: locate the primers and guide in a genomic window, trim the WT amplicon and build the KI allele from a donor FASTA or a supplementary template table."""

###################################### constants
COMP = str.maketrans("ACGTNacgtn", "TGCANtgcan")
MAX_SCAN_BP = 2000000
PARTS = {"Full Sequence": "full", "Left Homology Arm": "LHA", "Right Homology Arm": "RHA"}

###################################### sequence
def rc(s): return s.translate(COMP)[::-1]

def read_fasta(p):
    head, seq = "", []
    for l in open(p):
        if l.startswith(">"):
            if not head: head = l[1:].strip()
        else: seq.append(l.strip())
    return head, "".join(seq).upper()

def read_seq(p): return read_fasta(p)[1]

def best_hit(hay, nd):
    i = hay.find(nd)
    if i >= 0: return i, 0
    if not nd or len(nd) > len(hay): raise ValueError(f"sequence of {len(nd)} bp does not fit in a window of {len(hay)} bp")
    if len(hay) > MAX_SCAN_BP: raise ValueError(f"window is {len(hay):,} bp: too large to scan for an inexact match")
    return min(((j, sum(a != b for a, b in zip(hay[j:j + len(nd)], nd))) for j in range(len(hay) - len(nd) + 1)), key=lambda x: x[1])

def templates(p):
    import openpyxl
    out, cur = {}, None
    for row in openpyxl.load_workbook(p, read_only=True)["Table S1"].iter_rows(min_row=2, values_only=True):
        _, title, part, _, seq = (list(row) + [None] * 5)[:5]
        if title: cur = title.strip(); out[cur] = {}
        if cur and part and seq and part.strip() in PARTS: out[cur][PARTS[part.strip()]] = str(seq).replace(" ", "").upper()
    return out

###################################### derivation
def amplicon(g, f, r):
    fs, rs = g.find(f), g.find(rc(r))
    if fs < 0 or rs < 0: raise ValueError("primers not found in genomic window")
    return fs, rs, g[fs:rs + len(r)]

def guide_hit(wt, gd):
    gp = wt.find(gd)
    if gp >= 0: return gp, "+"
    gp = wt.find(rc(gd))
    if gp < 0: raise ValueError(f"guide {gd} not in WT amplicon")
    return gp, "-"

def cut_site(gp, n, off, strand): return gp + off if strand == "+" else gp + n - off

def arms_donor(wt, ki, flank_bp):
    n = min(len(wt), len(ki))
    a = next((i for i in range(n) if wt[i] != ki[i]), n)
    z = next((i for i in range(n) if wt[-1 - i] != ki[-1 - i]), n)
    if a + z >= n: raise ValueError("donor KI is not a WT-flanked allele")
    fl = min(flank_bp, a, len(wt) - z - a)
    return dict(t={"LHA": wt[a - fl:a], "RHA": wt[len(wt) - z:len(wt) - z + fl]}, lp=a - fl, lmm=0, rp=len(wt) - z, rmm=0, ins=ki[a:len(ki) - z], ki=ki, s=a)

def arms_table(wt, t):
    (lp, lmm), (rp, rmm) = best_hit(wt, t["LHA"]), best_hit(wt, t["RHA"])
    return dict(t=t, lp=lp, lmm=lmm, rp=rp, rmm=rmm, ins=t["full"][len(t["LHA"]):len(t["full"]) - len(t["RHA"])],
                ki=wt[:lp] + t["full"] + wt[rp + len(t["RHA"]):], s=lp + len(t["LHA"]))

def derive(g, p, donor=None, tbl=None):
    f, r = p["primer_f_specific"].upper(), p["primer_r_specific"].upper()
    fs, _, wt = amplicon(g, f, r)
    gd = p["guide"].upper()
    gp, strand = guide_hit(wt, gd)
    d = arms_donor(wt, donor, p["flank_bp"]) if donor is not None else arms_table(wt, tbl)
    return dict(d, wt=wt, gs=p["genomic_start_1based"] + fs, f=f, r=r, gd=gd, strand=strand, gp=gp,
                cut=cut_site(gp, len(gd), p["cut_offset_from_guide_5p"], strand), src="donor_ki_fasta" if donor is not None else "templates_xlsx")
