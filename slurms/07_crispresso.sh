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
PROCS=$THREADS
WINDOW_CENTER=-5
WINDOW=10
MIN_BQ=20
TIMEOUT=47h
PARAMS=(PROCS WINDOW_CENTER WINDOW MIN_BQ TIMEOUT); kv_args "$@"
###################################### amplicons
kv_activate kv_crispresso; out="$RESULTS/CRISPResso2"; mkdir -p "$out"; cd "$out"
mask() { awk '!/^>/{s=s $0} END{n=sprintf("%100s",""); gsub(/ /,"N",n); print n substr(s,101,length(s)-200) n}' "$1"; }
WT=$(mask "$REFS/TRAC_WT.fa"); KI=$(mask "$REFS/TRAC_KI.fa"); guide=$(kv_design "d['design']['guide']")
###################################### per sample
for label in $(kv_samples); do
  fq="$DATA/$label.fastq.gz"; rm -rf "${out:?}/CRISPResso_on_${label:?}"
  kv_log "CRISPResso2 $label ($(seqkit stats -T "$fq" | awk 'NR==2{print $4}') reads, -p $PROCS)"
  kv_time "time_$label.log" timeout "$TIMEOUT" CRISPResso --fastq_r1 "$fq" -a "$WT" -an TRAC_WT -e "$KI" -g "$guide" \
    -wc "$WINDOW_CENTER" -w "$WINDOW" --ignore_substitutions --min_bp_quality_or_N "$MIN_BQ" --suppress_report --suppress_plots \
    -p "$PROCS" -n "$label" -o . > "$label.log" 2>&1 || kv_log "!! $label failed (see $out/$label.log)"
done
kv_footer
