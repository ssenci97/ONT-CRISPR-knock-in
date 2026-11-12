import csv, json, os, sys, yaml
from snakemake.utils import min_version
from snakemake.settings.types import DeploymentMethod

min_version("8.0")

###################################### constants
ROOT = workflow.basedir
NAME = config.get("analysis") or sys.exit("[SLURM-INFO] give an analysis: --config analysis=<name> (create it with python3 src/analysis.py <name>)")
A = f"results/{NAME}"
INP = f"{A}/inputs"
os.path.exists(f"{INP}/samples.tsv") or sys.exit(f"[SLURM-INFO] {INP}/samples.tsv missing: create the analysis first with python3 src/analysis.py {NAME}")
DeploymentMethod.APPTAINER in workflow.deployment_settings.deployment_method or sys.exit(
    "[SLURM-INFO] refusing to run natively: use --profile profiles/slurm (or --sdm apptainer)")
P = yaml.safe_load(open(f"{INP}/params.yaml"))
SIF = f"{ROOT}/containers/ont-knockin-val.sif"
REF = open(f"{ROOT}/containers/images.env").read().split("KV_IMAGE_REF=")[1].split()[0]
IMAGE = os.environ.get("KV_SIF") or (SIF if os.path.exists(SIF) else f"docker://{REF}")
SAMPLES = {r["sample_id"]: r for r in csv.DictReader(open(f"{INP}/samples.tsv"), delimiter="\t") if r["sample_id"]}
CONTROLS = [s for s, r in SAMPLES.items() if r.get("control") == "1"]
FRAC = P["shared"]["ki_min_insert_frac"]
REFS = [f"{A}/refs/{f}" for f in ("TRAC_WT.fa", "TRAC_KI.fa", "CAR_insert.fa", "alpine/ref.fa", "alpine/config.tsv", "design.json")]
SAMPLES or sys.exit(f"[SLURM-INFO] {INP}/samples.tsv has no samples")
CONTROLS or sys.exit(f"[SLURM-INFO] {INP}/samples.tsv: no sample has control=1 (CRISPRLungo needs one)")

container: IMAGE
shell.prefix(f"set -euo pipefail; export PATH=/opt/conda/envs/kv/bin:$PATH TOOLS=/opt/tools KV_ROOT={ROOT} KV_OUT=$PWD/{A} KV_IMAGE={IMAGE} "
             "HOME=$PWD PYTHONNOUSERSITE=1 MPLBACKEND=Agg QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=${{TMPDIR:-/tmp}}/mpl; ")
wildcard_constraints: sample="[A-Za-z0-9_]+", run="[A-Za-z0-9]+"

###################################### helpers
def submitted(s):
    p = f"{INP}/samples/{s}.json"
    return json.load(open(p)) if os.path.exists(p) else {}

def raw_fastq(w):
    return SAMPLES[w.sample].get("fastq_path") or submitted(w.sample).get("fastq_path") or f"data/raw/{SAMPLES[w.sample]['srr']}.fastq.gz"

###################################### targets
rule all:
    input: f"{A}/summary.tsv", f"{A}/summary_matrix.tsv"

###################################### 01 fetch (raw downloads are a cache shared by all analyses)
rule ena:
    output: f"data/meta/{P['fetch']['bioproject']}_ena.tsv"
    params: bp=P["fetch"]["bioproject"]
    log: f"{A}/logs/01_fetch/ena.log"
    shell: "curl -sf 'https://www.ebi.ac.uk/ena/portal/api/filereport?accession={params.bp}&result=read_run&fields=run_accession,read_count&limit=0' > {output} 2> {log}"

rule download:
    input: rules.ena.output
    output: "data/raw/{run}.fastq.gz"
    log: f"{A}/logs/01_fetch/download_{{run}}.log"
    benchmark: f"{A}/logs/01_fetch/download_{{run}}.bench.tsv"
    threads: 16
    resources: mem_mb=32000, runtime=720
    shell: "bash {ROOT}/src/download.sh {wildcards.run} {input} {output} {threads} > {log} 2>&1"

rule filter:
    input: raw_fastq
    output: fq=f"{A}/data/{{sample}}.fastq.gz", stats=f"{A}/data/stats/{{sample}}.tsv"
    params: lo=P["fetch"]["min_len"], hi=P["fetch"]["max_len"], run=lambda w: SAMPLES[w.sample]["srr"] or "local"
    log: f"{A}/logs/01_fetch/filter_{{sample}}.log"
    benchmark: f"{A}/logs/01_fetch/filter_{{sample}}.bench.tsv"
    threads: 16
    resources: mem_mb=32000, runtime=240
    shell: "bash {ROOT}/src/filter.sh {wildcards.sample} {params.run} {input} {output.fq} {output.stats} {params.lo} {params.hi} {threads} > {log} 2>&1"

###################################### 02 references
rule refs:
    output: REFS
    log: f"{A}/logs/02_refs/refs.log"
    benchmark: f"{A}/logs/02_refs/refs.bench.tsv"
    threads: 1
    resources: mem_mb=8000, runtime=60
    shell: "bash {ROOT}/src/refs.sh > {log} 2>&1"

###################################### 03 ALPINE
rule alpine:
    input: fq=f"{A}/data/{{sample}}.fastq.gz", refs=REFS
    output: f"{A}/ALPINE/{{sample}}/{{sample}}_read_classification.txt"
    params: pcl=P["alpine"]["primer_check_length"], dt=P["alpine"]["data_type"], out=lambda w: f"{A}/ALPINE/{w.sample}"
    log: f"{A}/logs/03_alpine/{{sample}}.log"
    benchmark: f"{A}/logs/03_alpine/{{sample}}.bench.tsv"
    threads: 32
    resources: mem_mb=128000, runtime=1440
    shell: "bash {ROOT}/src/alpine.sh {wildcards.sample} {input.fq} {params.out} {params.pcl} {params.dt} {FRAC} {threads} {resources.mem_mb} > {log} 2>&1"

###################################### 04 CRISPRLungo
rule lungo:
    input: fq=f"{A}/data/{{sample}}.fastq.gz", ctrl=f"{A}/data/{CONTROLS[0]}.fastq.gz", refs=REFS
    output: f"{A}/CRISPRLungo/{{sample}}/results/read_classification.txt"
    params: cp=P["lungo"]["cleavage_pos"], win=P["lungo"]["window"], ctrl=CONTROLS[0], out=f"{A}/CRISPRLungo"
    log: f"{A}/logs/04_lungo/{{sample}}.log"
    benchmark: f"{A}/logs/04_lungo/{{sample}}.bench.tsv"
    threads: 32
    resources: mem_mb=128000, runtime=1440
    shell: "bash {ROOT}/src/lungo.sh {wildcards.sample} {input.fq} {input.ctrl} {params.ctrl} {params.out} {params.cp} {params.win} {threads} > {log} 2>&1"

###################################### 05 summary
rule summary:
    input:
        expand(f"{A}/ALPINE/{{s}}/{{s}}_read_classification.txt", s=SAMPLES),
        expand(f"{A}/CRISPRLungo/{{s}}/results/read_classification.txt", s=SAMPLES),
        expand(f"{A}/data/stats/{{s}}.tsv", s=SAMPLES), f"{A}/refs/design.json"
    output: f"{A}/summary.tsv", f"{A}/summary_matrix.tsv"
    log: f"{A}/logs/05_summary/summary.log"
    threads: 1
    resources: mem_mb=4000, runtime=30
    shell: "{{ bash {ROOT}/src/common.sh && python3 {ROOT}/src/summarize.py --analysis-dir $KV_OUT; }} > {log} 2>&1"
