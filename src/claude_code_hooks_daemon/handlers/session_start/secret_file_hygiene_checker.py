"""SecretFileHygieneCheckerHandler -- SessionStart advisory (Plan 00272 Task 6.1).

secret_meta already reports permissions/ownership hygiene for a single
protected path on demand (``bin/hooks-daemon secret-meta``). This handler is
the SESSION-START half: for every protected path (the effective
secret_file_guard globs) that EXISTS on disk, advise -- never block -- when
it is (a) not gitignored, (b) git-tracked, or (c) group/world-readable.

Content never enters the advisory. Files are found and classified by
``utils.git_file_states`` (``git ls-files`` per state, no filesystem walk)
and judged with ``stat()``, plus ONE content check that runs inside the
daemon and returns only a format name: ``utils.encrypted_at_rest`` (Plan
00459).

A file that is a whole-file Ansible Vault payload is ciphertext, and
tracking it is the point of Vault, so it gets no gitignore, untrack or
permissions finding. The reverse is advised instead: ciphertext that is
untracked, or that an ignore rule matches, is told how to come back under
version control -- the state a project is left in by following this
handler's own earlier advice. A YAML file with inline ``!vault`` values gets
a conditional statement instead of the untrack advice, because only its
owner knows whether every secret in it is vaulted.

**Not a git repository** (or ``git`` unavailable): falls back to a bounded
``os.walk`` for PERMISSIONS-only checking (gitignore/tracked status is
meaningless without git). If the bound is hit, that is reported explicitly
in the advisory -- a truncated scan must never present as a clean one.
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
from claude_code_hooks_daemon.utils.encrypted_at_rest import AtRestFormat, classify_at_rest
from claude_code_hooks_daemon.utils.git_file_states import (
    GitFileStates,
    scan_git_file_states,
    unignore_advice,
)
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

_CHMOD_HINT: Final[str] = "chmod 600 <path> (owner read/write only)"
_GIT_DIR_NAME: Final[str] = ".git"

_ISSUE_NOT_GITIGNORED: Final[str] = "not gitignored -- add it to .gitignore"
_ISSUE_TRACKED: Final[str] = "git-tracked -- untrack it: git rm --cached <path>"
_ISSUE_PERMISSIONS: Final[str] = f"group/world-readable -- run: {_CHMOD_HINT}"
_ISSUE_INLINE_VAULT: Final[str] = (
    "has inline `!vault` values -- tracking it is correct ONLY if every secret "
    "value in it is vaulted; the daemon cannot verify that, so reads stay denied"
)

_ENCRYPTED_SHOULD_BE_TRACKED: Final[str] = (
    "encrypted at rest (whole-file Ansible Vault) and SHOULD be tracked"
)
_ADD_STEP: Final[str] = "`git add {relpath}`"

_ENCRYPTED_HEADING: Final[str] = (
    "Encrypted at rest (whole-file Ansible Vault) -- tracking is correct, no action. "
    "It would need action only if decrypted in place:"
)
_CONTENT_NOTICE: Final[str] = (
    "Content never enters this advisory: the only read is the daemon's own "
    "encrypted-at-rest format check."
)

#: One file's findings: ``(relpath, issues)``.
_Finding = tuple[str, list[str]]

_NOT_A_REPO_NOTICE: Final[str] = (
    "not a git repository (or git is unavailable): gitignore/tracked checks "
    "were SKIPPED -- only permissions were checked"
)
_TRUNCATED_NOTICE: Final[str] = (
    "the non-git fallback scan hit its file-count bound before finishing -- "
    "this result is INCOMPLETE, not a clean bill of health"
)


def _encrypted_recovery(relpath: str, *, tracked: bool, ignored: bool) -> str | None:
    """How to bring ciphertext back under version control, or None if it is."""
    steps: list[str] = []
    if ignored:
        steps.append(unignore_advice(relpath))
    if not tracked:
        steps.append(_ADD_STEP.format(relpath=relpath))
    if not steps:
        return None
    return f"{_ENCRYPTED_SHOULD_BE_TRACKED} -- " + ", then ".join(steps)


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
        scan = scan_git_file_states(project_root)

        if scan is not None:
            findings, encrypted = self._collect_findings_git(project_root, patterns, scan)
            # A project whose only matches are encrypted gets no output at
            # all: the warning simply stops (Plan 00459).
            if not findings:
                return AdvisoryResult(decision=Decision.ALLOW, context=[])
            return AdvisoryResult(
                decision=Decision.ALLOW, context=self._render(findings, encrypted=encrypted)
            )

        # Fallback: no git available. gitignore/tracked status is meaningless
        # here, so only permissions are checked -- and the notice that this
        # happened is NEVER dropped, even when nothing else is found.
        protected, truncated = self._find_protected_files_fallback(project_root, patterns)
        findings, encrypted = self._collect_findings_permissions_only(project_root, protected)
        if not findings and not truncated:
            return AdvisoryResult(
                decision=Decision.ALLOW, context=[f"⚠️  SECRET FILE HYGIENE: {_NOT_A_REPO_NOTICE}"]
            )
        return AdvisoryResult(
            decision=Decision.ALLOW,
            context=self._render(
                findings, encrypted=encrypted, not_a_repo=True, truncated=truncated
            ),
        )

    # ------------------------------------------------------------------
    # git-native path (primary)
    # ------------------------------------------------------------------

    def _collect_findings_git(
        self, project_root: Path, patterns: tuple[str, ...], scan: GitFileStates
    ) -> tuple[list[_Finding], list[str]]:
        """``(findings, encrypted relpaths)`` for every protected path git knows.

        ``scan`` is ``None``-checked by the caller: a failed git enumeration
        falls back rather than reading as "nothing is ignored", so a non-git
        directory is never reported as a pile of ungitignored secrets.
        """
        findings: list[_Finding] = []
        encrypted: list[str] = []
        for relpath in sorted(scan.all_paths):
            if not sfm.path_is_protected(str(project_root / relpath), patterns):
                continue
            at_rest = classify_at_rest(project_root / relpath, project_root)
            if at_rest is AtRestFormat.ANSIBLE_VAULT:
                recovery = _encrypted_recovery(
                    relpath, tracked=relpath in scan.tracked, ignored=scan.is_ignored(relpath)
                )
                if recovery is None:
                    encrypted.append(relpath)
                else:
                    findings.append((relpath, [recovery]))
                continue
            issues: list[str] = []
            if at_rest is AtRestFormat.ANSIBLE_VAULT_INLINE:
                if relpath not in scan.ignored_untracked or relpath in scan.tracked:
                    issues.append(_ISSUE_INLINE_VAULT)
            else:
                if relpath not in scan.ignored_untracked:
                    issues.append(_ISSUE_NOT_GITIGNORED)
                if relpath in scan.tracked:
                    issues.append(_ISSUE_TRACKED)
            if self._permissions_insecure(project_root / relpath):
                issues.append(_ISSUE_PERMISSIONS)
            if issues:
                findings.append((relpath, issues))
        return findings, encrypted

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
    ) -> tuple[list[_Finding], list[str]]:
        findings: list[_Finding] = []
        encrypted: list[str] = []
        for relpath in relpaths:
            if classify_at_rest(project_root / relpath, project_root) is AtRestFormat.ANSIBLE_VAULT:
                encrypted.append(relpath)
            elif self._permissions_insecure(project_root / relpath):
                findings.append((relpath, [_ISSUE_PERMISSIONS]))
        return findings, encrypted

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
        findings: list[_Finding],
        *,
        encrypted: list[str],
        not_a_repo: bool = False,
        truncated: bool = False,
    ) -> list[str]:
        lines = [
            "⚠️  SECRET FILE HYGIENE: protected paths need attention",
            "",
        ]
        for relpath, issues in findings:
            lines.append(f"  {relpath}:")
            for issue in issues:
                lines.append(f"    - {issue}")
        if encrypted:
            # Named so a reader is not left wondering why a file matching the
            # same glob is missing from the list above.
            lines += ["", _ENCRYPTED_HEADING]
            lines += [f"  {relpath}" for relpath in encrypted]
        if not_a_repo:
            lines += ["", _NOT_A_REPO_NOTICE]
        if truncated:
            lines += ["", _TRUNCATED_NOTICE]
        lines += ["", _CONTENT_NOTICE]
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
            "**A file encrypted at rest is left alone.** When the file's content "
            "is a whole-file Ansible Vault payload (`$ANSIBLE_VAULT;...` header "
            "and hex armour, checked every session), it is ciphertext and "
            "committing it is the point of Vault: it gets none of the findings "
            "above, and the advisory stays silent if nothing else is wrong. "
            "Ciphertext that is untracked or gitignored -- the state an earlier "
            "version of this advice left projects in -- is told to come back: "
            "remove the ignore rule or add `!/<path>` after it, then "
            "`git add <path>`. The same file decrypted in place gets the full "
            "untrack advice again. A YAML "
            "file with inline `!vault |` values gets one statement instead: "
            "tracking it is correct only if EVERY secret value in it is vaulted, "
            "which the daemon cannot verify.\n\n"
            "**Content never enters the advisory.** Files are enumerated via "
            "`git ls-files` (tracked, untracked-visible and untracked-ignored -- "
            "three cheap index reads, no filesystem walk) and checked with "
            "`stat()`; the one content read is the encrypted-at-rest format "
            "check, inside the daemon, which returns only a format name. This "
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
