"""Cheap syntax-check backstop over staged files at ``git commit`` time.

`lint_on_edit` only ever sees a file at the moment `Write`/`Edit` touches it.
A file that reaches the index by any OTHER route -- `git add` of something
written earlier in the session, a commit of pre-existing changes, a merge --
is never linted before it lands. This handler closes that gap the same way
`plan_qa_commit_gate` closes the equivalent gap for plan hygiene: it inspects
the STAGED tree at the moment of `git commit`, so the outcome is caught
however the commit was invoked.

Cost bounds are part of the contract, not an afterthought (Plan 00268 Task
3.1 decision):

* only the CHEAP/syntax tier of each language's :class:`LintStrategy` ever
  runs -- never the extended linter, which the `default`/`extended` split
  already exists to keep optional;
* only staged Added/Copied/Modified files are considered (a deleted or
  renamed-away path has nothing left on disk to check);
* ``max_files`` stands the whole check down, with an advisory naming how many
  files were skipped, rather than linting an unbounded set on a large commit.

Ships ``mode: warn`` -- the same warn-first rollout as
``verification_result_gate`` and ``plan_qa_commit_gate`` -- so a failing
syntax check is visible as advisory context before this gate is ever allowed
to deny anything.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess  # nosec B404 - subprocess used for lint validation only (trusted tools)
import sys
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    Timeout,
    ToolName,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import AcceptanceTest, Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.strategies.lint.common import matches_skip_path
from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy
from claude_code_hooks_daemon.strategies.lint.registry import LintStrategyRegistry
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.command_evasion import (
    ENV_PREFIX,
    GIT_INVOCATION,
    normalise_line_continuations,
)
from claude_code_hooks_daemon.utils.git_repo import GitRepo, run_git
from claude_code_hooks_daemon.utils.shell_segmentation import split_unquoted

logger = logging.getLogger(__name__)

_MODE_WARN: Final[str] = "warn"
_MODE_BLOCK: Final[str] = "block"

# Default cap on how many staged lintable files one commit will check. A
# commit staging more than this stands the WHOLE check down rather than
# linting a subset silently -- either every staged file was considered, or
# the advisory says none were.
_DEFAULT_MAX_FILES: Final[int] = 20

_FIELD_COMMAND: Final[str] = "command"
_CWD_FIELD: Final[str] = "cwd"

# A newline separates commands exactly as `;` does (Plan 00268's own lesson,
# from `verification_result_gate`), and `&&`/`||`/`|` each start a new command
# span within a statement. Any segment being a `git commit` invocation is
# enough -- this handler does not care what precedes or follows it.
_SEGMENT_SEPARATORS: Final[tuple[str, ...]] = ("||", "&&", "|", ";", "\n")

_GIT_COMMIT_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"^\s*{ENV_PREFIX}{GIT_INVOCATION}commit(?=\s|$)"
)

# `git diff --cached --diff-filter=ACM` letters: Added, Copied, Modified. A
# Deleted or Renamed-away path has nothing left on disk to check.
_DIFF_FILTER: Final[str] = "ACM"

# Directory holding the console scripts of the environment running the
# daemon, mirroring `lint_on_edit`'s resolution order: the project venv
# first, `PATH` second.
_INTERPRETER_BIN_DIR: Final[Path] = Path(sys.executable).parent


def _is_git_commit_command(command: str) -> bool:
    """Whether any segment of ``command`` is a ``git commit`` invocation.

    Evasion-resistant via the same fragments `verification_result_gate` and
    `destructive_git` use: global options (`git -C`), an `env`/`VAR=` prefix,
    and line continuations (normalised before segmenting).
    """
    normalised = normalise_line_continuations(command)
    for segment in split_unquoted(normalised, _SEGMENT_SEPARATORS):
        if _GIT_COMMIT_PATTERN.search(segment.strip()):
            return True
    return False


class StagedLintGateHandler(PreToolUseHandlerBase):
    """Warn-first cheap-syntax-check backstop over staged files on git commit.

    Configuration options (set via config YAML):
        mode: "warn" (default) or "block".
        max_files: int - stand-down threshold (default 20).
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.STAGED_LINT_GATE,
            priority=Priority.STAGED_LINT_GATE,
            terminal=False,
            tags=[HandlerTag.VALIDATION, HandlerTag.QA_ENFORCEMENT, HandlerTag.GIT],
        )
        self._registry = LintStrategyRegistry.create_default()
        # Config options: set via setattr AFTER __init__.
        self._mode: str = _MODE_WARN
        self._max_files: Any = _DEFAULT_MAX_FILES
        # Single source of truth for the one rule this handler's DENY path
        # enforces (block mode only -- Plan 00116, gate-level granularity:
        # one Rule per GATE, not per lint check module). The per-file
        # findings are dynamic content and stay fully present in both
        # verbose and terse forms; only the surrounding teaching prose
        # about the gate itself goes terse-after-first-fire.
        self._rule = Rule(
            rule_id=RuleID.STAGED_LINT_FAILURE,
            blocked="a staged file fails the cheap syntax check at commit time",
            why=(
                "lint_on_edit only ever runs at Write/Edit time, so a git add of "
                "pre-existing content skips it entirely"
            ),
            fix="Fix the failing file(s) above and re-stage before committing",
            verbose=(
                "This is the CHEAP syntax tier only -- the same check `lint_on_edit` "
                "would have run at Write/Edit time, run again here because a file can "
                "reach the index by routes `lint_on_edit` never sees (a `git add` of "
                "something written earlier, a merge, a commit of pre-existing changes)."
            ),
        )
        self._formatter = RuleFormatter()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        if hook_input.get("tool_name") != ToolName.BASH:
            return False
        command = get_bash_command(hook_input)
        if not command:
            return False
        return _is_git_commit_command(command)

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        project_root = ProjectContext.project_root()

        if self._is_foreign_repo(hook_input, project_root):
            return GatingResult(decision=Decision.ALLOW, context=[])

        diff = run_git(
            project_root, "diff", "--cached", "--name-only", f"--diff-filter={_DIFF_FILTER}"
        )
        if diff.returncode != 0:
            return GatingResult(decision=Decision.ALLOW, context=[])

        lintable = self._lintable_files(project_root, diff.stdout)
        if not lintable:
            return GatingResult(decision=Decision.ALLOW, context=[])

        max_files = self._max_files_option()
        if len(lintable) > max_files:
            return GatingResult(
                decision=Decision.ALLOW,
                context=[
                    f"⚠️ staged-lint-gate: {len(lintable)} staged lintable file(s) exceed "
                    f"max_files ({max_files}) -- standing down without checking any of them."
                ],
            )

        failures = self._check_all(lintable)
        if not failures:
            return GatingResult(decision=Decision.ALLOW, context=[])

        if self._mode == _MODE_BLOCK:
            return GatingResult(
                decision=Decision.DENY,
                reason=self._blocking_message(failures, hook_input),
            )
        message = self._message(failures)
        return GatingResult(decision=Decision.ALLOW, context=[message])

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's block-mode denial."""
        return [self._rule]

    def _blocking_message(self, failures: list[tuple[str, str]], hook_input: dict[str, Any]) -> str:
        """Build the block-mode deny message: verbose-first/terse-after teaching
        prose (Plan 00116, Decision G), with the per-file findings ALWAYS fully
        present -- they are dynamic content, not the static teaching text the
        disclosure ladder governs.
        """
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(transcript_path, RuleID.STAGED_LINT_FAILURE):
            prose = self._formatter.terse(self._rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.STAGED_LINT_FAILURE)
            prose = self._formatter.verbose(self._rule)

        return f"{prose}\n\n{self._findings_block(failures)}"

    @staticmethod
    def _findings_block(failures: list[tuple[str, str]]) -> str:
        """Render the per-file findings list -- always present in full."""
        lines = [
            f"- {Path(path).name}: {diagnosis.splitlines()[0]}" for path, diagnosis in failures
        ]
        return "\n".join(lines)

    def _lintable_files(
        self, project_root: Path, staged_stdout: str
    ) -> list[tuple[str, LintStrategy]]:
        """Staged Added/Copied/Modified files a registered strategy handles."""
        found: list[tuple[str, LintStrategy]] = []
        for relpath in staged_stdout.splitlines():
            relpath = relpath.strip()
            if not relpath:
                continue
            abs_path = project_root / relpath
            if not abs_path.exists():
                continue
            # A protected file must never surface in a lint diagnostic -- a
            # syntax-error message can quote the offending source line
            # verbatim (Plan 00272 Task 4-5).
            if sfm.path_is_protected(str(abs_path), sfm.resolve_configured_patterns()):
                continue
            strategy = self._registry.get_strategy(str(abs_path))
            if strategy is None:
                continue
            if matches_skip_path(str(abs_path), strategy.skip_paths):
                continue
            found.append((str(abs_path), strategy))
        return found

    def _max_files_option(self) -> int:
        """The configured max_files, defensively coerced.

        Options arrive by blind ``setattr`` from YAML, so the type is not
        trusted. A malformed value falls back to the default rather than
        raising: this handler is advisory-by-default, and a config typo must
        not take the daemon down.
        """
        value = self._max_files
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return _DEFAULT_MAX_FILES

    def _check_all(self, lintable: list[tuple[str, LintStrategy]]) -> list[tuple[str, str]]:
        """Run the cheap syntax check on every file; return (path, diagnosis) failures."""
        failures: list[tuple[str, str]] = []
        for path, strategy in lintable:
            diagnosis = self._syntax_check(path, strategy)
            if diagnosis is not None:
                failures.append((path, diagnosis))
        return failures

    def _syntax_check(self, file_path: str, strategy: LintStrategy) -> str | None:
        """Run ONLY the strategy's cheap default command; None means it passed.

        Deliberately never runs `extended_lint_command` -- that is the
        deeper, slower linter the `default`/`extended` split exists to keep
        optional, and this handler's whole cost budget depends on staying on
        the cheap tier (Plan 00268 Task 3.1 decision).
        """
        command = strategy.default_lint_command.replace("{file}", file_path)
        parts = command.split()

        resolved = self._resolve_executable(parts[0])
        if resolved is None:
            return None  # tool not installed: never block on absence
        parts[0] = resolved

        try:
            result: subprocess.CompletedProcess[str] | None = (
                subprocess.run(  # nosec B603 - lint tools are trusted, file path from git
                    parts,
                    capture_output=True,
                    text=True,
                    timeout=Timeout.LINT_CHECK,
                )
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            # A missing binary or a timed-out subprocess is feature detection,
            # not a failure to hide: the file's syntax was never actually
            # checked, so there is nothing to report. Logged (not silent) so
            # the daemon log records that the check did not run, matching
            # `lint_on_edit`'s identical never-block-on-absence convention.
            logger.debug("staged_lint_gate: %s unavailable for %s: %s", parts[0], file_path, exc)
            result = None

        if result is None:
            return None

        if result.returncode == 0:
            return None

        output = result.stdout
        if result.stderr:
            output = f"{output}\n{result.stderr}" if output else result.stderr
        return output.strip() or f"exit code {result.returncode}"

    def _resolve_executable(self, executable: str) -> str | None:
        """Resolve a lint tool name to a runnable path, or None if absent.

        Mirrors `lint_on_edit._resolve_executable`: the project venv's own
        `bin/` is checked before `PATH`, since a Python project's tooling
        (`ruff`, `mypy`, ...) lives there rather than on `PATH`.
        """
        if Path(executable).is_absolute():
            return executable
        candidate = _INTERPRETER_BIN_DIR / executable
        if candidate.is_file():
            return str(candidate)
        return shutil.which(executable)

    @staticmethod
    def _is_foreign_repo(hook_input: dict[str, Any], project_root: Path) -> bool:
        """True when the command runs inside a repo other than the project's.

        Mirrors `PlanQaCommitGateHandler._is_foreign_repo`: nested/vendor
        repos and other worktrees own their own staged tree.
        """
        cwd_raw = hook_input.get(_CWD_FIELD)
        if not cwd_raw:
            return False
        repo = GitRepo.resolve_for(Path(cwd_raw))
        return repo is not None and repo.root != project_root

    @staticmethod
    def _message(failures: list[tuple[str, str]]) -> str:
        lines = [
            "STAGED LINT GATE: a syntax check FAILED for a staged file this commit "
            "would include.",
            "",
        ]
        for path, diagnosis in failures:
            lines.append(f"- {Path(path).name}: {diagnosis.splitlines()[0]}")
        lines.append("")
        lines.append(
            "Fix the file(s) above and re-stage before committing. This is the CHEAP "
            "syntax tier only -- the same check `lint_on_edit` would have run at "
            "Write/Edit time, run again here because a file can reach the index by "
            "routes `lint_on_edit` never sees (a `git add` of something written "
            "earlier, a merge, a commit of pre-existing changes)."
        )
        return "\n".join(lines)

    def get_claude_md(self) -> str | None:
        return (
            "## staged_lint_gate — staged files are syntax-checked at git commit\n\n"
            "Every staged Added/Copied/Modified file is run through the SAME cheap "
            "syntax check `lint_on_edit` uses (`python -m py_compile`, `bash -n`, "
            "`go vet`, `php -l`, …) at the moment of `git commit` — never the "
            "deeper `extended` linter, and never more than `max_files` (default 20) "
            "files, which stands the whole check down with an advisory naming how "
            "many were skipped rather than linting a subset silently.\n\n"
            "**This is a BACKSTOP, not a replacement for `lint_on_edit`.** "
            "`lint_on_edit` only ever sees a file at the moment `Write`/`Edit` "
            "touches it. A file that reaches the index by any OTHER route — "
            "`git add` of something written earlier in the session, a merge, a "
            "commit of pre-existing changes — is never linted before it lands. "
            "This handler catches that file's staleness at the one point that is "
            "guaranteed to see it: the commit itself.\n\n"
            "Ships `mode: warn` (advisory context naming each failing file and its "
            "first line of diagnosis); set "
            "`handlers.pre_tool_use.staged_lint_gate.options.mode: block` to deny "
            "the commit instead. Nested/vendor repos and other worktrees are "
            "exempt — this only checks the project's own staged tree."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Staged lint gate - a dry-run commit is never blocked",
                command="git commit --dry-run",
                description=(
                    "`--dry-run` reports what WOULD be committed without committing "
                    "anything, so this is safe to run against any repository state. "
                    "In the shipped `mode: warn` configuration the command always "
                    "succeeds regardless of what is staged."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="--dry-run never creates a commit or modifies the index.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Staged lint gate - git commit respellings are still recognised",
                command="git -C . commit --dry-run",
                description=(
                    "A `-C` global option must not hide the `commit` subcommand from "
                    "the gate. Read-only via `--dry-run`; proves the evasion-resistant "
                    "match without touching the index."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="--dry-run never creates a commit or modifies the index.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
