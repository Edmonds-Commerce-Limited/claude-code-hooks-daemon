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
        gnupg \
        apt-transport-https \
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
# Official Google apt repository
# ================================================================
RUN wget -qO- https://dl-ssl.google.com/linux/linux_signing_key.pub | \
    gpg --dearmor -o /usr/share/keyrings/dart.gpg && \
    echo 'deb [signed-by=/usr/share/keyrings/dart.gpg arch=amd64] https://storage.googleapis.com/download.dartlang.org/linux/debian stable main' \
        > /etc/apt/sources.list.d/dart_stable.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends dart && \
    rm -rf /var/lib/apt/lists/*

ENV PATH="/usr/lib/dart/bin:${PATH}"

# ================================================================
# Verify installations
# ================================================================
RUN go version && ruby --version && php --version && dart --version && tmux -V && \
    git filter-repo --version
