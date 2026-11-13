#!/bin/bash
###################################### dependencies
source "$(dirname "$0")/common.sh"
###################################### parameters
bioproject="$1"; out="$2"
###################################### fetch
kv_log "ENA filereport $bioproject"
curl -sSf "https://www.ebi.ac.uk/ena/portal/api/filereport?accession=$bioproject&result=read_run&fields=run_accession,read_count&limit=0" > "$out.tmp"
mv "$out.tmp" "$out"
kv_log "$bioproject: $(( $(wc -l < "$out") - 1 )) runs"; kv_footer
