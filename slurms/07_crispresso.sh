#!/bin/bash
#SBATCH --job-name=kv_crispresso
#SBATCH --partition=GENOA
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=64
#SBATCH --mem=240G
#SBATCH --time=48:00:00
#SBATCH --output=logs/07_crispresso/crispresso_%A_%a.log
#SBATCH --array=1-5
#SBATCH --open-mode=append
###################################### dependencies
KV_ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"; source "$KV_ROOT/slurms/analysis_env.sh"
###################################### parameters
NAME=07_crispresso
crispresso_window_center=-5
crispresso_window=10
crispresso_min_bq=20
crispresso_timeout=47h
PARAMS=(crispresso_window_center crispresso_window crispresso_min_bq crispresso_timeout); kv_args "$@"
###################################### amplicons
out="$RESULTS/CRISPResso2"; mkdir -p "$out"; cd "$out"
mask() { awk '!/^>/{s=s $0} END{n=sprintf("%100s",""); gsub(/ /,"N",n); print n substr(s,101,length(s)-200) n}' "$1"; }
WT=$(mask "$wt_fasta"); KI=$(mask "$ki_fasta"); guide=$(kv_design "d['design']['guide']")
###################################### per sample
for sample_id in $(kv_samples); do
  fastq="$DATA/$sample_id.fastq.gz"; rm -rf "${out:?}/CRISPResso_on_${sample_id:?}"
  kv_log "CRISPResso2 $sample_id ($(seqkit stats -T "$fastq" | awk 'NR==2{print $4}') reads, -p $threads)"
  kv_time "time_$sample_id.log" timeout "$crispresso_timeout" CRISPResso --fastq_r1 "$fastq" -a "$WT" -an TRAC_WT -e "$KI" -g "$guide" \
    -wc "$crispresso_window_center" -w "$crispresso_window" --ignore_substitutions --min_bp_quality_or_N "$crispresso_min_bq" --suppress_report --suppress_plots \
    -p "$threads" -n "$sample_id" -o . > "$sample_id.log" 2>&1 || kv_log "!! $sample_id failed (see $out/$sample_id.log)"
done
kv_footer
