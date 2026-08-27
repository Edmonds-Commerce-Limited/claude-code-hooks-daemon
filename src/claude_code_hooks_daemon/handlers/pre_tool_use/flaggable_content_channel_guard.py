"""FlaggableContentChannelGuardHandler - deny content-revealing git/grep (Plan 00278 Phase 3d.1).

The ``flaggable_work_advisor`` (Phase 3) can only ADVISE that a Read/Edit/
Write/Grep or a Bash mention of a flaggable path should be delegated before
opening the content. It cannot close one specific leak the field report
identified by inspection rather than by an actual flip: ``git diff``,
``git show``, ``git log -p``, ``git add -p``, and the ``grep``/``rg`` family
pull a flaggable file's content into the coordinator's context INSIDE a
routine command's output, with no deliberate ``Read`` at all — a file-handoff
contract does not cover this, because nobody ever decided to read the file.

This handler DENIES that shape deterministically: a Bash command segment
whose SHAPE is content-revealing (a small named constant tuple, extendable
via config) AND that references a configured flaggable path glob. A plain
``git status``, ``git log`` (no ``-p``), or ``git add <path>`` (no ``-p``) is
NOT content-revealing and is never touched — this is a command-SHAPE guard,
not a blanket ban on mentioning a flaggable path in Bash (that is
``flaggable_content_channel_guard``'s narrower, explicit scope; a bare mention
with no revealing shape is left to ``flaggable_work_advisor``'s advisory).

Ships DISABLED: the flaggable boundary is project-specific, matching
``flaggable_work_advisor``. Once enabled, this handler DENIES with no escape
hatch — an agent that could type its own justification would have
self-authorised exactly the disclosure this guard exists to prevent (the
``secret_file_guard`` doctrine).
"""

from __future__ import annotations

import re
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.bash_flags import SPAN_SEPARATORS, split_statements
from claude_code_hooks_daemon.utils.command_evasion import GIT_INVOCATION
from claude_code_hooks_daemon.utils.shell_segmentation import split_unquoted

# ── Config modes (command_hints' clobber-or-extend convention) ──────────────
_MODE_ADDITIVE: Final[str] = "additive"
_MODE_REPLACE: Final[str] = "replace"
_DEFAULT_MODE: Final[str] = _MODE_ADDITIVE

# The flaggable-path seed is deliberately empty -- like flaggable_work_advisor,
# the boundary is project-specific and this handler is inert until configured.
_SEED_PATH_GLOBS: Final[tuple[str, ...]] = ()

# Content-revealing command SHAPES (handover §1.3/§3.3): each pair is a
# human-readable label (echoed in the deny reason) and a regex matched
# against a single command SEGMENT (one statement/span, already split on
# ``;``/``&&``/``||``/``|``/newline). ``git status``, a plain ``git log``, and
# a plain ``git add <path>`` are deliberately absent -- they do not reveal
# content and must stay allowed even when they name a flaggable path.
#
# ``GIT_INVOCATION`` (shared with destructive_git.py) folds in git's own
# global options (``git -C <path> diff``) between the binary and the
# subcommand, and its ``\b`` anchor already tolerates a path-qualified or
# env-prefixed binary (``/usr/bin/git``, ``env git``) for free -- the same
# un-bypassable shape every other command-anchored handler in this codebase
# uses. The grep family has no equivalent "options between name and itself"
# problem, so a bare ``\b`` anchor (no ``^``) is enough for the same reason.
_CONTENT_REVEALING_PATTERNS: Final[tuple[tuple[str, str], ...]] = (
    ("git diff", rf"{GIT_INVOCATION}diff\b"),
    ("git show", rf"{GIT_INVOCATION}show\b"),
    ("git log -p", rf"{GIT_INVOCATION}log\b.*(?:\s-p\b|\s--patch\b)"),
    ("git add -p", rf"{GIT_INVOCATION}add\b.*(?:\s-p\b|\s--patch\b)"),
    ("grep/rg content search", r"\b(?:grep|egrep|fgrep|rg)\b"),
)

# Label attached to a project-supplied ``extra_content_revealing_patterns``
# entry in the deny reason -- these are raw regexes, not named shapes.
_CUSTOM_SHAPE_LABEL: Final[str] = "custom content-revealing pattern"

# Process-lifetime cache, keyed by source string (sensitive_content.py's
# ``_compiled_public_pattern`` precedent).
_COMPILED_SHAPE_CACHE: dict[str, re.Pattern[str] | None] = {}


def _compiled_shape_pattern(pattern: str) -> re.Pattern[str] | None:
    """Compile ``pattern`` (case-insensitive), caching by source string.

    A pattern that fails to compile is a documented no-match (never crashes
    the handler) — cached as ``None`` so a broken client config is not
    re-attempted on every event.
    """
    if pattern in _COMPILED_SHAPE_CACHE:
        return _COMPILED_SHAPE_CACHE[pattern]
    try:
        compiled: re.Pattern[str] | None = re.compile(pattern, re.IGNORECASE)
    except re.error:
        compiled = None
    _COMPILED_SHAPE_CACHE[pattern] = compiled
    return compiled


class FlaggableContentChannelGuardHandler(PreToolUseHandlerBase):
    """Deny content-revealing git/grep commands over configured flaggable paths.

    DENY-BY-SHAPE: ``terminal=True`` and ships DISABLED — a project opts in by
    configuring ``flaggable_path_globs`` (Plan 00278 Phase 3d.1).
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.FLAGGABLE_CONTENT_CHANNEL_GUARD,
            priority=Priority.FLAGGABLE_CONTENT_CHANNEL_GUARD,
            terminal=True,
            tags=[
                HandlerTag.SAFETY,
                HandlerTag.BLOCKING,
                HandlerTag.TERMINAL,
                HandlerTag.FILE_OPS,
            ],
        )
        # Options — injected by the registry via setattr; typed and defaulted
        # here so mypy sees real attributes (command_hints convention).
        self._mode: str = _DEFAULT_MODE
        self._flaggable_path_globs: list[str] = []
        self._extra_content_revealing_patterns: list[str] = []

    def get_default_enabled(self) -> bool:
        """Opt-in: the flaggable boundary is project-specific (Plan 00278)."""
        return False

    # ── Effective config (mode: additive | replace) ─────────────────────────

    def _effective_globs(self) -> list[str]:
        return self._merge_list(_SEED_PATH_GLOBS, self._flaggable_path_globs)

    def _effective_shapes(self) -> list[tuple[str, re.Pattern[str]]]:
        """Built-in content-revealing shapes plus any project-supplied extras.

        Unlike ``_effective_globs``, this is ALWAYS additive regardless of
        ``mode``: removing the built-in git/grep shapes would leave the
        handler unable to detect the exact leak it exists for, so there is
        no supported way to replace them — only to extend the set.
        """
        project_raw = [
            str(p) for p in (self._extra_content_revealing_patterns or []) if str(p).strip()
        ]
        pairs = list(_CONTENT_REVEALING_PATTERNS) + [
            (_CUSTOM_SHAPE_LABEL, pattern) for pattern in project_raw
        ]
        compiled = ((label, _compiled_shape_pattern(pattern)) for label, pattern in pairs)
        return [(label, pattern) for label, pattern in compiled if pattern is not None]

    def _merge_list(self, seed: tuple[str, ...], configured: list[str] | None) -> list[str]:
        """Merge a built-in seed list with the project's configured list.

        ``replace`` discards the seed entirely; anything else (including the
        default) appends project entries to the seed, deduplicated.
        """
        project = [str(entry) for entry in (configured or []) if str(entry).strip()]
        if self._mode == _MODE_REPLACE:
            return project
        merged: list[str] = list(seed)
        for entry in project:
            if entry not in merged:
                merged.append(entry)
        return merged

    # ── Matching ────────────────────────────────────────────────────────────

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return self._matched_reason(hook_input) is not None

    def _matched_reason(self, hook_input: dict[str, Any]) -> tuple[str, str] | None:
        """``(shape_label, matched_glob)`` for the first revealing segment, or None."""
        if not isinstance(hook_input, dict):
            return None
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return None

        globs = tuple(self._effective_globs())
        if not globs:
            return None

        command = get_bash_command(hook_input) or ""
        if not command:
            return None

        shapes = self._effective_shapes()
        if not shapes:
            return None

        for segment in _segments(command):
            for label, pattern in shapes:
                if pattern.search(segment):
                    mention = sfm.find_protected_mention(segment, globs)
                    if mention is not None:
                        return (label, mention)
        return None

    # ── Handling ────────────────────────────────────────────────────────────

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        matched = self._matched_reason(hook_input)
        if matched is None:
            return GatingResult(decision=Decision.ALLOW)

        shape_label, glob = matched
        return GatingResult(
            decision=Decision.DENY,
            reason=(
                "FLAGGABLE CONTENT CHANNEL: this command's shape "
                f"(`{shape_label}`) would reveal the content of a path matching "
                f"the configured flaggable glob `{glob}` inside routine command "
                "output, with no deliberate Read at all.\n\n"
                "Reading or producing attack-mechanics content in THIS context "
                "can silently downgrade the session's model. Delegate the WHOLE "
                "review of this file to the quarantine subagent instead:\n"
                '  Agent(subagent_type: "hooks-daemon-opus-security", '
                "prompt: <goal + files, not a narration>)\n\n"
                "The quarantine subagent owns the entire git cycle for "
                "flaggable files — it stages, commits and pushes them itself. "
                "Confirm CI by status (green/red), never by diffing the "
                "content yourself.\n\n"
                "There is NO escape hatch. Only a human may lift this, by "
                "editing `handlers.pre_tool_use.flaggable_content_channel_guard` "
                "in `.claude/hooks-daemon.yaml`. Ask the user; do not hunt for "
                "another way to reveal the content."
            ),
        )

    # ── Guidance surfaces ───────────────────────────────────────────────────

    def get_claude_md(self) -> str | None:
        return (
            "## flaggable_content_channel_guard — no content-revealing git/grep "
            "over flaggable paths\n\n"
            "Ships disabled (opt-in). When enabled, DENIES a Bash command "
            "segment whose SHAPE reveals file content — `git diff`, "
            "`git show`, `git log -p`/`--patch`, `git add -p`/`--patch`, or "
            "`grep`/`egrep`/`fgrep`/`rg` — when it also references a path "
            "matching a configured `flaggable_path_globs` entry. A plain "
            "`git status`, `git log` (no `-p`), or `git add <path>` (no "
            "`-p`) is NOT content-revealing and stays allowed.\n\n"
            "**Why**: those shapes pull a flaggable file's content into "
            "context inside a routine command's output, with no deliberate "
            "Read at all — the one leak an agent-side convention cannot "
            "plug. Delegate the WHOLE review to the quarantine subagent "
            "instead; it owns the entire git cycle for flaggable files "
            "(stage, commit, push) and reports back a clean summary — "
            "confirm CI by status, never by diffing the content.\n\n"
            "**Configure** via `handlers.pre_tool_use."
            "flaggable_content_channel_guard.options`: "
            "`flaggable_path_globs` (default empty — inert until "
            "configured) plus `mode: additive` (default) or `replace` "
            "(governs only the path-glob list); "
            "`extra_content_revealing_patterns` (raw regexes) always "
            "EXTENDS the built-in git/grep shape set — there is no "
            "supported way to remove the built-in shapes, since that would "
            "leave the handler unable to detect the leak it exists for.\n\n"
            "**There is NO escape hatch.** An agent that could type its own "
            "justification would have self-authorised the disclosure this "
            "guard exists to prevent. Only a human may lift it, by editing "
            "config."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        fixture = "tests/fixtures/cyber-flag/DO-NOT-READ-cyber-flag-context-fixture.txt"
        return [
            AcceptanceTest(
                title="git diff over a flaggable path is denied",
                command=f"git diff {fixture}",
                description=(
                    "`git diff` on a path matching a configured flaggable glob "
                    "is denied before the diff ever runs."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"FLAGGABLE CONTENT CHANNEL", r"git diff"],
                safety_notes=(
                    "Denied before execution — the diff never runs; requires "
                    "the handler enabled with the fixture path configured "
                    "(dogfooded in this repo)."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="grep over a flaggable path is denied",
                command=f"grep mechanics {fixture}",
                description=(
                    "grep content search on a flaggable path is denied before " "it runs."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"FLAGGABLE CONTENT CHANNEL"],
                safety_notes="Denied before execution — grep never runs.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git status on a flaggable path is NOT denied",
                command=f"git status {fixture}",
                description=(
                    "A non-content-revealing shape stays allowed even when it "
                    "names a flaggable path."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="git status is read-only and non-revealing; safe to run.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]


def _segments(command: str) -> list[str]:
    """Top-level command segments: statements, then pipe/&&/|| spans within each.

    Mirrors ``verification_result_gate``'s decomposition so both handlers
    agree on what one "command" is — quote-aware and heredoc-safe via
    ``split_statements``/``split_unquoted``.
    """
    segments: list[str] = []
    for statement in split_statements(command):
        segments.extend(split_unquoted(statement, SPAN_SEPARATORS))
    return [segment.strip() for segment in segments if segment.strip()]
