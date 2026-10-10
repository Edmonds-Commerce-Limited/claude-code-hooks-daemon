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
from claude_code_hooks_daemon.utils.command_evasion import RESERVED_WORD_PREFIX
from claude_code_hooks_daemon.utils.command_position import command_position_segments
from claude_code_hooks_daemon.utils.shell_segmentation import resolve_shell_word, shell_word_spans

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
# The opening quote counts so that a quoted body (`eval 'cp <wt> src/'`) the
# command-position view leaves as written is still read. A data command's
# quoted argument (`echo "cp <wt> src/"`, `grep 'mv <wt>' docs/`) never reaches
# this pattern: the view blanks it, and it is only a command when its output
# feeds an executor.
#
# The separator class includes the newline: a heredoc body runs each line as
# its own command, so `cp` starting a line is in command position even though
# nothing before it on that line is a separator character.
#
# Shell reserved words between the separator and the verb (`do cp`, `then mv`)
# leave the verb in command position, so they are skipped (Plan 00422 N25).
# So do leading `NAME=value` assignments and a shell invocation up to its `-c`
# (`sh -e -c`, `bash -n -c`, `bash -o pipefail -c`), whose body the
# command-position view splices in without its quotes.
_RELOCATION_VERB_RE = re.compile(
    r"""(?:^|[;&|\n"']|\$\()\s*"""
    + RESERVED_WORD_PREFIX
    + r"(?:[A-Za-z_]\w*=\S*\s+)*(?:sudo\s+)?(?:\S*/)?("
    + "|".join(_RELOCATION_VERBS)
    + r")\b",
    re.IGNORECASE,
)

_SHELL_NAMES = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
# Wrappers that run the command after their own options.
_WRAPPERS = frozenset({"sudo", "env", "command", "nice", "time", "exec"})
_MAX_WRAP_DEPTH = 4


def _is_short_c_option(word: str | None) -> bool:
    """Whether a word is a short-option cluster carrying `-c` (`-c`, `-nc`, `-ec`)."""
    return word is not None and re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", word) is not None


def _effective_command(segment: str, depth: int = 0) -> str:
    """The text of the command a segment finally runs, read word by word.

    Skips `NAME=value` words, wrappers (`sudo`, `env`, ...) with their options and
    a shell invocation up to its `-c`, whose body becomes the command
    (`sudo bash --login -c 'cp ...'`, `/bin/bash -n -c '...'`). Reuses the shared
    word readers; a word they cannot resolve ends the walk with the text as written.
    """
    spans = shell_word_spans(segment)
    words = [resolve_shell_word(segment[a:b]) for a, b in spans]
    index = 0
    while index < len(words):
        word = words[index]
        if word is None:
            return segment[spans[index][0] :]
        name = word.rsplit("/", 1)[-1]
        if (
            re.match(r"[A-Za-z_]\w*=", word)
            or (index > 0 and word.startswith("-"))
            or name in _WRAPPERS
        ):
            index += 1
        elif name in _SHELL_NAMES and depth < _MAX_WRAP_DEPTH:
            body_at = next(
                (
                    i + 1
                    for i in range(index + 1, len(words) - 1)
                    if _is_short_c_option(words[i])
                ),
                None,
            )
            if body_at is None:
                return segment[spans[index][0] :]
            # The command-position view splices a `-c` body in without its quotes, so
            # the body is the rest of the segment; a still-quoted body is one word.
            quoted = body_at == len(words) - 1 and words[body_at] is not None
            body = words[body_at] if quoted else segment[spans[body_at][0] :]
            return _effective_command(body or "", depth + 1)
        else:
            break
    return segment[spans[index][0] :] if index < len(spans) else segment


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
            blocked="`cp`/`mv`/`rsync` from a worktree into the main repo's code dirs",
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

        `command_position_segments` is this repository's answer to "what
        command is actually being run", shared with `destructive_git` and
        `git_stash`. It blanks a `-m`/`-F` message value, a quoted-delimiter
        heredoc body fed to a DATA SINK (not `bash <<'EOF'`, whose receiver
        runs the bytes) and the arguments of `echo`/`grep`, and splits what is
        left into command segments, which are judged one at a time.
        """
        command = get_bash_command(hook_input)
        if not command:
            return False
        # Each command segment is judged on its own tokens. The path patterns
        # run `.*` and would otherwise cross `&&`/`;` into the NEXT command,
        # and a segment that only prints a path (`grep`, `echo`) is blanked by
        # the command-position view unless its output feeds an executor.
        return any(
            self._segment_relocates(segment) for segment in command_position_segments(command)
        )

    def _segment_relocates(self, command: str) -> bool:
        """Whether one command segment relocates a file from a worktree into main-repo code."""
        if not any(prefix in command for prefix in _WORKTREE_PREFIXES):
            return False

        # Check for forbidden operations
        # The verb is looked for in the segment as written and in the command
        # it finally runs (through wrappers and a shell `-c`).
        effective = _effective_command(command)
        if not (_RELOCATION_VERB_RE.search(command) or _RELOCATION_VERB_RE.search(effective)):
            return False
        command = effective if _RELOCATION_VERB_RE.search(effective) else command

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
            "(`src/`, `tests/`, `config/`) are blocked. A copy the other way, from the "
            "main repo into a worktree, is not.\n\n"
            "Worktrees are isolated branches. Cross-copying corrupts that isolation "
            "and can silently overwrite in-progress work.\n\n"
            "Each command is judged on its own: a `grep` or `echo` that only MENTIONS a "
            "worktree path, and a `ls <worktree>/src/ && cp README.md src/` whose copy "
            "does not read the worktree, are allowed. The target must be a main-repo "
            "code dir, so `mv <worktree>/notes.txt tmp.txt` is not blocked.\n\n"
            "**Allowed**: operations within the same worktree branch. "
            "**To merge changes**: use `git merge` or `git cherry-pick` instead."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for worktree file copy handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="cp from worktree to main repo",
                command=(
                    "bash -n -c 'cp untracked/worktrees/acceptance-probe-absent/src/file.py "
                    "src/acceptance-probe-absent.py'"
                ),
                dispatch_as_bash=True,
                description="Blocks copying files from worktree to main repo (breaks isolation)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"CATASTROPHIC",
                    r"worktree.*isolation",
                    r"git merge",
                ],
                safety_notes=(
                    "bash -n only parses, so nothing runs; the source worktree does not exist "
                    "either"
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="rsync from worktree to main repo",
                command=(
                    "bash -n -c 'rsync -a --dry-run "
                    "untracked/worktrees/acceptance-probe-absent/src/ src/'"
                ),
                dispatch_as_bash=True,
                description="Blocks rsync from worktree to main repo",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"from a worktree into the main repo",
                    r"git history",
                ],
                safety_notes=(
                    "bash -n only parses, so nothing runs; --dry-run and a nonexistent source "
                    "worktree back it up"
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
