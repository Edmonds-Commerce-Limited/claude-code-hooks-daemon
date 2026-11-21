"""Deny an agent writing a `.scratch-keep` marker (Plan 00627, R-SCRATCH-KEEP-MARKER).

A scratch entry holding `.scratch-keep` is KEPT for ever by the sweep (DESIGN
R15), so the marker is a human's decision. An agent that could write it could
pin its own clutter past every TTL; one that could remove it could unpin a
human's keep. So every write route is judged on the file NAME: `Write`/`Edit`,
and a Bash command's redirects, `tee`, `cp`/`mv`/`install`/`dd`, `ln`, `touch`
and `rm`, read by the shared write scan.

A destination the scan cannot resolve (`> "$DIR/.scratch-keep"`) or command
text it cannot read fails CLOSED when it names the marker: where it writes is
unknown, and the name is the whole rule.
"""

from pathlib import PurePosixPath
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerTag
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.scratch_verdict import KEEP_MARKER
from claude_code_hooks_daemon.core.utils import get_file_path, scan_bash_write_targets
from claude_code_hooks_daemon.utils.scratch_dir import acceptance_path

#: Acceptance-test fixture directory, below the gitignored acceptance root.
_FIXTURE_DIR: Final[str] = "acceptance-test-scratch-keep"

_RULE = Rule(
    rule_id=RuleID.SCRATCH_KEEP_MARKER,
    blocked="an agent creating, changing or removing a `.scratch-keep` marker",
    why=(
        "The marker keeps a scratch entry for ever, so it is a human's decision; "
        "an agent's own keep would outlive every TTL"
    ),
    fix=(
        "Pause the entry instead (`hooks-daemon scratch-sweep keep <entry> --reason ...`, "
        "bounded), file what is worth keeping where git carries it, or ask the human "
        "to add the marker"
    ),
    verbose=(
        "WHY BLOCKED:\n"
        "A scratch entry holding `.scratch-keep` is KEPT by the sweep for ever.\n"
        "Pinning an entry for ever is a human's decision (Plan 00627 R15): an\n"
        "agent's keep would outlive every TTL, and an agent's removal would undo\n"
        "a human's keep. Every write route naming the file is denied, including\n"
        "Bash redirects, tee, cp/mv/install, ln, touch and rm."
    ),
)


def _names_marker(path: str) -> bool:
    """Whether ``path``'s final component is the keep marker."""
    return PurePosixPath(path.rstrip("/") or "/").name == KEEP_MARKER


class ScratchKeepMarkerGuardHandler(PreToolUseHandlerBase):
    """Block every agent write route onto a file named `.scratch-keep`.

    Priority: 18 (safety band, beside write_protected_paths)
    Terminal: True
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SCRATCH_KEEP_MARKER_GUARD,
            priority=Priority.SCRATCH_KEEP_MARKER_GUARD,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when a Write/Edit path or a Bash write names the marker."""
        file_path = get_file_path(hook_input)
        if file_path is not None:
            return bool(file_path) and _names_marker(file_path)
        scan = scan_bash_write_targets(hook_input, include_mutations=True)
        if any(_names_marker(path) for path in scan.paths):
            return True
        if any(_names_marker(token) for token in scan.unresolved):
            return True
        return scan.unreadable is not None and KEEP_MARKER in scan.unreadable

    def get_rules(self) -> list[Rule]:
        """Return the single Rule this handler denies under."""
        return [_RULE]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny the write, naming the bounded alternative."""
        if not self.matches(hook_input):
            return GatingResult(decision=Decision.ALLOW)
        return GatingResult(
            decision=Decision.DENY,
            reason=(
                f"{RuleFormatter().verbose(_RULE)}\n\n"
                "Only a human may pin a scratch entry for ever. An agent may pause "
                "one for a bounded time, with a reason."
            ),
        )

    def get_claude_md(self) -> str | None:
        return (
            "## scratch_keep_marker_guard — `.scratch-keep` is a human's mark\n\n"
            "A scratch entry holding a `.scratch-keep` file is never swept, so an agent "
            "may not create, change or remove that file: `Write`/`Edit`, and a Bash "
            "redirect, `tee`, `cp`/`mv`/`install`, `ln`, `touch` or `rm` naming it, are "
            "denied (R-SCRATCH-KEEP-MARKER). A destination built from a variable that "
            "names the marker is denied too.\n\n"
            "**Instead**: file the work where git carries it (a plan folder, a test, "
            "docs), pause the entry for a bounded time with a reason "
            "(`hooks-daemon scratch-sweep keep`), or ask the human to add the marker."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance tests: a Write and a Bash touch of the marker are denied."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        marker = acceptance_path(_FIXTURE_DIR, KEEP_MARKER)
        write_probe = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={"file_path": marker, "content": "keep: agent says so\n"},
        )
        touch_probe = ToolPayload(
            tool_name=ToolName.BASH,
            tool_input={"command": f"touch {marker}"},
        )
        setup = [f"mkdir -p untracked/acceptance/{_FIXTURE_DIR}"]
        cleanup = [f"rm -rf untracked/acceptance/{_FIXTURE_DIR}"]
        return [
            AcceptanceTest(
                title="Write a .scratch-keep marker",
                command=write_probe.as_instruction(),
                tool_payload=write_probe,
                description="Blocks an agent pinning a scratch entry with Write",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"R-SCRATCH-KEEP-MARKER", r"human"],
                safety_notes="Inside the gitignored acceptance directory; denied before the write.",
                test_type=TestType.BLOCKING,
                setup_commands=setup,
                cleanup_commands=cleanup,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="touch a .scratch-keep marker",
                command=touch_probe.as_instruction(),
                tool_payload=touch_probe,
                description="Blocks an agent pinning a scratch entry with a Bash touch",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"R-SCRATCH-KEEP-MARKER", r"human"],
                safety_notes="Inside the gitignored acceptance directory; denied before it runs.",
                test_type=TestType.BLOCKING,
                setup_commands=setup,
                cleanup_commands=cleanup,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
