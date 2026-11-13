#!/bin/bash
###################################### dependencies
source "$(dirname "$0")/common.sh"
###################################### parameters
sample_id="$1"; fq="$(realpath "$2")"; OUT="$(realpath -m "$3")"; primer_check_length="$4"; data_type="$5"; truncated_cutoff="$6"; threads="$7"; mem_mb="$8"
A="$TOOLS/ALPINE"; WORK="$OUT/cwl_local"; D="$WORK/DockerFile"; R="$KV_OUT/refs"
[ -d "$A/CWL" ] || { kv_log "ALPINE not found at $A (not running inside the image?)"; exit 1; }
###################################### job
rm -rf "${OUT:?}"; mkdir -p "$WORK"
pf=$(kv_design "d['amplicon']['primer_f_full']"); pr=$(kv_design "d['amplicon']['primer_r_full']"); lha=$(kv_design "d['design']['LHA_seq']"); rha=$(kv_design "d['design']['RHA_seq']")
printf 'fastqfile: {class: File, path: %s}\nreffile: {class: File, path: %s}\nconfig: {class: File, path: %s}\nsample_name: "%s"\nprimer_1: "%s"\nprimer_2: "%s"\nprimer_check_length: %s\ndata_type: %s\ntruncated_cutoff: %s\nfive_prime_HA_seq: "%s"\nthree_prime_HA_seq: "%s"\n' \
  "$fq" "$R/alpine/ref.fa" "$R/alpine/config.tsv" "$sample_id" "$pf" "$pr" "$primer_check_length" "$data_type" "$truncated_cutoff" "$lha" "$rha" > "$OUT/job.yaml"
###################################### patched local copy of the CWL
cp -r "$A/CWL/." "$WORK/"; cp -r "$A/DockerFile" "$WORK/"
preset=map-hifi; [ "$data_type" = nanopore ] && preset=map-ont; patched=0
if [ "$preset" != map-hifi ]; then
  for f in "$D/classify/utils/data_utils.py" "$D/classify/utils/realign_ins_to_wildtype.py"; do
    [ -f "$f" ] && grep -q -- "-ax map-hifi" "$f" && { sed -i "s/-ax map-hifi/-ax $preset/g" "$f"; patched=$((patched + 1)); }
  done
  [ "$patched" -gt 0 ] || { kv_log "wanted minimap2 preset $preset but found no map-hifi call to patch"; exit 1; }
fi
for f in "$WORK"/*.cwl "$WORK"/*/*.cwl; do
  sed -i -e "s#/opt/filter_fastq_gz.py#$D/filter/filter_fastq_gz.py#g" -e "s#/opt/classify_read.py#$D/classify/classify_read.py#g" \
    -e "s#/opt/count_classification_table.py#$D/count/count_classification_table.py#g" -e "s#/opt/merge_count_table.py#$D/merge_table/merge_count_table.py#g" \
    -e "s#coresMin: [0-9]*#coresMin: $threads#" -e "s#ramMin: [0-9]*#ramMin: $mem_mb#" -e '/class: DockerRequirement/{N;d}' "$f"
done
export PATCHER_MINIMAP2_PATH="$TOOLS/minimap2_216/bin/minimap2"
kv_log "ALPINE $sample_id: data_type=$data_type preset=$preset patched=$patched minimap2 $("$PATCHER_MINIMAP2_PATH" --version)"
kv_meta "$sample_id" 03_alpine primer_check_length="$primer_check_length" data_type="$data_type" truncated_cutoff="$truncated_cutoff" minimap2_preset="$preset" minimap2_calls_patched="$patched"
###################################### run
cd "$OUT"; rc=0
cwltool --no-container --preserve-entire-environment --outdir "$OUT" "$WORK/aav_per_sample_workflow.cwl" "$OUT/job.yaml" || rc=$?
t="$OUT/${sample_id}_read_classification.txt"
[ -s "$t" ] || { f=$(find "$OUT" -path "$WORK" -prune -o -name "${sample_id}_read_classification.txt" -print | head -1); [ -n "$f" ] && cp "$f" "$t"; }
[ -s "$t" ] || { kv_log "cwltool exit $rc and no classification table"; exit 1; }
[ "$rc" = 0 ] || kv_log "!! cwltool exit $rc after the classification table was written (group_output step)"
kv_footer
