#!/bin/bash
#SBATCH --job-name=kv_real_alpine
#SBATCH --partition=GENOA
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --output=logs/30_real/alpine_%A_%a.log
#SBATCH --array=1-5%2
#SBATCH --open-mode=append
###################################### dependencies
KV_ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"; source "$KV_ROOT/slurms/analysis_env.sh"
###################################### parameters
NAME=30_real_alpine
PRIMER_CHECK_LENGTH=150
DATA_TYPE=nanopore
PARAMS=(PRIMER_CHECK_LENGTH DATA_TYPE); kv_args "$@"
###################################### design
kv_activate kv_alpine
pf=$(kv_design "d['amplicon']['primer_f_full']"); pr=$(kv_design "d['amplicon']['primer_r_full']"); lha=$(kv_design "d['design']['LHA_seq']"); rha=$(kv_design "d['design']['RHA_seq']")
###################################### per sample
for label in $(kv_samples); do
  o="$RESULTS/real/ALPINE/$label"; rm -rf "${o:?}"; mkdir -p "$o"
  printf 'fastqfile: {class: File, path: %s}\nreffile: {class: File, path: %s}\nconfig: {class: File, path: %s}\nsample_name: "%s"\nprimer_1: "%s"\nprimer_2: "%s"\nprimer_check_length: %s\ndata_type: %s\nfive_prime_HA_seq: "%s"\nthree_prime_HA_seq: "%s"\n' \
    "$DATA/real/$label.fastq.gz" "$REFS/alpine/ref.fa" "$REFS/alpine/config.tsv" "$label" "$pf" "$pr" "$PRIMER_CHECK_LENGTH" "$DATA_TYPE" "$lha" "$rha" > "$o/job.yaml"
  kv_log "ALPINE $label"
  kv_time "$o/time.log" bash "$KV_ROOT/src/alpine_local.sh" "$o/job.yaml" "$o" "${KV_YFLAGS[@]}" > "$o/run.log" 2>&1 || kv_log "!! $label failed (see $o/run.log)"
done
kv_footer
