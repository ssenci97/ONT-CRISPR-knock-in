#!/bin/bash
#SBATCH --job-name=kv_refs
#SBATCH --partition=GENOA
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=logs/04_build_refs/refs_%j.log
#SBATCH --open-mode=append
###################################### dependencies
KV_ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"; source "$KV_ROOT/slurms/analysis_env.sh"
###################################### parameters
NAME=04_build_refs
region=14:22540000..22560000:1
pmc=PMC12166421
genomic_fasta=data/raw_refs/hg38_chr14_22540000_22560000.fa
templates_xlsx=data/raw_refs/supp/mmc2.xlsx
PARAMS=(region pmc); kv_args "$@"; [ $KV_YIN = 1 ] && kv_read build_refs genomic_fasta templates_xlsx
###################################### download
RR="$DATA/raw_refs"; G="$KV_ROOT/$genomic_fasta"; X="$KV_ROOT/$templates_xlsx"; mkdir -p "$RR/supp"
[ -s "$G" ] || { kv_log "hg38 $region"; curl -sf "https://rest.ensembl.org/sequence/region/human/$region?content-type=text/x-fasta" > "$G"; }
[ -s "$X" ] || { kv_log "supplements $pmc"; curl -sfL -o "$RR/supp/supp.zip" "https://www.ebi.ac.uk/europepmc/webservices/rest/$pmc/supplementaryFiles"; unzip -o -q "$RR/supp/supp.zip" -d "$RR/supp"; }
###################################### pin
pins="$KV_ROOT/configs/refs.sha256"
if [ -s "$pins" ]; then
  ( cd "$KV_ROOT" && sha256sum -c --quiet "$pins" ) || { kv_log "downloaded references do not match $pins"; exit 1; }
  kv_log "references match configs/refs.sha256"
else
  ( cd "$KV_ROOT" && sha256sum "$genomic_fasta" "$templates_xlsx" > "$pins" )
  kv_log "wrote configs/refs.sha256 -- commit it to pin these downloads"
fi
###################################### build
cd "$KV_ROOT"; kv_time - python3 src/build_refs.py "${KV_YFLAGS[@]}"
kv_footer
