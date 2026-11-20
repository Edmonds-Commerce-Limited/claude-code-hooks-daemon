#!/usr/bin/env bash
# Run a corpus through main, the parent tip and the branch, in every mode.
set -euo pipefail
R="$(cd "$(dirname "$0")" && pwd)"
B=/workspace/.claude/worktrees/agent-a13d7c8504105d4c9-aeae03b4
M=/workspace/untracked/scratch/p623rev2-mainwt
PA="$R/parentwt"
PY=/workspace/.venv/bin/python
CORPUS="${1:-commands.txt}"
TAG="${2:-c1}"
export CORPUS
cd "$R"
one() { # name tree capmode idx [rootcwd]
  local out="$R/out-$TAG-$1-$3-$4.json"
  DAEMON_CWD_ROOT="${5:-}" PYTHONPATH="$2/src:$2" timeout 900 "$PY" probe.py "$1" "$3" "$4" "$out" 2> "$R/err-$TAG-$1-$3-$4.txt"
}
one branch "$B" cap built
one branch "$B" lifted built
one branch "$B" lifted cold
one branch "$B" cap cold
one parent "$PA" cap built
one parent "$PA" lifted built
one main "$M" lifted cold 1
