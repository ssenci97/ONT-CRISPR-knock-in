# KNOCKIN-VAL

| | |
|---|---|
| **What** | runs ALPINE and CRISPRLungo on the same ONT knock-in amplicons |
| **Scope** | Oxford Nanopore, CRISPR knock-in PCR amplicons; tools with a native knock-in readout only |
| **Removed** | CRISPResso2 (2026-11-11): licence forbids redistribution → [LICENSES.md](LICENSES.md) |
| **Full reference** | [Manual.md](Manual.md) · [ALPINE](docs/manuals/ALPINE.md) · [CRISPRLungo](docs/manuals/CRISPRLungo.md) · [Inputs](docs/manuals/Inputs.md) |

## Quick start (Orfeo)

| Step | Where | Command |
|---|---|---|
| 1. build | cluster, repo root | `containers/build.sh pull` |
| 2. start | cluster, same shell | `python3 src/gui_serve.py` |
| 3. node name | cluster, same shell | `hostname -f` |
| 4. tunnel | laptop | `ssh -J <user>@195.14.102.215 -L 8000:127.0.0.1:8000 -N <user>@<node>` |
| 5. open | laptop browser | http://127.0.0.1:8000/ |

| Automatic | Done by |
|---|---|
| `module load singularity` | `build.sh` (line 4) and `gui_serve.py` |
| snakemake env | `gui_serve.py`: finds `kv_snakemake`, else creates `.kv_env/` from `envs/snakemake.yml` |

![console](docs/img/06_console.svg)

## Console

| Term | Definition |
|---|---|
| **Samples** tab | one card per sample → `configs/samples.tsv` + `configs/samples/<sample_id>.json` |
| **Run** tab | name an analysis → snakemake on SLURM; shows queue, steps, log (5 s refresh) |
| **Results** tab | KI % matrix + `results/<name>/meta/<sample_id>.json` per sample |
| header line | `image · snakemake · apptainer · sbatch`; Run refused if any is missing |
| bind | `127.0.0.1` only (no login; submits jobs as you) |
| host | run on the cluster host, never inside the container (needs `sbatch`) |
| port | `--yaml-out` → edit `gui_serve.port` in `configs/param_configs.yaml` → `--yaml-in` |

| Tunnel symptom | Cause |
|---|---|
| browser: *Unable to connect* | ssh tunnel not running on the laptop |
| `channel … connect failed` | console not listening on that node |
| `-L 8000:<node>:8000 <user>@<login>` refused | console binds loopback; use `-J` |
| ssh to node refused | no job of yours on that node |

## Command line

```bash
python3 src/analysis.py <name>                                   # freeze inputs
snakemake --profile profiles/slurm --config analysis=<name>      # run
cat results/<name>/summary_matrix.tsv                            # KI % per tool x sample
```

| Term | Definition |
|---|---|
| **analysis** | named run; everything in `results/<name>/`; inputs frozen at creation |
| **resume** | same name again → finished outputs kept, missing ones recomputed |
| `profiles/slurm` | one SLURM job per sample per tool, per-rule CPU/mem/time |
| `profiles/local` | tests only; the console always submits through SLURM |
| node pick | console puts `src/sbatch_pick.sh` before `sbatch`: `get_best_node` picks `-p`/`-w` per job, logged in `results/<analysis>/logs/node_pick.log`; `NODE_PICK=0` disables |
| container-only | Snakefile refuses without apptainer; each script re-checks it is inside the image |
| host needs | `snakemake`, `singularity`/`apptainer`, `curl` |

## Containers

![containers](docs/img/05_containers.svg)

| Command | Where | Does |
|---|---|---|
| `build.sh build` | workstation (Docker) | builds the image |
| `build.sh lock` | workstation | writes `containers/kv.lock.txt` |
| `build.sh ship` | workstation | login + push + records digest in `containers/images.env` |
| `build.sh pull` | Orfeo | `singularity pull` of the pinned digest → `containers/ont-knockin-val.sif` |
| `build.sh orfeo` | anywhere | prints the pull commands |

| Variable | Definition |
|---|---|
| `KV_OWNER` | GHCR namespace (default: owner of `origin`) |
| `KV_GITHUB_TOKEN` | PAT with `write:packages`, push only |
| `KV_ENGINE` | `docker` (default) or `podman` |
| `KV_SIF` | image snakemake uses (default `.sif`, else pinned digest) |
| `--cleanenv` | set by both profiles: host env does not leak into jobs |
| `--bind` | add to `apptainer-args` for data outside the repo (symlink targets too) |
| `.singularity/` | pull cache + tmp; warning below 12 GB free |

## Reproducibility

| Input | Pin | File |
|---|---|---|
| ALPINE, CRISPRLungo | 40-char commit SHA | `configs/tools.tsv` |
| base image | manifest digest | `containers/pins.env` |
| built image | manifest digest | `containers/images.env` |
| conda packages | URL + md5 | `containers/kv.lock.txt` |
| OS tools (`curl`, `unzip`, `time`, `flock`) | conda-forge, no apt | `envs/kv.yml` |
| hg38 region, paper xlsx | sha256 | `configs/refs.sha256` |
| reads | SRA accessions | `configs/samples.tsv` |
| analysis inputs | copied at creation | `results/<name>/inputs/` |

## Rules

| Rule | Does | Writes (in `results/<name>/`) |
|---|---|---|
| `ena` · `download` | SRA run table + reads | `data/raw/<run>.fastq.gz` (shared) |
| `filter` | length filter 3.5–7.5 kb, no subsampling | `data/<sample>.fastq.gz`, `data/stats/` |
| `refs` | WT / KI references, ALPINE config | `refs/` |
| `alpine` · `lungo` | each tool, all reads | `ALPINE/<sample>/`, `CRISPRLungo/<sample>/` |
| `summary` | KI % per tool x sample | `summary.tsv`, `summary_matrix.tsv` |
| every rule | log + benchmark; provenance via `src/sample_meta.py` | `logs/<step>/`, `meta/<sample_id>.json` |

## Metrics

| Term | Definition |
|---|---|
| `ki_min_insert_frac` | `shared:` param (0.80); drives both tools' insert threshold |
| ALPINE KI | `HDR-CD19`: insert ≥ cutoff **and** both homology arms aligned |
| CRISPRLungo KI | `CAR_insert` blocks, **merged**, cover ≥ cutoff of the insert |
| `metric` column | rule used per row in `summary.tsv` |
| ALPINE patch | upstream `minimap2 -ax map-hifi` → `map-ont` in a per-run copy; flag `minimap2_calls_patched` |
| control caveat | CRISPRLungo control ≈ 0 by construction; use `NoDonor` as its negative |
| denominator | length-passing reads (`reads_used`), not all reads (`reads_in`) |

## Parameters · tests

| Item | Definition |
|---|---|
| `configs/param_configs.yaml` | one section per rule + `shared:`; frozen into `inputs/params.yaml` |
| tests | `python3 -m pytest -q tests`; no cluster, no container |
| diagrams | `docs/diagrams/*.dot` → `bash src/diagrams.sh` |
| gitignored | `tools/ data/ results/ .snakemake/ .singularity/ .kv_bin/ .kv_env/` |
