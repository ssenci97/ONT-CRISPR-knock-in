#!/bin/bash
###################################### dependencies
set -euo pipefail
KV_ROOT="${KV_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export CONDA_BASE="$(conda info --base)"; source "$CONDA_BASE/etc/profile.d/conda.sh"
###################################### constants
export KV_ROOT TOOLS="$KV_ROOT/tools" DATA="$KV_ROOT/data" REFS="$KV_ROOT/refs" RESULTS="$KV_ROOT/results"
export PARAM_YAML="$KV_ROOT/configs/param_configs.yaml" MPLBACKEND=Agg QT_QPA_PLATFORM=offscreen
export THREADS="${SLURM_CPUS_PER_TASK:-${THREADS:-8}}" SEED=42
SAMPLES=(Mock_r1 NoDonor_r1 dsDNA_r1 ssDNA_r1 ssCTS_r1)
CONTROL=Mock_r1
KV_T0=$SECONDS; KV_MAXRSS=0; KV_ARGS=(); KV_YFLAGS=()
mkdir -p "$KV_ROOT"/logs/{00_clone,01_envs,20_fetch,21_build_refs,30_real,40_summary} "$DATA" "$REFS" "$RESULTS"
###################################### helpers
kv_log() { echo "[SLURM-INFO] $*"; }
kv_activate() { set +u; conda activate "$1"; set -u; }
kv_time() { local log="$1" rc=0 m tmp=0; shift; [ "$log" = - ] && { log=$(mktemp); tmp=1; }; /usr/bin/time -v -o "$log" "$@" || rc=$?; m=$(awk '/Maximum resident/{print $NF}' "$log" 2>/dev/null || true); [ -n "$m" ] && [ "$m" -gt "$KV_MAXRSS" ] && KV_MAXRSS=$m; [ $tmp = 1 ] && rm -f "${log:?}"; return $rc; }
kv_footer() { kv_log "$(date '+%F %T') | elapsed $(date -u -d @$((SECONDS-KV_T0)) +%H:%M:%S) | max RSS $(awk -v k="$KV_MAXRSS" 'BEGIN{printf "%.2f GB", k/1048576}')"; }
kv_samples() { if [ -n "${SLURM_ARRAY_TASK_ID:-}" ]; then echo "${SAMPLES[$((SLURM_ARRAY_TASK_ID-1))]}"; else printf '%s\n' "${SAMPLES[@]}"; fi; }
kv_design() { "$CONDA_BASE/bin/python3" -I -c "import json; d=json.load(open('$REFS/design.json')); print($1)"; }
###################################### yaml params
kv_args() {
  local yin=0 yout=0 a k kv=()
  for a in "$@"; do case "$a" in --yaml-in) yin=1; KV_YFLAGS+=("$a");; --yaml-out) yout=1; KV_YFLAGS+=("$a");; *) KV_ARGS+=("$a");; esac; done
  if [ $yin = 1 ]; then
    eval "$("$CONDA_BASE/bin/python3" -I - "$PARAM_YAML" "$NAME" "${PARAMS[@]}" <<'PY'
import os, shlex, sys, yaml
p, n, *keys = sys.argv[1:]
c = ((yaml.safe_load(open(p)) if os.path.exists(p) else None) or {}).get(n, {})
print("\n".join(f"{k}={shlex.quote(str(c[k]))}" for k in keys if k in c))
PY
)"; kv_log "params read from $PARAM_YAML [$NAME]"
  fi
  if [ $yout = 1 ]; then
    for k in "${PARAMS[@]}"; do kv+=("$k=${!k}"); done
    "$CONDA_BASE/bin/python3" -I - "$PARAM_YAML" "$NAME" "${kv[@]}" <<'PY'
import os, sys, yaml
p, n, *kv = sys.argv[1:]
c = (yaml.safe_load(open(p)) if os.path.exists(p) else None) or {}
c[n] = {k: yaml.safe_load(v) for k, v in (x.split("=", 1) for x in kv)}
yaml.safe_dump(c, open(p, "w"), sort_keys=False)
PY
    kv_log "params written to $PARAM_YAML [$NAME]"
  fi
  for k in "${PARAMS[@]}"; do kv_log "param $k=${!k}"; done
}
