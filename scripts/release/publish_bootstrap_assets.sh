#!/bin/bash
#
# publish_bootstrap_assets.sh - Build and attach the self-bootstrap bundle to
# a GitHub release.
#
# Plan 00362 Task 1.1: every skill wrapper that self-bootstraps
# (daemon-cli.sh, health-check.sh, init-handlers.sh) downloads
# bootstrap-checksums.txt from releases/latest/download/ and looks itself up
# in it. A release published without these assets 404s every wrapper on
# every client install (v3.62.1 did exactly that: the followed procedure ran
# `gh release create` with no artifacts). This script is the single release
# step that stages the scripts, builds the manifest deterministically, uploads
# them, and reads the release back to prove they landed.
#
# Usage:
#     scripts/release/publish_bootstrap_assets.sh vX.Y.Z [--build-only]
#
# Environment:
#     HOOKS_DAEMON_RELEASE_ARTIFACTS_DIR  staging dir (default untracked/release-artifacts)
#     HOOKS_DAEMON_GH_BIN                 gh executable (default: gh on PATH)
#     HOOKS_DAEMON_SKILL_SCRIPTS_DIR      skill scripts to bundle (default: this
#                                         checkout's src/.../skills/hooks-daemon/scripts).
#                                         Point it at a checkout of the tag to
#                                         attach tag-exact bytes to an already
#                                         published release.
#
# --build-only stages and builds without touching gh, for tests and for
# inspecting the bundle before a release exists.
#
# Exits non-zero on any failure — the release pipeline must abort rather
# than publish a release whose wrappers cannot bootstrap.

set -euo pipefail

usage() {
    echo "Usage: $0 vX.Y.Z [--build-only]" >&2
    echo "" >&2
    echo "Builds bootstrap-checksums.txt plus the skill scripts it covers and" >&2
    echo "attaches them to the GitHub release for the given tag." >&2
    exit 1
}

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    usage
fi

tag="$1"
build_only=0
if [ "$#" -eq 2 ]; then
    if [ "$2" = "--build-only" ]; then
        build_only=1
    else
        usage
    fi
fi

if [[ ! "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$ ]]; then
    echo "Error: tag must look like v3.62.1 (got: $tag)" >&2
    exit 1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
skill_scripts_dir="${HOOKS_DAEMON_SKILL_SCRIPTS_DIR:-$repo_root/src/claude_code_hooks_daemon/skills/hooks-daemon/scripts}"
if [ ! -d "$skill_scripts_dir" ]; then
    echo "Error: skill scripts dir not found: $skill_scripts_dir" >&2
    exit 1
fi
artifacts_dir="${HOOKS_DAEMON_RELEASE_ARTIFACTS_DIR:-$repo_root/untracked/release-artifacts}"
gh_bin="${HOOKS_DAEMON_GH_BIN:-gh}"
stanza_marker="# === SELF-BOOTSTRAP BEGIN"

# Fixed, explicit order so two builds of the same tree are byte-identical.
# upgrade.sh no longer self-bootstraps (Plan 00109) but stays bundled for
# cross-symmetry with the three that do — see RELEASING.md Step 14.
bundled_scripts=(upgrade.sh daemon-cli.sh health-check.sh init-handlers.sh)

# Self-check: every script in the skill tree that carries the stanza must be
# in the bundle. A new self-bootstrapping script that is not listed here
# would ship a manifest with no entry for it, and every client running it
# would abort with "has no entry for <name>".
for candidate in "$skill_scripts_dir"/*.sh; do
    name="$(basename "$candidate")"
    if ! grep -qF "$stanza_marker" "$candidate"; then
        continue
    fi
    listed=0
    for bundled in "${bundled_scripts[@]}"; do
        if [ "$bundled" = "$name" ]; then
            listed=1
        fi
    done
    if [ "$listed" -eq 0 ]; then
        echo "Error: $name carries a self-bootstrap stanza but is not in the release bundle." >&2
        echo "Add it to bundled_scripts in $0 — a manifest without it breaks every client running it." >&2
        exit 1
    fi
done

mkdir -p "$artifacts_dir"

staged=()
for name in "${bundled_scripts[@]}"; do
    src="$skill_scripts_dir/$name"
    if [ ! -f "$src" ]; then
        echo "Error: bundled script missing from skill tree: $src" >&2
        exit 1
    fi
    cp "$src" "$artifacts_dir/$name"
    staged+=("$artifacts_dir/$name")
done

manifest="$artifacts_dir/bootstrap-checksums.txt"
"$repo_root/scripts/release/build_bootstrap_checksums.sh" "$manifest" "${staged[@]}"

if [ "$build_only" -eq 1 ]; then
    echo "Built bootstrap bundle in $artifacts_dir (upload skipped: --build-only)"
    exit 0
fi

assets=("${staged[@]}" "$manifest")

echo "Uploading ${#assets[@]} assets to release $tag..."
"$gh_bin" release upload "$tag" "${assets[@]}" --clobber

# Read the release back: gh's exit code says the request succeeded, not that
# every asset is now attached under the name each wrapper will fetch.
published="$("$gh_bin" release view "$tag" --json assets --jq '.assets[].name')"
missing=0
for asset in "${assets[@]}"; do
    name="$(basename "$asset")"
    if ! grep -qxF "$name" <<< "$published"; then
        echo "Error: release $tag does not list $name after upload" >&2
        missing=1
    fi
done
if [ "$missing" -ne 0 ]; then
    echo "Release $tag is missing bootstrap assets — every client wrapper will abort. Re-run this step." >&2
    exit 1
fi

echo "Release $tag carries all ${#assets[@]} bootstrap assets:"
printf '  %s\n' "${assets[@]##*/}"
