# Licences of the bundled tools

KNOCKIN-VAL itself is a set of wrapper scripts. The analysis is done by three third-party tools, cloned at
the commits pinned in [`configs/tools.tsv`](configs/tools.tsv). Full texts are in [`LICENSES/`](LICENSES/).

| Tool | Commit | Licence | May it be redistributed inside a container image? |
|---|---|---|---|
| [ALPINE](https://github.com/Maggi-Chen/ALPINE) | `b59121d` | MIT — [text](LICENSES/ALPINE.LICENSE.txt) | **Yes.** Keep the copyright notice with it. |
| [CRISPRLungo](https://github.com/pinellolab/CRISPRLungo) | `e31ea36` | AGPL-3.0 for academic use, commercial licence otherwise — [text](LICENSES/CRISPRLungo.LICENSE.txt) | **Yes, with conditions.** Academic use only; anyone you give the image to must be able to get the corresponding source. Commercial use needs a licence from Luca Pinello / Gueho Hwang. |
| [CRISPResso2](https://github.com/pinellolab/CRISPResso2) | `240cd0a` | MGH end-user licence, academic non-commercial — [text](LICENSES/CRISPResso2.LICENSE.txt) | **No.** See below. |

## The constraint that shapes the container design

The CRISPResso2 EULA (section 2) says, of the software it covers:

> You may not copy or distribute the Software Tool in any form. This license is limited to the individual
> that accesses the Software Tool.

A container image containing CRISPResso2 is a copy of it, so pushing such an image to any registry —
public **or** private, inside the institute or not — is distribution, and the licence is granted per
individual rather than per organisation. Each user is expected to obtain CRISPResso2 themselves and attest
to being an academic researcher using it for research only.

Therefore:

- **Published image** (`containers/Dockerfile.base`): system libraries, the conda environment, cwltool and
  ALPINE. MIT and the usual open-source licences only. Safe to push to a registry and pull as a `.sif`.
- **Local layer** (`containers/Dockerfile`): adds CRISPRLungo and CRISPResso2 from their pinned commits.
  Built by each user, on their own machine or on Orfeo, and **never pushed**.

That split keeps the heavy, slow, fragile part — the conda solve, which took 15 minutes in the last run —
reproducible by digest, while the two restricted tools stay where their licences require them to stay.

CRISPResso2 also states it is not approved by the FDA or any other agency, must not be used for clinical
diagnosis, and that MGH collects usage statistics from it.

Nothing here is legal advice. If the institute wants a single pushable image, the people to ask are
licensing@edilytics.com for CRISPResso2 and the contacts in the CRISPRLungo licence.
