# Licences of the bundled tools

KNOCKIN-VAL itself is a set of wrapper scripts. The analysis is done by two third-party tools, cloned at
the commits pinned in [`configs/tools.tsv`](configs/tools.tsv). Full texts are in [`LICENSES/`](LICENSES/).

| Tool | Commit | Licence | May it be redistributed inside a container image? |
|---|---|---|---|
| [ALPINE](https://github.com/Maggi-Chen/ALPINE) | `b59121d` | MIT — [text](LICENSES/ALPINE.LICENSE.txt) | **Yes.** Keep the copyright notice with it. |
| [CRISPRLungo](https://github.com/pinellolab/CRISPRLungo) | `e31ea36` | AGPL-3.0 for academic use, commercial licence otherwise — [text](LICENSES/CRISPRLungo.LICENSE.txt) | **Yes, with conditions.** Academic use only; anyone you give the image to must be able to get the corresponding source. Commercial use needs a licence from Luca Pinello / Gueho Hwang. |

Both are redistributable, so there is **one image** and it is public. AGPL-3.0 requires that recipients can
obtain the corresponding source: the image ships the full CRISPRLungo git clone at the pinned commit under
`/opt/tools/CRISPRLungo`, and `org.opencontainers.image.source` points at this repository.

## Copied documentation

Verbatim copies of both tools' own documentation are kept in [`docs/upstream/`](docs/upstream/), with
per-file source URLs and sha256s in [`docs/upstream/README.md`](docs/upstream/README.md). Both licences
permit this as long as the notices travel with the copies, which they do via this file and `LICENSES/`.

The papers and the example dataset's supplementary table are **not** copied — the example paper is
CC BY-NC-ND 4.0 (see [Example data](#example-data) below).

## Other components

- Base image `condaforge/miniforge3`, pinned by digest in [`containers/pins.env`](containers/pins.env) —
  BSD-3-Clause.
- conda-forge and bioconda packages, pinned in `containers/kv.lock.txt` — individual open-source licences.
  `bwa` and `vsearch` are GPL-3.0; their source is available from the conda channels.
- Reference sequence from Ensembl REST and the supplementary table from Europe PMC are downloaded at run
  time, verified against `configs/refs.sha256`, and never redistributed.
- Sequencing reads come from SRA BioProjects PRJNA1257358 and PRJNA1183863 (see [Example data](#example-data)).

## Example data

Two published experiments are wired up as examples. Their reads are credited, not redistributed; their
articles are kept as verbatim copies in [`docs/papers/`](docs/papers), which both licences permit.

### Example 1 — TRAC CD19-CAR knock-in with AsCas12a (`example_trac`)

Five public runs of one published experiment.

| Item | Status (checked 2026-11-12) |
|---|---|
| Paper | Nitulescu A-M, Du W, Glaser V, Kath J, Aird EJ, Cullot G, Greensmith R, Mikkelsen NS, Stein M, Bak RO, Kaminski M, Corn JE, Wagner DL. *Single-stranded HDR templates with truncated Cas12a-binding sequences improve knock-in efficiencies in primary human T cells.* Mol Ther Nucleic Acids 36(2):102568 (2025). doi:10.1016/j.omtn.2025.102568, PMC12166421 |
| Paper licence | "© 2025 The Authors", open access under **CC BY-NC-ND 4.0** (Europe PMC full-text XML). Attribution required, non-commercial, no derivatives. |
| Reads | SRA BioProject PRJNA1257358, submitted by ETH Zurich, public since 2025-05-28, no access restriction. The paper's data-availability statement names it as the raw data behind its Figure 4. |
| SRA terms | NCBI places no restrictions on use or distribution of its data, but submitters "may claim patent, copyright, or other intellectual property rights", and NCBI cannot grant permission on their behalf. There is no attribution requirement for the data. |
| Supplement (Table S1) | Downloaded from Europe PMC at run time, pinned by sha256, never copied into this repository or the image. The XML carries no separate licence for it, so it is treated as covered by the article licence. |
| Copy in this repository | [`docs/papers/PMC12166421_Nitulescu2025_ssCTS_knockin.pdf`](docs/papers), the publisher PDF, unmodified. |

CC BY-NC-ND permits redistributing **verbatim** copies with attribution for non-commercial use, which is why
the unmodified PDF may sit in `docs/papers/`. What it forbids is derivatives: do not crop, re-typeset,
excerpt or re-caption the article, its figures or its supplement, and do not paste parts of them into the
README or the manuals. Everything else this repository holds from that work is either a short fact needed to
reproduce the design (accessions, guide and primer sequences) or a number this pipeline computed itself.

### Example 2 — TRAC knock-in with an ARCUS meganuclease and an AAV6 donor (`example_arcus`)

Three public runs of one published experiment: two sorted fractions of the same editing reaction plus a
nuclease-only control, which is what gives this example a real `no_donor` tier.

| Item | Status (checked 2026-11-13) |
|---|---|
| Paper | Nucleic Acids Research, *High-efficiency homology-directed insertion into the genome using the engineered homing endonuclease ARCUS*. doi:10.1093/nar/gkaf961, PMC12497482. Authors are employees of Precision BioSciences, Inc. |
| Paper licence | Open access under **CC BY-NC 4.0** (Europe PMC full-text XML). Attribution required, non-commercial; derivatives are permitted, unlike example 1. |
| Reads | SRA BioProject PRJNA1183863, named in the paper's data-availability statement. Same SRA terms as above. |
| Copy in this repository | [`docs/papers/PMC12497482_ARCUS_TRAC_HDR_insertion.fulltext.xml`](docs/papers) (Europe PMC full text), `...supplement.pdf` and the publisher PDF `...PMC12497482_ARCUS_TRAC_HDR_insertion.pdf`, unmodified. |
| Sequences used | The 22 bp ARCUS recognition site at TRAC, from Supplementary Table S4. The donor allele is **not published as a sequence**: `configs/examples/example_arcus/donor_ki.fa` was reconstructed here from the authors' own reads (SRR31290121) plus the hg38 window, not copied from the article. How, and what it costs, is in the [README](README.md#how-example-2s-donor-was-reconstructed-and-what-that-costs). |

Reading the licences does not replace asking. The corresponding author is Dimitrios L. Wagner; letting the authors know that their dataset is used as the example is good practice.

Nothing here is legal advice.
