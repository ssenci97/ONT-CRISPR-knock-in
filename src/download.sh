#!/bin/bash
###################################### dependencies
source "$(dirname "$0")/common.sh"
###################################### parameters
run="$1"; ena="$2"; out="$3"; threads="$4"
###################################### download
fq="${out%.fastq.gz}"; exp=$(awk -F'\t' -v r="$run" '$1==r{print $2}' "$ena")
[ -n "$exp" ] || { kv_log "$run not in $ena"; exit 1; }
kv_log "download $run (ENA read_count $exp)"
curl -sSf --retry 5 -C - -o "$fq.sra" "https://sra-pub-run-odp.s3.amazonaws.com/sra/$run/$run"
fasterq-dump -e "$threads" -t "$fq.tmp" -O "$(dirname "$fq")" "$fq.sra"; rm -rf "${fq:?}.tmp"
n=$(( $(wc -l < "$fq.fastq") / 4 )); [ "$n" = "$exp" ] || { kv_log "read count mismatch $run: $n vs ENA $exp"; exit 1; }
pigz -p "$threads" -c "$fq.fastq" > "$out.tmp"
mv "$out.tmp" "$out"; rm -f "${fq:?}.fastq" "${fq:?}.sra"
kv_log "$run: $n reads"; kv_footer
