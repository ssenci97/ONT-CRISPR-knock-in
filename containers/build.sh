#!/bin/bash
###################################### dependencies
set -euo pipefail
KV_ROOT="${KV_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"; cd "$KV_ROOT"
###################################### parameters
NAME=build
registry=ghcr.io
owner="${KV_OWNER:-local}"
tag=1.0
engine=podman
T0=$SECONDS
owner="${owner,,}"
base_image="$registry/$owner/ont-knockin-val-base:$tag"
full_image="localhost/ont-knockin-val:$tag"
sif=containers/ont-knockin-val.sif
lock=containers/kv.lock.txt
source containers/pins.env
###################################### helpers
log() { echo "[SLURM-INFO] $*"; }
footer() { log "$(date '+%F %T') | elapsed $(date -u -d @$((SECONDS-T0)) +%H:%M:%S) | max RSS 0.00 GB"; }
commit_of() { awk -F'\t' -v n="$1" 'NR>1 && $1==n{print $3}' configs/tools.tsv; }
pinned() { local c; c=$(commit_of "$1"); [[ "$c" =~ ^[0-9a-f]{40}$ ]] || { log "$1 is not pinned to a full commit sha in configs/tools.tsv: '$c'"; exit 1; }; echo "$c"; }
repo_of() { awk -F'\t' -v n="$1" 'NR>1 && $1==n{print $2}' configs/tools.tsv; }
###################################### build
command -v "$engine" >/dev/null || { log "$engine not found"; exit 1; }
MODE="${1:-all}"
[[ "$owner" =~ ^[a-z0-9._-]+$ ]] || { log "KV_OWNER must be lowercase: '$owner'"; exit 1; }
[ "$MODE" = push ] && [ "$owner" = local ] && { log "set KV_OWNER to your lowercase registry namespace before pushing, e.g. KV_OWNER=ritareasciencepark"; exit 1; }
log "param registry=$registry"; log "param owner=$owner"; log "param tag=$tag"; log "param engine=$engine"

build_base() {
  log "building $base_image (base $BASE_TAG_FOR_HUMANS, ALPINE @ $(pinned ALPINE | cut -c1-7), lock $([ -s "$lock" ] && echo yes || echo "no -- solved from envs/kv.yml"))"
  "$engine" build -f containers/Dockerfile.base -t "$base_image" --build-arg "BASE_REF=$BASE_REF" \
    --build-arg "ALPINE_REPO=$(repo_of ALPINE)" --build-arg "ALPINE_COMMIT=$(pinned ALPINE)" .
}
build_full() {
  log "building $full_image (CRISPRLungo @ $(commit_of CRISPRLungo | cut -c1-7)) -- local only, never pushed"
  "$engine" build -f containers/Dockerfile -t "$full_image" --build-arg "BASE=$base_image" \
    --build-arg "LUNGO_REPO=$(repo_of CRISPRLungo)" --build-arg "LUNGO_COMMIT=$(pinned CRISPRLungo)" .
}
push_base() {
  [ "$owner" = local ] && { log "refusing to push a 'local' namespace"; exit 1; }
  log "pushing $base_image"
  "$engine" push "$base_image"
  log "digest $("$engine" inspect --format '{{index .RepoDigests 0}}' "$base_image" 2>/dev/null || echo unknown)"
}

write_lock() {
  log "exporting $lock from $base_image"
  "$engine" run --rm "$base_image" conda list -n kv --explicit --md5 > "$lock.tmp"
  grep -q "^https\?://" "$lock.tmp" || { log "export produced no package urls"; rm -f "$lock.tmp"; exit 1; }
  mv "$lock.tmp" "$lock"
  log "$(grep -c "^https\?://" "$lock") packages pinned; rebuild to use it"
}

build_sif() {
  command -v apptainer >/dev/null || { log "apptainer not found"; exit 1; }
  log "converting $full_image to $sif"
  local tar; tar="$(mktemp -u "${TMPDIR:-/tmp}/kv.XXXXXX.tar")"
  "$engine" save --format oci-archive -o "$tar" "$full_image"
  apptainer build -F "$sif" "oci-archive:$tar"; rm -f "$tar"
  log "run it with: export KV_SIF=\$PWD/$sif"
}

case "$MODE" in
  base) build_base ;;
  lock) write_lock ;;
  sif)  build_sif ;;
  full) build_full ;;
  push) push_base ;;
  all)  build_base; build_full; build_sif ;;
  push-full) log "refusing: CRISPResso2 may not be redistributed, see LICENSES.md"; exit 1 ;;
  *) log "usage: build.sh [all|base|full|sif|lock|push]"; exit 1 ;;
esac
footer
