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
bioproject=PRJNA1257358
min_len=3500
max_len=7500
PARAMS=(bioproject min_len max_len); kv_args "$@"; MODE="${KV_ARGS[0]:-all}"
###################################### metadata
R="$DATA/raw"; mkdir -p "$R" "$DATA/meta"; meta="$DATA/meta/${bioproject}_ena.tsv"; stats="$DATA/read_stats.tsv"
( flock 8; [ -s "$meta" ] || curl -sf "https://www.ebi.ac.uk/ena/portal/api/filereport?accession=$bioproject&result=read_run&fields=run_accession,sample_accession,experiment_title,library_name,sample_alias,fastq_bytes,fastq_md5,fastq_ftp,read_count,base_count&limit=0" > "$meta" ) 8>"$meta.lock"
[ -z "${SLURM_ARRAY_TASK_ID:-}" ] && [ "$MODE" != "--download-only" ] && printf "sample_id\trun\traw_reads\tlen_pass\n" > "$stats"
###################################### per sample
for sample_id in $(kv_samples); do
  run=$(kv_field "$sample_id" srr); local_fq=$(kv_submitted "$sample_id" fastq_path)
  if [ -n "$local_fq" ]; then
    [ -s "$local_fq" ] || { kv_log "$sample_id: fastq_path not readable: $local_fq"; exit 1; }
    src="$local_fq"; run="${run:-local}"; n_raw=$(seqkit stats -T "$src" | awk 'NR==2{print $4}')
    kv_log "local fastq $sample_id ($src)"
    [ "$MODE" = "--download-only" ] && continue
  else
    fq="${R:?}/${run:?}"; exp=$(awk -F'\t' -v r="$run" '$1==r{print $9}' "$meta")
    if [ "$MODE" != "--filter-only" ] && [ ! -s "$fq.fastq.gz.ok" ]; then
      kv_log "download $run ($sample_id)"
      curl -sf --retry 5 -C - -o "$fq.sra" "https://sra-pub-run-odp.s3.amazonaws.com/sra/$run/$run"
      fasterq-dump -e "$threads" -t "$fq.tmp" -O "$R" "$fq.sra"; rm -rf "${fq:?}.tmp"
      n=$(( $(wc -l < "$fq.fastq") / 4 )); [ "$n" = "$exp" ] || { kv_log "read count mismatch $run: $n vs ENA $exp"; exit 1; }
      pigz -p "$threads" -f "$fq.fastq" && rm -f "${fq:?}.sra"; echo "$n" > "$fq.fastq.gz.ok"
    fi
    [ "$MODE" = "--download-only" ] && continue
    src="$fq.fastq.gz"; n_raw=$(cat "$fq.fastq.gz.ok")
  fi
  kv_log "length filter $sample_id ($min_len-$max_len bp)"
  seqkit seq -j "$threads" -g -G "-" -m "$min_len" -M "$max_len" "$src" -o "$DATA/$sample_id.fastq.gz"
  n_f=$(seqkit stats -T "$DATA/$sample_id.fastq.gz" | awk 'NR==2{print $4}')
  ( flock 9; [ -s "$stats" ] || printf "sample_id\trun\traw_reads\tlen_pass\n" > "$stats"; { grep -v "^$sample_id	" "$stats" || true; printf "%s\t%s\t%s\t%s\n" "$sample_id" "$run" "$n_raw" "$n_f"; } > "$stats.tmp"; mv "$stats.tmp" "$stats" ) 9>"$stats.lock"
  kv_meta "$sample_id" "$NAME" run="$run" raw_reads="$n_raw" len_pass="$n_f" min_len="$min_len" max_len="$max_len"
  kv_log "$sample_id: raw $n_raw, length-pass $n_f (all used)"
done
kv_footer
