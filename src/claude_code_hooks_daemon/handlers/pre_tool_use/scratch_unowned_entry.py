"""Advise on a new entry made directly in a scratch root (Plan 00627 Task 4.5).

DESIGN.md section 7: throwaway work goes in the session's own directory, as an
entry made by ``hooks-daemon scratch new``, which records its owner, birth,
purpose and TTL. A write that would create a NEW first-level entry in a scratch
root (``.../untracked/scratch/<name>``), outside any session directory, makes an
entry nobody owns: the sweep can only judge it by mtime.

``scratch.sweep.unowned_entry`` decides the answer: ``advise`` (the default, and
what an un-injected instance does) adds context and never denies, ``block``
denies under R-SCRATCH-UNOWNED-ENTRY, ``off`` does nothing.

Judged on the first path segment under the root, so ``scratch/foo/a.txt``
creating ``foo`` counts. A segment that already exists (no link followed), a
session directory name and ``.gitignore`` never fire. The Bash write scan does
not report ``mkdir`` or ``touch``, so those create an entry unseen; a
destination the scan cannot resolve is not guessed at, since this is a location
advisory, not a safety guard.
"""

import os
from pathlib import PurePosixPath
from typing import Any, Final

from claude_code_hooks_daemon.config.models import ScratchConfig
from claude_code_hooks_daemon.constants import HandlerTag, HookInputField
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.scratch_session import is_session_dir_name
from claude_code_hooks_daemon.core.utils import get_file_path, scan_bash_write_targets
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs
from claude_code_hooks_daemon.utils.scratch_dir import project_dir_path

_MODE_OFF: Final[str] = "off"
_MODE_BLOCK: Final[str] = "block"
_ROOT_PARTS: Final[tuple[str, str]] = ("untracked", "scratch")
_EXEMPT_NAMES: Final[frozenset[str]] = frozenset({".gitignore"})

_RULE = Rule(
    rule_id=RuleID.SCRATCH_UNOWNED_ENTRY,
    blocked="a new entry made directly in a scratch root, outside the session directory "
    "(only when `scratch.sweep.unowned_entry` is `block`)",
    why=(
        "An entry outside a session directory has no recorded owner, birth or purpose, "
        "so the sweep can judge it only by its timestamps"
    ),
    fix="Make the entry with `hooks-daemon scratch new <name> --purpose '...'` and write inside it",
    verbose=(
        "WHY BLOCKED:\n"
        "This project sets scratch.sweep.unowned_entry to block. Throwaway work\n"
        "goes in the session's own scratch directory, as an entry made by\n"
        "`scratch new`, which records its owner, birth, purpose and TTL. An entry\n"
        "made directly in the scratch root has none of those."
    ),
)


def _new_entry(path: str, cwd: object) -> str | None:
    """The first segment under a scratch root that ``path`` would create, else None."""
    pure = PurePosixPath(path)
    if not pure.is_absolute():
        if not isinstance(cwd, str) or not cwd:
            return None
        pure = PurePosixPath(cwd) / pure
    parts = pure.parts
    for index in range(len(parts) - 2):
        if parts[index : index + 2] != _ROOT_PARTS:
            continue
        name = parts[index + 2]
        if name in _EXEMPT_NAMES or is_session_dir_name(name) or name in (".", ".."):
            return None
        entry = PurePosixPath(*parts[: index + 3])
        return None if os.path.lexists(entry) else str(entry)
    return None


class ScratchUnownedEntryHandler(PreToolUseHandlerBase):
    """Advise (or block) a write creating an entry directly in a scratch root."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SCRATCH_UNOWNED_ENTRY,
            priority=Priority.SCRATCH_UNOWNED_ENTRY,
            terminal=True,
            tags=[HandlerTag.ADVISORY, HandlerTag.WORKFLOW],
        )
        # Overwritten by the registry with the project's ``scratch`` block.
        self._scratch: ScratchConfig = ScratchConfig()

    def _mode(self) -> str:
        return str(self._scratch.sweep.unowned_entry)

    def _entries(self, hook_input: dict[str, Any]) -> list[str]:
        cwd = hook_input.get(HookInputField.CWD)
        file_path = get_file_path(hook_input)
        paths = (
            [file_path]
            if file_path is not None
            else list(scan_bash_write_targets(hook_input).paths)
        )
        found: list[str] = []
        for path in paths:
            entry = _new_entry(path, cwd) if path else None
            if entry is not None and entry not in found:
                found.append(entry)
        return found

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when a write would create an unowned entry and the mode is not ``off``."""
        if self._mode() == _MODE_OFF:
            return False
        return bool(self._entries(hook_input))

    def get_rules(self) -> list[Rule]:
        """The rule a ``block`` mode denies under."""
        return [_RULE]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Advise, or deny in ``block`` mode, naming the entry and ``scratch new``."""
        if not self.matches(hook_input):
            return GatingResult(decision=Decision.ALLOW)
        entries = ", ".join(self._entries(hook_input))
        command = daemon_cli_command_for_docs("scratch", "new")
        message = (
            f"New scratch entry outside your session directory: {entries}. It has no "
            f"recorded owner, birth or purpose. Make entries with `{command} <name> "
            "--purpose '...'` (it prints the path) and write inside that."
        )
        if self._mode() == _MODE_BLOCK:
            return GatingResult(
                decision=Decision.DENY,
                reason=f"{RuleFormatter().verbose(_RULE)}\n\n{message}",
                rule=_RULE.rule_id,
            )
        return GatingResult(decision=Decision.ALLOW, context=[message])

    def get_claude_md(self) -> str | None:
        command = daemon_cli_command_for_docs("scratch", "new")
        return (
            "## scratch_unowned_entry — scratch entries belong in the session directory\n\n"
            "A write that would create a new entry directly in `untracked/scratch/` (outside "
            "the `s-*` session directory) gets an advisory: such an entry has no recorded "
            f"owner, birth or purpose. Make entries with `{command} <name> --purpose '...'` "
            "and write inside the path it prints. `scratch.sweep.unowned_entry` sets the "
            "answer: `advise` (default), `block` (R-SCRATCH-UNOWNED-ENTRY) or `off`."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance test: a Write straight into the scratch root is advised, not denied."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        target = project_dir_path("untracked", "scratch", "acceptance-unowned-entry.txt")
        probe = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={"file_path": target, "content": "unowned\n"},
        )
        return [
            AcceptanceTest(
                title="Write a new file directly in the scratch root",
                command=probe.as_instruction(),
                tool_payload=probe,
                description="Advises making the entry with `scratch new`; never denies",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"scratch new"],
                safety_notes="Writes one ignored file under untracked/scratch/.",
                test_type=TestType.ADVISORY,
                cleanup_commands=[f"rm -f {target}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
