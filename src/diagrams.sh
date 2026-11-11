#!/bin/bash
###################################### dependencies
set -euo pipefail
KV_ROOT="${KV_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
###################################### constants
SRC="$KV_ROOT/docs/diagrams"; OUT="$KV_ROOT/docs/img"; T0=$SECONDS
###################################### render
command -v dot >/dev/null || { echo "[SLURM-INFO] graphviz 'dot' not found"; exit 1; }
mkdir -p "$OUT"
for f in "$SRC"/*.dot; do dot -Tsvg "$f" -o "$OUT/$(basename "${f%.dot}").svg"; echo "[SLURM-INFO] rendered $(basename "$f")"; done
echo "[SLURM-INFO] $(date '+%F %T') | elapsed $(date -u -d @$((SECONDS-T0)) +%H:%M:%S) | max RSS 0.00 GB"
