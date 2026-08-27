"""QuarantineArtefactReadGuardHandler - enforce the DETAIL read-boundary (Plan 00278 Phase 3d.2).

The two-file artefact contract (handover §2.3) has the quarantine subagent
report back through TWO files: a mandatory ``<topic>-opus-security-SUMMARY``
the coordinator always reads, and an optional ``<topic>-opus-security-DETAIL``
holding the raw flaggable substance — which the coordinator must NEVER read.
Today that boundary is a naming convention with ZERO enforcement, and it
fails exactly where the risk is highest: a document *about* the mechanism
(the handover report itself proved this — it enumerates every category and is
named so no pattern catches it).

This handler enforces the boundary by PATTERN, not trust:

- ``Read``/``Edit``/``Grep``/``NotebookEdit`` on a path matching a configured
  quarantined-artefact glob (default seed: ``*-opus-security-DETAIL*``) are
  DENIED.
- Any Bash command whose SHAPE reveals file content (``cat``, ``head``,
  ``tail``, ``less``, ``more``, ``grep``/``egrep``/``fgrep``/``rg``,
  ``strings``, ``xxd``/``hexdump``/``od``, ``awk``, or an interpreter
  one-liner) mentioning such a path is DENIED.

Writing/creating the artefact is deliberately ALLOWED — the subagent authors
it — so ``Write`` is never checked, and a Bash command that AUTHORS the path
(``cat > file <<EOF`` with a redirect) is not treated as a reveal. The
subagent also owns the entire git cycle for its own artefacts (handover
§2.4), so `git add`/`git commit`/`git push` mentioning the path are not
revealing shapes either — that channel is `flaggable_content_channel_guard`'s
narrower job (``git diff``/``show``/``log -p``/``add -p``), configured
against its own path list.

Ships DISABLED but PRE-SEEDED: unlike ``flaggable_work_advisor``, the marker
tokens are a project-independent convention, so enabling this handler works
with zero configuration.
"""

from __future__ import annotations

import re
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.bash_flags import SPAN_SEPARATORS, split_statements
from claude_code_hooks_daemon.utils.command_evasion import compile_command_name_pattern
from claude_code_hooks_daemon.utils.shell_segmentation import split_unquoted

# ── Config modes (command_hints' clobber-or-extend convention) ──────────────
_MODE_ADDITIVE: Final[str] = "additive"
_MODE_REPLACE: Final[str] = "replace"
_DEFAULT_MODE: Final[str] = _MODE_ADDITIVE

# Pre-seeded by design (Decision text, Plan 00278 Phase 3d.2): the marker
# convention is project-independent, so this handler works out of the box —
# unlike flaggable_work_advisor's deliberately empty path-glob seed.
_SEED_QUARANTINE_GLOBS: Final[tuple[str, ...]] = (
    "*-opus-security-DETAIL*",
    "*-opus-security-DETAIL.md",
)

# Tools whose single path argument is checked directly (mirrors secret_file_guard).
_FIELD_FILE_PATH: Final[str] = "file_path"
_FIELD_NOTEBOOK_PATH: Final[str] = "notebook_path"
_FIELD_PATH: Final[str] = "path"
_FIELD_COMMAND: Final[str] = "command"

_PATH_FIELD_BY_TOOL: Final[dict[str, str]] = {
    ToolName.READ: _FIELD_FILE_PATH,
    ToolName.EDIT: _FIELD_FILE_PATH,
    ToolName.NOTEBOOK_EDIT: _FIELD_NOTEBOOK_PATH,
    ToolName.GREP: _FIELD_PATH,
}

# Bash verbs whose fundamental purpose is PRINTING file content. `tee` is
# deliberately absent -- its whole purpose is writing/echoing to a file, so
# treating it as revealing would deny the subagent's own authoring route.
_REVEALING_BASH_VERBS: Final[tuple[str, ...]] = (
    "cat",
    "head",
    "tail",
    "less",
    "more",
    "grep",
    "egrep",
    "fgrep",
    "rg",
    "strings",
    "xxd",
    "hexdump",
    "od",
    "awk",
    "python",
    "python3",
    "perl",
    "ruby",
    "node",
)

# Precompiled once at import time: `compile_command_name_pattern` (shared with
# every other command-anchored handler in this codebase, e.g. destructive_git,
# sudo_pip) tolerates the same respellings this project already defends
# against elsewhere -- a path-qualified binary (`/usr/bin/cat`) and an `env`/
# `VAR=value` prefix -- so a wrapper spelling cannot walk past this deny the
# way `git -C` once walked past destructive_git.
_REVEALING_VERB_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = tuple(
    (verb, compile_command_name_pattern(verb)) for verb in _REVEALING_BASH_VERBS
)

# `cat` is the one verb that is ALSO a common authoring idiom
# (`cat > file <<EOF`). When a redirect marker is present anywhere in the
# segment, treat the whole segment as authoring rather than revealing.
_AMBIGUOUS_WRITE_VERB: Final[str] = "cat"
_REDIRECT_MARKER: Final[str] = ">"


class QuarantineArtefactReadGuardHandler(PreToolUseHandlerBase):
    """Deny reading a quarantined DETAIL artefact from the main context.

    DENY-BY-PATTERN: ``terminal=True`` and ships DISABLED, but pre-seeded so
    enabling it needs no configuration (Plan 00278 Phase 3d.2).
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.QUARANTINE_ARTEFACT_READ_GUARD,
            priority=Priority.QUARANTINE_ARTEFACT_READ_GUARD,
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
        self._quarantine_artefact_globs: list[str] = []

    def get_default_enabled(self) -> bool:
        """Opt-in: matches the estate's other Plan 00278 delegation surfaces."""
        return False

    # ── Effective config (mode: additive | replace) ─────────────────────────

    def _effective_globs(self) -> tuple[str, ...]:
        project = [
            str(entry) for entry in (self._quarantine_artefact_globs or []) if str(entry).strip()
        ]
        if self._mode == _MODE_REPLACE:
            return tuple(project)
        merged: list[str] = list(_SEED_QUARANTINE_GLOBS)
        for entry in project:
            if entry not in merged:
                merged.append(entry)
        return tuple(merged)

    # ── Matching (single dispatch point shared by matches()/handle()) ───────

    def _matched_pattern(self, hook_input: dict[str, Any]) -> str | None:
        if not isinstance(hook_input, dict):
            return None
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        tool_input = hook_input.get(HookInputField.TOOL_INPUT)
        if not isinstance(tool_input, dict):
            return None

        patterns = self._effective_globs()
        if not patterns:
            return None

        if tool_name == ToolName.BASH:
            command = str(tool_input.get(_FIELD_COMMAND, "") or "")
            return self._bash_mention(command, patterns)

        path_field = _PATH_FIELD_BY_TOOL.get(str(tool_name or ""))
        if path_field is None:
            return None
        path = str(tool_input.get(path_field, "") or "")
        if not path:
            return None
        for pattern in patterns:
            if sfm.path_is_protected(path, (pattern,)):
                return pattern

        if tool_name == ToolName.GREP:
            # Partial enforcement for directory-rooted content search
            # (mirrors secret_file_guard): a Grep rooted at a directory
            # containing a DETAIL artefact reads it without naming it.
            return sfm.directory_contains_protected(path, patterns)
        return None

    def _bash_mention(self, command: str, patterns: tuple[str, ...]) -> str | None:
        """First quarantine glob mentioned by a content-REVEALING segment, or None."""
        if not command:
            return None
        for segment in _segments(command):
            for verb, verb_pattern in _REVEALING_VERB_PATTERNS:
                if not verb_pattern.search(segment):
                    continue
                if verb == _AMBIGUOUS_WRITE_VERB and _REDIRECT_MARKER in segment:
                    # `cat > file <<EOF ...` AUTHORS the file; not a reveal.
                    continue
                mention = sfm.find_protected_mention(segment, patterns)
                if mention is not None:
                    return mention
        return None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return self._matched_pattern(hook_input) is not None

    # ── Handling ────────────────────────────────────────────────────────────

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        pattern = self._matched_pattern(hook_input)
        if pattern is None:
            return GatingResult(decision=Decision.ALLOW)
        return GatingResult(
            decision=Decision.DENY,
            reason=(
                "QUARANTINE ARTEFACT READ-BOUNDARY: this tool call would "
                f"put the contents of a quarantined artefact into context "
                f"(matched glob: `{pattern}`).\n\n"
                "A `*-opus-security-DETAIL*` artefact holds the raw "
                "flaggable substance a quarantine subagent examined on your "
                "behalf. It exists for a human or another quarantine agent "
                "to open on purpose — the coordinator must NEVER read it.\n\n"
                "What you CAN do instead:\n"
                "- Read the paired `*-opus-security-SUMMARY*` artefact — "
                "that is the ONLY file the coordinator should read, and it "
                "is provably clean of attack-mechanics content.\n"
                "- Confirm the subagent's work by commit hash and CI status "
                "(green/red), never by reading the DETAIL file's content.\n\n"
                "Creating or editing the artefact from the SUBAGENT's own "
                "context (e.g. via the Write tool) is unaffected by this "
                "guard — only reading it back into the coordinator is "
                "denied.\n\n"
                "There is NO escape hatch. Only a human may lift this, by "
                "editing `handlers.pre_tool_use.quarantine_artefact_read_guard` "
                "in `.claude/hooks-daemon.yaml`. Ask the user; do not hunt "
                "for another way to read the file."
            ),
        )

    # ── Guidance surfaces ───────────────────────────────────────────────────

    def get_claude_md(self) -> str | None:
        return (
            "## quarantine_artefact_read_guard — the DETAIL artefact is "
            "never read into the coordinator's context\n\n"
            "Ships disabled but pre-seeded (opt-in; works with zero config "
            "once enabled). Denies `Read`/`Edit`/`Grep`/`NotebookEdit` on "
            "any path matching a configured `quarantine_artefact_globs` "
            "entry (default seed: `*-opus-security-DETAIL*`), and any Bash "
            "command whose shape reveals file content (`cat`, `head`, "
            "`tail`, `less`, `more`, `grep`/`egrep`/`fgrep`/`rg`, "
            "`strings`, `xxd`/`hexdump`/`od`, `awk`, or an interpreter "
            "one-liner) mentioning such a path.\n\n"
            "**Why**: the two-file artefact contract has a quarantine "
            "subagent report back through a mandatory `*-opus-security-"
            "SUMMARY*` (always safe to read) and an optional "
            "`*-opus-security-DETAIL*` holding the raw flaggable substance "
            "it examined. Reading DETAIL back into the coordinator "
            "re-contaminates exactly the context the delegation was meant "
            "to protect. Confirm the subagent's work by commit hash and CI "
            "status, never by reading DETAIL's content.\n\n"
            "**Writing/creating the artefact is unaffected** — the "
            "subagent authors it, so `Write` is never checked, and a Bash "
            "command that AUTHORS the path (`cat > file <<EOF` with a "
            "redirect) is not treated as a reveal. The subagent also owns "
            "the entire git cycle for its own artefacts, so `git add`/"
            "`git commit`/`git push` mentioning the path are unaffected — "
            "content-revealing git commands (`git diff`/`show`/`log -p`/"
            "`add -p`) are `flaggable_content_channel_guard`'s job.\n\n"
            "**Configure** via `handlers.pre_tool_use."
            "quarantine_artefact_read_guard.options`: "
            "`quarantine_artefact_globs` (additive onto the seed by "
            "default) and `mode: additive` (default) or `replace`.\n\n"
            "**There is NO escape hatch.** Only a human may lift this, by "
            "editing config. Ask; do not work around the block."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="quarantine_artefact_read_guard - blocks Read of a DETAIL artefact",
                command=(
                    "Use the Read tool on a dummy fixture file named "
                    "`/tmp/topic-opus-security-DETAIL.md` (create nothing — "
                    "the deny fires on the path alone)"
                ),
                description="Read of a path matching the DETAIL seed glob is denied.",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"QUARANTINE ARTEFACT READ-BOUNDARY", r"SUMMARY"],
                safety_notes="Dummy path only; deny fires on the path, no read happens",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="quarantine_artefact_read_guard - blocks Bash cat of a DETAIL artefact",
                command="cat /tmp/topic-opus-security-DETAIL.md",
                description="A content-revealing Bash mention of a DETAIL path is denied.",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"QUARANTINE ARTEFACT READ-BOUNDARY"],
                safety_notes="Dummy path — the file need not exist; deny fires on the mention",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="quarantine_artefact_read_guard - allows Read of the SUMMARY artefact",
                command=(
                    "Use the Read tool on a dummy fixture file named "
                    "`/tmp/topic-opus-security-SUMMARY.md`"
                ),
                description="The paired SUMMARY artefact is always readable.",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Dummy path — SUMMARY is the sanctioned read route.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]


def _segments(command: str) -> list[str]:
    """Top-level command segments: statements, then pipe/&&/|| spans within each.

    Mirrors ``flaggable_content_channel_guard``'s decomposition (itself
    matching ``verification_result_gate``) so every Plan 00278 command-shape
    guard agrees on what one "command" is.
    """
    segments: list[str] = []
    for statement in split_statements(command):
        segments.extend(split_unquoted(statement, SPAN_SEPARATORS))
    return [segment.strip() for segment in segments if segment.strip()]
