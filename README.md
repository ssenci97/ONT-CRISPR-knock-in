# KNOCKIN-VAL

KNOCKIN-VAL is a toolkit for validating CRISPR knock-in experiments with Oxford Nanopore Technologies (ONT) amplicon sequencing. It runs two independent knock-in callers on the same reads and reports their knock-in percentages side by side. Everything runs inside one container on a SLURM HPC cluster. The analysis itself is done by [ALPINE](https://github.com/Maggi-Chen/ALPINE) and [CRISPRLungo](https://github.com/pinellolab/CRISPRLungo), and we warmly thank their authors for making these tools openly available. This repository only orchestrates them, records provenance, and puts a simple web console in front of them.

![what a knock-in is and how it is measured](docs/img/00_knockin.svg)

| | |
|---|---|
| **Scope** | ONT reads of CRISPR knock-in PCR amplicons; tools with a native knock-in readout only |
| **Runs on** | a SLURM HPC cluster with Singularity/Apptainer; jobs are placed by `get_best_node` |
| **Removed** | CRISPResso2 (2026-11-11): its licence forbids redistribution → [LICENSES.md](LICENSES.md) |
| **Full reference** | [Manual.md](Manual.md) · [ALPINE](docs/manuals/ALPINE.md) · [CRISPRLungo](docs/manuals/CRISPRLungo.md) · [Inputs](docs/manuals/Inputs.md) |

## Inputs and parameters

The console's info panel shows the same definitions, together with the current values.

### Input data types

- **FASTQ (local)** (gzipped FASTQ (`.fastq.gz`), one file per sample, absolute path on the cluster): The preferred source. Step `01_fetch` length-filters it with seqkit into `results/<analysis>/data/<sample_id>.fastq.gz`; the original file is never modified. A file outside `$HOME` and the repo needs `--bind <dir>` in `apptainer-args` (local FASTQ directories are bound automatically).
- **SRA run accession** (`SRR` / `ERR` / `DRR` followed by digits): The alternative source, for public data. Step `01_fetch` checks the read count against ENA, downloads the `.sra` file, converts it with `fasterq-dump` and keeps it in the shared cache `data/raw/<run>.fastq.gz`, so later analyses reuse it.
- **sample_id** (letters, digits, underscore): The row key. It names every file, log and SLURM job of the sample, so it must be unique within the sheet.
- **condition** (free text): A human-readable label for the treatment, e.g. `rnp_dsDNA_donor`. Carried into `summary.tsv` and the KI % matrix; not interpreted by the tools.
- **control** (tick box (`1` / `0`)): Marks a negative control. The first ticked sample is passed to CRISPRLungo as `--control`; at least one is required.
- **Wet-lab and sequencing fields** (free text, dates, numbers): Provenance only. Stored in `configs/samples/<sample_id>.json` and copied into `results/<analysis>/meta/`; never read by the tools.
- **References (built by `02_refs`)** (`TRAC_WT.fa`, `TRAC_KI.fa`, `CAR_insert.fa`, `alpine/ref.fa`, `alpine/config.tsv`, `design.json`): Control (unedited) and knock-in amplicons, the inserted gene, guide, primers and homology arms. Built from a genome window (`refs.region`) and the donor template table of the paper (`refs.pmc`). The files are named after the example locus (`TRAC`, `CAR`); their roles are the same for any target.

![inputs](docs/img/01_inputs.svg)

### Variables (`configs/param_configs.yaml`)

Each variable is listed with what it controls, the step that reads it, and the original argument it maps to in the tool.

- `shared.ki_min_insert_frac`: Minimum fraction of the inserted gene that a read must cover to be counted as a knock-in. 0.8 means at least 80% of the insert must be present; shorter, truncated integrations are not counted. The same threshold is applied to both tools so their percentages are comparable.
  - step: `03_alpine`, `05_summary`
  - original argument: ALPINE `truncated_cutoff` in job.yaml; for CRISPRLungo it is applied afterwards by `summarize.py` on the merged insert blocks
- `fetch.bioproject`: NCBI/ENA BioProject that the SRA runs belong to. Only used to download the run table from ENA, so that every downloaded run can be checked against its expected read count. Not needed when all samples are local FASTQ files.
  - step: `01_fetch` (jobs ena, download)
  - original argument: ENA filereport `accession=`
- `fetch.min_len`: Shortest read kept, in bp. Reads below this length are dropped before any tool sees them (primer dimers, broken reads). Nothing is subsampled: all passing reads are used.
  - step: `01_fetch` (job filter)
  - original argument: `seqkit seq -m`
- `fetch.max_len`: Longest read kept, in bp. Removes concatemers and chimeric reads much longer than the knock-in amplicon.
  - step: `01_fetch` (job filter)
  - original argument: `seqkit seq -M`
- `refs.region`: hg38 genomic window (chromosome:start..end:strand) that contains the amplicon. Downloaded once from Ensembl and pinned by sha256.
  - step: `02_refs`
  - original argument: Ensembl REST `/sequence/region/human/<region>`
- `refs.pmc`: Europe PMC id of the paper whose supplementary table holds the HDR donor templates. Downloaded once and pinned by sha256.
  - step: `02_refs`
  - original argument: Europe PMC `supplementaryFiles`
- `build_refs.genomic_fasta`: Local path of the cached hg38 window downloaded from `refs.region`.
  - step: `02_refs`
  - original argument: `build_refs.py --yaml-in`
- `build_refs.genomic_start_1based`: 1-based genomic coordinate of the first base of `genomic_fasta`; converts positions in the window back to hg38 coordinates.
  - step: `02_refs`
  - original argument: `build_refs.py --yaml-in`
- `build_refs.templates_xlsx`: Supplementary spreadsheet containing the donor templates (full sequence and homology arms).
  - step: `02_refs`
  - original argument: `build_refs.py --yaml-in`
- `build_refs.template_title`: Exact title of the row in the supplementary table to use as donor; selects the knock-in construct.
  - step: `02_refs`
  - original argument: `build_refs.py --yaml-in`
- `build_refs.guide`: crRNA spacer sequence (5'->3'). Locates the cut site in the wild-type amplicon and is passed to CRISPRLungo.
  - step: `02_refs`, `04_lungo`
  - original argument: CRISPRlungo positional `<guide>`
- `build_refs.cut_offset_from_guide_5p`: Distance of the cut from the 5' end of the guide: 17 for SpCas9, 18 for AsCas12a. Wrong values shift the expected integration site.
  - step: `02_refs`
  - original argument: `build_refs.py --yaml-in`
- `build_refs.primer_f_full` / `primer_r_full`: Full PCR primers including adapters; define the amplicon ends that ALPINE searches for in each read.
  - step: `02_refs`, `03_alpine`
  - original argument: ALPINE `primer_1` / `primer_2` in job.yaml
- `build_refs.primer_f_specific` / `primer_r_specific`: Gene-specific part of the primers only; used to locate the amplicon in the hg38 window.
  - step: `02_refs`
  - original argument: `build_refs.py --yaml-in`
- `alpine.primer_check_length`: Number of bases at each read end in which ALPINE looks for the primers. Reads whose primers are not found there are discarded as incomplete amplicons.
  - step: `03_alpine`
  - original argument: ALPINE `primer_check_length` in job.yaml
- `alpine.data_type`: Read technology. `nanopore` tells ALPINE to expect ONT errors and also makes the pipeline patch ALPINE's hard-coded `minimap2 -ax map-hifi` into `map-ont`.
  - step: `03_alpine`
  - original argument: ALPINE `data_type` in job.yaml
- `lungo.cleavage_pos`: Position of the cut inside the guide as CRISPRLungo counts it; centres the window where edits are scored.
  - step: `04_lungo`
  - original argument: CRISPRlungo `--cleavage_pos`
- `lungo.window`: Half-width in bp around the cut in which CRISPRLungo scores indels and integrations. Larger values catch more distal edits but also more sequencing noise.
  - step: `04_lungo`
  - original argument: CRISPRlungo `--window`
- `threads`, `mem_mb`, `runtime`: CPU, memory (MB) and time (minutes) of each job, set in `src/pipeline.py`. `get_best_node` uses them to choose a partition and node with enough free resources when each job is submitted.
  - step: `every step`
  - original argument: `sbatch --cpus-per-task`, `--mem`, `-t`; CRISPRlungo `-t`; ALPINE coresMin/ramMin

Each analysis freezes its own copy of these values in `results/<analysis>/inputs/params.yaml`.

### Original command lines

| Step | Command |
|---|---|
| `01_fetch` | `seqkit seq -j <threads> -g -G - -m <min_len> -M <max_len> <raw.fastq.gz> -o data/<sample_id>.fastq.gz` |
| `03_alpine` | `cwltool --no-container aav_per_sample_workflow.cwl job.yaml` (fastqfile, reffile, config, primer_1/2, primer_check_length, data_type, truncated_cutoff, five/three_prime_HA_seq) |
| `04_lungo` | `CRISPRlungo TRAC_WT.fa <sample.fastq.gz> <out> <guide> --cleavage_pos <cp> --window <w> --control <control.fastq.gz> --induced_sequence_path TRAC_KI.fa --integration_file CAR_insert.fa -t <threads>` |
| `05_summary` | `python3 src/summarize.py --analysis-dir results/<analysis>` — writes `ki_reads`/`ki_pct`, `partial_reads`/`partial_pct` and the per-class `notes` |

## Quick start (SLURM HPC cluster)

| Step | Where | Command |
|---|---|---|
| 1. get the image | cluster login node, repo root | `containers/build.sh pull` |
| 2. start the console | same shell | `python3 src/gui_serve.py` |
| 3. node name | same shell | `hostname -f` |
| 4. tunnel | laptop | `ssh -J <user>@<login-host> -L 8000:127.0.0.1:8000 -N <user>@<node>` |
| 5. open | laptop browser | http://127.0.0.1:8000/ |

| Automatic | Done by |
|---|---|
| `module load singularity` | `build.sh` (line 4) and `gui_serve.py` |
| node choice | `gui_serve.py` puts `src/sbatch_pick.sh` in front of `sbatch` |

## Console

![console](docs/img/06_console.svg)

### Samples

The page starts empty. **Show example data** fills in five public ONT runs of a published knock-in experiment (BioProject PRJNA1257358, credited under [Credits and citation](#credits-and-citation)). **Hide info** collapses the definitions above. Each card keeps the fields the pipeline needs; the sequencing and wet-lab fields sit at the end under **Optional details**, collapsed by default.

![samples: info panel](docs/img/gui_samples_info.png)

Each sample card has a **Local file | SRA** switch, with Local file as the default. While you type a path, the console checks that the file exists on the cluster and suggests folders and FASTQ files.

![samples: cards](docs/img/gui_samples_example.png)

| Term | Definition |
|---|---|
| **Save samples** | validates, then writes `configs/samples.tsv` (`sample_id, fastq_path, srr, condition, control`) and `configs/samples/<sample_id>.json` |
| **Load saved** | reopens the saved sheet |

### Run

The screenshot below shows an illustrative mid-run state.

![run](docs/img/gui_run.png)

| Term | Definition |
|---|---|
| **Run on SLURM** | runs `src/pipeline.py <name>` on the login node: freezes inputs into `results/<name>/inputs/`, submits the jobs with `sbatch --dependency` and exits; jobs run unattended, there is no local mode |
| overall bar | finished jobs out of planned jobs |
| step rows | waiting / running / done / failed / cancelled / stopped per step, from files on disk plus `squeue`/`sacct`, each labelled in words and marked ✓ ✕ ▶ rather than by colour alone. A job counts as done once its output exists and its log ends with the footer. Failed jobs open with their log tail. |
| SLURM queue | only this run's jobs (`squeue -n <run id>`), with partition and node |
| node choice | `results/<name>/logs/node_pick.log`, one line per submitted job |
| header line | `image · singularity · sbatch · get_best_node`; a run is refused if `sbatch` or singularity is missing |
| resume | the same name again: done jobs are kept, the rest (and everything downstream) is resubmitted |
| stop | `pipeline.py <name> --stop` (`scancel` of this run's jobs) |

### Results

| Term | Definition |
|---|---|
| KI % | `results/<name>/summary_matrix.tsv`: tool × sample |
| per sample | `results/<name>/meta/<sample_id>.json`: submitted fields plus one record per step |

![metadata](docs/img/04_metadata.svg)

| Console setting | Definition |
|---|---|
| bind | `127.0.0.1` only (no login; jobs are submitted as you) |
| host | the cluster login node, never inside the container (needs `sbatch`) |
| port | `--yaml-out` → edit `gui_serve.port` in `configs/param_configs.yaml` → `--yaml-in` |

| Tunnel symptom | Cause |
|---|---|
| browser: *Unable to connect* | ssh tunnel not running on the laptop |
| `channel … connect failed` | console not listening on that node |
| `-L 8000:<node>:8000 <user>@<login-host>` refused | console binds loopback; use `-J` |
| ssh to node refused | no job of yours on that node |

## Node placement (`get_best_node`)

For each job `pipeline.py` submits, `src/sbatch_pick.sh`:
1. reads `--cpus-per-task`, `--mem` and `-t`;
2. keeps the partitions whose time limit covers the job, never DGX or GPU;
3. asks `get_best_node` (`src/best_node.sh`) for the idle or mixed node with the most free CPUs and memory;
4. submits with `-p <partition> -w <node>`.

If no node fits, the default partition (GENOA) is kept. `NODE_PICK=0` turns this off.

## Pipeline

![all tools](docs/img/03_all_tools.svg)

| Step | Job | Does | Writes (in `results/<name>/`) |
|---|---|---|---|
| `01_fetch` | `ena` · `download` · `filter` | SRA reads (cached) or local FASTQ, length filter | `data/<sample>.fastq.gz`, `data/stats/` |
| `02_refs` | `refs` | WT / KI references, ALPINE config | `refs/` |
| `03_alpine` | `alpine` | ALPINE, all reads, one job per sample | `ALPINE/<sample>/` |
| `04_lungo` | `lungo` | CRISPRLungo, all reads, one job per sample | `CRISPRLungo/<sample>/` |
| `05_summary` | `summary` | KI % per tool × sample | `summary.tsv`, `summary_matrix.tsv` |
| every job | — | log, provenance via `src/sample_meta.py` | `logs/<step>/`, `meta/<sample_id>.json` |

![single tool](docs/img/02_single_tool.svg)

Command-line equivalent of the console:

```bash
python3 src/analysis.py <name>                  # freeze inputs
python3 src/pipeline.py <name> --dry-run        # show what would be submitted
python3 src/pipeline.py <name>                  # submit; run again to resume
python3 src/pipeline.py <name> --stop           # scancel this analysis' jobs
cat results/<name>/summary_matrix.tsv           # KI % per tool x sample
```

`pipeline.py` plans the jobs (`01_fetch`: `ena`, `download` per SRA run, `filter` per sample; `02_refs`; `03_alpine` and `04_lungo` per sample; `05_summary`) and submits them with `sbatch --dependency=afterok:... --kill-on-invalid-dep=yes`, each through `src/kv_job.sh`, which runs the step inside the image and then checks the job's outputs (exist, non-empty, `gzip -t` for `.gz`); a job that fails the check fails, so its dependents never start. Job ids go to `results/<name>/jobs.tsv`.

| Resume and safety | Definition |
|---|---|
| done rule | every output exists and is non-empty, the log ends with the `kv_footer` line (not required for the shared `data/raw`, `data/meta` cache), and no output is older than an output of a job it depends on |
| resume | run the same command again: only jobs not done, and everything downstream, are resubmitted |
| frozen inputs | sha256 of `results/<name>/inputs/` kept in `inputs/analysis.json` and re-verified every launch; edited inputs are refused (create a new analysis); local FASTQ size + mtime are re-verified too |
| pre-flight | every input of every job to run must exist or be produced in this launch, else nothing is submitted |
| paths | outputs and logs must resolve inside `results/<name>/`, `data/raw` or `data/meta` |
| one launch | lock `results/<name>/.lock`; refused while the analysis has live SLURM jobs, or another analysis has a live job writing the same shared download |
| environment | `SLURM_*`/`SBATCH_*` are scrubbed, so launching from an `salloc` shell is safe |
| timing | `sacct -j <id> -o JobID,Elapsed,MaxRSS` |

## Metrics

| Term | Definition |
|---|---|
| ALPINE KI | `HDR-<name>` class: insert ≥ `ki_min_insert_frac` **and** both homology arms aligned |
| CRISPRLungo KI | integration blocks matching the insert, **merged**, cover ≥ `ki_min_insert_frac` of the insert |
| `metric` column | the definition used for each row of `summary.tsv` |
| denominator | length-passing reads (`reads_used`), not all reads |
| control caveat | the CRISPRLungo control is ≈ 0 by construction; use `NoDonor` as its negative |
| ALPINE caveat | under-reports on ONT; see [docs/manuals/ALPINE.md](docs/manuals/ALPINE.md) |

### Reads that are not knock-in are not thrown away

A read that is neither a clean knock-in nor unedited is still counted and reported, so a failed experiment can be told apart from a partly successful one.

- **Partial inserts (more than 0 but below the threshold)** are counted in their own columns of `summary.tsv`: `partial_reads` and `partial_pct`. For ALPINE these are the `Non-HDR-...` classes, which is exactly what ALPINE calls a read whose insert is too short; for CRISPRLungo they are reads with some insert integration whose merged blocks cover less than `ki_min_insert_frac` of the insert. In the public data these are not rare: ALPINE reported 4–6 % `Non-HDR-...` reads in the donor samples, against 0 % in the controls.
- **Everything else is distinguished too, not merged into "not knock-in".** Both tools classify every read, and the full class breakdown with percentages goes into the `notes` column of `summary.tsv`. A small insertion or deletion at the cut is therefore a different outcome from an unedited read: ALPINE reports `Unmodified`, `Unmodified-with-SNP`, `DEL-small`, `INS-small`, `DEL-large`, `INS-large`, `INV`, `DUP`, `Unclassified`; CRISPRLungo reports `WT`, `Sub`, `Ins`, `Del`, `LargeIns`, `LargeDel`, `Inversion`, `Complex`.
- The per-read tables are kept as well, under `results/<name>/ALPINE/<sample>/` and `results/<name>/CRISPRLungo/<sample>/results/`, if you want to go back to individual reads.

Only `ki_pct` is shown in the KI % matrix; the other columns live in `summary.tsv`.

## Containers

![containers](docs/img/05_containers.svg)

| Command | Where | Does |
|---|---|---|
| `build.sh build` | workstation (Docker) | builds the image |
| `build.sh lock` | workstation | writes `containers/kv.lock.txt` |
| `build.sh ship` | workstation | login + push, records the digest in `containers/images.env`, prints the cluster pull commands |
| `build.sh pull` | SLURM HPC cluster | `singularity pull` of the pinned digest → `containers/ont-knockin-val.sif` |

| Variable | Definition |
|---|---|
| `KV_OWNER` | GHCR namespace (default: owner of `origin`) |
| `KV_GITHUB_TOKEN` | PAT with `write:packages`, push only |
| `KV_ENGINE` | `docker` (default) or `podman` |
| `KV_SIF` | image the jobs run in (default: the `.sif`, else the pinned digest) |
| `--cleanenv` | host environment does not leak into jobs |
| `--bind` | add to `apptainer-args` for data outside the repo (symlink targets too) |

## Reproducibility

| Input | Pin | File |
|---|---|---|
| ALPINE, CRISPRLungo | 40-char commit SHA | `configs/tools.tsv` |
| base image · built image | manifest digest | `containers/pins.env` · `containers/images.env` |
| conda packages | URL + md5 | `containers/kv.lock.txt` |
| hg38 region, paper xlsx | sha256 | `configs/refs.sha256` |
| reads | SRA accession, or local path as submitted | `results/<name>/inputs/samples.tsv` |
| analysis inputs | copied at creation | `results/<name>/inputs/` |

## Credits and citation

- **Tools.** ALPINE (Chen et al., *Bioinformatics* 2026) and CRISPRLungo (Hwang, Pinello et al., *Nature Biomedical Engineering* 2026) do the analysis. Please cite them if you use these results. Their licences are in [LICENSES.md](LICENSES.md).
- **Example data.** The example samples are public reads of: Nitulescu A-M, Du W, Glaser V, et al. *Single-stranded HDR templates with truncated Cas12a-binding sequences improve knock-in efficiencies in primary human T cells.* Mol Ther Nucleic Acids 36(2):102568 (2025), [doi:10.1016/j.omtn.2025.102568](https://doi.org/10.1016/j.omtn.2025.102568), reads in SRA BioProject [PRJNA1257358](https://www.ncbi.nlm.nih.gov/bioproject/PRJNA1257358). The paper is open access under CC BY-NC-ND 4.0. Nothing from it is copied here: reads and the supplement are downloaded from their original source when you run the pipeline. Details in [LICENSES.md](LICENSES.md#example-data).

## Development

| Item | Definition |
|---|---|
| tests | `python3 -m pytest -q tests` (no cluster, no container) |
| diagrams | edit `docs/diagrams/*.dot` → `bash src/diagrams.sh` |
| gitignored | `tools/ data/ results/ .singularity/ .kv_bin/ .kv_env/` |
