# Shared inputs

One name per concept, identical as yaml key, bash variable and argparse flag. SLURM-derived values are not yaml params.

| Name | Meaning | Source / used by |
|---|---|---|
| `sample_id` | row key of `configs/samples.tsv` (`sample_id`, `srr`, `condition`, `control`) | 03 (srr), 06 (control), 07 (condition); array task N = row N |
| `fastq_path` | optional local FASTQ, from `configs/samples/<sample_id>.json` | 03: used instead of downloading the SRA run |
| `ki_min_insert_frac` | `shared:` yaml section, read by every step | 05 (ALPINE `truncated_cutoff`), 07 (CRISPRLungo insert span) |
| `fastq` | `data/<sample_id>.fastq.gz` (length-filtered) | ALPINE `fastqfile`, CRISPRlungo positional |
| `wt_fasta` · `ki_fasta` · `insert_fasta` | `refs/TRAC_WT.fa` · `TRAC_KI.fa` · `CAR_insert.fa` | CRISPRlungo (reference, `--induced_sequence_path`, `--integration_file`) |
| `guide`, `primer_f`, `primer_r` | read from `refs/design.json` | 05, 06 |
| `threads`, `mem_mb` | from `SLURM_CPUS_PER_TASK`, `SLURM_MEM_PER_NODE` | every tool |
| `out_dir` | `results/<Tool>/<sample_id>`; `refs` for build_refs | all |
| `lungo_cleavage_pos`, `lungo_window` | CRISPRlungo `--cleavage_pos`, `--window` | 06 |
| `alpine_primer_check_length`, `alpine_data_type` | ALPINE job params | 05 |
| `KV_SIF` / `KV_IMAGE` | apptainer/singularity `.sif` or docker/podman image; set to run every step inside the container | `slurms/analysis_env.sh`, all steps |
| `KV_BIND` | host path bound into the container (default `$KV_ROOT`) | `slurms/analysis_env.sh` |

Data flow: 03 `data/<sample_id>.fastq.gz` + `data/read_stats.tsv` -> 04 `refs/*` -> 05/06 `results/<Tool>/...` -> 07 `results/summary*.tsv`.

## Metadata

| File | Written by | Holds |
|---|---|---|
| `configs/samples/<sample_id>.json` | `src/gui_serve.py` (the form) | what the wet lab submitted: operator, date, cell type, donor format and dose, flow cell, basecaller, notes, optional `fastq_path` |
| `results/meta/<sample_id>.json` | `src/sample_meta.py`, via `kv_meta <sample_id> <step> k=v` | the submitted block, one record per step (parameters, read counts, SLURM job and array ids, timestamp), the pipeline commit, and the container image plus the two tool commits |
| `results/run.log`, `results/run_state.json` | `src/gui_serve.py` | the console's launch record: pid, mode, engine, image, start time, sample list |

`src/sample_meta.py` is the only writer of `results/meta/`. Steps never touch those files directly; they
call `kv_meta` with plain `key=value` pairs. Field definitions for the form live in
`configs/sample_schema.json`, which is the single source of truth for both the form and the JSON.
