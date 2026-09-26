#!/usr/bin/env bash
#
# Run the project's custom semgrep rules (Plan 00231).
#
# Ruff has no plugin mechanism, so project-specific "ban this code shape" rules
# used to mean one bespoke AST scanner per rule — a few hundred lines of Python
# plus its own test suite, catching a fraction of the spellings. Benchmarked
# against an 11-shape probe of the bounded-read defect class, the hand-written
# checker caught 1 and the equivalent semgrep rules caught 9.
#
# Rules live in scripts/qa/semgrep/*.yaml. Add a rule file there and it is
# picked up automatically — no wiring required.
#
# semgrep is a DEV dependency (pyproject [dev]); the client installer runs
# `uv pip install -e <dir>` with no [dev] extra, so it never ships to a client.
#
# Runs fully offline: local --config, metrics disabled, no registry fetch.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# The QA_SEMGREP_* overrides exist so tests/unit/qa/test_run_semgrep_check.py
# can drive this exact wrapper against a planted rule and fixture without
# touching the real rules or the real untracked/qa/ output. Unset, they change
# nothing.
RULES_DIR="${QA_SEMGREP_RULES_DIR:-${SCRIPT_DIR}/semgrep}"
OUTPUT_DIR="${QA_SEMGREP_OUTPUT_DIR:-${REPO_ROOT}/untracked/qa}"
OUTPUT_FILE="${OUTPUT_DIR}/semgrep.json"
# Per rule, per file. Semgrep's default of 5 s is too tight: the taint rule
# bounded-intent-unbounded-read-deferred needs about 2.2 s on daemon/cli.py
# with the machine idle, and timed out there under the parallel QA run. A
# timeout now FAILS the gate (00466 N21), so a budget this close to the real
# cost would make the gate flaky instead of blind. 30 s leaves headroom.
RULE_TIMEOUT_SECONDS="${QA_SEMGREP_TIMEOUT:-30}"

# shellcheck source=/dev/null
source "${REPO_ROOT}/scripts/lib/resolve_venv.sh"
VENV_PYTHON="$(resolve_venv_python "${REPO_ROOT}")"
SEMGREP="$(dirname "${VENV_PYTHON}")/semgrep"

mkdir -p "${OUTPUT_DIR}"

if [ ! -x "${SEMGREP}" ]; then
    # FAIL LOUD: a missing linter that silently passes is worse than no check.
    # It reports green while examining nothing, which is the exact failure this
    # project's DBF standard exists to prevent.
    echo "ERROR: semgrep not found at ${SEMGREP}" >&2
    echo "Install dev dependencies:  uv pip install -e '.[dev]' --python ${VENV_PYTHON}" >&2
    printf '{"tool":"semgrep","summary":{"passed":false,"total_violations":0,"error":"semgrep not installed"},"violations":[]}\n' \
        > "${OUTPUT_FILE}"
    exit 1
fi

# Trees whose Python runs against files with no upper bound, mirroring the
# scan roots the rules were validated against.
SCAN_TARGETS=("${REPO_ROOT}/src" "${REPO_ROOT}/scripts")
if [ -d "${REPO_ROOT}/.claude/project-handlers" ]; then
    SCAN_TARGETS+=("${REPO_ROOT}/.claude/project-handlers")
fi
if [ -n "${QA_SEMGREP_TARGETS:-}" ]; then
    SCAN_TARGETS=("${QA_SEMGREP_TARGETS}")
fi

RAW_OUTPUT="${OUTPUT_DIR}/semgrep-raw.json"
# Removed first, so a run that writes nothing can never be graded on the
# previous run's file.
rm -f "${RAW_OUTPUT}"
"${SEMGREP}" scan \
    --config "${RULES_DIR}" \
    --metrics=off \
    --disable-version-check \
    --quiet \
    --json \
    --timeout "${RULE_TIMEOUT_SECONDS}" \
    --output "${RAW_OUTPUT}" \
    "${SCAN_TARGETS[@]}"
SEMGREP_EXIT=$?

# Without --error semgrep exits 0 whether or not it finds anything, so any
# other status means it did not complete the scan.
if [ "${SEMGREP_EXIT}" -ne 0 ] || [ ! -s "${RAW_OUTPUT}" ]; then
    echo "ERROR: semgrep did not complete the scan (exit ${SEMGREP_EXIT}); nothing was checked" >&2
    printf '{"tool":"semgrep","summary":{"passed":false,"total_violations":1,"error":"semgrep did not complete the scan (exit %s)"},"violations":[{"file":"","line":0,"rule":"semgrep-did-not-run","message":"semgrep exited %s without a complete scan"}]}\n' \
        "${SEMGREP_EXIT}" "${SEMGREP_EXIT}" > "${OUTPUT_FILE}"
    exit 1
fi

# Normalise into the shape every other QA check emits, so llm_qa.py and
# run_all.sh consume it identically.
"${VENV_PYTHON}" - "${RAW_OUTPUT}" "${OUTPUT_FILE}" <<'PYEOF'
import json
import sys
from pathlib import Path

raw = json.loads(Path(sys.argv[1]).read_text())
violations = [
    {
        "file": r.get("path", ""),
        "line": r.get("start", {}).get("line", 0),
        "rule": r.get("check_id", "").split(".")[-1],
        "message": " ".join(r.get("extra", {}).get("message", "").split()),
    }
    for r in raw.get("results", [])
]
# 00466 N21: semgrep reports a rule that timed out on a file (and every other
# failure to check something) in errors[], at level "warn", and still exits 0.
# That file was NOT checked by that rule, so any entry here fails the gate:
# reading results[] alone made a timeout indistinguishable from a clean scan.
# Each one is reported as a violation of its own, so it is counted, listed
# under the same jq hint, and never mistaken for a clean scan.
errors = [
    {
        "file": e.get("path", ""),
        "line": 0,
        "rule": (e.get("rule_id") or "").split(".")[-1],
        "error_type": e.get("type") if isinstance(e.get("type"), str) else json.dumps(e.get("type")),
        "message": "semgrep could NOT check this file with this rule: "
        + " ".join(str(e.get("message", "")).split()),
    }
    for e in raw.get("errors", [])
]
findings = violations + errors
summary = {"passed": not findings, "total_violations": len(findings)}
if errors:
    summary["error"] = (
        f"semgrep could not check {len(errors)} rule/file pair(s); a rule that "
        "times out has checked nothing, so the gate fails closed"
    )
output = {"tool": "semgrep", "summary": summary, "violations": findings}
Path(sys.argv[2]).write_text(json.dumps(output, indent=2))

if violations:
    print(f"Found {len(violations)} semgrep violations:")
    for v in violations:
        print(f"  {v['file']}:{v['line']}  [{v['rule']}]")
if errors:
    print(f"semgrep could NOT check {len(errors)} rule/file pair(s) -- the gate fails closed:")
    for e in errors:
        print(f"  {e['file'] or '(no file)'}  [{e['rule'] or '(no rule)'}]  {e['error_type']}")
if not findings:
    print("No semgrep violations found")
sys.exit(1 if findings else 0)
PYEOF
exit $?
