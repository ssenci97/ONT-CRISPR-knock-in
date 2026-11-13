#!/bin/bash
###################################### dependencies
set -euo pipefail
KV_ROOT="${KV_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"; TOOLS="${TOOLS:-/opt/tools}"
###################################### container guard
if [ -z "${APPTAINER_CONTAINER:-}${SINGULARITY_CONTAINER:-}" ] && [ ! -d /.singularity.d ]; then echo "[SLURM-INFO] refusing to run outside the container image (run through python3 src/pipeline.py <analysis>)"; exit 1; fi
[ -d "$TOOLS/ALPINE" ] && [ -d "$TOOLS/CRISPRLungo" ] || { echo "[SLURM-INFO] $TOOLS lacks ALPINE/CRISPRLungo: wrong image"; exit 1; }
[ -n "${KV_OUT:-}" ] || { echo "[SLURM-INFO] KV_OUT (results/<analysis_name>) is not set: run through python3 src/pipeline.py <analysis> or the console"; exit 1; }
###################################### constants
export SEED=42
KV_T0=$SECONDS
###################################### helpers
kv_log() { echo "[SLURM-INFO] $*"; }
kv_meta() { local id="$1" step="$2"; shift 2; python3 -I "$KV_ROOT/src/sample_meta.py" "$id" "$step" "$@"; }
kv_design() { python3 -I -c "import json; d=json.load(open('$KV_OUT/refs/design.json')); print($1)"; }
kv_peak() { local f; for f in /sys/fs/cgroup/memory.peak /sys/fs/cgroup/memory/memory.max_usage_in_bytes; do [ -r "$f" ] && { awk '{printf "%.2f GB", $1/1073741824}' "$f"; return; }; done; echo "NA (see sacct)"; }
kv_footer() { kv_log "$(date '+%F %T') | elapsed $(date -u -d @$((SECONDS-KV_T0)) +%H:%M:%S) | max RSS $(kv_peak)"; }
kv_log "host $(hostname) | job ${SLURM_JOB_ID:-local} | image ${KV_IMAGE:-none}"
