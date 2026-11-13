#!/bin/bash
###################################### dependencies
set -euo pipefail
module load singularity
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
MODE="${1:-build}"
if [ "$MODE" = orfeo ] || [ "$MODE" = pull ]; then
  orfeo_only=1
else
  orfeo_only=0
fi
if [ "$orfeo_only" = 0 ] && [ -z "$engine" ]; then
  if command -v docker >/dev/null && docker info >/dev/null 2>&1; then engine=docker; else engine=podman; fi
fi
[ "$orfeo_only" = 1 ] || command -v "$engine" >/dev/null || { log "$engine not found"; exit 1; }
engine_flags=()
if [ "$orfeo_only" = 0 ] && [ "$engine" = podman ]; then
  engine_flags=(--cgroup-manager=cgroupfs --events-backend=file)
  if [ ! -d "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" ]; then
    export XDG_RUNTIME_DIR="${TMPDIR:-/tmp}/podman-$(id -u)"; mkdir -p -m 700 "$XDG_RUNTIME_DIR"
    log "no /run/user/$(id -u); using XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"
  fi
fi
[[ "$owner" =~ ^[a-z0-9._-]+$ ]] || { log "KV_OWNER must be lowercase: '$owner'"; exit 1; }
if [ "$orfeo_only" = 0 ]; then
  log "param registry=$registry"; log "param owner=$owner"; log "param tag=$tag"; log "param engine=$engine ${engine_flags[*]}"
fi
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
pull() {
  local app ref
  app="${KV_APPTAINER:-$(command -v singularity || command -v apptainer || true)}"
  if [ -z "$app" ]; then
    log "singularity not on PATH: trying 'module load singularity' in a login shell"
    app="$(bash -lc 'module load singularity >/dev/null 2>&1; command -v singularity || command -v apptainer' 2>/dev/null || true)"
  fi
  [ -n "$app" ] || { log "no singularity/apptainer, even after 'module load singularity' -- are you on the cluster?"; exit 1; }
  log "using $app"
  ref="$image"
  if [ -s "$digests" ]; then ref="$(sed -n 's/^KV_IMAGE_REF=//p' "$digests" | tail -1)"
  else log "!! $digests missing: pulling by tag, not by digest"; fi
  export SINGULARITY_CACHEDIR="${SINGULARITY_CACHEDIR:-$KV_ROOT/.singularity}"
  export APPTAINER_CACHEDIR="$SINGULARITY_CACHEDIR"
  export SINGULARITY_TMPDIR="${SINGULARITY_TMPDIR:-$SINGULARITY_CACHEDIR/tmp}"
  export APPTAINER_TMPDIR="$SINGULARITY_TMPDIR"
  mkdir -p "$SINGULARITY_TMPDIR"
  local avail; avail=$(df -Pk "$KV_ROOT" | awk 'NR==2{print int($4/1048576)}')
  log "pulling $ref"
  log "into $KV_ROOT/$sif (cache $SINGULARITY_CACHEDIR, ${avail} GB free here)"
  [ "$avail" -lt 12 ] && log "!! only ${avail} GB free; the pull needs about 11 GB (cache + sif)"
  local procs="${SLURM_CPUS_ON_NODE:-$(nproc)}" sqmem="${KV_SQUASH_MEM:-1G}"
  log "mksquashfs capped: $procs procs, $sqmem"
  "$app" build --force --mksquashfs-args "-processors $procs -mem $sqmem" "$KV_ROOT/$sif" "docker://$ref"
  [ -s "$KV_ROOT/$sif" ] || { log "pull reported success but $sif is missing or empty"; exit 1; }
  log "ok: $(du -h "$KV_ROOT/$sif" | cut -f1) at $KV_ROOT/$sif"
  log "now start the console (python3 src/gui_serve.py) or run: python3 src/pipeline.py <analysis>"
}
orfeo() {
  local ref="$image"
  [ -s "$digests" ] && ref="$(sed -n 's/^KV_IMAGE_REF=//p' "$digests" | tail -1)"
  cat <<EOS
[SLURM-INFO] on orfeo, from the repo root:

  module load singularity
  export SINGULARITY_CACHEDIR=\$PWD/.singularity APPTAINER_CACHEDIR=\$PWD/.singularity
  singularity build --force --mksquashfs-args "-processors \${SLURM_CPUS_ON_NODE:-1} -mem 1G" $sif docker://$ref

  python3 src/pipeline.py <analysis>   # or start the console: python3 src/gui_serve.py
EOS
}
###################################### dispatch
case "$MODE" in
  build|all) build_image ;;
  pull)      pull ;;
  lock)      write_lock ;;
  login)     do_login ;;
  push)      push_image ;;
  ship)      do_login; push_image; orfeo ;;
  orfeo)     orfeo ;;
  *) log "usage: build.sh [build|all|lock|login|push|ship|pull|orfeo]"; exit 1 ;;
esac
footer
