"""GuardConfigCommitGateHandler — name a guard weakening as it enters history.

Plan 00412 class 2, `guard-self-disablement-unwatched`: an action that changes
what a future session's guards will do, judged by no gate and recorded nowhere.
:mod:`...handlers.session_start.guard_config_drift` reports a weakening sitting
in the working tree; this reports one at the moment it is committed, which is
where a reviewer looks.

**It reports and never denies, which is measured rather than preferred.** Two
designs were tested against this repository's 3,903 commits:

* requiring a literal `RULE CHANGE:` marker — 7 of 20 weakening commits carry
  one, so 13 that were already explaining themselves would be blocked;
* requiring the commit message to NAME the weakened handler — 1 of 5.

Both judge the message's SPELLING rather than whether anyone reasoned. One of
the four the second design would block spends a paragraph on precisely the
config decision it changes, and fails only because it writes "sensitive-content
guard" instead of the underscore config key. A gate with an 80% historical
false-alarm rate gets switched off, which is the finding eating itself — so no
marker and no naming rule is imposed, and the RECORD is the whole deliverable.
That is what class 2 asks for: denial was never part of it.

Only WEAKENINGS are reported, unlike the session-start sibling which also
counts unrecognised differences. There the question is "does this differ from
what was reviewed"; here the diff is already in front of the reviewer, so an
unnamed difference earns no line.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority, ToolName
from claude_code_hooks_daemon.core import AcceptanceTest, Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.command_evasion import git_subcommand_index
from claude_code_hooks_daemon.utils.git_commit_parsing import (
    commits_working_tree,
    extract_commit_pathspecs,
    tokenise_command,
)
from claude_code_hooks_daemon.utils.git_repo import run_git
from claude_code_hooks_daemon.utils.guard_config_drift import (
    DriftReport,
    compare_guard_config,
)
from claude_code_hooks_daemon.utils.path_predicates import read_text_or_reason

logger = logging.getLogger(__name__)

CONFIG_RELATIVE_PATH: Final[str] = ".claude/hooks-daemon.yaml"
_HEAD_REF: Final[str] = f"HEAD:{CONFIG_RELATIVE_PATH}"
_INDEX_REF: Final[str] = f":{CONFIG_RELATIVE_PATH}"
_GIT_COMMIT_SUBCOMMAND: Final[str] = "commit"
_GIT_EXECUTABLE: Final[str] = "git"


class RecordedSource(StrEnum):
    """Which version of the config a ``git commit`` will actually record."""

    INDEX = "index"
    WORKING_TREE = "working-tree"


def recorded_config_source(command: str, config_path: str) -> RecordedSource | None:
    """Where ``command`` takes the config content from, or None if it takes none.

    Three shapes, and reading the wrong one makes the gate look clean on a
    commit it never examined:

    * ``git commit -a`` records the WORKING TREE, so the index is not what
      lands. This is the route the class is about -- edit the config, commit
      with ``-a`` -- and a gate reading only the index sees nothing.
    * ``git commit <pathspec>`` records the WORKING TREE of those paths only.
      When the config is not among them the commit cannot carry a config
      change at all, and None says so.
    * anything else records the INDEX.
    """
    tokens = tokenise_command(command)
    if not tokens:
        return None
    subcommand_index = _commit_subcommand_index(tokens)
    if subcommand_index is None:
        return None

    if commits_working_tree(tokens[subcommand_index + 1 :]):
        return RecordedSource.WORKING_TREE

    pathspecs = extract_commit_pathspecs(tokens)
    if not pathspecs:
        return RecordedSource.INDEX
    if any(_pathspec_covers(spec, config_path) for spec in pathspecs):
        return RecordedSource.WORKING_TREE
    return None


def _commit_subcommand_index(tokens: list[str]) -> int | None:
    """Index of the ``commit`` subcommand, reading ``git -C path commit`` too."""
    for position, token in enumerate(tokens[:-1]):
        if token != _GIT_EXECUTABLE and not token.endswith(f"/{_GIT_EXECUTABLE}"):
            continue
        index = git_subcommand_index(tokens, position)
        if index is not None and tokens[index] == _GIT_COMMIT_SUBCOMMAND:
            return index
    return None


def _pathspec_covers(spec: str, config_path: str) -> bool:
    """Whether ``spec`` names the config, or a directory containing it.

    A directory pathspec commits everything beneath it, so ``git commit
    .claude`` carries the config even though it never names the file.
    """
    normalised = spec.rstrip("/")
    return config_path == normalised or config_path.startswith(f"{normalised}/")


class GuardConfigCommitGateHandler(PreToolUseHandlerBase):
    """Report, at commit time, a config change that weakens this project's guards."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.GUARD_CONFIG_COMMIT_GATE,
            priority=Priority.GUARD_CONFIG_COMMIT_GATE,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.SAFETY,
                HandlerTag.NON_TERMINAL,
                HandlerTag.GIT,
            ],
        )
        #: Injected in tests so the comparison needs no git and no filesystem.
        self.head_reader: Callable[[], str | None] = self._read_head
        self.recorded_reader: Callable[[RecordedSource], str | None] = self._read_recorded

    def matches(self, hook_input: dict[str, Any]) -> bool:
        if hook_input.get("tool_name") != ToolName.BASH:
            return False
        command = get_bash_command(hook_input) or ""
        return _commit_subcommand_index(tokenise_command(command)) is not None

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        command = get_bash_command(hook_input) or ""
        source = recorded_config_source(command, CONFIG_RELATIVE_PATH)
        if source is None:
            return GatingResult(decision=Decision.ALLOW, context=[])

        committed = self.head_reader()
        recorded = self.recorded_reader(source)
        if committed is None or recorded is None:
            # No baseline, or nothing readable to compare. Neither is drift,
            # and neither is evidence of its absence.
            return GatingResult(decision=Decision.ALLOW, context=[])

        report = compare_guard_config(committed, recorded, known_handlers=_known_handlers())
        return GatingResult(decision=Decision.ALLOW, context=_render(report, source))

    @staticmethod
    def _project_root() -> Path | None:
        """The project root, or None when the daemon has not initialised one.

        ASKS rather than catches: ``project_root()`` raises when the context is
        not set up, and catching that to return None makes an ordinary,
        expected state look like a failure.
        """
        if not ProjectContext.is_initialized():
            logger.debug("guard_config_commit_gate: ProjectContext not initialised")
            return None
        return ProjectContext.project_root()

    def _read_head(self) -> str | None:
        """The config as the last commit has it, or None when there is none."""
        root = self._project_root()
        if root is None:
            return None
        result = run_git(root, "show", _HEAD_REF)
        if result.returncode != 0:
            logger.debug("guard_config_commit_gate: no committed config to compare against")
            return None
        return result.stdout

    def _read_recorded(self, source: RecordedSource) -> str | None:
        """The config content this commit will actually record."""
        root = self._project_root()
        if root is None:
            return None
        if source is RecordedSource.WORKING_TREE:
            # The reason is carried on the returned value rather than discarded,
            # so "absent" and "unreadable" stay distinct to anyone debugging a
            # silent gate -- and so this is not a `return None` from an except
            # body, which is error hiding.
            return read_text_or_reason(root / CONFIG_RELATIVE_PATH).text
        result = run_git(root, "show", _INDEX_REF)
        if result.returncode != 0:
            # The path is not in the index, so the commit records no config.
            logger.debug("guard_config_commit_gate: config absent from the index")
            return None
        return result.stdout

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        from claude_code_hooks_daemon.core import RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="guard config commit gate - reports a weakening at commit time",
                command='echo "test"',
                description=(
                    "Tests that a git commit whose config disables a handler, removes "
                    "its block, or widens an exclusion relative to HEAD is named "
                    "before the commit runs. Reports only; it never denies."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"GUARD CONFIG|weaken"],
                safety_notes="Advisory handler - reports but never blocks",
                test_type=TestType.CONTEXT,
                requires_event="PreToolUse event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]


def _known_handlers() -> frozenset[str]:
    """Config keys of every handler the registry still knows about.

    Gates the `removed` finding: a config block removed while the handler
    still exists silently disables a guard that is there to run, whereas one
    removed for a deleted handler is housekeeping. Measured over this
    repository's history, counting every removal turned two ordinary config
    reorganisations into 21 and 19 findings apiece.
    """
    return frozenset(
        member.config_key
        for name, member in vars(HandlerID).items()
        if not name.startswith("_") and hasattr(member, "config_key")
    )


def _render(report: DriftReport, source: RecordedSource) -> list[str]:
    """The advisory text, or nothing at all when no guard is weakened."""
    if not report.guard_changes:
        return []

    origin = (
        "the working tree (this commit carries it)"
        if source is RecordedSource.WORKING_TREE
        else "the staged config"
    )
    lines = [
        f"GUARD CONFIG: this commit WEAKENS a guard, per {origin}:",
        "",
    ]
    lines += [f"  - {change}" for change in report.guard_changes]
    lines += [
        "",
        "Not a reason to stop: weakening a guard is sometimes right. This is a "
        "record, so the change is reviewable rather than silent. If it is "
        "deliberate, say why in the commit message; if it is not, drop it from "
        "this commit.",
    ]
    return lines
