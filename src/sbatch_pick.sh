#!/bin/bash
###################################### usage: sbatch <args>  (shim first on PATH; NODE_PICK=0 passes through)
SELF="$(realpath "$0")"
REAL=$(type -ap sbatch | while read -r p; do [ "$(realpath "$p")" != "${SELF}" ] && { echo "$p"; break; }; done)
[ -n "${REAL}" ] || { echo "[SLURM-INFO] Error: no real sbatch on PATH" >&2; exit 1; }
[ "${NODE_PICK:-1}" = "1" ] || exec "${REAL}" "$@"
source "$(dirname "${SELF}")/best_node.sh"
LOG="${KV_ROOT:-.}/results/${KV_ANALYSIS:-_}/logs/node_pick.log"
[ -n "${KV_ANALYSIS}" ] || LOG=/dev/null
mkdir -p "$(dirname "${LOG}")" 2>/dev/null
###################################### helpers
to_minutes() {
  awk -v t="$1" 'BEGIN{
    if (t ~ /^(infinite|UNLIMITED)$/) { print 1e9; exit }
    if (t ~ /^[0-9]+$/) { print t; exit }
    d = 0; if (t ~ /-/) { split(t, a, "-"); d = a[1]; t = a[2]; n = split(t, b, ":"); h = b[1]; mi = (n > 1) ? b[2] : 0; print d*1440 + h*60 + mi; exit }
    n = split(t, b, ":"); if (n == 3) print b[1]*60 + b[2]; else print b[1]
  }'
}
###################################### parse
ORIG=("$@"); ARGS=(); CPUS=1; MEM_MB=1024; TIME=60; RULE=""
while [ $# -gt 0 ]; do
  case "$1" in
    -p|--partition) shift ;;
    --partition=*) ;;
    -c|--cpus-per-task) CPUS="$2"; ARGS+=("$1" "$2"); shift ;;
    --cpus-per-task=*) CPUS="${1#*=}"; ARGS+=("$1") ;;
    --mem) MEM_MB="$2"; ARGS+=("$1" "$2"); shift ;;
    --mem=*) MEM_MB="${1#*=}"; ARGS+=("$1") ;;
    -t|--time) TIME="$2"; ARGS+=("$1" "$2"); shift ;;
    --time=*) TIME="${1#*=}"; ARGS+=("$1") ;;
    --comment) RULE="$2"; ARGS+=("$1" "$2"); shift ;;
    *) ARGS+=("$1") ;;
  esac
  shift
done
MEM_GB=$(awk -v m="${MEM_MB}" 'BEGIN{v = m + 0; if (m ~ /[Gg]$/) v = v * 1024; else if (m ~ /[Tt]$/) v = v * 1048576; v = int((v + 1023) / 1024); print (v < 1) ? 1 : v}')
###################################### node
NEED=$(to_minutes "${TIME}")
PARTS=$(sinfo -h -o "%P %l" | while read -r p l; do p="${p%\*}"; [[ "${p^^}" =~ ^(DGX|GPU) ]] && continue; [ "$(to_minutes "${l}")" -ge "${NEED}" ] && echo "${p}"; done | sort -u | paste -sd, -)
read -r NODE BEST_PART < <(get_best_node "${CPUS}" "${MEM_GB}" "${PARTS}" 2>>"${LOG}")
###################################### submit
if [ -n "${NODE}" ]; then
  echo "[SLURM-INFO] $(date '+%F %T') ${RULE} cpus=${CPUS} mem=${MEM_GB}G time=${NEED}m -> -p ${BEST_PART} -w ${NODE}" >> "${LOG}"
  exec "${REAL}" -p "${BEST_PART}" -w "${NODE}" "${ARGS[@]}"
fi
echo "[SLURM-INFO] $(date '+%F %T') ${RULE} cpus=${CPUS} mem=${MEM_GB}G time=${NEED}m -> no node fits, original partition kept" >> "${LOG}"
exec "${REAL}" "${ORIG[@]}"
