#!/bin/bash
###################################### dependencies
source "$(dirname "$0")/common.sh"; cd "$KV_ROOT"
###################################### parameters
PARAMS="$KV_OUT/inputs/params.yaml"
eval "$(python3 -I - "$PARAMS" <<'PY'
import shlex, sys, yaml
c = yaml.safe_load(open(sys.argv[1]))
for k in ("region", "pmc"): print(f"{k}={shlex.quote(str(c['refs'][k]))}")
for k in ("genomic_fasta", "templates_xlsx"): print(f"{k}={shlex.quote(str(c['build_refs'][k]))}")
PY
)"
###################################### download (cache shared by all analyses)
mkdir -p "$(dirname "$genomic_fasta")" data/raw_refs/supp
[ -s "$genomic_fasta" ] || { kv_log "hg38 $region"; curl -sf "https://rest.ensembl.org/sequence/region/human/$region?content-type=text/x-fasta" > "$genomic_fasta.tmp"; mv "$genomic_fasta.tmp" "$genomic_fasta"; }
[ -s "$templates_xlsx" ] || { kv_log "supplements $pmc"; curl -sfL -o data/raw_refs/supp/supp.zip "https://www.ebi.ac.uk/europepmc/webservices/rest/$pmc/supplementaryFiles"; unzip -o -q data/raw_refs/supp/supp.zip -d data/raw_refs/supp; }
###################################### pin
pins=configs/refs.sha256; touch "$pins"
for f in "$genomic_fasta" "$templates_xlsx"; do
  want=$(awk -v f="$f" '$2==f{print $1}' "$pins"); got=$(sha256sum "$f" | cut -d" " -f1)
  if [ -z "$want" ]; then echo "$got  $f" >> "$pins"; kv_log "pinned $f in $pins -- commit it"
  elif [ "$want" != "$got" ]; then kv_log "$f does not match $pins ($got vs $want)"; exit 1
  else kv_log "$f matches $pins"; fi
done
###################################### build
python3 src/build_refs.py --yaml-in --params "$PARAMS" --out-dir "$KV_OUT/refs"
kv_footer
