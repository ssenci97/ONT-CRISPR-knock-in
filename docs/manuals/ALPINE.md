# ALPINE

| | |
|---|---|
| Paper | Chen et al. 2026, *Bioinformatics*, "ALPINE: a scalable pipeline for comprehensive classification of gene-editing outcomes from long-read amplicon sequencing" |
| Repo | https://github.com/Maggi-Chen/ALPINE, pinned `b59121d` (v1.6) |
| Env | `kv` in the container image; minimap2 2.16 in `$TOOLS/minimap2_216` for `patcher.py` |
| Knock-in readout | **yes, purpose-built**: Unmodified, Unmodified-with-SNP, DEL/INS-small, DEL/INS-large, **HDR-\<vector\>**, Non-HDR-with/without-ITR, INV, DUP, Unclassified |

## What it does
A CWL v1.2 workflow:
1. **`filter_primer`** drops reads missing either primer within `primer_check_length` bp of the ends, and reads below `min_qual` (10 for nanopore).
2. **`minimap2`** aligns with `-a --eqx` against every reference (WT, HDR, ITR-integration).
3. **`samtools_sort`** sorts and indexes.
4. **`classify_read.py`** assigns a class per read from its best reference and the config coordinates: HDR junctions against the homology-arm sequences, ITRs with BLAST, SVs with debreak, indels in `variant_window` around the cut. `patcher.py` re-aligns unclassified reads with minimap2 2.16, whose map-pb preset leaves large deletions unclipped.
5. **`count_read`** writes `<sample>_read_classification.txt` and pie charts.
6. **`group_output`** collects the files.

## Running it here
`src/alpine.sh`, the `alpine` job of `src/pipeline.py`. It writes the CWL job file itself and runs cwltool.

The CWL needs private images (`aavlr_filter:1.6`, `aavlr_classify:1.6.0`, …) that are on no registry, and no build script ships with the repo. The wrapper therefore copies `CWL/`, repoints `/opt/<script>.py` at `tools/ALPINE/DockerFile/<step>/`, sets `coresMin` to `threads` and `ramMin` to `mem_mb`, deletes the `DockerRequirement` blocks, exports `PATCHER_MINIMAP2_PATH`, and runs `cwltool --no-container --preserve-entire-environment`.

Two known quirks:
- **`group_output` fails** with "str object expected; got None" under `--no-container`. It only copies files that already exist, so the wrapper treats it as success when the classification table is present.
- **`plot_pie_charts.py` calls `plt.show()`**, which blocks forever on a desktop session. `MPLBACKEND=Agg` is set in the container image and by `src/kv_job.sh`.

## Inputs
- **`fastqfile`**: one FASTQ(.gz) per sample.
- **`reffile`**: every expected sequence (WT, HDR allele(s), ITR-integration alleles).
- **`config`**: 9-column TSV, `#AAV_Vector Ref_Name Ref_Type ITR1_start ITR1_end gene_start gene_end ITR2_start ITR2_end`, 1-based. WT rows carry the two bases around the cut; HDR rows carry the insert coordinates.
- **Optional**: `primer_1`/`primer_2`, `primer_check_length` (50), **`data_type nanopore`** (the default is pacbio-hifi), `five_prime_HA_seq`/`three_prime_HA_seq`, `HA_Seq_match_ratio` (0.90 for nanopore), `variant_window` (20), `min_qual`.
- There is no guide input: the cut site lives in the WT row of the config.

`src/build_refs.py` writes `refs/alpine/ref.fa` (WT_TRAC + Ref_HDR_CD19) and `refs/alpine/config.tsv` (WT cut site, HDR insert coordinates). No ITR rows, because the donors are linear dsDNA, ssDNA and ssCTS, not AAV.

## Why ALPINE calls fewer knock-ins than CRISPRLungo

Two gates, both in `b59121d`:

1. **Insert-length gate.** `merge_aav_tag` (`classify_read.py:583`) keeps the `HDR-` tag only if
   `truncated_hdr_cutoff * full_insert_length <= observed_insert`, otherwise it rewrites it to
   `Non-HDR-without-ITR-`. The wrapper passes `truncated_cutoff` from the shared `ki_min_insert_frac`,
   the same threshold CRISPRLungo is scored with, so the two columns answer the same question.
2. **Homology-arm gate.** `verify_update_hdr_tag` keeps the tag only for reads that align to **both** arms
   over `ha_match_ratio` of each arm's length. Two helpers hardcode `minimap2 -ax map-hifi`
   (`classify/utils/data_utils.py:89`, `classify/utils/realign_ins_to_wildtype.py:12`) regardless of
   `data_type`, while `classify_read.py` itself picks `map-ont` for nanopore. With `data_type: nanopore`,
   `src/alpine.sh` copies the `DockerFile/` tree into `results/<analysis>/ALPINE/<sample>/cwl_local/` and
   rewrites those two calls to `-ax map-ont` there. **The clone at the pinned commit is never modified**;
   the patch is recorded as `minimap2_preset` and `minimap2_calls_patched` in `results/<analysis>/meta/<sample>.json`.

`find_true_hdr_reads` additionally skips reads carrying an `SA` tag, so a chimeric alignment to a homology
arm also costs the HDR call.

**Reading the classes**
- **HDR-CD19** is strict: both junctions must match the template arms within `HA_Seq_match_ratio`, so it counts precise knock-ins only.
- **Non-HDR-without-ITR-CD19** is CAR sequence without precise junctions, meaning partial or imperfect integration. Compare it with the no-donor control to see the false-positive floor of that class on ONT reads.
- **Unclassified** is mostly reads failing the primer, quality or full-length checks.

## primer_2 orientation
`primer_2` is the reverse primer **as ordered (5'→3')**. `filter_fastq_gz.py` reverse-complements it itself in `main()` (`revcom(args.reve)`) before `primer_in` looks for it at the read ends, so passing it already reverse-complemented makes the filter look for the wrong strand at both ends.

Checked with ALPINE's own `primer_in` on synthetic top- and bottom-strand amplicons: both pass with the primer as written, neither with its reverse complement. If ALPINE classifies only a tiny fraction of the length-passing reads (visible in the Results tab with **Read filtering panel**), check this first.
