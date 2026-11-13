#!/bin/bash
###################################### usage: node_pick.sh <cpus> <mem_mb> <minutes>  -> stdout "<node> <partition>" (empty if none fits), choice on stderr
source "$(dirname "$(realpath "$0")")/best_node.sh"
###################################### parameters
CPUS="${1:-1}"; MEM_MB="${2:-1024}"; NEED="${3:-60}"
MEM_GB=$(( (MEM_MB + 1023) / 1024 ))
###################################### helpers
to_minutes() {
  awk -v t="$1" 'BEGIN{
    if (t ~ /^(infinite|UNLIMITED)$/) { print 1e9; exit }
    if (t ~ /^[0-9]+$/) { print t; exit }
    d = 0; if (t ~ /-/) { split(t, a, "-"); d = a[1]; t = a[2]; n = split(t, b, ":"); h = b[1]; mi = (n > 1) ? b[2] : 0; print d*1440 + h*60 + mi; exit }
    n = split(t, b, ":"); if (n == 3) print b[1]*60 + b[2]; else print b[1]
  }'
}
###################################### node
PARTS=$(sinfo -h -o "%P %l" | while read -r p l; do p="${p%\*}"; [[ "${p^^}" =~ ^(DGX|GPU|H100|UPDATE) ]] && continue; [ "$(to_minutes "${l}")" -ge "${NEED}" ] && echo "${p}"; done | sort -u | paste -sd, -)
[ -n "${PARTS}" ] || { echo "[BASH-INFO] no CPU partition allows ${NEED} min" >&2; exit 0; }
get_best_node "${CPUS}" "${MEM_GB}" "${PARTS}"
