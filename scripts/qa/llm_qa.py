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
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, NamedTuple, TypeAlias

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts" / "qa"
#: The QA output directory relative to a checkout root. This script runs under
#: whatever python3 the shebang finds, before any venv, so it must not import
#: the daemon package to derive this.
QA_OUTPUT_RELATIVE: Final = Path("untracked") / "qa"
QA_OUTPUT_DIR = PROJECT_ROOT / QA_OUTPUT_RELATIVE

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
#: The host-wide QA lock stayed held for the whole bounded wait. 3 was the
#: retired "busy" refusal of the old per-checkout lock and stays unused, so an
#: old caller's `== 3` can never be misread as this.
EXIT_LOCK_TIMEOUT = 4

# Host-wide run lock (Plan 00262, widened by Plan 00475 Task 2.3). Concurrent
# runs share one `tests/` tree and one coverage.json, so their verdicts contend
# and NEITHER can be trusted -- a contended run can fail a check that is fine
# and pass one that is not. Since a green run gates commits and releases, that
# turns a blocking gate into a coin flip with no signal that it happened. More
# than that, the owner's rule is one QA process at a time on the host.
#
# ONE lock, not two: the file whole-suite pytest already uses,
# `<git-common-dir>/hooksdaemon-full-qa.lock`
# (`claude_code_hooks_daemon.qa.full_qa_lock`, `acquire_full_qa_lock.bash`).
# It lives in the COMMON git dir, so every worktree contends for the same file,
# and a tool this run starts recognises it as held (the conftest sink proves
# possession by an inherited descriptor on that file). This script runs under
# the system python3 before any venv and cannot import the package, so it opens
# the same file itself; `tests/unit/qa/test_llm_qa_host_lock.py` pins that the
# two agree on the path.
#
# NOT in /tmp: security standard B108.
HOST_LOCK_NAME: Final = "hooksdaemon-full-qa.lock"
#: The bash helper's variable, reused so one setting bounds every waiter.
WAIT_SECONDS_ENV: Final = "FULL_QA_LOCK_WAIT_SECONDS"
#: Names the descriptor a child inherits; `acquire_full_qa_lock.bash` reads it.
INHERITED_FD_ENV: Final = "FULL_QA_LOCK_INHERITED_FD"
DEFAULT_WAIT_SECONDS: Final = 600
_POLL_SECONDS: Final = 0.5
_REANNOUNCE_SECONDS: Final = 60
_PID_KEY: Final = "pid"
_CHECKOUT_KEY: Final = "checkout"
_UNKNOWN_HOLDER = "unknown (a run that predates this lock's stamp, or one that has exited)"
_LOCK_FILE_MODE = 0o644
_GIT_COMMON_DIR_TIMEOUT_SECONDS: Final = 60

#: Sink for a message; a print to stderr in `main`, a list append in tests.
Announcer: TypeAlias = Callable[[str], None]


class LockTimeout(Exception):
    """The host-wide QA lock stayed held for the whole bounded wait."""


def host_lock_path(root: Path = PROJECT_ROOT) -> Path:
    """The one lock file shared by every worktree of ``root``'s repository.

    Raises:
        OSError: ``root`` is not in a git worktree, or git could not be run.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=_GIT_COMMON_DIR_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError(f"git rev-parse --git-common-dir timed out in {root}") from exc
    if completed.returncode != 0:
        raise OSError(
            f"git rev-parse --git-common-dir failed in {root} "
            f"(exit {completed.returncode}): {completed.stderr.strip()}"
        )
    return Path(completed.stdout.strip()) / HOST_LOCK_NAME


def configured_wait_seconds() -> float:
    """The bounded wait, from ``FULL_QA_LOCK_WAIT_SECONDS`` (default 600).

    Raises:
        ValueError: the variable is set to something that is not a
            non-negative number. A typo must not silently become "wait for
            ever" or "do not wait".
    """
    raw = os.environ.get(WAIT_SECONDS_ENV)
    if raw is None:
        return float(DEFAULT_WAIT_SECONDS)
    message = f"{WAIT_SECONDS_ENV} must be a non-negative number of seconds, got {raw!r}"
    try:
        seconds = float(raw)
    except ValueError as exc:
        raise ValueError(message) from exc
    if not seconds >= 0:
        raise ValueError(message)
    return seconds


def _open_lock_fd(path: Path | str) -> int:
    """Open (creating if needed) the lock file and return a raw descriptor.

    A raw descriptor rather than a buffered text handle: a lock is a file
    DESCRIPTOR, and ``flock`` operates on one. ``os.open`` returns it
    non-inheritable (PEP 446), so a daemon a tool starts during the run cannot
    keep the lock; only :func:`run_tool` passes it on, and only to its child.
    """
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    return os.open(lock_path, os.O_RDWR | os.O_CREAT, _LOCK_FILE_MODE)


def _stamp_holder(fd: int, checkout: Path) -> None:
    """Record the holder's pid and checkout so a waiter can name them.

    Diagnostic only: the decision is ``flock``'s, never this file's contents.
    A holder that is not ``llm_qa.py`` (a bare whole-suite run) stamps nothing.
    """
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, f"{_PID_KEY}={os.getpid()}\n{_CHECKOUT_KEY}={checkout}\n".encode())


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Alive, owned by someone else.
        return True
    return True


def describe_holder(path: Path | str) -> str:
    """Who holds the lock, as far as the stamp says and the pid is still alive."""
    try:
        content = Path(path).read_text(encoding="utf-8")
    except OSError:
        return _UNKNOWN_HOLDER
    fields = dict(line.split("=", 1) for line in content.splitlines() if "=" in line)
    pid_text = fields.get(_PID_KEY, "")
    if not pid_text.isdigit() or not _pid_is_alive(int(pid_text)):
        return _UNKNOWN_HOLDER
    checkout = fields.get(_CHECKOUT_KEY, "unknown checkout")
    return f"pid {pid_text} in {checkout}"


def _waiting_message(path: Path, waited: float, wait_seconds: float) -> str:
    return (
        f"llm_qa: waiting for the host-wide QA lock (one QA process at a time), held by "
        f"{describe_holder(path)}; waited {waited:.0f}s of {wait_seconds:.0f}s. "
        f"Inspect the run with: llm_qa.py --read-only all"
    )


def timeout_message(path: Path, wait_seconds: float) -> str:
    """Explain the give-up well enough that nobody deletes the lock file."""
    return (
        f"QA lock still held after {wait_seconds:.0f}s: {path}\n"
        f"  Held by {describe_holder(path)}.\n"
        "\n"
        "Only one QA process may run on the host at a time, so this run did not start.\n"
        f"  - Wait for that run to finish, then re-run (or raise {WAIT_SECONDS_ENV}).\n"
        "  - Inspect the run in progress with:  llm_qa.py --read-only all\n"
        "  - If that pid is genuinely dead, the lock is ALREADY released: flock drops it\n"
        f"    on process exit, so do NOT delete {path}. A lock file on disk does not\n"
        "    mean a lock is held. A live orphan that inherited the descriptor can hold it.\n"
    )


def _try_lock(fd: int) -> bool:
    """One non-blocking lock attempt; whether it succeeded.

    Contention is the EXPECTED answer: another run holds the lock. Only this
    errno means "held" -- anything else (a bad path, a full disk) propagates
    rather than being reported as a busy host.
    """
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def acquire_host_lock(
    path: Path | str,
    *,
    wait_seconds: float,
    announce: Announcer,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Take the host-wide lock, queueing behind a holder for up to ``wait_seconds``.

    ``flock`` has no timeout, so this polls the non-blocking form. Announces
    once when it starts waiting and again each minute, naming the holder.

    Returns:
        The locked descriptor. The caller owns it and closes it to release; the
        kernel also drops the lock when the process dies, SIGKILL included.

    Raises:
        LockTimeout: the lock was still held after ``wait_seconds``.
    """
    lock_path = Path(path)
    fd = _open_lock_fd(lock_path)
    started = clock()
    next_announcement = started
    try:
        while True:
            if _try_lock(fd):
                return fd
            now = clock()
            if now - started >= wait_seconds:
                raise LockTimeout(timeout_message(lock_path, wait_seconds))
            if now >= next_announcement:
                announce(_waiting_message(lock_path, now - started, wait_seconds))
                next_announcement = now + _REANNOUNCE_SECONDS
            sleep(min(_POLL_SECONDS, wait_seconds - (now - started)))
    except BaseException:
        os.close(fd)
        raise


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
    state: dict[str, str], *, exit_code: int, passed: bool, output_sha256: str | None
) -> ProvenanceRecord:
    """One tool's entry: the tree it judged, its live verdict and its report's hash.

    ``output_sha256`` is taken when the tool returns, not at the end of the
    run, so a later tool that rewrites this report cannot be certified as it.
    """
    return {
        **state,
        _RECORD_PASSED: passed,
        _RECORD_EXIT_CODE: exit_code,
        _RECORD_OUTPUT_DIGEST: output_sha256,
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
    """Configuration for a single QA tool.

    ``live_daemon`` marks a tool that probes this checkout's RUNNING daemon;
    :func:`ensure_live_daemon` runs before it (00422 N27).
    """

    command: list[str]
    json_file: str
    jq_hint: str
    live_daemon: bool = False


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
    # A live consumer through tests/acceptance: its daemon fixtures skip with
    # no socket, and a skip in a RELEASING.md Step 12.0 gate is a failure.
    # run_test_matrix.py runs run_tests.sh AND the suite under every other
    # Python in CI's matrix (00466 N110), so the gate is not narrower than CI.
    "tests": ToolConfig(
        command=_python("run_test_matrix.py"),
        json_file="tests.json",
        jq_hint="jq '.tests[] | select(.outcome == \"failed\") | .name'",
        live_daemon=True,
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
    "signal_targets": ToolConfig(
        command=_python("check_signal_targets.py", "--json"),
        json_file="signal_targets.json",
        jq_hint="jq '.violations[] | {file, line, rule, message}'",
    ),
    "skip_list_substring": ToolConfig(
        command=_python("check_skip_list_substring.py", "--json"),
        json_file="skip_list_substring.json",
        jq_hint="jq '.violations[] | {file, line, rule, message}'",
    ),
    "unreachable_handle_branch": ToolConfig(
        command=_python("check_unreachable_handle_branch.py", "--json"),
        json_file="unreachable_handle_branch.json",
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
    # Plan 00402: a restart never rewrites .claude/HOOKS-DAEMON.md, so this is
    # what catches a handler change that left it stale.
    "generated_doc_drift": ToolConfig(
        command=_python("check_generated_doc_drift.py", "--json"),
        json_file="generated_doc_drift.json",
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
        live_daemon=True,
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


def _interpreter_lines(data: QaReport) -> str:
    """One line per interpreter run, so the versions tested are stated, not implied.

    run_test_matrix.py (00466 N110) records every run it owed in
    ``interpreters``; a run that never happened carries its ``error``.
    """
    lines = []
    for entry in data.get("interpreters", []):
        head = f"py{entry.get('version', '?')} {entry.get('scope', '?')}"
        if entry.get("error"):
            lines.append(f"{head}: NOT RUN - {entry['error']}")
            continue
        verdict = "ok" if entry.get("passed_all") else "FAILED"
        lines.append(
            f"{head}: {verdict}, {entry.get('passed', 0)} passed, {entry.get('failed', 0)} "
            f"failed, {entry.get('errors', 0)} errored in {entry.get('duration_seconds', 0)}s"
        )
    if not lines:
        return ""
    return "\n   " + "\n   ".join(lines)


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
    line += _interpreter_lines(data)

    # Name a red run the failed/errored counts alone do not explain — a
    # coverage-threshold miss exits non-zero over "0 failed" and a coverage
    # percentage that rounds to looking fine (94.99% displays as "95.0%")
    # (00466 N118). Without this the gate reported failure and named nothing.
    unnamed_reason = s.get("unnamed_failure_reason")
    if unnamed_reason:
        line += f"\n   cause: {unnamed_reason}"
    return line + _named_failures(data, "tests.json")


def _named_failures(data: QaReport, json_file: str) -> str:
    """The failing test names, one per line, or "" when there are none.

    Named rather than counted (Plan 00226). A count alone forces a full re-run
    to find out what broke, and a re-run may not reproduce an order-dependent
    failure — during Plan 00224 one of two real failures was never
    identified. Bounded so a mass breakage cannot flood the artifact. Each
    carries its first error line when one was recorded (00466 N196): ten
    errored tests named with no cause sent the reader to a raw shard log.
    """
    failed = [t for t in data.get("tests", []) if t.get("outcome") == "failed" and t.get("name")]
    names = [f"{t['name']} - {t['reason']}" if t.get("reason") else t["name"] for t in failed]
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
    "signal_targets": _summarize_violations,
    "skip_list_substring": _summarize_violations,
    "unreachable_handle_branch": _summarize_violations,
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
    "generated_doc_drift": _summarize_violations,
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


# This checkout's own wrapper: in a worktree it resolves the worktree's daemon.
DAEMON_CLI: Final[Path] = PROJECT_ROOT / "bin" / "hooks-daemon"
DAEMON_CLI_TIMEOUT_SECONDS: Final[int] = 120

_DAEMON_STARTED_LABEL: Final[str] = "⚙️  DAEMON STARTED:"
_DAEMON_START_FAILED_LABEL: Final[str] = "⚠️  DAEMON START FAILED:"


def _daemon_cli(subcommand: str) -> subprocess.CompletedProcess[str]:
    """Run ``bin/hooks-daemon <subcommand>`` for this checkout, capturing output."""
    return subprocess.run(
        [str(DAEMON_CLI), subcommand],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=DAEMON_CLI_TIMEOUT_SECONDS,
        check=False,
    )


def ensure_live_daemon(tool: str) -> str | None:
    """Start this checkout's daemon if it is not running, before ``tool`` probes it.

    A stopped daemon is an ordinary state, not a defect: it exits after
    ``idle_timeout_seconds`` without hook traffic, and a worktree's daemon gets
    none while its session's hooks go to the main checkout's daemon, so a
    restart at the start of a long run is gone by its end (00422 N27). Every
    real hook starts it on demand; this does the same. It never RESTARTS a
    running daemon, so a stale one still fails the freshness check.

    Returns:
        None when the daemon was already running, otherwise a line to print
        saying it was started or why it could not be.
    """
    try:
        if _daemon_cli("status").returncode == 0:
            return None
        started = _daemon_cli("start")
    except subprocess.TimeoutExpired:
        return (
            f"   {_DAEMON_START_FAILED_LABEL} {DAEMON_CLI} did not answer within "
            f"{DAEMON_CLI_TIMEOUT_SECONDS}s before {tool}"
        )
    if started.returncode == 0:
        return (
            f"   {_DAEMON_STARTED_LABEL} no daemon was running before {tool} (it stops "
            f"after idle_timeout_seconds without hook traffic), so llm_qa started one"
        )
    output = f"{started.stdout}{started.stderr}".strip()
    return (
        f"   {_DAEMON_START_FAILED_LABEL} no daemon was running before {tool}, and "
        f"`bin/hooks-daemon start` failed (exit {started.returncode}): {output}"
    )


def run_tool(name: str, extra_args: Sequence[str] = (), *, lock_fd: int | None = None) -> int:
    """Run a QA tool, suppressing its stdout/stderr. Returns exit code.

    ``lock_fd`` is the host-wide lock this run holds. The child inherits that
    very descriptor (``pass_fds``), which is how a whole-suite pytest under it
    proves it holds the lock and does not wait on its own parent. The
    environment variable is only a hint at which descriptor to test, for the
    bash side; the proof is ``flock`` on the descriptor itself.
    """
    config = TOOL_REGISTRY[name]
    env = None if lock_fd is None else {**os.environ, INHERITED_FD_ENV: str(lock_fd)}
    result = subprocess.run(
        [*resolved_command(config), *extra_args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(PROJECT_ROOT),
        env=env,
        pass_fds=() if lock_fd is None else (lock_fd,),
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
_RANGE_OPTION: Final[str] = "--range"
_ALLOW_UNMAPPED_OPTION: Final[str] = "--allow-unmapped"
_CHANGED_TESTS_TOOL: Final[str] = "changed_tests"
#: Forwarded options that take a value, spelt ``--opt VALUE`` or ``--opt=VALUE``.
_CHANGED_VALUE_OPTIONS: Final[tuple[str, ...]] = (_BASE_OPTION, _RANGE_OPTION)


def split_changed_options(args: list[str]) -> tuple[list[str], list[str], str | None]:
    """Take ``--base REF``, ``--range A..B`` and ``--allow-unmapped`` out for ``changed_tests``.

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
        option, separator, value = argument.partition("=")
        if argument == _ALLOW_UNMAPPED_OPTION:
            forwarded.append(argument)
        elif argument in _CHANGED_VALUE_OPTIONS:
            if index >= len(args) or args[index].startswith("-"):
                return args, [], f"{argument} needs a value"
            forwarded.extend([argument, args[index]])
            index += 1
        elif separator and option in _CHANGED_VALUE_OPTIONS:
            forwarded.extend([option, value])
        else:
            remaining.append(argument)
    if forwarded:
        tools, _ = resolve_tools(remaining)
        if _CHANGED_TESTS_TOOL not in tools:
            return (
                args,
                [],
                (
                    f"{_BASE_OPTION}, {_RANGE_OPTION} and {_ALLOW_UNMAPPED_OPTION} apply to "
                    f"`{_SELECTION_CHANGED}` (changed_tests) only"
                ),
            )
    return remaining, forwarded, None


# ── main-moved: what must re-run when main moves during a batch ─────

#: The subcommand (CLAUDE/QA.md, "The Batched Integration Gate"). ``main``
#: moved after the batch base; the verdict names the recheck that makes the
#: green run cover what would land.
MAIN_MOVED_COMMAND: Final[str] = "main-moved"
_START_OPTION: Final[str] = "--start"
_RESTART_OPTION: Final[str] = "--restart"
_ADVANCE_OPTION: Final[str] = "--advance"
_FINISH_OPTION: Final[str] = "--finish"
#: Every accepted option set; anything else is a usage error.
_MAIN_MOVED_OPTION_SETS: Final[frozenset[frozenset[str]]] = frozenset(
    {
        frozenset(),
        frozenset({_START_OPTION}),
        frozenset({_START_OPTION, _RESTART_OPTION}),
        frozenset({_ADVANCE_OPTION}),
        frozenset({_FINISH_OPTION}),
    }
)
_MAIN_MOVED_USAGE: Final[str] = (
    f"Usage: llm_qa.py {MAIN_MOVED_COMMAND} [{_START_OPTION} [{_RESTART_OPTION}] | "
    f"{_ADVANCE_OPTION} | {_FINISH_OPTION}] [MAIN_REF]  (MAIN_REF defaults to main)"
)
_DEFAULT_MAIN_REF: Final[str] = "main"

VERDICT_UNMOVED: Final[str] = "unmoved"
VERDICT_DOCS_ONLY: Final[str] = "docs-only"
VERDICT_TARGETED: Final[str] = "targeted"
VERDICT_FULL_GATE: Final[str] = "full-gate"
#: The integration head is not the head a gate passed on a clean tree.
VERDICT_HEAD_MOVED: Final[str] = "head-moved"
#: Each verdict is an answer, not a failure, so each has its own exit code and
#: a script can branch on it.
EXIT_FULL_GATE: Final[int] = 4
EXIT_DOCS_ONLY: Final[int] = 5
EXIT_TARGETED: Final[int] = 6
EXIT_HEAD_MOVED: Final[int] = 7
_VERDICT_EXIT: Final[Mapping[str, int]] = {
    VERDICT_UNMOVED: EXIT_SUCCESS,
    VERDICT_DOCS_ONLY: EXIT_DOCS_ONLY,
    VERDICT_TARGETED: EXIT_TARGETED,
    VERDICT_FULL_GATE: EXIT_FULL_GATE,
    VERDICT_HEAD_MOVED: EXIT_HEAD_MOVED,
}

#: What a docs-only move re-runs: checks that read documents and change nothing.
#: The last four read the WHOLE tree, and a test runs each on this repository
#: (``test_repo_hygiene_check`` and the like) while naming no file, so no
#: mapping selects that test for a moved page: the checker runs instead.
#: ``format`` is black, which checks Python and rewrites files, so it is not here.
DOCS_ONLY_TOOL_NAMES: Final[list[str]] = [
    "plan_qa",
    "docs_qa",
    "british_english",
    "sensitive_content",
    "repo_hygiene",
    "doc_truth",
    "doc_snippets",
    "handler_reference",
]

#: THE runtime-read set, defined here only. Runtime code reads these, so no
#: test mapping can clear a change to them: the guidance injector and every
#: session read root ``CLAUDE.md``; the upgrade path reads ``CHANGELOG.md``,
#: ``RELEASES/`` and ``CLAUDE/UPGRADES/``; Claude Code reads ``.claude/``
#: (agents, skills, rules, settings, this project's config and handlers).
RUNTIME_READ_FILES: Final[frozenset[str]] = frozenset({"CLAUDE.md", "CHANGELOG.md"})
RUNTIME_READ_ROOTS: Final[tuple[str, ...]] = (".claude/", "RELEASES/", "CLAUDE/UPGRADES/")
_DOCS_SUFFIX: Final[str] = ".md"
_CODE_ROOTS: Final[tuple[str, ...]] = ("src/", "tests/", "scripts/")
_SYMLINK_MODE: Final[str] = "120000"
#: ``run_changed_tests``' reason for a file no test, rule or dependent covers.
_UNCOVERED: Final[str] = "uncovered"

#: How one moved path is judged.
PATH_DOCS: Final[str] = "docs"
PATH_TESTED: Final[str] = "tested"
PATH_FULL: Final[str] = "full"
_PATH_KINDS: Final[tuple[str, ...]] = (PATH_FULL, PATH_TESTED, PATH_DOCS)

#: The batch base and the certified head live in git refs, not shell
#: variables: they must survive between Bash calls, and refs are shared by
#: every worktree of the checkout. The kind comes BEFORE the branch, so the
#: refs mirror the branch namespace and cannot collide where branches cannot.
_BASE_REF_TEMPLATE: Final[str] = "refs/integration/base/{branch}"
_CERTIFIED_REF_TEMPLATE: Final[str] = "refs/integration/certified/{branch}"
_SELECT_TIMEOUT_SECONDS: Final[int] = 600
_RANGE_REPORT_KEY: Final[str] = "range"
_MERGE_PARENTS: Final[int] = 2
#: ``git status --porcelain``: "XY path", and X or Y of R/C for a rename/copy.
_PORCELAIN_PATH_OFFSET: Final[int] = 3
_PORCELAIN_COPY_OR_RENAME: Final[frozenset[str]] = frozenset({"R", "C"})


class MainMovedError(RuntimeError):
    """No verdict can be given, or the base cannot advance; the message says why."""


class MovedPath(NamedTuple):
    """One path the move changed, and whether either side of it is a symlink."""

    path: str
    symlink: bool


class PathVerdict(NamedTuple):
    """How one moved path is judged (``PATH_DOCS``/``TESTED``/``FULL``), and why."""

    path: str
    kind: str
    why: str


class MainMoved(NamedTuple):
    """The verdict for ``base..main``, each path's judgement, and the reason.

    ``head`` is the certified head, when HEAD is it: the exact commit that
    lands. ``recheck_passed`` means ``main`` is already merged into it and
    the recheck the verdict names has already passed on this tree, so only
    ``--advance`` is left. ``merge_first`` means HEAD lacks the base itself.
    """

    verdict: str
    base: str
    main: str
    paths: list[PathVerdict]
    reason: str
    head: str = ""
    recheck_passed: bool = False
    merge_first: bool = False


#: ``(root, "A..B")`` to the ``run_changed_tests --select-only`` payload.
Selector = Callable[[Path, str], Mapping[str, Any]]


def is_runtime_read(path: str) -> bool:
    """Whether runtime code reads ``path``, so only the full gate can clear it."""
    return path in RUNTIME_READ_FILES or path.startswith(RUNTIME_READ_ROOTS)


def _is_document(path: str) -> bool:
    return path.endswith(_DOCS_SUFFIX) and not path.startswith(_CODE_ROOTS)


def _needs_mapping(moved: MovedPath) -> bool:
    return not moved.symlink and not is_runtime_read(moved.path) and _is_document(moved.path)


def judge_path(moved: MovedPath, selection: Mapping[str, Any]) -> PathVerdict:
    """Judge one moved path; ``selection`` is the mapper's answer for the range.

    Only a document the mapper covers with no test and no tool beyond the doc
    tools is docs-only. A document tests read is targeted. Everything else,
    and anything the mapper cannot target or did not report, is the full gate.
    """
    path = moved.path
    if is_runtime_read(path):
        return PathVerdict(path, PATH_FULL, "read at runtime")
    if moved.symlink:
        return PathVerdict(path, PATH_FULL, "a symlink, so judged as what it points at")
    if not _is_document(path):
        return PathVerdict(path, PATH_FULL, "not a document outside src/, tests/ and scripts/")
    reasons: Mapping[str, Any] = selection.get("unmapped_reasons", {})
    if path in reasons:
        reason = str(reasons[path].get("reason", ""))
        if reason == _UNCOVERED:
            return PathVerdict(path, PATH_DOCS, "no test reads it")
        return PathVerdict(path, PATH_FULL, f"the mapper cannot target it ({reason})")
    entry = next((item for item in selection.get("mapping", []) if item.get("file") == path), None)
    if entry is None:
        return PathVerdict(path, PATH_FULL, "the mapper did not report it")
    tests = list(entry.get("tests", []))
    if tests:
        return PathVerdict(path, PATH_TESTED, f"{len(tests)} test file(s) read it")
    other_tools = [tool for tool in entry.get("tools", []) if tool not in DOCS_ONLY_TOOL_NAMES]
    if other_tools:
        return PathVerdict(path, PATH_TESTED, f"checked by {', '.join(other_tools)}")
    return PathVerdict(path, PATH_DOCS, "no test reads it")


def combine_verdicts(judged: Sequence[PathVerdict]) -> str:
    """One full path means the full gate; one tested document means targeted.

    New commits that change no file (a commit and its revert) are docs-only,
    not unmoved: ``--ff-only`` refuses until ``main`` is merged in.
    """
    kinds = {verdict.kind for verdict in judged}
    if PATH_FULL in kinds:
        return VERDICT_FULL_GATE
    if PATH_TESTED in kinds:
        return VERDICT_TARGETED
    return VERDICT_DOCS_ONLY


def required_tools(verdict: str) -> list[str]:
    """What must have passed on the merged head before the base may advance."""
    if verdict == VERDICT_DOCS_ONLY:
        return list(DOCS_ONLY_TOOL_NAMES)
    if verdict == VERDICT_TARGETED:
        extra = [tool for tool in DOCS_ONLY_TOOL_NAMES if tool not in CHANGED_TOOL_NAMES]
        return [*CHANGED_TOOL_NAMES, *extra]
    if verdict in (VERDICT_FULL_GATE, VERDICT_HEAD_MOVED):
        return list(ALL_TOOL_NAMES)
    return []


def _git_text(args: list[str], root: Path, git: GitBytesRunner, failure: str) -> str:
    code, output = git(args, root)
    if code != 0:
        raise MainMovedError(f"{failure} (git {' '.join(args)} exited {code})")
    return output.decode().strip()


def _commit_of(ref: str, root: Path, git: GitBytesRunner) -> str:
    return _git_text(
        ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        root,
        git,
        f"`{ref}` does not name a commit",
    )


def integration_branch(root: Path, git: GitBytesRunner = _run_git_bytes) -> str:
    """The checked-out branch, which the batch base is kept for."""
    code, output = git(["symbolic-ref", "--quiet", "--short", "HEAD"], root)
    branch = output.decode().strip()
    if code != 0 or not branch:
        raise MainMovedError(
            "HEAD is detached: the batch base is kept per integration branch, so run "
            "this on the integration branch"
        )
    return branch


def batch_base_ref(root: Path, git: GitBytesRunner = _run_git_bytes) -> str:
    """The ref holding this integration branch's batch base."""
    return _BASE_REF_TEMPLATE.format(branch=integration_branch(root, git))


def certified_ref(root: Path, git: GitBytesRunner = _run_git_bytes) -> str:
    """The ref holding the head a gate last passed on, for this integration branch."""
    return _CERTIFIED_REF_TEMPLATE.format(branch=integration_branch(root, git))


def _is_ancestor(older: str, newer: str, root: Path, git: GitBytesRunner) -> bool:
    code, _ = git(["merge-base", "--is-ancestor", older, newer], root)
    if code not in (0, 1):
        raise MainMovedError(f"git merge-base --is-ancestor {older} {newer} exited {code}")
    return code == 0


def _ref_commit(ref: str, root: Path, git: GitBytesRunner) -> str | None:
    """The commit ``ref`` holds, or None when it is not set."""
    code, output = git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], root)
    return output.decode().strip() if code == 0 else None


def _recorded_base(root: Path, git: GitBytesRunner) -> tuple[str, str]:
    ref = batch_base_ref(root, git)
    base = _ref_commit(ref, root, git)
    if base is None:
        raise MainMovedError(
            f"no batch base is recorded in {ref}: run `llm_qa.py {MAIN_MOVED_COMMAND} "
            f"{_START_OPTION}` on the integration branch when the batch is built"
        )
    return ref, base


def uncommitted_paths(root: Path, git: GitBytesRunner = _run_git_bytes) -> list[str]:
    """Tracked changes and untracked, not-ignored files: what ``--ff-only`` leaves behind."""
    code, output = git(["status", "--porcelain", "-z", "--untracked-files=all"], root)
    if code != 0:
        raise MainMovedError(f"git status exited {code}, so the tree cannot be judged clean")
    entries = iter(output.decode("utf-8", "surrogateescape").split("\0"))
    paths = []
    for entry in entries:
        if not entry:
            continue
        paths.append(entry[_PORCELAIN_PATH_OFFSET:])
        if _PORCELAIN_COPY_OR_RENAME & set(entry[:_PORCELAIN_PATH_OFFSET]):
            # A rename or copy is followed by its source path, which carries no status.
            next(entries, None)
    return paths


def _refuse_uncommitted(root: Path, git: GitBytesRunner, action: str) -> None:
    dirty = uncommitted_paths(root, git)
    if dirty:
        shown = ", ".join(dirty[:3]) + (", ..." if len(dirty) > 3 else "")
        raise MainMovedError(
            f"{action}: the tree has uncommitted changes ({shown}), and --ff-only lands "
            "only HEAD. Commit them (or remove them), then run the check again"
        )


def _delete_ref(ref: str, root: Path, git: GitBytesRunner) -> None:
    if _ref_commit(ref, root, git) is not None:
        _git_text(["update-ref", "-d", ref], root, git, f"could not delete {ref}")


def start_batch(
    root: Path,
    main_ref: str = _DEFAULT_MAIN_REF,
    *,
    restart: bool = False,
    git: GitBytesRunner = _run_git_bytes,
) -> str:
    """Record the newest ``main_ref`` commit this branch contains as the batch base.

    A base already recorded is kept: a second start would move it forward past
    code ``main`` added since, so that code would never meet the full gate.
    ``restart`` is for a batch rebuilt from scratch only; it also clears the
    certified head, so the full gate has to pass again.

    Raises:
        MainMovedError: a base exists and ``restart`` is not set, or git failed.
    """
    ref = batch_base_ref(root, git)
    existing = _ref_commit(ref, root, git)
    if existing is not None and not restart:
        raise MainMovedError(
            f"a batch base is already recorded in {ref} ({existing[:_SHORT_SHA]}). Another "
            "start would move it past whatever main added since, and skip the full gate for "
            f"it. Run {MAIN_MOVED_COMMAND} to judge that movement instead. Only for a batch "
            f"rebuilt from scratch: {_START_OPTION} {_RESTART_OPTION}, which also clears the "
            "certified head, so `llm_qa.py all` must pass again"
        )
    main = _commit_of(main_ref, root, git)
    base = _git_text(
        ["merge-base", "HEAD", main], root, git, f"this branch shares no history with {main_ref}"
    )
    _delete_ref(certified_ref(root, git), root, git)
    _git_text(["update-ref", ref, base], root, git, f"could not record {ref}")
    return base


def certify_head(
    root: Path, judged: dict[str, str] | None, *, git: GitBytesRunner = _run_git_bytes
) -> str | None:
    """Record HEAD as the head the full gate passed on, and return it.

    ``judged`` is the tree the passing run judged; it must still be the tree,
    and the tree must be clean, because ``--ff-only`` lands only HEAD. Outside
    a batch (no branch, or no base recorded) nothing is recorded: None.

    Raises:
        MainMovedError: the tree is dirty or changed since the run judged it.
    """
    code, _ = git(["symbolic-ref", "--quiet", "HEAD"], root)
    if code != 0 or _ref_commit(batch_base_ref(root, git), root, git) is None:
        return None
    _refuse_uncommitted(root, git, "the gate cannot certify this head")
    if judged is None or worktree_state(root, git=git) != judged:
        raise MainMovedError(
            "the gate cannot certify this head: the tree changed since the run judged it"
        )
    head = _commit_of("HEAD", root, git)
    ref = certified_ref(root, git)
    _git_text(["update-ref", ref, head], root, git, f"could not record {ref}")
    return head


def _head_uncertified(root: Path, git: GitBytesRunner) -> str | None:
    """Why HEAD is not the head a gate passed on a clean tree, or None when it is."""
    certified = _ref_commit(certified_ref(root, git), root, git)
    if certified is None:
        return (
            "no full gate has passed on this branch since the batch base was recorded: "
            f"run `llm_qa.py {_SELECTION_ALL}` on a clean tree"
        )
    dirty = uncommitted_paths(root, git)
    if dirty:
        return (
            f"the tree has uncommitted changes ({', '.join(dirty[:3])}), which --ff-only "
            f"would not land: commit or remove them, then run `llm_qa.py {_SELECTION_ALL}`"
        )
    head = _commit_of("HEAD", root, git)
    if head != certified:
        return (
            f"HEAD {head[:_SHORT_SHA]} is not the head the gate passed "
            f"({certified[:_SHORT_SHA]}): something was committed or merged after it. "
            f"Run `llm_qa.py {_SELECTION_ALL}` on this head"
        )
    return None


def moved_paths(
    base: str, tip: str, root: Path, git: GitBytesRunner = _run_git_bytes
) -> list[MovedPath]:
    """Every path ``git diff base tip`` changed, a rename as both of its paths."""
    code, output = git(["diff", "--raw", "--no-renames", "--no-abbrev", "-z", base, tip], root)
    if code != 0:
        raise MainMovedError(f"git diff {base} {tip} exited {code}")
    fields = output.decode("utf-8", "surrogateescape").split("\0")
    moved: list[MovedPath] = []
    for header, path in zip(fields[0::2], fields[1::2], strict=False):
        if not header.startswith(":") or not path:
            continue
        modes = header[1:].split()[:2]
        moved.append(MovedPath(path, _SYMLINK_MODE in modes))
    return moved


def select_range(root: Path, spec: str) -> Mapping[str, Any]:
    """Ask ``run_changed_tests`` which tests read each file ``spec`` changed."""
    try:
        command = [
            str(venv_python()),
            str(SCRIPTS_DIR / "run_changed_tests.py"),
            "--root",
            str(root),
            "--range",
            spec,
            "--select-only",
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=_SELECT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired, VenvResolutionError) as exc:
        raise MainMovedError(f"run_changed_tests --select-only did not run: {exc}") from exc
    if completed.returncode != 0:
        raise MainMovedError(
            f"run_changed_tests --select-only failed: {completed.stderr.strip() or 'no output'}"
        )
    try:
        payload = json.loads(completed.stdout)
    except ValueError as exc:
        raise MainMovedError(f"run_changed_tests --select-only printed no JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise MainMovedError("run_changed_tests --select-only printed no selection")
    return payload


def _judge_range(
    base: str, tip: str, root: Path, git: GitBytesRunner, select: Selector
) -> tuple[str, list[PathVerdict], str]:
    if not _is_ancestor(base, tip, root, git):
        return (
            VERDICT_FULL_GATE,
            [],
            f"the base {base[:_SHORT_SHA]} is not an ancestor of {tip[:_SHORT_SHA]}: main "
            "was rewritten, so there is no change set to judge",
        )
    moved = moved_paths(base, tip, root, git)
    selection = select(root, f"{base}..{tip}") if any(map(_needs_mapping, moved)) else {}
    judged = [judge_path(path, selection) for path in moved]
    if not judged:
        reason = "new commits that change no file; --ff-only still needs main merged in"
    else:
        counts = {kind: sum(1 for j in judged if j.kind == kind) for kind in _PATH_KINDS}
        reason = (
            f"{len(judged)} moved path(s): {counts[PATH_FULL]} need the full gate, "
            f"{counts[PATH_TESTED]} are read by tests, {counts[PATH_DOCS]} are documents only"
        )
    return combine_verdicts(judged), judged, reason


def main_moved(
    root: Path,
    main_ref: str = _DEFAULT_MAIN_REF,
    *,
    git: GitBytesRunner = _run_git_bytes,
    select: Selector = select_range,
    qa_dir: Path | None = None,
) -> MainMoved:
    """The verdict for what would land: this head, plus what ``main_ref`` changed.

    The integration head comes first: unless HEAD is the head a gate passed on
    a clean tree, the verdict is ``head-moved`` whatever ``main`` did, save
    when all HEAD adds to that head is ``main`` merged in, which is judged as
    that movement (review 6 m8). It is also ``head-moved`` when ``main`` is
    still the base but HEAD does not contain it (review 5 n2): ``--ff-only``
    would refuse, and running the check again would only say the same thing.

    Raises:
        MainMovedError: no base is recorded, a ref does not resolve, or git or
            the mapper cannot answer.
    """
    _, base = _recorded_base(root, git)
    main = _commit_of(main_ref, root, git)
    head_reason = _head_uncertified(root, git)
    if head_reason is not None:
        merged_in = _main_merged_since_certified(root, main_ref, base, main, git, select, qa_dir)
        return merged_in or MainMoved(VERDICT_HEAD_MOVED, base, main, [], head_reason)
    head = _commit_of("HEAD", root, git)
    contains_main = _is_ancestor(main, head, root, git)
    if main == base and not contains_main:
        reason = (
            f"HEAD does not contain {main_ref} {main[:_SHORT_SHA]}, the batch base: its merge "
            f"was backed out, so --ff-only would refuse. Merge it back in, then run "
            f"`llm_qa.py {_SELECTION_ALL}` on the merged head"
        )
        return MainMoved(VERDICT_HEAD_MOVED, base, main, [], reason, head, merge_first=True)
    if main == base:
        reason = f"{main_ref} is still the batch base"
        return MainMoved(VERDICT_UNMOVED, base, main, [], reason, head)
    verdict, judged, reason = _judge_range(base, main, root, git, select)
    qa = qa_dir if qa_dir is not None else root / QA_OUTPUT_RELATIVE
    recheck_passed = contains_main and not _uncertified(verdict, (base, main), root, qa, git)
    return MainMoved(verdict, base, main, judged, reason, head, recheck_passed)


def certification_reason(
    record: ProvenanceRecord | None, current: dict[str, str] | None, output: Path
) -> str | None:
    """Why a recorded result does not certify a PASS on the current tree, or None."""
    stale = stale_reason(record, current)
    if stale is not None or record is None:
        return stale
    return output_reason(record, output) or recorded_failure_reason(record)


def recorded_failure_reason(record: ProvenanceRecord) -> str | None:
    """Why the recorded run itself failed, or None when it passed."""
    if record.get(_RECORD_PASSED) is not True or record.get(_RECORD_EXIT_CODE) != 0:
        return "the recorded run did not pass; fix it and re-run the tool"
    return None


def _recorded_range(report: Path) -> str | None:
    """The ``--range`` a ``changed_tests`` report was run over, or None for none."""
    if not report.is_file():
        return None
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MainMovedError(f"{report} cannot be read as a report: {exc}") from exc
    value = data.get(_RANGE_REPORT_KEY) if isinstance(data, dict) else None
    return value if isinstance(value, str) else None


def _range_commits(spec: str, root: Path, git: GitBytesRunner) -> tuple[str, str] | None:
    """Both ends of ``A..B`` as commits, or None when it is not such a range."""
    older, separator, newer = spec.partition("..")
    if not separator or not older or not newer or newer.startswith("."):
        return None
    ends = [_ref_commit(end, root, git) for end in (older, newer)]
    if ends[0] is None or ends[1] is None:
        return None
    return ends[0], ends[1]


def _uncertified(
    verdict: str, commits: tuple[str, str], root: Path, qa_dir: Path, git: GitBytesRunner
) -> list[str]:
    current = worktree_state(root, git=git)
    records = read_provenance(qa_dir)
    problems = []
    for name in required_tools(verdict):
        output = qa_dir / TOOL_REGISTRY[name].json_file
        reason = certification_reason(records.get(name), current, output)
        if reason is not None:
            problems.append(f"{name}: {reason}")
    if verdict == VERDICT_TARGETED and not problems:
        ran = _recorded_range(qa_dir / TOOL_REGISTRY[_CHANGED_TESTS_TOOL].json_file)
        if ran is None or _range_commits(ran, root, git) != commits:
            problems.append(
                f"{_CHANGED_TESTS_TOOL} ran over {ran or 'no range'}; run it with "
                f"{_RANGE_OPTION} {commits[0]}..{commits[1]}"
            )
    return problems


def _merge_edits(merge: str, root: Path, git: GitBytesRunner) -> list[str]:
    """Paths ``merge`` holds that differ from git's own merge of its parents.

    Those are a conflict's resolution, or an edit made inside the merge.
    """
    parents = _git_text(
        ["rev-list", "--parents", "-n", "1", merge], root, git, f"cannot read {merge}"
    ).split()[1:]
    if len(parents) != _MERGE_PARENTS:
        raise MainMovedError(
            f"{merge[:_SHORT_SHA]} merges {len(parents)} parents; only a two-parent merge "
            f"of main can be judged. Run `llm_qa.py {_SELECTION_ALL}`"
        )
    code, output = git(["merge-tree", "--write-tree", "--no-messages", *parents], root)
    if code not in (0, 1):
        raise MainMovedError(f"git merge-tree for {merge[:_SHORT_SHA]} exited {code}")
    automatic = output.decode().split("\n", 1)[0].strip()
    names = _git_text(
        ["diff", "--name-only", "-z", "--no-renames", automatic, merge],
        root,
        git,
        f"cannot compare {merge[:_SHORT_SHA]} with its automatic merge",
    )
    return [name for name in names.split("\0") if name]


def _work_beside_main(
    certified: str, merged: str, moved: Sequence[str], root: Path, git: GitBytesRunner
) -> str | None:
    """Why HEAD holds something since ``certified`` that is not ``main`` merged in, or None.

    A commit that is not a merge is new work no recheck covers, and so is an
    edit inside a merge on a path ``main`` did not move: both need the gate.
    """
    if not _is_ancestor(certified, "HEAD", root, git):
        return (
            f"the certified head {certified[:_SHORT_SHA]} is not in this branch's history: "
            f"run `llm_qa.py {_SELECTION_ALL}`"
        )
    listed = _git_text(
        ["rev-list", "--parents", f"{certified}..HEAD", "--not", merged],
        root,
        git,
        "cannot list the commits since the certified head",
    )
    moved_set = set(moved)
    for line in filter(None, listed.splitlines()):
        commit, *parents = line.split()
        if len(parents) < _MERGE_PARENTS:
            return (
                f"HEAD holds {commit[:_SHORT_SHA]}, a commit that is not a merge of main: "
                f"the gate never judged it. Run `llm_qa.py {_SELECTION_ALL}`"
            )
        try:
            edits = _merge_edits(commit, root, git)
        except MainMovedError as exc:
            return str(exc)
        outside = [path for path in edits if path not in moved_set]
        if outside:
            return (
                f"the merge {commit[:_SHORT_SHA]} changes {', '.join(outside[:3])}, which "
                f"main did not move, so no recheck covers it. Run `llm_qa.py {_SELECTION_ALL}`"
            )
    return None


def _main_merged_since_certified(
    root: Path,
    main_ref: str,
    base: str,
    main: str,
    git: GitBytesRunner,
    select: Selector,
    qa_dir: Path | None,
) -> MainMoved | None:
    """The movement of ``main`` when all HEAD holds past the certified head is ``main`` merged.

    The coordinator merges ``main``, passes its recheck, and may check again
    before ``--advance`` (review 6 m8). HEAD is then past the certified head,
    but only by what the recheck covers, so the verdict is that movement and
    its recheck, not ``head-moved`` and a second full gate. None when there
    is no certified head, the tree is dirty, nothing of ``main`` is merged
    since the base, or HEAD holds other work.
    """
    certified = _ref_commit(certified_ref(root, git), root, git)
    if certified is None or uncommitted_paths(root, git):
        return None
    merged = _git_text(
        ["merge-base", "HEAD", main], root, git, f"this branch shares no history with {main_ref}"
    )
    if merged == base:
        return None
    verdict, judged, reason = _judge_range(base, merged, root, git, select)
    if _work_beside_main(certified, merged, [path.path for path in judged], root, git):
        return None
    qa = qa_dir if qa_dir is not None else root / QA_OUTPUT_RELATIVE
    recheck_passed = not _uncertified(verdict, (base, merged), root, qa, git)
    head = _commit_of("HEAD", root, git)
    reason = f"HEAD holds {main_ref} merged in since the certified head, and nothing else: {reason}"
    return MainMoved(verdict, base, merged, judged, reason, head, recheck_passed)


def _only_main_merged(
    certified: str, merged: str, moved: Sequence[str], root: Path, git: GitBytesRunner
) -> None:
    """Refuse when HEAD holds anything since ``certified`` that is not ``main`` merged in."""
    reason = _work_beside_main(certified, merged, moved, root, git)
    if reason is not None:
        raise MainMovedError(reason)


def advance_batch(
    root: Path,
    main_ref: str = _DEFAULT_MAIN_REF,
    *,
    git: GitBytesRunner = _run_git_bytes,
    select: Selector = select_range,
    qa_dir: Path | None = None,
) -> str:
    """Move the base to the newest ``main_ref`` commit merged in, once its recheck passed.

    The recheck is the one the verdict for ``base..merged`` names, and it must
    have PASSED on the current tree (the provenance ``--read-only`` trusts).
    The tree must be clean, and HEAD must hold nothing since the certified
    head but ``main`` merged in; then HEAD becomes the certified head.

    Raises:
        MainMovedError: the tree is dirty, nothing new is merged in, HEAD holds
            work the gate never judged, or the recheck has not passed.
    """
    _refuse_uncommitted(root, git, "the base cannot advance")
    ref, base = _recorded_base(root, git)
    main = _commit_of(main_ref, root, git)
    merged = _git_text(
        ["merge-base", "HEAD", main], root, git, f"this branch shares no history with {main_ref}"
    )
    if merged == base:
        raise MainMovedError(
            f"nothing to advance: no {main_ref} commit after the base {base[:_SHORT_SHA]} is "
            f"merged into this branch. Merge it in (git merge --no-edit {main_ref}), run the "
            "recheck the verdict names, then advance"
        )
    certified_name = certified_ref(root, git)
    certified = _ref_commit(certified_name, root, git)
    if certified is None:
        raise MainMovedError(
            "no full gate has passed on this branch since the batch base was recorded: "
            f"run `llm_qa.py {_SELECTION_ALL}` on a clean tree first"
        )
    verdict, judged, _ = _judge_range(base, merged, root, git, select)
    _only_main_merged(certified, merged, [path.path for path in judged], root, git)
    qa = qa_dir if qa_dir is not None else root / QA_OUTPUT_RELATIVE
    problems = _uncertified(verdict, (base, merged), root, qa, git)
    if problems:
        raise MainMovedError(
            f"the base stays at {base[:_SHORT_SHA]}: the {verdict} recheck has not passed "
            f"on this tree. " + "; ".join(problems)
        )
    head = _commit_of("HEAD", root, git)
    _git_text(["update-ref", ref, merged, base], root, git, f"could not move {ref}")
    _git_text(
        ["update-ref", certified_name, head, certified],
        root,
        git,
        f"could not move {certified_name}",
    )
    return merged


def finish_batch(
    root: Path, main_ref: str = _DEFAULT_MAIN_REF, *, git: GitBytesRunner = _run_git_bytes
) -> None:
    """Delete the batch refs once ``main_ref`` is exactly the certified head.

    ``main_ref`` must BE the certified head, or a two-parent merge of it into
    a commit it already contains, whose tree is the certified tree (review 5
    m5, review 6 n3). A descendant is not enough: a late commit landed with it
    was never judged, and removing the refs would erase the evidence of that.

    Raises:
        MainMovedError: there is no certified head, or what landed is not it.
    """
    certified_name = certified_ref(root, git)
    certified = _ref_commit(certified_name, root, git)
    if certified is None:
        raise MainMovedError(f"no certified head is recorded in {certified_name}")
    main = _commit_of(main_ref, root, git)
    if main != certified and not _merges_exactly(main, certified, root, git):
        raise MainMovedError(
            f"{main_ref} is at {main[:_SHORT_SHA]}, which is not the certified head "
            f"{certified[:_SHORT_SHA]} nor a two-parent merge of it into what it contains, with "
            "its tree: what landed is not what the gate passed. Land exactly that head "
            f"(git merge --ff-only {certified}) before finishing"
        )
    _delete_ref(batch_base_ref(root, git), root, git)
    _delete_ref(certified_name, root, git)


def _merges_exactly(merge: str, certified: str, root: Path, git: GitBytesRunner) -> bool:
    """Whether ``merge`` is a merge of ``certified`` that lands exactly it.

    Two parents: ``certified``, and a commit ``certified`` already contains
    (``main`` as it was, merged with ``--no-ff``); and the certified tree. A
    same-tree child with one parent, an octopus and a merge with another line
    of work are not a landing of the certified head (review 6 n3).
    """
    parents = _git_text(
        ["rev-list", "--parents", "-n", "1", merge], root, git, f"cannot read {merge}"
    ).split()[1:]
    if len(parents) != _MERGE_PARENTS or certified not in parents:
        return False
    other = next(parent for parent in parents if parent != certified)
    if not _is_ancestor(other, certified, root, git):
        return False
    trees = [
        _git_text(["rev-parse", f"{commit}^{{tree}}"], root, git, f"cannot read {commit}")
        for commit in (merge, certified)
    ]
    return trees[0] == trees[1]


def _recheck_command(outcome: MainMoved) -> str:
    if outcome.verdict == VERDICT_DOCS_ONLY:
        return f"./scripts/qa/llm_qa.py {' '.join(DOCS_ONLY_TOOL_NAMES)}"
    if outcome.verdict == VERDICT_TARGETED:
        extra = [tool for tool in DOCS_ONLY_TOOL_NAMES if tool not in CHANGED_TOOL_NAMES]
        return (
            f"./scripts/qa/llm_qa.py {_SELECTION_CHANGED} {' '.join(extra)} "
            f"{_RANGE_OPTION} {outcome.base}..{outcome.main}"
        )
    return f"./scripts/qa/llm_qa.py {_SELECTION_ALL}"


def _print_verdict(outcome: MainMoved, main_ref: str, root: Path) -> None:
    print(f"VERDICT: {outcome.verdict}")
    print(
        f"  {outcome.reason} (base {outcome.base[:_SHORT_SHA]}, {main_ref} {outcome.main[:_SHORT_SHA]})"
    )
    for judged in outcome.paths:
        print(f"  [{judged.kind}] {judged.path}: {judged.why}")
    if outcome.verdict == VERDICT_UNMOVED:
        print(
            f"NEXT: from the main checkout, git merge --ff-only {outcome.head} (the certified "
            f"head of {integration_branch(root)}), then push. If --ff-only refuses, {main_ref} "
            "moved again: run this command again."
        )
    elif outcome.verdict == VERDICT_HEAD_MOVED:
        print("NEXT, in this integration worktree, on a clean tree:")
        steps = [
            *([f"git merge --no-edit {main_ref}"] if outcome.merge_first else []),
            f"{_recheck_command(outcome)}   (a pass certifies this head)",
            f"./scripts/qa/llm_qa.py {MAIN_MOVED_COMMAND}   (again)",
        ]
        for number, step in enumerate(steps, 1):
            print(f"  {number}. {step}")
    elif outcome.recheck_passed:
        print(
            f"NEXT, in this integration worktree ({main_ref} is merged in and its recheck "
            "already passed on this tree):"
        )
        print(f"  1. ./scripts/qa/llm_qa.py {MAIN_MOVED_COMMAND} {_ADVANCE_OPTION}")
        print(f"  2. ./scripts/qa/llm_qa.py {MAIN_MOVED_COMMAND}   (again, until unmoved)")
    else:
        print("NEXT, in this integration worktree:")
        # Merge the exact commit judged (outcome.main), not main_ref: if
        # main_ref has moved further since, merging it would put HEAD past
        # what the recheck below covers, wasting the recheck (review 7 m5).
        print(f"  1. git merge --no-edit {outcome.main}")
        print(f"  2. {_recheck_command(outcome)}")
        print(f"  3. ./scripts/qa/llm_qa.py {MAIN_MOVED_COMMAND} {_ADVANCE_OPTION}")
        print(f"  4. ./scripts/qa/llm_qa.py {MAIN_MOVED_COMMAND}   (again, until unmoved)")
    print("CI on the pushed head is the second line, not a substitute for this gate.")


def main_moved_command(args: Sequence[str], *, root: Path = PROJECT_ROOT) -> int:
    """``llm_qa.py main-moved [--start [--restart] | --advance | --finish] [MAIN_REF]``."""
    options = [arg for arg in args if arg.startswith("-")]
    refs = [arg for arg in args if not arg.startswith("-")]
    chosen = frozenset(options)
    if len(chosen) != len(options) or chosen not in _MAIN_MOVED_OPTION_SETS or len(refs) > 1:
        print(_MAIN_MOVED_USAGE, file=sys.stderr)
        return EXIT_FAILURE
    main_ref = refs[0] if refs else _DEFAULT_MAIN_REF
    try:
        if _START_OPTION in chosen:
            base = start_batch(root, main_ref, restart=_RESTART_OPTION in chosen)
            print(f"BATCH BASE: {base} recorded in {batch_base_ref(root)}")
            print(f"NEXT: ./scripts/qa/llm_qa.py {_SELECTION_ALL}   (a pass certifies the head)")
            return EXIT_SUCCESS
        if _ADVANCE_OPTION in chosen:
            advanced = advance_batch(root, main_ref)
            print(
                f"BATCH BASE: advanced to {advanced}; this head is certified. "
                f"Run {MAIN_MOVED_COMMAND} again."
            )
            return EXIT_SUCCESS
        if _FINISH_OPTION in chosen:
            finish_batch(root, main_ref)
            print(f"BATCH: landed on {main_ref}; the batch refs are removed.")
            return EXIT_SUCCESS
        outcome = main_moved(root, main_ref)
        _print_verdict(outcome, main_ref, root)
    except MainMovedError as exc:
        print(f"llm_qa: {MAIN_MOVED_COMMAND}: {exc}", file=sys.stderr)
        return EXIT_FAILURE
    return _VERDICT_EXIT[outcome.verdict]


def main() -> int:
    """Entry point."""
    args = sys.argv[1:]

    command_args = [arg for arg in args if arg != "--read-only"]
    if command_args[:1] == [MAIN_MOVED_COMMAND]:
        return main_moved_command(command_args[1:])
    if MAIN_MOVED_COMMAND in command_args:
        print(f"llm_qa: {MAIN_MOVED_COMMAND} runs on its own. {_MAIN_MOVED_USAGE}", file=sys.stderr)
        return EXIT_FAILURE

    read_only = False
    if "--read-only" in args:
        read_only = True
        args.remove("--read-only")

    if not args or "--help" in args or "-h" in args:
        print(
            "Usage: llm_qa.py [--read-only] <tool|all|changed> [tool ...] "
            f"[{_BASE_OPTION} REF | {_RANGE_OPTION} A..B] [{_ALLOW_UNMAPPED_OPTION}]"
        )
        print(f"  {_SELECTION_ALL}: the full suite (the coordinator's gate)")
        print(f"  {_SELECTION_CHANGED}: targeted, {', '.join(CHANGED_TOOL_NAMES)}")
        print(
            f"  {_BASE_OPTION}, {_RANGE_OPTION}, {_ALLOW_UNMAPPED_OPTION}: passed to changed_tests"
        )
        print("  --read-only: summarise; a result recorded for another tree FAILS")
        print(
            f"  {MAIN_MOVED_COMMAND} [{_START_OPTION} [{_RESTART_OPTION}] | {_ADVANCE_OPTION} | "
            f"{_FINISH_OPTION}] [MAIN_REF]: the batched gate's check on what would land "
            "(runs no tools)"
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

    try:
        lock_file = host_lock_path(PROJECT_ROOT)
        wait_seconds = configured_wait_seconds()
    except (OSError, ValueError) as exc:
        print(f"llm_qa: {exc}", file=sys.stderr)
        return EXIT_FAILURE
    try:
        lock_fd = acquire_host_lock(
            lock_file,
            wait_seconds=wait_seconds,
            announce=lambda message: print(message, file=sys.stderr, flush=True),
        )
    except LockTimeout as exc:
        print(exc, file=sys.stderr)
        return EXIT_LOCK_TIMEOUT
    try:
        _stamp_holder(lock_fd, PROJECT_ROOT)
        return _run_tools(tools, read_only=False, forwarded=forwarded, lock_fd=lock_fd)
    finally:
        os.close(lock_fd)


#: Per tool: the exit code, the live verdict, and the report hash taken on return.
RunOutcome: TypeAlias = tuple[int, bool, str | None]


def _record_run(run_records: Mapping[str, RunOutcome], before: dict[str, str] | None) -> None:
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
            name: run_record(state, exit_code=exit_code, passed=passed, output_sha256=digest)
            for name, (exit_code, passed, digest) in run_records.items()
        },
    )


def _certify_gate(judged: dict[str, str] | None) -> None:
    """After a passing full run, record HEAD as the batch's certified head, and say so."""
    try:
        head = certify_head(PROJECT_ROOT, judged)
    except MainMovedError as exc:
        # The run's own verdict stands; only the certification is refused, and said.
        print(f"\n{_TREE_WARNING_LABEL} {exc}")
    else:
        if head is not None:
            print(f"\nGATE: {head[:_SHORT_SHA]} certified for {MAIN_MOVED_COMMAND}")


def _run_tools(
    tools: list[str],
    *,
    read_only: bool,
    forwarded: Sequence[str] = (),
    lock_fd: int | None = None,
) -> int:
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
    run_records: dict[str, RunOutcome] = {}
    before = worktree_state(PROJECT_ROOT)
    recorded = read_provenance(QA_OUTPUT_DIR) if read_only else {}

    for name in tools:
        output = QA_OUTPUT_DIR / TOOL_REGISTRY[name].json_file
        exit_code: int | None = None
        stale: str | None = None
        digest: str | None = None
        record: ProvenanceRecord | None = None
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
            if TOOL_REGISTRY[name].live_daemon:
                daemon_note = ensure_live_daemon(name)
                if daemon_note is not None:
                    print(daemon_note)
            extra = forwarded if name == _CHANGED_TESTS_TOOL else ()
            exit_code = run_tool(name, extra, lock_fd=lock_fd)
            digest = output_digest(output)

        # Summarize from JSON, passing exit code for cross-check
        passed, summary = summarize_tool(name, exit_code=exit_code, stale=stale)
        failed_as_recorded = recorded_failure_reason(record) if record and passed else None
        if failed_as_recorded is not None:
            passed = False
            summary = summary.replace("✅", "❌", 1) + f"   {_STALE_LABEL} {failed_as_recorded}\n"
        tool_results[name] = (passed, summary)
        if exit_code is not None and not read_only:
            run_records[name] = (exit_code, passed, digest)
        print(summary, end="")
        if not passed:
            all_passed = False

    if not read_only:
        _record_run(run_records, before)
        if all_passed and set(ALL_TOOL_NAMES) <= set(tools):
            _certify_gate(before)

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
