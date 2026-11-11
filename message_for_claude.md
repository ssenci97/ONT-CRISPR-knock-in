# message_for_claude

Handoff note written 2026-11-11. Working tree is **uncommitted**: `git status --short` shows ~25 entries.
Nothing has been pushed, no image has been built, no pipeline step has been re-run.

## Objective

Make KNOCKIN-VAL lightweight, completely reproducible, and usable by wet-lab scientists on the **Orfeo**
cluster (Area Science Park), in the spirit of the discontinued Nastro pipeline but without its interfaces.
Constraints the user stated: **no sudo** (rootless podman only), **never work directly on Orfeo** — the user
builds and tests there, Claude writes the scripts — and **all tool licences visible in the repo root**.

## Done and verified

1. **seqkit warning** in `03_fetch.sh` — fixed with `-g -G "-"`; output confirmed byte-identical.
2. **ALPINE vs the other two tools** — verified from source at `b59121d`, written up in
   `docs/manuals/ALPINE.md`. Two gates: a 0.95 insert-length cutoff on nanopore, and a hardcoded
   `minimap2 -ax map-hifi` for the homology-arm check (`utils/data_utils.py:89`) that ignores
   `data_type: nanopore`. A new shared `ki_min_insert_frac` (0.80) now drives both ALPINE's
   `truncated_cutoff` and CRISPRLungo's insert span.
3. **Console** — `gui/submit.{html,css,js}` + `src/gui_serve.py` (stdlib, localhost), three tabs:
   Samples (writes `configs/samples.tsv`, `configs/samples/<id>.json`, syncs `#SBATCH --array=1-N`),
   Run (`POST /api/run` launches `run_all.sh [--sbatch]` detached; `/api/status` reports queue, per-step
   log progress and the run log; `/api/stop` kills the process group), Results (`/api/results` returns the
   KI% matrix, `summary.tsv` rows and every `results/meta/<id>.json`). All endpoints tested against a stub
   `run_all.sh`, including the concurrency guard, stop and relaunch. Must run on the host, not inside the
   container, because it needs `sbatch`; it auto-detects `containers/ont-knockin-val.sif`.
4. **Run metadata** — `src/sample_meta.py` is the single writer of `results/meta/<sample_id>.json`
   (submitted block, per-step params, read counts, SLURM ids, pipeline commit, image, tool commits).
5. **Diagrams** — five graphviz sources in `docs/diagrams/`, rendered to `docs/img/` by `src/diagrams.sh`,
   embedded in the README.
6. **Containers** — `containers/Dockerfile.base` (publishable: conda env, cwltool, minimap2 2.16, ALPINE)
   and `containers/Dockerfile` (adds CRISPRLungo + CRISPResso2, never pushed), `containers/build.sh`
   (podman; targets base/full/sif/lock/push). `slurms/analysis_env.sh` re-executes each step inside the
   image when `KV_SIF` or `KV_IMAGE` is set; verified with stub engines including the sbatch spool case.
7. **Licences** — `LICENSES.md` at root + `LICENSES/`. CRISPResso2's EULA forbids redistribution, which is
   why the image is split in two. Do not collapse it back into one pushable image.
8. **Pinning** — tool commits (`configs/tools.tsv`, full SHAs, enforced), base image digest
   (`containers/pins.env`), conda lock (`containers/kv.lock.txt`, via `build.sh lock`), reference downloads
   (`configs/refs.sha256`, verified by `04_build_refs`).
9. **Failure handling** — steps 05/06/07 now preflight their binary and `exit $rc`, instead of exiting 0
   with every sample silently empty.
10. **Docs** — README, `Manual.md`, `docs/manuals/{ALPINE,Inputs}.md` all updated. `.gitignore` and
    `.containerignore` added (there was no `.gitignore` at all before).

## Next, in order

1. **User builds on Orfeo**: `containers/build.sh all` (KV_OWNER only needed to push; it defaults to
   `local`). For a reproducible rebuild: `base`, then `lock`, then `base` again, then `full`, then `sif`.
   Expect the first solve to be slow. Nothing here has ever been built — treat the first build as
   debugging, not verification.
2. **Commit the generated pins**: `containers/kv.lock.txt` and `configs/refs.sha256`.
3. **`tools/ALPINE`, `tools/CRISPRLungo`, `tools/CRISPResso2` are tracked as gitlinks with no
   `.gitmodules`.** A fresh clone gives three empty directories. Needs
   `git rm --cached tools/ALPINE tools/CRISPRLungo tools/CRISPResso2` — left to the user, it rewrites the index.
4. **Re-run the pipeline** once containerized and compare `results/summary_matrix.tsv` against the
   2026-11-09 run: ALPINE 0.0/0.0/1.31/0.0/0.35, CRISPRLungo 0.0/0.0/4.23/0.85/7.12,
   CRISPResso2 0.01/0.03/4.62/1.28/7.86 (Mock/NoDonor/dsDNA/ssDNA/ssCTS). ALPINE's numbers should rise,
   because `truncated_cutoff` moved from 0.95 to 0.80. If they do not, suspect the `map-hifi` bug.
5. **Open question for the user**: whether to patch ALPINE's `map-hifi` line. It would fix ONT arm checking
   but means modifying a tool pinned by commit. Not done; deliberately.

## The user's acceptance criteria (stated 2026-11-11, second session)

1. Build the image with a script → `containers/build.sh all`.
2. Run it from the GUI, with a button for a preconfigured default run → Run tab, "Run default pipeline".
3. See results and per-sample metadata at the end → Results tab.

All three are implemented and tested locally; none has been exercised on Orfeo with a real image.

## Things not to redo

- Do not re-verify the seqkit fix, the console endpoints, or the re-exec wiring; all were tested.
- Do not add a compose service for the GUI — the user declined.
- Do not run the console inside the container; it would lose `sbatch`.
- Do not push the full image. `build.sh push-full` refuses on purpose.
