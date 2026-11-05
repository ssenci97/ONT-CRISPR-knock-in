# KNOCKIN-VAL manual

## 1. What this is
Three published tools, each with a **native knock-in readout**, installed at pinned commits and run on the same ONT knock-in amplicon data.

| Tool | Commit | Env | Knock-in readout |
|---|---|---|---|
| ALPINE | `b59121d` (v1.6) | `kv_alpine` + `kv_mm216` | per-read classes: HDR, Non-HDR (partial integration), indels, SVs |
| CRISPRLungo | `e31ea36` | `kv_lungo` | outcome classes + donor integration matching (`--integration_file`) |
| CRISPResso2 | `240cd0a` (2.3.4) | `kv_crispresso` | reads assigned to the expected HDR amplicon (`-e`) |

**Not included:** GREPore-seq, VAULT/IDMseq and longread_umi have no knock-in readout, so a KI % from them needs a hand-written metric. PANGEA's repository no longer exists.

## 2. Requirements
- `conda` ≥ 23 (libmamba solver), `git`, `curl`.
- About 15 GB free: 6.5 GB of reads, 5 GB of conda envs, the rest intermediate.
- No Docker and no GPU.
- SLURM headers request 16 CPU / 32 GB on partition GENOA. Locally the scripts use 8 threads.

## 3. Layout
The repository holds only scripts, envs, configs and docs. Everything else is created by the pipeline and gitignored.
```
configs/   tools.tsv (repo, pinned commit, env) · param_configs.yaml
envs/      kv_alpine · kv_mm216 · kv_lungo · kv_crispresso · kv_sra
slurms/    analysis_env.sh (shared library) · 01_clone · 02_envs · 03_fetch · 04_build_refs
           05_alpine · 06_lungo · 07_crispresso · 08_summary · run_all.sh
src/       build_refs.py · summarize.py · alpine_local.sh
docs/manuals/{ALPINE,CRISPRLungo,CRISPResso2}.md

tools/     the 3 cloned repos                         created by 01_clone
data/      meta/ · raw/ · raw_refs/ · <label>.fastq.gz · read_stats.tsv  created by 03_fetch
refs/      TRAC_WT.fa · TRAC_KI.fa · CAR_insert.fa · design.json · alpine/  created by 04_build_refs
results/   <tool>/ · summary.tsv · summary_matrix.tsv        created by 05–07 and 08_summary
logs/      <step>/<tool>_<jobid>_<task>.log
```

## 4. Conventions
- **Parameters** sit at the top of each script. `--yaml-out` writes them to `configs/param_configs.yaml` under the script name; `--yaml-in` reads them back.
- **SLURM:** every step carries a GENOA header. The per-sample steps (`03_fetch`, `05`–`07`) are arrays (`--array=1-5`, fetch `1-5%2`), sized for full runs (~320–490k reads per sample), and `SLURM_ARRAY_TASK_ID` selects the sample. Run with `bash`, they loop over all samples.
- **Logs** start with `[SLURM-INFO]` or `[PYTHON-INFO]` and end with `date | elapsed | max RSS`.
- **No subsampling anywhere.** Every tool gets every read that passes the length filter. `SEED=42` is still exported for any random step.
- Samples and the control are defined in `slurms/analysis_env.sh` (`SAMPLES`, `CONTROL`).

## 5. Install
```bash
bash slurms/01_clone.sh
bash slurms/02_envs.sh            # or: bash slurms/02_envs.sh kv_lungo   (one env)
```
`02_envs` also does `pip install -e tools/CRISPRLungo`, which the tool needs.

**ALPINE without Docker** (`src/alpine_local.sh`): the upstream CWL runs `/opt/*.py` inside private images that were never published. The script copies the CWL, repoints those paths at `tools/ALPINE/DockerFile/*`, lowers `coresMin`/`ramMin`, strips `DockerRequirement`, points `PATCHER_MINIMAP2_PATH` at the minimap2 2.16 in `kv_mm216`, and runs `cwltool --no-container`.
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

`03_fetch` takes the `.sra` objects from the NCBI open-data S3 bucket (ENA serves them at about 10 KB/s from here), converts them with `fasterq-dump`, checks the read count against ENA, and keeps every read of 3.5–7.5 kb (no subsampling). Counts go to `data/read_stats.tsv`.

## 7. References (`04_build_refs` → `src/build_refs.py`)
- **WT:** hg38 chr14:22,545,232-22,549,589 (4,358 bp), bounded by the paper's gene-specific primers, fetched from Ensembl REST.
- **Knock-in allele:** the paper's Table S1 AsCas12a HDR template (305 bp arms carrying PAM-blocking mutations) placed into the WT. Insert 2,011 bp, KI allele 6,373 bp. The supplements come from Europe PMC.
- **Guide:** crRNA `GAGTCTCTCAGCTGGTACACGGC`, minus strand, cut after WT base 2299.
- Also writes `refs/alpine/{ref.fa,config.tsv}` and `refs/design.json`, which the other steps read.

The dataset was checked once against both of the paper's templates: reads carrying the full insert matched the AsCas12a template (85 / 17 / 108 of 3,000 for dsDNA / ssDNA / ssCTS) and never the SpCas9 one.

## 8. How each tool is run
| Tool | Key settings | KI % |
|---|---|---|
| ALPINE | refs WT + HDR; full ONT-tailed primers with `primer_check_length 150`, because reads still carry barcode sequence; template homology arms; `data_type nanopore` | HDR class / classified reads |
| CRISPRLungo | `--cleavage_pos 17` (AsCas12a cuts after protospacer nt 18); `--window 25`, because a PAM-blocking mutation sits 20 bp from the cut; `--control Mock_r1`; `--induced_sequence_path`; `--integration_file` | reads whose integration covers ≥ 80 % of the CAR insert / classified reads |
| CRISPResso2 | amplicon ends N-masked over 100 bp, `--ignore_substitutions`, `--min_bp_quality_or_N 20` (the BMC Res Notes 2024 nanopore recipe); `-e` knock-in allele; `-wc -5 -w 10`; all reads, `-p 64`; plots and report off; `timeout 47h` | HDR-amplicon reads / aligned reads |

## 9. Reference results
From an earlier **subsampled** run (20,000 reads per sample, seed 42); superseded by the full-data run. `08_summary` regenerates these into `results/summary_matrix.tsv`.

| Tool | Mock | NoDonor | dsDNA | ssDNA | ssCTS |
|---|---|---|---|---|---|
| ALPINE (strict HDR) | 0.00 | 0.00 | **2.30** | **0.38** | **3.70** |
| CRISPRLungo (≥ 80 % of the CAR insert) | 0.00 | 0.01 | **4.12** | **0.77** | **7.14** |
| CRISPResso2 | not completed: over 1 h per 1,000 reads on 4–6 kb amplicons | | | | |

- **The controls are clean** in both tools.
- **Both rank the donors the same way: ssCTS > dsDNA ≫ ssDNA**, as the paper does.
- **ALPINE counts precise HDR only.** Partial integrations (`Non-HDR-without-ITR`) add 4–6 % in donor samples, and 1.1 % in NoDonor, which is that class's false-positive floor.
- **CRISPRLungo counts any near-full-length cassette at the cut**, so it lands about 1.8–2× above ALPINE.
- **ssDNA integrates mostly as fragments:** 578 large insertions, of which only 89 cover the full cassette.
- Roughly 97–99 % of reads in edited samples are non-WT, mostly deletions. Knock-in is a small share of amplicon reads, and amplicon fractions are not comparable with flow-cytometry CAR+ percentages, because PCR and ONT both favour the shorter alleles.

## 10. Troubleshooting
| Symptom | Cause and fix |
|---|---|
| ALPINE: cwltool refuses `--no-container` | hard `DockerRequirement`; `alpine_local.sh` strips it from its CWL copy |
| ALPINE hangs at `count_read`, 0 % CPU | `plt.show()`; `MPLBACKEND=Agg` is exported |
| ALPINE `group_output … got None` | cosmetic final step; treated as success when the classification table exists |
| ALPINE: one sample took 60 min against 1 min for the others | seen once (ssCTS_r1), all steps completed, cause not identified; rerun that sample |
| CRISPRLungo: 0 desired edits, "induced mutation outside the analysis window" | the PAM-blocking mutation at +20 bp; `--window 25` |
| CRISPRLungo: `Induce_type` is `X` for every read | expected for a 2-kb insert with ONT errors; the KI % uses integration matching instead |
| CRISPRLungo `--large_induced_insertion` crashes | two upstream bugs in that code path; not used here |
| CRISPResso2 `Cannot parse analysis window coordinate '-5'` | `-qwc` is the window *coordinates* flag; the window *center* is `-wc` |
| CRISPResso2 killed for low memory | each worker holds full-length alignments of both 4–6 kb amplicons; `-p 2` locally |
| CRISPResso2 runs for hours, or hangs while plotting | 64 cores / 240G / 48 h per sample, `--suppress_report --suppress_plots`, `timeout 47h` |

## 11. Using your own data
1. Set your samples and control in `slurms/analysis_env.sh` (`SAMPLES`, `CONTROL`), and the SRA accessions in `slurms/03_fetch.sh`. For your own FASTQs, skip `03_fetch` and drop them in as `data/<label>.fastq.gz`.
2. In `src/build_refs.py`, set the genomic window, primers, HDR template, guide and `cut_offset_from_guide_5p` (SpCas9 17, AsCas12a 18).
3. Match the nuclease elsewhere: CRISPRLungo `--cleavage_pos` = cut offset − 1; CRISPResso2 `-wc` = −(guide length − cut offset); CRISPRLungo `--window` must cover every intended mutation.
4. Run `04_build_refs`, check `refs/design.json` (arm mismatches, insert length), then `05`–`07` and `08_summary`.

## 12. Which tool to use
**ALPINE 8/10 · CRISPRLungo 7/10 · CRISPResso2 5/10**, for ONT knock-in amplicons.
- **ALPINE:** the strictest precise-HDR fraction, with partial integrations reported separately. About 1 min and 0.4 GB per sample. Costs a CWL workaround, since the images are private.
- **CRISPRLungo:** the full outcome spectrum with control filtering and donor matching. About 1 min and 0.6 GB per sample. Easiest to install.
- **CRISPResso2:** solid on short amplicons (≤ 1 kb) and the usual cross-check against Illumina pipelines, but slow and memory-hungry at 4–6 kb. Its own maintainers point long-read users at CRISPRLungo.
- **Default:** run ALPINE and CRISPRLungo together, with a mock control.
