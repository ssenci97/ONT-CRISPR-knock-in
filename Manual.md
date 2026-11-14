# KNOCKIN-VAL manual

## 1. Tools

| Tool | Commit | Env | Knock-in readout |
|---|---|---|---|
| ALPINE | `b59121d` (v1.6) | `kv` | per-read classes: HDR, Non-HDR, indels, SVs |
| CRISPRLungo | `e31ea36` | `kv` | outcome classes + donor integration (`--integration_file`) |

| Excluded | Reason |
|---|---|
| GREPore-seq, VAULT/IDMseq, longread_umi | no knock-in readout |
| PANGEA | repository gone |

## 2. Requirements

| Where | Needs |
|---|---|
| cluster | `python3` (PyYAML optional), `sbatch`, `singularity` (`module load singularity`), `curl` |
| workstation (build) | `docker` or `podman` |
| disk | room for the downloaded reads, results and the image |
| resources | CPUs per tool in `RES` (`src/pipeline.py`); memory/time learned from earlier runs (log footer + `sacct`); ≤ 32 GB per job; ≤ 100 jobs per launch; per-analysis ceiling set by the agency profile (§4) |

## 3. Layout

| Path | Holds |
|---|---|
| `configs/` | `samples.tsv`, `samples/<id>.json`, `sample_schema.json`, `tools.tsv`, `param_configs.yaml`, `refs.sha256` |
| `envs/` | `kv.yml` (in image) |
| `src/` | `analysis.py`, `pipeline.py`, `kv_job.sh`, `common.sh`, step scripts (`ena download filter refs alpine lungo summary`), `build_refs.py`, `summarize.py`, `sample_meta.py`, `gui_serve.py`, `diagrams.sh` |
| `gui/` | console: `submit.html/.css/.js` |
| `tests/` | pytest, no cluster/container |
| `containers/` | `Dockerfile`, `build.sh`, `pins.env`, `kv.lock.txt`, `images.env` |
| `data/raw/`, `data/meta/`, `data/raw_refs/` | downloads shared by all analyses |
| `results/<analysis>/` | see below |

| `results/<analysis>/…` | Holds |
|---|---|
| `inputs/` | frozen `samples.tsv`, `samples/<id>.json`, `params.yaml`, `analysis.json` (with sha256) |
| `jobs.tsv`, `.lock` | SLURM job ids of the last launch; one-launch lock |
| `data/` | filtered `<sample>.fastq.gz`, `stats/<sample>.tsv` |
| `refs/` | `TRAC_WT.fa`, `TRAC_KI.fa`, `CAR_insert.fa`, `design.json`, `alpine/` |
| `ALPINE/<sample>/`, `CRISPRLungo/<sample>/` | tool outputs |
| `meta/<sample_id>.json` | run provenance; `steps.<step>.perf` = the job's performance record (asked, used, `sacct`) |
| `meta/_analysis.json` | `perf` records of jobs that belong to no sample (ENA, downloads, refs, summary), keyed by job name |
| `logs/<step>/` | one log per job |
| `summary.tsv`, `summary_matrix.tsv`, `summary_classes.tsv` | KI % results; `summary_classes.tsv` has read counts per tool class and outcome group (charted in the Results tab); `summary.tsv` also carries `partial_reads`/`partial_pct` (insert present but below `ki_min_insert_frac`) and the full per-class breakdown in `notes` |
| `run.log`, `run_state.json` | console launch record; `run_state.json` also holds `profile`, the `nodes` used, and `group` for analyses launched together by **All examples** |

## 4. Conventions

| Term | Definition |
|---|---|
| parameters | `configs/param_configs.yaml`, one section per step + `shared:`; frozen per analysis |
| SLURM | one job per step per sample; no arrays; chained with `--dependency=afterok` |
| agency profile | `--profile` / Run tab **Agency**: `savemem` (default; 1 node, ≤ half of it and ≤ 32 cores / 64 GB), `processive` (≤ 2 nodes of one partition, ≤ half of each), `custom` (`--nodes`, 1–4 ticked nodes, ≤ half of each). Ceilings, not targets: lanes = min(fit, parallel width); a further node only when the width does not fit |
| performance metadata | JSON next to the sample metadata: `kv_job.sh` writes `perf` (`jobid node partition asked used started ended`) when a job ends; `pipeline.py` / the Performance page add `sacct` once SLURM has accounted it |
| logs | start `[SLURM-INFO]`/`[PYTHON-INFO]`, end `date \| elapsed \| max RSS` (`kv_footer`) |
| subsampling | none; `SEED=42` exported anyway |
| control | `control_tier` in `samples.tsv`: first `mock`, else first `no_donor`; never row order |
| `ki_min_insert_frac` | `shared:`, 0.80; ALPINE `truncated_cutoff` + CRISPRLungo insert span |
| container | mandatory; `KV_SIF` overrides image; no native mode |
| driver | `src/pipeline.py` on the login node: plans, submits with dependencies, exits; done = outputs exist + log footer + not older than inputs; rerun resumes |
| console | host only (needs `sbatch`); one run at a time; pid in `run_state.json` |
| pins | `tools.tsv`, `pins.env`, `kv.lock.txt`, `refs.sha256`; full 40-char SHAs enforced |

## 5. Install

| Step | Command |
|---|---|
| image | `srun -p THIN --mem=16G -c 4 --time=00:30:00 containers/build.sh pull` |
| console (auto-loads singularity) | `python3 src/gui_serve.py` |
| tests | automatic during `build.sh pull` (unit tests in background + container smoke test); alone: `containers/build.sh test` |

| Image detail | Definition |
|---|---|
| contents | both tools at pinned commits, `kv` env, minimap2 2.16 |
| CRISPRLungo install | `pip install --no-deps -e`; without `--no-deps` PyPI pysam segfaults on conda htslib |
| ALPINE without Docker | `src/alpine.sh` copies the CWL, repoints `/opt/*.py`, sets cores/RAM, strips `DockerRequirement`, `cwltool --no-container` |
| `group_output` error | "str object expected; got None"; OK if classification table exists |
| `MPLBACKEND=Agg` | avoids `plt.show()` hang |

## 6. Data

| Item | Value |
|---|---|
| project | SRA PRJNA1257358 — Nitulescu et al. 2025, *Mol Ther Nucleic Acids*, doi:10.1016/j.omtn.2025.102568 |
| project 2 | SRA PRJNA1183863 — ARCUS homology-directed insertion, *Nucleic Acids Res* 2025, doi:10.1093/nar/gkaf961 |
| edit | CD19-CAR at *TRAC*, primary human T cells, AsCas12a |
| amplicon | ONT R10.4.1 |
| `download` | `.sra` from NCBI S3 → `fasterq-dump` → count checked against ENA |
| `filter` | keep reads between `fetch.min_len` and `fetch.max_len`; stats in `data/stats/<sample>.tsv` |

| Label | Run | Condition |
|---|---|---|
| Mock_r1 | SRR33387478 | mock electroporated (control) |
| NoDonor_r1 | SRR33387470 | RNP only |
| dsDNA_r1 | SRR33387467 | RNP + dsDNA donor |
| ssDNA_r1 | SRR33387464 | RNP + ssDNA donor |
| ssCTS_r1 | SRR33387474 | RNP + ssCTS donor |

## 7. References (`refs` → `src/refs.sh` → `src/build_refs.py`)

| Term | Definition |
|---|---|
| WT | hg38 window `refs.region` from Ensembl REST, trimmed to the paper primers |
| KI allele | WT + the donor template selected by `build_refs.template_title` (PAM-blocking arms) |
| guide | `build_refs.guide`; cut position from `cut_offset_from_guide_5p` |
| extra outputs | `refs/alpine/{ref.fa,config.tsv}`, `refs/design.json` (lengths, arms, cut site) |

## 8. Tool settings

| Tool | Settings | KI % |
|---|---|---|
| ALPINE | WT + HDR refs; full primers (`primer_2` = reverse primer as ordered); `primer_check_length`; template arms; `data_type nanopore` | HDR / classified |
| CRISPRLungo | `--cleavage_pos`; `--window`; `--control` (first `mock`, else first `no_donor`); `--induced_sequence_path`; `--integration_file` | integration ≥ `ki_min_insert_frac` of insert / classified |

## 9. Reading the results

| Check | What to look for |
|---|---|
| controls | mock and no-donor samples should show no full knock-in in either tool |
| read filtering | Results tab → **Read filtering panel**: raw → length-passing → classified reads per tool; a tool classifying only a small fraction points at a setup problem (primers, preset) |
| ALPINE vs CRISPRLungo | ALPINE counts only precise HDR (both arms validated); CRISPRLungo counts any near-full cassette at the cut, so it is expected to be higher |
| partials | `Non-HDR-*` (ALPINE) and sub-threshold insertions (CRISPRLungo) are reported as partial knock-in, not hidden |
| non-WT reads | edited samples are mostly deletions; not comparable to flow-cytometry CAR+ % |

## 10. Troubleshooting

| Symptom | Cause → fix |
|---|---|
| browser: *Unable to connect* | tunnel not running on laptop |
| `refusing to run natively` | no singularity → `module load singularity` |
| `refusing to run outside the container image` | script run by hand → use `python3 src/pipeline.py <name>` |
| `results/<name>/inputs/samples.tsv missing` | `python3 src/analysis.py <name>` first |
| job cannot see a file | add `--bind /path` to `apptainer-args` (symlink targets too) |
| refused: live SLURM jobs / lock held | wait, or `python3 src/pipeline.py <name> --stop` |
| refused: inputs changed | frozen inputs were edited → create a new analysis |
| refused: `custom profile needs 1-4 available nodes` | a ticked node is drained, down or busy now → reopen **Custom** (the list is refreshed from `sinfo`) and tick others |
| Processive used only one node | the parallel jobs fit on the first node, or no second node of that partition had room for the widest job; `logs/node_pick.log` says which |
| **All examples** shows one report | fixed: the Results tab now shows one KI % table per analysis of the group; a missing table means that analysis' summary job has not finished (see its Run tab) |
| `perf.used.max_rss_gb` is `null` | the job's cgroup peak is not readable on that node; `perf.sacct.max_rss_gb` fills it after accounting |
| job failed or half-done | run `python3 src/pipeline.py <name>` again; done jobs are skipped |
| ALPINE `--no-container` refused | `DockerRequirement`; stripped by `src/alpine.sh` |
| ALPINE hangs at `count_read` | `plt.show()`; `MPLBACKEND=Agg` |
| ALPINE `group_output … got None` | cosmetic; success if table exists |
| ALPINE ≪ CRISPRLungo | stricter by design (precise HDR only); `map-hifi` helpers patched to `map-ont` per run |
| ALPINE classifies almost no reads | `primer_2` must be the reverse primer as ordered (ALPINE reverse-complements it itself) |
| CRISPRLungo 0 desired edits | PAM mutation at +20 bp → `--window 25` |
| CRISPRLungo `Induce_type` = `X` | expected for a multi-kb insert on ONT; KI uses integration matching |
| CRISPRLungo `--large_induced_insertion` crash | upstream bugs; not used |
| podman `lstat /run/user/<uid>` | no user session; fallback `$TMPDIR/podman-$(id -u)` |
| podman `newuidmap` / subuid | needs admin; use Docker on workstation + `singularity pull` |

## 11. Own data

| Step | Action |
|---|---|
| 1. samples | console or `configs/samples.tsv`; local reads → `fastq_path` |
| 2. design | `build_refs:` in `param_configs.yaml`: window, primers, template, guide, `cut_offset_from_guide_5p` (SpCas9 17, AsCas12a 18) |
| 3. nuclease | CRISPRLungo `--cleavage_pos` = cut offset − 1; `--window` covers all intended mutations |
| 4. dry run | `python3 src/pipeline.py <name> --dry-run`; after `02_refs`, check arms and insert length in `refs/design.json` |
| 5. run | `python3 src/pipeline.py <name>`; rerun to resume |

| Validation (before run) | Checks |
|---|---|
| sample sheet | ids, duplicates, accession format, `fastq_path` exists, one control |

## 12. Which tool

| Tool | Use for |
|---|---|
| ALPINE | strictest precise-HDR fraction; partials separate |
| CRISPRLungo | full outcome spectrum, control filtering, donor matching |
| **default** | both together, with a mock control |
