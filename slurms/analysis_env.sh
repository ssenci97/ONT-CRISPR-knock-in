#!/bin/bash
###################################### dependencies
set -euo pipefail
KV_ROOT="${KV_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export CONDA_BASE="$(conda info --base)"; source "$CONDA_BASE/etc/profile.d/conda.sh"
###################################### constants
export KV_ROOT TOOLS="$KV_ROOT/tools" DATA="$KV_ROOT/data" REFS="$KV_ROOT/refs" RESULTS="$KV_ROOT/results"
export PARAM_YAML="$KV_ROOT/configs/param_configs.yaml" MPLBACKEND=Agg QT_QPA_PLATFORM=offscreen
export SEED=42 SAMPLES_TSV="$KV_ROOT/configs/samples.tsv"
threads="${SLURM_CPUS_PER_TASK:-${threads:-8}}"; mem_mb="${SLURM_MEM_PER_NODE:-${mem_mb:-6000}}"
wt_fasta="$REFS/TRAC_WT.fa"; ki_fasta="$REFS/TRAC_KI.fa"; insert_fasta="$REFS/CAR_insert.fa"
KV_PY="$CONDA_BASE/bin/python3"; [ -x "$CONDA_BASE/envs/kv/bin/python3" ] && KV_PY="$CONDA_BASE/envs/kv/bin/python3"
KV_T0=$SECONDS; KV_MAXRSS=0; KV_ARGS=(); KV_YFLAGS=()
mkdir -p "$KV_ROOT"/logs/{01_clone,02_envs,03_fetch,04_build_refs,05_alpine,06_lungo,07_crispresso,08_summary} "$DATA" "$REFS" "$RESULTS"
###################################### helpers
kv_log() { echo "[SLURM-INFO] $*"; }
kv_activate() { set +u; conda activate "$1"; set -u; }
[ -x "$CONDA_BASE/envs/kv/bin/python3" ] && kv_activate kv
kv_time() { local log="$1" rc=0 m tmp=0; shift; [ "$log" = - ] && { log=$(mktemp); tmp=1; }; /usr/bin/time -v -o "$log" "$@" || rc=$?; m=$(awk '/Maximum resident/{print $NF}' "$log" 2>/dev/null || true); [ -n "$m" ] && [ "$m" -gt "$KV_MAXRSS" ] && KV_MAXRSS=$m; [ $tmp = 1 ] && rm -f "${log:?}"; return $rc; }
kv_footer() { kv_log "$(date '+%F %T') | elapsed $(date -u -d @$((SECONDS-KV_T0)) +%H:%M:%S) | max RSS $(awk -v k="$KV_MAXRSS" 'BEGIN{printf "%.2f GB", k/1048576}')"; }
kv_ids() { awk -F'\t' 'NR>1 && $1!=""{print $1}' "$SAMPLES_TSV"; }
kv_samples() { if [ -n "${SLURM_ARRAY_TASK_ID:-}" ]; then kv_ids | sed -n "${SLURM_ARRAY_TASK_ID}p"; else kv_ids; fi; }
kv_field() { awk -F'\t' -v id="$1" -v c="$2" 'NR==1{for(i=1;i<=NF;i++)if($i==c)n=i} NR>1&&$1==id{print $n}' "$SAMPLES_TSV"; }
kv_control() { awk -F'\t' 'NR==1{for(i=1;i<=NF;i++)if($i=="control")n=i} NR>1&&$n==1{print $1}' "$SAMPLES_TSV"; }
kv_design() { "$KV_PY" -I -c "import json; d=json.load(open('$REFS/design.json')); print($1)"; }
###################################### yaml params
kv_read() {
  local n="$1"; shift
  eval "$("$KV_PY" -I - "$PARAM_YAML" "$n" "$@" <<'PY'
import os, shlex, sys, yaml
p, n, *keys = sys.argv[1:]
c = ((yaml.safe_load(open(p)) if os.path.exists(p) else None) or {}).get(n, {})
print("\n".join(f"{k}={shlex.quote(str(c[k]))}" for k in keys if k in c))
PY
)"
}
kv_args() {
  local a k kv=()
  KV_YIN=0; KV_YOUT=0
  for a in "$@"; do case "$a" in --yaml-in) KV_YIN=1; KV_YFLAGS+=("$a");; --yaml-out) KV_YOUT=1; KV_YFLAGS+=("$a");; *) KV_ARGS+=("$a");; esac; done
  if [ $KV_YIN = 1 ]; then kv_read "$NAME" "${PARAMS[@]}"; kv_log "params read from $PARAM_YAML [$NAME]"; fi
  if [ $KV_YOUT = 1 ]; then
    for k in "${PARAMS[@]}"; do kv+=("$k=${!k}"); done
    "$KV_PY" -I - "$PARAM_YAML" "$NAME" "${kv[@]}" <<'PY'
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
