# KNOCKIN-VAL

Wrapper to run two long-read CRISPR **knock-in** analysis tools on the same ONT amplicon data: **ALPINE** and **CRISPRLungo**.

> A third tool, CRISPResso2, was part of this pipeline until 2026-11-11 and was removed: its licence
> forbids copying it in any form, so it could not ship in the image. [LICENSES.md](LICENSES.md) records
> what that cost and what it bought.

Scope: Oxford Nanopore sequencing of CRISPR knock-in PCR amplicons. Only tools with a native knock-in readout are included.

## The console

Three steps on Orfeo, none of which need a shell after the first:

```bash
containers/build.sh pull                # 1. fetch the image once (~5 GB)
python3 src/gui_serve.py                # 2. start the console on the login node
ssh -L 8000:127.0.0.1:8000 <user>@orfeo # from your laptop, then open http://127.0.0.1:8000/
```

![console](docs/img/06_console.svg)

The page has three tabs:

1. **Samples** — one card per sample. Saving writes `configs/samples.tsv`, one
   `configs/samples/<sample_id>.json` (operator, date, cell type, donor format, dose, flow cell, notes) and
   sets `#SBATCH --array=1-N` in every per-sample step, so the sheet and the array size cannot drift apart.
   Fields come from `configs/sample_schema.json`; add one there and it appears in the form and the JSON and
   nowhere else. Editing `configs/samples.tsv` by hand still works.
2. **Run** — **Run default pipeline (SLURM)** submits all seven steps with their dependencies, using the
   sample sheet and the parameters already in `configs/param_configs.yaml`. Nothing to configure. The tab
   then shows the queue, per-step log progress and the tail of `run_all.sh`, refreshing every 5 seconds.
   A second button runs the same thing without a scheduler, for a laptop.
3. **Results** — the knock-in % matrix and, per sample, its full `results/meta/<sample_id>.json`: what the
   wet lab submitted, what each step did, read counts, SLURM job ids, the image and the tool commits.

The console picks up `containers/ont-knockin-val.sif` automatically if it exists, so you do **not** need to
export `KV_SIF` for it; the header line tells you which runtime it resolved (`runtime apptainer (...)`, or
`runtime native` if it found no image). **Run the console on the host, not inside the container** — it needs
`sbatch`, which a container cannot reach.

Two things that trip people up on a cluster. The tunnel must reach **the same login node** the console is
running on: if `ssh user@orfeo` round-robins between nodes you will forward to the wrong one and get a
blank page, so note the hostname from the console's shell (`hostname -f`) and `ssh -L 8000:127.0.0.1:8000
<user>@<that host>`. And if port 8000 is already taken, change it once:

```bash
python3 src/gui_serve.py --yaml-out      # writes a [gui_serve] block to configs/param_configs.yaml
vim configs/param_configs.yaml           # set port: 8010
python3 src/gui_serve.py --yaml-in       # and forward 8010 instead
```

## How to run
```bash
cd KNOCKIN-VAL
bash slurms/run_all.sh --sbatch     # cluster: submits every step with dependencies
bash slurms/run_all.sh              # workstation: same steps, one after another
cat results/summary_matrix.tsv      # knock-in % per tool x sample
```
Run from the repo root (SLURM jobs use the submit dir as root). Needs `conda` on PATH, plus `git` and `curl`. Nothing else has to exist first: the pipeline clones the tools, builds the envs, downloads the data and builds the references.

## Containers

Orfeo does not build images and does not run Docker. So the image is **built with Docker on a workstation,
pushed to GHCR, and pulled on Orfeo with Singularity**, which converts it to a `.sif` on the way in. No
root and no build tooling are needed on the cluster. Running in a container makes `01_clone` and `02_envs`
no-ops: the tools and the conda environment are already inside, which is the part most likely to rot.

Both tools are redistributable, so there is **one image** and it is public — no token is needed to pull
it on Orfeo (see [LICENSES.md](LICENSES.md)):

![containers](docs/img/05_containers.svg)

### On the workstation (Docker)

```bash
export KV_OWNER=<your lowercase github namespace>      # defaults to the owner of 'origin'
export KV_GITHUB_TOKEN=<PAT with write:packages>       # only needed to push

containers/build.sh build                               # build the image
containers/build.sh ship                                # login, push, print the Orfeo lines
```
The push records the image **manifest digest** in `containers/images.env`; commit that file, because it is
what makes the cluster-side pull reproducible. Individual targets: `build lock login push ship orfeo`.
Commits come from `configs/tools.tsv` and the build refuses to start if any is not a full SHA.
`KV_ENGINE=podman` switches engine.

### On Orfeo (Singularity)

```bash
cd <the repo root>                 # the pull writes a path relative to it
containers/build.sh pull           # downloads and converts; verifies the .sif exists
export KV_SIF=$PWD/containers/ont-knockin-val.sif
bash slurms/run_all.sh --sbatch    # or start the console and press the button
```
`pull` reads the digest from `containers/images.env`, puts the cache and temp dir under `.singularity/`,
warns if the filesystem has under 12 GB free, and fails loudly if the `.sif` is missing afterwards. No
credentials: the package is public. `containers/build.sh orfeo` prints the same commands without running
them, if you would rather paste them yourself.

`run_all.sh` refuses to submit when `KV_SIF` points at a file that is not there, and warns when
`#SBATCH --array=1-N` disagrees with the number of rows in `configs/samples.tsv`.

`slurms/analysis_env.sh` re-executes each step script inside the container with a whitelisted environment
(`--cleanenv --no-home` under apptainer, so a `module load` or a stray `~/.condarc` on the host cannot
reach in). Under `sbatch` the batch script lives in SLURM's spool directory, which is not mounted, so it is
copied into `logs/` first. `KV_BIND` takes a comma-separated list of host paths if your data sits outside
the repo — mount the symlink target too, not just the symlink. `KV_IMAGE` runs the same steps under
docker/podman on a workstation. With neither `KV_SIF` nor `KV_IMAGE` set, everything runs natively exactly
as before. The image reference and the two tool commits are recorded in `results/meta/<sample_id>.json`
for every sample.

## Reproducibility

Every external input is pinned to something immutable, and the pin is a file in the repo:

| What | Pinned by | Where |
|---|---|---|
| ALPINE and CRISPRLungo | full 40-character commit SHAs | [`configs/tools.tsv`](configs/tools.tsv) |
| Container base image | manifest digest, not a tag | [`containers/pins.env`](containers/pins.env) |
| The built images | manifest digest, written by every push | `containers/images.env` |
| Conda packages | explicit URL + md5 per package | `containers/kv.lock.txt` |
| OS-level tools (`curl`, `unzip`, `time`, `flock`) | installed from conda-forge, **not apt**, so they are in the lock too | `envs/kv.yml` |
| hg38 region and the paper's supplementary xlsx | sha256 of the downloaded files | `configs/refs.sha256` |
| Sequencing reads | SRA run accessions, immutable by definition | [`configs/samples.tsv`](configs/samples.tsv) |

The image installs **nothing from apt**. Every binary comes from conda-forge or bioconda and is therefore
captured by `containers/kv.lock.txt`; apt packages would have been the one unpinned input left, and the
distribution mirrors are not reachable from every network anyway.

`01_clone` refuses to run if a `commit` in `tools.tsv` is not a full SHA, and verifies that `HEAD` after
checkout equals it. `containers/build.sh` applies the same check before building. `04_build_refs` verifies
the two downloads against `configs/refs.sha256`, and fails rather than proceeding if they changed.

Two of those pins are created on first run, then committed:

```bash
containers/build.sh build     # solves the environment once
containers/build.sh lock      # writes containers/kv.lock.txt from what was solved
containers/build.sh build     # rebuilds from the lock: no solver, identical packages
bash slurms/04_build_refs.sh  # writes configs/refs.sha256 on the first run
git add containers/kv.lock.txt configs/refs.sha256
```

After that the image builds without invoking the conda solver at all, which is both the fast path and the
reproducible one. The repo itself stays small: it holds scripts, configs, envs, licences, diagram sources
and the two pin files. `tools/ data/ refs/ results/ logs/` are generated and gitignored.

## Steps
| Step | Does | Writes |
|---|---|---|
| `01_clone` | clones the 2 tools at the pinned commits in `configs/tools.tsv` | `tools/` |
| `02_envs` | creates the conda env from `envs/kv.yml` | `kv` env |
| `03_fetch` | downloads the SRA runs, length-filters (3.5–7.5 kb); **all passing reads are kept, no subsampling** | `data/<label>.fastq.gz`, `data/read_stats.tsv` |
| `04_build_refs` | builds WT / knock-in references and the ALPINE config | `refs/` |
| `05_alpine` · `06_lungo` | runs each tool on every read of every sample | `results/<tool>/` |
| `07_summary` | one knock-in % per tool x sample | `results/summary*.tsv` |

Every per-sample step also appends what it did to `results/meta/<sample_id>.json`: the submitted wet-lab
metadata, the parameters used, read counts, SLURM job ids and the pipeline commit. `src/sample_meta.py` is
the only writer of those files.

Every step is a standalone SLURM script: `sbatch slurms/06_lungo.sh` or `bash slurms/06_lungo.sh`. The per-sample steps are job arrays; run locally they loop over all samples.

## What each run reads

Running one tool and running both feed on **the same files**. The only difference is how many
readers there are and whether SLURM chains the steps for you.

| | |
|---|---|
| The input contract, and the flag each tool receives it under | ![inputs](docs/img/01_inputs.svg) |
| One tool on its own: `sbatch slurms/06_lungo.sh` | ![single tool](docs/img/02_single_tool.svg) |
| Both: `bash slurms/run_all.sh --sbatch` | ![all tools](docs/img/03_all_tools.svg) |
| Where sample metadata comes from, and what the run records | ![metadata](docs/img/04_metadata.svg) |
| What a wet-lab user does: build once, then three tabs | ![console](docs/img/06_console.svg) |

Sources are in `docs/diagrams/*.dot`; re-render with `bash src/diagrams.sh` (needs graphviz).

## Comparing the two tools

The two knock-in percentages are not interchangeable, and ALPINE is the stricter by a wide margin:

- ALPINE calls `HDR-CD19` only when the inserted transgene reaches `truncated_cutoff` of the full insert
  **and** both homology arms align to the read. Everything shorter becomes `Non-HDR-without-ITR-CD19`.
- CRISPRLungo counts reads whose `CAR_insert` integration blocks **together** cover at least the same
  fraction of the insert. The blocks are merged before measuring, so an insert reported in two pieces is
  scored on its union, not on its largest piece.

`shared.ki_min_insert_frac` (default 0.80) drives both, so they answer the same question.
The `metric` column of `results/summary.tsv` states the rule used for each row.

**Known upstream issue, patched here.** ALPINE validates the homology arms with `minimap2 -ax map-hifi`,
hardcoded in two helpers (`classify/utils/data_utils.py:89` and `classify/utils/realign_ins_to_wildtype.py:12`)
that never receive `data_type`, even when `data_type: nanopore` — although ALPINE's own `classify_read.py`
selects the preset correctly in four other places. On ONT reads the HiFi preset makes genuine HDR reads fail
the arm check, so ALPINE under-reported knock-in. `src/alpine_local.sh` now patches those two lines to
`-ax map-ont` in a per-run copy of the tool; **the pinned clone is never touched**, and the patch is
recorded per sample as `minimap2_preset_patched`. See [ALPINE](docs/manuals/ALPINE.md).

**Two caveats on the denominators.** First, `06_lungo` passes `--control <the control sample>` to every
sample *including the control itself*, so CRISPRLungo's value for the control is ~0 by construction and is
not independent evidence of specificity — `NoDonor` is the informative negative control for that tool.
ALPINE ignores `--control`, so its control value *is* informative. Second, `03_fetch` keeps reads of
3,500–7,500 bp while the WT amplicon is 4,358 bp and the knock-in allele 6,373 bp: both pass, but alleles
with more than ~858 bp deleted fall below the floor and never reach either tool. `ki_pct` is therefore a
fraction of length-passing reads, not of all amplicon reads. `results/summary.tsv` carries `reads_in`
(pre-filter) beside `reads_used` so the gap is visible.

## Parameters
Hardcoded at the top of each script, overridable through `configs/param_configs.yaml`. The `shared:`
section holds values more than one step must agree on (currently `ki_min_insert_frac`) and is read by every
step automatically. To change a per-step parameter without editing code:
```bash
bash slurms/06_lungo.sh --yaml-out   # dump this step's parameters
vim configs/param_configs.yaml            # edit them
bash slurms/06_lungo.sh --yaml-in    # rerun with them
```

## Repository contents
Scripts, envs, configs, the submission form (`gui/`) and docs only.
`tools/ data/ refs/ results/ logs/` are created by the pipeline and gitignored.

Licences of the bundled tools: **[LICENSES.md](LICENSES.md)**. Full documentation: **[Manual.md](Manual.md)**. Per-tool notes: [ALPINE](docs/manuals/ALPINE.md) · [CRISPRLungo](docs/manuals/CRISPRLungo.md). Shared input names: [Inputs](docs/manuals/Inputs.md).
