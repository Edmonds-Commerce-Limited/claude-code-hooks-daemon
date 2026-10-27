#!/bin/bash
# Build the static hooks-screen binary (Plan 00538 Phase 2).
#
# Same constraints as relay/build.sh: std only, zero crates, no cargo, plain
# rustc with the musl target for a fully static binary. The output lands under
# untracked/ and is NEVER committed.
#
# Usage: bash screen/build.sh
#   RUSTC=<path>          override the compiler (default ~/.cargo/bin/rustc)
#   SCREEN_TARGET=<triple> override the target (default x86_64-unknown-linux-musl)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUSTC="${RUSTC:-$HOME/.cargo/bin/rustc}"
TARGET="${SCREEN_TARGET:-x86_64-unknown-linux-musl}"
SRC="$REPO_ROOT/screen/hooks_screen.rs"
OUT_DIR="$REPO_ROOT/untracked/screen-build"
OUT="$OUT_DIR/hooks-screen-$TARGET"

mkdir -p "$OUT_DIR"

# Deny all rustc warnings so the source stays lint-clean without any
# suppression attributes in the file.
"$RUSTC" --edition 2021 -O -C strip=symbols -D warnings \
    --target "$TARGET" "$SRC" -o "$OUT"

strip "$OUT"

if readelf -l "$OUT" | grep -q "INTERP"; then
    echo "ERROR: $OUT is not statically linked (has an ELF interpreter)" >&2
    exit 1
fi

# Content stamp: a hash of the source, stable across git checkouts.
sha256sum "$SRC" | cut -d ' ' -f 1 >"$OUT.source-sha256"

echo "built:         $OUT"
echo "target:        $TARGET"
echo "stripped size: $(stat -c %s "$OUT") bytes"
