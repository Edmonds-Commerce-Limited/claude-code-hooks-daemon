"""Deny a ``Write`` that would clobber an existing file nobody read (Plan 00261).

``Write`` replaces a file's entire contents. When the target already exists and
the agent has not read it, everything in it is destroyed with no warning and no
diff -- and the agent cannot even report what was lost, because it never knew.

This is a recorded incident, not a hypothetical: a ``Write`` in this repository
destroyed a tracked 58-line journal a sub-agent had committed minutes earlier.
It was caught only because that path happened to fall under an ADVISE-level
plan-QA rule; anywhere else the loss would have entered a commit looking clean.

**Why reads and not sizes.** The obvious design is to generalise the existing
``plan-shrink-without-journal`` rule and block a write that loses many bytes.
That would have passed the incident above: the clobbering write GREW the file,
58 -> ~67 lines. The destructive property was replacement without knowledge, not
shrinkage. So this handler tracks whether the file was READ.

**Why this exists at all.** The ``Write`` tool's own description states
"Overwriting an existing file you haven't Read will fail." Measured under
``bypassPermissions``, it does not -- an unread file was clobbered and its
content destroyed, reproduced both inside and outside the project. In other
permission modes the approval prompt is a real net, so the gap is specific to
the mode agents run unattended in. This handler restores the documented
contract rather than inventing a new rule.
"""

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.tags import HandlerTag
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase

# The daemon is long-lived, so per-session state must be bounded or it grows for
# the life of the process. These caps are generous for real sessions while
# keeping worst-case memory trivial.
_MAX_TRACKED_SESSIONS = 32
_MAX_PATHS_PER_SESSION = 2_000

# Used when a payload carries no session id. Grouping those together is correct:
# without an id there is nothing to distinguish one session from another, and
# the alternative (treating each as unique) would leak entries without bound.
_UNKNOWN_SESSION = "<no-session-id>"

_CONFIG_KEY_PATH = "handlers.pre_tool_use.write_clobber_guard.enabled"


class WriteClobberGuardHandler(PreToolUseHandlerBase):
    """Deny ``Write`` to an existing file that was not read this session.

    Priority: 16 -- deliberately after the blocking safety handlers, because a
    ``Read`` that one of them DENIES never happened and must not be recorded as
    knowledge of the file.

    Terminal: False. This handler ALLOWs on its common path (recording a read),
    and a terminal ALLOW ends the dispatch chain, silently disabling every
    handler behind it (the Plan 00241 shadowing defect). The chain merges
    decisions most-restrictive-wins, so a non-terminal DENY still denies.
    """

    def __init__(self) -> None:
        """Initialise with safety-band priority and empty per-session state."""
        super().__init__(
            handler_id=HandlerID.WRITE_CLOBBER_GUARD,
            priority=Priority.WRITE_CLOBBER_GUARD,
            terminal=False,
            # BLOCKING, not decoration: this handler denies unconditionally, and
            # the generated handler table renders whatever is declared here. An
            # untagged blocker rendered as NON-TERMINAL, telling agents to expect
            # a warning where they will meet a wall.
            tags=[HandlerTag.SAFETY, HandlerTag.FILE_OPS, HandlerTag.BLOCKING],
        )
        # session id -> paths whose contents this session has seen.
        self._known_paths: dict[str, set[str]] = {}

    @staticmethod
    def _session_id(hook_input: dict[str, Any]) -> str:
        session = hook_input.get("session_id")
        return session if isinstance(session, str) and session else _UNKNOWN_SESSION

    @staticmethod
    def _file_path(hook_input: dict[str, Any]) -> str | None:
        """Read ``file_path`` directly rather than via the shared accessor.

        ``core.utils.get_file_path`` returns None for anything that is not
        Write/Edit, which would make a Read invisible here -- the exact gating
        Plan 00260 Task 3.1b is about. This handler needs the Read.
        """
        tool_input = hook_input.get("tool_input")
        if not isinstance(tool_input, dict):
            return None
        path = tool_input.get("file_path")
        return path if isinstance(path, str) and path else None

    def _record(self, hook_input: dict[str, Any], path: str) -> None:
        """Remember that this session knows the contents of ``path``."""
        session = self._session_id(hook_input)
        if session not in self._known_paths and len(self._known_paths) >= _MAX_TRACKED_SESSIONS:
            # Evict the oldest tracked session. Losing state only ever costs an
            # extra Read, never safety -- the guard fails CLOSED.
            self._known_paths.pop(next(iter(self._known_paths)))
        known = self._known_paths.setdefault(session, set())
        if len(known) < _MAX_PATHS_PER_SESSION:
            known.add(path)

    def _is_known(self, hook_input: dict[str, Any], path: str) -> bool:
        return path in self._known_paths.get(self._session_id(hook_input), set())

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Fire on every Read (to record it) and on a clobbering Write.

        Args:
            hook_input: Hook input containing tool_name and tool_input.

        Returns:
            True for a Read carrying a path, or a Write that would replace an
            existing file this session has not read.
        """
        tool_name = hook_input.get("tool_name")
        path = self._file_path(hook_input)
        if path is None:
            return False

        if tool_name == ToolName.READ:
            return True

        if tool_name != ToolName.WRITE:
            return False

        # Creating a new file destroys nothing.
        if not Path(path).is_file():
            return False

        return not self._is_known(hook_input, path)

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Record a Read, or deny a Write that would clobber unread content.

        Args:
            hook_input: Hook input for the Read or Write call.

        Returns:
            ALLOW for a Read (always), DENY for a clobbering Write.
        """
        path = self._file_path(hook_input)
        if path is None:
            return GatingResult(decision=Decision.ALLOW)

        if hook_input.get("tool_name") == ToolName.READ:
            self._record(hook_input, path)
            return GatingResult(decision=Decision.ALLOW)

        if not self.matches(hook_input):
            # A Write we are not blocking still teaches this session the file's
            # contents, so a later rewrite of the same path is not blocked.
            if hook_input.get("tool_name") == ToolName.WRITE:
                self._record(hook_input, path)
            return GatingResult(decision=Decision.ALLOW)

        line_count = self._count_lines(path)
        reason = f"""🚫 BLOCKED: this Write would destroy a file you have not read

FILE: {path}
AT RISK: {line_count} lines, which would be replaced wholesale

WHY BLOCKED:
`Write` replaces a file's ENTIRE contents. You have not read this file in this
session, so you do not know what is in it — which means you could not report
what was lost even after losing it. This is not hypothetical: a Write destroyed
a tracked 58-line journal in this repository, and it was noticed only by luck.

DO INSTEAD (either is one call):
  • `Read` the file, then retry the Write if a full replacement is what you want
  • Use `Edit` for a targeted change — it replaces known text, not the whole file

NOTE: creating a NEW file is never blocked, and a file you wrote or read earlier
in this session is not blocked either.

To disable: {_CONFIG_KEY_PATH}: false"""

        return GatingResult(decision=Decision.DENY, reason=reason, context=[], guidance=None)

    @staticmethod
    def _count_lines(path: str) -> int:
        """Count lines at risk, reporting 0 when the file cannot be read.

        A file that cannot be read is still worth blocking -- the agent knows
        even less about it -- so this degrades the message rather than the
        decision.
        """
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                return sum(1 for _ in handle)
        except OSError:
            return 0

    def get_claude_md(self) -> str | None:
        """Resident guidance for the active-handler block."""
        return (
            "## write_clobber_guard — `Write` to an existing file you have not read\n\n"
            "`Write` replaces a file's ENTIRE contents. A `Write` to a file that already "
            "exists and that you have NOT read in this session is blocked, because you "
            "cannot know what you are destroying — and so could not report the loss even "
            "afterwards.\n\n"
            "**Never blocked**: creating a new file; rewriting a file you read or wrote "
            "earlier this session; any `Edit` (it replaces known text, not the file).\n\n"
            "**The fix is one call**: `Read` the file and retry, or use `Edit`. Reading "
            "first is what you should do regardless, so there is no escape hatch and none "
            "is needed — unlike a `MUST_..._BECAUSE` declaration, a `Read` actually "
            "removes the hazard instead of declaring it acceptable.\n\n"
            "**Why this exists**: the `Write` tool's own description says overwriting an "
            "unread file will fail. Measured under `bypassPermissions`, it does not — so "
            "this handler restores the documented contract rather than adding a new rule. "
            "A `Write` destroyed a tracked 58-line journal in this repository, and a "
            "size-based rule would NOT have caught it: the clobbering write made the file "
            "bigger. Replacement, not shrinkage, is the hazard."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests: a DENY case and an ALLOW case."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Write to an existing unread file is denied",
                command=(
                    "Use the Write tool on a file that already exists and that you "
                    "have NOT read in this session (for example a tracked source file)."
                ),
                description="Blocks a Write that would destroy unread file contents",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"would destroy a file you have not read",
                    r"AT RISK",
                    r"Edit",
                ],
                safety_notes="Denied before the write runs, so nothing is destroyed.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Write to a brand-new path is allowed",
                command=("Use the Write tool to create a file at a path that does not exist yet."),
                description=(
                    "Creating a new file is NOT blocked - proves the matcher is not "
                    "over-broad, which a deny-only suite cannot show"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Creates a new file; destroys nothing.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
