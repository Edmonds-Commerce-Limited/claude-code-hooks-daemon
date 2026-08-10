"""DestructiveGitHandler - blocks destructive git commands that permanently destroy data."""

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult, get_data_layer
from claude_code_hooks_daemon.core.utils import get_bash_command

# Generic reason used when a destructive pattern matches but warrants no
# command-specific explanation (e.g. bare `git checkout .`).
_GENERIC_DESTRUCTIVE_REASON = "This git command destroys uncommitted changes permanently"

# Characters that separate shell sub-commands. A flag that appears AFTER one of
# these in a compound command belongs to a DIFFERENT sub-command, so any pattern
# that must stay within a single sub-command segment scopes its match by
# forbidding these characters between the sub-command head and the flag.
_SUBCOMMAND_SEPARATOR_CHARS = ";&|"

# Git accepts GLOBAL OPTIONS between `git` and the subcommand -- `-C <path>`,
# `-c <k>=<v>`, `--git-dir=<path>`, `--work-tree=<path>`, `--no-pager`, and more.
# Every pattern below must tolerate them. Anchoring on a bare `\bgit\s+<sub>`
# made ONE inserted token silently disable the whole handler:
#
#     git reset --hard origin/main            -> denied
#     git -C /path reset --hard origin/main   -> ALLOWED
#
# The same insertion bypassed clean -f, push --force, stash drop and the rest.
# `--git-dir=/repo/.git reset --hard` looked covered, but only by accident: the
# path ends in `.git`, so `\bgit` matched INSIDE THE PATH and `\s+reset` matched
# right after it. Aim it at a directory not ending in `.git` and the block
# disappeared -- so the near-miss also hid how broad the hole was.
#
# An option token starts with `-` and may take a separate value token, which by
# definition does NOT start with `-`. Neither may cross a sub-command separator,
# so a later segment of a compound command can never be dragged into the prefix.
# Deliberately permissive rather than an allowlist of known option names: this
# handler must fail CLOSED, and an unrecognised option must never mean "allow".
_GIT_GLOBAL_OPTION = (
    rf"-[^\s{_SUBCOMMAND_SEPARATOR_CHARS}]+"
    rf"(?:\s+[^-\s{_SUBCOMMAND_SEPARATOR_CHARS}][^\s{_SUBCOMMAND_SEPARATOR_CHARS}]*)?"
)
# `git` followed by any run of global options. Every destructive pattern starts
# with this instead of a bare `\bgit\s+`.
_GIT_INVOCATION = rf"\bgit\s+(?:{_GIT_GLOBAL_OPTION}\s+)*"

# Force-push detection, scoped to the `git push` sub-command segment.
# `[^;&|]*?` consumes only characters within the push segment (never a command
# separator), so a non-push `--force` later in a compound command — e.g.
# `git push origin main; git worktree remove <path> --force` — is NOT matched.
# Within the segment, the long (`--force`, `--force-with-lease`) and short (`-f`)
# force flags all qualify as a destructive force push.
_GIT_PUSH_FORCE_PATTERN = (
    rf"{_GIT_INVOCATION}push\b[^{_SUBCOMMAND_SEPARATOR_CHARS}]*?"
    r"(?:--force(?:-with-lease)?|-f)\b"
)

# SINGLE SOURCE OF TRUTH: ordered (pattern, reason) pairs consumed by BOTH matches()
# and handle(). Order matters — handle() returns the reason of the FIRST matching
# pattern, exactly mirroring matches()' first-hit semantics. Keeping one ordered
# list prevents the pattern source from drifting between the two methods.
_DESTRUCTIVE_PATTERN_REASONS: tuple[tuple[str, str], ...] = (
    (
        rf"{_GIT_INVOCATION}reset\s+.*--hard\b",
        "git reset --hard destroys all uncommitted changes permanently",
    ),
    (
        rf"{_GIT_INVOCATION}clean\s+.*-[a-z]*f",
        "git clean -f permanently deletes untracked files",
    ),
    # Bare `git checkout .` discards working-tree changes; generic reason suffices.
    (
        rf"{_GIT_INVOCATION}checkout\s+\.\s*(?:$|;|&&|\|)",
        _GENERIC_DESTRUCTIVE_REASON,
    ),
    # Match all variants of checkout with -- and a file:
    # git checkout -- file / git checkout HEAD -- file / git checkout main -- file
    (
        rf"{_GIT_INVOCATION}checkout\s+.*--\s+\S",
        "git checkout [REF] -- file discards all local changes to that file permanently",
    ),
    # git restore with file paths discards working-tree changes.
    # Does NOT match the staged-only forms (safe - they only unstage):
    #   git restore --staged file.txt   (long flag)
    #   git restore -S file.txt          (short flag, equivalent to --staged)
    (
        rf"{_GIT_INVOCATION}restore\s+(?!--staged\b)(?!-S\b).*\S",
        "git restore discards all local changes to files permanently",
    ),
    (
        rf"{_GIT_INVOCATION}stash\s+drop\b",
        "git stash drop permanently destroys stashed changes",
    ),
    (
        rf"{_GIT_INVOCATION}stash\s+clear\b",
        "git stash clear permanently destroys all stashed changes",
    ),
    (
        _GIT_PUSH_FORCE_PATTERN,
        "git push --force can overwrite remote history and destroy team members' work",
    ),
    # Force branch deletion bypasses merge check. (?-i:) matches only uppercase -D
    # (lowercase -d is safe, it checks merge status).
    (
        rf"{_GIT_INVOCATION}branch\s+.*(?-i:-D)\b",
        "git branch -D force-deletes a branch without checking if it has been merged",
    ),
    (
        rf"{_GIT_INVOCATION}commit\s+.*--amend\b",
        "git commit --amend rewrites the previous commit, creating messy history "
        "and potential data loss — create a new commit instead",
    ),
)


class DestructiveGitHandler(Handler):
    """Block destructive git commands that permanently destroy data."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DESTRUCTIVE_GIT,
            priority=Priority.DESTRUCTIVE_GIT,
            tags=[HandlerTag.SAFETY, HandlerTag.GIT, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        # Compile the single source-of-truth mapping once, preserving order.
        self._pattern_reasons: tuple[tuple[re.Pattern[str], str], ...] = tuple(
            (re.compile(pattern, re.IGNORECASE), reason)
            for pattern, reason in _DESTRUCTIVE_PATTERN_REASONS
        )

    @property
    def destructive_patterns(self) -> tuple[re.Pattern[str], ...]:
        """Compiled destructive-command patterns (derived from the single mapping)."""
        return tuple(pattern for pattern, _reason in self._pattern_reasons)

    def _match_reason(self, command: str) -> str | None:
        """Return the reason for the first matching destructive pattern, or None."""
        for pattern, reason in self._pattern_reasons:
            if pattern.search(command):
                return reason
        return None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a destructive git command."""
        command = get_bash_command(hook_input)
        if not command or "git" not in command.lower():
            return False

        return self._match_reason(command) is not None

    def _get_block_count(self) -> int:
        """Get number of previous blocks by this handler.

        Falls back to 0 only when the data layer / history is not available
        (AttributeError). Any other error propagates (FAIL FAST) rather than being
        silently swallowed.
        """
        try:
            return get_data_layer().history.count_blocks_by_handler(self.name)
        except AttributeError:
            return 0

    def _terse_reason(self, reason: str, command: str) -> str:
        """Generate terse reason message (first block)."""
        return f"BLOCKED: {reason}. Ask the user to run manually."

    def _standard_reason(self, reason: str, command: str) -> str:
        """Generate standard reason message (blocks 2-3)."""
        return (
            f"BLOCKED: {reason}\n\n"
            f"Command: {command}\n\n"
            "SAFE alternatives:\n"
            "  - git stash        (save changes, can recover later)\n"
            "  - git diff         (review changes first)\n"
            "  - git status       (see what would be affected)\n"
            "  - git commit       (save changes permanently first)\n\n"
            "Ask the user to run this manually if needed."
        )

    def _verbose_reason(self, reason: str, command: str) -> str:
        """Generate verbose reason message (blocks 4+)."""
        return (
            f"BLOCKED: Destructive git command detected\n\n"
            f"Reason: {reason}\n\n"
            f"Command: {command}\n\n"
            "This command PERMANENTLY DESTROYS uncommitted changes with NO recovery possible.\n\n"
            "If this operation is truly necessary, you must ask the human user to run it manually.\n\n"
            "SAFE alternatives:\n"
            "  - git stash        (save changes, can recover later)\n"
            "  - git diff         (review changes first)\n"
            "  - git status       (see what would be affected)\n"
            "  - git commit       (save changes permanently first)\n\n"
            "The LLM is NOT ALLOWED to run destructive git commands. Ask the user to do it."
        )

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block the destructive command with explanation."""
        command = get_bash_command(hook_input)
        if not command:
            return HookResult(decision=Decision.ALLOW)

        # Determine which pattern matched and provide its reason. Both matches() and
        # handle() consume the same ordered mapping, so they can never drift.
        specific_reason = self._match_reason(command) or _GENERIC_DESTRUCTIVE_REASON

        # Get block count and determine verbosity level
        block_count = self._get_block_count()

        if block_count == 0:
            reason = self._terse_reason(specific_reason, command)
        elif block_count <= 2:
            reason = self._standard_reason(specific_reason, command)
        else:
            reason = self._verbose_reason(specific_reason, command)

        return HookResult(
            decision=Decision.DENY,
            reason=reason,
        )

    def get_claude_md(self) -> str | None:
        return (
            "## destructive_git — blocked git commands\n\n"
            "The following git commands are permanently blocked and will always be denied:\n\n"
            "| Command | Reason |\n"
            "|---------|--------|\n"
            "| `git reset --hard` | Permanently destroys all uncommitted changes |\n"
            "| `git clean -f` | Permanently deletes untracked files |\n"
            "| `git checkout -- <file>` | Discards all local changes to that file |\n"
            "| `git restore <file>` | Discards local changes (`--staged` is allowed) |\n"
            "| `git stash drop` | Permanently destroys stashed changes |\n"
            "| `git stash clear` | Permanently destroys all stashes |\n"
            "| `git push --force` | Can overwrite remote history and destroy teammates' work |\n"
            "| `git branch -D` | Force-deletes branch without checking if merged (lowercase `-d` is safe) |\n"
            "| `git commit --amend` | Rewrites the previous commit — create a new commit instead |\n\n"
            "If the user needs to run one of these, ask them to do it manually. "
            "Do not attempt to work around the block.\n\n"
            "**Safe alternatives**: `git stash` (recoverable), `git diff` / `git status` "
            "(inspect first), `git commit` (save changes permanently first)."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for destructive git handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="git reset --hard",
                command='echo "git reset --hard NONEXISTENT_REF_SAFE_TEST"',
                description="Blocks git reset --hard (destroys uncommitted changes)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"destroys.*uncommitted changes",
                ],
                safety_notes="Uses non-existent ref - would fail harmlessly if executed",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git clean -f",
                command='echo "git clean -fd /nonexistent/safe/test/path"',
                description="Blocks git clean -f (permanently deletes untracked files)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"permanently deletes untracked files",
                ],
                safety_notes="Uses non-existent path - would fail harmlessly if executed",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git push --force",
                command='echo "git push --force NONEXISTENT_REMOTE NONEXISTENT_BRANCH"',
                description="Blocks git push --force (overwrites remote history)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"overwrite remote history",
                    r"destroy.*work",
                ],
                safety_notes="Uses non-existent remote/branch - would fail harmlessly if executed",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git stash drop",
                command='echo "git stash drop stash@{999}"',
                description="Blocks git stash drop (permanent deletion)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"permanently destroys",
                    r"stash",
                ],
                safety_notes="Uses non-existent stash index - would fail harmlessly if executed",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git checkout --",
                command='echo "git checkout -- /nonexistent/safe/test/file.py"',
                description="Blocks git checkout -- (discards changes)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"discards.*local changes",
                    r"permanently",
                ],
                safety_notes="Uses non-existent file path - would fail harmlessly if executed",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git restore",
                command='echo "git restore /nonexistent/safe/test/file.py"',
                description="Blocks git restore (discards working tree changes)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"discards.*local changes",
                    r"permanently",
                ],
                safety_notes="Uses non-existent file path - would fail harmlessly if executed",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git branch -D",
                command='echo "git branch -D NONEXISTENT_SAFE_TEST_BRANCH"',
                description="Blocks git branch -D (force-deletes branch without merge check)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"force-deletes.*branch",
                    r"merged",
                ],
                safety_notes="Uses non-existent branch - would fail harmlessly if executed",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git stash clear",
                command='echo "git stash clear"',
                description="Blocks git stash clear (destroys all stashes)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"permanently destroys all",
                    r"stash",
                ],
                safety_notes="Safe to test - only clears stash (recoverable via reflog)",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git commit --amend",
                command='echo "git commit --amend"',
                description="Blocks git commit --amend (rewrites previous commit)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"rewrites the previous commit",
                    r"messy history",
                ],
                safety_notes="Uses echo - command is not actually executed",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git tag -f is not a force push",
                command='echo "git tag -f v1.0.0-test-safe NONEXISTENT_SAFE_TEST_SHA"',
                description=(
                    "git tag -f force-moves a tag; it has nothing to do with "
                    "git push --force and must NOT be blocked. Regression test "
                    "for a dogfooding false positive (Plan 00200) where -f was "
                    "matched too broadly outside the git push segment."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses echo - command is not actually executed",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
