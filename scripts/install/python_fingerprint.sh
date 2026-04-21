#!/bin/bash
#
# python_fingerprint.sh - Compute the Python-environment fingerprint for venv keying
#
# Plan 00099: venvs are keyed by a fingerprint derived from the target Python
# interpreter so that concurrent containers from the same image share one venv
# while distinct Pythons (pyenv vs distro, different minor versions, different
# arches) get distinct venvs.
#
# This bash helper DOES NOT re-implement the MD5 logic. It invokes the target
# Python and runs the same formula as the Python-side implementation in
# src/claude_code_hooks_daemon/daemon/paths.py::python_venv_fingerprint().
# There is therefore no dual implementation to drift.
#
# Usage:
#   source "$(dirname "$0")/python_fingerprint.sh"
#   fp="$(python_venv_fingerprint)"            # uses python3 from PATH
#   fp="$(python_venv_fingerprint /usr/bin/python3.11)"
#

# python_venv_fingerprint() - Compute fingerprint via the target Python itself
#
# Args:
#   $1 - python interpreter to fingerprint (optional, default: python3)
#
# Returns:
#   Prints the fingerprint to stdout: "py{MAJOR}{MINOR}-{8-hex-chars}"
#   Exit code 0 on success. If the interpreter is missing or errors, the
#   invocation's own error message propagates to stderr and the exit code
#   from Python (or shell ENOENT=127) is returned to the caller.
python_venv_fingerprint() {
    local python_bin="${1:-python3}"

    "$python_bin" -c '
import hashlib
import platform
import sys

parts = f"{sys.version}|{sys.base_prefix}|{platform.machine()}"
digest = hashlib.md5(parts.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
print(f"py{sys.version_info.major}{sys.version_info.minor}-{digest}")
'
}
