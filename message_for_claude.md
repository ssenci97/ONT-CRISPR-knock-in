# message_for_claude

Handoff note written 2026-11-11. Working tree is **uncommitted**: `git status --short` shows ~25 entries.
Nothing has been pushed, no image has been built, no pipeline step has been re-run.

## Objective

Make KNOCKIN-VAL lightweight, completely reproducible, and usable by wet-lab scientists on the **Orfeo**
cluster (Area Science Park), in the spirit of the discontinued Nastro pipeline but without its interfaces.
Constraints the user stated: **never work directly on Orfeo** — Claude writes the scripts, the user runs
them there — and **all tool licences visible in the repo root**.

**2026-11-11, third session: the build strategy changed.** Rootless podman on Orfeo failed three times
(no `/run/user/$UID`, no systemd user session, and no `/etc/subuid` allocation for the account). Orfeo
admins then said to **build locally with Docker, push to a registry, and pull on Orfeo with Singularity**.
That is now the supported path and the README documents it. `build.sh` auto-detects docker and falls back
to podman; the podman workarounds are kept but are no longer the main route.

**2026-11-11, user decision: CRISPResso2 is removed from the repo.** Its MGH EULA forbids copying the
software "in any form", so it could not ship in the image; rather than architect around a tool that cannot
travel with the pipeline, it was dropped. Consequences, all applied:
- `slurms/07_crispresso.sh`, `envs/kv_crispresso.yml`, `docs/manuals/CRISPResso2.md` and
  `LICENSES/CRISPResso2.LICENSE.txt` deleted; `crispresso2` removed from `envs/kv.yml` and the
  `CRISPResso2` row from `configs/tools.tsv`.
- `08_summary` renamed to **`07_summary`** so steps stay contiguous 01..07. Updated in `run_all.sh`,
  `analysis_env.sh`, `gui_serve.py`, `gui/submit.js`, `param_configs.yaml` and all docs.
- `src/summarize.py` TOOLS is now `{ALPINE, CRISPRLungo}`; `crispresso_version()` gone from
  `src/sample_meta.py`.
- **The two-image split is gone.** It existed only for the EULA. There is now one `containers/Dockerfile`
  producing one **public** image, `ghcr.io/<owner>/ont-knockin-val:<tag>`. `Dockerfile.base` deleted.
  `build.sh` targets are now `build lock login push ship orfeo` — no push-full, no private-package gate,
  no scp route. Orfeo pulls with `singularity pull` and **needs no credentials**.
- `LICENSES.md` records why CRISPResso2 went and what it cost (it was the cross-check that validated
  CRISPRLungo, and it was ~86% of the runtime). Do not re-add it without the user asking.

Two further findings from the first local Docker build:
- **`archive.ubuntu.com` does not resolve on the institute network** (nor does `security.ubuntu.com`;
  `deb.debian.org`, `conda.anaconda.org`, `github.com` and `ghcr.io` all do). apt can never work here.
  `Dockerfile.base` no longer uses apt at all: `curl`, `unzip`, `time` and `util-linux` now come from
  conda-forge via `envs/kv.yml`, so they land in `containers/kv.lock.txt` like everything else. This is
  strictly better for reproducibility and also removes the old rootless-podman apt-sandbox workaround.
- `kv_time` in `analysis_env.sh` no longer hardcodes `/usr/bin/time`; it resolves `type -P time` once
  (after the env is activated) and degrades to running the command untimed if GNU time is absent.

**Claude has no GitHub credentials and must never supply, invent or reuse any.** Pushing requires the user
to create a PAT and export `KV_GITHUB_TOKEN`; `build.sh login` pipes it via stdin and never echoes it.

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
   -- superseded, see the 2026-11-11 decision above: one `containers/Dockerfile`, one public image. `slurms/analysis_env.sh` re-executes each step inside the
   image when `KV_SIF` or `KV_IMAGE` is set; verified with stub engines including the sbatch spool case.
7. **Licences** — `LICENSES.md` at root + `LICENSES/`. Two tools, both redistributable, one public image.
8. **Pinning** — tool commits (`configs/tools.tsv`, full SHAs, enforced), base image digest
   (`containers/pins.env`), conda lock (`containers/kv.lock.txt`, via `build.sh lock`), reference downloads
   (`configs/refs.sha256`, verified by `04_build_refs`).
9. **Failure handling** — steps 05/06/07 now preflight their binary and `exit $rc`, instead of exiting 0
   with every sample silently empty.
10. **Docs** — README, `Manual.md`, `docs/manuals/{ALPINE,Inputs}.md` all updated. `.gitignore` and
    `.containerignore` added (there was no `.gitignore` at all before).

## Next, in order

1. **Build locally with Docker**: `containers/build.sh build`. Then `lock` and `build` again for a solver-free rebuild. `KV_OWNER` defaults to the owner of `origin` (`ssenci97`).
2. **Push**: `KV_GITHUB_TOKEN=<PAT write:packages> containers/build.sh ship`. One public package.
   Claude has no GitHub credentials and must never supply any.
3. **Pull on Orfeo**: `containers/build.sh orfeo` prints the exact `singularity pull` by digest.
4. **Commit the generated pins**: `containers/kv.lock.txt`, `containers/images.env`, `configs/refs.sha256`.
5. **`tools/ALPINE`, `tools/CRISPRLungo` are tracked as gitlinks with no `.gitmodules`.** A fresh clone
   gives empty directories. Needs `git rm --cached tools/ALPINE tools/CRISPRLungo` (and `tools/CRISPResso2`,
   now obsolete) — left to the user, it rewrites the index.
6. **Re-run the pipeline** once containerized and compare `results/summary_matrix.tsv` against the
   2026-11-09 run: ALPINE 0.0/0.0/1.31/0.0/0.35, CRISPRLungo 0.0/0.0/4.23/0.85/7.12,
   (Mock/NoDonor/dsDNA/ssDNA/ssCTS). ALPINE's numbers should rise,
   because `truncated_cutoff` moved from 0.95 to 0.80. If they do not, suspect the `map-hifi` bug.
7. **Open question for the user**: whether to patch ALPINE's `map-hifi` line. It would fix ONT arm checking
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
- Do not re-add CRISPResso2. The user removed it deliberately on 2026-11-11.
- Do not commit or echo a GitHub token. `build.sh login` reads `KV_GITHUB_TOKEN` and pipes it to stdin.
