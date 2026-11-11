#!/bin/bash
#SBATCH --job-name=kv_alpine
#SBATCH --partition=GENOA
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=128G
#SBATCH --time=24:00:00
#SBATCH --output=logs/05_alpine/alpine_%A_%a.log
#SBATCH --array=1-5
#SBATCH --open-mode=append
###################################### dependencies
KV_ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"; source "$KV_ROOT/slurms/analysis_env.sh"
###################################### parameters
NAME=05_alpine
alpine_primer_check_length=150
alpine_data_type=nanopore
PARAMS=(alpine_primer_check_length alpine_data_type); kv_args "$@"; kv_log "param shared.ki_min_insert_frac=$ki_min_insert_frac"
###################################### preflight
[ -d "$TOOLS/ALPINE" ] || { kv_log "ALPINE not found at $TOOLS/ALPINE"; exit 1; }
command -v cwltool >/dev/null || { kv_log "cwltool not on PATH"; exit 1; }
rc=0
###################################### design
pf=$(kv_design "d['amplicon']['primer_f_full']"); pr=$(kv_design "d['amplicon']['primer_r_full'].translate(str.maketrans('ACGT','TGCA'))[::-1]"); lha=$(kv_design "d['design']['LHA_seq']"); rha=$(kv_design "d['design']['RHA_seq']")
###################################### per sample
for sample_id in $(kv_samples); do
  o="$RESULTS/ALPINE/$sample_id"; rm -rf "${o:?}"; mkdir -p "$o"
  printf 'fastqfile: {class: File, path: %s}\nreffile: {class: File, path: %s}\nconfig: {class: File, path: %s}\nsample_name: "%s"\nprimer_1: "%s"\nprimer_2: "%s"\nprimer_check_length: %s\ndata_type: %s\ntruncated_cutoff: %s\nfive_prime_HA_seq: "%s"\nthree_prime_HA_seq: "%s"\n' \
    "$DATA/$sample_id.fastq.gz" "$REFS/alpine/ref.fa" "$REFS/alpine/config.tsv" "$sample_id" "$pf" "$pr" "$alpine_primer_check_length" "$alpine_data_type" "$ki_min_insert_frac" "$lha" "$rha" > "$o/job.yaml"
  kv_meta "$sample_id" "$NAME" primer_check_length="$alpine_primer_check_length" data_type="$alpine_data_type" truncated_cutoff="$ki_min_insert_frac"
  kv_log "ALPINE $sample_id"
  kv_time "$o/time.log" bash "$KV_ROOT/src/alpine_local.sh" "$o/job.yaml" "$o" "${KV_YFLAGS[@]}" > "$o/run.log" 2>&1 || { kv_log "!! $sample_id failed (see $o/run.log)"; rc=1; }
done
kv_footer
exit $rc
