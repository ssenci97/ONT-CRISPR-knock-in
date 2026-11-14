#!/bin/bash
###################################### dependencies
set -euo pipefail
command -v singularity >/dev/null || module load singularity
###################################### parameters
script="$1"; shift
cd "$KV_ROOT"
KV_OUT="$KV_ROOT/results/$KV_ANALYSIS"
T_START="$(date '+%F %T')"; S0=$SECONDS
###################################### run
prefix="set -euo pipefail; export PATH=/opt/conda/envs/kv/bin:\$PATH TOOLS=/opt/tools"
prefix+=" KV_ROOT=$(printf %q "$KV_ROOT") KV_OUT=$(printf %q "$KV_OUT") KV_IMAGE=$(printf %q "$KV_IMAGE") SLURM_JOB_ID=$(printf %q "${SLURM_JOB_ID:-local}")"
prefix+='; export HOME="$KV_ROOT" PYTHONNOUSERSITE=1 MPLBACKEND=Agg QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=${TMPDIR:-/tmp}/mpl; cd "$KV_ROOT"; exec bash "$0" "$@"'
echo "[SLURM-INFO] host $(hostname) | job ${SLURM_JOB_ID:-local} | image $KV_IMAGE | $script $*"
rc=0; singularity exec --cleanenv --bind "$KV_ROOT${KV_BINDS:+,$KV_BINDS}" "$KV_IMAGE" bash -c "$prefix" "$KV_ROOT/$script" "$@" || rc=$?
###################################### verify outputs
if [ "$rc" -eq 0 ]; then
  IFS=: read -ra outs <<< "${KV_OUTPUTS:-}"
  for f in "${outs[@]}"; do
    [ -s "$f" ] && { [[ "$f" != *.gz ]] || gzip -t "$f"; } 2>/dev/null || { echo "[SLURM-INFO] output check failed: $f"; rc=1; break; }
  done
  [ "$rc" -eq 0 ] && echo "[SLURM-INFO] outputs verified: ${#outs[@]}"
fi
###################################### performance metadata
if [ -n "${KV_META_TARGET:-}" ]; then
  KV_OUT="$KV_OUT" python3 -I "$KV_ROOT/src/sample_meta.py" --perf "$KV_META_TARGET" "$KV_META_STEP" \
    elapsed_s=$((SECONDS-S0)) exit="$rc" started="$T_START" ended="$(date '+%F %T')" \
    && echo "[SLURM-INFO] perf metadata: meta/$KV_META_TARGET.json steps.$KV_META_STEP.perf" \
    || echo "[SLURM-INFO] !! perf metadata not written"
fi
exit "$rc"
