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
| resources | defaults per tool in `RES` (`src/pipeline.py`); after a finished run, memory = 1.25 × `sacct` MaxRSS (input-scaled) + 0.5 GB, cores = 1.25 × cores used (never above the default), time = 2 × longest + 10 min; OOM/TIMEOUT double at the next launch; ≤ 32 GB per job; ≤ 100 jobs per launch; per-analysis ceiling set by the agency profile (§4) |

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
| agency profile | `--profile` / Run tab **Agency**: `savemem` (default; 1 node, ≤ half of it and ≤ 32 cores / 64 GB), `processive` (≤ 2 nodes of one partition, ≤ half of each), `custom` (`--nodes`, 1–4 ticked nodes, ≤ half of each). Ceilings, not targets; a further node only when the jobs that can run at once do not fit |
| launch plan | DAG-aware: ceiling split into tokens (1 core + equal memory share); each job holds max(cores, memory share) tokens of one node, starts as early as its inputs and tokens allow (longest remaining chain first) and waits `afterany` only for its tokens' previous holders, so the ceiling holds whatever the run times; plan in `logs/node_pick.log` |
| performance metadata | JSON next to the sample metadata: `kv_job.sh` writes `perf` (`jobid node partition asked used started ended`) when a job ends; `pipeline.py` / the Performance page add `sacct` once SLURM has accounted it |
| logs | start `[SLURM-INFO]`/`[PYTHON-INFO]`, end `date \| elapsed \| max RSS` (`kv_footer`) |
| subsampling | none; `SEED=42` exported anyway |
| control | `control_tier` in `samples.tsv`: first `mock`, else first `no_donor`; never row order |
| `ki_min_insert_frac` | `shared:`, 0.80; ALPINE `truncated_cutoff` + CRISPRLungo insert span |
| container | mandatory; `KV_SIF` overrides image; no native mode |
| driver | `src/pipeline.py` on the login node: plans, submits with dependencies, exits; done = outputs exist + log footer + not older than inputs; rerun resumes |
| console | host only (needs `sbatch`); one run at a time; pid in `run_state.json` |
| pins | `tools.tsv`, `pins.env`, `kv.lock.txt`, `refs.sha256`; full 40-char SHAs enforced |

### Shared input names

One name per concept, identical as yaml key, bash variable and argparse flag. SLURM-derived values are not yaml
params.

| Name | Meaning | Used by |
|---|---|---|
| `analysis` | the run's name; everything it produces lives in `results/<analysis>/` | `pipeline.py <name>`, every job |
| `sample_id` | row key of the frozen `inputs/samples.tsv` | `filter` (srr), `lungo` (control), `summary` (condition) |
| `fastq_path` | optional local FASTQ, from `inputs/samples/<sample_id>.json` | `filter`, instead of downloading |
| `fastq` | `results/<analysis>/data/<sample_id>.fastq.gz` (length-filtered) | ALPINE `fastqfile`, CRISPRlungo positional |
| `wt_fasta` · `ki_fasta` · `insert_fasta` | `refs/TRAC_WT.fa` · `TRAC_KI.fa` · `CAR_insert.fa` | CRISPRlungo reference, `--induced_sequence_path`, `--integration_file` |
| `guide`, `primer_f`, `primer_r` | read from `refs/design.json` | `alpine`, `lungo` |
| `ki_min_insert_frac` | `shared:` of the frozen `params.yaml` | `alpine` (`truncated_cutoff`), `summary` |
| `threads`, `mem_mb` | job resources (`RES` in `src/pipeline.py`), passed as `sbatch` options | every tool |
| `KV_OUT` | `results/<analysis>`, exported by `src/kv_job.sh`; every script writes only under it | all |
| `KV_SIF` | override the image every job runs in | `src/kv_job.sh` |

Data flow, all inside `results/<analysis>/` except the shared `data/raw/` download cache:
`inputs/` (frozen) -> `data/<sample_id>.fastq.gz` + `data/stats/` -> `refs/*` -> `ALPINE/`, `CRISPRLungo/` ->
`summary*.tsv`.

`src/sample_meta.py` is the only writer of `results/<analysis>/meta/`. Steps never touch those files directly;
they call `kv_meta <sample_id> <step> k=v`. `configs/sample_schema.json` is the single source of truth for the
console form, its validator and the JSON it writes, and its `design` section does the same for the experiment
design — so the form, the checks and `param_configs.yaml` cannot drift. `src/design.py` holds the derivation
itself and is imported by both `src/build_refs.py` and `src/gui_serve.py`, so what the console predicts and what
`02_refs` builds are the same code.

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

## 7. References (`refs` → `src/refs.sh` → `src/build_refs.py` → `src/design.py`)

| Term | Definition |
|---|---|
| WT | hg38 window `refs.region` from Ensembl REST, trimmed to the paper primers |
| KI allele | WT + the donor template selected by `build_refs.template_title` (PAM-blocking arms) |
| guide | `build_refs.guide`; cut position from `cut_offset_from_guide_5p` |
| primers, gene-specific | `primer_f_specific` / `primer_r_specific`: the part that anneals to hg38; matched in the window to set the amplicon ends |
| primers, full | `primer_f_full` / `primer_r_full`: the same oligos as ordered, 5' tail included, 5'->3'. Optional, and only ALPINE uses them: a 10 bp-window completeness check on the reads, skipped when left empty. Identical to the gene-specific pair when the primers are untailed |
| extra outputs | `refs/alpine/{ref.fa,config.tsv}`, `refs/design.json` (lengths, arms, cut site) |

## 8. Tool settings

| Tool | Settings | KI % |
|---|---|---|
| ALPINE | WT + HDR refs; full primers, both 5'->3' as ordered and both optional; `primer_check_length` 150 (upstream default 50); template arms; `data_type nanopore` (sets min_qual 10 and HA match 0.90; the default pacbio-hifi would apply Q30) | HDR / classified |
| CRISPRLungo | `--cleavage_pos` (0-based along the spacer, applied strand-aware); `--window` (**half-width**, and it gates integration calls too, so it sets the KI number); `--control` (first `mock`, else first `no_donor`, and **omitted when the sample is that control**); `--induced_sequence_path`; `--integration_file` | integration ≥ `ki_min_insert_frac` of insert / classified |

## 9. Reading the results

| Check | What to look for |
|---|---|
| controls | mock and no-donor samples should show no full knock-in in either tool. The control sample runs without `--control`, so its CRISPRLungo class spectrum is a real background and can be compared with ALPINE's |
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
| first run of a tool ends `OUT_OF_MEMORY` | the first-run defaults are modest by design → run the analysis again: the job asks twice as much, done jobs are kept |
| `perf.used.max_rss_gb` ≫ `perf.sacct.max_rss_gb` | the first is the cgroup peak and includes page cache; sizing uses the second |
| job failed or half-done | run `python3 src/pipeline.py <name>` again; done jobs are skipped |
| ALPINE `--no-container` refused | `DockerRequirement`; stripped by `src/alpine.sh` |
| ALPINE hangs at `count_read` | `plt.show()`; `MPLBACKEND=Agg` |
| ALPINE `group_output … got None` | cosmetic; success if table exists |
| ALPINE ≪ CRISPRLungo | stricter by design (precise HDR only); `map-hifi` helpers patched to `map-ont` per run |
| ALPINE classifies almost no reads | not the primers: its filter needs only 10 bp of either primer within `primer_check_length` of the end, checks the reverse complement too, and is skipped entirely when no primer is given. Look at the preset, the reference or the quality filter instead |
| CRISPRLungo 0 desired edits | PAM mutation at +20 bp → `--window 25` |
| CRISPRLungo `Induce_type` = `X` | expected for a multi-kb insert on ONT; KI uses integration matching |
| CRISPRLungo `--large_induced_insertion` crash | upstream bugs; not used |
| podman `lstat /run/user/<uid>` | no user session; fallback `$TMPDIR/podman-$(id -u)` |
| podman `newuidmap` / subuid | needs admin; use Docker on workstation + `singularity pull` |

## 11. Own data

| Step | Action |
|---|---|
| 1. samples | console or `configs/samples.tsv`; local reads → `fastq_path` |
| 2. design | console → Samples → **Experiment design**: the four open groups (window, nuclease and guide, primers, donor) are the required ones; **Optional** (read filters, scoring, public-data ids) and **Advanced** (tool internals) are collapsed and can stay at their defaults. Or `build_refs:` in `param_configs.yaml` by hand |
| 3. nuclease | pick it in the design panel: it fills `cut_offset_from_guide_5p` (SpCas9 17, AsCas12a 18, ARCUS 11) and CRISPRLungo `--cleavage_pos` = cut offset − 1; `--window` must cover all intended mutations |
| 4. dry run | `python3 src/pipeline.py <name> --dry-run`; after `02_refs`, check arms and insert length in `refs/design.json` |
| 5. run | `python3 src/pipeline.py <name>`; rerun to resume |

| Validation (before run) | Checks |
|---|---|
| sample sheet | ids, duplicates, accession format, `fastq_path` exists, one control |
| design | every required field filled, primers and guide located in the window, each full primer ending with its gene-specific part, arms and insert derived from the donor, region well-formed, one donor source, cut positions consistent (console → **Experiment design**) |

## 12. ALPINE in detail

Pinned `b59121d` (v1.6). Paper: Chen et al. 2026, *Bioinformatics*. The authors' own documentation is in
[`docs/manuals/ALPINE.md`](docs/manuals/ALPINE.md); everything below is what *this pipeline* does with it, verified
against the pinned source.

**The workflow.** A CWL v1.2 pipeline: `filter_primer` (drops reads missing a primer near the ends, and reads
below `min_qual`, 10 for nanopore) -> `minimap2 -a --eqx` against every reference -> `samtools_sort` ->
`classify_read.py` (one class per read, from its best reference plus the config coordinates) -> `count_read`
(writes `<sample>_read_classification.txt`) -> `group_output`.

**Why we patch it.** The shipped CWL needs private images (`aavlr_filter:1.6`, …) that are on no registry and
have no build script. So `src/alpine.sh` copies `CWL/`, repoints `/opt/<script>.py` at the clone, sets
`coresMin`/`ramMin`, deletes the `DockerRequirement` blocks and runs `cwltool --no-container`. **The clone
itself is never modified.** Two quirks are handled: `group_output` fails with "str object expected; got None"
under `--no-container` (it only copies existing files, so the wrapper accepts success once the table is there),
and `plot_pie_charts.py` calls `plt.show()`, which blocks forever — `MPLBACKEND=Agg` is set in the image.

**The minimap2 preset.** `data_utils.py:89` hardcodes `-ax map-hifi` regardless of `data_type`, while
`classify_read.py` itself picks `map-ont` for nanopore. With `data_type: nanopore` the wrapper rewrites that
call to `map-ont` in its local copy. A second file, `realign_ins_to_wildtype.py:12`, hardcodes the same preset
and is patched too, but is **dead code** at this commit, so `minimap2_calls_patched: 2` counts one rewrite that
has no effect. Both values are recorded in `results/<analysis>/meta/<sample>.json`.

**Why ALPINE calls fewer knock-ins.** Two gates. The *insert-length gate* (`classify_read.py:583`) keeps the
`HDR-` tag only if `truncated_cutoff x full_insert_length <= observed_insert`, else rewrites it to
`Non-HDR-without-ITR-`; we feed it the shared `ki_min_insert_frac` so both tools answer the same question. The
*homology-arm gate* (`verify_update_hdr_tag`) keeps the tag only for reads aligning to **both** arms over
`HA_Seq_match_ratio` (0.90 for nanopore). `find_true_hdr_reads` also skips reads carrying an `SA` tag, so a
chimeric alignment costs the HDR call.

**Primers.** Pass both **as ordered, 5'->3'**. `main()` hands the filter `revcom(args.reve)`
(`filter_fastq_gz.py:64`), and `primer_in` (`:107-117`) tests two paired branches: a sense read needs
`primer_1` as given in the head **and** revcom(`primer_2`) in the tail; an antisense read needs the mirror. So
each primer is searched in both orientations, but only at the end that pairs with the other — reverse-
complementing `primer_2` yourself inverts both branches and empties the sample. Two further properties of
`is_subsequence` (`:96-104`): an **empty** primer returns True for every read, so a blank primer disables that
side of the check rather than rejecting everything (omitting the key and passing `""` are equivalent); and a
primer **shorter than 10 bp** returns False for every read, silently discarding the whole sample — the console
refuses one.

**Inputs.** `fastqfile` (one per sample); `reffile` (every expected sequence); `config` (9-column TSV, 1-based,
WT rows carrying the two bases around the cut, HDR rows the insert coordinates). There is no guide input: the
cut site lives in the WT row. `src/build_refs.py` writes no ITR rows, because our donors are linear dsDNA,
ssDNA and ssCTS, not AAV — which also means `Non-HDR-with-ITR` can never occur here.

**Defaults we rely on**: `truncated_cutoff` is data-type dependent in the code (0.95 nanopore / 0.99 hifi,
`classify_read.py:918-921`) even though the README says a flat 0.99; `primer_check_length` defaults to 50 and we
pass 150, because a nanopore read can carry residual adapter and barcode ahead of the primer; `variant_window`
defaults to 20 and we pass 25 to match CRISPRLungo.

**Reading the classes.** `HDR-<vector>` is strict — both junctions must match the template arms — so it counts
precise knock-ins only. `Non-HDR-without-ITR-<vector>` is donor sequence without precise junctions: partial or
imperfect integration; compare it against the no-donor control for that class's false-positive floor.
`Unclassified` is unmapped reads, reads with complex alignments and reads not spanning the cut; it is excluded
from the denominator and reported separately, because CRISPRLungo emits nothing comparable.

## 13. CRISPRLungo in detail

Pinned `e31ea36`. Paper: Hwang, Pinello et al. 2026, *Nature Biomedical Engineering*. The authors' own
documentation is in [`docs/manuals/CRISPRLungo.md`](docs/manuals/CRISPRLungo.md).

**The workflow.** minimap2 against the WT amplicon with a multipass algorithm that rescues split and chimeric
alignments -> one class per read (WT, Sub, Ins, Del, LargeIns, LargeDel, Inv, Complex, ComplexWithLargeMut) ->
optional background filtering against a control -> optional re-alignment to the expected edited allele ->
`combined_graphs.html`, an IGV session and tables under `results/`.

**`--window` is a half-width, and it is not only an indel knob.** The kept region is `[cut-W, cut+W]`
(`CRISPRlungo_mutation_analysis.py:64-65`); the default is 5 (`CRISPRlungo.py:82`). It **also gates integration
detection, so it sets the knock-in number**: `check_in_window` runs before `confirm_insertion_seq`, the only
producer of `Integration_info`, which iterates the in-window bucket alone. An insertion junction outside the
window contributes nothing to `ki_reads`, so lowering `--window` silently lowers the knock-in percentage. We use
25 because the example donor carries PAM-blocking mutations from -3 to 0 and at **+20 bp**.

**`--control` is not a subtraction.** Each mutation pattern faces a 2x2 enrichment test against the control
(Fisher or chi-square, `:805-903`); only patterns that pass enter the read's real-mutation bucket and the rest
move to an unread column. A large insertion absent from the control is force-passed (`:869-870`), which is why
genuine knock-ins survive. **A sample cannot be its own control**: with identical files every ratio is equal, so
nothing is ever enriched and the sample collapses to near-100% WT. The pipeline therefore omits `--control`
entirely for the control sample itself.

**`--cleavage_pos` is strand-aware.** It is a 0-based offset along the spacer from the spacer's own 5' end, and
the tool searches both strands (`CRISPRlungo.py:266-272`). For a minus-strand guide it computes
`start + len - cleavage_pos - 2`, which equals our `design.py` cut boundary minus one — so the rule that it is
always one less than `cut_offset_from_guide_5p` holds on either strand.

**How the KI % is built.** Reads whose `Integration_info` blocks together cover at least `ki_min_insert_frac` of
the insert, over classified reads (`src/summarize.py`). Overlapping and adjacent blocks are merged first, so a
read reported in several pieces is scored on the union, and `_split_N` segments are merged back into one read.
`inRef` coordinates are inside the integration reference, 1-based with an exclusive end, always ascending
(`CRISPRlungo_insert_analysis.py:174-175`). Only hits on the insert count — amplicon self-duplications and
inversions do not. Note that orientation is **not** currently checked, so an inverted cassette counts as a
knock-in.

**`Induce_type` is not used.** It compares each read against the whole expected allele, and with a multi-kb
insert on ONT nearly every read is labelled `X`. Upstream's answer is `--large_induced_insertion`, which needs
`badread`; that is not in `envs/kv.yml`, so `CRISPRlungo_insert_analysis.py:224` hard-errors before it can run.

**Defaults we rely on**: `--align_sa_len_threshold` 100 is the minimum soft-clip that gets re-aligned, i.e. the
mechanism that *creates* our split knock-in reads, not a filter that drops them; `--min_read_cnt` and
`--min_read_freq` both default to 0 and neither touches `read_classification.txt`. `--integration_file` is read
as strict two-line FASTA (`CRISPRlungo_insert_analysis.py:66-71`), so `build_refs.py` writes all FASTAs
unwrapped. Outputs land in `<outdir>/results/`, lowercase `read_classification.txt`, columns `Read_id,
Classification, Mutation_info, Integration_info, Induce_type, whole_mutation`.

## 14. Which tool

| Tool | Use for |
|---|---|
| ALPINE | strictest precise-HDR fraction; partials separate |
| CRISPRLungo | full outcome spectrum, control filtering, donor matching |
| **default** | both together, with a mock control |
