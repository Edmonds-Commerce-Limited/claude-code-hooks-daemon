"""SecretFileHygieneCheckerHandler -- SessionStart advisory (Plan 00272 Task 6.1).

secret_meta already reports permissions/ownership hygiene for a single
protected path on demand (``bin/hooks-daemon secret-meta``). This handler is
the SESSION-START half: for every protected path (the effective
secret_file_guard globs) that EXISTS on disk, advise -- never block -- when
it is (a) not gitignored, (b) git-tracked, or (c) group/world-readable.

Metadata only. The file's CONTENTS are never opened -- only ``os.walk``
enumeration, ``git check-ignore``/``git ls-files`` and ``stat()`` are used, so
this advisory cannot leak what it is protecting.
"""

import os
import stat
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
        findings = self._collect_findings(project_root, patterns)
        if not findings:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])
        return AdvisoryResult(decision=Decision.ALLOW, context=self._render(findings))

    def _collect_findings(
        self, project_root: Path, patterns: tuple[str, ...]
    ) -> list[tuple[str, list[str]]]:
        findings: list[tuple[str, list[str]]] = []
        for relpath in self._find_protected_files(project_root, patterns):
            issues: list[str] = []
            if not self._is_gitignored(project_root, relpath):
                issues.append(_ISSUE_NOT_GITIGNORED)
            if self._is_tracked(project_root, relpath):
                issues.append(_ISSUE_TRACKED)
            if self._permissions_insecure(project_root / relpath):
                issues.append(_ISSUE_PERMISSIONS)
            if issues:
                findings.append((relpath, issues))
        return findings

    def _find_protected_files(self, project_root: Path, patterns: tuple[str, ...]) -> list[str]:
        """Relative paths under ``project_root`` matching a protected glob.

        Bounded the same way ``sfm.directory_contains_protected`` is: a walk
        past the cap stops rather than stalling SessionStart on a huge tree
        (documented residual, not a guarantee of full coverage).
        """
        if not patterns:
            return []
        found: list[str] = []
        seen = 0
        for current_dir, subdirs, files in os.walk(project_root):
            if _GIT_DIR_NAME in subdirs:
                subdirs.remove(_GIT_DIR_NAME)
            for name in files:
                seen += 1
                if seen > sfm.DIRECTORY_SCAN_MAX_ENTRIES:
                    return found
                full_path = Path(current_dir) / name
                if sfm.path_is_protected(str(full_path), patterns):
                    found.append(str(full_path.relative_to(project_root)))
        return found

    def _is_gitignored(self, project_root: Path, relpath: str) -> bool:
        result = run_git(project_root, "check-ignore", "-q", relpath)
        return result.returncode == 0

    def _is_tracked(self, project_root: Path, relpath: str) -> bool:
        result = run_git(project_root, "ls-files", "--error-unmatch", relpath)
        return result.returncode == 0

    def _permissions_insecure(self, path: Path) -> bool:
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except OSError:
            return False
        return bool(mode & FileMode.DAEMON_UMASK)

    def _render(self, findings: list[tuple[str, list[str]]]) -> list[str]:
        lines = [
            "⚠️  SECRET FILE HYGIENE: a protected path has an unsafe on-disk state",
            "",
        ]
        for relpath, issues in findings:
            lines.append(f"  {relpath}:")
            for issue in issues:
                lines.append(f"    - {issue}")
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
            "**Metadata only.** The walk uses `os.walk`, `git check-ignore`/"
            "`git ls-files` and `stat()` -- the file's CONTENTS are never opened, "
            "so this advisory cannot leak what it protects. This is the "
            "SessionStart half of the permissions/ownership hygiene the "
            "`secret-meta` CLI already reports on demand for a single path."
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
