#!/bin/bash
###################################### dependencies
set -euo pipefail
cd "$(dirname "$0")/.."
###################################### constants
STEPS=(01_clone 02_envs 03_fetch 04_build_refs 05_alpine 06_lungo 07_summary)
MODE=local; YFLAGS=()
mkdir -p logs/{01_clone,02_envs,03_fetch,04_build_refs,05_alpine,06_lungo,07_summary}
for a in "$@"; do case "$a" in --sbatch) MODE=sbatch;; --yaml-in|--yaml-out) YFLAGS+=("$a");; esac; done
###################################### preflight
T0=$SECONDS
log() { echo "[SLURM-INFO] $*"; }
if [ -n "${KV_SIF:-}" ]; then
  [ -s "$KV_SIF" ] || { log "KV_SIF points at a missing or empty file: $KV_SIF"; log "run 'containers/build.sh pull' from the repo root first, or unset KV_SIF to run natively"; exit 1; }
  command -v singularity >/dev/null || command -v apptainer >/dev/null || { log "KV_SIF is set but neither singularity nor apptainer is on PATH"; exit 1; }
  log "image $KV_SIF ($(du -h "$KV_SIF" | cut -f1))"
elif [ -n "${KV_IMAGE:-}" ]; then
  log "image $KV_IMAGE"
else
  log "no KV_SIF or KV_IMAGE: running natively, 01_clone and 02_envs will need network and will build conda envs"
fi
[ -s configs/samples.tsv ] || { log "configs/samples.tsv is missing or empty"; exit 1; }
n_samples=$(awk -F'\t' 'NR>1 && $1!=""' configs/samples.tsv | wc -l)
for s in 03_fetch 05_alpine 06_lungo; do
  a=$(sed -n 's/^#SBATCH --array=1-\([0-9]*\).*/\1/p' "slurms/$s.sh")
  [ -n "$a" ] && [ "$a" != "$n_samples" ] && log "!! slurms/$s.sh has --array=1-$a but configs/samples.tsv has $n_samples samples"
done
###################################### helpers
sb() { local id; id=$(sbatch --parsable "$@" "${YFLAGS[@]}"); log "submitted $* -> $id" >&2; echo "$id"; }
###################################### run
if [ "$MODE" = sbatch ]; then
  c=$(sb slurms/01_clone.sh); e=$(sb -d afterok:$c slurms/02_envs.sh); f=$(sb -d afterok:$e slurms/03_fetch.sh); r=$(sb -d afterok:$f slurms/04_build_refs.sh)
  d=""; for s in 05_alpine 06_lungo; do d+=":$(sb -d afterok:$r slurms/$s.sh)"; done
  sb -d afterany$d slurms/07_summary.sh > /dev/null; log "all jobs submitted; follow with: squeue -u $USER ; logs in logs/<step>/"
else
  for s in "${STEPS[@]}"; do l="logs/$s/${s}_local.log"; log "$(date +%T) $s -> $l"; bash "slurms/$s.sh" "${YFLAGS[@]}" > "$l" 2>&1 && log "ok" || log "FAILED (see $l)"; done
  log "KI % matrix:"; sed 's/^/[SLURM-INFO]   /' results/summary_matrix.tsv 2>/dev/null || true
fi
log "$(date '+%F %T') | elapsed $(date -u -d @$((SECONDS-T0)) +%H:%M:%S) | max RSS $(grep -ho 'max RSS [0-9.]* GB' logs/*/*_local.log 2>/dev/null | awk '{if($3>m)m=$3} END{printf "%.2f GB", m}')"
