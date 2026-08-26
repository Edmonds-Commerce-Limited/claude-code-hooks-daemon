"""SecretFileHygieneCheckerHandler -- SessionStart advisory (Plan 00272 Task 6.1).

secret_meta already reports permissions/ownership hygiene for a single
protected path on demand (``bin/hooks-daemon secret-meta``). This handler is
the SESSION-START half: for every protected path (the effective
secret_file_guard globs) that EXISTS on disk, advise -- never block -- when
it is (a) not gitignored, (b) git-tracked, or (c) group/world-readable.

Metadata only. The file's CONTENTS are never opened -- only ``git ls-files``
(three cheap, index-backed enumerations, no filesystem walk) and ``stat()``
are used, so this advisory cannot leak what it is protecting.

**File enumeration is git-native, not a blind ``os.walk``** (Plan 00272 code
review): an unfiltered directory walk with an entry cap can exhaust its cap
inside an unrelated large subtree (``tests/``, ``node_modules/``) before ever
reaching the directory a protected file actually lives in, and would then
silently report the tree clean -- worse than not scanning at all, because it
looks like a real answer. ``git ls-files`` answers tracked/ignored/untracked
status directly from the index, which is exactly the three states this
handler needs, so enumeration and classification collapse into ONE cheap
call per state instead of a walk plus a `check-ignore`/`ls-files` pair per
candidate file.

**Not a git repository** (or ``git`` unavailable): falls back to a bounded
``os.walk`` for PERMISSIONS-only checking (gitignore/tracked status is
meaningless without git). If the bound is hit, that is reported explicitly
in the advisory -- a truncated scan must never present as a clean one.
"""

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.constants.permissions import FileMode
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.git_repo import run_git
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

_CHMOD_HINT: Final[str] = "chmod 600 <path> (owner read/write only)"
_GIT_DIR_NAME: Final[str] = ".git"

_ISSUE_NOT_GITIGNORED: Final[str] = "not gitignored -- add it to .gitignore"
_ISSUE_TRACKED: Final[str] = "git-tracked -- untrack it: git rm --cached <path>"
_ISSUE_PERMISSIONS: Final[str] = f"group/world-readable -- run: {_CHMOD_HINT}"

_NOT_A_REPO_NOTICE: Final[str] = (
    "not a git repository (or git is unavailable): gitignore/tracked checks "
    "were SKIPPED -- only permissions were checked"
)
_TRUNCATED_NOTICE: Final[str] = (
    "the non-git fallback scan hit its file-count bound before finishing -- "
    "this result is INCOMPLETE, not a clean bill of health"
)


@dataclass(frozen=True)
class _RepoScan:
    """The three git-native file-state sets this handler needs.

    ``all_paths`` is the union -- every path git knows about at all
    (tracked, or untracked-and-visible, or untracked-and-ignored) -- so
    membership in ``tracked``/``ignored`` directly answers both hygiene
    questions without a second git call per candidate file.
    """

    tracked: frozenset[str]
    ignored: frozenset[str]
    all_paths: frozenset[str]


class SecretFileHygieneCheckerHandler(SessionStartHandlerBase):
    """Advise (never block) unsafe on-disk state for existing protected files."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SECRET_FILE_HYGIENE_CHECKER,
            priority=Priority.SECRET_FILE_HYGIENE_CHECKER,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.SAFETY,
                HandlerTag.NON_TERMINAL,
                HandlerTag.ENVIRONMENT,
            ],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return not is_resume_session(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        project_root = ProjectContext.project_root()
        patterns = sfm.resolve_configured_patterns()
        scan = self._scan_repo(project_root)

        if scan is not None:
            findings = self._collect_findings_git(project_root, patterns, scan)
            if not findings:
                return AdvisoryResult(decision=Decision.ALLOW, context=[])
            return AdvisoryResult(decision=Decision.ALLOW, context=self._render(findings))

        # Fallback: no git available. gitignore/tracked status is meaningless
        # here, so only permissions are checked -- and the notice that this
        # happened is NEVER dropped, even when nothing else is found.
        protected, truncated = self._find_protected_files_fallback(project_root, patterns)
        findings = self._collect_findings_permissions_only(project_root, protected)
        if not findings and not truncated:
            return AdvisoryResult(
                decision=Decision.ALLOW, context=[f"⚠️  SECRET FILE HYGIENE: {_NOT_A_REPO_NOTICE}"]
            )
        return AdvisoryResult(
            decision=Decision.ALLOW,
            context=self._render(findings, not_a_repo=True, truncated=truncated),
        )

    # ------------------------------------------------------------------
    # git-native path (primary)
    # ------------------------------------------------------------------

    def _scan_repo(self, project_root: Path) -> _RepoScan | None:
        """The three git file-state sets, or ``None`` if git enumeration failed.

        A ``None`` result (not a repository, or git is unavailable) tells the
        caller to fall back rather than to silently treat "git failed" as
        "nothing is ignored" -- a non-git directory must never be reported as
        a pile of ungitignored secrets.
        """
        tracked = self._git_paths(project_root, "--cached")
        if tracked is None:
            return None
        others = self._git_paths(project_root, "--others", "--exclude-standard")
        if others is None:
            return None
        ignored = self._git_paths(project_root, "--others", "--ignored", "--exclude-standard")
        if ignored is None:
            return None
        return _RepoScan(tracked=tracked, ignored=ignored, all_paths=tracked | others | ignored)

    def _git_paths(self, project_root: Path, *flags: str) -> frozenset[str] | None:
        result = run_git(project_root, "ls-files", *flags)
        if result.returncode != 0:
            return None
        return frozenset(line for line in result.stdout.splitlines() if line)

    def _collect_findings_git(
        self, project_root: Path, patterns: tuple[str, ...], scan: _RepoScan
    ) -> list[tuple[str, list[str]]]:
        findings: list[tuple[str, list[str]]] = []
        for relpath in sorted(scan.all_paths):
            if not sfm.path_is_protected(str(project_root / relpath), patterns):
                continue
            issues: list[str] = []
            if relpath not in scan.ignored:
                issues.append(_ISSUE_NOT_GITIGNORED)
            if relpath in scan.tracked:
                issues.append(_ISSUE_TRACKED)
            if self._permissions_insecure(project_root / relpath):
                issues.append(_ISSUE_PERMISSIONS)
            if issues:
                findings.append((relpath, issues))
        return findings

    # ------------------------------------------------------------------
    # non-git fallback (permissions only)
    # ------------------------------------------------------------------

    def _find_protected_files_fallback(
        self, project_root: Path, patterns: tuple[str, ...]
    ) -> tuple[list[str], bool]:
        """Bounded ``os.walk`` fallback; returns ``(paths, truncated)``.

        ``truncated`` is ``True`` the moment the cap is hit, and the caller
        MUST surface that in the advisory -- a capped walk that stops mid-tree
        is not evidence the rest of the tree is clean.
        """
        if not patterns:
            return [], False
        found: list[str] = []
        seen = 0
        for current_dir, subdirs, files in os.walk(project_root):
            if _GIT_DIR_NAME in subdirs:
                subdirs.remove(_GIT_DIR_NAME)
            for name in files:
                seen += 1
                if seen > sfm.DIRECTORY_SCAN_MAX_ENTRIES:
                    return found, True
                full_path = Path(current_dir) / name
                if sfm.path_is_protected(str(full_path), patterns):
                    found.append(str(full_path.relative_to(project_root)))
        return found, False

    def _collect_findings_permissions_only(
        self, project_root: Path, relpaths: list[str]
    ) -> list[tuple[str, list[str]]]:
        findings: list[tuple[str, list[str]]] = []
        for relpath in relpaths:
            if self._permissions_insecure(project_root / relpath):
                findings.append((relpath, [_ISSUE_PERMISSIONS]))
        return findings

    # ------------------------------------------------------------------
    # shared
    # ------------------------------------------------------------------

    def _permissions_insecure(self, path: Path) -> bool:
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except OSError:
            return False
        return bool(mode & FileMode.GROUP_OTHER_MASK)

    def _render(
        self,
        findings: list[tuple[str, list[str]]],
        *,
        not_a_repo: bool = False,
        truncated: bool = False,
    ) -> list[str]:
        lines = [
            "⚠️  SECRET FILE HYGIENE: a protected path has an unsafe on-disk state",
            "",
        ]
        for relpath, issues in findings:
            lines.append(f"  {relpath}:")
            for issue in issues:
                lines.append(f"    - {issue}")
        if not_a_repo:
            lines += ["", _NOT_A_REPO_NOTICE]
        if truncated:
            lines += ["", _TRUNCATED_NOTICE]
        lines += ["", "Metadata only -- content was never read."]
        return lines

    def get_default_enabled(self) -> bool:
        return True

    def get_claude_md(self) -> str | None:
        return (
            "## secret_file_hygiene_checker -- on-disk hygiene for protected paths\n\n"
            "At SessionStart, for every configured protected path (the effective "
            "`secret_file_guard` globs) that EXISTS on disk, this advisory reports "
            "(never blocks) when it is:\n\n"
            "- **not gitignored** -- add it to `.gitignore`\n"
            "- **git-tracked** -- `git rm --cached <path>` to untrack it\n"
            "- **group/world-readable** -- `chmod 600 <path>`\n\n"
            "**Metadata only.** Files are enumerated via `git ls-files` (tracked, "
            "untracked-visible and untracked-ignored -- three cheap index reads, "
            "no filesystem walk) and checked with `stat()` -- the file's CONTENTS "
            "are never opened, so this advisory cannot leak what it protects. This "
            "is the SessionStart half of the permissions/ownership hygiene the "
            "`secret-meta` CLI already reports on demand for a single path.\n\n"
            "**Outside a git repository** (or when `git` is unavailable), "
            "gitignore/tracked status is meaningless, so only permissions are "
            "checked via a bounded fallback walk -- and if that walk hits its "
            "file-count bound, the advisory says so explicitly rather than "
            "reporting a truncated scan as a clean one."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="secret_file_hygiene_checker - advises on session start",
                command='echo "test"',
                description=(
                    "Verifies the hygiene advisory runs on new sessions and reports "
                    "any protected path with unsafe on-disk state, without ever "
                    "reading its contents."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Advisory handler - never blocks; silent when clean",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session only)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
