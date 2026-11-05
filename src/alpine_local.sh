#!/bin/bash
###################################### dependencies
KV_ROOT="${KV_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"; source "$KV_ROOT/slurms/analysis_env.sh"
###################################### parameters
NAME=alpine_local
RAM_MB=6000
MM216="$CONDA_BASE/envs/kv_mm216/bin/minimap2"
PARAMS=(RAM_MB); kv_args "$@"
JOB="$(realpath "${KV_ARGS[0]:?usage: alpine_local.sh <job.yaml> <outdir> [--yaml-in|--yaml-out]}")"; OUT="$(realpath -m "${KV_ARGS[1]:?missing outdir}")"
A="$TOOLS/ALPINE"; D="$A/DockerFile"; WORK="$OUT/cwl_local"
###################################### local CWL
rm -rf "${WORK:?}"; mkdir -p "$WORK" "$OUT"; cp -r "$A/CWL/." "$WORK/"
for f in "$WORK"/*.cwl "$WORK"/*/*.cwl; do
  sed -i -e "s#/opt/filter_fastq_gz.py#$D/filter/filter_fastq_gz.py#g" -e "s#/opt/classify_read.py#$D/classify/classify_read.py#g" \
    -e "s#/opt/count_classification_table.py#$D/count/count_classification_table.py#g" -e "s#/opt/merge_count_table.py#$D/merge_table/merge_count_table.py#g" \
    -e "s#coresMin: [0-9]*#coresMin: $THREADS#" -e "s#ramMin: [0-9]*#ramMin: $RAM_MB#" -e '/class: DockerRequirement/{N;d}' "$f"
done
[ -x "$MM216" ] || { kv_log "missing $MM216 (create env kv_mm216)"; exit 1; }
export PATCHER_MINIMAP2_PATH="$MM216"
###################################### run
cd "$OUT"; rc=0
cwltool --no-container --preserve-entire-environment --outdir "$OUT" "$WORK/aav_per_sample_workflow.cwl" "$JOB" || rc=$?
if [ "$rc" -ne 0 ] && ls "$OUT"/*_read_classification.txt >/dev/null 2>&1; then kv_log "cwltool exit $rc in group_output only; classification table present"; rc=0; fi
kv_log "ALPINE exit $rc"; kv_footer
exit "$rc"
