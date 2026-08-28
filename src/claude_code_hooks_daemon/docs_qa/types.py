"""Core types for the docs QA check system (Plan 00284).

A *check* is a pure function ``CheckContext -> list[Finding]`` registered
declaratively as a :class:`CheckSpec` with an id and the stage it runs at.
Handlers and the CLI never contain rule logic: they build a
:class:`CheckContext`, call :func:`docs_qa.runner.run_stage`, and render
the findings. Mirrors :mod:`claude_code_hooks_daemon.plan_qa.types`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy

if TYPE_CHECKING:
    from claude_code_hooks_daemon.docs_qa.corpus import DocCorpus


class CheckStage(StrEnum):
    """When a check runs."""

    EDIT = "edit"  # Write/Edit (or Bash-authored write) of a single doc file
    STAGED = "staged"  # git commit gate over the staged tree
    SWEEP = "sweep"  # whole-corpus drift sweep (SessionStart / CLI)


class Severity(StrEnum):
    """Severity of a finding: blocks the action, or advises only."""

    BLOCK = "block"
    ADVISE = "advise"


@dataclass(frozen=True)
class Finding:
    """One violated invariant plus its exact remediation."""

    check_id: str
    severity: Severity
    message: str
    remediation: str
    path: str | None = None


@dataclass(frozen=True)
class CheckContext:
    """Everything a check may consult, built by the calling surface.

    Stage-specific slots are ``None`` when not applicable: an EDIT context
    carries the would-be file content; a SWEEP context carries a
    :class:`~claude_code_hooks_daemon.docs_qa.corpus.DocCorpus`. STAGED is
    not implemented in this slice (see ``docs_qa.context.staged_context``).
    """

    project_root: Path
    policy: DocumentationPolicy

    # EDIT stage: the file being written and its would-be content.
    file_path: Path | None = None
    file_content: str | None = None
    file_exists_before: bool | None = None
    # Pre-edit on-disk content, when the surface already read it — lets a
    # check distinguish a NEW violation from a pre-existing one.
    file_content_before: str | None = None

    # STAGED / SWEEP: the corpus index.
    corpus: "DocCorpus | None" = None


CheckFn = Callable[[CheckContext], list[Finding]]


@dataclass(frozen=True)
class CheckSpec:
    """Declarative registration of one check."""

    check_id: str
    stage: CheckStage
    run: CheckFn
