#!/bin/bash
#SBATCH --job-name=kv_clone
#SBATCH --partition=GENOA
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=logs/00_clone/clone_%j.log
#SBATCH --open-mode=append
###################################### dependencies
KV_ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"; source "$KV_ROOT/slurms/analysis_env.sh"
###################################### parameters
NAME=00_clone
TOOLS_TSV=configs/tools.tsv
PARAMS=(TOOLS_TSV); kv_args "$@"
###################################### clone
mkdir -p "$TOOLS"
while IFS=$'\t' read -r name repo commit _; do
  [ -d "$TOOLS/$name/.git" ] || git clone -q "$repo" "$TOOLS/$name"
  git -C "$TOOLS/$name" fetch -q origin; git -C "$TOOLS/$name" checkout -q -f "$commit"
  kv_log "$name @ $(git -C "$TOOLS/$name" rev-parse --short HEAD)"
done < <(tail -n +2 "$KV_ROOT/$TOOLS_TSV")
kv_footer
