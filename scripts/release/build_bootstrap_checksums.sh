#!/bin/bash
#
# build_bootstrap_checksums.sh - Generate bootstrap-checksums.txt for release.
#
# Plan 00104 Task 5.1 (Decision 3.C): the skill upgrade.sh self-bootstrap
# stanza fetches bootstrap-checksums.txt from the GitHub release artifact
# bundle and verifies its own sha256 against that manifest before re-execing
# into a freshly-downloaded copy. This script produces that manifest.
#
# Format (one line per artifact, matches `sha256sum` output):
#     <64-hex-sha256>  <basename>
#
# The skill upgrade.sh stanza parses with:
#     awk '/  upgrade\.sh$/ {print $1; exit}' bootstrap-checksums.txt
#
# Usage:
#     scripts/build/build_bootstrap_checksums.sh <output-file> <artifact> [<artifact>...]
#
# Each <artifact> must be an existing readable regular file. Output is
# written atomically (tmp + mv) so a partial run never leaves a half-written
# manifest behind. Exits non-zero on any failure — release pipeline must
# abort rather than ship an incomplete or empty manifest.

set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <output-file> <artifact> [<artifact>...]" >&2
    echo "" >&2
    echo "Generates bootstrap-checksums.txt for the GitHub release bundle." >&2
    exit 1
fi

output_file="$1"
shift

if command -v sha256sum > /dev/null; then
    sha256_cmd="sha256sum"
elif command -v shasum > /dev/null; then
    sha256_cmd="shasum -a 256"
else
    echo "Error: neither sha256sum nor shasum is available — cannot build manifest" >&2
    exit 1
fi

tmp_out="$(mktemp)"
trap 'rm -f "$tmp_out"' EXIT

for artifact in "$@"; do
    if [ ! -f "$artifact" ]; then
        echo "Error: artifact not found or not a regular file: $artifact" >&2
        exit 1
    fi
    if [ ! -r "$artifact" ]; then
        echo "Error: artifact not readable: $artifact" >&2
        exit 1
    fi
    sha="$($sha256_cmd "$artifact" | awk '{print $1}')"
    base="$(basename "$artifact")"
    printf '%s  %s\n' "$sha" "$base" >> "$tmp_out"
done

if [ ! -s "$tmp_out" ]; then
    echo "Error: refusing to write empty manifest to $output_file" >&2
    exit 1
fi

mv "$tmp_out" "$output_file"
trap - EXIT

echo "Wrote $output_file:"
cat "$output_file"
