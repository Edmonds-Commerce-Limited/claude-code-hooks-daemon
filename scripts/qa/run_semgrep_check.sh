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
# semgrep is a dev-only tool run from uv's isolated tool environment (see the
# resolution block below); the client installer never installs it.
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
# semgrep is NOT in the project venv: its mcp and opentelemetry pins held the
# project lock below patched versions (Plan 00607). It runs from uv's isolated
# tool environment at the one exact version in scripts/qa/semgrep-version.txt,
# the single place to bump it. uv caches that environment, so a warmed machine
# runs offline. The interpreter is pinned beside it in semgrep-python.txt:
# semgrep 1.185.0's semgrep-core is only installed for Python 3.13 under uv, so
# an unpinned run fails on whichever other interpreter uv happens to pick.
SEMGREP_VERSION_FILE="${QA_SEMGREP_VERSION_FILE:-${SCRIPT_DIR}/semgrep-version.txt}"
SEMGREP_PYTHON_FILE="${QA_SEMGREP_PYTHON_FILE:-${SCRIPT_DIR}/semgrep-python.txt}"
UV_BIN="${QA_SEMGREP_UV:-uv}"
SEMGREP_VERSION=""
if [ -f "${SEMGREP_VERSION_FILE}" ]; then
    SEMGREP_VERSION="$(tr -d '[:space:]' < "${SEMGREP_VERSION_FILE}")"
fi
SEMGREP_PYTHON=""
if [ -f "${SEMGREP_PYTHON_FILE}" ]; then
    SEMGREP_PYTHON="$(tr -d '[:space:]' < "${SEMGREP_PYTHON_FILE}")"
fi

mkdir -p "${OUTPUT_DIR}"

# Fail closed unless the pinned semgrep is obtained AND reports that version.
SEMGREP_PROBE=""
SEMGREP_PROBE_ERROR="semgrep not installed"
if [ -z "${SEMGREP_VERSION}" ]; then
    SEMGREP_PROBE_ERROR="no semgrep version pinned in ${SEMGREP_VERSION_FILE}"
elif [ -z "${SEMGREP_PYTHON}" ]; then
    SEMGREP_PROBE_ERROR="no semgrep python pinned in ${SEMGREP_PYTHON_FILE}"
elif ! type -P "${UV_BIN}" > /dev/null; then
    SEMGREP_PROBE_ERROR="uv not found, so the pinned semgrep cannot be obtained"
else
    SEMGREP=("${UV_BIN}" tool run --quiet --python "${SEMGREP_PYTHON}" --from "semgrep==${SEMGREP_VERSION}" semgrep)
    PROBE_LOG="${OUTPUT_DIR}/semgrep-probe.log"
    if SEMGREP_PROBE="$("${SEMGREP[@]}" --version 2> "${PROBE_LOG}")" \
        && [ "$(printf '%s' "${SEMGREP_PROBE}" | tail -n 1)" = "${SEMGREP_VERSION}" ]; then
        SEMGREP_PROBE_ERROR=""
    else
        SEMGREP_PROBE_ERROR="semgrep ${SEMGREP_VERSION} could not be obtained from uv (see ${PROBE_LOG})"
    fi
fi

if [ -n "${SEMGREP_PROBE_ERROR}" ]; then
    # FAIL LOUD: a missing linter that silently passes is worse than no check.
    # It reports green while examining nothing, which is the exact failure this
    # project's DBF standard exists to prevent.
    echo "ERROR: ${SEMGREP_PROBE_ERROR}" >&2
    echo "Install uv (https://docs.astral.sh/uv/) and run once with network access to warm its cache; the version is pinned in ${SEMGREP_VERSION_FILE}" >&2
    "${VENV_PYTHON}" -c '
import json, sys
error = "semgrep unavailable: " + sys.argv[1]
print(json.dumps({"tool": "semgrep", "summary": {"passed": False, "total_violations": 0, "error": error}, "violations": []}))
' "${SEMGREP_PROBE_ERROR}" > "${OUTPUT_FILE}"
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
"${SEMGREP[@]}" scan \
    --config "${RULES_DIR}" \
    --metrics=off \
    --disable-version-check \
    --quiet \
    --json \
    --timeout "${RULE_TIMEOUT_SECONDS}" \
    --output "${RAW_OUTPUT}" \
    "${SCAN_TARGETS[@]}"
SEMGREP_EXIT=$?

# Rules that read the TEST suite live in their own directory and run over the
# test files named one by one: semgrep skips a whole `tests/` directory target
# by default, and widening the source scan to it would also run every source
# rule over the fixtures that plant violations on purpose.
# A run that overrides the source rules dir is a planted-rule run and scans
# nothing else unless it also names a test rules dir.
if [ -n "${QA_SEMGREP_RULES_DIR:-}" ]; then
    TEST_RULES_DIR="${QA_SEMGREP_TEST_RULES_DIR:-}"
else
    TEST_RULES_DIR="${QA_SEMGREP_TEST_RULES_DIR:-${SCRIPT_DIR}/semgrep-tests}"
fi
TEST_RAW_OUTPUT="${OUTPUT_DIR}/semgrep-tests-raw.json"
rm -f "${TEST_RAW_OUTPUT}"
if [ "${SEMGREP_EXIT}" -eq 0 ] && [ -n "${TEST_RULES_DIR}" ] && [ -d "${TEST_RULES_DIR}" ]; then
    # `mapfile` is bash 4 only; macOS ships bash 3.2, so read line by line.
    TEST_FILES=()
    while IFS= read -r TEST_FILE; do
        TEST_FILES+=("${TEST_FILE}")
    done < <(find "${QA_SEMGREP_TEST_ROOT:-${REPO_ROOT}/tests}" -name 'test_*.py' -not -path '*/fixtures/*')
    if [ "${#TEST_FILES[@]}" -gt 0 ]; then
        "${SEMGREP[@]}" scan \
            --config "${TEST_RULES_DIR}" \
            --metrics=off \
            --disable-version-check \
            --quiet \
            --json \
            --timeout "${RULE_TIMEOUT_SECONDS}" \
            --output "${TEST_RAW_OUTPUT}" \
            "${TEST_FILES[@]}"
        SEMGREP_EXIT=$?
    fi
fi

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
"${VENV_PYTHON}" - "${RAW_OUTPUT}" "${OUTPUT_FILE}" "${TEST_RAW_OUTPUT}" <<'PYEOF'
import json
import sys
from pathlib import Path

raw = json.loads(Path(sys.argv[1]).read_text())
test_raw_path = Path(sys.argv[3])
if test_raw_path.exists():
    test_raw = json.loads(test_raw_path.read_text())
    raw["results"] = [*raw.get("results", []), *test_raw.get("results", [])]
    raw["errors"] = [*raw.get("errors", []), *test_raw.get("errors", [])]
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
