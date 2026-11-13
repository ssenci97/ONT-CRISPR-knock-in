# Upstream documentation (verbatim copies)

Verbatim copies of the two analysis tools' own documentation, taken at the commits pinned in
[`configs/tools.tsv`](../../configs/tools.tsv). They are here so the pipeline's parameter choices can be
checked against the authors' own wording without network access, and so that a future upstream edit cannot
silently change what this repository was built against.

**Nothing in this directory is written or modified by this project.** For this project's own reading of the
tools — what each argument means here, the known quirks and the patches applied — see
[`docs/manuals/ALPINE.md`](../manuals/ALPINE.md) and [`docs/manuals/CRISPRLungo.md`](../manuals/CRISPRLungo.md),
which cite these files.

Retrieved 2026-11-13.

## Licences

Copying is permitted by both licences, provided the notices travel with the copies. Full texts are in
[`LICENSES/`](../../LICENSES/) and the terms are summarised in [`LICENSES.md`](../../LICENSES.md).

| Source | Licence | Condition on these copies |
|---|---|---|
| [ALPINE](https://github.com/Maggi-Chen/ALPINE) @ `b59121d` | MIT, © 2026 Maggie Chen, Xing-Huang Gao — [text](../../LICENSES/ALPINE.LICENSE.txt) | Keep the copyright and permission notice with the copy. |
| [CRISPRLungo](https://github.com/pinellolab/CRISPRLungo) @ `e31ea36` | AGPL-3.0 for academic use, commercial licence otherwise — [text](../../LICENSES/CRISPRLungo.LICENSE.txt) | Academic use. Recipients must be able to obtain the corresponding source; commercial use needs a licence from Luca Pinello. |

**Not copied, deliberately:** the two papers and the example dataset's supplementary table. The example
paper is CC BY-NC-ND 4.0, which forbids redistributing it here — see the Example data section of
[`LICENSES.md`](../../LICENSES.md). Cite those; do not vendor them.

CRISPRLungo's upstream `docs/` directory is a browser application (JavaScript, WebAssembly and two example
FASTQ files), not prose, so it is not copied.

## Files

| Copy | Source at the pinned commit | sha256 |
|---|---|---|
| `ALPINE/README.md` | [`README.md`](https://github.com/Maggi-Chen/ALPINE/blob/b59121d132f20e5056b76038b50dc136a91a756b/README.md) | `589f71da496385312063f5915ed6c85946e3207a130e08045d2caed274537e46` |
| `ALPINE/testdata/example_ref.config_trac.txt` | [`testdata/example_ref.config_trac.txt`](https://github.com/Maggi-Chen/ALPINE/blob/b59121d132f20e5056b76038b50dc136a91a756b/testdata/example_ref.config_trac.txt) | `d85eb51b650c9ddf70ca118fb6478ce8ff8eb0f55945e85eab6a9f8539af4fe1` |
| `ALPINE/testdata/example_output.test_sample_read_classification.txt` | [`testdata/example_output.test_sample_read_classification.txt`](https://github.com/Maggi-Chen/ALPINE/blob/b59121d132f20e5056b76038b50dc136a91a756b/testdata/example_output.test_sample_read_classification.txt) | `fcef5e371e73590cdec3ab765f4c6b1e45cdecd7b70843ff5f84ef17748261e2` |
| `ALPINE/testdata/example_output.readname_test_sample.txt` | [`testdata/example_output.readname_test_sample.txt`](https://github.com/Maggi-Chen/ALPINE/blob/b59121d132f20e5056b76038b50dc136a91a756b/testdata/example_output.readname_test_sample.txt) | `aeebf654c7c9288b4e87f6c064d50dc5ec8bd528c33841feb114f34618f2ddef` |
| `CRISPRLungo/README.md` | [`README.md`](https://github.com/pinellolab/CRISPRLungo/blob/e31ea36a3373c018cdee7b61ede8f571e4ecbf7f/README.md) | `fe15bc70ff943388adfbe3b0d1e80a8b556148c8b16f249a08a62b9cccf21452` |
| `CRISPRLungo/rust-BUILD.md` | [`rust/BUILD.md`](https://github.com/pinellolab/CRISPRLungo/blob/e31ea36a3373c018cdee7b61ede8f571e4ecbf7f/rust/BUILD.md) | `aee6979bde8b865b43b62ba9031a53497fcf4821a21fd1cf5865899e72a48014` |
| `CRISPRLungo/cutoff-finding-Readme.txt` | [`CRIPSRlungo_cutoff_finding/Readme.txt`](https://github.com/pinellolab/CRISPRLungo/blob/e31ea36a3373c018cdee7b61ede8f571e4ecbf7f/CRIPSRlungo_cutoff_finding/Readme.txt) | `bad6efbf08be6aa58d13a964d383e3e6b34e9a61f3265b58348983366b97de5c` |

## Refreshing

These copies are pinned to the commits in `configs/tools.tsv`. They only change when a tool is repinned.
To refetch after a repin, re-run the download with the new commit and update the table above:

```bash
curl -sS -o docs/upstream/ALPINE/README.md \
  https://raw.githubusercontent.com/Maggi-Chen/ALPINE/<commit>/README.md
sha256sum docs/upstream/ALPINE/README.md
```
