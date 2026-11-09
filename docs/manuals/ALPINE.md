# ALPINE

| | |
|---|---|
| Paper | Chen et al. 2026, *Bioinformatics*, "ALPINE: a scalable pipeline for comprehensive classification of gene-editing outcomes from long-read amplicon sequencing" |
| Repo | https://github.com/Maggi-Chen/ALPINE, pinned `b59121d` (v1.6) |
| Envs | `kv` (shared; minimap2 2.22, optional `tools/minimap2_216` fallback for `patcher.py`) |
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
`src/alpine_local.sh <job.yaml> <outdir>`, called by `slurms/05_alpine.sh`.

The CWL needs private images (`aavlr_filter:1.6`, `aavlr_classify:1.6.0`, …) that are on no registry, and no build script ships with the repo. The wrapper therefore copies `CWL/`, repoints `/opt/<script>.py` at `tools/ALPINE/DockerFile/<step>/`, sets `coresMin` to `threads` and `ramMin` to `mem_mb`, deletes the `DockerRequirement` blocks, exports `PATCHER_MINIMAP2_PATH`, and runs `cwltool --no-container --preserve-entire-environment`.

Two known quirks:
- **`group_output` fails** with "str object expected; got None" under `--no-container`. It only copies files that already exist, so the wrapper treats it as success when the classification table is present.
- **`plot_pie_charts.py` calls `plt.show()`**, which blocks forever on a desktop session. `MPLBACKEND=Agg` is exported in `analysis_env.sh`.

## Inputs
- **`fastqfile`**: one FASTQ(.gz) per sample.
- **`reffile`**: every expected sequence (WT, HDR allele(s), ITR-integration alleles).
- **`config`**: 9-column TSV, `#AAV_Vector Ref_Name Ref_Type ITR1_start ITR1_end gene_start gene_end ITR2_start ITR2_end`, 1-based. WT rows carry the two bases around the cut; HDR rows carry the insert coordinates.
- **Optional**: `primer_1`/`primer_2`, `primer_check_length` (50), **`data_type nanopore`** (the default is pacbio-hifi), `five_prime_HA_seq`/`three_prime_HA_seq`, `HA_Seq_match_ratio` (0.90 for nanopore), `variant_window` (20), `min_qual`.
- There is no guide input: the cut site lives in the WT row of the config.

`src/build_refs.py` writes `refs/alpine/ref.fa` (WT_TRAC + Ref_HDR_CD19) and `refs/alpine/config.tsv` (WT cut 2299/2300, HDR insert 2301–4311). No ITR rows, because the donors are linear dsDNA, ssDNA and ssCTS, not AAV.

## Results on the TRAC CD19-CAR data
Earlier subsampled run (20,000 reads per sample, seed 42); the pipeline now uses all length-passing reads. **KI % = HDR-CD19 / classified reads.**

| run | classified | HDR-CD19 | Non-HDR-without-ITR-CD19 | top classes |
|---|---|---|---|---|
| Mock_r1 | 15,900 | **0 (0.00 %)** | – | Unmodified 53.1 %, DEL-small 18.1 %, Unclassified 11.0 % |
| NoDonor_r1 | 13,777 | **0 (0.00 %)** | 1.1 % | DEL-small 61.1 %, Unclassified 20.9 %, DEL-large 14.0 % |
| dsDNA_r1 | 14,185 | **326 (2.30 %)** | 4.4 % | DEL-small 57.1 %, Unclassified 20.9 %, DEL-large 12.3 % |
| ssDNA_r1 | 14,224 | **54 (0.38 %)** | 5.1 % | DEL-small 58.3 %, Unclassified 19.6 %, DEL-large 14.7 % |
| ssCTS_r1 | 12,218 | **452 (3.70 %)** | 5.9 % | DEL-small 47.3 %, Unclassified 29.6 %, DEL-large 11.1 % |

About 1 min and 0.38 GB per sample. One exception: ssCTS_r1 took 60 min, with every step completing and no cause identified.

**Reading the numbers**
- **HDR-CD19 is strict**: both junctions must match the template arms within `HA_Seq_match_ratio`, so it counts precise knock-ins only.
- **Non-HDR-without-ITR-CD19** is CAR sequence without precise junctions, meaning partial or imperfect integration. Its 1.1 % in NoDonor is the false-positive floor of that class on ONT reads.
- **Unclassified** is 11–30 %, mostly reads failing the primer, quality or full-length checks.

Validated once against the shipped `testdata/`: the classification table was identical to the committed expected output.

## primer_2 orientation
The `filter_primer` step looks for `primer_1` at the start of the read and `primer_2` *as given* at the end. That means `primer_2` must be the reverse complement of the 5'→3' reverse primer (`filter_fastq_gz.py:107-116`). Checked on 3,096 dsDNA_r1 reads: 0 % pass with the reverse primer as written and 72 % pass with its reverse complement. `05_alpine.sh` now passes the reverse complement.
