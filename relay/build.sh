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

# No separate `strip` pass: -C strip=symbols above already strips, and a second
# binutils strip failed intermittently on a CI runner ("[.rodata]: invalid
# operation"), aborting the build. The checks below verify the binary instead.

# Confirm the binary is genuinely static: no PT_INTERP program header means
# no dynamic loader is involved (readelf is in binutils; `file` is not
# guaranteed on minimal containers).
if readelf -l "$OUT" | grep -q "INTERP"; then
    echo "ERROR: $OUT is not statically linked (has an ELF interpreter)" >&2
    exit 1
fi

# Confirm the binary runs. The relay has no --version, so invoke it with no
# socket path: it must reject that with its usage exit code (13) without
# touching a daemon or stdin. Only possible when the target is this host's
# architecture (a cross-built binary cannot execute here).
if [[ "$TARGET" == "$(uname -m)-"* ]]; then
    if RUN_OUTPUT="$("$OUT" 2>&1 </dev/null)"; then
        RUN_STATUS=0
    else
        RUN_STATUS=$?
    fi
    if [[ "$RUN_STATUS" -ne 13 ]]; then
        echo "ERROR: $OUT did not run (usage self-check exited $RUN_STATUS, expected 13): $RUN_OUTPUT" >&2
        exit 1
    fi
fi

# Content stamp the relay tests compare against relay/hooks_relay.rs: mtime
# moves on every git checkout, a hash of the source does not.
sha256sum "$SRC" | cut -d ' ' -f 1 >"$OUT.source-sha256"

SIZE_BYTES="$(stat -c %s "$OUT")"
echo "built:         $OUT"
echo "target:        $TARGET"
echo "stripped size: $SIZE_BYTES bytes"
sha256sum "$OUT"
