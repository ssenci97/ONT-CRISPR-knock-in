#!/bin/bash
#SBATCH --job-name=kv_lungo
#SBATCH --partition=GENOA
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=128G
#SBATCH --time=24:00:00
#SBATCH --output=logs/06_lungo/lungo_%A_%a.log
#SBATCH --array=1-5
#SBATCH --open-mode=append
###################################### dependencies
KV_ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"; source "$KV_ROOT/slurms/analysis_env.sh"
###################################### parameters
NAME=06_lungo
CLEAVAGE_POS=17
WINDOW=25
PARAMS=(CLEAVAGE_POS WINDOW CONTROL); kv_args "$@"
###################################### per sample
kv_activate kv_lungo; out="$RESULTS/CRISPRLungo"; mkdir -p "$out"; guide=$(kv_design "d['design']['guide']"); cd "$out"
for label in $(kv_samples); do
  rm -rf "${out:?}/${label:?}"; kv_log "CRISPRLungo $label"
  kv_time "$out/time_$label.log" CRISPRlungo "$REFS/TRAC_WT.fa" "$DATA/$label.fastq.gz" "$out/$label" "$guide" \
    --cleavage_pos "$CLEAVAGE_POS" --window "$WINDOW" --control "$DATA/$CONTROL.fastq.gz" \
    --induced_sequence_path "$REFS/TRAC_KI.fa" --integration_file "$REFS/CAR_insert.fa" -t "$THREADS" > "$out/$label.log" 2>&1 || kv_log "!! $label failed (see $out/$label.log)"
done
kv_footer
