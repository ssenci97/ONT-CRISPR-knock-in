# KNOCKIN-VAL manual

## 1. What this is
Two published tools, each with a **native knock-in readout**, installed at pinned commits and run on the same ONT knock-in amplicon data.

| Tool | Commit | Env | Knock-in readout |
|---|---|---|---|
| ALPINE | `b59121d` (v1.6) | `kv` | per-read classes: HDR, Non-HDR (partial integration), indels, SVs |
| CRISPRLungo | `e31ea36` | `kv` | outcome classes + donor integration matching (`--integration_file`) |

**Removed:** CRISPResso2 (`240cd0a`, 2.3.4) ran here until 2026-11-11. Its MGH end-user licence forbids
copying the software "in any form", so it could not ship inside the container image. See
[LICENSES.md](LICENSES.md) for the reasoning and what the loss of that cross-check costs.

**Not included:** GREPore-seq, VAULT/IDMseq and longread_umi have no knock-in readout, so a KI % from them needs a hand-written metric. PANGEA's repository no longer exists.

## 2. Requirements
- On the cluster: `snakemake` ≥ 8 with the SLURM executor plugin (`envs/snakemake.yml`), `singularity`/`apptainer`, `curl`. Nothing else — the tools and their environment are inside the image. No sudo, no GPU.
- On a workstation, to build the image: `docker` (or `podman`).
- About 15 GB free: 6.5 GB of reads, the rest intermediate and results. Add ~5 GB for the image.
- Resources are per rule, not per script: `default-resources` in `profiles/slurm/config.yaml` sets partition GENOA and the modest defaults; `alpine` and `lungo` ask for 32 CPU / 128 GB / 24 h, `download` and `filter` 16 CPU / 32 GB. Change them in the Snakefile's `threads:`/`resources:` or override per run with `--set-resources`.

## 3. Layout
The repository holds only scripts, envs, configs and docs. Everything else is created by the pipeline and gitignored.
```
Snakefile  the whole pipeline: rules ena, download, filter, refs, alpine, lungo, summary
profiles/  slurm/config.yaml (SLURM executor + apptainer) · local/config.yaml
configs/   samples.tsv · samples/<sample_id>.json (submitted metadata) · sample_schema.json
           tools.tsv (repo, pinned commit) · param_configs.yaml · refs.sha256 (pin)
envs/      kv.yml (inside the image) · snakemake.yml (the launcher env, on the host)
src/       analysis.py (create/freeze an analysis) · common.sh (guards + helpers, sourced by every script)
           download.sh · filter.sh · refs.sh · alpine.sh · lungo.sh
           build_refs.py · summarize.py · sample_meta.py · gui_serve.py · diagrams.sh
gui/       submit.html · submit.css · submit.js (the console: samples, run, results)
tests/     pytest suite, no cluster or container needed
containers/ Dockerfile · build.sh · pins.env · kv.lock.txt (pin) · images.env (digest)
LICENSES/  one file per tool, indexed by LICENSES.md at the root
docs/manuals/{ALPINE,CRISPRLungo,Inputs}.md · docs/diagrams/*.dot · docs/img/*.svg

data/raw/ · data/meta/ · data/raw_refs/   downloads, shared by every analysis (accessions are immutable)
results/<analysis>/
   inputs/    samples.tsv · samples/<id>.json · params.yaml · analysis.json   frozen at creation
   data/      <sample>.fastq.gz · stats/<sample>.tsv        length-filtered reads
   refs/      TRAC_WT.fa · TRAC_KI.fa · CAR_insert.fa · design.json · alpine/
   ALPINE/<sample>/ · CRISPRLungo/<sample>/                 tool outputs
   meta/<sample_id>.json    run provenance, written by src/sample_meta.py
   logs/<step>/             one log + one benchmark TSV per job
   summary.tsv · summary_matrix.tsv · run.log · run_state.json
```

**One analysis, one directory.** `python3 src/analysis.py <name>` validates the sample sheet and copies it,
the per-sample JSONs and `param_configs.yaml` into `results/<name>/inputs/`. From then on the run reads
only those copies, so editing `configs/` cannot change a finished analysis, and two analyses differing in
one parameter sit side by side with the exact inputs that produced each.

## 4. Conventions
- **Parameters** live in `configs/param_configs.yaml`, one section per rule plus `shared:`. They are frozen into the analysis at creation and read from there.
- **SLURM:** snakemake submits one job per rule per sample through the executor plugin; there are no job arrays and no `#SBATCH` headers to keep in sync with the sample count. `jobs: 40` in the profile caps how many are in flight.
- **Logs** start with `[SLURM-INFO]` or `[PYTHON-INFO]` and end with `date | elapsed | max RSS`.
- **No subsampling anywhere.** Every tool gets every read that passes the length filter. `SEED=42` is still exported for any random step.
- **Samples** live in `configs/samples.tsv` (`sample_id`, `srr`, `condition`, `control`). The control is the
  first row with `control=1`. Submit them with the form (`python3 src/gui_serve.py`) or edit the file.
- **Shared parameters** sit in the `shared:` section of `configs/param_configs.yaml` and are read by every
  step. `ki_min_insert_frac` (0.80) drives both ALPINE's `truncated_cutoff` and CRISPRLungo's insert span,
  so the two tools answer the same question.
- **Containers are mandatory.** Snakemake runs every rule in `containers/ont-knockin-val.sif` (or the pinned
  GHCR digest). The Snakefile refuses to start without apptainer, and `src/common.sh` aborts any script that
  finds itself outside the image. `KV_SIF` picks a different image; there is no native mode.
- **The console** (`python3 src/gui_serve.py`) submits samples, names and launches an analysis, and shows its
  results and per-sample metadata. It must run on the host, never inside the container, because it calls
  `sbatch`. One run at a time across all analyses; `results/<analysis>/run_state.json` holds the pid.
- **Everything external is pinned**: tool commits (`configs/tools.tsv`), base image digest
  (`containers/pins.env`), conda packages (`containers/kv.lock.txt`), downloaded references
  (`configs/refs.sha256`). `containers/build.sh` and the Dockerfile refuse anything but a full 40-char SHA.

## 5. Install
```bash
conda env create -f envs/snakemake.yml && conda activate kv_snakemake   # the launcher, on the host
containers/build.sh pull                                                # the image, ~5 GB
python3 -m pytest -q tests                                              # optional, ~30 s
```
That is the whole installation on the cluster. The two tools, their pinned commits, the `kv` conda
environment and minimap2 2.16 are all inside the image; the Dockerfile does the `pip install --no-deps -e
CRISPRLungo` that the tool needs (`--no-deps` matters: without it pip pulls PyPI wheels over the
conda-provided numpy, pandas and pysam, and a PyPI pysam on top of conda's htslib segfaults at import).

**ALPINE without Docker** (`src/alpine.sh`): the upstream CWL runs `/opt/*.py` inside private images that were never published. The script copies the CWL into the analysis directory, repoints those paths at `$TOOLS/ALPINE/DockerFile/*`, lowers `coresMin`/`ramMin` to the job's resources, strips `DockerRequirement`, points `PATCHER_MINIMAP2_PATH` at the image's minimap2 2.16, and runs `cwltool --no-container`.
- The last step, `group_output`, can fail with "str object expected; got None". It only copies finished files, so the run counts as OK when the classification table exists.
- `MPLBACKEND=Agg` is exported, because ALPINE calls `plt.show()`, which blocks forever on a desktop session.

## 6. The data
**SRA PRJNA1257358** — Nitulescu et al. 2025, *Mol Ther Nucleic Acids*, doi:10.1016/j.omtn.2025.102568.
- CD19-CAR knock-in (2,011 bp insert) at *TRAC* in primary human T cells, made with AsCas12a.
- 4.36 kb amplicons, ONT R10.4.1.

| label | run | condition |
|---|---|---|
| Mock_r1 | SRR33387478 | mock electroporated (control) |
| NoDonor_r1 | SRR33387470 | RNP only |
| dsDNA_r1 | SRR33387467 | RNP + dsDNA donor |
| ssDNA_r1 | SRR33387464 | RNP + ssDNA donor |
| ssCTS_r1 | SRR33387474 | RNP + ssCTS donor |

The `download` rule takes the `.sra` objects from the NCBI open-data S3 bucket (ENA serves them at about 10 KB/s from here), converts them with `fasterq-dump` and checks the read count against ENA; `filter` keeps every read of 3.5–7.5 kb (no subsampling). Counts go to `results/<analysis>/data/stats/<sample>.tsv`.

## 7. References (rule `refs` → `src/refs.sh` → `src/build_refs.py`)
- **WT:** hg38 chr14:22,545,232-22,549,589 (4,358 bp), bounded by the paper's gene-specific primers, fetched from Ensembl REST.
- **Knock-in allele:** the paper's Table S1 AsCas12a HDR template (305 bp arms carrying PAM-blocking mutations) placed into the WT. Insert 2,011 bp, KI allele 6,373 bp. The supplements come from Europe PMC.
- **Guide:** crRNA `GAGTCTCTCAGCTGGTACACGGC`, minus strand, cut after WT base 2299.
- Also writes `refs/alpine/{ref.fa,config.tsv}` and `refs/design.json` inside the analysis, which the other rules read.

The dataset was checked once against both of the paper's templates: reads carrying the full insert matched the AsCas12a template (85 / 17 / 108 of 3,000 for dsDNA / ssDNA / ssCTS) and never the SpCas9 one.

## 8. How each tool is run
| Tool | Key settings | KI % |
|---|---|---|
| ALPINE | refs WT + HDR; full ONT-tailed primers with `primer_check_length 150`, because reads still carry barcode sequence; template homology arms; `data_type nanopore` | HDR class / classified reads |
| CRISPRLungo | `--cleavage_pos 17` (AsCas12a cuts after protospacer nt 18); `--window 25`, because a PAM-blocking mutation sits 20 bp from the cut; `--control Mock_r1`; `--induced_sequence_path`; `--integration_file` | reads whose integration covers ≥ 80 % of the CAR insert / classified reads |

## 9. Reference results
From an earlier **subsampled** run (20,000 reads per sample, seed 42); superseded by the full-data run. The `summary` rule regenerates these into `results/<analysis>/summary_matrix.tsv`.

| Tool | Mock | NoDonor | dsDNA | ssDNA | ssCTS |
|---|---|---|---|---|---|
| ALPINE (strict HDR) | 0.00 | 0.00 | **2.30** | **0.38** | **3.70** |
| CRISPRLungo (≥ 80 % of the CAR insert) | 0.00 | 0.01 | **4.12** | **0.77** | **7.14** |

Full-data run of 2026-11-09 (all length-passing reads), which supersedes the table above:

| Tool | Mock | NoDonor | dsDNA | ssDNA | ssCTS |
|---|---|---|---|---|---|
| ALPINE (strict HDR) | 0.00 | 0.00 | **1.31** | **0.00** | **0.35** |
| CRISPRLungo (≥ 80 % of the CAR insert) | 0.00 | 0.00 | **4.23** | **0.85** | **7.12** |

Both predate the 2026-11-11 fix that measures the CAR insert as the **union** of its integration blocks
rather than the largest single block, so CRISPRLungo's figures will rise on the next run.

- **The controls are clean** in both tools.
- **Both rank the donors the same way: ssCTS > dsDNA ≫ ssDNA**, as the paper does.
- **ALPINE counts precise HDR only.** Partial integrations (`Non-HDR-without-ITR`) add 4–6 % in donor samples, and 1.1 % in NoDonor, which is that class's false-positive floor.
- **CRISPRLungo counts any near-full-length cassette at the cut**, so it lands about 1.8–2× above ALPINE.
- **ssDNA integrates mostly as fragments:** 578 large insertions, of which only 89 cover the full cassette.
- Roughly 97–99 % of reads in edited samples are non-WT, mostly deletions. Knock-in is a small share of amplicon reads, and amplicon fractions are not comparable with flow-cytometry CAR+ percentages, because PCR and ONT both favour the shorter alleles.

## 10. Troubleshooting
| Symptom | Cause and fix |
|---|---|
| ALPINE: cwltool refuses `--no-container` | hard `DockerRequirement`; `src/alpine.sh` strips it from its CWL copy |
| ALPINE hangs at `count_read`, 0 % CPU | `plt.show()`; `MPLBACKEND=Agg` is exported |
| ALPINE `group_output … got None` | cosmetic final step; treated as success when the classification table exists |
| ALPINE: one sample took 60 min against 1 min for the others | seen once (ssCTS_r1), all steps completed, cause not identified; rerun that sample |
| CRISPRLungo: 0 desired edits, "induced mutation outside the analysis window" | the PAM-blocking mutation at +20 bp; `--window 25` |
| CRISPRLungo: `Induce_type` is `X` for every read | expected for a 2-kb insert with ONT errors; the KI % uses integration matching instead |
| CRISPRLungo `--large_induced_insertion` crashes | two upstream bugs in that code path; not used here |
| ALPINE reports far less knock-in than CRISPRLungo | by design plus a bug, now patched. It needs the insert to reach `truncated_cutoff` (now `ki_min_insert_frac`, was 0.95 on nanopore) **and** both homology arms to align. The arm check ran `minimap2 -ax map-hifi` hardcoded in two helpers that never see `data_type: nanopore`. Since 2026-11-11 `src/alpine.sh` rewrites those to `-ax map-ont` in a per-run copy; the image's pinned clone is untouched. Expect ALPINE's numbers to rise relative to runs before that date. |
| podman: `Failed to obtain podman configuration: lstat /run/user/<uid>` | no systemd user session on that node. `containers/build.sh` and `analysis_env.sh` now fall back to `$TMPDIR/podman-$(id -u)`; set `XDG_RUNTIME_DIR` yourself if you call podman directly |
| podman: `newuidmap: write to uid_map failed` or "cannot find UID in /etc/subuid" | rootless podman needs a subuid/subgid range for your account; only a cluster admin can add it. Not needed any more: the image is built with Docker on a workstation and pulled on the cluster with `singularity pull`, which needs neither. |
| `refusing to run natively` | the workflow was started without apptainer. Use `--profile profiles/slurm` (or `--sdm apptainer`). |
| `refusing to run outside the container image` | a step script was run by hand. Go through snakemake; the scripts are not meant to be called directly. |
| `results/<name>/inputs/samples.tsv missing` | create the analysis first: `python3 src/analysis.py <name>`. |
| a job cannot see a file that exists | it is outside the bound paths; add `--bind /path` to `apptainer-args` in the profile, symlink targets included. |
| snakemake says the directory is locked | a previous run was killed. `snakemake --unlock --config analysis=<name>`, then run again. |

## 11. Using your own data
1. Submit the samples with `python3 src/gui_serve.py`, or write `configs/samples.tsv` by hand. For your own
   FASTQs, put the absolute path in the `fastq_path` field (stored in `configs/samples/<sample_id>.json`);
   `filter` then length-filters that file instead of downloading an SRA run. The sheet is validated before
   anything runs: sample ids, duplicates, accession format, that the FASTQ path exists, and that one sample
   is marked control.
2. In `configs/param_configs.yaml` under `build_refs:`, set the genomic window, primers, HDR template, guide and `cut_offset_from_guide_5p` (SpCas9 17, AsCas12a 18).
3. Match the nuclease elsewhere: CRISPRLungo `--cleavage_pos` = cut offset − 1, and `--window` must cover every intended mutation.
4. Create the analysis, build the references, check `results/<name>/refs/design.json` (arm mismatches, insert length), then run the rest:
   ```bash
   python3 src/analysis.py my_run
   snakemake --profile profiles/slurm --config analysis=my_run results/my_run/refs/design.json
   snakemake --profile profiles/slurm --config analysis=my_run
   ```

## 12. Which tool to use
**ALPINE 8/10 · CRISPRLungo 7/10**, for ONT knock-in amplicons.
- **ALPINE:** the strictest precise-HDR fraction, with partial integrations reported separately. Treat its
  absolute numbers with care until the `map-hifi` arm-check bug above is patched. About 6 min and 0.15 GB per sample on full data. Costs a CWL workaround, since the images are private.
- **CRISPRLungo:** the full outcome spectrum with control filtering and donor matching. About 11 min and 5 GB per sample on full data. Easiest to install.
- **Default:** run ALPINE and CRISPRLungo together, with a mock control.
