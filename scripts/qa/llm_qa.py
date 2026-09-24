#!/usr/bin/env python3
"""LLM-optimized QA runner - minimal stdout, structured JSON to file.

Runs the same QA tools as run_all.sh but produces 2 lines per tool
instead of 50+. Designed for AI coding assistants that prefer concise,
machine-parseable output with pointers to detailed JSON.

Usage:
    ./scripts/qa/llm_qa.py all              # Run every QA check in the suite
    ./scripts/qa/llm_qa.py changed          # Targeted: fast static tools + mapped tests
    ./scripts/qa/llm_qa.py lint type_check  # Run specific tools
    ./scripts/qa/llm_qa.py --read-only all  # Summarize existing JSON only
    ./scripts/qa/llm_qa.py main-moved BASE  # Batched gate: did main move in code?

``all`` is the coordinator's full gate. A sub-agent runs ``changed`` or named
tools, and ``subagent_full_qa_blocker`` denies it the full suite (Plan 00463).
"""

from __future__ import annotations

import fcntl
import functools
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final, NamedTuple, TypeAlias

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts" / "qa"
QA_OUTPUT_DIR = PROJECT_ROOT / "untracked" / "qa"

#: The canonical bash venv resolver, relative to a checkout root. It answers
#: with the fingerprint-keyed ``untracked/venv-<fingerprint>/bin/python`` that
#: every other entry point (init.sh, venv_resolver.sh, venv-include.bash) uses.
_RESOLVE_VENV_SH = Path("scripts") / "lib" / "resolve_venv.sh"

#: The pre-v3.7.0 unversioned venv path. `venv-include.bash` refuses to CREATE
#: anything here, so it exists only where an operator left a symlink behind —
#: which is why hardcoding it worked in the main checkout and in no worktree.
_LEGACY_VENV_PYTHON = Path("untracked") / "venv" / "bin" / "python"


class VenvResolutionError(RuntimeError):
    """No QA interpreter could be resolved for a checkout."""


def resolve_venv_python(project_root: Path = PROJECT_ROOT) -> Path:
    """The interpreter the QA tools run under, for ``project_root``.

    The resolver is authoritative wherever it is deployed; the legacy path is
    consulted ONLY when the resolver itself is missing, never as a rescue for
    a resolver that ran and reported failure. Rescuing there would resurrect
    the silent fallback the fingerprint layout exists to remove: a stale
    ``untracked/venv`` symlink would answer for a venv the resolver had just
    rejected, and the QA suite would run under the wrong Python.

    Raises:
        VenvResolutionError: naming BOTH places that were tried, and the
            resolver's own diagnostic when it produced one.
    """
    resolver = project_root / _RESOLVE_VENV_SH
    legacy = project_root / _LEGACY_VENV_PYTHON

    if not resolver.is_file():
        if legacy.is_file():
            return legacy
        raise VenvResolutionError(
            f"no QA interpreter for {project_root}:\n"
            f"  1. canonical resolver {resolver} is not present\n"
            f"  2. legacy interpreter {legacy} does not exist either\n"
            "Install/repair the daemon so the resolver is deployed, then re-run."
        )

    completed = subprocess.run(
        ["bash", str(resolver), "python", str(project_root)],
        capture_output=True,
        text=True,
        check=False,
    )
    resolved = completed.stdout.strip()
    if completed.returncode == 0 and resolved:
        return Path(resolved)

    diagnostic = completed.stderr.strip() or "(no diagnostic on stderr)"
    raise VenvResolutionError(
        f"no QA interpreter for {project_root}:\n"
        f"  1. {resolver} python {project_root} exited {completed.returncode}:\n"
        f"     {diagnostic}\n"
        f"  2. legacy interpreter {legacy} is NOT consulted when the resolver "
        "is present, so that a stale symlink cannot answer for a venv the "
        "resolver rejected.\n"
        "Create the venv (hooks-daemon skill, install action), then re-run."
    )


@functools.cache
def venv_python() -> Path:
    """The interpreter the tools run under, resolved once, on first use.

    Resolved at RUN time, not import time. Importing this module to inspect
    ``TOOL_REGISTRY`` (the wiring tests do) must not depend on the shell it is
    imported in: on CI the venv is ``.venv``, visible to the resolver only
    through ``HOOKS_DAEMON_VENV_PATH``, and the test suite unsets that for
    every test — so an import-time resolution raised ``SystemExit`` in a test
    about registry wiring. A tool that RUNS still needs the interpreter, and
    :func:`main` reports the same failure before running anything.
    """
    return resolve_venv_python(PROJECT_ROOT)


# Stands in for the venv interpreter inside every ``_python(...)`` command
# until the tool runs; :func:`resolved_command` swaps in :func:`venv_python`.
VENV_PYTHON_PLACEHOLDER: Final[str] = "<venv-python>"

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


# ── Provenance: which tree a result judged ─────────────────────────
# Plan 00463, review finding 3. `--read-only` is how a sub-agent reads the
# coordinator's full run without running it, and nothing tied the JSON to a
# commit: a green result from an older commit, or from before later edits,
# read as a pass. Each run records, per tool, the tree it judged, the live
# verdict and exit code, and the hash of the report it wrote. A read-only
# summary FAILS a result recorded for any other tree or a report the run did
# not write, and re-applies the recorded exit code (delta review N1: a crashed
# tool's older green report once read as a pass).

#: Per-tool record of the tree each result was produced from.
PROVENANCE_FILE: Final[str] = "provenance.json"

#: What a run records when the tree changed while it ran: matches no tree.
_TREE_CHANGED_DURING_RUN: Final[str] = "changed-during-run"

_STATE_HEAD: Final[str] = "head"
_STATE_DIGEST: Final[str] = "tree_digest"
_RECORD_PASSED: Final[str] = "passed"
_RECORD_EXIT_CODE: Final[str] = "exit_code"
_RECORD_OUTPUT_DIGEST: Final[str] = "output_sha256"
_DIGEST_ALGORITHM: Final[str] = "sha256"
_SHORT_SHA: Final[int] = 12
_GIT_STATE_TIMEOUT_SECONDS: Final[int] = 60

#: One tool's provenance entry, as JSON: the tree (str), the live verdict
#: (bool), the exit code (int) and its report's hash (str, or None when the
#: run wrote no report).
ProvenanceRecord: TypeAlias = dict[str, str | bool | int | None]

#: (exit code, stdout bytes) for one git call; injected in tests.
GitBytesRunner = Callable[[list[str], Path], tuple[int, bytes]]


def _run_git_bytes(args: list[str], root: Path) -> tuple[int, bytes]:
    """One git call in ``root``; a failure to run is a non-zero result."""
    try:
        completed = subprocess.run(
            ["git", *args],
            capture_output=True,
            cwd=str(root),
            timeout=_GIT_STATE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc).encode()
    return completed.returncode, completed.stdout


def worktree_state(root: Path, *, git: GitBytesRunner = _run_git_bytes) -> dict[str, str] | None:
    """HEAD plus a digest of every uncommitted change, or None when unreadable.

    Two results match only when both the commit and the working tree do:
    tracked edits through ``git diff HEAD``, new files through their names and
    contents. Ignored files (``untracked/``, where results live) are not part
    of it.
    """
    code, head = git(["rev-parse", "HEAD"], root)
    if code != 0:
        return None
    code, diff = git(["diff", "HEAD", "--binary"], root)
    if code != 0:
        return None
    code, untracked = git(["ls-files", "--others", "--exclude-standard", "-z"], root)
    if code != 0:
        return None
    digest = hashlib.sha256(diff)
    for name in sorted(entry for entry in untracked.split(b"\0") if entry):
        digest.update(b"\0" + name + b"\0")
        try:
            # Streamed, so a large untracked artefact is never held whole.
            with open(root / name.decode(), "rb") as handle:
                digest.update(hashlib.file_digest(handle, _DIGEST_ALGORITHM).digest())
        except (OSError, UnicodeDecodeError) as exc:
            # Still part of the digest, as its failure: a file that cannot be
            # read now and could later must not match its readable self.
            digest.update(type(exc).__name__.encode())
    return {_STATE_HEAD: head.decode().strip(), _STATE_DIGEST: digest.hexdigest()}


def stale_reason(recorded: ProvenanceRecord | None, current: dict[str, str] | None) -> str | None:
    """Why a recorded result does not describe the current tree, or None when it does."""
    if current is None:
        return "the working tree cannot be read (git failed), so no result can be tied to it"
    if not recorded:
        return "no record of which tree this result judged; re-run the tool"
    recorded_head = str(recorded.get(_STATE_HEAD, ""))
    current_head = current[_STATE_HEAD]
    if recorded_head != current_head:
        return (
            f"recorded at {recorded_head[:_SHORT_SHA]}, but HEAD is "
            f"{current_head[:_SHORT_SHA]}; re-run the tool"
        )
    if recorded.get(_STATE_DIGEST) != current[_STATE_DIGEST]:
        return (
            f"recorded at {current_head[:_SHORT_SHA]} with different uncommitted changes "
            "(or the tree changed during that run); re-run the tool"
        )
    return None


def output_reason(recorded: ProvenanceRecord, output: Path) -> str | None:
    """Why the report on disk is not the one the recorded run wrote, or None when it is.

    A run removes each tool's report before running it, so a tool that
    crashed leaves nothing behind rather than an older green report.
    """
    if _RECORD_EXIT_CODE not in recorded:
        return "the record carries no verdict for this result; re-run the tool"
    expected = recorded.get(_RECORD_OUTPUT_DIGEST)
    if expected is None:
        return "the recorded run wrote no report; re-run the tool"
    if output_digest(output) != expected:
        return "the report on disk is not the one that run wrote; re-run the tool"
    return None


def output_digest(path: Path) -> str | None:
    """The sha256 of a tool's report, or None when there is none."""
    if not path.is_file():
        return None
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, _DIGEST_ALGORITHM).hexdigest()


def run_record(
    state: dict[str, str], *, exit_code: int, passed: bool, output: Path
) -> ProvenanceRecord:
    """One tool's entry: the tree it judged, its live verdict and its report's hash."""
    return {
        **state,
        _RECORD_PASSED: passed,
        _RECORD_EXIT_CODE: exit_code,
        _RECORD_OUTPUT_DIGEST: output_digest(output),
    }


def read_provenance(qa_dir: Path) -> dict[str, ProvenanceRecord]:
    """The per-tool record; missing or unreadable reads as no record at all."""
    try:
        data = json.loads((qa_dir / PROVENANCE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record_provenance(qa_dir: Path, records: Mapping[str, ProvenanceRecord]) -> None:
    """Record each tool's entry, keeping the entries of tools not in ``records``."""
    recorded = read_provenance(qa_dir)
    recorded.update(records)
    qa_dir.mkdir(parents=True, exist_ok=True)
    (qa_dir / PROVENANCE_FILE).write_text(json.dumps(recorded, indent=2), encoding="utf-8")


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
    return [VENV_PYTHON_PLACEHOLDER, str(SCRIPTS_DIR / script), *args]


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
    # Zero-errors gate over what pyrightconfig.json scopes (Plan 00368): the
    # same binary and config the language server uses, so a diagnostic the
    # agent sees mid-edit is one this gate would fail on too.
    "pyright": ToolConfig(
        command=_python("run_pyright_check.py", "--json"),
        json_file="pyright.json",
        jq_hint="jq '.errors[] | {file, line, rule, message}'",
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
    # N22: run_all.sh step 8 runs this, but no TOOL_REGISTRY entry ever did —
    # so `llm_qa.py all`, the ONLY suite `enforce_llm_qa` lets an agent run,
    # reported "full QA N/N" while shellcheck never ran. Only CI's separate
    # `shellcheck` step (.github/workflows/qa.yml) caught a shell defect, and
    # only after the merge. Pinned by test_llm_qa_run_all_wiring.py.
    "shell_check": ToolConfig(
        command=_bash("run_shell_check.sh"),
        json_file="shell_check.json",
        jq_hint="jq '.issues[] | {file, line, rule, message}'",
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
    "github_urls": ToolConfig(
        command=_python("check_github_urls.py", "--json"),
        json_file="github_urls.json",
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
    "eacces_safe": ToolConfig(
        command=_python("check_eacces_safe_predicates.py", "--json"),
        json_file="eacces_safe.json",
        jq_hint="jq '.violations[] | {file, line, rule, message}'",
    ),
    "authored_path_stat": ToolConfig(
        command=_python("check_authored_path_stat.py", "--json"),
        json_file="authored_path_stat.json",
        jq_hint="jq '.violations[] | {file, line, rule, message}'",
    ),
    "skip_list_substring": ToolConfig(
        command=_python("check_skip_list_substring.py", "--json"),
        json_file="skip_list_substring.json",
        jq_hint="jq '.violations[] | {file, line, rule, message}'",
    ),
    "declared_invariant_pairs": ToolConfig(
        command=_python("check_declared_invariant_pairs.py", "--json"),
        json_file="declared_invariant_pairs.json",
        jq_hint="jq '.violations[] | {row, left, right, members, message}'",
    ),
    "fail_open_inventory": ToolConfig(
        command=_python("check_fail_open_inventory.py", "--json"),
        json_file="fail_open_inventory.json",
        jq_hint="jq '.violations[] | {surface, scope, construct, detail}'",
    ),
    "dangerous_invocation_corpus": ToolConfig(
        command=_python("check_dangerous_invocation_corpus.py", "--json"),
        json_file="dangerous_invocation_corpus.json",
        jq_hint="jq '.violations[] | {row, command, detail}'",
    ),
    "security_downgrade_flags": ToolConfig(
        command=_python("check_security_downgrade_flags.py", "--json"),
        json_file="security_downgrade_flags.json",
        jq_hint="jq '.violations[] | {path, rule, detail}'",
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
    # The two corpus sweeps (Plan 00373). Both shipped as CLI verbs exiting
    # non-zero on findings and neither was registered here, so plan-tree and
    # doc-corpus drift could not fail QA, CI or the release gate — and did
    # not, for four findings a merge put on main.
    "plan_qa": ToolConfig(
        command=_python("run_corpus_qa.py", "--corpus", "plan", "--json"),
        json_file="plan_qa.json",
        jq_hint="jq '.findings[] | {check_id, severity, path, message}'",
    ),
    "docs_qa": ToolConfig(
        command=_python("run_corpus_qa.py", "--corpus", "docs", "--json"),
        json_file="docs_qa.json",
        jq_hint="jq '.findings[] | {check_id, severity, path, message}'",
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
    # Targeted only (Plan 00463): pytest on the tests mapped from what changed
    # since the merge base. Excluded from `all`, which runs the whole suite
    # through `tests` and would run these a second time.
    "changed_tests": ToolConfig(
        command=_python("run_changed_tests.py", "--json"),
        json_file="changed_tests.json",
        jq_hint="jq '.tests[] | select(.outcome == \"failed\") | .name'",
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

#: Tools that exist for the targeted path only, and never run as part of `all`.
_TARGETED_ONLY_TOOLS: Final[frozenset[str]] = frozenset({"changed_tests"})

ALL_TOOL_NAMES = [name for name in TOOL_REGISTRY if name not in _TARGETED_ONLY_TOOLS]

#: `changed`: what a sub-agent runs before handing a commit to the coordinator.
#: The fast static tools, the project handlers' own suite (seconds), the tools
#: `changed_tests_map.yaml` names as covering non-Python files, and the tests
#: mapped from the change set. Never `tests`, which is the whole suite.
CHANGED_TOOL_NAMES: Final[list[str]] = [
    "magic_values",
    "format",
    "lint",
    "type_check",
    "pyright",
    "error_hiding",
    "project_handlers",
    "docs_qa",
    "plan_qa",
    "shell_check",
    "declared_invariant_pairs",
    "changed_tests",
]

#: Selection words that expand to a tool list rather than naming one tool.
_SELECTION_ALL: Final[str] = "all"
_SELECTION_CHANGED: Final[str] = "changed"


# ── Summarizers ────────────────────────────────────────────────────


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


def _summarize_pyright(data: QaReport) -> str:
    s = data.get("summary", {})
    return f"{s.get('total_errors', 0)} errors ({s.get('files_analyzed', 0)} files analysed)"


# How many failing test names to print inline. This output is read by an LLM on
# every QA run, so a mass breakage must not flood it; the rest stay in
# tests.json, which is the complete record.
_MAX_NAMED_FAILURES = 15


def _summarize_tests(data: QaReport) -> str:
    s = data.get("summary", {})
    passed = s.get("passed", 0)
    failed = s.get("failed", 0)
    skipped = s.get("skipped", 0)
    # Shown whenever non-zero rather than always, so the common green line
    # stays unchanged. pytest counts a fixture/setup/teardown blow-up as an
    # ERROR, not a failure, so a summary reading "0 failed" was compatible
    # with a red run and the named node id below had nothing to explain it.
    errors = s.get("errors", 0)
    cov = data.get("coverage", {}).get("percent_covered", 0)
    error_part = f", {errors} errored" if errors else ""
    line = f"{passed} passed, {failed} failed{error_part}, {skipped} skipped | coverage: {cov:.1f}%"
    return line + _named_failures(data, "tests.json")


def _named_failures(data: QaReport, json_file: str) -> str:
    """The failing test names, one per line, or "" when there are none.

    Named rather than counted (Plan 00226). A count alone forces a full re-run
    to find out what broke, and a re-run may not reproduce an order-dependent
    failure — during Plan 00224 one of two real failures was never
    identified. Bounded so a mass breakage cannot flood the artifact.
    """
    names = [t.get("name", "") for t in data.get("tests", []) if t.get("outcome") == "failed"]
    names = [name for name in names if name]
    if not names:
        return ""

    shown = names[:_MAX_NAMED_FAILURES]
    text = "\n   failed: " + "\n           ".join(shown)
    if len(names) > len(shown):
        text += f"\n           ... and {len(names) - len(shown)} more (see {json_file})"
    return text


def _summarize_changed_tests(data: QaReport) -> str:
    """The targeted run, saying outright when it ran nothing and what it could not map.

    ``0 failed`` from an empty selection reads as a pass, and a sub-agent
    handing that to the coordinator as evidence would be overstating it. An
    unmapped file is NAMED, because a count is what agents skim past.
    """
    s = data.get("summary", {})
    considered = s.get("files_considered", 0)
    selected = s.get("test_files_selected", 0)
    unmapped_files = [str(name) for name in data.get("unmapped", [])]
    unmapped = len(unmapped_files)
    if selected == 0:
        line = (
            f"no tests ran: no test files mapped from {considered} changed files "
            f"({unmapped} unmapped)"
        )
    else:
        errors = s.get("errors", 0)
        error_part = f", {errors} errored" if errors else ""
        line = (
            f"{s.get('passed', 0)} passed, {s.get('failed', 0)} failed{error_part}, "
            f"{s.get('skipped', 0)} skipped | {selected} test files from {considered} "
            f"changed files ({unmapped} unmapped)"
        )
    if unmapped_files:
        verdict = (
            "allowed, the full gate must cover them"
            if data.get("unmapped_allowed")
            else (
                "each FAILS the run: add a test, a changed_tests_map.yaml rule, "
                "or pass --allow-unmapped"
            )
        )
        reasons = data.get("unmapped_reasons", {})
        shown = [
            f"{name} [{reasons[name].get('reason')}]" if name in reasons else name
            for name in unmapped_files[:_MAX_NAMED_FAILURES]
        ]
        more = unmapped - len(shown)
        line += f"\n   unmapped ({verdict}): " + ", ".join(shown)
        if more:
            line += f" ... and {more} more (see changed_tests.json)"
    return line + _named_failures(data, "changed_tests.json")


def _summarize_security(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_issues", 0)
    return f"{total} issues"


def _summarize_dependencies(data: QaReport) -> str:
    total = data.get("summary", {}).get("total_issues", 0)
    return f"{total} issues"


def _summarize_shell_check(data: QaReport) -> str:
    """Issue count plus files checked — the same denominator shellcheck's own
    console output leads with, so the summary line does not read as a smaller
    claim than the tool itself makes."""
    summary = data.get("summary", {})
    total = summary.get("total_issues", 0)
    return f"{total} issues{_denominators(summary)}"


def _summarize_smoke_test(data: QaReport) -> str:
    s = data.get("summary", {})
    passed = s.get("passed_probes", 0)
    total = s.get("total_probes", 0)
    failed = s.get("failed_probes", 0)
    if failed == 0:
        return f"{passed}/{total} probes passed"
    return f"{passed}/{total} probes passed ({failed} failed)"


#: Suffixes naming an INPUT count — what a check consumed, as opposed to what
#: it found. Kept in step with the vocabulary the guard in
#: `tests/integration/test_qa_checks_report_their_denominator.py` accepts: a
#: check that adds a denominator the guard recognises is surfaced here with no
#: further wiring.
_INPUT_COUNT_SUFFIXES: Final[tuple[str, ...]] = (
    "_scanned",
    "_loaded",
    "_compiled",
    "_analysed",
    "_analyzed",
    "_swept",
    "_checked",
    "_considered",
    "_read",
)


def _denominators(summary: dict[str, Any]) -> str:
    """Every input count this summary carries, rendered for the one-line report.

    Empty when a check reports none, so the line degrades to the bare count
    rather than to a misleading `(0 files)`.
    """
    parts = [
        f"{value} {key.replace('_', ' ')}"
        for key, value in summary.items()
        if key.endswith(_INPUT_COUNT_SUFFIXES)
    ]
    return f" ({', '.join(parts)})" if parts else ""


def _summarize_violations(data: QaReport, noun: str = "violations") -> str:
    """A findings count, followed by whatever the check says it looked at.

    ONE renderer rather than one per check, and that is the point rather than
    tidiness. Eighteen summarisers had byte-identical bodies that dropped the
    denominator, so a check could publish `files_scanned` and no reader would
    ever see it — the Plan 00244 failure of a verdict under a key nobody reads,
    recurring in the layer that exists to be read. Surfacing counts generically
    means the next check to add one is reported without anybody remembering to
    wire it up (Plan 00412 class 5).
    """
    summary = data.get("summary", {})
    total = summary.get("total_violations", 0)
    return f"{total} {noun}{_denominators(summary)}"


def _summarize_corpus_qa(data: QaReport) -> str:
    """Findings plus the severity split, which is the first thing a reader wants.

    Both sweeps print `N findings (B block, A advise)` themselves; the summary
    line says the same thing so the two never appear to disagree.
    """
    summary = data.get("summary", {})
    total = summary.get("total_issues", 0)
    return f"{total} findings ({summary.get('block', 0)} block, {summary.get('advise', 0)} advise)"


def _summarize_sensitive_content(data: QaReport) -> str:
    """Clean is reported WITH its denominators, or it is not a clean result.

    This check reads two independent corpora, and either can resolve to nothing
    while the other is healthy. A zero term count means the secret half of the
    scan did not run — `0 violations` then says only that an inert check found
    nothing (Plan 00412 class 5).
    """
    summary = data.get("summary", {})
    total = summary.get("total_violations", 0)
    files = summary.get("files_scanned", 0)
    terms = summary.get("secret_terms_loaded", 0)
    patterns = summary.get("public_patterns_compiled", 0)
    return f"{total} violations ({files} files, {terms} terms, {patterns} patterns)"


def _summarize_git_history(data: QaReport) -> str:
    summary = data.get("summary", {})
    total = summary.get("total_violations", 0)
    commits = summary.get("commits_scanned", 0)
    refs = summary.get("refs_scanned", 0)
    return f"{total} violations ({commits} commits, {refs} refs swept)"


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
    "magic_values": _summarize_violations,
    "format": _summarize_format,
    "lint": _summarize_lint,
    "type_check": _summarize_type_check,
    "pyright": _summarize_pyright,
    "tests": _summarize_tests,
    "security": _summarize_security,
    "dependencies": _summarize_dependencies,
    "shell_check": _summarize_shell_check,
    "error_hiding": _summarize_violations,
    "shell_audit": _summarize_violations,
    "skill_refs": _summarize_violations,
    "github_urls": _summarize_violations,
    "canonical_callers": _summarize_violations,
    "capture_corruption": _summarize_violations,
    "python_var_guidance": _summarize_violations,
    "eacces_safe": _summarize_violations,
    "authored_path_stat": _summarize_violations,
    "skip_list_substring": _summarize_violations,
    "declared_invariant_pairs": _summarize_violations,
    "fail_open_inventory": _summarize_violations,
    "dangerous_invocation_corpus": _summarize_violations,
    "security_downgrade_flags": _summarize_violations,
    "smoke_test": _summarize_smoke_test,
    "repo_hygiene": _summarize_violations,
    "doc_truth": _summarize_violations,
    "doc_snippets": _summarize_violations,
    "plan_qa": _summarize_corpus_qa,
    "docs_qa": _summarize_corpus_qa,
    "sensitive_content": _summarize_sensitive_content,
    "git_history": _summarize_git_history,
    "handler_reference": _summarize_violations,
    "british_english": _summarize_violations,
    "semgrep": _summarize_violations,
    "project_handlers": _summarize_project_handlers,
    "changed_tests": _summarize_changed_tests,
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

# Prefix for a `--read-only` result recorded for a different tree (Plan 00463).
_STALE_LABEL: Final[str] = "⚠️  STALE:"

#: Said by a run whose results cannot be tied to one tree.
_TREE_WARNING_LABEL: Final[str] = "⚠️  NOT RECORDED FOR THIS TREE:"

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


def resolved_command(config: ToolConfig) -> list[str]:
    """``config.command`` with the venv interpreter placeholder filled in.

    Raises:
        VenvResolutionError: when the command needs the interpreter and none
            can be resolved for this checkout.
    """
    return [
        str(venv_python()) if part == VENV_PYTHON_PLACEHOLDER else part for part in config.command
    ]


def run_tool(name: str, extra_args: Sequence[str] = ()) -> int:
    """Run a QA tool, suppressing its stdout/stderr. Returns exit code."""
    config = TOOL_REGISTRY[name]
    result = subprocess.run(
        [*resolved_command(config), *extra_args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(PROJECT_ROOT),
    )
    return result.returncode


def summarize_tool(
    name: str, exit_code: int | None = None, *, stale: str | None = None
) -> tuple[bool, str]:
    """Read JSON output and produce a 2-line summary.

    Args:
        name: Tool name from TOOL_REGISTRY.
        exit_code: Exit code from running the tool. If non-zero, overrides
            JSON pass/fail (catches cases where JSON lies about results).
        stale: Why the recorded result does not describe the current tree
            (``--read-only`` only). A stale result FAILS, however green.

    Returns (passed, formatted_summary_string).
    """
    passed, text = _summarize_recorded(name, exit_code)
    if stale is None:
        return passed, text
    marked = text.replace("✅", "❌", 1)
    return False, f"{marked}   {_STALE_LABEL} {stale}\n"


def _summarize_recorded(name: str, exit_code: int | None) -> tuple[bool, str]:
    """The summary of the JSON on disk, before any provenance judgement."""
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


def resolve_tools(names: list[str]) -> tuple[list[str], list[str]]:
    """Expand the selection words, keeping order and dropping repeats.

    ``all`` anywhere means the full suite and nothing else: every other name is
    already in it. ``changed`` expands to its targeted list, and a named tool
    beside it is added once.

    Returns:
        ``(tools, unknown)``: the tools to run, and each name that is neither a
        selection word nor a registered tool.
    """
    if _SELECTION_ALL in names:
        return list(ALL_TOOL_NAMES), []
    tools: list[str] = []
    unknown: list[str] = []
    for name in names:
        expanded = CHANGED_TOOL_NAMES if name == _SELECTION_CHANGED else [name]
        for tool in expanded:
            if tool not in TOOL_REGISTRY:
                unknown.append(tool)
            elif tool not in tools:
                tools.append(tool)
    return tools, unknown


#: Options `changed` forwards to `run_changed_tests.py` (Plan 00463).
_BASE_OPTION: Final[str] = "--base"
_ALLOW_UNMAPPED_OPTION: Final[str] = "--allow-unmapped"
_CHANGED_TESTS_TOOL: Final[str] = "changed_tests"


def split_changed_options(args: list[str]) -> tuple[list[str], list[str], str | None]:
    """Take ``--base REF`` and ``--allow-unmapped`` out of ``args`` for ``changed_tests``.

    Returns:
        ``(remaining, forwarded, error)``. An option given without a tool
        that uses it is an error rather than a silently ignored flag.
    """
    remaining: list[str] = []
    forwarded: list[str] = []
    index = 0
    while index < len(args):
        argument = args[index]
        index += 1
        if argument == _ALLOW_UNMAPPED_OPTION:
            forwarded.append(argument)
        elif argument == _BASE_OPTION:
            if index >= len(args) or args[index].startswith("-"):
                return args, [], f"{_BASE_OPTION} needs a ref"
            forwarded.extend([_BASE_OPTION, args[index]])
            index += 1
        elif argument.startswith(f"{_BASE_OPTION}="):
            forwarded.extend([_BASE_OPTION, argument.split("=", 1)[1]])
        else:
            remaining.append(argument)
    if forwarded:
        tools, _ = resolve_tools(remaining)
        if _CHANGED_TESTS_TOOL not in tools:
            return (
                args,
                [],
                (
                    f"{_BASE_OPTION} and {_ALLOW_UNMAPPED_OPTION} apply to "
                    f"`{_SELECTION_CHANGED}` (changed_tests) only"
                ),
            )
    return remaining, forwarded, None


# ── main-moved: may the batched gate skip a second full run? ────────

#: The subcommand, and what it answers (CLAUDE/QA.md, "The Batched Integration
#: Gate"). ``main`` moved after the integration branch was cut from it; the
#: verdict says whether the green full run still stands.
MAIN_MOVED_COMMAND: Final[str] = "main-moved"
VERDICT_UNMOVED: Final[str] = "unmoved"
VERDICT_DOCS_ONLY: Final[str] = "docs-only"
VERDICT_FULL_GATE: Final[str] = "full-gate"
#: A full-gate verdict is an answer, not a failure, so it has its own code.
EXIT_FULL_GATE: Final[int] = 4
_DEFAULT_MAIN_REF: Final[str] = "main"
_MAX_MAIN_MOVED_ARGS: Final[int] = 2

#: What a docs-only move re-runs instead of the full gate.
DOCS_ONLY_TOOL_NAMES: Final[list[str]] = [
    "plan_qa",
    "docs_qa",
    "format",
    "british_english",
    "sensitive_content",
]

#: THE docs-only path set, and its only definition. A file inside a numbered
#: plan folder (optionally under a bucket such as ``Completed/``), or a
#: markdown file outside the code roots. The plan directory's own root is
#: excluded on purpose: ``mkplan.bash`` and ``_planlib.inc.bash`` are executed
#: code with tests of their own.
_PLAN_FOLDER_FILE: Final[re.Pattern[str]] = re.compile(
    r"^CLAUDE/Plan/(?:[A-Za-z][^/]*/)?\d{5}-[^/]+/.+"
)
_DOCS_SUFFIX: Final[str] = ".md"
_CODE_ROOTS: Final[tuple[str, ...]] = ("src/", "tests/", "scripts/")


class MainMovedError(RuntimeError):
    """``base..main`` could not be read, so no verdict can be given."""


class MainMoved(NamedTuple):
    """The verdict, every path ``main`` changed since the base, and why."""

    verdict: str
    paths: list[str]
    reason: str


def is_docs_only_path(path: str) -> bool:
    """True when a change to ``path`` cannot alter what the full gate proved."""
    if _PLAN_FOLDER_FILE.match(path):
        return True
    return path.endswith(_DOCS_SUFFIX) and not path.startswith(_CODE_ROOTS)


def classify_moved_paths(paths: Sequence[str]) -> str:
    """Unmoved, docs-only, or full-gate: one code path anywhere means the full gate."""
    if not paths:
        return VERDICT_UNMOVED
    if all(is_docs_only_path(path) for path in paths):
        return VERDICT_DOCS_ONLY
    return VERDICT_FULL_GATE


def main_moved(
    base: str, main_ref: str, root: Path, *, git: GitBytesRunner = _run_git_bytes
) -> MainMoved:
    """Classify what ``main_ref`` changed since the batch was cut at ``base``.

    Renames are split into a deletion and an addition (``--no-renames``), so a
    file moved out of ``src/`` is judged by the path it left as well.

    Raises:
        MainMovedError: a ref does not resolve, or git cannot answer.
    """
    ancestor, _ = git(["merge-base", "--is-ancestor", base, main_ref], root)
    if ancestor == 1:
        return MainMoved(
            VERDICT_FULL_GATE,
            [],
            f"{base} is not an ancestor of {main_ref}: {main_ref} was rewritten, "
            "so there is no change set to classify",
        )
    if ancestor != 0:
        raise MainMovedError(
            f"git merge-base --is-ancestor {base} {main_ref} failed (exit {ancestor})"
        )
    code, output = git(["diff", "--name-only", "--no-renames", "-z", base, main_ref], root)
    if code != 0:
        raise MainMovedError(f"git diff {base} {main_ref} failed (exit {code})")
    paths = [path for path in output.decode("utf-8", "surrogateescape").split("\0") if path]
    verdict = classify_moved_paths(paths)
    code_paths = [path for path in paths if not is_docs_only_path(path)]
    reason = {
        VERDICT_UNMOVED: f"{main_ref} has not moved since {base}",
        VERDICT_DOCS_ONLY: f"every path {main_ref} changed since {base} is docs-only",
        VERDICT_FULL_GATE: f"{len(code_paths)} changed path(s) are not docs-only",
    }[verdict]
    return MainMoved(verdict, paths, reason)


_MAIN_MOVED_NEXT: Final[dict[str, str]] = {
    VERDICT_UNMOVED: "fast-forward main to the integration head",
    VERDICT_DOCS_ONLY: (
        "merge main into the integration branch, run "
        f"./scripts/qa/llm_qa.py {' '.join(DOCS_ONLY_TOOL_NAMES)}, "
        "then fast-forward main to the result"
    ),
    VERDICT_FULL_GATE: (
        "merge main into the integration branch and run ./scripts/qa/llm_qa.py all again"
    ),
}


def main_moved_command(args: Sequence[str], *, root: Path = PROJECT_ROOT) -> int:
    """``llm_qa.py main-moved BASE [MAIN]``: print the verdict and the next step."""
    if not args or len(args) > _MAX_MAIN_MOVED_ARGS or any(a.startswith("-") for a in args):
        print(
            f"Usage: llm_qa.py {MAIN_MOVED_COMMAND} BATCH_BASE [MAIN_REF]  "
            f"(MAIN_REF defaults to {_DEFAULT_MAIN_REF})",
            file=sys.stderr,
        )
        return EXIT_FAILURE
    base = args[0]
    main_ref = args[1] if len(args) == _MAX_MAIN_MOVED_ARGS else _DEFAULT_MAIN_REF
    try:
        outcome = main_moved(base, main_ref, root)
    except MainMovedError as exc:
        print(f"llm_qa: {MAIN_MOVED_COMMAND}: {exc}", file=sys.stderr)
        return EXIT_FAILURE
    print(f"VERDICT: {outcome.verdict}")
    print(f"  {outcome.reason}")
    for path in outcome.paths:
        marker = "docs" if is_docs_only_path(path) else "CODE"
        print(f"  [{marker}] {path}")
    print(f"NEXT: {_MAIN_MOVED_NEXT[outcome.verdict]}")
    print("CI on the pushed head is the second line, not a substitute for this gate.")
    return EXIT_FULL_GATE if outcome.verdict == VERDICT_FULL_GATE else EXIT_SUCCESS


def main() -> int:
    """Entry point."""
    args = sys.argv[1:]

    if args[:1] == [MAIN_MOVED_COMMAND]:
        return main_moved_command(args[1:])

    read_only = False
    if "--read-only" in args:
        read_only = True
        args.remove("--read-only")

    if not args or "--help" in args or "-h" in args:
        print(
            "Usage: llm_qa.py [--read-only] <tool|all|changed> [tool ...] "
            f"[{_BASE_OPTION} REF] [{_ALLOW_UNMAPPED_OPTION}]"
        )
        print(f"  {_SELECTION_ALL}: the full suite (the coordinator's gate)")
        print(f"  {_SELECTION_CHANGED}: targeted, {', '.join(CHANGED_TOOL_NAMES)}")
        print(f"  {_BASE_OPTION}, {_ALLOW_UNMAPPED_OPTION}: passed to changed_tests")
        print("  --read-only: summarise; a result recorded for another tree FAILS")
        print(
            f"  {MAIN_MOVED_COMMAND} BATCH_BASE [MAIN_REF]: may the batched gate skip "
            "a second full run? (runs no tools)"
        )
        print(f"Tools: {', '.join(TOOL_REGISTRY)}")
        return EXIT_SUCCESS

    args, forwarded, option_error = split_changed_options(args)
    if option_error is not None:
        print(f"llm_qa: {option_error}", file=sys.stderr)
        return EXIT_FAILURE

    tools, unknown = resolve_tools(args)
    if unknown:
        for name in unknown:
            print(f"Unknown tool: {name}")
        print(f"Available: {_SELECTION_ALL}, {_SELECTION_CHANGED}, {', '.join(TOOL_REGISTRY)}")
        return EXIT_FAILURE

    # The run lock guards the EXECUTING path only. `--read-only` runs no tools,
    # so it cannot contend -- and it is exactly the command someone reaches for
    # to inspect a run already in progress. Locking it would block the
    # diagnostic during the one situation the diagnostic is for.
    if read_only:
        return _run_tools(tools, read_only=True)

    # Every ``_python(...)`` tool needs the interpreter, so an unresolvable
    # venv means the run cannot happen: report it as the message it is, before
    # any tool starts, rather than as a traceback from the first one.
    try:
        venv_python()
    except VenvResolutionError as exc:
        print(f"llm_qa: {exc}", file=sys.stderr)
        return EXIT_FAILURE

    lock_file = run_lock_path()
    if not try_acquire_run_lock(str(lock_file)):
        print(busy_message(str(lock_file)), file=sys.stderr)
        return EXIT_BUSY

    return _run_tools(tools, read_only=False, forwarded=forwarded)


def _record_run(run_records: Mapping[str, tuple[int, bool]], before: dict[str, str] | None) -> None:
    """Record what this run certifies, and say at once when it certifies no tree."""
    if before is None:
        print(f"\n{_TREE_WARNING_LABEL} the working tree cannot be read, so nothing was recorded")
        return
    after = worktree_state(PROJECT_ROOT)
    state = before
    if after != before:
        state = {**before, _STATE_DIGEST: _TREE_CHANGED_DURING_RUN}
        print(
            f"\n{_TREE_WARNING_LABEL} the working tree changed during the run, so these "
            "results certify no tree: `--read-only` will read them STALE. Re-run on a "
            "still tree."
        )
    record_provenance(
        QA_OUTPUT_DIR,
        {
            name: run_record(
                state,
                exit_code=exit_code,
                passed=passed,
                output=QA_OUTPUT_DIR / TOOL_REGISTRY[name].json_file,
            )
            for name, (exit_code, passed) in run_records.items()
        },
    )


def _run_tools(tools: list[str], *, read_only: bool, forwarded: Sequence[str] = ()) -> int:
    """Run (or merely summarize) each tool and print the overall verdict.

    A run records, per tool, the tree it judged (before and after must agree,
    or the record matches no tree), the live verdict, the exit code and the
    hash of the report the tool wrote. A read-only summary fails a result
    recorded for another tree, a report that is not the one recorded, and
    re-applies the recorded exit code, so it can never pass what the live run
    failed.
    """
    all_passed = True
    tool_results: dict[str, tuple[bool, str]] = {}
    run_records: dict[str, tuple[int, bool]] = {}
    before = worktree_state(PROJECT_ROOT)
    recorded = read_provenance(QA_OUTPUT_DIR) if read_only else {}

    for name in tools:
        output = QA_OUTPUT_DIR / TOOL_REGISTRY[name].json_file
        exit_code: int | None = None
        stale: str | None = None
        if read_only:
            record = recorded.get(name)
            stale = stale_reason(record, before) or (
                output_reason(record, output) if record else None
            )
            recorded_exit = record.get(_RECORD_EXIT_CODE) if record else None
            exit_code = recorded_exit if isinstance(recorded_exit, int) else None
        else:
            # Removed first, so a tool that writes nothing leaves nothing: an
            # older green report must never stand in for this run's result.
            output.unlink(missing_ok=True)
            extra = forwarded if name == _CHANGED_TESTS_TOOL else ()
            exit_code = run_tool(name, extra)

        # Summarize from JSON, passing exit code for cross-check
        passed, summary = summarize_tool(name, exit_code=exit_code, stale=stale)
        tool_results[name] = (passed, summary)
        if exit_code is not None and not read_only:
            run_records[name] = (exit_code, passed)
        print(summary, end="")
        if not passed:
            all_passed = False

    if not read_only:
        _record_run(run_records, before)

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
