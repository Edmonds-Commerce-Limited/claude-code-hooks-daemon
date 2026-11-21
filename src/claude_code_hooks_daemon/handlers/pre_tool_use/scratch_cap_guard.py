"""Deny new directory trees in scratch at the block cap (Plan 00627 Task 5.4, R-SCRATCH-CAP).

DESIGN.md section 8. Only a Bash command that creates a directory tree under a
scratch root is judged (``utils/scratch_dir_creation``); a ``Write`` and a
redirect into a file never are, so commit and journal bodies stay writable.
The level comes from the cached inventory only. When the entries the sweep
may act on are below the block cap by themselves, the deny would strand the
agent (only PROTECTED, KEPT or LIVE entries keep it over), so it becomes an
advisory naming them. ``scratch.caps.mode: advise`` also only advises.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.config.models import Config, ScratchCapsConfig
from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.scratch_caps import CapCounts, CapLevel, evaluate_caps
from claude_code_hooks_daemon.core.scratch_inventory import (
    INVENTORY_FILE,
    Inventory,
    InventoryEntry,
    inventory_caps,
    read_inventory,
)
from claude_code_hooks_daemon.core.scratch_verdict import Verdict
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs
from claude_code_hooks_daemon.utils.scratch_dir_creation import (
    creates_directory_under,
    scratch_roots,
)

logger = logging.getLogger(__name__)

#: Verdicts the sweep never packs, so they cannot be swept below a cap.
_UNSWEEPABLE: Final[frozenset[str]] = frozenset(
    {Verdict.LIVE.value, Verdict.KEPT.value, Verdict.PROTECTED.value}
)
_LARGEST: Final[int] = 5
#: The sweep command, named by program in the module-level Rule; runtime
#: strings resolve it with :func:`_sweep_command` for this install.
_SWEEP_ARGS: Final[tuple[str, ...]] = ("scratch-sweep", "--apply")


def _sweep_command() -> str:
    """The sweep command as this install runs it, safe for tracked docs."""
    return daemon_cli_command_for_docs(*_SWEEP_ARGS)


_RULE = Rule(
    rule_id=RuleID.SCRATCH_CAP,
    blocked="a command creating a directory tree under scratch while scratch is at its block cap",
    why=(
        "Scratch directories are counted by the link index, which overflows; new trees "
        "wait until the sweep has brought scratch back under the cap"
    ),
    fix=(
        "Run `hooks-daemon scratch-sweep --apply` (packs due entries, and at block "
        "also idle ones), then retry; "
        "writing a file is never denied"
    ),
    verbose=(
        "WHY BLOCKED:\n"
        "The cached scratch inventory is at the block cap (scratch.caps). A command\n"
        "that creates a directory tree under a scratch root (mkdir, git clone, git init,\n"
        "git worktree add, cp -r, tar -x, mktemp -d) is denied until the sweep runs.\n"
        "A Write of a file and a redirect into a file are never denied."
    ),
)


def _largest(entries: tuple[InventoryEntry, ...]) -> list[str]:
    ranked = sorted(entries, key=lambda entry: entry.directories, reverse=True)[:_LARGEST]
    return [f"  {entry.name} ({entry.verdict}, {entry.directories} dirs)" for entry in ranked]


class ScratchCapGuardHandler(PreToolUseHandlerBase):
    """Deny a directory-creating command into scratch at the block cap.

    Priority: 19 (safety band, beside scratch_keep_marker_guard)
    Terminal: True
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SCRATCH_CAP_GUARD,
            priority=Priority.SCRATCH_CAP_GUARD,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
        )
        self.project_root_override: Path | None = None
        self.caps_override: ScratchCapsConfig | None = None

    def _project_root(self) -> Path:
        return self.project_root_override or ProjectContext.project_root()

    def _caps(self, root: Path) -> ScratchCapsConfig:
        if self.caps_override is not None:
            return self.caps_override
        try:
            return Config.load_or_default(root / ".claude" / "hooks-daemon.yaml").scratch.caps
        except (OSError, ValueError) as exc:
            logger.info("scratch caps: config unreadable (%s); using defaults", type(exc).__name__)
            return ScratchCapsConfig()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A Bash command that creates a directory under a scratch root."""
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False
        root = self._project_root()
        cwd = Path(str(hook_input.get(HookInputField.CWD) or root))
        command = get_bash_command(hook_input) or ""
        return creates_directory_under(command, cwd, scratch_roots(root))

    def get_rules(self) -> list[Rule]:
        """Return the single Rule this handler denies under."""
        return [_RULE]

    def _stranded(self, inventory: Inventory, caps: ScratchCapsConfig) -> bool:
        """Whether the sweepable entries alone are below the block cap."""
        sweepable = tuple(e for e in inventory.entries if e.verdict not in _UNSWEEPABLE)
        counts = CapCounts(
            directories=sum(entry.directories for entry in sweepable),
            bytes=sum(entry.bytes for entry in sweepable),
            entries=len(sweepable),
        )
        level = evaluate_caps(counts, caps, incomplete=False).level
        return level < CapLevel.BLOCK

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny at block; advise in advise mode or when the deny would strand."""
        if not self.matches(hook_input):
            return GatingResult(decision=Decision.ALLOW)
        root = self._project_root()
        inventory = read_inventory(root / "untracked" / INVENTORY_FILE).inventory
        if inventory is None:
            return GatingResult(decision=Decision.ALLOW)
        caps = self._caps(root)
        report = inventory_caps(inventory, caps)
        if report.level < CapLevel.BLOCK:
            return GatingResult(decision=Decision.ALLOW)
        over = ", ".join(
            f"{check.key} {check.count} >= {check.block}"
            for check in report.at_or_above(CapLevel.BLOCK)
        )
        if self._stranded(inventory, caps):
            pinned = tuple(e for e in inventory.entries if e.verdict in _UNSWEEPABLE)
            lines = [
                f"{RuleID.SCRATCH_CAP} (advisory): scratch is at its block cap ({over}) only "
                "because of entries the sweep never packs:",
                *_largest(pinned),
                "Release a KEPT entry or end a LIVE one to bring scratch under the cap.",
            ]
            return GatingResult(decision=Decision.ALLOW, context=["\n".join(lines)])
        largest = "\n".join(_largest(inventory.entries))
        if not report.enforce:
            return GatingResult(
                decision=Decision.ALLOW,
                context=[
                    f"{RuleID.SCRATCH_CAP} (advisory, caps.mode advise): scratch is at its "
                    f"block cap ({over}). Run `{_sweep_command()}`. Largest entries:\n{largest}"
                ],
            )
        return GatingResult(
            decision=Decision.DENY,
            reason=(
                f"{RuleFormatter().verbose(_RULE)}\n\n"
                f"Over the block cap: {over}.\nLargest entries:\n{largest}\n\n"
                f"Run `{_sweep_command()}`, then retry."
            ),
        )

    def get_claude_md(self) -> str | None:
        return (
            "## scratch_cap_guard — no new directory trees in scratch at the block cap\n\n"
            "When the cached scratch inventory is at its block cap (`scratch.caps`), a Bash "
            "command that creates a directory tree under a scratch root (`mkdir`, `git clone`, "
            "`git init`, `git worktree add`, `cp -r`, `tar -x`, `mktemp -d`) is denied "
            "(R-SCRATCH-CAP). A `Write` and a redirect into a file are never denied.\n\n"
            f"**Instead**: run `{_sweep_command()}`, then retry. If only "
            "LIVE, KEPT or PROTECTED entries keep scratch over the cap, the deny is an "
            "advisory naming them."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """The deny and the allow; the harness cannot put the inventory at the block cap."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="scratch-cap-guard - mkdir under scratch at the block cap is denied",
                command="mkdir -p untracked/scratch/acceptance-cap-probe",
                harness_cannot_produce=(
                    "The deny needs untracked/scratch-inventory.json at the block cap "
                    "(25,000 directories by default) under `scratch.caps.mode: block`; no "
                    "acceptance setup should create that inventory, and a probe cannot "
                    "fake it without overwriting the real cache the sweep reads. Covered "
                    "by tests/unit/handlers/pre_tool_use/test_scratch_cap_guard.py."
                ),
                description=(
                    "At the block cap a directory-creating command under scratch is "
                    "denied, naming the sweep command and the largest entries."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"R-SCRATCH-CAP", r"scratch-sweep --apply"],
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
            ),
            AcceptanceTest(
                title="scratch-cap-guard - mkdir under scratch below the cap is allowed",
                command="mkdir -p untracked/scratch/acceptance-cap-probe",
                harness_cannot_produce=(
                    "A deny needs untracked/scratch-inventory.json at the block cap "
                    "(25,000 directories by default), which no acceptance setup should "
                    "create. Covered by "
                    "tests/unit/handlers/pre_tool_use/test_scratch_cap_guard.py."
                ),
                description="Below the block cap the command runs.",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
            ),
        ]
