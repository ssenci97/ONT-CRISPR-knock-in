#!/bin/bash
###################################### dependencies
KV_ROOT="${KV_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"; source "$KV_ROOT/slurms/analysis_env.sh"
###################################### parameters
NAME=alpine_local
PARAMS=(mem_mb); kv_args "$@"
minimap2_bin="$(command -v minimap2)"; [ -x "$TOOLS/minimap2_216/bin/minimap2" ] && minimap2_bin="$TOOLS/minimap2_216/bin/minimap2"
JOB="$(realpath "${KV_ARGS[0]:?usage: alpine_local.sh <job.yaml> <outdir> [--yaml-in|--yaml-out]}")"; OUT="$(realpath -m "${KV_ARGS[1]:?missing outdir}")"
A="$TOOLS/ALPINE"; WORK="$OUT/cwl_local"; D="$WORK/DockerFile"
###################################### local CWL and patched tool copy
rm -rf "${WORK:?}"; mkdir -p "$WORK" "$OUT"; cp -r "$A/CWL/." "$WORK/"; cp -r "$A/DockerFile" "$WORK/"
data_type="$(awk -F':[[:space:]]*' '$1=="data_type"{print $2}' "$JOB" | tr -d '"'"'"'" ')"
preset=map-hifi; [ "$data_type" = nanopore ] && preset=map-ont
patched=0
if [ "$preset" != map-hifi ]; then
  for f in "$D/classify/utils/data_utils.py" "$D/classify/utils/realign_ins_to_wildtype.py"; do
    [ -f "$f" ] && grep -q -- "-ax map-hifi" "$f" && { sed -i "s/-ax map-hifi/-ax $preset/g" "$f"; patched=$((patched + 1)); }
  done
fi
printf '%s\t%s\n' "$preset" "$patched" > "$OUT/minimap2_patch.tsv"
kv_log "ALPINE data_type=$data_type preset=$preset; patched $patched hardcoded minimap2 call(s) in the local copy"
grep -rn -- "-ax map-hifi" "$D" >/dev/null 2>&1 && kv_log "!! map-hifi still present in $D after patching"
for f in "$WORK"/*.cwl "$WORK"/*/*.cwl; do
  sed -i -e "s#/opt/filter_fastq_gz.py#$D/filter/filter_fastq_gz.py#g" -e "s#/opt/classify_read.py#$D/classify/classify_read.py#g" \
    -e "s#/opt/count_classification_table.py#$D/count/count_classification_table.py#g" -e "s#/opt/merge_count_table.py#$D/merge_table/merge_count_table.py#g" \
    -e "s#coresMin: [0-9]*#coresMin: $threads#" -e "s#ramMin: [0-9]*#ramMin: $mem_mb#" -e '/class: DockerRequirement/{N;d}' "$f"
done
[ -x "$minimap2_bin" ] || { kv_log "minimap2 not found (run slurms/02_envs.sh)"; exit 1; }
kv_log "minimap2 $minimap2_bin ($("$minimap2_bin" --version))"
export PATCHER_MINIMAP2_PATH="$minimap2_bin"
###################################### run
cd "$OUT"; rc=0
cwltool --no-container --preserve-entire-environment --outdir "$OUT" "$WORK/aav_per_sample_workflow.cwl" "$JOB" || rc=$?
if [ "$rc" -ne 0 ] && ls "$OUT"/*_read_classification.txt >/dev/null 2>&1; then kv_log "cwltool exit $rc in group_output only; classification table present"; rc=0; fi
kv_log "ALPINE exit $rc"; kv_footer
exit "$rc"
