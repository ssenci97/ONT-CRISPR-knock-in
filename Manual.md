# KNOCKIN-VAL manual

## 1. Tools

| Tool | Commit | Env | Knock-in readout |
|---|---|---|---|
| ALPINE | `b59121d` (v1.6) | `kv` | per-read classes: HDR, Non-HDR, indels, SVs |
| CRISPRLungo | `e31ea36` | `kv` | outcome classes + donor integration (`--integration_file`) |

| Excluded | Reason |
|---|---|
| CRISPResso2 (`240cd0a`) | MGH licence forbids copying → [LICENSES.md](LICENSES.md) |
| GREPore-seq, VAULT/IDMseq, longread_umi | no knock-in readout |
| PANGEA | repository gone |

## 2. Requirements

| Where | Needs |
|---|---|
| cluster | `python3` (PyYAML optional), `sbatch`, `singularity` (`module load singularity`), `curl` |
| workstation (build) | `docker` or `podman` |
| disk | ~15 GB data/results + ~5 GB image |
| resources | `RES` in `src/pipeline.py`: GENOA; `alpine`/`lungo` 32 CPU · 128 GB · 24 h; `download`/`filter` 16 CPU · 32 GB |

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
| `meta/<sample_id>.json` | run provenance |
| `logs/<step>/` | one log per job |
| `summary.tsv`, `summary_matrix.tsv`, `summary_classes.tsv` | KI % results; `summary_classes.tsv` has read counts per tool class and outcome group (charted in the Results tab); `summary.tsv` also carries `partial_reads`/`partial_pct` (insert present but below `ki_min_insert_frac`) and the full per-class breakdown in `notes` |
| `run.log`, `run_state.json` | console launch record |

## 4. Conventions

| Term | Definition |
|---|---|
| parameters | `configs/param_configs.yaml`, one section per step + `shared:`; frozen per analysis |
| SLURM | one job per step per sample; no arrays; chained with `--dependency=afterok` |
| logs | start `[SLURM-INFO]`/`[PYTHON-INFO]`, end `date \| elapsed \| max RSS` (`kv_footer`) |
| subsampling | none; `SEED=42` exported anyway |
| control | first row of `samples.tsv` with `control=1` |
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
| tests (optional, ~30 s) | `python3 -m pytest -q tests` |

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
| edit | CD19-CAR (2,011 bp) at *TRAC*, primary human T cells, AsCas12a |
| amplicon | 4.36 kb, ONT R10.4.1 |
| `download` | `.sra` from NCBI S3 → `fasterq-dump` → count checked against ENA |
| `filter` | keep 3.5–7.5 kb; stats in `data/stats/<sample>.tsv` |

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
| WT | hg38 chr14:22,545,232-22,549,589 (4,358 bp), Ensembl REST, bounded by paper primers |
| KI allele | WT + Table S1 AsCas12a template (305 bp arms, PAM-blocking); 6,373 bp |
| insert | 2,011 bp |
| guide | crRNA `GAGTCTCTCAGCTGGTACACGGC`, minus strand, cut after WT base 2299 |
| extra outputs | `refs/alpine/{ref.fa,config.tsv}`, `refs/design.json` |
| template check | full-insert reads match AsCas12a template (85/17/108 of 3,000 dsDNA/ssDNA/ssCTS), never SpCas9 |

## 8. Tool settings

| Tool | Settings | KI % |
|---|---|---|
| ALPINE | WT + HDR refs; ONT-tailed primers, `primer_check_length 150`; template arms; `data_type nanopore` | HDR / classified |
| CRISPRLungo | `--cleavage_pos 17`; `--window 25`; `--control Mock_r1`; `--induced_sequence_path`; `--integration_file` | integration ≥ 80 % of insert / classified |

## 9. Reference results

| Run | Tool | Mock | NoDonor | dsDNA | ssDNA | ssCTS |
|---|---|---|---|---|---|---|
| subsampled (20k reads) | ALPINE | 0.00 | 0.00 | 2.30 | 0.38 | 3.70 |
| subsampled (20k reads) | CRISPRLungo | 0.00 | 0.01 | 4.12 | 0.77 | 7.14 |
| full, 2026-11-09 | ALPINE | 0.00 | 0.00 | 1.31 | 0.00 | 0.35 |
| full, 2026-11-09 | CRISPRLungo | 0.00 | 0.00 | 4.23 | 0.85 | 7.12 |

Both predate the 2026-11-11 fixes (ALPINE `map-ont` patch, CRISPRLungo block union): expect both to rise.

| Finding | Definition |
|---|---|
| controls | clean in both tools |
| donor ranking | ssCTS > dsDNA ≫ ssDNA (matches paper) |
| ALPINE | precise HDR only; `Non-HDR-without-ITR` adds 4–6 % (1.1 % in NoDonor = false-positive floor) |
| CRISPRLungo | any near-full cassette at cut; ~1.8–2× ALPINE |
| ssDNA | mostly fragments: 578 large insertions, 89 full cassette |
| non-WT reads | 97–99 % in edited samples, mostly deletions; not comparable to flow CAR+ % |

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
| job failed or half-done | run `python3 src/pipeline.py <name>` again; done jobs are skipped |
| ALPINE `--no-container` refused | `DockerRequirement`; stripped by `src/alpine.sh` |
| ALPINE hangs at `count_read` | `plt.show()`; `MPLBACKEND=Agg` |
| ALPINE `group_output … got None` | cosmetic; success if table exists |
| ALPINE one sample 60 min | seen once (ssCTS_r1); rerun |
| ALPINE ≪ CRISPRLungo | stricter by design + `map-hifi` bug, patched 2026-11-11 |
| CRISPRLungo 0 desired edits | PAM mutation at +20 bp → `--window 25` |
| CRISPRLungo `Induce_type` = `X` | expected for 2 kb insert on ONT; KI uses integration matching |
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

| Tool | Score | Use for | Cost per sample |
|---|---|---|---|
| ALPINE | 8/10 | strictest precise-HDR fraction; partials separate | ~6 min, 0.15 GB |
| CRISPRLungo | 7/10 | full outcome spectrum, control filtering, donor matching | ~11 min, 5 GB |
| **default** | — | both together, with a mock control | — |
