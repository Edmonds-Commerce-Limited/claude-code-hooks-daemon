#!/bin/bash
#
# python_fingerprint.sh - Compute the Python-environment fingerprint for venv keying
#
# Plan 00099: venvs are keyed by a fingerprint derived from the target Python
# interpreter so that concurrent containers from the same image share one venv
# while distinct Pythons (pyenv vs distro, different minor versions, different
# arches) get distinct venvs.
#
# Plan 00100 Task 3.0.5: when a project root is provided (positional $2 or the
# HOOKS_DAEMON_ROOT_DIR env var), a filesystem-safe slug is prepended so the
# same image viewed from two different mount points (e.g. host vs container)
# gets distinct venvs. Without a root, the bare ``py{MM}-{hash}`` form is
# preserved for backwards compatibility.
#
# This bash helper DOES NOT re-implement the MD5 logic. It invokes the target
# Python and runs the same formula as the Python-side implementation in
# src/claude_code_hooks_daemon/daemon/paths.py::python_venv_fingerprint().
# There is therefore no dual implementation to drift.
#
# Usage:
#   source "$(dirname "$0")/python_fingerprint.sh"
#   fp="$(python_venv_fingerprint)"                                 # bare fingerprint
#   fp="$(python_venv_fingerprint /usr/bin/python3.11)"              # explicit interpreter
#   fp="$(python_venv_fingerprint python3 /workspace)"               # slug-prefixed
#   HOOKS_DAEMON_ROOT_DIR=/workspace fp="$(python_venv_fingerprint)" # slug from env
#

# python_venv_fingerprint() - Compute fingerprint via the target Python itself
#
# Args:
#   $1 - python interpreter to fingerprint (optional, default: python3)
#   $2 - project root for slug prefix (optional; falls back to
#        $HOOKS_DAEMON_ROOT_DIR; absent = bare fingerprint, no slug)
#
# Returns:
#   Prints the fingerprint to stdout. With no root: ``py{MAJOR}{MINOR}-{8-hex-chars}``.
#   With a root: ``{slug}-py{MAJOR}{MINOR}-{8-hex-chars}``.
#   Exit code 0 on success. If the interpreter is missing or errors, the
#   invocation's own error message propagates to stderr and the exit code
#   from Python (or shell ENOENT=127) is returned to the caller.
python_venv_fingerprint() {
    local python_bin="${1:-python3}"
    local root="${2:-${HOOKS_DAEMON_ROOT_DIR:-}}"

    "$python_bin" -c '
import hashlib
import platform
import sys
from pathlib import Path

_SLUG_SAFE_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
_SLUG_MAX_LEN = 40
_SLUG_TRUNCATED_PREFIX_LEN = 36
_SLUG_TRUNCATED_HASH_LEN = 4


def _project_path_slug(root):
    abs_path = str(Path(root).resolve())
    stripped = abs_path.lstrip("/")
    if not stripped:
        stripped = "root"
    replaced = stripped.replace("/", "_")
    safe = "".join(ch for ch in replaced if ch in _SLUG_SAFE_CHARS)
    if not safe:
        safe = "root"
    if len(safe) > _SLUG_MAX_LEN:
        suffix = hashlib.md5(
            abs_path.encode("utf-8"), usedforsecurity=False
        ).hexdigest()[:_SLUG_TRUNCATED_HASH_LEN]
        safe = safe[:_SLUG_TRUNCATED_PREFIX_LEN] + "-" + suffix
    return safe


root = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None
parts = f"{sys.version}|{sys.base_prefix}|{platform.machine()}"
digest = hashlib.md5(parts.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
py_part = f"py{sys.version_info.major}{sys.version_info.minor}-{digest}"
if root:
    print(f"{_project_path_slug(root)}-{py_part}")
else:
    print(py_part)
' "$root"
}
