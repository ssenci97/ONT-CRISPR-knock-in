#!/bin/bash
###################################### dependencies
set -euo pipefail
KV_ROOT="${KV_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
###################################### container
if [ -z "${KV_INSIDE:-}" ] && { [ -n "${KV_SIF:-}" ] || [ -n "${KV_IMAGE:-}" ]; }; then
  IFS=',' read -r -a kv_paths <<< "${KV_BIND:-$KV_ROOT}"
  kv_bound() { local p; for p in "${kv_paths[@]}"; do case "$1" in "$p"|"$p"/*) return 0;; esac; done; return 1; }
  kv_bound "$PWD" || cd "$KV_ROOT"
  kv_script="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
  if ! kv_bound "$kv_script"; then
    mkdir -p "$KV_ROOT/logs"
    kv_script="$KV_ROOT/logs/.rexec.${SLURM_JOB_ID:-$$}.${SLURM_ARRAY_TASK_ID:-0}.sh"
    cp "$(cd "$(dirname "$0")" && pwd)/$(basename "$0")" "$kv_script"
  fi
  kv_pass=(KV_INSIDE=1 TOOLS=/opt/tools HOME=/tmp PYTHONNOUSERSITE=1 MPLCONFIGDIR=/tmp/mpl)
  for v in KV_SIF KV_IMAGE TMPDIR SLURM_JOB_ID SLURM_ARRAY_TASK_ID SLURM_CPUS_PER_TASK SLURM_MEM_PER_NODE; do
    if [ -n "${!v:-}" ]; then kv_pass+=("$v=${!v}"); fi
  done
  if [ -n "${KV_SIF:-}" ]; then
    kv_app="${KV_APPTAINER:-$(command -v apptainer || command -v singularity || true)}"
    [ -n "$kv_app" ] || { echo "[SLURM-INFO] neither apptainer nor singularity is on PATH"; exit 1; }
    kv_cmd=("$kv_app" exec --cleanenv --no-home --pwd "$PWD")
    for b in "${kv_paths[@]}"; do kv_cmd+=(-B "$b"); done
    for e in "${kv_pass[@]}"; do kv_cmd+=(--env "$e"); done
    exec "${kv_cmd[@]}" "$KV_SIF" bash "$kv_script" "$@"
  fi
  kv_eng="${KV_ENGINE:-}"
  if [ -z "$kv_eng" ]; then
    if command -v docker >/dev/null && docker info >/dev/null 2>&1; then kv_eng=docker; else kv_eng=podman; fi
  fi
  kv_cmd=("$kv_eng" run --rm -w "$PWD")
  if [ "$kv_eng" = podman ]; then
    if [ ! -d "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" ]; then
      export XDG_RUNTIME_DIR="${TMPDIR:-/tmp}/podman-$(id -u)"; mkdir -p -m 700 "$XDG_RUNTIME_DIR"
    fi
    kv_cmd=("$kv_eng" run --rm --userns=keep-id --cgroup-manager=cgroupfs --events-backend=file -w "$PWD")
  else
    kv_cmd+=(--user "$(id -u):$(id -g)")
  fi
  for b in "${kv_paths[@]}"; do kv_cmd+=(-v "$b:$b"); done
  for e in "${kv_pass[@]}"; do kv_cmd+=(-e "$e"); done
  exec "${kv_cmd[@]}" "$KV_IMAGE" bash "$kv_script" "$@"
fi
###################################### conda
export CONDA_BASE="$(conda info --base)"; source "$CONDA_BASE/etc/profile.d/conda.sh"
###################################### constants
export KV_ROOT TOOLS="${TOOLS:-$KV_ROOT/tools}" DATA="$KV_ROOT/data" REFS="$KV_ROOT/refs" RESULTS="$KV_ROOT/results"
export PARAM_YAML="$KV_ROOT/configs/param_configs.yaml" MPLBACKEND=Agg QT_QPA_PLATFORM=offscreen
export SEED=42 SAMPLES_TSV="$KV_ROOT/configs/samples.tsv"
threads="${SLURM_CPUS_PER_TASK:-${threads:-8}}"; mem_mb="${SLURM_MEM_PER_NODE:-${mem_mb:-6000}}"
wt_fasta="$REFS/TRAC_WT.fa"; ki_fasta="$REFS/TRAC_KI.fa"; insert_fasta="$REFS/CAR_insert.fa"
ki_min_insert_frac=0.8
KV_PY="$CONDA_BASE/bin/python3"; [ -x "$CONDA_BASE/envs/kv/bin/python3" ] && KV_PY="$CONDA_BASE/envs/kv/bin/python3"
KV_T0=$SECONDS; KV_MAXRSS=0; KV_ARGS=(); KV_YFLAGS=()
mkdir -p "$KV_ROOT"/logs/{01_clone,02_envs,03_fetch,04_build_refs,05_alpine,06_lungo,07_summary} "$DATA" "$REFS" "$RESULTS" "$RESULTS/meta" "$KV_ROOT/configs/samples"
###################################### helpers
kv_log() { echo "[SLURM-INFO] $*"; }
kv_activate() { set +u; conda activate "$1"; set -u; }
[ -x "$CONDA_BASE/envs/kv/bin/python3" ] && kv_activate kv
KV_TIME="$(type -P time 2>/dev/null || true)"; [ -x "$KV_TIME" ] || KV_TIME=/usr/bin/time
kv_time() { local log="$1" rc=0 m tmp=0; shift; [ "$log" = - ] && { log=$(mktemp); tmp=1; };
  if [ -x "$KV_TIME" ]; then "$KV_TIME" -v -o "$log" "$@" || rc=$?; else : > "$log"; "$@" || rc=$?; fi; m=$(awk '/Maximum resident/{print $NF}' "$log" 2>/dev/null || true); [ -n "$m" ] && [ "$m" -gt "$KV_MAXRSS" ] && KV_MAXRSS=$m; [ $tmp = 1 ] && rm -f "${log:?}"; return $rc; }
kv_footer() { kv_log "$(date '+%F %T') | elapsed $(date -u -d @$((SECONDS-KV_T0)) +%H:%M:%S) | max RSS $(awk -v k="$KV_MAXRSS" 'BEGIN{printf "%.2f GB", k/1048576}')"; }
kv_ids() { awk -F'\t' 'NR>1 && $1!=""{print $1}' "$SAMPLES_TSV"; }
kv_samples() { if [ -n "${SLURM_ARRAY_TASK_ID:-}" ]; then kv_ids | sed -n "${SLURM_ARRAY_TASK_ID}p"; else kv_ids; fi; }
kv_field() { awk -F'\t' -v id="$1" -v c="$2" 'NR==1{for(i=1;i<=NF;i++)if($i==c)n=i} NR>1&&$1==id{print $n}' "$SAMPLES_TSV"; }
kv_controls() { awk -F'\t' 'NR==1{for(i=1;i<=NF;i++)if($i=="control")n=i} NR>1&&$n==1{print $1}' "$SAMPLES_TSV"; }
kv_control() { local c; mapfile -t c < <(kv_controls); [ ${#c[@]} -gt 1 ] && kv_log "!! ${#c[@]} control samples in $SAMPLES_TSV (${c[*]}); using ${c[0]}" >&2; printf '%s' "${c[0]:-}"; }
kv_submitted() { "$KV_PY" -I -c "import json, os, sys; p = '$KV_ROOT/configs/samples/%s.json' % sys.argv[1]; print(json.load(open(p)).get(sys.argv[2], '') if os.path.exists(p) else '')" "$1" "$2"; }
kv_meta() { local id="$1" step="$2"; shift 2; "$KV_PY" -I "$KV_ROOT/src/sample_meta.py" "$id" "$step" "$@"; }
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
###################################### shared params
kv_read shared ki_min_insert_frac
