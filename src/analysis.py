#!/usr/bin/env python3
"""Create or resume an analysis: validate the sample sheet and freeze inputs into results/<analysis_name>/inputs."""
import argparse, csv, datetime, hashlib, json, os, re, resource, shutil, sys, time

###################################### constants
T0 = time.time()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
ID_RE = re.compile(r"^[A-Za-z0-9_]+$")
SRR_RE = re.compile(r"^(SRR|ERR|DRR)[0-9]+$")

###################################### helpers
def log(m): print(f"[PYTHON-INFO] {m}", flush=True)

def read_sheet(p):
    return [r for r in csv.DictReader(open(p), delimiter="\t") if (r.get("sample_id") or "").strip()]

def submitted(root, sid):
    p = f"{root}/configs/samples/{sid}.json"
    return json.load(open(p)) if os.path.exists(p) else {}

def validate(samples):
    seen, errs = set(), []
    if not samples: return ["the sample sheet is empty"]
    for i, s in enumerate(samples, 1):
        sid = (s.get("sample_id") or "").strip()
        if not ID_RE.match(sid): errs.append(f"row {i}: sample_id {sid!r} must be letters, digits or underscore")
        if sid in seen: errs.append(f"row {i}: duplicate sample_id {sid!r}")
        seen.add(sid)
        if not (s.get("condition") or "").strip(): errs.append(f"row {i}: condition is required")
        srr, fq = (s.get("srr") or "").strip(), (s.get("fastq_path") or "").strip()
        if not srr and not fq: errs.append(f"row {i}: give either an SRA run accession or a local FASTQ path")
        if srr and not SRR_RE.match(srr): errs.append(f"row {i}: {srr!r} is not an SRA run accession")
        if fq and not (os.path.isabs(fq) and os.path.isfile(fq)): errs.append(f"row {i}: fastq_path {fq!r} must be an absolute path to an existing file")
    if not any(str(s.get("control")) in ("1", "true", "True") for s in samples):
        errs.append("at least one sample must be marked as negative control (CRISPRLungo needs it)")
    return errs

def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def analysis_dir(name, root=ROOT):
    if not NAME_RE.match(name or ""): raise ValueError(f"analysis name {name!r}: use letters, digits, _ . - (max 64)")
    return f"{root}/results/{name}"

def create(name, root=ROOT):
    """Freeze configs into results/<name>/inputs once; an existing analysis is resumed with its frozen inputs."""
    a = analysis_dir(name, root); inp = f"{a}/inputs"
    if os.path.exists(f"{inp}/samples.tsv"): return a, False, []
    rows = read_sheet(f"{root}/configs/samples.tsv")
    errs = validate([{**submitted(root, r["sample_id"]), **r} for r in rows])
    if errs: return a, False, errs
    tmp = f"{inp}.tmp"; shutil.rmtree(tmp, ignore_errors=True); os.makedirs(f"{tmp}/samples")
    shutil.copy(f"{root}/configs/samples.tsv", f"{tmp}/samples.tsv"); shutil.copy(f"{root}/configs/param_configs.yaml", f"{tmp}/params.yaml")
    for r in rows:
        if os.path.exists(f"{root}/configs/samples/{r['sample_id']}.json"): shutil.copy(f"{root}/configs/samples/{r['sample_id']}.json", f"{tmp}/samples/")
    sums = {os.path.relpath(f"{d}/{f}", tmp): sha256(f"{d}/{f}") for d, _, fs in os.walk(tmp) for f in fs}
    fq = {p: dict(size=os.stat(p).st_size, mtime=os.stat(p).st_mtime) for p in sorted({submitted(root, r["sample_id"]).get("fastq_path") if not r.get("fastq_path") else r["fastq_path"] for r in rows} - {None, ""}) if os.path.isfile(p)}
    json.dump(dict(analysis=name, created_at=f"{datetime.datetime.now():%F %T}", samples=[r["sample_id"] for r in rows], checksums=dict(sorted(sums.items())), fastq=fq), open(f"{tmp}/analysis.json", "w"), indent=2)
    os.replace(tmp, inp)
    return a, True, []

###################################### main
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("analysis_name")
    a = ap.parse_args()
    try: d, new, errs = create(a.analysis_name)
    except ValueError as e: sys.exit(f"[PYTHON-INFO] {e}")
    if errs: [log(f"!! {e}") for e in errs]; sys.exit(1)
    log(f"{'created' if new else 'resuming'} {os.path.relpath(d, ROOT)} (inputs frozen in {os.path.relpath(d, ROOT)}/inputs)")
    log(f"run: python3 src/pipeline.py {a.analysis_name}")
    log(f"{datetime.datetime.now():%F %T} | elapsed {time.time() - T0:.1f} s | max RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576:.2f} GB")

if __name__ == "__main__":
    main()
