#!/bin/bash
###################################### dependencies
set -euo pipefail
cd "$(dirname "$0")/.."
###################################### constants
STEPS=(01_clone 02_envs 03_fetch 04_build_refs 05_alpine 06_lungo 07_summary)
MODE=local; YFLAGS=()
mkdir -p logs/{01_clone,02_envs,03_fetch,04_build_refs,05_alpine,06_lungo,07_summary}
for a in "$@"; do case "$a" in --sbatch) MODE=sbatch;; --yaml-in|--yaml-out) YFLAGS+=("$a");; esac; done
###################################### helpers
T0=$SECONDS
log() { echo "[SLURM-INFO] $*"; }
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
