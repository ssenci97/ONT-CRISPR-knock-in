#!/bin/bash
#SBATCH --job-name=kv_summary
#SBATCH --partition=GENOA
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=logs/08_summary/summary_%j.log
#SBATCH --open-mode=append
###################################### dependencies
KV_ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"; source "$KV_ROOT/slurms/analysis_env.sh"
###################################### parameters
NAME=08_summary
PARAMS=(); kv_args "$@"
###################################### summary
kv_activate kv_alpine; kv_time - python3 "$KV_ROOT/src/summarize.py" "${KV_YFLAGS[@]}"
kv_footer
