# KNOCKIN-VAL

Wrapper to run three long-read CRISPR **knock-in** analysis tools on the same ONT amplicon data: **ALPINE**, **CRISPRLungo**, **CRISPResso2**.

Scope: Oxford Nanopore sequencing of CRISPR knock-in PCR amplicons. Only tools with a native knock-in readout are included.

## How to run
```bash
cd KNOCKIN-VAL
bash slurms/run_all.sh --sbatch     # cluster: submits every step with dependencies
bash slurms/run_all.sh              # workstation: same steps, one after another
cat results/summary_matrix.tsv      # knock-in % per tool x sample
```
Run from the repo root (SLURM jobs use the submit dir as root). Needs `conda` on PATH, plus `git` and `curl`. Nothing else has to exist first: the pipeline clones the tools, builds the envs, downloads the data and builds the references.

## Steps
| Step | Does | Writes |
|---|---|---|
| `01_clone` | clones the 3 tools at the pinned commits in `configs/tools.tsv` | `tools/` |
| `02_envs` | creates the 5 conda envs from `envs/*.yml` | `kv_*` envs |
| `03_fetch` | downloads the SRA runs, length-filters (3.5–7.5 kb); **all passing reads are kept, no subsampling** | `data/<label>.fastq.gz`, `data/read_stats.tsv` |
| `04_build_refs` | builds WT / knock-in references and the ALPINE config | `refs/` |
| `05_alpine` · `06_lungo` · `07_crispresso` | runs each tool on every read of every sample | `results/<tool>/` |
| `08_summary` | one knock-in % per tool x sample | `results/summary*.tsv` |

Every step is a standalone SLURM script: `sbatch slurms/06_lungo.sh` or `bash slurms/06_lungo.sh`. The per-sample steps are job arrays; run locally they loop over all samples.

## Parameters
Hardcoded at the top of each script. To change one without editing code:
```bash
bash slurms/06_lungo.sh --yaml-out   # dump this step's parameters
vim configs/param_configs.yaml            # edit them
bash slurms/06_lungo.sh --yaml-in    # rerun with them
```

## Repository contents
Scripts, envs, configs and docs only. `tools/ data/ refs/ results/ logs/` are created by the pipeline and gitignored.

Full documentation: **[Manual.md](Manual.md)**. Per-tool notes: [ALPINE](docs/manuals/ALPINE.md) · [CRISPRLungo](docs/manuals/CRISPRLungo.md) · [CRISPResso2](docs/manuals/CRISPResso2.md).
