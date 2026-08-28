#!/usr/bin/env python3
"""LLM-optimized QA runner - minimal stdout, structured JSON to file.

Runs the same QA tools as run_all.sh but produces 2 lines per tool
instead of 50+. Designed for AI coding assistants that prefer concise,
machine-parseable output with pointers to detailed JSON.

Usage:
    ./scripts/qa/llm_qa.py all              # Run every QA check in the suite
    ./scripts/qa/llm_qa.py tests lint       # Run specific tools
    ./scripts/qa/llm_qa.py --read-only all  # Summarize existing JSON only
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final, NamedTuple, TypeAlias

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts" / "qa"
QA_OUTPUT_DIR = PROJECT_ROOT / "untracked" / "qa"
VENV_PYTHON = PROJECT_ROOT / "untracked" / "venv" / "bin" / "python"

# Exit codes. 2 is deliberately skipped: the sibling run_all.sh already uses it
# for "cannot run" (venv resolver missing), and the two entry points must not
# give the same number two meanings.
EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_BUSY = 3

# Run lock (Plan 00262). Concurrent suite runs share one `tests/` tree and one
# coverage.json, so their verdicts contend and NEITHER can be trusted -- a
# contended run can fail a check that is fine and pass one that is not. Since a
# green run gates commits and releases, that turns a blocking gate into a coin
# flip with no signal that it happened.
#
# NOT in /tmp: security standard B108 -- runtime files live under the project's
# untracked dir, never a world-writable shared directory.
RUN_LOCK_NAME = ".llm_qa.lock"
_PID_PREFIX = "pid="
_UNKNOWN_PID = "unknown"
_LOCK_FILE_MODE = 0o644


def run_lock_path() -> Path:
    """Return the canonical run-lock path (never ``/tmp`` -- B108)."""
    return QA_OUTPUT_DIR / RUN_LOCK_NAME


def _open_lock_fd(path: Path | str) -> int:
    """Open (creating if needed) the lock file and return a raw descriptor.

    A raw descriptor rather than a buffered text handle: a lock is a file
    DESCRIPTOR, and ``flock`` operates on one. Using ``os.open`` also keeps the
    "held for the process lifetime" case honest -- there is no stream to leave
    unclosed, so nothing has to be excused to a linter.
    """
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    return os.open(lock_path, os.O_RDWR | os.O_CREAT, _LOCK_FILE_MODE)


def _stamp_holder(fd: int) -> None:
    """Record the holder's pid so a refusal can name it.

    A bare "already running" invites deleting the lock file, which reintroduces
    the race AND removes the signal. Naming the pid lets the reader check
    whether it is alive and decide between waiting and investigating.
    """
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, f"{_PID_PREFIX}{os.getpid()}\n".encode())


def try_acquire_run_lock(path: str) -> bool:
    """Attempt a non-blocking acquire; return whether it succeeded.

    Exposed separately from ``run_lock`` so a caller (or a test) can ask the
    question without taking ownership. On success the descriptor is deliberately
    left open for the process lifetime: the kernel releases the lock when the
    process exits, which is the whole point of using ``flock``.
    """
    fd = _open_lock_fd(path)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        # Contention is the EXPECTED answer here, not an error: another run
        # holds the lock. Only this errno means "held" -- anything else (a bad
        # path, a full disk) propagates rather than being misreported as a busy
        # suite, which would silently skip the gate.
        os.close(fd)
        return False
    _stamp_holder(fd)
    return True


def read_holder_pid(path: str) -> str:
    """Return the recorded holder pid, or a reason it could not be read.

    Diagnostic only. The refusal itself is decided by ``flock``, never by this
    file's contents -- so an unreadable lock file degrades the MESSAGE and must
    never be allowed to change the DECISION.
    """
    lock_file = Path(path)
    if not lock_file.is_file():
        return _UNKNOWN_PID
    try:
        content = lock_file.read_text(encoding="utf-8")
    except OSError as exc:
        return f"{_UNKNOWN_PID} (lock file unreadable: {exc.strerror})"
    for line in content.splitlines():
        if line.startswith(_PID_PREFIX):
            return line.split("=", 1)[1].strip()
    return _UNKNOWN_PID


def busy_message(path: str) -> str:
    """Explain the refusal well enough that nobody deletes the lock file."""
    holder = read_holder_pid(path)
    return (
        f"QA is already running (pid {holder}).\n"
        "\n"
        "Two concurrent runs share this tree and one coverage.json, so their\n"
        "verdicts contend and NEITHER can be trusted -- a contended run can\n"
        "fail a check that is fine, and pass one that is not. Refusing rather\n"
        "than producing a verdict you would have to distrust.\n"
        "\n"
        "  - Wait for that run to finish, then re-run.\n"
        "  - Inspect the run in progress with:  llm_qa.py --read-only all\n"
        f"  - If pid {holder} is genuinely dead, the lock is ALREADY released:\n"
        f"    flock drops it on process exit, so do NOT delete {path}.\n"
        "    A lock file on disk does not mean a lock is held.\n"
    )


@contextmanager
def run_lock(path: Path | str) -> Generator[None]:
    """Hold the run lock for the duration of the block.

    ``flock`` rather than a PID-file convention: the kernel drops it when the
    holder dies, INCLUDING on SIGKILL. That removes the entire stale-lock class
    instead of adding cleanup logic for it -- and a guard that could wedge the
    suite permanently would be worse than the race it prevents, because an agent
    would soon learn to delete the lock file.
    """
    fd = _open_lock_fd(path)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _stamp_holder(fd)
        yield
    finally:
        os.close(fd)


# A QA tool's parsed JSON report. Every tool writes its own schema, so the
# value type is genuinely open — but the mapping itself is not, and a bare
# ``dict`` disables checking on every summarizer that reads one.
QaReport: TypeAlias = dict[str, Any]

# Type alias for summarizer functions
Summarizer = Callable[[QaReport], str]


class ToolConfig(NamedTuple):
    """Configuration for a single QA tool."""

    command: list[str]
    json_file: str
    jq_hint: str


def _python(script: str, *args: str) -> list[str]:
    """Build command to run a Python script via the project venv.

    Extra ``args`` are appended to the invocation, so a caller writes
    ``_python("check_x.py", "--json")`` rather than concatenating a list onto
    the result.
    """
    return [str(VENV_PYTHON), str(SCRIPTS_DIR / script), *args]


def _bash(script: str) -> list[str]:
    """Build command to run a bash QA script."""
    return [str(SCRIPTS_DIR / script)]


# ── Tool registry ──────────────────────────────────────────────────
# Order matches run_all.sh for consistency.
TOOL_REGISTRY: dict[str, ToolConfig] = {
    "magic_values": ToolConfig(
        command=_python("check_magic_values.py", "--json"),
        json_file="magic_values.json",
        jq_hint="jq '.violations[] | {file, line, rule, message}'",
    ),
    "format": ToolConfig(
        command=_bash("run_format_check.sh"),
        json_file="format.json",
        jq_hint="jq '.violations[].file'",
    ),
    "lint": ToolConfig(
        command=_bash("run_lint.sh"),
        json_file="lint.json",
        jq_hint="jq '.violations[] | {file, rule, message}'",
    ),
    "type_check": ToolConfig(
        command=_bash("run_type_check.sh"),
        json_file="type_check.json",
        jq_hint="jq '.errors[] | {file, line, message}'",
    ),
    # The hint MUST name the array holding the detail, not the summary. It
    # pointed at `.summary` until Plan 00229 — sending a reader who wanted to
    # know WHAT failed back to the count they had already been shown. That is
    # why Plan 00226's missing failure names had no surface on which they could
    # look wrong. Asserted by test_llm_qa_count_implies_detail.py.
    "tests": ToolConfig(
        command=_bash("run_tests.sh"),
        json_file="tests.json",
        jq_hint="jq '.tests[] | select(.outcome == \"failed\") | .name'",
    ),
    "security": ToolConfig(
        command=_bash("run_security_check.sh"),
        json_file="security.json",
        jq_hint="jq '.issues[] | {file, test_id, severity, message}'",
    ),
    "dependencies": ToolConfig(
        command=_bash("run_dependency_check.sh"),
        json_file="dependencies.json",
        jq_hint="jq '.issues[]'",
    ),
    "error_hiding": ToolConfig(
        command=_python("audit_error_hiding.py", "--json"),
        json_file="error_hiding.json",
        jq_hint="jq '.violations[] | {file, line, rule, message}'",
    ),
    "shell_audit": ToolConfig(
        command=_python("audit_shell.py", "--json"),
        json_file="shell_audit.json",
        jq_hint="jq '.violations[] | {file, line, rule, message}'",
    ),
    "skill_refs": ToolConfig(
        command=_python("check_skill_references.py", "--json"),
        json_file="skill_references.json",
        jq_hint="jq '.violations[] | {file, line, rule, message}'",
    ),
    "canonical_callers": ToolConfig(
        command=_bash("run_canonical_callers_check.sh"),
        json_file="canonical_callers.json",
        jq_hint="jq '.violations[]'",
    ),
    "python_var_guidance": ToolConfig(
        command=_python("check_python_var_guidance.py", "--json"),
        json_file="python_var_guidance.json",
        jq_hint="jq '.violations[] | {file, line, rule, message}'",
    ),
    "semgrep": ToolConfig(
        command=_bash("run_semgrep_check.sh"),
        json_file="semgrep.json",
        jq_hint="jq '.violations[] | {file, line, rule, message}'",
    ),
    "capture_corruption": ToolConfig(
        command=_bash("run_capture_corruption_check.sh"),
        json_file="capture_corruption.json",
        jq_hint="jq '.violations[] | {file, line, function, rule, message}'",
    ),
    "repo_hygiene": ToolConfig(
        command=_python("check_repo_hygiene.py", "--json"),
        json_file="repo_hygiene.json",
        jq_hint="jq '.violations[] | {rule, path, message}'",
    ),
    "doc_truth": ToolConfig(
        command=_python("check_doc_truth.py", "--json"),
        json_file="doc_truth.json",
        jq_hint="jq '.violations[] | {rule, file, line, message}'",
    ),
    "doc_snippets": ToolConfig(
        command=_python("check_doc_snippets.py", "--json"),
        json_file="doc_snippets.json",
        jq_hint="jq '.violations[] | {file, line, symbol, keyword}'",
    ),
    "sensitive_content": ToolConfig(
        command=_python("check_sensitive_content.py", "--json"),
        json_file="sensitive_content.json",
        jq_hint="jq '.violations[] | {file, line, rule, message}'",
    ),
    "git_history": ToolConfig(
        command=_python("check_git_history.py", "--json"),
        json_file="git_history.json",
        jq_hint="jq '.violations[] | {surface, locator, rule, message}'",
    ),
    "handler_reference": ToolConfig(
        command=_python("check_handler_reference.py", "--json"),
        json_file="handler_reference.json",
        jq_hint="jq '.violations[] | {rule, file, line, message}'",
    ),
    "british_english": ToolConfig(
        command=_python("check_british_english.py", "--json"),
        json_file="british_english.json",
        jq_hint="jq '.violations[] | {file, line, american, british}'",
    ),
    # Runs the project handlers' own tests, which `run_tests.sh` cannot reach:
    # `testpaths` is ["tests"], so the 61 tests co-located with
    # `.claude/project-handlers/` went unexecuted by every gate while
    # gate-scope.bash cited them as the reason those handlers need no type
    # checking. Both are terminal and both DENY.
    "project_handlers": ToolConfig(
        command=_python("check_project_handler_tests.py", "--json"),
        json_file="project_handlers.json",
        jq_hint="jq '.tests[] | {name, outcome}'",
    ),
    # Diffs the daemon's schemas/claim tables against the vendored Claude Code
    # hooks contract (Plan 00271). Network-free; staleness is the
    # contract_staleness SessionStart advisory's job.
    "hook_contract": ToolConfig(
        command=_python("check_hook_contract.py", "--json"),
        json_file="hook_contract.json",
        jq_hint="jq '.violations[] | {rule, event, subject, message}'",
    ),
    # Diffs the daemon's top-level hook_input READ surface against the vendored
    # per-event input_examples (Plan 00273, superset rule). Network-free.
    "input_contract": ToolConfig(
        command=_python("check_input_contract.py", "--json"),
        json_file="input_contract.json",
        jq_hint="jq '.violations[] | {rule, event, subject, message}'",
    ),
    # smoke_test MUST stay last: it probes the live daemon, so it belongs
    # after every static check has had its say. Pinned by
    # test_smoke_test_is_last_in_registry -- three tools were appended below
    # it before that test caught the drift.
    "smoke_test": ToolConfig(
        command=_bash("run_smoke_test.sh"),
        json_file="smoke_test.json",
        jq_hint="jq '.probes[] | {name, passed, expected, actual_decision}'",
    ),
}

ALL_TOOL_NAMES = list(TOOL_REGISTRY)


# ── Summarizers ────────────────────────────────────────────────────


def _summarize_magic_values(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_format(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} files need reformatting"


def _summarize_lint(data: QaReport) -> str:
    s = data.get("summary", {})
    total = s.get("total_violations", 0)
    if total == 0:
        return "0 violations"
    errors = s.get("errors", 0)
    warnings = s.get("warnings", 0)
    return f"{total} violations ({errors} errors, {warnings} warnings)"


def _summarize_type_check(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_errors", 0)
    return f"{total} errors"


# How many failing test names to print inline. This output is read by an LLM on
# every QA run, so a mass breakage must not flood it; the rest stay in
# tests.json, which is the complete record.
_MAX_NAMED_FAILURES = 15


def _summarize_tests(data: QaReport) -> str:
    s = data.get("summary", {})
    passed = s.get("passed", 0)
    failed = s.get("failed", 0)
    skipped = s.get("skipped", 0)
    cov = data.get("coverage", {}).get("percent_covered", 0)
    line = f"{passed} passed, {failed} failed, {skipped} skipped | coverage: {cov:.1f}%"

    # Name the failures (Plan 00226). A count alone forces a full re-run to
    # find out what broke, and a re-run may not reproduce an order-dependent
    # failure — during Plan 00224 one of two real failures was never
    # identified. Bounded so a mass breakage cannot flood the artifact.
    names = [t.get("name", "") for t in data.get("tests", []) if t.get("outcome") == "failed"]
    names = [name for name in names if name]
    if not names:
        return line

    shown = names[:_MAX_NAMED_FAILURES]
    line += "\n   failed: " + "\n           ".join(shown)
    if len(names) > len(shown):
        line += f"\n           ... and {len(names) - len(shown)} more (see tests.json)"
    return line


def _summarize_security(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_issues", 0)
    return f"{total} issues"


def _summarize_dependencies(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_issues", 0)
    return f"{total} issues"


def _summarize_error_hiding(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_shell_audit(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_skill_refs(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_smoke_test(data: QaReport) -> str:
    s = data.get("summary", {})
    passed = s.get("passed_probes", 0)
    total = s.get("total_probes", 0)
    failed = s.get("failed_probes", 0)
    if failed == 0:
        return f"{passed}/{total} probes passed"
    return f"{passed}/{total} probes passed ({failed} failed)"


def _summarize_canonical_callers(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_capture_corruption(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_python_var_guidance(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_repo_hygiene(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_doc_truth(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_doc_snippets(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_sensitive_content(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_git_history(data: QaReport) -> str:
    summary = data.get("summary", {})
    total = summary.get("total_violations", 0)
    commits = summary.get("commits_scanned", 0)
    refs = summary.get("refs_scanned", 0)
    return f"{total} violations ({commits} commits, {refs} refs swept)"


def _summarize_handler_reference(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_british_english(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_semgrep(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_violations", 0)
    return f"{total} violations"


def _summarize_project_handlers(data: QaReport) -> str:
    """Report the project-handler suite, distinguishing clean from absent.

    A runner that collected nothing yields "0 failed", which reads as success.
    Saying so explicitly keeps the summary line honest, since that is the line
    an agent acts on.
    """
    summary = data.get("summary", {})
    total = summary.get("total", 0)
    if total == 0:
        return "0 tests collected - the suite did NOT run"

    failed = summary.get("failed", 0)
    line = f"{summary.get('passed', 0)} passed, {failed} failed"
    if not failed:
        return line

    names = [entry.get("name", "?") for entry in data.get("tests", [])]
    return line + " | " + ", ".join(names[:_MAX_NAMED_FAILURES])


def _summarize_hook_contract(data: QaReport) -> str:
    summary = data.get("summary", {})
    total = summary.get("total_violations", 0)
    allowlisted = summary.get("allowlisted", 0)
    return f"{total} violations ({allowlisted} allowlisted gaps recorded)"


SUMMARIZERS: dict[str, Summarizer] = {
    "magic_values": _summarize_magic_values,
    "format": _summarize_format,
    "lint": _summarize_lint,
    "type_check": _summarize_type_check,
    "tests": _summarize_tests,
    "security": _summarize_security,
    "dependencies": _summarize_dependencies,
    "error_hiding": _summarize_error_hiding,
    "shell_audit": _summarize_shell_audit,
    "skill_refs": _summarize_skill_refs,
    "canonical_callers": _summarize_canonical_callers,
    "capture_corruption": _summarize_capture_corruption,
    "python_var_guidance": _summarize_python_var_guidance,
    "smoke_test": _summarize_smoke_test,
    "repo_hygiene": _summarize_repo_hygiene,
    "doc_truth": _summarize_doc_truth,
    "doc_snippets": _summarize_doc_snippets,
    "sensitive_content": _summarize_sensitive_content,
    "git_history": _summarize_git_history,
    "handler_reference": _summarize_handler_reference,
    "british_english": _summarize_british_english,
    "semgrep": _summarize_semgrep,
    "project_handlers": _summarize_project_handlers,
    "hook_contract": _summarize_hook_contract,
    "input_contract": _summarize_hook_contract,
}


# ── Core logic ─────────────────────────────────────────────────────


# The leading `.<key>[]` of a jq hint — the array the operator is sent to.
# `jq '.violations[] | {file, line}'` yields "violations".
_HINT_DETAIL_ARRAY_PATTERN = re.compile(r"\.(?P<key>\w+)\[\]")

# Prefix for the inconsistency line. Named so a test can assert the warning
# fires without pinning the whole sentence, which is prose and may be reworded.
_DETAIL_MISSING_WARNING: Final[str] = "⚠️  DETAIL MISSING:"

# Prefix for an explanation the tool itself recorded.
_REPORT_ERROR_LABEL: Final[str] = "⚠️  TOOL ERROR:"

# Where a tool may record why it could not run. Two locations because the
# shipped scripts genuinely use both: run_smoke_test.sh writes a top-level
# `error`, run_shell_check.sh nests one inside `summary`.
_REPORT_ERROR_PATHS: Final[tuple[tuple[str, ...], ...]] = (("error",), ("summary", "error"))

# Summary keys that count BAD things. Detail is owed only when one of these is
# non-zero; `passed` and `total_probes` say nothing about whether detail is due.
_FAILURE_COUNT_KEYS: Final[tuple[str, ...]] = (
    "total_violations",
    "total_errors",
    "total_issues",
    "failed",
    "failed_probes",
)


def detail_array_key(jq_hint: str) -> str | None:
    """The report array a printed hint sends the operator to, or None.

    Public because the guard in tests/unit/qa/test_llm_qa_count_implies_detail.py
    asserts against THIS function rather than reimplementing the parse. A
    second copy in the test would be free to drift from the one that runs —
    which is precisely the producer/consumer split that produced the defect
    Plan 00226 fixed and Plan 00229 generalised.
    """
    match = _HINT_DETAIL_ARRAY_PATTERN.search(jq_hint)
    return match.group("key") if match else None


def failure_count(summary: QaReport) -> int:
    """How many bad things this report claims, across every count key it uses."""
    return sum(int(summary.get(key, 0)) for key in _FAILURE_COUNT_KEYS)


def _detail_is_missing(data: QaReport, jq_hint: str) -> bool:
    """True when a report claims failures but its detail array is empty.

    The failure this catches is silent by construction: the reader is given a
    number, follows the printed hint, sees nothing, and cannot distinguish
    "no detail exists" from "the detail was dropped". Plan 00226 lost a real
    test failure to exactly that ambiguity, because the only recourse was a
    re-run and the re-run did not reproduce it.
    """
    if failure_count(data.get("summary", {})) == 0:
        return False
    key = detail_array_key(jq_hint)
    if key is None:
        return True
    return not data.get(key)


def _report_error(data: QaReport) -> str | None:
    """An explanation the tool recorded, which nothing else would show.

    `run_tool` sends every tool's stdout to DEVNULL, so a script's own console
    message ("❌ shellcheck not installed") never reaches the reader. If the
    tool also wrote the reason into its JSON, that copy is the only one left —
    and no summariser reads it, so the artifact shows a red line with a count
    and no cause.

    Both shapes below are live in the shipped scripts, which is why this looks
    in two places rather than one.
    """
    for path in _REPORT_ERROR_PATHS:
        value: Any = data
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _is_passed(data: QaReport) -> bool:
    """Determine pass/fail from JSON data (handles both schemas)."""
    summary = data.get("summary", {})
    # tests.json uses "passed_all", everything else uses "passed"
    if "passed_all" in summary:
        return bool(summary["passed_all"])
    return bool(summary.get("passed", False))


def run_tool(name: str) -> int:
    """Run a QA tool, suppressing its stdout/stderr. Returns exit code."""
    config = TOOL_REGISTRY[name]
    result = subprocess.run(
        config.command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(PROJECT_ROOT),
    )
    return result.returncode


def summarize_tool(name: str, exit_code: int | None = None) -> tuple[bool, str]:
    """Read JSON output and produce a 2-line summary.

    Args:
        name: Tool name from TOOL_REGISTRY.
        exit_code: Exit code from running the tool. If non-zero, overrides
            JSON pass/fail (catches cases where JSON lies about results).

    Returns (passed, formatted_summary_string).
    """
    config = TOOL_REGISTRY[name]
    json_path = QA_OUTPUT_DIR / config.json_file

    if not json_path.exists():
        return False, f"  {name}: NO OUTPUT (run tool first)\n"

    with open(json_path) as f:
        data = json.load(f)

    json_passed = _is_passed(data)
    # Tool exit code is authoritative - if non-zero, it's a failure even if
    # JSON claims success (e.g. mypy finds errors but the JSON parser misses
    # them). Both conditions must hold for a PASS, so neither source can
    # unilaterally declare success.
    tool_reported_failure = exit_code is not None and exit_code != 0
    passed = json_passed and not tool_reported_failure

    icon = "\u2705" if passed else "\u274c"
    summarizer = SUMMARIZERS[name]
    metrics = summarizer(data)

    # Warn when exit code disagrees with JSON
    mismatch_note = ""
    if exit_code is not None and exit_code != 0 and json_passed:
        mismatch_note = " (exit code non-zero, JSON may be inaccurate)"

    line1 = f"{icon} {name}: {metrics}{mismatch_note}"
    line2 = f"   {config.json_file} | {config.jq_hint}"

    # A recorded reason beats any inference we could make, and it is the ONLY
    # copy left once run_tool discards the tool's stdout. It also takes
    # precedence over the generic warning below: that warning says detail
    # "was dropped", which is false for a tool that never ran — no probes
    # executed, so there was never anything to drop (Plan 00229).
    recorded_error = _report_error(data)
    if recorded_error is not None:
        line3 = f"   {_REPORT_ERROR_LABEL} {recorded_error}"
        return passed, f"{line1}\n{line2}\n{line3}\n"

    # A report that counts failures it cannot show is worse than one that
    # counts none: the hint above becomes a promise it does not keep, and an
    # empty result reads as "nothing to fix". Say so rather than let the
    # reader draw that conclusion (Plan 00229).
    if _detail_is_missing(data, config.jq_hint):
        line3 = (
            f"   {_DETAIL_MISSING_WARNING} the count above has no detail behind it, "
            f"so the command on the previous line will print nothing. Do NOT read "
            f"that as 'nothing to fix' — the detail was dropped, not absent."
        )
        return passed, f"{line1}\n{line2}\n{line3}\n"

    return passed, f"{line1}\n{line2}\n"


# ── CLI ────────────────────────────────────────────────────────────


def main() -> int:
    """Entry point."""
    args = sys.argv[1:]

    read_only = False
    if "--read-only" in args:
        read_only = True
        args.remove("--read-only")

    if not args or "--help" in args or "-h" in args:
        print("Usage: llm_qa.py [--read-only] <tool|all> [tool ...]")
        print(f"Tools: {', '.join(ALL_TOOL_NAMES)}")
        return EXIT_SUCCESS

    # Resolve tool list
    if "all" in args:
        tools = ALL_TOOL_NAMES
    else:
        tools = []
        for name in args:
            if name not in TOOL_REGISTRY:
                print(f"Unknown tool: {name}")
                print(f"Available: {', '.join(ALL_TOOL_NAMES)}")
                return EXIT_FAILURE
            tools.append(name)

    # The run lock guards the EXECUTING path only. `--read-only` runs no tools,
    # so it cannot contend -- and it is exactly the command someone reaches for
    # to inspect a run already in progress. Locking it would block the
    # diagnostic during the one situation the diagnostic is for.
    if read_only:
        return _run_tools(tools, read_only=True)

    lock_file = run_lock_path()
    if not try_acquire_run_lock(str(lock_file)):
        print(busy_message(str(lock_file)), file=sys.stderr)
        return EXIT_BUSY

    return _run_tools(tools, read_only=False)


def _run_tools(tools: list[str], *, read_only: bool) -> int:
    """Run (or merely summarize) each tool and print the overall verdict."""
    all_passed = True
    tool_results: dict[str, tuple[bool, str]] = {}

    for name in tools:
        # Run the tool (unless read-only)
        exit_code: int | None = None
        if not read_only:
            exit_code = run_tool(name)

        # Summarize from JSON, passing exit code for cross-check
        passed, summary = summarize_tool(name, exit_code=exit_code)
        tool_results[name] = (passed, summary)
        print(summary, end="")
        if not passed:
            all_passed = False

    # Overall summary
    total = len(tools)
    passed_count = sum(1 for passed, _ in tool_results.values() if passed)
    print()
    if all_passed:
        print(f"QA: {passed_count}/{total} PASSED")
    else:
        print(f"QA: {passed_count}/{total} PASSED, {total - passed_count}/{total} FAILED")

    return EXIT_SUCCESS if all_passed else EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
