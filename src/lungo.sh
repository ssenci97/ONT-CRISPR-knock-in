#!/bin/bash
###################################### dependencies
source "$(dirname "$0")/common.sh"
###################################### parameters
sample_id="$1"; fq="$(realpath "$2")"; ctrl="$(realpath "$3")"; ctrl_id="$4"; out="$(realpath -m "$5")"; cleavage_pos="$6"; window="$7"; threads="$8"
R="$KV_OUT/refs"
command -v CRISPRlungo >/dev/null || { kv_log "CRISPRlungo not on PATH (not running inside the image?)"; exit 1; }
###################################### run
guide=$(kv_design "d['design']['guide']")
rm -rf "${out:?}/${sample_id:?}"; mkdir -p "$out"; cd "$out"
kv_meta "$sample_id" 04_lungo cleavage_pos="$cleavage_pos" window="$window" control="$ctrl_id"
kv_log "CRISPRLungo $sample_id (control $ctrl_id)"
CRISPRlungo "$R/TRAC_WT.fa" "$fq" "$out/$sample_id" "$guide" --cleavage_pos "$cleavage_pos" --window "$window" --control "$ctrl" \
  --induced_sequence_path "$R/TRAC_KI.fa" --integration_file "$R/CAR_insert.fa" -t "$threads"
kv_footer
