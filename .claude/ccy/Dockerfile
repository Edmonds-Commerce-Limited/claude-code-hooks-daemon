FROM claude-yolo:latest

# ================================================================
# Multi-language lint tools for Claude Code Hooks Daemon
#
# Required by LintOnEdit handler (PostToolUse) acceptance tests:
#   - Go:   go vet {file}
#   - Ruby: ruby -c {file}
#   - PHP:  php -l {file}
#   - Dart: dart analyze {file}
#
# Skipped (too large for container):
#   - Rust:   rustc nightly -Z parse-only (~800MB) → acceptance test skips
#   - Kotlin: kotlinc + JDK (~400MB)              → acceptance test skips
#   - Swift:  swiftc ~2GB                          → acceptance test skips
#
# Python linters (ruff) already in base image.
# ESLint already available via npm in base image.
# shellcheck added explicitly (NOT in base image).
# ================================================================

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        golang-go \
        ruby \
        php-cli \
        shellcheck \
        wget \
        tmux \
        git-filter-repo \
    && rm -rf /var/lib/apt/lists/*

# tmux: required for Plan 00135 (event-driven send-keys injection) spikes/feature —
# lets the container drive a real tmux session + Claude TUI for capture-pane/key-table
# experiments and (eventually) a CI tmux test harness for the injector.

# git-filter-repo: the supported tool for rewriting published history when a
# secret-word-list term reaches a commit. Baked into the image rather than
# pip-installed on demand because the alternatives are all worse here: the venv
# it used to live in (untracked/fr-venv) is gitignored and vanishes with the
# container, and `pip install --break-system-packages` is blocked by the daemon's
# own handler. Debian ships it, so apt is the clean route.
# Consumed by untracked/rewrite/refresh.sh, which resolves it from PATH.

# ================================================================
# Dart SDK - dart analyze
# Official SDK zip (the apt repo is amd64-only, so it fails on arm64 hosts)
# ================================================================
RUN set -eux; \
    case "$(dpkg --print-architecture)" in \
        amd64) dart_arch=x64 ;; \
        arm64) dart_arch=arm64 ;; \
        *) echo "unsupported architecture for Dart SDK" >&2; exit 1 ;; \
    esac; \
    apt-get update; \
    apt-get install -y --no-install-recommends unzip; \
    rm -rf /var/lib/apt/lists/*; \
    wget -qO /tmp/dart.zip "https://storage.googleapis.com/dart-archive/channels/stable/release/latest/sdk/dartsdk-linux-${dart_arch}-release.zip"; \
    unzip -q /tmp/dart.zip -d /usr/lib; \
    mv /usr/lib/dart-sdk /usr/lib/dart; \
    rm /tmp/dart.zip

ENV PATH="/usr/lib/dart/bin:${PATH}"

# ================================================================
# Rust toolchain - Plan 00290 (rust socket relay forwarder)
#
# Stable + minimal profile + the host-architecture musl target (x86_64 or
# aarch64, matching the relay target the daemon picks): builds the static relay
# binary (std-only, no crates). gcc provides the host linker rustc needs;
# musl-tools provides musl-gcc for the fully static musl target. This
# supersedes the old "Rust skipped, too large" note above, which referred
# to nightly `-Z parse-only` for the LintOnEdit acceptance test — that
# test still skips; this toolchain exists to BUILD the relay, not lint.
# ================================================================
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends gcc musl-tools && \
    rm -rf /var/lib/apt/lists/*

RUN wget -qO /tmp/rustup-init.sh https://sh.rustup.rs && \
    sh /tmp/rustup-init.sh -y --profile minimal --default-toolchain stable \
        --target "$(uname -m)-unknown-linux-musl" && \
    rm /tmp/rustup-init.sh

ENV PATH="/root/.cargo/bin:${PATH}"

# ================================================================
# Verify installations
# ================================================================
RUN go version && ruby --version && php --version && dart --version && tmux -V && \
    git filter-repo --version && \
    rustc --version && cargo --version && musl-gcc --version
