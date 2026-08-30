#!/bin/bash
# Build the static hooks-relay binary (Plan 00290, Task 3.3).
#
# Constraints (DESIGN-socket-relay.md section 3.1): std only, zero crates, no
# cargo — a crate-less single source file needs nothing but plain rustc with
# the musl target, which yields a fully static binary. The output lands under
# untracked/ and is NEVER committed: the repo's auditable surface stays 100%
# source (relay/hooks_relay.rs + this script).
#
# Usage: bash relay/build.sh
#   RUSTC=<path>          override the compiler (default ~/.cargo/bin/rustc)
#   RELAY_TARGET=<triple> override the target (default x86_64-unknown-linux-musl)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUSTC="${RUSTC:-$HOME/.cargo/bin/rustc}"
TARGET="${RELAY_TARGET:-x86_64-unknown-linux-musl}"
SRC="$REPO_ROOT/relay/hooks_relay.rs"
OUT_DIR="$REPO_ROOT/untracked/relay-build"
OUT="$OUT_DIR/hooks-relay-$TARGET"

mkdir -p "$OUT_DIR"

# -O for release codegen; -C strip=symbols does the primary strip at link
# time. Deny all rustc warnings so the committed source stays lint-clean
# without any suppression attributes in the file.
"$RUSTC" --edition 2021 -O -C strip=symbols -D warnings \
    --target "$TARGET" "$SRC" -o "$OUT"

# Belt-and-braces strip (removes any residual section rustc's strip leaves);
# a no-op on an already fully stripped binary.
strip "$OUT"

# Confirm the binary is genuinely static: no PT_INTERP program header means
# no dynamic loader is involved (readelf is in binutils, present wherever
# strip is; `file` is not guaranteed on minimal containers).
if readelf -l "$OUT" | grep -q "INTERP"; then
    echo "ERROR: $OUT is not statically linked (has an ELF interpreter)" >&2
    exit 1
fi

SIZE_BYTES="$(stat -c %s "$OUT")"
echo "built:         $OUT"
echo "target:        $TARGET"
echo "stripped size: $SIZE_BYTES bytes"
sha256sum "$OUT"
