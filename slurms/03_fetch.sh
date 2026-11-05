#!/bin/bash
#SBATCH --job-name=kv_fetch
#SBATCH --partition=GENOA
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --output=logs/03_fetch/fetch_%A_%a.log
#SBATCH --array=1-5%2
#SBATCH --open-mode=append
###################################### dependencies
KV_ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"; source "$KV_ROOT/slurms/analysis_env.sh"
###################################### parameters
NAME=03_fetch
BIOPROJECT=PRJNA1257358
MIN_LEN=3500
MAX_LEN=7500
declare -A SRR=([Mock_r1]=SRR33387478 [NoDonor_r1]=SRR33387470 [dsDNA_r1]=SRR33387467 [ssDNA_r1]=SRR33387464 [ssCTS_r1]=SRR33387474)
PARAMS=(BIOPROJECT MIN_LEN MAX_LEN); kv_args "$@"; MODE="${KV_ARGS[0]:-all}"
###################################### metadata
R="$DATA/raw"; mkdir -p "$R" "$DATA/meta"; meta="$DATA/meta/${BIOPROJECT}_ena.tsv"; stats="$DATA/read_stats.tsv"; kv_activate kv_sra
( flock 8; [ -s "$meta" ] || curl -sf "https://www.ebi.ac.uk/ena/portal/api/filereport?accession=$BIOPROJECT&result=read_run&fields=run_accession,sample_accession,experiment_title,library_name,sample_alias,fastq_bytes,fastq_md5,fastq_ftp,read_count,base_count&limit=0" > "$meta" ) 8>"$meta.lock"
[ -z "${SLURM_ARRAY_TASK_ID:-}" ] && [ "$MODE" != "--download-only" ] && printf "label\trun\traw_reads\tlen_pass\n" > "$stats"
###################################### per sample
for label in $(kv_samples); do
  run=${SRR[$label]}; fq="${R:?}/${run:?}"; exp=$(awk -F'\t' -v r="$run" '$1==r{print $9}' "$meta")
  if [ "$MODE" != "--filter-only" ] && [ ! -s "$fq.fastq.gz.ok" ]; then
    kv_log "download $run ($label)"
    curl -sf --retry 5 -C - -o "$fq.sra" "https://sra-pub-run-odp.s3.amazonaws.com/sra/$run/$run"
    fasterq-dump -e "$THREADS" -t "$fq.tmp" -O "$R" "$fq.sra"; rm -rf "${fq:?}.tmp"
    n=$(( $(wc -l < "$fq.fastq") / 4 )); [ "$n" = "$exp" ] || { kv_log "read count mismatch $run: $n vs ENA $exp"; exit 1; }
    pigz -p "$THREADS" -f "$fq.fastq" && rm -f "${fq:?}.sra"; echo "$n" > "$fq.fastq.gz.ok"
  fi
  [ "$MODE" = "--download-only" ] && continue
  n_raw=$(cat "$fq.fastq.gz.ok"); kv_log "length filter $label ($MIN_LEN-$MAX_LEN bp)"
  seqkit seq -j "$THREADS" -m "$MIN_LEN" -M "$MAX_LEN" "$fq.fastq.gz" -o "$DATA/$label.fastq.gz"
  n_f=$(seqkit stats -T "$DATA/$label.fastq.gz" | awk 'NR==2{print $4}')
  ( flock 9; [ -s "$stats" ] || printf "label\trun\traw_reads\tlen_pass\n" > "$stats"; { grep -v "^$label	" "$stats" || true; printf "%s\t%s\t%s\t%s\n" "$label" "$run" "$n_raw" "$n_f"; } > "$stats.tmp"; mv "$stats.tmp" "$stats" ) 9>"$stats.lock"
  kv_log "$label: raw $n_raw, length-pass $n_f (all used)"
done
kv_footer
