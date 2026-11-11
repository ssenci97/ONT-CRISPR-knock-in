#!/bin/bash
###################################### dependencies
set -euo pipefail
KV_ROOT="${KV_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"; cd "$KV_ROOT"
###################################### parameters
NAME=build
registry="${KV_REGISTRY:-ghcr.io}"
owner="${KV_OWNER:-$(git config --get remote.origin.url 2>/dev/null | sed -n 's#.*[/:]\([^/]*\)/[^/]*$#\1#p')}"
owner="${owner:-local}"; owner="${owner,,}"
tag="${KV_TAG:-1.0}"
engine="${KV_ENGINE:-}"
T0=$SECONDS
image="$registry/$owner/ont-knockin-val:$tag"
sif=containers/ont-knockin-val.sif
lock=containers/kv.lock.txt
digests=containers/images.env
source containers/pins.env
###################################### helpers
log() { echo "[SLURM-INFO] $*"; }
footer() { log "$(date '+%F %T') | elapsed $(date -u -d @$((SECONDS-T0)) +%H:%M:%S) | max RSS 0.00 GB"; }
commit_of() { awk -F'\t' -v n="$1" 'NR>1 && $1==n{print $3}' configs/tools.tsv; }
pinned() { local c; c=$(commit_of "$1"); [[ "$c" =~ ^[0-9a-f]{40}$ ]] || { log "$1 is not pinned to a full commit sha in configs/tools.tsv: '$c'"; exit 1; }; echo "$c"; }
repo_of() { awk -F'\t' -v n="$1" 'NR>1 && $1==n{print $2}' configs/tools.tsv; }
###################################### engine
if [ -z "$engine" ]; then
  if command -v docker >/dev/null && docker info >/dev/null 2>&1; then engine=docker; else engine=podman; fi
fi
command -v "$engine" >/dev/null || { log "$engine not found"; exit 1; }
engine_flags=()
if [ "$engine" = podman ]; then
  engine_flags=(--cgroup-manager=cgroupfs --events-backend=file)
  if [ ! -d "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" ]; then
    export XDG_RUNTIME_DIR="${TMPDIR:-/tmp}/podman-$(id -u)"; mkdir -p -m 700 "$XDG_RUNTIME_DIR"
    log "no /run/user/$(id -u); using XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"
  fi
fi
MODE="${1:-build}"
[[ "$owner" =~ ^[a-z0-9._-]+$ ]] || { log "KV_OWNER must be lowercase: '$owner'"; exit 1; }
log "param registry=$registry"; log "param owner=$owner"; log "param tag=$tag"; log "param engine=$engine ${engine_flags[*]}"
###################################### build
build_image() {
  log "building $image (base $BASE_TAG_FOR_HUMANS, ALPINE @ $(pinned ALPINE | cut -c1-7), CRISPRLungo @ $(pinned CRISPRLungo | cut -c1-7), lock $([ -s "$lock" ] && echo yes || echo "no -- solved from envs/kv.yml"))"
  "$engine" "${engine_flags[@]}" build -f containers/Dockerfile -t "$image" --build-arg "BASE_REF=$BASE_REF" \
    --build-arg "ALPINE_REPO=$(repo_of ALPINE)" --build-arg "ALPINE_COMMIT=$(pinned ALPINE)" \
    --build-arg "LUNGO_REPO=$(repo_of CRISPRLungo)" --build-arg "LUNGO_COMMIT=$(pinned CRISPRLungo)" .
}
write_lock() {
  log "exporting $lock from $image"
  "$engine" "${engine_flags[@]}" run --rm "$image" conda list -n kv --explicit --md5 > "$lock.tmp"
  grep -q "^https\?://" "$lock.tmp" || { log "export produced no package urls"; rm -f "$lock.tmp"; exit 1; }
  mv "$lock.tmp" "$lock"
  log "$(grep -c "^https\?://" "$lock") packages pinned; rebuild to use it"
}
###################################### registry
do_login() {
  [ -n "${KV_GITHUB_TOKEN:-}" ] || { log "export KV_GITHUB_TOKEN=<github personal access token with write:packages>"; exit 1; }
  log "logging in to $registry as $owner"
  printf '%s' "$KV_GITHUB_TOKEN" | "$engine" "${engine_flags[@]}" login "$registry" -u "$owner" --password-stdin
}
push_image() {
  [ "$owner" = local ] && { log "set KV_OWNER to your github namespace before pushing"; exit 1; }
  log "pushing $image"
  "$engine" "${engine_flags[@]}" push "$image"
  local d; d="$("$engine" "${engine_flags[@]}" inspect --format '{{index .RepoDigests 0}}' "$image" 2>/dev/null | sed -n 's/.*@//p')"
  [ -n "$d" ] || { log "no digest for $image"; exit 1; }
  printf 'KV_IMAGE_REF=%s@%s\n' "${image%:*}" "$d" > "$digests"
  log "wrote $digests: ${image%:*}@$d -- commit it"
}
###################################### orfeo
orfeo() {
  local ref="$image"
  [ -s "$digests" ] && ref="$(sed -n 's/^KV_IMAGE_REF=//p' "$digests" | tail -1)"
  cat <<EOS
[SLURM-INFO] on orfeo, from the repo root:

  export SINGULARITY_CACHEDIR=\$PWD/.singularity APPTAINER_CACHEDIR=\$PWD/.singularity
  singularity pull --force $sif docker://$ref

  export KV_SIF=\$PWD/$sif
  bash slurms/run_all.sh --sbatch
EOS
}
###################################### dispatch
case "$MODE" in
  build|all) build_image ;;
  lock)      write_lock ;;
  login)     do_login ;;
  push)      push_image ;;
  ship)      do_login; push_image; orfeo ;;
  orfeo)     orfeo ;;
  *) log "usage: build.sh [build|lock|login|push|ship|orfeo]"; exit 1 ;;
esac
footer
