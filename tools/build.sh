#!/usr/bin/env bash
# Rebuild the map data.
#   tools/build.sh            extract + build (uses cached parcel/address lookups)
#   tools/build.sh --geocode  also look up new parcels and addresses (network)
# Run tools/fetch_minutes.py first to pull new minutes from the Town.
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
python3 -I "$here/extract_planning.py" "$root/sources" > "$data/planning.json"
python3 -I "$here/extract_design.py" "$root/sources" > "$data/design.json"
if [[ "${1:-}" == "--geocode" ]]; then
  python3 -I "$here/parcels.py" "$data/parcels.json" "$data/cases.json" "$data/planning.json" "$data/design.json"
  python3 -I "$here/geocode.py" "$data/geocode-cache.json" "$data/cases.json" "$data/planning.json" "$data/design.json"
fi
python3 -I "$here/build_data.py" "$data"
