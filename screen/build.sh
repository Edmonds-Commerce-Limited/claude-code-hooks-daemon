#!/bin/bash
# Build the static hooks-screen binary (Plan 00538 Phase 2).
#
# hooks-screen depends on ONE crate, vt100, vendored under screen/vendor/
# (owner ruling, Plan 00538; see screen/VENDORED.md). The build is fully
# offline and locked: screen/.cargo/config.toml replaces crates-io with the
# vendored source, so no network is touched. The relay (relay/build.sh) stays
# std-only plain rustc. The output lands under untracked/ and is NEVER
# committed.
#
# Usage: bash screen/build.sh
#   CARGO=<path>           override cargo (default ~/.cargo/bin/cargo)
#   SCREEN_TARGET=<triple> override the target (default x86_64-unknown-linux-musl)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CARGO="${CARGO:-$HOME/.cargo/bin/cargo}"
TARGET="${SCREEN_TARGET:-x86_64-unknown-linux-musl}"
SCREEN_DIR="$REPO_ROOT/screen"
OUT_DIR="$REPO_ROOT/untracked/screen-build"
TARGET_DIR="$OUT_DIR/cargo-target"
OUT="$OUT_DIR/hooks-screen-$TARGET"

mkdir -p "$OUT_DIR"

# Warnings are denied for our crate only, through [lints.rust] in
# screen/Cargo.toml; vendored crates are built with cap-lints.
# cargo reads .cargo/config.toml relative to the CURRENT directory, so build
# from inside screen/ or the vendored-source replacement is not applied.
cd "$SCREEN_DIR"
"$CARGO" build --release --offline --locked --target "$TARGET" \
    --target-dir "$TARGET_DIR"

cp "$TARGET_DIR/$TARGET/release/hooks-screen" "$OUT"
strip "$OUT"

if readelf -l "$OUT" | grep -q "INTERP"; then
    echo "ERROR: $OUT is not statically linked (has an ELF interpreter)" >&2
    exit 1
fi

# Content stamp: a hash of everything that goes into the binary, stable across
# git checkouts.
(
    find src vendor Cargo.toml Cargo.lock .cargo -type f | LC_ALL=C sort | xargs sha256sum
) | sha256sum | cut -d ' ' -f 1 >"$OUT.source-sha256"

echo "built:         $OUT"
echo "target:        $TARGET"
echo "stripped size: $(stat -c %s "$OUT") bytes"
