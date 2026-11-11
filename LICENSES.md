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

## CRISPResso2 was removed

CRISPResso2 was part of this pipeline until 2026-11-11. It was removed because its end-user licence
(The General Hospital Corporation dba Massachusetts General Hospital) says, in section 2:

> You may not copy or distribute the Software Tool in any form. This license is limited to the individual
> that accesses the Software Tool.

That clause grants the right to *use* the tool but not to ship it. Any container image containing
CRISPResso2 is a copy of it, and the licence is granted per individual rather than per organisation, so no
such image could be pushed to a registry, shared on a cluster filesystem, or handed to a colleague. Rather
than build the pipeline around a tool that cannot travel with it, CRISPResso2 was dropped.

What that cost: CRISPResso2 was the tool used in Nitulescu et al. 2025, and it agreed closely with
CRISPRLungo (4.62 vs 4.23, 1.28 vs 0.85, 7.86 vs 7.12 % knock-in on dsDNA / ssDNA / ssCTS), which is what
established that CRISPRLungo's numbers were sound. That cross-check is no longer run. ALPINE remains as the
second opinion, with the caveat in [`docs/manuals/ALPINE.md`](docs/manuals/ALPINE.md) that it under-reports
on ONT data.

What it bought: the pipeline is ~86% faster (its step, then `07_crispresso`, took 1h05m-2h38m per sample at
up to 34 GB RSS, against ~11 min and 5 GB for CRISPRLungo), the largest SLURM request drops from
64 CPU / 240 GB to 32 CPU / 128 GB, and the image is a single public artifact with no licence conditions
beyond AGPL source availability.

Anyone who wants the CRISPResso2 comparison back should install it themselves from bioconda, under their
own acceptance of the MGH EULA, and run it outside this pipeline.

## Other components

- Base image `condaforge/miniforge3`, pinned by digest in [`containers/pins.env`](containers/pins.env) —
  BSD-3-Clause.
- conda-forge and bioconda packages, pinned in `containers/kv.lock.txt` — individual open-source licences.
  `bwa` and `vsearch` are GPL-3.0; their source is available from the conda channels.
- Reference sequence from Ensembl REST and the supplementary table from Europe PMC are downloaded at run
  time, verified against `configs/refs.sha256`, and never redistributed.
- Sequencing reads come from SRA BioProject PRJNA1257358, which is public.

Nothing here is legal advice.
