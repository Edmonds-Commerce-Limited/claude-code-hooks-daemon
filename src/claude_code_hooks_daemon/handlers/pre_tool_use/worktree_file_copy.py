"""WorktreeFileCopyHandler - prevents copying files between worktrees and main repo."""

import re
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.paths import ProjectPath
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler import WorkspaceScope
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_layout import main_repo_code_dirs
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.shell_segmentation import strip_inert_spans

# Both worktree root prefixes — untracked/ is manually managed, .claude/ is Claude Code managed
_WORKTREE_PREFIXES = (ProjectPath.WORKTREES_DIR, ProjectPath.CLAUDE_WORKTREES_DIR)

# Regex alternation matching either worktree root (used in pattern strings below).
# Derived from _WORKTREE_PREFIXES (Plan 00288 Task 4.6/C8) rather than a second,
# independently hardcoded literal that could drift from it.
_WORKTREE_RE = "(?:" + "|".join(re.escape(prefix) for prefix in _WORKTREE_PREFIXES) + ")"

# The verbs that RELOCATE a file. Named rather than inlined so the
# `declared-invariant-pairs` Detector can read them and hold this list against
# `core.utils._WRITE_INDICATOR_RE`, the other place this repository enumerates
# the same idea. An alternation inlined at its only call site has no sibling to
# be checked against, and drifts from one silently.
#
# The declared relation is a SUPERSET, not equality: `rsync` matters to this
# handler and is not a plain write indicator, so it is absent from the sibling
# by design.
_RELOCATION_VERBS: tuple[str, ...] = ("cp", "mv", "rsync", "install", "dd")

# The verb must sit where a program NAME would: start of string, after a
# separator, after a `$(`, or after an opening QUOTE — optionally through
# `sudo` and a path prefix. A bare `\b(cp|mv|...)\b` search anywhere in the
# string cannot tell the coreutils `install`/`dd` this handler exists to
# catch from the same word used as another program's SUBCOMMAND, so
# `pip install -r requirements.txt` inside a worktree earned a TERMINAL deny
# announcing catastrophic data loss. In `pip install` the program is `pip`;
# `install` is an argument, and argument position is what this excludes.
#
# The opening quote counts, and that is load-bearing rather than incidental.
# Every acceptance probe in this project wraps its command in `echo "..."` so
# that a guard under test can never destroy anything when it is the guard
# that is broken, and the guards are TEXT scanners for exactly that reason.
# Requiring true command position would make `echo "cp <worktree> src/"` stop
# matching, which reads as a passing probe against a handler that has
# silently stopped working — the failure this handler's own deny message
# calls CATASTROPHIC.
#
# The separator class includes the newline: a heredoc body runs each line as
# its own command, so `cp` starting a line is in command position even though
# nothing before it on that line is a separator character.
_RELOCATION_VERB_RE = re.compile(
    r"""(?:^|[;&|\n"']|\$\()\s*(?:sudo\s+)?(?:\S*/)?(""" + "|".join(_RELOCATION_VERBS) + r")\b",
    re.IGNORECASE,
)


class WorktreeFileCopyHandler(PreToolUseHandlerBase):
    """Prevent copying files between worktrees and main repo."""

    # PROJECT-scoped: the "main repo code dirs" alternation aggregates every
    # declared project's source/test/config dirs (see
    # CLAUDE/Code/WorkspaceResolution.md).
    workspace_scope: ClassVar[WorkspaceScope] = WorkspaceScope.PROJECT

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.WORKTREE_FILE_COPY,
            priority=Priority.WORKTREE_FILE_COPY,
            tags=[HandlerTag.SAFETY, HandlerTag.GIT, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        self._rule = Rule(
            rule_id=RuleID.WORKTREE_FILE_COPY,
            blocked="`cp`/`mv`/`rsync` between a worktree and the main repo",
            why="Defeats worktree isolation, bypasses git tracking, and can "
            "nuke untracked work in the target directory",
            fix="cd into the worktree, commit, then git merge back",
            verbose=(
                "🔥 WHY THIS IS CATASTROPHIC:\n"
                "  1. Defeats entire purpose of worktrees (isolation)\n"
                "  2. Destroys branch isolation\n"
                "  3. Loses git history (bypasses git tracking)\n"
                "  4. Nukes untracked work in target directory\n"
                "  5. Creates merge conflicts\n\n"
                "✅ CORRECT WORKFLOW:\n"
                "  1. cd untracked/worktrees/your-branch\n"
                "  2. git add . && git commit -m 'feat: changes'\n"
                "  3. cd /workspace (main repo)\n"
                "  4. git merge your-branch\n\n"
                "📖 See CLAUDE/Worktree.md for complete guide."
            ),
        )
        self._formatter = RuleFormatter()

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's deny path."""
        return [self._rule]

    def _all_main_repo_code_dirs(self) -> tuple[str, ...]:
        """Union of "main repo code dirs" across every declared project.

        A Bash command's two paths can name any two declared projects (or
        none), so this must aggregate rather than resolve one owning
        project the way a per-file consumer (`tdd_enforcement`) does.
        Falls back to the single root `_project_layout` when no registry
        was injected -- a unit test exercising the handler directly, or a
        zero-config repository, where `iter_layouts()` yields only the root.
        """
        if self._project_registry is None:
            return main_repo_code_dirs(self._project_layout)
        seen: dict[str, None] = {}
        for _, layout in self._project_registry.iter_layouts():
            for name in main_repo_code_dirs(layout):
                seen.setdefault(name, None)
        return tuple(seen)

    def _is_same_worktree_operation(self, command: str) -> bool:
        """Return True if both paths in command refer to the same worktree branch."""
        for prefix in _WORKTREE_PREFIXES:
            if command.count(prefix) >= 2:
                escaped = re.escape(prefix)
                branches = re.findall(rf"{escaped}/([^/\s]+)", command)
                if len(branches) >= 2 and branches[0] == branches[1]:
                    return True
        return False

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if copying between worktree and main repo.

        Judges the command bash will RUN, not the raw string. A `git commit`
        message describing this handler -- naming a worktree path and a
        relocation verb -- is prose that git stores, and denying it reports a
        catastrophic data-loss scenario to someone writing a sentence.

        `strip_inert_spans` is this repository's existing answer to "what
        command is actually being run", shared with `destructive_git`,
        `pipe_blocker`, `merge_to_main_approval` and `daemon_location_guard`.
        It blanks a `-m`/`-F` message value and a quoted-delimiter heredoc body
        fed to a DATA SINK -- and only to a data sink, so `bash <<'EOF'` still
        has its body judged, because the receiver runs those bytes whatever the
        outer shell quoted.
        """
        command = get_bash_command(hook_input)
        if not command:
            return False
        command = strip_inert_spans(command)

        if not any(prefix in command for prefix in _WORKTREE_PREFIXES):
            return False

        # Check for forbidden operations
        if not _RELOCATION_VERB_RE.search(command):
            return False

        # Check patterns — the "main repo code dirs" alternation is built
        # from the ProjectLayout facade (Plan 00288 Task 4.3/C5) rather than
        # hardcoded, so a project declaring extra source/test/config dirs is
        # also protected. A Bash command can name ANY declared project's
        # code dirs (there is no single "owning file" here), so this
        # AGGREGATES across every declared project via `iter_layouts`
        # (Plan 00301 follow-up), never just the root `_project_layout`.
        code_dirs = "|".join(re.escape(d) for d in self._all_main_repo_code_dirs())
        patterns = [
            rf"{_WORKTREE_RE}/[^/\s]+/\S+\s+.*\b({code_dirs})/",
            rf"rsync.*{_WORKTREE_RE}.*\b({code_dirs})\b",
        ]

        for pattern in patterns:
            if re.search(pattern, command, re.IGNORECASE):
                if self._is_same_worktree_operation(command):
                    continue
                return True

        return False

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Block worktree file copying.

        Verbosity is decided per (transcript_path, rule_id) via the shared
        DisclosureTracker (Plan 00116, Decision G). The blocked command is
        invocation-specific evidence and is always appended, regardless of
        disclosure state.
        """
        command = get_bash_command(hook_input)

        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure
        rule_id = self._rule.rule_id

        if transcript_path and tracker.was_disclosed(transcript_path, rule_id):
            message = self._formatter.terse(self._rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, rule_id)
            message = self._formatter.verbose(self._rule)

        message += f"\n\nCommand: {command}"

        return GatingResult(decision=Decision.DENY, reason=message)

    def get_claude_md(self) -> str | None:
        return (
            "## worktree_file_copy — do not copy files between worktrees and the main repo\n\n"
            "`cp`, `mv`, and `rsync` operations that move files from a worktree directory "
            "(`untracked/worktrees/` or `.claude/worktrees/`) into the main repo "
            "(`src/`, `tests/`, `config/`) — or vice versa — are blocked.\n\n"
            "Worktrees are isolated branches. Cross-copying corrupts that isolation "
            "and can silently overwrite in-progress work.\n\n"
            "**Allowed**: operations within the same worktree branch. "
            "**To merge changes**: use `git merge` or `git cherry-pick` instead."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for worktree file copy handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="cp from worktree to main repo",
                command='echo "cp untracked/worktrees/feature-branch/src/file.py src/"',
                dispatch_as_bash=True,
                description="Blocks copying files from worktree to main repo (breaks isolation)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"CATASTROPHIC",
                    r"worktree.*isolation",
                    r"git merge",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="rsync from worktree to main repo",
                command='echo "rsync -av untracked/worktrees/feature/src/ src/"',
                dispatch_as_bash=True,
                description="Blocks rsync from worktree to main repo",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"between a worktree and the main repo",
                    r"git history",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
