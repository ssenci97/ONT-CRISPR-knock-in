# CRISPRLungo

| | |
|---|---|
| Paper | Hwang, Pinello et al. 2026, *Nature Biomedical Engineering*, "Analysing long-read CRISPR experiments with CRISPRLungo" |
| Repo | https://github.com/pinellolab/CRISPRLungo, pinned `e31ea36` (actively maintained) |
| Env | `kv` (shared): the repo's `environment.yml` (python 3.10, minimap2 2.22, samtools, pysam 0.19.1, pyspoa, vsearch, edlib) plus `pip install -e tools/CRISPRLungo` |
| Knock-in readout | **yes**: `--induced_sequence_path` labels reads `Precise` / `Precise_with_mutations`, and `--integration_file` names large insertions by matching them to the donor sequence |

## What it does
1. **Alignment:** minimap2 against the WT amplicon, with a multipass algorithm that rescues split and chimeric alignments.
2. **Classification:** one class per read — WT, Sub, Ins, Del, LargeIns, LargeDel, Inversion, Complex, ComplexWithLargeMut — counting variants within `--window` bp of the cut.
3. **Background filtering:** with `--control`, mutations also present in the control are discarded.
4. **Desired edit:** with `--induced_sequence_path`, reads are re-aligned to the expected edited allele.
5. **Report:** `combined_graphs.html`, an IGV session, and tables under `results/`.

## Command used here
```
CRISPRlungo refs/TRAC_WT.fa data/<label>.fastq.gz results/CRISPRLungo/<label> GAGTCTCTCAGCTGGTACACGGC \
  --cleavage_pos 17 --window 25 --control data/Mock_r1.fastq.gz \
  --induced_sequence_path refs/TRAC_KI.fa --integration_file refs/CAR_insert.fa -t 8
```
- **`--cleavage_pos`** (default 16 = SpCas9) is the 0-based index in the guide of the last base 5′ of the cut. **AsCas12a cuts after protospacer nt 18, so 17.**
- **`--window 25`** is required here: the knock-in allele carries PAM-blocking mutations from −3 to 0 and at **+20 bp**. With the default 5, CRISPRLungo warns that an induced mutation lies outside the analysis window and no read can be precise.
- **Outputs** in `<outdir>/results/`: `read_classification.txt` (per read: Classification, Mutation_info, Integration_info, Induce_type), `Allele_table.txt`, `mutation_summary_count.txt`, `visualization.sorted.bam`.

## KI % definition
**Reads whose `Integration_info` matches ≥ 80 % of the CAR insert, over classified reads** (`src/summarize.py`, parameter `lungo_min_insert_frac`).

`Induce_type` is **not** used: it compares each read with the whole expected allele, and with a 2,011 bp insert in about Q15 reads every read is labelled `X`. Upstream's answer to that is `--large_induced_insertion`, which judges the junction anchors against a badread-simulated control; that code path crashed twice on upstream bugs (a missing `minimap2_opt` argument, then `[]` passed as `anchor_information`), so it is not used and the tool is not patched.

## Results on the TRAC CD19-CAR data
Earlier subsampled run (20,000 reads per sample, seed 42); the pipeline now uses all length-passing reads.

| run | classified | WT | LargeIns | ≥ 80 % CAR insert | **KI %** |
|---|---|---|---|---|---|
| Mock_r1 | 14,419 | 14,407 | 0 | 0 | **0.00** |
| NoDonor_r1 | 11,088 | 155 | 104 | 1 | **0.01** |
| dsDNA_r1 | 11,390 | 291 | 765 | 469 | **4.12** |
| ssDNA_r1 | 11,599 | 86 | 578 | 89 | **0.77** |
| ssCTS_r1 | 8,706 | 91 | 959 | 622 | **7.14** |

About 1.1 min and 0.6 GB per sample.

**Reading the numbers**
- **Edited samples are almost never WT.** NoDonor and the donor samples are 97–99 % edited, mostly deletions. Mock is 99.9 % WT, so control filtering works.
- **Matching the cassette matters.** NoDonor has 104 large insertions but only 1 matching the CAR cassette. ssDNA has 578 large insertions but only 89 full-cassette matches, so its donors integrate mostly as fragments. Counting `LargeIns` alone would overestimate knock-in.

## Notes
- **`--control` is strongly recommended.** Without it, homopolymer sequencing errors show up as small indels.
- The repo's own examples pass unchanged; its README calls the induced file `induced.fasta`, while the shipped file is `Allele_induced.fasta`.

## Parsing notes
- `--integration_file` is read as strict 2-line FASTA (`CRISPRlungo_insert_analysis.py:66-71`), so `build_refs.py` writes all FASTAs unwrapped.
- KI % counts only `Integration_info` hits on `CAR_insert` (amplicon self-duplications and inversions are not counted). `_split_N` segments are merged back into one read before counting.
