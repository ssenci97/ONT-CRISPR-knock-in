#!/bin/bash
#SBATCH --job-name=kv_clone
#SBATCH --partition=GENOA
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=logs/01_clone/clone_%j.log
#SBATCH --open-mode=append
###################################### dependencies
KV_ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"; source "$KV_ROOT/slurms/analysis_env.sh"
###################################### parameters
NAME=01_clone
tools_tsv=configs/tools.tsv
PARAMS=(tools_tsv); kv_args "$@"
[ -n "${KV_INSIDE:-}" ] && { kv_log "tools come from the image"; kv_footer; exit 0; }
###################################### clone
mkdir -p "$TOOLS"
while IFS=$'\t' read -r name repo commit _; do
  [[ "$commit" =~ ^[0-9a-f]{40}$ ]] || { kv_log "$name is not pinned to a full commit sha in $tools_tsv: '$commit'"; exit 1; }
  [ -d "$TOOLS/$name/.git" ] || git clone -q "$repo" "$TOOLS/$name"
  git -C "$TOOLS/$name" fetch -q origin; git -C "$TOOLS/$name" checkout -q -f "$commit"
  [ "$(git -C "$TOOLS/$name" rev-parse HEAD)" = "$commit" ] || { kv_log "$name checkout does not match $commit"; exit 1; }
  kv_log "$name @ $(git -C "$TOOLS/$name" rev-parse --short HEAD)"
done < <(tail -n +2 "$KV_ROOT/$tools_tsv")
kv_footer
