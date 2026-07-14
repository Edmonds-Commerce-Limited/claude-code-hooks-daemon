"""Core types for the plan QA check system (Plan 00144).

A *check* is a pure function ``CheckContext -> list[Finding]`` registered
declaratively as a :class:`CheckSpec` with an id, the stage it runs at, its
nominal level, and the audit-catalogue sins it defends against. Handlers and
the CLI never contain rule logic: they build a :class:`CheckContext`, call
:func:`plan_qa.runner.run_stage`, and render the findings.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts
    from claude_code_hooks_daemon.plan_qa.model import PlanTree
    from claude_code_hooks_daemon.plan_qa.readme_index import ReadmeIndex


class Stage(str, Enum):
    """When a check runs."""

    EDIT = "edit"  # Stage 1: Write/Edit of a single plan file
    COMMIT = "commit"  # Stage 2: git commit gate over the staged tree
    SWEEP = "sweep"  # Stage 3: whole-tree drift sweep (SessionStart / CLI)


class Level(str, Enum):
    """Severity of a finding: blocks the action, or advises only."""

    BLOCK = "block"
    ADVISE = "advise"


DEFAULT_STALENESS_DAYS: Final[int] = 30
DEFAULT_COMPLETED_DIR_NAME: Final[str] = "Completed"
DEFAULT_CANCELLED_DIR_NAME: Final[str] = "Cancelled"

# Journal policy defaults (Plan 00163). The daemon config model overrides these
# via QaPolicy; the package-level defaults keep plan_qa usable standalone.
DEFAULT_JOURNAL_DIR_NAME: Final[str] = "JOURNAL"
DEFAULT_JOURNAL_FRESHNESS_DAYS: Final[int] = 3
DEFAULT_JOURNAL_MODE: Final[str] = "advise"


@dataclass(frozen=True)
class Finding:
    """One violated invariant plus its exact remediation."""

    check_id: str
    level: Level
    message: str
    remediation: str
    path: str | None = None


@dataclass(frozen=True)
class CheckContext:
    """Everything a check may consult, built by the calling surface.

    Stage-specific slots are ``None`` when not applicable: an EDIT context
    carries the would-be file content; a COMMIT context carries
    :class:`GitFacts` plus tree/readme views; a SWEEP context carries the
    tree/readme views only. Policy knobs mirror ``plan_workflow.qa`` config
    as plain values so this package stays daemon-decoupled.
    """

    project_root: Path
    plan_dir_rel: str

    # Policy (mirrors the plan_workflow.qa config; plain values only).
    completed_dir: str = DEFAULT_COMPLETED_DIR_NAME
    cancelled_dir: str | None = DEFAULT_CANCELLED_DIR_NAME
    require_terminal_date: bool = False
    staleness_days: int = DEFAULT_STALENESS_DAYS
    legacy_plan_allowlist: frozenset[int] = field(default_factory=frozenset)
    collision_allowlist: frozenset[int] = field(default_factory=frozenset)

    # Journal policy (Plan 00163; mirrors plan_workflow.qa.journal.*).
    journal_enabled: bool = True
    journal_mode: str = DEFAULT_JOURNAL_MODE
    journal_dir_name: str = DEFAULT_JOURNAL_DIR_NAME
    journal_freshness_days: int = DEFAULT_JOURNAL_FRESHNESS_DAYS
    journal_enforce_on_completion: bool = False
    journal_grandfather_before: int = 0

    # Stage 1 (EDIT): the file being written and its would-be content.
    file_path: Path | None = None
    file_content: str | None = None
    file_exists_before: bool | None = None
    # Pre-edit on-disk content (Plan 00163): threaded by plan_qa_edit so the
    # append-only journal check stays a pure function. ``None`` when the file
    # did not exist before (a creation) or the surface did not supply it.
    file_content_before: str | None = None

    # Stage 2 (COMMIT).
    gitfacts: "GitFacts | None" = None
    commit_message: str | None = None

    # Stage 2 + 3 (COMMIT / SWEEP): parsed tree state.
    tree: "PlanTree | None" = None
    readme: "ReadmeIndex | None" = None
    today: date | None = None

    @property
    def plan_dir(self) -> Path:
        """Absolute path of the configured plan directory."""
        return self.project_root / self.plan_dir_rel


CheckFn = Callable[[CheckContext], list[Finding]]


@dataclass(frozen=True)
class CheckSpec:
    """Declarative registration of one check.

    ``level`` is the check's NOMINAL level (used for docs and defaults); a
    check may emit individual findings at a lower level, e.g. advise-only on
    grandfathered legacy plans while blocking on new material.
    """

    check_id: str
    stage: Stage
    level: Level
    sins: tuple[str, ...]
    run: CheckFn
