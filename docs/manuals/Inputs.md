# Shared inputs

One name per concept, identical as yaml key, bash variable and argparse flag. SLURM-derived values are not yaml params.

| Name | Meaning | Source / used by |
|---|---|---|
| `sample_id` | row key of `configs/samples.tsv` (`sample_id`, `srr`, `condition`, `control`) | 03 (srr), 06 (control), 08 (condition); array task N = row N |
| `fastq` | `data/<sample_id>.fastq.gz` (length-filtered) | ALPINE `fastqfile`, CRISPRlungo / CRISPResso `--fastq_r1` |
| `wt_fasta` · `ki_fasta` · `insert_fasta` | `refs/TRAC_WT.fa` · `TRAC_KI.fa` · `CAR_insert.fa` | CRISPRlungo (reference, `--induced_sequence_path`, `--integration_file`), CRISPResso (`-a`, `-e`) |
| `guide`, `primer_f`, `primer_r` | read from `refs/design.json` | 05, 06, 07 |
| `threads`, `mem_mb` | from `SLURM_CPUS_PER_TASK`, `SLURM_MEM_PER_NODE` | every tool |
| `out_dir` | `results/<Tool>/<sample_id>` (CRISPResso: `results/CRISPResso2/CRISPResso_on_<sample_id>`); `refs` for build_refs | all |
| `lungo_cleavage_pos`, `lungo_window` | CRISPRlungo `--cleavage_pos`, `--window` | 06 |
| `crispresso_window_center`, `crispresso_window`, `crispresso_min_bq`, `crispresso_timeout` | CRISPResso `-wc`, `-w`, `--min_bp_quality_or_N`, `timeout` | 07 |
| `alpine_primer_check_length`, `alpine_data_type` | ALPINE job params | 05 |

Data flow: 03 `data/<sample_id>.fastq.gz` + `data/read_stats.tsv` -> 04 `refs/*` -> 05/06/07 `results/<Tool>/...` -> 08 `results/summary*.tsv`.
