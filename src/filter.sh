#!/bin/bash
###################################### dependencies
source "$(dirname "$0")/common.sh"
###################################### parameters
sample_id="$1"; run="$2"; src="$3"; out="$4"; stats="$5"; min_len="$6"; max_len="$7"; threads="$8"
###################################### filter
kv_log "length filter $sample_id ($src, $min_len-$max_len bp)"
n_raw=$(seqkit stats -T "$src" | awk 'NR==2{print $4}')
seqkit seq -j "$threads" -g -G "-" -m "$min_len" -M "$max_len" "$src" -o "$out"
n_f=$(seqkit stats -T "$out" | awk 'NR==2{print $4}')
printf "sample_id\trun\traw_reads\tlen_pass\n%s\t%s\t%s\t%s\n" "$sample_id" "$run" "$n_raw" "$n_f" > "$stats"
kv_meta "$sample_id" 01_fetch run="$run" raw_reads="$n_raw" len_pass="$n_f" min_len="$min_len" max_len="$max_len"
kv_log "$sample_id: raw $n_raw, length-pass $n_f"; kv_footer
