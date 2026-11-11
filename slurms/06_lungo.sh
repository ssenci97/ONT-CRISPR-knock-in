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
lungo_cleavage_pos=17
lungo_window=25
PARAMS=(lungo_cleavage_pos lungo_window); kv_args "$@"
###################################### preflight
command -v CRISPRlungo >/dev/null || { kv_log "CRISPRlungo not on PATH"; exit 1; }
rc=0
###################################### per sample
control_fastq="$DATA/$(kv_control).fastq.gz"; out="$RESULTS/CRISPRLungo"; mkdir -p "$out"; guide=$(kv_design "d['design']['guide']"); cd "$out"
for sample_id in $(kv_samples); do
  rm -rf "${out:?}/${sample_id:?}"
  kv_meta "$sample_id" "$NAME" cleavage_pos="$lungo_cleavage_pos" window="$lungo_window" control="$(kv_control)"
  kv_log "CRISPRLungo $sample_id"
  kv_time "$out/time_$sample_id.log" CRISPRlungo "$wt_fasta" "$DATA/$sample_id.fastq.gz" "$out/$sample_id" "$guide" \
    --cleavage_pos "$lungo_cleavage_pos" --window "$lungo_window" --control "$control_fastq" \
    --induced_sequence_path "$ki_fasta" --integration_file "$insert_fasta" -t "$threads" > "$out/$sample_id.log" 2>&1 || { kv_log "!! $sample_id failed (see $out/$sample_id.log)"; rc=1; }
done
kv_footer
exit $rc
