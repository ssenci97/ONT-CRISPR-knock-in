#!/bin/bash
#SBATCH --job-name=kv_real_crispresso
#SBATCH --partition=GENOA
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --output=logs/30_real/crispresso_%A_%a.log
#SBATCH --array=1-5%2
#SBATCH --open-mode=append
###################################### dependencies
KV_ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"; source "$KV_ROOT/slurms/analysis_env.sh"
###################################### parameters
NAME=30_real_crispresso
N_READS=1000
PROCS=$([ -n "${SLURM_JOB_ID:-}" ] && echo 8 || echo 2)
WINDOW_CENTER=-5
WINDOW=10
MIN_BQ=20
TIMEOUT=3h
PARAMS=(N_READS PROCS WINDOW_CENTER WINDOW MIN_BQ TIMEOUT SEED); kv_args "$@"
###################################### amplicons
kv_activate kv_crispresso; out="$RESULTS/real/CRISPResso2"; mkdir -p "$out"; cd "$out"
mask() { awk '!/^>/{s=s $0} END{n=sprintf("%100s",""); gsub(/ /,"N",n); print n substr(s,101,length(s)-200) n}' "$1"; }
WT=$(mask "$REFS/TRAC_WT.fa"); KI=$(mask "$REFS/TRAC_KI.fa"); guide=$(kv_design "d['design']['guide']")
###################################### per sample
for label in $(kv_samples); do
  fq="${out:?}/${label:?}.capped.fastq.gz"; rm -rf "${out:?}/CRISPResso_on_${label:?}"
  ( set +o pipefail; seqkit shuffle -s "$SEED" "$DATA/real/$label.fastq.gz" 2>/dev/null | seqkit head -n "$N_READS" -o "$fq" )
  kv_log "CRISPResso2 $label ($N_READS reads)"
  kv_time "time_$label.log" timeout "$TIMEOUT" CRISPResso --fastq_r1 "$fq" -a "$WT" -an TRAC_WT -e "$KI" -g "$guide" \
    -wc "$WINDOW_CENTER" -w "$WINDOW" --ignore_substitutions --min_bp_quality_or_N "$MIN_BQ" --suppress_report --suppress_plots \
    -p "$PROCS" -n "$label" -o . > "$label.log" 2>&1 || kv_log "!! $label failed (see $out/$label.log)"
  rm -f "${fq:?}"
done
kv_footer
