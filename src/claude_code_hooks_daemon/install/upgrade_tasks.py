"""Pre- and post-upgrade tasks: one schema, one loader (Plan 00376).

A release can ship work for the upgrading agent in two places inside each
guide directory (and in ``UNRELEASED/`` before the release):

- ``pre-upgrade-tasks/`` -- a change the project must hear about BEFORE the
  new version is deployed. Every such task declares how to find the call sites
  it affects (``**Detect**:``), so the upgrade gate stays silent for a project
  it does not touch and names the affected lines, at file:line, for one it
  does.
- ``post-upgrade-tasks/`` -- work that can only happen after the install. A
  post-upgrade task MAY declare detection too, and the post-upgrade report then
  says whether it applies to this project.

The schema is written down for authors in
``CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/README.md`` and
``.../pre-upgrade-tasks/README.md``; :func:`schema_errors` is what enforces it,
from ``tests/integration/test_upgrade_task_schema.py``.

Standard library only: the upgrade gate loads this file before the target's
venv exists (see ``upgrade_gate_standalone.py``).
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
import shutil
import stat
import subprocess  # nosec B404 - used only for a fixed `git ls-files` argv on a trusted PATH (no shell, no user input)
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.install.install_stamp import is_branch_install
from claude_code_hooks_daemon.install.upgrade_guides import (
    UNRELEASED_DIRNAME,
    UNRELEASED_SOURCE,
    crossed_guide_dirs,
    default_upgrades_dir,
)
from claude_code_hooks_daemon.install.version_parse import strip_tag_prefix
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.path_containment import path_relative_to

logger = logging.getLogger(__name__)


class TaskKind(Enum):
    """Which task directory: the value is the directory name."""

    PRE = "pre-upgrade-tasks"
    POST = "post-upgrade-tasks"


TASK_TYPES: Final[frozenset[str]] = frozenset(
    {"audit", "config-migration", "data-migration", "workflow-change", "notification", "other"}
)
SEVERITIES: Final[tuple[str, ...]] = ("critical", "recommended", "optional")
SEVERITY_CRITICAL: Final[str] = "critical"
IDEMPOTENT_VALUES: Final[frozenset[str]] = frozenset({"yes", "no"})
REQUIRED_SECTIONS: Final[tuple[str, ...]] = (
    "## Why",
    "## How to detect if this applies to you",
    "## How to handle",
    "## How to confirm",
)
UNKNOWN_FIELD: Final[str] = "unknown"
DEFAULT_DETECT_PATHS: Final[tuple[str, ...]] = ("*",)
DEFAULT_HIT_LIMIT: Final[int] = 20

_TITLE_PREFIX: Final[str] = "# Task: "
_TASK_FILE_RE: Final[re.Pattern[str]] = re.compile(r"^\d{2,3}-.+\.md$")
_README: Final[str] = "README.md"
_FIELD_TYPE: Final[str] = "Type"
_FIELD_SEVERITY: Final[str] = "Severity"
_FIELD_APPLIES_TO: Final[str] = "Applies to"
_FIELD_IDEMPOTENT: Final[str] = "Idempotent"
_FIELD_DETECT: Final[str] = "Detect"
_FIELD_DETECT_IN: Final[str] = "Detect in"
_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    _FIELD_TYPE,
    _FIELD_SEVERITY,
    _FIELD_APPLIES_TO,
    _FIELD_IDEMPOTENT,
)
_BACKTICKED_RE: Final[re.Pattern[str]] = re.compile(r"`([^`]+)`")
#: A group holding a quantifier, itself quantified: ``(x+)+``, ``(a*)*``,
#: ``(a+){2,}``. The shape behind catastrophic backtracking.
_NESTED_QUANTIFIER_RE: Final[re.Pattern[str]] = re.compile(
    r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)[+*{]"
)
_SECTION_PREFIX: Final[str] = "## "
#: Directory names a detection never descends into at ANY depth: version
#: control and tool caches, which never hold the project's own call sites.
_SKIP_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)
#: Top-level directories skipped as vendored, built or local-only copies;
#: ``src/venv/`` is the project's own code and is scanned.
_SKIP_ROOT_DIRS: Final[frozenset[str]] = frozenset(
    {"untracked", "venv", ".venv", "vendor", "dist", "build", "target"}
)
#: The daemon's own clone: its files are the daemon's, never the project's.
_DAEMON_CLONE_REL: Final[str] = ".claude/hooks-daemon"
_MAX_SCANNED_BYTES: Final[int] = 1_048_576
#: Only this much of each line is matched, so no pattern meets an unbounded
#: input (a minified file is one very long line).
MAX_SCANNED_LINE_CHARS: Final[int] = 4096
_GIT_LIST_TIMEOUT_SECONDS: Final[int] = 60
#: Tracked files, plus untracked files the project's own `.gitignore` files do
#: not exclude. Not `--exclude-standard`: `.git/info/exclude` and
#: `core.excludesFile` are local state that could hide a call site. No
#: fsmonitor either: the project's own config could name one, and git would
#: run it in the scan.
_GIT_LIST_ARGS: Final[tuple[str, ...]] = (
    "-c",
    "core.fsmonitor=false",
    "ls-files",
    "-z",
    "--cached",
    "--others",
    "--exclude-per-directory=.gitignore",
)
#: Where the scan's git is looked up: fixed system locations, never the
#: caller's PATH, so a planted `git` cannot choose which files the scan sees
#: (Plan 00376 fresh review BLOCKER 1). Layer 2's GATE_SAFE_PATH is the same list.
TRUSTED_TOOL_PATH: Final[str] = "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin"
#: The only variable git gets from the caller: HOME, for its own safe.directory.
_GIT_ENV_PASSED: Final[tuple[str, ...]] = ("HOME",)
#: A NUL byte marks a binary file, which has no lines to report.
_NUL_BYTE: Final[bytes] = b"\x00"
_HIT_TEXT_WIDTH: Final[int] = 160


@dataclass(frozen=True)
class Detection:
    """How to find the call sites a task affects: a pattern, over some files."""

    pattern: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class DetectionHit:
    """One matching line, relative to the project root."""

    path: str
    line: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        """Serialise for ``--format json``."""
        return {"path": self.path, "line": self.line, "text": self.text}


@dataclass(frozen=True)
class UpgradeTask:
    """One task file, and the guide directory (or holding area) it came from."""

    path: Path
    source: str
    kind: TaskKind
    title: str
    task_type: str
    severity: str
    applies_to: str
    idempotent: str
    detection: Detection | None

    def to_dict(self) -> dict[str, Any]:
        """Serialise for ``--format json``."""
        return {
            "path": str(self.path),
            "source": self.source,
            "kind": self.kind.value,
            "title": self.title,
            "type": self.task_type,
            "severity": self.severity,
            "applies_to": self.applies_to,
        }


def is_task_file(path: Path) -> bool:
    """True for ``NN-slug.md`` files (never the directory's README)."""
    return path.is_file() and path.name != _README and _TASK_FILE_RE.match(path.name) is not None


def _header_block(text: str) -> str:
    """Everything before the first ``## `` section."""
    before, _sep, _rest = text.partition(f"\n{_SECTION_PREFIX}")
    return before


def _field(header: str, name: str) -> str | None:
    match = re.search(rf"^\*\*{re.escape(name)}\*\*:\s*(?P<value>.+?)\s*$", header, re.MULTILINE)
    return match.group("value") if match else None


def _title(text: str) -> str | None:
    first = text.splitlines()[0] if text else ""
    return first[len(_TITLE_PREFIX) :].strip() if first.startswith(_TITLE_PREFIX) else None


def _detection(header: str) -> Detection | None:
    raw = _field(header, _FIELD_DETECT)
    if raw is None:
        return None
    pattern = _BACKTICKED_RE.search(raw)
    paths_raw = _field(header, _FIELD_DETECT_IN)
    paths = tuple(_BACKTICKED_RE.findall(paths_raw)) if paths_raw else DEFAULT_DETECT_PATHS
    return Detection(
        pattern=pattern.group(1) if pattern else raw,
        paths=paths or DEFAULT_DETECT_PATHS,
    )


def load_task(path: Path, source: str, kind: TaskKind) -> UpgradeTask:
    """Read a task file. Never raises on a malformed task: an unreadable field
    is reported as ``unknown`` so the upgrade still shows the task; the schema
    test is what keeps a malformed task from shipping.
    """
    text = path.read_text(encoding="utf-8")
    header = _header_block(text)
    return UpgradeTask(
        path=path,
        source=source,
        kind=kind,
        title=_title(text) or path.stem,
        task_type=_field(header, _FIELD_TYPE) or UNKNOWN_FIELD,
        severity=_field(header, _FIELD_SEVERITY) or UNKNOWN_FIELD,
        applies_to=_field(header, _FIELD_APPLIES_TO) or UNKNOWN_FIELD,
        idempotent=_field(header, _FIELD_IDEMPOTENT) or UNKNOWN_FIELD,
        detection=_detection(header),
    )


def schema_errors(path: Path, kind: TaskKind) -> list[str]:
    """Every way ``path`` breaks the task schema; empty when it conforms."""
    errors: list[str] = []
    if _TASK_FILE_RE.match(path.name) is None:
        errors.append(f"file name must be NN-kebab-slug.md, got {path.name!r}")
    text = path.read_text(encoding="utf-8")
    if _title(text) is None:
        errors.append(f"first line must be '{_TITLE_PREFIX}<title>'")
    header = _header_block(text)
    for name in _REQUIRED_FIELDS:
        if _field(header, name) is None:
            errors.append(f"header field **{name}** is missing")
    task_type = _field(header, _FIELD_TYPE)
    if task_type is not None and task_type not in TASK_TYPES:
        errors.append(f"**Type** {task_type!r} is not one of {sorted(TASK_TYPES)}")
    severity = _field(header, _FIELD_SEVERITY)
    if severity is not None and severity not in SEVERITIES:
        errors.append(f"**Severity** {severity!r} is not one of {list(SEVERITIES)}")
    idempotent = _field(header, _FIELD_IDEMPOTENT)
    if idempotent is not None and idempotent not in IDEMPOTENT_VALUES:
        errors.append(f"**Idempotent** {idempotent!r} is not yes or no")
    detection = _detection(header)
    if detection is None and kind is TaskKind.PRE:
        errors.append("a pre-upgrade task must declare **Detect**: `<pattern>`")
    raw_detect = _field(header, _FIELD_DETECT)
    if raw_detect is not None and _BACKTICKED_RE.search(raw_detect) is None:
        errors.append("**Detect** must hold one pattern in backticks: **Detect**: `<pattern>`")
    if detection is not None:
        try:
            re.compile(detection.pattern)
        except re.error as exc:
            errors.append(f"**Detect** pattern {detection.pattern!r} does not compile: {exc}")
        if _NESTED_QUANTIFIER_RE.search(detection.pattern):
            errors.append(
                f"**Detect** pattern {detection.pattern!r} has a nested quantifier, which can "
                "backtrack for ever on one long line"
            )
    lines = set(text.splitlines())
    for section in REQUIRED_SECTIONS:
        if section not in lines:
            errors.append(f"section '{section}' is missing")
    return errors


def _is_skipped(rel: str) -> bool:
    parts = rel.split("/")
    return (
        parts[0] in _SKIP_ROOT_DIRS
        or rel == _DAEMON_CLONE_REL
        or rel.startswith(f"{_DAEMON_CLONE_REL}/")
        or any(part in _SKIP_DIR_NAMES for part in parts)
    )


def _dir_trust_from_stat(info: os.stat_result) -> bool:
    """Whether a ``stat`` result names a directory safe to trust for a tool
    (review2 MAJOR 2): root-owned, and neither group- nor world-writable. A
    directory this same process could itself write to -- Homebrew's
    ``/opt/homebrew/bin`` and ``/usr/local/bin`` are user-owned by default on
    macOS -- is not trusted merely for being listed. An agent running AS root
    defeats this by construction (root owns every directory here regardless
    of its permission bits); no in-process check can defend against that, and
    LLM-UPDATE says so. Split from :func:`_trusted_dirs` so the policy is
    testable on a plain ``os.stat_result`` -- constructing one costs no real
    directory of a uid this process does not have.
    """
    return info.st_uid == 0 and not (info.st_mode & (stat.S_IWGRP | stat.S_IWOTH))


def _trusted_dirs(candidates: list[str] | None = None) -> list[str]:
    """Of ``candidates`` (default: every ``TRUSTED_TOOL_PATH`` entry), the ones
    :func:`_dir_trust_from_stat` accepts; the caller skips the rest and keeps
    looking rather than treating a rejection as fatal.
    """
    trusted: list[str] = []
    for candidate in TRUSTED_TOOL_PATH.split(os.pathsep) if candidates is None else candidates:
        try:
            info = Path(candidate).stat()
        except OSError as exc:
            # Expected for most hosts: TRUSTED_TOOL_PATH lists locations that
            # exist on SOME platform (e.g. /opt/homebrew/bin only on macOS),
            # not every one of them on this host. Logged so a genuinely
            # unexpected stat failure (permissions, not absence) is still
            # visible, rather than indistinguishable from "not on this OS".
            log_and_continue(
                logger,
                exc,
                reason=f"a trusted-path candidate {candidate} that cannot be stat-ed is left out of the trusted set, which only narrows what the upgrade trusts; absence is expected on most hosts",
                level=logging.DEBUG,
            )
            continue
        if _dir_trust_from_stat(info):
            trusted.append(candidate)
    return trusted


def _trusted_tool_path() -> str:
    """``TRUSTED_TOOL_PATH``, with every untrusted directory removed."""
    return os.pathsep.join(_trusted_dirs())


def _git_listed_files(project_root: Path) -> list[str] | None:
    """The files git would track or offer to track, or None outside a work tree."""
    trusted_path = _trusted_tool_path()
    git = shutil.which("git", path=trusted_path)
    if git is None:
        return None
    env = {name: os.environ[name] for name in _GIT_ENV_PASSED if name in os.environ}
    env["PATH"] = trusted_path
    result = subprocess.run(  # nosec B603 - fixed argv, git resolved on a trusted PATH, restricted env, no shell
        [git, "-C", str(project_root), *_GIT_LIST_ARGS],
        capture_output=True,
        check=False,
        timeout=_GIT_LIST_TIMEOUT_SECONDS,
        env=env,
    )
    if result.returncode != 0:
        return None
    return sorted(
        name for name in result.stdout.decode("utf-8", errors="replace").split("\0") if name
    )


def _walked_files(project_root: Path) -> list[str]:
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(project_root):
        current = Path(dirpath)
        rel_dir = path_relative_to(current, project_root).as_posix()
        prefix = "" if rel_dir == "." else f"{rel_dir}/"
        dirnames[:] = sorted(name for name in dirnames if not _is_skipped(f"{prefix}{name}"))
        found.extend(f"{prefix}{name}" for name in sorted(filenames))
    return found


def _scanned_files(project_root: Path) -> list[tuple[str, Path]]:
    """The project's files, honouring ``.gitignore`` in a git work tree."""
    listed = _git_listed_files(project_root)
    names = listed if listed is not None else _walked_files(project_root)
    return [(rel, project_root / rel) for rel in names if not _is_skipped(rel)]


def detect(
    detection: Detection, project_root: Path, limit: int = DEFAULT_HIT_LIMIT
) -> tuple[list[DetectionHit], int]:
    """Lines under ``project_root`` matching the task's pattern.

    Globs are matched against the project-relative POSIX path with
    ``fnmatch``, whose ``*`` crosses ``/``, so ``*.py`` means every Python
    file. Symlinks, files over 1 MiB, files this user cannot read and binary
    files (any NUL byte) are skipped; other bytes that are not UTF-8 decode as
    replacement characters, so a Latin-1 file is still scanned. Only the first
    :data:`MAX_SCANNED_LINE_CHARS` characters of a line are matched.

    Returns:
        Up to ``limit`` hits in path order, and the total number of hits.
    """
    compiled = re.compile(detection.pattern)
    hits: list[DetectionHit] = []
    total = 0
    for rel, path in _scanned_files(project_root):
        if not any(fnmatch.fnmatchcase(rel, glob) for glob in detection.paths):
            continue
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size > _MAX_SCANNED_BYTES
            or not os.access(path, os.R_OK)
        ):
            continue
        data = path.read_bytes()
        if _NUL_BYTE in data:
            continue
        text = data.decode("utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            if compiled.search(line[:MAX_SCANNED_LINE_CHARS]) is None:
                continue
            total += 1
            if len(hits) < limit:
                hits.append(DetectionHit(rel, number, line.strip()[:_HIT_TEXT_WIDTH]))
    return hits, total


def tasks_in_dir(tasks_dir: Path, source: str, kind: TaskKind) -> list[UpgradeTask]:
    """Every task file in one task directory, in file-name order."""
    if not tasks_dir.is_dir():
        return []
    return [
        load_task(path, source, kind)
        for path in sorted(tasks_dir.iterdir(), key=lambda p: p.name)
        if is_task_file(path)
    ]


def tasks_for_range(
    kind: TaskKind,
    from_version: str,
    to_version: str,
    upgrades_dir: Path | None = None,
    include_unreleased: bool | None = None,
) -> list[UpgradeTask]:
    """The tasks of every guide the upgrade crossed, oldest guide first.

    The holding area's tasks follow when ``include_unreleased`` holds (``None``
    asks the install stamp), even for ``from == to``: a branch install
    normally reports the same release number on both sides.

    Raises:
        ValueError: on an unparseable version or a backwards range.
    """
    base = upgrades_dir if upgrades_dir is not None else default_upgrades_dir()
    tasks: list[UpgradeTask] = []
    for guide_dir in crossed_guide_dirs(base, from_version, to_version):
        tasks.extend(tasks_in_dir(guide_dir / kind.value, guide_dir.name, kind))
    if include_unreleased is None:
        include_unreleased = is_branch_install()
    if include_unreleased:
        tasks.extend(tasks_in_dir(base / UNRELEASED_DIRNAME / kind.value, UNRELEASED_SOURCE, kind))
    return tasks


@dataclass(frozen=True)
class TaskFinding:
    """A task and, when it declares detection and a project was scanned, its hits."""

    task: UpgradeTask
    hits: list[DetectionHit]
    total_hits: int
    scanned: bool

    @property
    def applies(self) -> bool | None:
        """True/False once scanned; None when the task declares no detection."""
        return self.total_hits > 0 if self.scanned else None

    def to_dict(self) -> dict[str, Any]:
        """Serialise for ``--format json``."""
        payload = self.task.to_dict()
        payload["applies"] = self.applies
        payload["hits"] = [hit.to_dict() for hit in self.hits]
        payload["total_hits"] = self.total_hits
        return payload


def evaluate(tasks: list[UpgradeTask], project_root: Path | None) -> list[TaskFinding]:
    """Run each task's detection over ``project_root`` (when there is one)."""
    findings: list[TaskFinding] = []
    for task in tasks:
        if task.detection is None or project_root is None:
            findings.append(TaskFinding(task, [], 0, scanned=False))
            continue
        try:
            hits, total = detect(task.detection, project_root)
        except re.error:
            findings.append(TaskFinding(task, [], 0, scanned=False))
            continue
        findings.append(TaskFinding(task, hits, total, scanned=True))
    return findings


def format_findings_line(finding: TaskFinding) -> list[str]:
    """The lines one task contributes to a report."""
    task = finding.task
    lines = [f"  - [{task.severity}, {task.task_type}] {task.path}"]
    if finding.applies is None and task.kind is TaskKind.PRE:
        lines.append(
            "      detection could not run (missing or invalid **Detect**): read it and "
            "check by hand"
        )
    elif finding.applies is False:
        lines.append("      not detected in this project: skip unless you know better")
    elif finding.applies:
        lines.append(f"      detected at {finding.total_hits} place(s):")
        lines.extend(f"        {hit.path}:{hit.line}: {hit.text}" for hit in finding.hits)
        if finding.total_hits > len(finding.hits):
            lines.append(f"        ... and {finding.total_hits - len(finding.hits)} more")
    return lines


_KIND_LABEL: Final[dict[TaskKind, str]] = {
    TaskKind.PRE: "Pre-upgrade tasks",
    TaskKind.POST: "Post-upgrade tasks",
}


def format_task_report(
    kind: TaskKind, findings: list[TaskFinding], from_version: str, to_version: str
) -> str:
    """The text form of ``check-post-upgrade-tasks`` (and its pre-upgrade twin)."""
    frm, to = strip_tag_prefix(from_version), strip_tag_prefix(to_version)
    label = _KIND_LABEL[kind]
    lines = [f"{label}: v{frm} -> v{to}", ""]
    if not findings:
        lines.append(f"No {label.lower()} for this version range.")
        return "\n".join(lines)
    lines.append(f"{len(findings)} task(s) to read and carry out, in this order:")
    for finding in findings:
        lines.extend(format_findings_line(finding))
    lines.extend(
        [
            "",
            "For EACH task: read its header block, skip it only if 'Applies to' does",
            "not cover this project, otherwise follow 'How to detect if this applies",
            "to you', 'How to handle' and 'How to confirm'. Adapt sample commands to",
            "the project; never run them blind. Never edit anything under",
            ".claude/hooks-daemon/. Report the outcome of every task, grouped by",
            "severity (critical first).",
        ]
    )
    return "\n".join(lines)


def run_check_upgrade_tasks(
    kind: TaskKind,
    from_version: str,
    to_version: str,
    upgrades_dir: Path | None = None,
    include_unreleased: bool | None = None,
    project_root: Path | None = None,
    output_format: str = "text",
) -> dict[str, Any]:
    """Resolve and evaluate the tasks for one kind over a version range.

    Returns:
        ``from_version``, ``to_version``, ``has_tasks`` and ``tasks`` (dicts),
        plus ``text`` when ``output_format`` is ``'text'``.

    Raises:
        ValueError: on an unparseable version or a backwards range.
    """
    tasks = tasks_for_range(
        kind,
        from_version,
        to_version,
        upgrades_dir=upgrades_dir,
        include_unreleased=include_unreleased,
    )
    findings = evaluate(tasks, project_root)
    result: dict[str, Any] = {
        "from_version": from_version,
        "to_version": to_version,
        "has_tasks": bool(findings),
        "tasks": [finding.to_dict() for finding in findings],
    }
    if output_format == "text":
        result["text"] = format_task_report(kind, findings, from_version, to_version)
    return result
