# CRISPResso2 (nanopore recipe)

| | |
|---|---|
| Papers | Clement et al. 2019, *Nat Biotechnol* (CRISPResso2); McFarlane, Polanco & Bogema 2024, *BMC Res Notes* 17:205, "CRISPR-Cas guide RNA indel analysis using CRISPResso2 with Nanopore sequencing data" |
| Repo | https://github.com/pinellolab/CRISPResso2, pinned `240cd0a` (v2.3.4). The BMC paper has no code; its recipe is in Supp. Table 3 |
| Env | `kv` (shared): bioconda `crispresso2` 2.3.4 + seqkit |
| Knock-in readout | **yes**: `-e` gives the expected HDR amplicon, and reads are assigned to WT or HDR |

## The nanopore recipe
CRISPResso2 was built for short Illumina amplicons. The BMC 2024 paper adapts it for ONT:
- **Mask 100 bp of N at both amplicon ends**, so that soft-clipped or adapter-carrying read ends do not count as edits.
- **`--ignore_substitutions`**, because ONT substitution errors would otherwise dominate.
- **`--min_bp_quality_or_N 20`**.

Reproduced once on the paper's own data (PRJNA1109565, 100,000-read subsamples): sheep MSTN 67.8 % indels against the paper's 64 %, horse MSTN 86.3 % against 86 %. The recipe holds.

## Command used here
```
CRISPResso --fastq_r1 <label>.capped.fastq.gz -a <TRAC_WT, ends N-masked> -an TRAC_WT \
  -e <TRAC_KI, ends N-masked> -g GAGTCTCTCAGCTGGTACACGGC -wc -5 -w 10 \
  --ignore_substitutions --min_bp_quality_or_N 20 --suppress_report --suppress_plots -p 2
```
- **`-wc -5`** is `--quantification_window_center`. AsCas12a cuts after protospacer nt 18 of a 23-nt crRNA, so the last base before the cut sits 5 nt from the guide 3′ end. For SpCas9 it would be −3.
  **Do not confuse it with `-qwc`**, which is `--quantification_window_coordinates` and fails with "Cannot parse analysis window coordinate '-5'".
- **KI %** = `Reads_aligned` of the HDR amplicon / `Reads_aligned_all_amplicons`.
- **No read cap.** All length-passing reads are used (~320–490k per sample).

## Result here: not completed
The earlier workstation run (subsampled) was stopped. On 4,358 bp WT and 6,373 bp knock-in amplicons, CRISPResso2 aligns every unique read globally against both references, which is O(L²) per read, and ONT reads are almost never identical.

Measured on this machine (8 cores, 7.7 GB):
- 5,000 reads with 2 workers: **2 h 44 min** per sample.
- 1,000 reads with 2 workers: **about 1 h** per sample.
- With `-p 4`, the session was killed for low system memory.
- Once, the plotting step hung for 10 h at 0 % CPU. Plots and report are now suppressed and every sample runs under `timeout 3h`.

The Mock control did complete: 627 of 1,000 reads aligned, 0 to the knock-in allele, 10.2 % of WT-assigned reads modified. That is the expected background.

`slurms/07_crispresso.sh` now runs every read with `-p $SLURM_CPUS_PER_TASK` (64) on 240G for up to 48 h per sample (one array task each). At ~1.1 worker-h per 1,000 reads this is ~6–8 h per sample on 64 cores.

## Known upstream issues
- **#565:** no hard amplicon length limit; 1–5 kb works, about 15 kb exhausts memory.
- **#484:** memory grows with the number of unique reads, which is nearly every read on ONT data. Cap the reads, or split and use `CRISPRessoAggregate`.
- **#668:** truncated reads score as large deletions in global alignment, so reads are length-filtered to 3.5–7.5 kb in `03_fetch`.
- **#309 / #636:** long reads are "not validated"; the maintainers recommend CRISPRLungo for long-read amplicons.

**Verdict for this use case:** fine for short amplicons and as a cross-check against Illumina pipelines, impractical at 4–6 kb.
