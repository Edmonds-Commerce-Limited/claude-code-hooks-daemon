"""Refresh the scratch inventory after a command that creates a directory under scratch.

Plan 00627 Task 5.1 (DESIGN.md section 8): the cached
``untracked/scratch-inventory.json`` is refreshed at SessionStart, after
``scratch-sweep --apply``, and here, after a Bash command that creates a
directory tree under the project's scratch root. The refresh runs in a
background thread (one at a time); this handler never blocks and adds no
context.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.scratch_dir_creation import creates_directory_under

logger = logging.getLogger(__name__)


def _start_refresh(project_root: Path) -> None:
    """Start the background refresh; never raises."""
    from claude_code_hooks_daemon.daemon.cli import start_scratch_inventory_refresh

    try:
        start_scratch_inventory_refresh(project_root)
    except Exception:
        logger.exception("scratch inventory refresh not started")


class ScratchInventoryRefresherHandler(PostToolUseHandlerBase):
    """Start an inventory refresh after a directory-creating command into scratch."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SCRATCH_INVENTORY_REFRESHER,
            priority=Priority.SCRATCH_INVENTORY_REFRESHER,
            terminal=False,
            tags=[HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL, HandlerTag.WORKFLOW],
        )
        self.project_root_override: Path | None = None

    def _project_root(self) -> Path:
        return self.project_root_override or ProjectContext.project_root()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A Bash command that creates a directory under the scratch root."""
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False
        root = self._project_root()
        cwd = Path(str(hook_input.get(HookInputField.CWD) or root))
        command = get_bash_command(hook_input) or ""
        return creates_directory_under(command, cwd, (root / "untracked" / "scratch",))

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Start the refresh; always a silent allow."""
        _start_refresh(self._project_root())
        return BlockingResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        """Silent bookkeeping: nothing an agent needs to act on."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """One test: the refresh is a background side effect the harness cannot observe."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="scratch-inventory-refresher - mkdir under scratch refreshes the inventory",
                command="mkdir -p untracked/scratch/acceptance-refresh-probe",
                harness_cannot_produce=(
                    "The refresh is a background thread writing "
                    "untracked/scratch-inventory.json; the harness observes only the hook "
                    "result, which is a silent allow. Covered by "
                    "tests/unit/handlers/post_tool_use/test_scratch_inventory_refresher.py "
                    "and tests/unit/utils/test_scratch_dir_creation.py."
                ),
                description="The command succeeds; the handler adds no context.",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
            )
        ]
