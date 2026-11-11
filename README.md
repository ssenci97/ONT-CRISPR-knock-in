# KNOCKIN-VAL

Wrapper to run three long-read CRISPR **knock-in** analysis tools on the same ONT amplicon data: **ALPINE**, **CRISPRLungo**, **CRISPResso2**.

Scope: Oxford Nanopore sequencing of CRISPR knock-in PCR amplicons. Only tools with a native knock-in readout are included.

## The console

Three steps on Orfeo, none of which need a shell after the first:

```bash
containers/build.sh all                 # 1. build base + full image and convert to .sif
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
2. **Run** — **Run default pipeline (SLURM)** submits all eight steps with their dependencies, using the
   sample sheet and the parameters already in `configs/param_configs.yaml`. Nothing to configure. The tab
   then shows the queue, per-step log progress and the tail of `run_all.sh`, refreshing every 5 seconds.
   A second button runs the same thing without a scheduler, for a laptop.
3. **Results** — the knock-in % matrix and, per sample, its full `results/meta/<sample_id>.json`: what the
   wet lab submitted, what each step did, read counts, SLURM job ids, the image and the tool commits.

The console picks up `containers/ont-knockin-val.sif` automatically if it exists, so the jobs it submits run
inside the image; the header line tells you which runtime it resolved. **Run the console on the host, not
inside the container** — it needs `sbatch`, which a container cannot reach.

## How to run
```bash
cd KNOCKIN-VAL
bash slurms/run_all.sh --sbatch     # cluster: submits every step with dependencies
bash slurms/run_all.sh              # workstation: same steps, one after another
cat results/summary_matrix.tsv      # knock-in % per tool x sample
```
Run from the repo root (SLURM jobs use the submit dir as root). Needs `conda` on PATH, plus `git` and `curl`. Nothing else has to exist first: the pipeline clones the tools, builds the envs, downloads the data and builds the references.

## Containers

Orfeo does not run Docker, so the target is one OCI image used two ways: **podman** (rootless, no sudo) to
build and test, **apptainer** to run on the cluster. Running in a container makes `01_clone` and `02_envs`
no-ops: the tools and the conda environment are already inside, which is the part most likely to rot.

The image is split in two because **CRISPResso2 may not be redistributed** (see [LICENSES.md](LICENSES.md)):

![containers](docs/img/05_containers.svg)

```bash
export KV_OWNER=<your lowercase ghcr namespace>
containers/build.sh base      # publishable layer: conda env, cwltool, minimap2 2.16, ALPINE (MIT)
containers/build.sh full      # adds CRISPRLungo + CRISPResso2 on top; local only
containers/build.sh sif       # converts the FULL image to containers/ont-knockin-val.sif
containers/build.sh push      # pushes the base layer only; 'push-full' is refused on purpose
containers/build.sh all       # base, full and sif in one go
```
Commits come from `configs/tools.tsv`, and the build refuses to start if any of them is not a full SHA.

**The thing you run is the full image, never the base.** The base has no CRISPRLungo and no CRISPResso2,
and inside a container `01_clone`/`02_envs` do nothing, so running the base would leave steps 06 and 07
with no tools — and because both are wrapped in `|| kv_log "!! failed"`, the jobs would exit 0 with every
sample silently empty. Pulling the base from GHCR only saves you the conda solve:

```bash
podman pull ghcr.io/<owner>/ont-knockin-val-base:1.0   # optional: skip the solve
containers/build.sh full && containers/build.sh sif

export KV_IMAGE=localhost/ont-knockin-val:1.0          # podman, on your own machine
bash slurms/run_all.sh

export KV_SIF=$PWD/containers/ont-knockin-val.sif      # apptainer, on Orfeo
bash slurms/run_all.sh --sbatch
```
`slurms/analysis_env.sh` re-executes each step script inside the container with a whitelisted environment
(`--cleanenv --no-home` under apptainer, so a `module load` or a stray `~/.condarc` on the host cannot
reach in). Under `sbatch` the batch script lives in SLURM's spool directory, which is not mounted, so it is
copied into `logs/` first. `KV_BIND` takes a comma-separated list of host paths if your data sits outside
the repo — mount the symlink target too, not just the symlink. With neither `KV_SIF` nor `KV_IMAGE` set,
everything runs natively exactly as before. The image reference, the two tool commits and the CRISPResso2
conda version are recorded in `results/meta/<sample_id>.json` for every sample.

## Reproducibility

Every external input is pinned to something immutable, and the pin is a file in the repo:

| What | Pinned by | Where |
|---|---|---|
| ALPINE and CRISPRLungo | full 40-character commit SHAs | [`configs/tools.tsv`](configs/tools.tsv) |
| CRISPResso2 | conda package version (it is installed from bioconda, not from the clone) | `containers/kv.lock.txt` |
| Container base image | manifest digest, not a tag | [`containers/pins.env`](containers/pins.env) |
| Conda packages | explicit URL + md5 per package | `containers/kv.lock.txt` |
| hg38 region and the paper's supplementary xlsx | sha256 of the downloaded files | `configs/refs.sha256` |
| Sequencing reads | SRA run accessions, immutable by definition | [`configs/samples.tsv`](configs/samples.tsv) |

`01_clone` refuses to run if a `commit` in `tools.tsv` is not a full SHA, and verifies that `HEAD` after
checkout equals it. `containers/build.sh` applies the same check before building. `04_build_refs` verifies
the two downloads against `configs/refs.sha256`, and fails rather than proceeding if they changed.

Two of those pins are created on first run, then committed:

```bash
containers/build.sh base      # solves the environment once
containers/build.sh lock      # writes containers/kv.lock.txt from what was solved
containers/build.sh base      # rebuilds from the lock: no solver, identical packages
bash slurms/04_build_refs.sh  # writes configs/refs.sha256 on the first run
git add containers/kv.lock.txt configs/refs.sha256
```

After that the image builds without invoking the conda solver at all, which is both the fast path and the
reproducible one. The repo itself stays small: it holds scripts, configs, envs, licences, diagram sources
and the two pin files. `tools/ data/ refs/ results/ logs/` are generated and gitignored.

## Steps
| Step | Does | Writes |
|---|---|---|
| `01_clone` | clones the 3 tools at the pinned commits in `configs/tools.tsv` | `tools/` |
| `02_envs` | creates the 5 conda envs from `envs/*.yml` | `kv_*` envs |
| `03_fetch` | downloads the SRA runs, length-filters (3.5–7.5 kb); **all passing reads are kept, no subsampling** | `data/<label>.fastq.gz`, `data/read_stats.tsv` |
| `04_build_refs` | builds WT / knock-in references and the ALPINE config | `refs/` |
| `05_alpine` · `06_lungo` · `07_crispresso` | runs each tool on every read of every sample | `results/<tool>/` |
| `08_summary` | one knock-in % per tool x sample | `results/summary*.tsv` |

Every per-sample step also appends what it did to `results/meta/<sample_id>.json`: the submitted wet-lab
metadata, the parameters used, read counts, SLURM job ids and the pipeline commit. `src/sample_meta.py` is
the only writer of those files.

Every step is a standalone SLURM script: `sbatch slurms/06_lungo.sh` or `bash slurms/06_lungo.sh`. The per-sample steps are job arrays; run locally they loop over all samples.

## What each run reads

Running one tool and running all three feed on **the same files**. The only difference is how many
readers there are and whether SLURM chains the steps for you.

| | |
|---|---|
| The input contract, and the flag each tool receives it under | ![inputs](docs/img/01_inputs.svg) |
| One tool on its own: `sbatch slurms/06_lungo.sh` | ![single tool](docs/img/02_single_tool.svg) |
| All three: `bash slurms/run_all.sh --sbatch` | ![all tools](docs/img/03_all_tools.svg) |
| Where sample metadata comes from, and what the run records | ![metadata](docs/img/04_metadata.svg) |
| What a wet-lab user does: build once, then three tabs | ![console](docs/img/06_console.svg) |

Sources are in `docs/diagrams/*.dot`; re-render with `bash src/diagrams.sh` (needs graphviz).

## Comparing the three tools

The three knock-in percentages are not interchangeable, and ALPINE is the strictest by a wide margin:

- ALPINE calls `HDR-CD19` only when the inserted transgene reaches `truncated_cutoff` of the full insert
  **and** both homology arms align to the read. Everything shorter becomes `Non-HDR-without-ITR-CD19`.
- CRISPRLungo counts reads whose `CAR_insert` integration spans at least the same fraction of the insert.
- CRISPResso2 has no length threshold at all: a read is HDR if it aligns better to the KI amplicon than to WT.

`shared.ki_min_insert_frac` (default 0.80) now drives the first two, so they answer the same question.
The `metric` column of `results/summary.tsv` states the rule used for each row.

**Known upstream issue.** ALPINE validates the homology arms with `minimap2 -ax map-hifi`, hardcoded in
`DockerFile/classify/utils/data_utils.py`, even when `data_type: nanopore`. On ONT reads the wrong preset
makes genuine HDR reads fail the arm check and be downgraded, so ALPINE under-reports knock-in here.
`alpine_data_type` does not reach that call.

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

Licences of the bundled tools: **[LICENSES.md](LICENSES.md)**. Full documentation: **[Manual.md](Manual.md)**. Per-tool notes: [ALPINE](docs/manuals/ALPINE.md) · [CRISPRLungo](docs/manuals/CRISPRLungo.md) · [CRISPResso2](docs/manuals/CRISPResso2.md). Shared input names: [Inputs](docs/manuals/Inputs.md).
