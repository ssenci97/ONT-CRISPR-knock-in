# CRISPRLungo

| | |
|---|---|
| Paper | Hwang, Pinello et al. 2026, *Nature Biomedical Engineering*, "Analysing long-read CRISPR experiments with CRISPRLungo" |
| Repo | https://github.com/pinellolab/CRISPRLungo, pinned `e31ea36` (actively maintained) |
| Env | `kv` in the container image (`envs/kv.yml`, locked in `containers/kv.lock.txt`) plus `pip install --no-deps -e` of the pinned clone |
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
  --induced_sequence_path refs/TRAC_KI.fa --integration_file refs/CAR_insert.fa -t <threads>
```
- **`--cleavage_pos`** (default 16 = SpCas9) is the 0-based index in the guide of the last base 5′ of the cut. **AsCas12a cuts after protospacer nt 18, so 17.**
- **`--window 25`** is required here: the knock-in allele carries PAM-blocking mutations from −3 to 0 and at **+20 bp**. With the default 5, CRISPRLungo warns that an induced mutation lies outside the analysis window and no read can be precise.
- **Outputs** in `<outdir>/results/`: `read_classification.txt` (per read: Classification, Mutation_info, Integration_info, Induce_type), `Allele_table.txt`, `mutation_summary_count.txt`, `visualization.sorted.bam`.

## KI % definition
**Reads whose `Integration_info` blocks together cover at least `ki_min_insert_frac` of the CAR insert, over classified reads**
(`src/summarize.py`, shared parameter in `configs/param_configs.yaml`). Overlapping and adjacent blocks
are merged before measuring, so a read whose insert is reported in several pieces is scored on the union of
those pieces.

`Induce_type` is **not** used: it compares each read with the whole expected allele, and with a multi-kb insert in ONT reads nearly every read is labelled `X`. Upstream's answer to that is `--large_induced_insertion`, which judges the junction anchors against a badread-simulated control; that code path crashed twice on upstream bugs (a missing `minimap2_opt` argument, then `[]` passed as `anchor_information`), so it is not used and the tool is not patched.

## Reading the classes
- **Edited samples are rarely WT.** Compare donor and no-donor samples with the mock control: the control should be almost all WT.
- **Matching the cassette matters.** Not every large insertion is the CAR cassette, and donors can integrate as fragments. KI % counts only insertions whose merged blocks cover `ki_min_insert_frac` of the insert; counting `LargeIns` alone would overestimate knock-in. Shorter matches are reported as partial knock-in.

## Notes
- **`--control` is strongly recommended.** Without it, homopolymer sequencing errors show up as small indels.
- The repo's own examples pass unchanged; its README calls the induced file `induced.fasta`, while the shipped file is `Allele_induced.fasta`.

## Parsing notes
- `--integration_file` is read as strict 2-line FASTA (`CRISPRlungo_insert_analysis.py:66-71`), so `build_refs.py` writes all FASTAs unwrapped.
- KI % counts only `Integration_info` hits on `CAR_insert` (amplicon self-duplications and inversions are not counted). `_split_N` segments are merged back into one read before counting.
