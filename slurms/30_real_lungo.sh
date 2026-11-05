#!/bin/bash
#SBATCH --job-name=kv_real_lungo
#SBATCH --partition=GENOA
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --output=logs/30_real/lungo_%A_%a.log
#SBATCH --array=1-5%2
#SBATCH --open-mode=append
###################################### dependencies
KV_ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"; source "$KV_ROOT/slurms/analysis_env.sh"
###################################### parameters
NAME=30_real_lungo
CLEAVAGE_POS=17
WINDOW=25
PARAMS=(CLEAVAGE_POS WINDOW CONTROL); kv_args "$@"
###################################### per sample
kv_activate kv_lungo; out="$RESULTS/real/CRISPRLungo"; mkdir -p "$out"; guide=$(kv_design "d['design']['guide']"); cd "$out"
for label in $(kv_samples); do
  rm -rf "${out:?}/${label:?}"; kv_log "CRISPRLungo $label"
  kv_time "$out/time_$label.log" CRISPRlungo "$REFS/TRAC_WT.fa" "$DATA/real/$label.fastq.gz" "$out/$label" "$guide" \
    --cleavage_pos "$CLEAVAGE_POS" --window "$WINDOW" --control "$DATA/real/$CONTROL.fastq.gz" \
    --induced_sequence_path "$REFS/TRAC_KI.fa" --integration_file "$REFS/CAR_insert.fa" -t "$THREADS" > "$out/$label.log" 2>&1 || kv_log "!! $label failed (see $out/$label.log)"
done
kv_footer
