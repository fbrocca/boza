#!/usr/bin/env bash
# Rebuild the map data from the minutes PDFs.
#   tools/build.sh            extract + build (uses cached geocodes)
#   tools/build.sh --geocode  also look up new parcels/addresses (network)
# Needs pdftotext (poppler-utils) and python3.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"
data="$root/data"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

mkdir -p "$work/txt"
for pdf in "$root"/minutes/*.pdf; do
  pdftotext -layout "$pdf" "$work/txt/$(basename "${pdf%.pdf}").txt"
done
python3 -I "$here/extract_cases.py" "$work/txt" > "$data/cases.json"
if [[ "${1:-}" == "--geocode" ]]; then
  python3 -I "$here/parcels.py" "$data/cases.json" "$data/parcels.json"
  python3 -I "$here/geocode.py" "$data/cases.json" "$data/geocode-cache.json"
fi
python3 -I "$here/build_data.py" "$data/cases.json" "$data"
