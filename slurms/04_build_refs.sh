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
REGION=14:22540000..22560000:1
PMC=PMC12166421
PARAMS=(REGION PMC); kv_args "$@"
###################################### download
RR="$DATA/raw_refs"; mkdir -p "$RR/supp"; G="$RR/hg38_chr14_22540000_22560000.fa"
[ -s "$G" ] || { kv_log "hg38 $REGION"; curl -sf "https://rest.ensembl.org/sequence/region/human/$REGION?content-type=text/x-fasta" > "$G"; }
[ -s "$RR/supp/mmc2.xlsx" ] || { kv_log "supplements $PMC"; curl -sfL -o "$RR/supp/supp.zip" "https://www.ebi.ac.uk/europepmc/webservices/rest/$PMC/supplementaryFiles"; unzip -o -q "$RR/supp/supp.zip" -d "$RR/supp"; }
###################################### build
kv_activate kv_alpine
cd "$KV_ROOT"; kv_time - python3 src/build_refs.py "${KV_YFLAGS[@]}"
kv_footer
