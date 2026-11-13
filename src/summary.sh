#!/bin/bash
###################################### dependencies
source "$(dirname "$0")/common.sh"
###################################### summary
python3 "$KV_ROOT/src/summarize.py" --analysis-dir "$KV_OUT"
kv_footer
