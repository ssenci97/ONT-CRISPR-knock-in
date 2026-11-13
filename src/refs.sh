#!/bin/bash
###################################### dependencies
source "$(dirname "$0")/common.sh"; cd "$KV_ROOT"
###################################### parameters
PARAMS="$KV_OUT/inputs/params.yaml"
eval "$(python3 -I - "$PARAMS" <<'PY'
import shlex, sys, yaml
c = yaml.safe_load(open(sys.argv[1]))
for k in ("region", "pmc"): print(f"{k}={shlex.quote(str(c['refs'][k]))}")
for k in ("genomic_fasta", "templates_xlsx", "donor_ki_fasta"): print(f"{k}={shlex.quote(str(c['build_refs'].get(k) or ''))}")
PY
)"
###################################### download (cache shared by all analyses)
mkdir -p "$(dirname "$genomic_fasta")" data/raw_refs/supp
[ -s "$genomic_fasta" ] || { kv_log "hg38 $region"; curl -sSf "https://rest.ensembl.org/sequence/region/human/$region?content-type=text/x-fasta" > "$genomic_fasta.tmp"; mv "$genomic_fasta.tmp" "$genomic_fasta"; }
if [ -n "$donor_ki_fasta" ]; then
  [ -s "$donor_ki_fasta" ] || { kv_log "donor_ki_fasta $donor_ki_fasta is missing"; exit 1; }
  pin_files=("$genomic_fasta" "$donor_ki_fasta")
else
  [ -s "$templates_xlsx" ] || { kv_log "supplements $pmc"; curl -sSfL -o data/raw_refs/supp/supp.zip "https://www.ebi.ac.uk/europepmc/webservices/rest/$pmc/supplementaryFiles"; unzip -o -q data/raw_refs/supp/supp.zip -d data/raw_refs/supp; }
  pin_files=("$genomic_fasta" "$templates_xlsx")
fi
###################################### pin
pins=configs/refs.sha256; touch "$pins"
for f in "${pin_files[@]}"; do
  want=$(awk -v f="$f" '$2==f{print $1}' "$pins"); got=$(sha256sum "$f" | cut -d" " -f1)
  if [ -z "$want" ]; then echo "$got  $f" >> "$pins"; kv_log "pinned $f in $pins -- commit it"
  elif [ "$want" != "$got" ]; then kv_log "$f does not match $pins ($got vs $want)"; exit 1
  else kv_log "$f matches $pins"; fi
done
###################################### build
rm -f "$KV_OUT"/refs/{TRAC_WT.fa,TRAC_KI.fa,CAR_insert.fa,design.json} "$KV_OUT"/refs/alpine/{ref.fa,config.tsv}
python3 src/build_refs.py --yaml-in --params "$PARAMS" --out-dir "$KV_OUT/refs"
kv_footer
