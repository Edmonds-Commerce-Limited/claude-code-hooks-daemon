"""LintOnEditHandler - runs language-aware lint validation after Write/Edit.

Uses Strategy Pattern: all language-specific logic is delegated to LintStrategy
implementations. The handler itself has ZERO language awareness.
"""

import shutil
import subprocess  # nosec B404 - subprocess used for lint validation only (trusted tools)
import sys
from pathlib import Path
from typing import Any, ClassVar, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    Timeout,
    ToolName,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import BlockingResult, Decision, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_written_file_paths
from claude_code_hooks_daemon.core.workspace import Workspace, resolve_workspace
from claude_code_hooks_daemon.strategies.lint.common import matches_skip_path
from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy
from claude_code_hooks_daemon.strategies.lint.registry import LintStrategyRegistry
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.path_exclusion import (
    handler_excludes_path,
    resolve_project_root,
)

# Placeholder for file path in lint commands
_FILE_PLACEHOLDER = "{file}"

# Directory holding the console scripts of the environment running the daemon.
# ``sys.executable`` is the project venv's interpreter, and a venv's ``ruff`` /
# ``black`` / ``mypy`` entry points sit beside it. Resolved once at import.
_INTERPRETER_BIN_DIR: Final[Path] = Path(sys.executable).parent

# Single rule (Plan 00116): the language dimension lives in the strategy
# registry, not in a per-language RuleID -- every language's lint failure is
# the same concept, "a written/authored file fails its language's lint check".
# This is a POST-hoc failure report, not a rollback -- the dynamic lint tool
# output itself must stay fully present in BOTH verbose and terse forms; only
# the surrounding "the write already landed, fix with Edit" prose goes terse.
_LINT_FAILURE_RULE = Rule(
    rule_id=RuleID.LINT_FAILURE,
    blocked="a written/authored file that fails its language's lint check",
    why="The write has already landed on disk; this is a failure report, not a rollback",
    fix="Fix the reported problems with Edit — do not re-Write the file from scratch",
    verbose=(
        "The write has ALREADY landed on disk. This is a failure report, not a "
        "rollback — the file exists, with your content in it. Fix the reported "
        "problems with Edit. Do NOT re-Write the file from scratch: that rewrites "
        "content already on disk from memory, and loses anything you no longer "
        "have in hand.\n\n"
        "A denial also cancels every sibling tool call batched in the same turn, "
        "so re-issue those separately."
    ),
)


class LintOnEditHandler(PostToolUseHandlerBase):
    """Run language-aware lint validation on files after Write/Edit.

    Uses Strategy Pattern: delegates ALL language-specific decisions to LintStrategy
    implementations registered in the LintStrategyRegistry. The handler orchestrates
    the workflow without any knowledge of specific languages.

    Each language defines a default lint command (e.g., bash -n, python -m py_compile)
    and an optional extended lint command (e.g., shellcheck, ruff). Commands are
    overridable at project level via config.

    Configuration options (set via config YAML):
        languages: list[str] | None - Restrict to specific languages.
            If not set or empty, ALL registered languages are enforced (default).
        command_overrides: dict[str, dict] | None - Override lint commands per language.
            Example: {"Python": {"default": "ruff check {file}", "extended": null}}
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.LINT_ON_EDIT,
            priority=Priority.LINT_ON_EDIT,
            terminal=False,
            tags=[
                HandlerTag.VALIDATION,
                HandlerTag.MULTI_LANGUAGE,
                HandlerTag.QA_ENFORCEMENT,
                # BLOCKING despite terminal=False: a lint failure returns
                # Decision.DENY. The two are independent -- `terminal` controls
                # whether dispatch continues, not whether the call is denied --
                # and rendering this as NON-TERMINAL contradicted this handler's
                # own resident guidance, which states plainly that it DENIES.
                HandlerTag.BLOCKING,
                HandlerTag.NON_TERMINAL,
            ],
        )
        self._registry = LintStrategyRegistry.create_default()
        # Config options: set via setattr AFTER __init__
        self._languages: list[str] | None = None
        self._command_overrides: dict[str, dict[str, str | None]] | None = None
        self._languages_applied: bool = False
        # Glob patterns exempted from linting entirely. Unions with the
        # project-wide daemon.exclude_paths the registry injects (Plan 00251,
        # the other half of the follow-up Plan 00150's Non-Goals deferred).
        self._exclude_paths: list[str] | None = None
        # Lint files a Bash command AUTHORED -- a redirect, `tee`, a heredoc
        # (Plan 00260 Task 3.5). Before this, `cat > x.py <<EOF` reached disk
        # unlinted while the identical content via `Write` was denied, so the
        # safest-looking route was the unguarded one. Relocation (`cp`/`mv`/
        # `dd`) is never linted -- see `get_written_file_paths`.
        self._lint_bash_writes: bool = True
        self._formatter = RuleFormatter()

    def _apply_language_filter(self) -> None:
        """Apply language filter to registry on first use (lazy)."""
        if self._languages_applied:
            return
        self._languages_applied = True
        effective_languages = self._languages or self._project_languages
        if effective_languages:
            self._registry.filter_by_languages(effective_languages)

    def _lintable_paths(self, hook_input: dict[str, Any]) -> list[str]:
        """Files this event authored that this handler should actually lint.

        A Bash command can author several files at once (`tee a.py b.py`), so
        this is a LIST where the Write/Edit path was always a single file.
        """
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name == ToolName.BASH and not self._lint_bash_writes:
            return []
        if tool_name not in (ToolName.WRITE, ToolName.EDIT, ToolName.BASH):
            return []
        return [path for path in get_written_file_paths(hook_input) if self._is_lintable(path)]

    def _is_lintable(self, file_path: str) -> bool:
        """Whether one authored path is in scope for linting."""
        # A protected file (secret_file_guard's globs) must never surface in a
        # lint diagnostic -- a syntax-error message can quote the offending
        # source line verbatim (Plan 00272 Task 4-5). Checked first: a
        # protected path is never lintable, whatever its extension.
        if sfm.path_is_protected(file_path, sfm.resolve_configured_patterns()):
            return False

        # A project may exempt a path from linting entirely (Plan 00251). Checked
        # before the strategy lookup and before the exists() stat: an exclusion is
        # the project declaring this path out of scope, which should not depend on
        # a strategy existing for the extension.
        if handler_excludes_path(
            file_path,
            handler_patterns=self._exclude_paths,
            project_patterns=self._project_exclude_paths,
        ):
            return False

        # Find strategy for this file's language
        strategy = self._registry.get_strategy(file_path)
        if strategy is None:
            return False  # Unknown language - allow through

        # Check skip paths
        if matches_skip_path(file_path, strategy.skip_paths):
            return False

        # File must exist. For Write/Edit this is a formality -- PostToolUse runs
        # after the write. For Bash it is load-bearing: the target is PREDICTED
        # from the command text, and a command that failed (or was never going to
        # write) leaves nothing on disk. Linting a path that does not exist would
        # manufacture an error the agent cannot act on.
        return Path(file_path).exists()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this event authored a lintable file, via any write route."""
        self._apply_language_filter()
        return bool(self._lintable_paths(hook_input))

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Run lint commands and deny if errors found."""
        paths = self._lintable_paths(hook_input)
        if not paths:
            return BlockingResult(decision=Decision.ALLOW, reason="No file path found")

        for file_path in paths:
            result = self._lint_one(hook_input, file_path)
            if result is not None:
                return result

        return BlockingResult(decision=Decision.ALLOW)

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's blocking behaviour."""
        return [_LINT_FAILURE_RULE]

    def _lint_one(self, hook_input: dict[str, Any], file_path: str) -> BlockingResult | None:
        """Lint a single file; a BlockingResult means it failed, None means it passed."""
        strategy = self._registry.get_strategy(file_path)
        if strategy is None:
            return None

        # Get lint commands (config overrides take priority)
        default_cmd, extended_cmd = self._get_lint_commands(strategy)

        # Run default lint command
        default_result = self._run_lint_command(
            hook_input, default_cmd, file_path, strategy.language_name
        )
        if default_result is not None:
            return default_result

        # Run extended lint command if configured and default passed
        if extended_cmd:
            return self._run_lint_command(
                hook_input, extended_cmd, file_path, strategy.language_name
            )

        return None

    def _get_lint_commands(self, strategy: LintStrategy) -> tuple[str, str | None]:
        """Get lint commands, checking config overrides first."""
        default_cmd = strategy.default_lint_command
        extended_cmd = strategy.extended_lint_command

        if self._command_overrides and strategy.language_name in self._command_overrides:
            overrides = self._command_overrides[strategy.language_name]
            if "default" in overrides:
                override_default = overrides["default"]
                if override_default is not None:
                    default_cmd = override_default
            if "extended" in overrides:
                extended_cmd = overrides.get("extended")

        return default_cmd, extended_cmd

    @staticmethod
    def _find_module_root(file_path: str, marker_file: str) -> str | None:
        """Find the nearest parent directory containing a marker file (e.g., go.mod).

        Walks up from the file's directory to find the module/project root.
        Returns the directory path if found, None otherwise.
        """
        current = Path(file_path).parent
        while current != current.parent:
            if (current / marker_file).exists():
                return str(current)
            current = current.parent
        return None

    # Map of language names to their module root marker files.
    #
    # Ansible needs this for the same reason Go does, but the failure is
    # sneakier: ``ansible.cfg``, ``.ansible-lint``, ``roles/`` and vendored
    # collections all resolve relative to the working directory, so running
    # from the wrong one makes the linter fail for the WRONG REASON — a denial
    # the author cannot act on, which is worse than not running it at all.
    #
    # One marker per language is a known limit (Plan 00268 DESIGN §4): a
    # project with ``.ansible-lint`` but no ``ansible.cfg`` resolves no root and
    # runs from the daemon's cwd, where ``--syntax-check`` on an absolute path
    # still works and only role/collection resolution degrades.
    _MODULE_ROOT_MARKERS: ClassVar[dict[str, str]] = {
        "Go": "go.mod",
        "Ansible": "ansible.cfg",
    }

    def _workspace_for(self, file_path: str) -> Workspace:
        """The declared project containing ``file_path``.

        Falls back to the file's own directory as the notional root when no
        ``ProjectContext`` is initialised, so a unit test exercising this
        handler directly neither raises nor resolves against an unrelated
        repository.
        """
        resolved = resolve_project_root()
        project_root = Path(resolved) if resolved else Path(file_path).parent
        return resolve_workspace(self._project_registry, Path(file_path), project_root)

    def _resolve_executable(
        self, executable: str, workspace_bin_dirs: tuple[Path, ...] = ()
    ) -> str | None:
        """Resolve a lint tool name to a runnable path, or None if absent.

        ``subprocess.run`` without a shell resolves a bare name against ``PATH``
        only. A Python project keeps its tooling in a virtualenv, so ``ruff``
        lives in ``<venv>/bin/ruff`` and is NOT on ``PATH`` — the daemon's own
        repo included. Every ``.py`` edit therefore raised ``FileNotFoundError``
        and degraded to "lint tool not found (ruff) - install to enable lint
        checking": the guard silently inert, and the advice wrong, because ruff
        was already installed.

        Search order: the edited file's OWN workspace bin dirs
        (``vendor/bin``, ``node_modules/.bin``), then the interpreter's own
        ``bin`` directory (that IS the project venv), then ``PATH`` for tools
        installed system wide (``golangci-lint``, ``shellcheck``).

        The workspace comes first deliberately (Plan 00296): a project pins a
        linter VERSION in its own manifest, so a global copy that happens to
        be on PATH is the wrong tool, and in a monorepo it may not exist at
        all while the workspace's copy does.

        Returning None rather than guessing is deliberate: the caller turns it
        into an advisory ALLOW. Invoking a missing tool some other way — e.g.
        rewriting the command to ``python -m ruff`` — would exit NON-ZERO
        instead of raising, and a non-zero lint result DENIES the user's edit.
        A tool that is not installed must never block anyone.
        """
        # An absolute path (e.g. sys.executable in the default Python command)
        # is already resolved; do not second-guess it.
        if Path(executable).is_absolute():
            return executable

        for bin_dir in workspace_bin_dirs:
            workspace_candidate = bin_dir / executable
            if workspace_candidate.is_file():
                return str(workspace_candidate)

        candidate = _INTERPRETER_BIN_DIR / executable
        if candidate.is_file():
            return str(candidate)

        return shutil.which(executable)

    def _run_lint_command(
        self,
        hook_input: dict[str, Any],
        command_template: str,
        file_path: str,
        language_name: str,
    ) -> BlockingResult | None:
        """Run a lint command and return BlockingResult if it fails, None if it passes.

        Returns:
            BlockingResult with DENY if lint fails, None if lint passes.
            BlockingResult with ALLOW if linter not found or times out (graceful degradation).
        """
        # The language's own marker wins where it declares one. `ansible.cfg`
        # is NOT a manifest, so the workspace resolver cannot find it -- going
        # resolver-only here would silently drop Ansible's working directory
        # and make the linter fail for the WRONG reason (see the comment on
        # _MODULE_ROOT_MARKERS). Every other language falls through to the
        # file's own workspace, which is where its config actually lives.
        workspace = self._workspace_for(file_path)
        working_dir: str | None = None
        marker = self._MODULE_ROOT_MARKERS.get(language_name)
        if marker:
            working_dir = self._find_module_root(file_path, marker)
        if working_dir is None:
            working_dir = str(workspace.root)

        # For Go, vet the package directory (not single file) since Go packages span
        # multiple files and single-file vetting can't resolve cross-file references
        effective_path = file_path
        if language_name == "Go" and working_dir:
            pkg_dir = str(Path(file_path).parent)
            # Convert absolute path to module-relative package path for go vet
            if pkg_dir.startswith(working_dir):
                effective_path = "./" + pkg_dir[len(working_dir) :].lstrip("/") + "/"

        command = command_template.replace(_FILE_PLACEHOLDER, effective_path)
        # Split command into list for subprocess
        # SECURITY: These are trusted lint tools defined in strategy constants
        command_parts = command.split()

        # Resolve the executable BEFORE running it. Strategies name their tools
        # bare (``ruff check {file}``) so they stay environment-independent; it
        # is this handler's job to find that name in the project venv or on
        # PATH. Without this the guard is inert wherever tooling lives in a
        # venv, which is the normal case for a Python project.
        resolved = self._resolve_executable(command_parts[0], workspace.bin_dirs)
        if resolved is None:
            searched = ", ".join(str(bin_dir) for bin_dir in workspace.bin_dirs)
            where = f"{searched}, " if searched else ""
            return BlockingResult(
                decision=Decision.ALLOW,
                context=[
                    f"⚠️ {language_name} lint tool not found ({command_parts[0]}) "
                    f"- looked in {where}{_INTERPRETER_BIN_DIR} and on PATH. "
                    f"Install it to enable lint checking."
                ],
            )
        command_parts[0] = resolved

        try:
            result = subprocess.run(  # nosec B603 - lint tools are trusted, file path from hook
                command_parts,
                capture_output=True,
                text=True,
                timeout=Timeout.LINT_CHECK,
                cwd=working_dir,
            )

            if result.returncode != 0:
                error_output = result.stdout
                if result.stderr:
                    error_output = (
                        error_output + "\n" + result.stderr if error_output else result.stderr
                    )

                dynamic_detail = (
                    f"{language_name} lint FAILED for {Path(file_path).name}\n\n"
                    f"{error_output}\n\n"
                    f"Command: {command}"
                )
                return BlockingResult(
                    decision=Decision.DENY,
                    reason=self._deny_reason(hook_input, dynamic_detail),
                )

        except FileNotFoundError:
            # Linter not installed - advisory allow (visible in system-reminders)
            return BlockingResult(
                decision=Decision.ALLOW,
                context=[
                    f"⚠️ {language_name} lint tool not found ({command_parts[0]}) "
                    f"- install to enable lint checking"
                ],
            )
        except subprocess.TimeoutExpired:
            return BlockingResult(
                decision=Decision.ALLOW,
                context=[
                    f"Lint check timed out after {Timeout.LINT_CHECK}s for {Path(file_path).name}"
                ],
            )

        return None

    def _deny_reason(self, hook_input: dict[str, Any], dynamic_detail: str) -> str:
        """Build a DENY reason, verbose-first/terse-after per (transcript_path, rule_id).

        Plan 00116, Decision G. The dynamic lint tool output is a POST-hoc
        failure report -- it must stay fully present in BOTH the verbose and
        terse forms; only the surrounding "write already landed, fix with
        Edit" teaching prose goes terse on repeat fires.
        """
        rule = _LINT_FAILURE_RULE
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(transcript_path, rule.rule_id):
            message = self._formatter.terse(rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, rule.rule_id)
            message = self._formatter.verbose(rule)

        return f"{message}\n\n{dynamic_detail}"

    def get_enforcement_status(self, project_root: Path) -> list[str]:
        """Advisory when an active strategy's extended linter is unresolvable.

        Plan 00296 Task 4.1. Only the EXTENDED tool is probed -- the built-in
        default command (``bash -n``, ``python -m py_compile``) is always
        available, so its absence is not a meaningful degradation to report.
        Cheap: reuses `_resolve_executable`'s own filesystem checks (`is_file`/
        `shutil.which`), no subprocess is run.
        """
        self._apply_language_filter()
        workspace = resolve_workspace(self._project_registry, project_root, project_root)
        statuses: list[str] = []
        for strategy in self._registry.strategies():
            extended = strategy.extended_lint_command
            if not extended:
                continue
            executable = extended.split()[0]
            if self._resolve_executable(executable, workspace.bin_dirs) is None:
                statuses.append(
                    f"lint_on_edit: {strategy.language_name} extended linter "
                    f"'{executable}' not found at {project_root} (workspace bin dirs, "
                    "interpreter bin, or PATH) — falls back to the built-in default "
                    "lint command only."
                )
        return statuses

    def get_claude_md(self) -> str | None:
        return """## lint_on_edit — source writes are linted, and a failure DENIES

Every `Write`/`Edit` to a Python, Shell, Go, PHP, Ruby, Rust, Swift, Kotlin or
Dart file is linted immediately. A lint failure DENIES the tool call.

**Ansible YAML is covered too, and only Ansible YAML.** A `.yml`/`.yaml` file is
linted when it is plausibly a playbook or a role task file — by Ansible's own
conventions (`playbooks/`, `roles/`, `tasks/`, `handlers/`, `site.yml`,
`play-*`, `playbook-*`) or by carrying a top-level `- hosts:` / `- import_playbook:`
line wherever it sits. Everything else sharing the extension is left alone:
`.github/workflows/`, `hooks-daemon.yaml`, `docker-compose*`, `group_vars/`,
`host_vars/`, inventories, and any vault file (never read — it is encrypted).
The cheap tier is `ansible-playbook --syntax-check`, which is what catches a
play that will not LOAD: an unbalanced quote inside a `shell:` block aborts the
whole play at parse time, before `#` means comment. Full `ansible-lint` runs at
the `extended` tier. The linter runs from the nearest directory containing
`ansible.cfg`, because roles and collections resolve relative to it.

**Bash-authored files are linted too.** A file a command writes with `>`, `>>`,
`tee` or a `cat <<EOF` heredoc gets the same treatment — so the heredoc route is
no longer the quiet way to land unparseable source. A command can author several
files at once (`tee a.py b.py`); each is linted and the first failure is
reported. Two boundaries are deliberate:

- **Relocation is NOT linted.** `cp`, `mv`, `install` and `dd` move bytes that
  were already on disk, so denying them would report a defect the command did
  not introduce and leave you repairing a file you never wrote.
- **A target that does not exist is NOT linted.** The path is inferred from the
  command text, so a command that failed leaves nothing to check.

Opt out with `handlers.post_tool_use.lint_on_edit.options.lint_bash_writes:
false`, which leaves `Write`/`Edit` linting untouched.

**The write has ALREADY landed on disk.** A PostToolUse denial is a failure
report, not a rollback — the file exists, with your content in it. Fix the
reported problems with `Edit`. Do NOT re-`Write` the file from scratch: that
rewrites content already on disk from memory, and loses anything you no longer
have in hand.

A denial also cancels every sibling tool call batched in the same turn, so
re-issue those separately.

Each language runs a cheap syntax check first (`python -m py_compile`, `bash
-n`, `go vet`, `php -l`, …) and then an optional deeper linter (`ruff`,
`shellcheck`, `golangci-lint`, `rubocop`, …). Tools are resolved from the
daemon's venv before `PATH`.

**A linter that is not installed never blocks.** You get an advisory saying it
was not found and the write stands — so that message means the check was
SKIPPED, not that it passed. That leniency is specific to THIS handler:
`.ts`/`.tsx` files are handled by `validate_eslint_on_write`, which denies on
a timeout and on any failure to run ESLint.

Narrow it under `handlers.post_tool_use.lint_on_edit.options`: `languages`
restricts which languages are checked, `command_overrides` replaces a
language's `default`/`extended` command (set `extended: null` to run only the
syntax check), and `exclude_paths` exempts paths entirely via gitignore-style
globs. The project-wide `daemon.exclude_paths` applies here too; the two are
additive and neither overrides the other."""

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests aggregated from all registered strategies."""
        tests: list[Any] = []
        seen_languages: set[str] = set()
        for strategy in self._registry._strategies.values():
            if strategy.language_name in seen_languages:
                continue
            seen_languages.add(strategy.language_name)
            if hasattr(strategy, "get_acceptance_tests"):
                tests.extend(strategy.get_acceptance_tests())
        tests.extend(self._bash_route_acceptance_tests())
        return tests

    def _bash_route_acceptance_tests(self) -> list[Any]:
        """Tests for the Bash write route, which is handler-level, not per-language.

        The per-strategy tests above all drive the `Write` TOOL and are therefore
        English prose -- no shell command can express "use the Write tool". The
        Bash route is the opposite: it IS a shell command, so these are literal
        and machine-executable, which is what `CLAUDE/CodeLifecycle/Features.md`
        asks for wherever a test can be expressed that way.

        Both directions are covered on purpose. A test that only proves the
        denial would pass just as well against a handler that denied every Bash
        command, so the relocation case is what shows the boundary is real.
        """
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        # nosec B108 - acceptance test fixture path a human runs in a shell, not a
        # runtime temp file. B108 guards sockets/PID files/logs, which CLAUDE.md
        # routes to the daemon's untracked dir; the same convention is used at
        # recovery_cron_advisor.py for an identical fixture path.
        directory = "/tmp/acceptance-test-lint-bash"  # nosec B108
        return [
            AcceptanceTest(
                title="Bash heredoc authoring invalid Python is DENIED",
                command=(f"cat > {directory}/authored.py <<'EOF'\ndef broken(\nEOF"),
                description=(
                    "Plan 00260 Task 3.5. Before this, a heredoc put unparseable Python on "
                    "disk in silence while identical content through Write was denied -- so "
                    "the route that looked safest, because nothing complained, was the only "
                    "unguarded one. The write lands first, so the denial is a failure report "
                    "to repair with Edit, not a rollback."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"authored\.py"],
                safety_notes="Writes a temporary Python file under /tmp; removed by cleanup",
                test_type=TestType.BLOCKING,
                setup_commands=[f"mkdir -p {directory}"],
                cleanup_commands=[f"rm -rf {directory}"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Copying an already-broken file is NOT denied",
                command=(f"cp {directory}/source.py {directory}/copied.py"),
                description=(
                    "The boundary that makes the Bash route safe to enable by default. "
                    "`cp` writes a file, and the memory-path guard must see it -- copying "
                    "INTO a guarded directory is a real bypass. A LINTER must not: the bytes "
                    "were already on disk, so denying the copy would report a defect the "
                    "command did not introduce and leave the agent repairing a file it never "
                    "chose to write. The source here is deliberately invalid Python."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Copies a temporary file under /tmp; removed by cleanup",
                test_type=TestType.ADVISORY,
                setup_commands=[
                    f"mkdir -p {directory}",
                    f"printf 'def broken(\\n' > {directory}/source.py",
                ],
                cleanup_commands=[f"rm -rf {directory}"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
