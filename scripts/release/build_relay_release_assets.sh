#!/bin/bash
#
# build_relay_release_assets.sh - Build the release-bundle relay binary + SHA256SUMS.
#
# Plan 00290 Phase 5, Task 5.1: a release publishes the static relay binary
# plus a sha256 manifest as GitHub release assets, so a client that CHOOSES
# `daemon.transport.relay_source: download` can fetch and digest-verify it
# (install/relay_deploy.py::deploy_relay_from_download). The source
# (relay/hooks_relay.rs + relay/build.sh) ships in the repo regardless — this
# script never replaces that, it only produces the CONVENIENCE artifact for
# clients who choose not to build.
#
# Usage:
#   scripts/release/build_relay_release_assets.sh [<output-dir>]
#
# Output (in <output-dir>, default untracked/release-artifacts/):
#   hooks-relay-x86_64-unknown-linux-musl
#   SHA256SUMS
#
# Exits non-zero on any build/checksum failure — the release pipeline must
# abort rather than publish a missing or unverifiable relay asset.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUTPUT_DIR="${1:-$REPO_ROOT/untracked/release-artifacts}"
TARGET="${RELAY_TARGET:-x86_64-unknown-linux-musl}"
ASSET_NAME="hooks-relay-$TARGET"

mkdir -p "$OUTPUT_DIR"

echo "Building relay binary ($TARGET)..."
bash "$REPO_ROOT/relay/build.sh"

BUILT="$REPO_ROOT/untracked/relay-build/$ASSET_NAME"
if [ ! -f "$BUILT" ]; then
    echo "Error: relay/build.sh reported success but output is missing: $BUILT" >&2
    exit 1
fi

cp "$BUILT" "$OUTPUT_DIR/$ASSET_NAME"
echo "Copied release asset: $OUTPUT_DIR/$ASSET_NAME"

"$REPO_ROOT/scripts/release/build_bootstrap_checksums.sh" \
    "$OUTPUT_DIR/SHA256SUMS" \
    "$OUTPUT_DIR/$ASSET_NAME"

echo "Relay release assets ready in $OUTPUT_DIR:"
ls -la "$OUTPUT_DIR/$ASSET_NAME" "$OUTPUT_DIR/SHA256SUMS"
