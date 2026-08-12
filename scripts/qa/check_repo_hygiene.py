#!/usr/bin/env python3
"""Repo-hygiene check — the tracked tree must carry no generated detritus.

Plan 00200 Tasks 6.1 + 6.3. Built under DBF (``CLAUDE.md`` Core Standard 15):
``coverage.json`` (1,464,897 bytes, stale from v2.16.0) and
``.claude/settings.json.bak`` were committed not because anyone decided to, but
because **no guard could see them**. Their siblings ``coverage.xml``,
``htmlcov/`` and ``.coverage`` were already gitignored; these leaked through the
gap unnoticed.

Per that standard's corollary, a write-time PreToolUse handler cannot cover what
is already on disk, so this is a batch check over the tracked tree.

Ground truth is ``git ls-files``: only what is **tracked** is a violation. An
untracked ``coverage.json`` in a working tree is the normal result of running
the test suite and must never fail the gate — a check that fired on that would
be switched off within a day.

Four rule families, deliberately scoped:

``tracked-build-artifact``
    Generated reports and editor/merge/backup detritus that should be produced,
    never committed.

``frozen-session-summary``
    A tracked document that is unedited agent session output — a "Mission
    Accomplished" heading, a "Next Steps (User's Original Request)" section, or
    a frozen ``N PASSING / M FAILING`` tally. ``validate_instruction_content``
    blocks this material at write time, but only for ``CLAUDE.md`` and
    ``README.md``; two such documents sat tracked at the top of ``CLAUDE/`` for
    months, one advertising 13 failing tests in its header. This is that
    handler's batch half.

    Narrative records are exempt BY LOCATION: a plan, its journal, a release
    note and the changelog are dated accounts of what happened and are supposed
    to read that way. A rule that flagged them would fire on hundreds of
    legitimate files and be switched off within a day.

``src-test-stub``
    A ``test_*.py`` tracked under ``src/``, which pytest can never collect
    (``testpaths = ["tests"]``). The one instance stated its own purpose:
    *"This file satisfies the TDD enforcement handler requirement."* No test
    function, no import, no assertion. A committed decoy that documents
    bypassing the flagship guardrail is worse than the missing test it stood
    in for.

``root-test-script``
    A ``test_*.sh`` stranded at the repository root. Scoped to the root ON
    PURPOSE: a rule wide enough to flag every ``test_*.sh`` anywhere would be a
    naming-convention rule, not a hygiene one, and would fire on shell tests
    that legitimately sit beside the code they exercise. The root is the one
    location where a test script has no owning context.

    An earlier version of this note cited ``scripts/install/test_helpers.sh``
    and its five siblings as the legitimate files this narrow scope protected.
    They were not legitimate — all six had zero callers and were removed. The
    justification was true about the *shape* of the rule and false about its
    example, which is exactly the kind of claim a guard should not assert
    without checking. The scope stands on the reasoning above alone.

Usage:
    python scripts/qa/check_repo_hygiene.py [--json] [--root DIR] [--report-stdout]

Exit codes:
    0 - No violations found
    1 - Violations found
    2 - Operational failure (not a git repository, git unavailable)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404 — only ever runs the trusted system ``git`` binary
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR_PARTS: Final[tuple[str, str]] = ("untracked", "qa")
_OUTPUT_FILENAME: Final[str] = "repo_hygiene.json"

_GIT_BINARY: Final[str] = "git"
_GIT_TIMEOUT_SECONDS: Final[int] = 60
_NUL: Final[str] = "\0"

_TOOL_NAME: Final[str] = "repo_hygiene"

RULE_TRACKED_ARTIFACT: Final[str] = "tracked-build-artifact"
RULE_ROOT_TEST_SCRIPT: Final[str] = "root-test-script"
RULE_FROZEN_SUMMARY: Final[str] = "frozen-session-summary"
RULE_SRC_TEST_STUB: Final[str] = "src-test-stub"
RULE_IGNORED_PLAN_DOC: Final[str] = "ignored-plan-document"

_ALL_RULES: Final[tuple[str, ...]] = (
    RULE_TRACKED_ARTIFACT,
    RULE_ROOT_TEST_SCRIPT,
    RULE_FROZEN_SUMMARY,
    RULE_SRC_TEST_STUB,
    RULE_IGNORED_PLAN_DOC,
)

# Directory whose contents are tracked source BY POLICY (CLAUDE/Plan/CLAUDE.md:
# "never let a plan folder linger untracked"). Nothing under it may be caught
# by a convenience ignore pattern.
_PLAN_DIR: Final[str] = "CLAUDE/Plan"

_MARKDOWN_SUFFIXES: Final[tuple[str, ...]] = (".md", ".markdown")

# Path prefixes whose contents are dated narrative BY DESIGN. A plan, its
# journal, a release note and the changelog are accounts of what happened;
# "Mission Accomplished" in one of those is the genre, not a defect.
_NARRATIVE_PREFIXES: Final[tuple[str, ...]] = (
    "CLAUDE/Plan/",
    "RELEASES/",
    "untracked/",
)
_NARRATIVE_BASENAMES: Final[frozenset[str]] = frozenset({"CHANGELOG.md"})
_JOURNAL_DIRNAME: Final[str] = "JOURNAL"

# Directory names holding deliberate specimens. Freezing the real pre-fix
# documents as evidence (``tests/fixtures/repo_hygiene/pre_fix_*.md``) puts two
# deliberately-awful documents in the tracked tree; without this the rule would
# flag its own proof, and the only way to keep the gate green would be to
# delete that proof. Declared locally rather than shared with
# ``check_british_english.py``: each QA script in this directory is
# self-contained by design, and a shared-constants module for one frozenset
# would couple them for no gain.
_FIXTURE_DIRNAMES: Final[frozenset[str]] = frozenset({"fixtures", "test-files", "__fixtures__"})

# The plan-workflow task-status icons. In a plan they belong in a TASK LIST
# (`- [ ] ⬜ **Task 1.1**`); leading a HEADING that also names a lifecycle STATE
# they mark a per-session progress board, which is what
# ``CLAUDE/AGENT_TEAM_EXECUTION_STATUS.md`` was
# (`## 🔄 READY: Plan 003 - Planning Mode Integration (25-30% done)`).
#
# The icon ALONE is not enough, and an earlier draft that stopped there flagged
# nine legitimate documents: `## ❌ Working in Wrong Directory` and
# `# ✅ RIGHT - Use parentheses` are ordinary do-this/not-that pedagogy, and a
# rule that forbade it would be unusable. What distinguishes a board is the
# lifecycle token and the colon: it is tracking a work ITEM's state, not
# marking an example good or bad.
_STATUS_ICONS: Final[str] = "✅🔄⬜🚫❌⏸️👁️"
_LIFECYCLE_TOKENS: Final[str] = (
    "COMPLETE|COMPLETED|DONE|READY|IN PROGRESS|BLOCKED|PENDING|NEXT|TODO|WIP"
)

_FENCE_MARKER: Final[str] = "```"

# Phrases that only ever appear in unedited agent session output. Each is
# anchored tightly enough that prose *about* the problem (this file, the tests,
# the audit that found them) does not trip it: the markers require the heading
# or tally form, not a bare mention.
_SESSION_SUMMARY_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (
        re.compile(r"^#{1,6}\s+.*Mission Accomplished", re.MULTILINE),
        'a "Mission Accomplished" heading',
    ),
    (
        re.compile(r"^#{1,6}\s+.*Next Steps \(User's Original Request\)", re.MULTILINE),
        'a "Next Steps (User\'s Original Request)" heading',
    ),
    (
        re.compile(r"\d+\s+PASSING\s*/\s*\d+\s+FAILING"),
        "a frozen PASSING/FAILING test tally",
    ),
    (
        re.compile(
            rf"^#{{1,6}}\s+[{_STATUS_ICONS}]\s*\**\s*(?:{_LIFECYCLE_TOKENS})\b[^\n]*:",
            re.MULTILINE,
        ),
        "a status-icon lifecycle heading (a per-session progress board)",
    ),
)

_SRC_DIR_PREFIX: Final[str] = "src/"
_PYTHON_SUFFIX: Final[str] = ".py"

# Exact basenames of generated coverage reports. Matched exactly rather than by
# a ``coverage.*`` glob so a legitimate source file (``coverage.py``) is safe.
_COVERAGE_BASENAMES: Final[frozenset[str]] = frozenset(
    {
        "coverage.json",
        "coverage.xml",
        "coverage.lcov",
        "coverage.info",
        ".coverage",
    }
)

# Directory whose entire contents are a generated HTML coverage report.
_HTMLCOV_DIR: Final[str] = "htmlcov"

# Suffixes that mark editor backups, merge detritus and manual copies.
_ARTIFACT_SUFFIXES: Final[tuple[str, ...]] = (".bak", ".orig", ".rej", "~")

# The daemon writes ``settings.json.bak.pre-registration-repair`` at runtime
# (``utils/settings_repair.py:34``), so the marker can also appear mid-name.
_BACKUP_INFIX: Final[str] = ".bak."

# Prefix + suffixes identifying a shell test script.
_TEST_SCRIPT_PREFIX: Final[str] = "test_"
_SHELL_SUFFIXES: Final[tuple[str, ...]] = (".sh", ".bash")

_REMEDIATION_ARTIFACT: Final[str] = (
    "Untrack it (`git rm --cached <path>`) and add a matching rule to .gitignore. "
    "Generated reports are produced by the tooling that needs them, never committed."
)
_REMEDIATION_ROOT_SCRIPT: Final[str] = (
    "Move it into tests/ (or beside the code it exercises) if it still earns its "
    "keep, otherwise delete it. A test script at the repository root is referenced "
    "by nothing and drifts silently out of date."
)
_REMEDIATION_FROZEN_SUMMARY: Final[str] = (
    "Delete it, or fold the durable part into the doc that owns that topic. A "
    "session summary is a snapshot of one conversation: its counts freeze, its "
    "'next steps' are already done or abandoned, and nothing updates it. If the "
    "narrative matters, it belongs in the relevant plan's JOURNAL/."
)
_REMEDIATION_SRC_TEST_STUB: Final[str] = (
    "Delete it and write the real test under tests/. pytest's testpaths never "
    "reach src/, so this file runs nowhere — if it exists to satisfy "
    "tdd_enforcement, fix that handler's test-path resolution or add an "
    "exclusion. Never commit a bypass."
)

_REMEDIATION_IGNORED_PLAN_DOC: Final[str] = (
    "Narrow the .gitignore pattern that matches it — anchor a root-level "
    "scratch name with a leading slash (/STATUS.md), since an unanchored "
    "pattern matches at EVERY depth. Then `git add` the document. Do not "
    "rename the plan document to dodge the pattern: the next one will hit it "
    "too. This is a silent loss — git status stays clean, so the document is "
    "missing for everyone except its author, who still sees it on disk and "
    "whose PLAN.md link still resolves locally."
)


@dataclass(frozen=True)
class Violation:
    """One tracked path that should not be tracked, plus its remediation."""

    rule: str
    path: str
    message: str
    remediation: str

    def to_dict(self) -> dict[str, str]:
        return {
            "rule": self.rule,
            "path": self.path,
            "message": self.message,
            "remediation": self.remediation,
        }


@dataclass
class Report:
    """Accumulated findings for one repository."""

    violations: list[Violation] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, object]:
        by_rule = {rule: sum(1 for v in self.violations if v.rule == rule) for rule in _ALL_RULES}
        return {
            "tool": _TOOL_NAME,
            "summary": {
                "passed": self.passed,
                "total_violations": len(self.violations),
                "by_rule": by_rule,
            },
            "violations": [v.to_dict() for v in self.violations],
        }


def tracked_files(root: Path) -> tuple[str, ...]:
    """Every path in ``root``'s git index, repo-relative.

    Raises:
        RuntimeError: when ``root`` is not a git repository or git is
            unavailable. FAIL FAST — a hygiene check that silently reports
            "clean" because it could not read the index is precisely the
            blind-guard failure this check exists to prevent.
    """
    # SECURITY: list-form argv, no shell (B603); git is a trusted tool (B607).
    result = subprocess.run(  # nosec B603 B607 — fixed argv, no shell, trusted binary
        [_GIT_BINARY, "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"could not read the git index at {root}: {result.stderr.strip() or 'git failed'}"
        )
    return tuple(path for path in result.stdout.split(_NUL) if path)


def ignored_plan_documents(root: Path) -> tuple[str, ...]:
    """Files under the plan directory that git is IGNORING, repo-relative.

    The failure this exists for is silent by construction. An unanchored
    ``.gitignore`` entry matches at every depth, so a root-level scratch name
    like ``PHASE-*.md`` or ``STATUS.md`` also swallows a plan's supporting
    documents. ``git status`` then stays clean, no other check looks, and the
    document is missing for everyone except its author — whose copy is still
    on disk and whose ``PLAN.md`` link still resolves locally. Two real plan
    documents were lost this way before anything noticed.

    Raises:
        RuntimeError: when git cannot be read. FAIL FAST — reporting "clean"
            because the check could not run is the blind guard again.
    """
    plan_dir = root / _PLAN_DIR
    if not plan_dir.is_dir():
        return ()

    # `ls-files --others --ignored` is exactly the silent-loss set: files that
    # are NOT in the index AND are ignored. A tracked file is safe even if a
    # pattern also matches it, and an untracked-but-not-ignored file is just
    # unstaged work — normal mid-edit, and visible in `git status`.
    # SECURITY: list-form argv, no shell (B603); git is a trusted tool (B607).
    result = subprocess.run(  # nosec B603 B607 — fixed argv, no shell, trusted binary
        [
            _GIT_BINARY,
            "-C",
            str(root),
            "ls-files",
            "-z",
            "--others",
            "--ignored",
            "--exclude-standard",
            "--",
            _PLAN_DIR,
        ],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"could not list ignored files at {root}: {result.stderr.strip() or 'git failed'}"
        )

    return tuple(sorted(path for path in result.stdout.split(_NUL) if path))


def _is_build_artifact(rel_path: str) -> str | None:
    """Describe why ``rel_path`` is a generated artifact, or ``None``."""
    parts = rel_path.split("/")
    basename = parts[-1]

    if basename in _COVERAGE_BASENAMES:
        return "generated coverage report"
    if basename.startswith(".coverage."):
        return "generated coverage data file"
    if _HTMLCOV_DIR in parts[:-1]:
        return "generated HTML coverage report"
    if _BACKUP_INFIX in basename:
        return "backup copy"
    for suffix in _ARTIFACT_SUFFIXES:
        if basename.endswith(suffix):
            return "editor/merge backup file"
    return None


def _is_root_test_script(rel_path: str) -> bool:
    """True when ``rel_path`` is a shell test script at the repository root."""
    if "/" in rel_path:
        return False
    if not rel_path.startswith(_TEST_SCRIPT_PREFIX):
        return False
    return rel_path.endswith(_SHELL_SUFFIXES)


def _is_narrative_record(rel_path: str) -> bool:
    """True when ``rel_path`` is exempt: a dated account, or a frozen specimen.

    A plan, its journal, a release note and the changelog are accounts of what
    happened and are SUPPOSED to read this way. A fixture is a deliberately-bad
    document kept as evidence that the rule fires.
    """
    if rel_path.startswith(_NARRATIVE_PREFIXES):
        return True
    if rel_path in _NARRATIVE_BASENAMES:
        return True
    directories = rel_path.split("/")[:-1]
    if _JOURNAL_DIRNAME in directories:
        return True
    return bool(_FIXTURE_DIRNAMES.intersection(directories))


def _strip_fenced_blocks(content: str) -> str:
    """Drop fenced code blocks, keeping line numbering irrelevant to the caller.

    Every marker here describes PROSE. Inside a fence the same characters are
    code: `# ❌ WRONG - Line too long` is a Python comment in a style guide, and
    a doc quoting `## Mission Accomplished` as an example of what not to write
    would otherwise convict itself.
    """
    kept: list[str] = []
    in_fence = False
    for line in content.split("\n"):
        if line.strip().startswith(_FENCE_MARKER):
            in_fence = not in_fence
            continue
        if not in_fence:
            kept.append(line)
    return "\n".join(kept)


def _frozen_summary_marker(root: Path, rel_path: str) -> str | None:
    """Describe why ``rel_path`` reads as frozen session output, or ``None``.

    Reads the file from the WORKING TREE. A tracked path with no regular file
    behind it (a sparse checkout, a submodule gitlink) has no prose to judge
    and is skipped by an explicit ``is_file()`` test — NOT by catching the read
    error. FAIL FAST: a genuinely unreadable or non-UTF-8 ``.md`` in the index
    is a broken tree, and this check must say so rather than quietly report the
    file clean.
    """
    if not rel_path.endswith(_MARKDOWN_SUFFIXES):
        return None
    if _is_narrative_record(rel_path):
        return None

    target = root / rel_path
    if not target.is_file():
        return None
    content = _strip_fenced_blocks(target.read_text(encoding="utf-8"))

    for pattern, description in _SESSION_SUMMARY_PATTERNS:
        if pattern.search(content):
            return description
    return None


def _is_src_test_stub(rel_path: str) -> bool:
    """True when ``rel_path`` is a ``test_*.py`` stranded under ``src/``."""
    if not rel_path.startswith(_SRC_DIR_PREFIX):
        return False
    basename = rel_path.rsplit("/", 1)[-1]
    return basename.startswith(_TEST_SCRIPT_PREFIX) and basename.endswith(_PYTHON_SUFFIX)


def scan(root: Path) -> Report:
    """Check every tracked path in ``root`` against every rule family."""
    report = Report()
    for rel_path in tracked_files(root):
        reason = _is_build_artifact(rel_path)
        if reason is not None:
            report.violations.append(
                Violation(
                    rule=RULE_TRACKED_ARTIFACT,
                    path=rel_path,
                    message=f"tracked {reason}",
                    remediation=_REMEDIATION_ARTIFACT,
                )
            )
            continue
        if _is_root_test_script(rel_path):
            report.violations.append(
                Violation(
                    rule=RULE_ROOT_TEST_SCRIPT,
                    path=rel_path,
                    message="test script stranded at the repository root",
                    remediation=_REMEDIATION_ROOT_SCRIPT,
                )
            )
            continue
        if _is_src_test_stub(rel_path):
            report.violations.append(
                Violation(
                    rule=RULE_SRC_TEST_STUB,
                    path=rel_path,
                    message="test file under src/, where pytest never collects it",
                    remediation=_REMEDIATION_SRC_TEST_STUB,
                )
            )
            continue
        marker = _frozen_summary_marker(root, rel_path)
        if marker is not None:
            report.violations.append(
                Violation(
                    rule=RULE_FROZEN_SUMMARY,
                    path=rel_path,
                    message=f"tracked document carries {marker}",
                    remediation=_REMEDIATION_FROZEN_SUMMARY,
                )
            )

    for rel_path in ignored_plan_documents(root):
        report.violations.append(
            Violation(
                rule=RULE_IGNORED_PLAN_DOC,
                path=rel_path,
                message="plan document silently ignored by .gitignore",
                remediation=_REMEDIATION_IGNORED_PLAN_DOC,
            )
        )
    return report


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(_PROJECT_ROOT), help="repository root to scan")
    parser.add_argument("--json", action="store_true", help="write the JSON artifact")
    parser.add_argument(
        "--report-stdout", action="store_true", help="print the JSON report to stdout"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(args.root)

    try:
        report = scan(root)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = report.to_dict()

    if args.json:
        output_dir = root.joinpath(*_QA_OUTPUT_DIR_PARTS)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / _OUTPUT_FILENAME).write_text(json.dumps(payload, indent=2))

    if args.report_stdout:
        print(json.dumps(payload, indent=2))
    elif report.violations:
        print(f"Found {len(report.violations)} repo-hygiene violation(s):")
        for violation in report.violations:
            print(f"  [{violation.rule}] {violation.path}: {violation.message}")
            print(f"    Fix: {violation.remediation}")
    else:
        print("No repo-hygiene violations found")

    return 1 if report.violations else 0


if __name__ == "__main__":
    sys.exit(main())
