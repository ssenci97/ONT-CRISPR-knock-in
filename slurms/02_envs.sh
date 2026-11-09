#!/bin/bash
#SBATCH --job-name=kv_envs
#SBATCH --partition=GENOA
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --output=logs/02_envs/envs_%j.log
#SBATCH --open-mode=append
###################################### dependencies
KV_ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"; source "$KV_ROOT/slurms/analysis_env.sh"
###################################### parameters
NAME=02_envs
envs=kv
minimap2_216=0
PARAMS=(envs minimap2_216); kv_args "$@"; [ ${#KV_ARGS[@]} -gt 0 ] && envs="${KV_ARGS[*]}"
###################################### envs
failed=()
for e in $envs; do
  kv_log "env $e"
  if conda env list | awk '{print $1}' | grep -qx "$e"; then conda env update -q -n "$e" -f "$KV_ROOT/envs/$e.yml" --prune || failed+=("$e")
  else conda env create -q -f "$KV_ROOT/envs/$e.yml" || failed+=("$e"); fi
  [ "$e" = kv ] && { kv_activate kv; pip install -q -e "$TOOLS/CRISPRLungo"; conda deactivate; }
done
[ "$minimap2_216" = 1 ] && [ ! -x "$TOOLS/minimap2_216/bin/minimap2" ] && conda create -y -q -p "$TOOLS/minimap2_216" -c conda-forge -c bioconda minimap2=2.16
kv_log "failed envs: ${failed[*]:-none}"; kv_footer
[ ${#failed[@]} -eq 0 ]
