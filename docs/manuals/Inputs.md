# Shared inputs

One name per concept, identical as yaml key, bash variable and argparse flag. SLURM-derived values are not yaml params.

| Name | Meaning | Source / used by |
|---|---|---|
| `analysis` | the run's name; everything it produces lives in `results/<analysis>/` | `--config analysis=<name>`, every rule |
| `sample_id` | row key of the frozen `results/<analysis>/inputs/samples.tsv` | `filter` (srr), `lungo` (control), `summary` (condition); one job per sample |
| `fastq_path` | optional local FASTQ, from `results/<analysis>/inputs/samples/<sample_id>.json` | `filter`: used instead of downloading the SRA run |
| `ki_min_insert_frac` | `shared:` section of the frozen `params.yaml` | `alpine` (`truncated_cutoff`), `summary` (CRISPRLungo insert span) |
| `fastq` | `results/<analysis>/data/<sample_id>.fastq.gz` (length-filtered) | ALPINE `fastqfile`, CRISPRlungo positional |
| `wt_fasta` · `ki_fasta` · `insert_fasta` | `results/<analysis>/refs/TRAC_WT.fa` · `TRAC_KI.fa` · `CAR_insert.fa` | CRISPRlungo (reference, `--induced_sequence_path`, `--integration_file`) |
| `guide`, `primer_f`, `primer_r` | read from `results/<analysis>/refs/design.json` | `alpine`, `lungo` |
| `threads`, `mem_mb` | each rule's `threads:` and `resources:`, passed by snakemake | every tool |
| `KV_OUT` | `results/<analysis>`, exported by the Snakefile; every script writes only under it | all |
| `lungo.cleavage_pos`, `lungo.window` | CRISPRlungo `--cleavage_pos`, `--window` | `lungo` |
| `alpine.primer_check_length`, `alpine.data_type` | ALPINE job params | `alpine` |
| `KV_SIF` | override the image snakemake runs every rule in (default: `containers/ont-knockin-val.sif`, else the pinned GHCR digest) | `Snakefile` |

Data flow, all inside `results/<analysis>/` except the shared `data/raw/` download cache:
`inputs/` (frozen) -> `data/<sample_id>.fastq.gz` + `data/stats/` -> `refs/*` -> `ALPINE/`, `CRISPRLungo/` -> `summary*.tsv`.

## Metadata

| File | Written by | Holds |
|---|---|---|
| `configs/samples/<sample_id>.json`, copied to `results/<analysis>/inputs/samples/` | `src/gui_serve.py` (the form) | what the wet lab submitted: operator, date, cell type, donor format and dose, flow cell, basecaller, notes, optional `fastq_path` |
| `results/<analysis>/meta/<sample_id>.json` | `src/sample_meta.py`, via `kv_meta <sample_id> <step> k=v` | the submitted block, one record per step (parameters, read counts, SLURM job and array ids, timestamp), the pipeline commit, and the container image plus the two tool commits |
| `results/<analysis>/run.log`, `run_state.json` | `src/gui_serve.py` | the console's launch record: pid, mode, engine, image, start time, sample list |

`src/sample_meta.py` is the only writer of `results/<analysis>/meta/`. Steps never touch those files directly; they
call `kv_meta` with plain `key=value` pairs. Field definitions for the form live in
`configs/sample_schema.json`, which is the single source of truth for both the form and the JSON.
