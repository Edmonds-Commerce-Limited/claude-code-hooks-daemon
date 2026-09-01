"""MonorepoDetectorHandler - advises when a repo looks like an unconfigured monorepo.

Runs on SessionStart (new sessions only). Detection advises, never decides
(``CLAUDE/Code/WorkspaceResolution.md``): manifests found BELOW the repo root
with none AT it is the signature of a monorepo nobody has declared to the
daemon via ``projects:``. This handler reports the shape and prints a
ready-to-paste ``projects:`` block -- it never resolves a boundary itself.
"""

import logging
from pathlib import Path
from typing import Any

import yaml

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.constants.layout import CORE_VENDORED_BUILD_DIR_NAMES
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.workspace import _manifest_in
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

logger = logging.getLogger(__name__)

# Directories never worth descending into: vendored/build content can never
# hold a real workspace boundary, and a dotdir (.git, .venv, .github, ...) is
# either tooling metadata or already covered by the vendor set.
_SKIP_DIR_NAMES: frozenset[str] = CORE_VENDORED_BUILD_DIR_NAMES

# Bounds the walk so a huge repository cannot make session start slow. Chosen
# to comfortably cover a two- or three-level monorepo (apps/web,
# packages/shared/ui) without scanning the whole tree.
_MAX_WALK_DEPTH = 4


def _find_manifest_dirs(root: Path, max_depth: int = _MAX_WALK_DEPTH) -> list[tuple[Path, str]]:
    """Return ``(directory, kind)`` for every recognised manifest found below ``root``.

    Does not walk into vendored/build directories, dotdirs, or a directory
    that itself contains a ``.git`` entry (a different repository, not a
    sub-project of this one) -- and stops descending past a directory once a
    manifest is found in it, since that directory is itself the workspace
    boundary worth reporting.

    Args:
        root: Directory to search BELOW (root itself is never reported).
        max_depth: Maximum number of directory levels below ``root`` to visit.

    Returns:
        Manifest-bearing directories in a stable, depth-first, sorted order.
    """
    found: list[tuple[Path, str]] = []

    def _recurse(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(directory.iterdir())
        except OSError as exc:
            logger.debug("Could not list %s during monorepo scan: %s", directory, exc)
            return

        for entry in entries:
            if not entry.is_dir():
                continue
            if entry.name in _SKIP_DIR_NAMES or entry.name.startswith("."):
                continue
            if (entry / ".git").exists():
                # A nested git repository is a different repository, not a
                # sub-project of this one -- CLAUDE/Code/WorkspaceResolution.md.
                continue

            manifest, kind, _ = _manifest_in(entry)
            if manifest is not None:
                found.append((entry, kind))
                continue

            _recurse(entry, depth + 1)

    _recurse(root, 1)
    return found


class MonorepoDetectorHandler(SessionStartHandlerBase):
    """Advise when manifests exist below the repo root but not at it.

    Advisory only -- never blocks, never resolves a project boundary. Silent
    when a root manifest exists, when ``projects:`` is already declared, or in
    an ordinary single-project repository with nothing below the root either.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.MONOREPO_DETECTOR,
            priority=Priority.MONOREPO_DETECTOR,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
                HandlerTag.ENVIRONMENT,
            ],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return not is_resume_session(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Scan for an unconfigured monorepo shape and advise if found."""
        try:
            project_root = ProjectContext.project_root()
        except RuntimeError:
            logger.debug("ProjectContext not initialised; skipping monorepo detection")
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

        # Declared already -- the daemon knows the boundaries. Advising would
        # be noise on every session start for a repo that has already acted.
        if self._project_registry is not None and self._project_registry.projects:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

        root_manifest, _, _ = _manifest_in(project_root)
        if root_manifest is not None:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

        found = _find_manifest_dirs(project_root)
        if not found:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

        return AdvisoryResult(
            decision=Decision.ALLOW, context=self._build_context(found, project_root)
        )

    def _build_context(self, found: list[tuple[Path, str]], project_root: Path) -> list[str]:
        """Build the advisory text: workspaces found + a paste-ready projects: block."""
        entries = [
            {"name": directory.name, "root": directory.relative_to(project_root).as_posix()}
            for directory, _ in found
        ]
        yaml_block = yaml.safe_dump(
            {"projects": entries}, default_flow_style=False, sort_keys=False
        ).rstrip("\n")

        context = [
            "🔎 MONOREPO DETECTED: manifests found below the repo root, none at it",
            "",
            "This looks like a monorepo, but no `projects:` block is declared, so",
            "handlers that need a project (not just the git root) cannot see these",
            "workspaces -- see CLAUDE/Code/WorkspaceResolution.md.",
            "",
            "Workspaces found:",
        ]
        for directory, kind in found:
            rel = directory.relative_to(project_root).as_posix()
            context.append(f"  - {rel} ({kind})")
        context += [
            "",
            "Paste into .claude/hooks-daemon.yaml to declare them:",
            "",
            yaml_block,
        ]
        return context

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="monorepo detector - advises on an unconfigured monorepo shape",
                command='echo "test"',
                description=(
                    "Verifies the monorepo detector reports workspaces found below "
                    "the repo root when none is declared via projects:."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"monorepo|MONOREPO|projects:"],
                safety_notes="Advisory handler - never blocks, never resolves a boundary",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session only)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
