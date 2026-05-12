"""Git branch handler for status line.

Shows current git branch with magicmonty-style status icons:
↑N ahead, ↓N behind, ●N staged, ✚N changed, ✖N conflicts,
…N untracked, ⚑N stashed.

Fails silently if not in a git repo or if git commands error.
"""

import logging
import subprocess  # nosec B404 - subprocess used for git commands only (trusted system tool)
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority, Timeout
from claude_code_hooks_daemon.core import Decision, Handler, HookResult

logger = logging.getLogger(__name__)

_COLOR_GREEN = "\033[32m"
_COLOR_RED = "\033[31m"
_COLOR_YELLOW = "\033[33m"
_COLOR_CYAN = "\033[36m"
_COLOR_GREY = "\033[37m"
_COLOR_ORANGE = "\033[38;5;208m"
_COLOR_RESET = "\033[0m"

_ICON_AHEAD = "↑"
_ICON_BEHIND = "↓"
_ICON_STAGED = "●"
_ICON_CHANGED = "✚"
_ICON_CONFLICTS = "✖"
_ICON_UNTRACKED = "…"
_ICON_STASHED = "⚑"

_PORCELAIN_BRANCH_AB_PREFIX = "# branch.ab "
_PORCELAIN_UNTRACKED_PREFIX = "? "
_PORCELAIN_ORDINARY_PREFIX = "1 "
_PORCELAIN_RENAMED_PREFIX = "2 "
_PORCELAIN_UNMERGED_PREFIX = "u "
_PORCELAIN_UNCHANGED = "."
_PORCELAIN_XY_START = 2
_PORCELAIN_XY_END = 4
_BRANCH_AB_FIELD_COUNT = 2


class GitBranchHandler(Handler):
    """Show current git branch with magicmonty-style status icons if in a git repo."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.GIT_BRANCH,
            priority=Priority.GIT_BRANCH,
            terminal=False,
            tags=[HandlerTag.STATUS, HandlerTag.GIT, HandlerTag.NON_TERMINAL],
        )
        self._default_branch: str | None = None
        self._default_branch_detected: bool = False

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Get current git branch with status icons and format for status line.

        Args:
            hook_input: Status event input with workspace data

        Returns:
            HookResult with formatted git branch + icons, or empty if not in git repo
        """
        workspace = hook_input.get("workspace", {})
        cwd = workspace.get("current_dir") or workspace.get("project_dir")

        if not cwd or not Path(cwd).exists():
            return HookResult(context=[])

        try:
            result = subprocess.run(  # nosec B603 B607 - git is trusted system tool, no user input
                ["git", "rev-parse", "--show-toplevel"],
                cwd=cwd,
                capture_output=True,
                timeout=Timeout.GIT_STATUS_SHORT,
                check=False,
            )

            if result.returncode != 0:
                return HookResult(context=[])

            result = subprocess.run(  # nosec B603 B607 - git is trusted system tool, no user input
                ["git", "branch", "--show-current"],
                cwd=cwd,
                capture_output=True,
                timeout=Timeout.GIT_STATUS_SHORT,
                check=True,
            )

            branch = result.stdout.decode().strip()
            if branch:
                if not self._default_branch_detected:
                    self._default_branch = self._get_default_branch(cwd)
                    self._default_branch_detected = True
                if self._default_branch is None:
                    color = _COLOR_GREY
                elif branch == self._default_branch:
                    color = _COLOR_GREEN
                else:
                    color = _COLOR_ORANGE
                icons = self._format_git_status_icons(cwd)
                return HookResult(context=[f"| ⎇ {color}{branch}{_COLOR_RESET}{icons}"])

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.debug("Failed to get git branch: %s", e)
        except Exception as e:
            logger.error("Unexpected error in git branch handler: %s", e, exc_info=True)

        return HookResult(context=[])

    def _get_default_branch(self, cwd: str) -> str | None:
        """Detect the default branch for the repo.

        Strategy:
        1. Try git symbolic-ref refs/remotes/origin/HEAD (fast, no network)
        2. Fall back to checking if 'main' or 'master' exist locally
        3. Return None if undetermined (branch will be shown grey)
        """
        try:
            result = subprocess.run(  # nosec B603 B607 - git is trusted system tool, no user input
                ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
                cwd=cwd,
                capture_output=True,
                timeout=Timeout.GIT_STATUS_SHORT,
                check=False,
            )
            if result.returncode == 0:
                return result.stdout.decode().strip().split("/")[-1]

            for candidate in ("main", "master"):
                result = (
                    subprocess.run(  # nosec B603 B607 - git is trusted system tool, no user input
                        ["git", "show-ref", "--verify", f"refs/heads/{candidate}"],
                        cwd=cwd,
                        capture_output=True,
                        timeout=Timeout.GIT_STATUS_SHORT,
                        check=False,
                    )
                )
                if result.returncode == 0:
                    return candidate
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.debug("Failed to detect default branch: %s", e)

        return None

    def _format_git_status_icons(self, cwd: str) -> str:
        """Render magicmonty-style status icons after the branch name.

        Parses ``git status --porcelain=v2 --branch`` for ahead/behind,
        staged/unstaged change counts, untracked files, and conflicts, then
        appends a stash count from ``git stash list``.

        Returns:
            Leading-space-prefixed icon string (e.g. ' ↑2 ●1 ✚3'), or an
            empty string on any subprocess failure / clean working tree.
        """
        try:
            result = subprocess.run(  # nosec B603 B607 - git is trusted system tool, no user input
                ["git", "status", "--porcelain=v2", "--branch"],
                cwd=cwd,
                capture_output=True,
                timeout=Timeout.GIT_STATUS_SHORT,
                check=False,
            )
            if result.returncode != 0:
                return ""

            ahead, behind, staged, changed, untracked, conflicts = self._parse_porcelain(
                result.stdout.decode()
            )
            stashed = self._get_stash_count(cwd)
            return self._render_icons(
                ahead=ahead,
                behind=behind,
                staged=staged,
                changed=changed,
                conflicts=conflicts,
                untracked=untracked,
                stashed=stashed,
            )
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.debug("Failed to render git status icons: %s", e)
            return ""
        except Exception as e:
            logger.error("Unexpected error in git status icons: %s", e, exc_info=True)
            return ""

    @staticmethod
    def _parse_porcelain(stdout: str) -> tuple[int, int, int, int, int, int]:
        """Parse porcelain v2 output into (ahead, behind, staged, changed, untracked, conflicts).

        Lines we recognise:
            ``# branch.ab +N -M`` — ahead/behind counts
            ``1 XY ...`` / ``2 XY ...`` — ordinary/renamed entries (X=staged, Y=worktree)
            ``? path`` — untracked
            ``u XY ...`` — unmerged (conflict)
        """
        ahead = behind = staged = changed = untracked = conflicts = 0
        for line in stdout.splitlines():
            if line.startswith(_PORCELAIN_BRANCH_AB_PREFIX):
                fields = line[len(_PORCELAIN_BRANCH_AB_PREFIX) :].split()
                if len(fields) == _BRANCH_AB_FIELD_COUNT:
                    a, b = GitBranchHandler._parse_branch_ab(fields[0], fields[1])
                    if a is not None and b is not None:
                        ahead, behind = a, b
            elif line.startswith(_PORCELAIN_UNTRACKED_PREFIX):
                untracked += 1
            elif line.startswith(_PORCELAIN_ORDINARY_PREFIX) or line.startswith(
                _PORCELAIN_RENAMED_PREFIX
            ):
                xy = line[_PORCELAIN_XY_START:_PORCELAIN_XY_END]
                if len(xy) >= _BRANCH_AB_FIELD_COUNT:
                    if xy[0] != _PORCELAIN_UNCHANGED:
                        staged += 1
                    if xy[1] != _PORCELAIN_UNCHANGED:
                        changed += 1
            elif line.startswith(_PORCELAIN_UNMERGED_PREFIX):
                conflicts += 1
        return ahead, behind, staged, changed, untracked, conflicts

    @staticmethod
    def _parse_branch_ab(ahead_field: str, behind_field: str) -> tuple[int | None, int | None]:
        """Parse the ``+N -M`` fields of a ``# branch.ab`` line.

        Returns (None, None) when either field is malformed — caller keeps prior values.
        """
        try:
            return int(ahead_field.lstrip("+")), int(behind_field.lstrip("-"))
        except ValueError as e:
            logger.debug("Malformed branch.ab fields %r %r: %s", ahead_field, behind_field, e)
            return None, None

    @staticmethod
    def _render_icons(
        *,
        ahead: int,
        behind: int,
        staged: int,
        changed: int,
        conflicts: int,
        untracked: int,
        stashed: int,
    ) -> str:
        """Render non-zero counts as a space-separated, leading-space-prefixed icon string."""
        parts: list[str] = []
        if ahead:
            parts.append(f"{_COLOR_GREEN}{_ICON_AHEAD}{ahead}{_COLOR_RESET}")
        if behind:
            parts.append(f"{_COLOR_RED}{_ICON_BEHIND}{behind}{_COLOR_RESET}")
        if staged:
            parts.append(f"{_COLOR_GREEN}{_ICON_STAGED}{staged}{_COLOR_RESET}")
        if changed:
            parts.append(f"{_COLOR_YELLOW}{_ICON_CHANGED}{changed}{_COLOR_RESET}")
        if conflicts:
            parts.append(f"{_COLOR_RED}{_ICON_CONFLICTS}{conflicts}{_COLOR_RESET}")
        if untracked:
            parts.append(f"{_COLOR_GREY}{_ICON_UNTRACKED}{untracked}{_COLOR_RESET}")
        if stashed:
            parts.append(f"{_COLOR_CYAN}{_ICON_STASHED}{stashed}{_COLOR_RESET}")
        if not parts:
            return ""
        return " " + " ".join(parts)

    def _get_stash_count(self, cwd: str) -> int:
        """Return the number of stashed entries (``git stash list`` line count).

        Returns 0 on any subprocess failure.
        """
        try:
            result = subprocess.run(  # nosec B603 B607 - git is trusted system tool, no user input
                ["git", "stash", "list"],
                cwd=cwd,
                capture_output=True,
                timeout=Timeout.GIT_STATUS_SHORT,
                check=False,
            )
            if result.returncode != 0:
                return 0
            return sum(1 for line in result.stdout.decode().splitlines() if line.strip())
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
            return 0

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="git branch handler test",
                command='echo "test"',
                description="Tests git branch handler functionality",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
