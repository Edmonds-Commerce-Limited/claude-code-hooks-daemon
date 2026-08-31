"""ValidateEslintOnWriteHandler - runs ESLint validation on TypeScript/TSX files after write.

When llm: commands exist in package.json, runs ESLint validation (enforcement mode).
When llm: commands do NOT exist, skips validation and advises about creating llm:lint.
"""

import logging
import os
import subprocess  # nosec B404 - subprocess used for eslint validation only (trusted tool)
from pathlib import Path
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    Timeout,
    ToolName,
)
from claude_code_hooks_daemon.constants.layout import CORE_VENDORED_BUILD_DIR_NAMES
from claude_code_hooks_daemon.constants.paths import ProjectPath
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import (
    BlockingResult,
    Decision,
    ProjectContext,
    get_data_layer,
)
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_written_file_paths
from claude_code_hooks_daemon.strategies.lint.common import matches_skip_path
from claude_code_hooks_daemon.utils.guides import get_llm_command_guide_path
from claude_code_hooks_daemon.utils.npm import has_llm_commands_in_package_json

logger = logging.getLogger(__name__)

# 3 rules (Plan 00116): distinct failure shapes with distinct diagnostics --
# reported errors, a timeout, and a failure to run ESLint at all.
_ESLINT_ERRORS_RULE = Rule(
    rule_id=RuleID.ESLINT_ERRORS,
    blocked="a written/authored TS/TSX file with reported ESLint errors",
    why="The write has already landed on disk; this is a failure report, not a rollback",
    fix="Fix the reported problems with Edit (`npx eslint <file> --fix` clears most)",
    verbose=(
        "The write has ALREADY landed on disk. The denial is a failure report, "
        "not a rollback — the file exists with your content in it. Fix the "
        "reported problems with Edit (`npx eslint <file> --fix` clears most of "
        "them), and re-issue any sibling tool calls that were cancelled "
        "alongside the denied one."
    ),
)
_ESLINT_TIMEOUT_RULE = Rule(
    rule_id=RuleID.ESLINT_TIMEOUT,
    blocked="an ESLint run that did not finish within the configured timeout",
    why="This handler DENIES on a timeout — unlike lint_on_edit, which allows",
    fix="Investigate why ESLint is slow (config, project size); retry the edit",
    verbose=(
        "This is STRICTER than `lint_on_edit`, which covers the other "
        "languages: that handler ALLOWs when its linter is missing or when "
        "the check times out. This one DENIES on an ESLint timeout — do not "
        "carry 'a missing linter never blocks' across to TypeScript."
    ),
)
_ESLINT_RUN_FAILURE_RULE = Rule(
    rule_id=RuleID.ESLINT_RUN_FAILURE,
    blocked="an ESLint invocation that failed to run at all",
    why="ESLint could not be launched (exception raised invoking it)",
    fix="Check the ESLint wrapper/tsx setup, then retry the edit",
    verbose=(
        "This is STRICTER than `lint_on_edit`, which covers the other "
        "languages: that handler ALLOWs when its linter is missing. This one "
        "DENIES on any failure to run ESLint at all — do not carry 'a missing "
        "linter never blocks' across to TypeScript."
    ),
)


class ValidateEslintOnWriteHandler(PostToolUseHandlerBase):
    """Run ESLint validation on TypeScript/TSX files after write."""

    VALIDATE_EXTENSIONS: ClassVar[list[str]] = [".ts", ".tsx"]
    # Plan 00288 Task 3.2: core (11 names) plus this handler's own extra,
    # "test-results" (Playwright/JS test artifacts) -- see
    # MEASUREMENT-vendored-dirs.md §3. Slash-suffixed and matched via
    # ``matches_skip_path``'s slash-bounded containment, NOT the old bare
    # substring check -- a bare check would newly skip first-party paths
    # like ``src/builder/x.ts`` ("build") or ``src/venvtool.ts`` ("venv")
    # once the set grew to include those short, common tokens.
    SKIP_PATHS: ClassVar[tuple[str, ...]] = tuple(
        f"{name}/" for name in (*sorted(CORE_VENDORED_BUILD_DIR_NAMES), "test-results")
    )

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        """
        Initialize handler with optional workspace root for test isolation.

        Args:
            workspace_root: Optional Path to project root (for testing).
                          If None, auto-detects using ProjectContext.
                          This allows tests to provide isolated test directories.
        """
        super().__init__(
            handler_id=HandlerID.VALIDATE_ESLINT_ON_WRITE,
            priority=Priority.VALIDATE_ESLINT_ON_WRITE,
            tags=[
                HandlerTag.VALIDATION,
                HandlerTag.TYPESCRIPT,
                HandlerTag.JAVASCRIPT,
                HandlerTag.QA_ENFORCEMENT,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )
        self.workspace_root = (
            Path(workspace_root) if workspace_root else ProjectContext.project_root()
        )
        self.has_llm_commands: bool = has_llm_commands_in_package_json()
        # Check files a Bash command AUTHORED as well as Write/Edit ones
        # (Plan 00260 Task 3.5). Relocation (`cp`/`mv`/`dd`) is never checked --
        # see `get_written_file_paths` for why a DENYING guard must not.
        self._check_bash_writes: bool = True
        self._formatter = RuleFormatter()

    def get_rules(self) -> list[Rule]:
        """Return the 3 Rule objects backing this handler's blocking behaviour."""
        return [_ESLINT_ERRORS_RULE, _ESLINT_TIMEOUT_RULE, _ESLINT_RUN_FAILURE_RULE]

    def _deny_reason(self, hook_input: dict[str, Any], rule: Rule, dynamic_detail: str) -> str:
        """Build a DENY reason, verbose-first/terse-after per (transcript_path, rule_id).

        Plan 00116, Decision G. This is a POST-hoc failure report -- the
        dynamic diagnostic (ESLint output, the failing command) must stay
        fully present in BOTH verbose and terse forms; only the surrounding
        teaching prose goes terse on repeat fires.
        """
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(transcript_path, rule.rule_id):
            message = self._formatter.terse(rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, rule.rule_id)
            message = self._formatter.verbose(rule)

        return f"{message}\n\n{dynamic_detail}"

    def _checkable_paths(self, hook_input: dict[str, Any]) -> list[str]:
        """TypeScript files this event authored, via any write route."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name == ToolName.BASH and not self._check_bash_writes:
            return []
        if tool_name not in [ToolName.WRITE, ToolName.EDIT, ToolName.BASH]:
            return []
        return [path for path in get_written_file_paths(hook_input) if self._is_checkable(path)]

    def _is_checkable(self, file_path: str) -> bool:
        """Whether one authored path is in scope for ESLint."""
        # Only check TypeScript/TSX files
        if not any(file_path.endswith(ext) for ext in self.VALIDATE_EXTENSIONS):
            return False

        # Skip build artifacts
        if matches_skip_path(file_path, self.SKIP_PATHS):
            return False

        # File must exist. A formality for Write/Edit; load-bearing for Bash,
        # where the target is PREDICTED from the command and a failed command
        # leaves nothing behind.
        return Path(file_path).exists()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if writing TypeScript/TSX file that needs validation."""
        return bool(self._checkable_paths(hook_input))

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Run ESLint on the file and block if errors found."""
        paths = self._checkable_paths(hook_input)
        if not paths:
            return BlockingResult(
                decision=Decision.ALLOW, reason="No file path found in hook input"
            )

        # One command can author several files; the first failure is reported,
        # matching how `handle` has always returned a single verdict.
        file_path = paths[0]
        file_path_obj = Path(file_path)

        # Advisory mode: no llm: commands in package.json - skip validation
        if not self.has_llm_commands:
            guide_path = get_llm_command_guide_path()
            return BlockingResult(
                decision=Decision.ALLOW,
                context=[
                    f"⚠️  ESLint advisory: {file_path_obj.name} written - consider adding llm:lint",
                    "No llm: commands in package.json. ESLint validation skipped.",
                    f"Full guide: {guide_path}",
                    f"⚠️  ADVISORY: Consider creating llm:lint for ESLint validation\n\n"
                    f"File written: {file_path_obj.name}\n\n"
                    f"RECOMMENDATION: Create llm:lint in package.json for automated validation\n"
                    f"  • Runs ESLint with JSON output to ./var/qa/eslint-cache.json\n"
                    f"  • Provides machine-readable results for jq queries\n"
                    f"  • Enables automated post-write validation\n\n"
                    f"Example package.json script:\n"
                    f'  "llm:lint": "eslint . --format json --output-file ./var/qa/eslint-cache.json '
                    f'&& eslint . --format compact"\n\n'
                    f"Full guide: {guide_path}\n\n"
                    f"ESLint validation skipped (no llm: commands detected in package.json).",
                ],
            )

        logger.info("Running ESLint validation on %s...", file_path_obj.name)

        # Check if this is a worktree file (either manually managed or Claude Code managed)
        is_worktree = any(
            f"{prefix}/" in file_path
            for prefix in (ProjectPath.WORKTREES_DIR, ProjectPath.CLAUDE_WORKTREES_DIR)
        )

        # Run ESLint using wrapper script
        try:
            command = [
                "tsx",
                "scripts/eslint-wrapper.ts",
                file_path,
                "--max-warnings",
                "0",
                "--human",
            ]
            cwd = str(self.workspace_root)

            # Prepend node_modules/.bin so tsx is resolvable even when the daemon
            # runs with a restricted system PATH (no node_modules/.bin included).
            env = os.environ.copy()
            bin_path = self.workspace_root / "node_modules" / ".bin"
            if bin_path.exists():
                env["PATH"] = str(bin_path) + os.pathsep + env.get("PATH", "")

            if is_worktree:
                logger.info("Detected worktree file - using ESLint wrapper for consistent config")

            result = (
                subprocess.run(  # nosec B603 - eslint/npx are trusted tools, file path validated
                    command,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=Timeout.ESLINT_CHECK,
                    env=env,
                )
            )

            if result.returncode != 0:
                error_message = (
                    f"ESLint validation FAILED for {file_path}\n\n"
                    + "=" * 80
                    + "\n"
                    + result.stdout
                    + "\n"
                )

                if result.stderr:
                    error_message += result.stderr + "\n"

                error_message += (
                    "=" * 80 + "\n\n"
                    "🚫 FILE WAS WRITTEN BUT HAS ESLINT ERRORS!\n"
                    "   You MUST fix these errors before continuing.\n\n"
                    f"   Run: npx eslint {file_path} --fix\n"
                    "   Or:  npm run lint -- --fix\n"
                )

                return BlockingResult(
                    decision=Decision.DENY,
                    reason=self._deny_reason(hook_input, _ESLINT_ERRORS_RULE, error_message),
                )

            logger.info("ESLint validation passed for %s", file_path_obj.name)
            return BlockingResult(decision=Decision.ALLOW)

        except subprocess.TimeoutExpired:
            return BlockingResult(
                decision=Decision.DENY,
                reason=self._deny_reason(
                    hook_input,
                    _ESLINT_TIMEOUT_RULE,
                    f"ESLint timed out after {Timeout.ESLINT_CHECK} seconds",
                ),
            )
        except Exception as e:
            return BlockingResult(
                decision=Decision.DENY,
                reason=self._deny_reason(
                    hook_input, _ESLINT_RUN_FAILURE_RULE, f"Failed to run ESLint: {e!s}"
                ),
            )

    def get_claude_md(self) -> str | None:
        return """## validate_eslint_on_write — TypeScript writes are ESLint-checked, and a failure DENIES

A `Write`/`Edit` to a `.ts` or `.tsx` file is run through ESLint. Reported
errors DENY the tool call.

**A Bash-authored `.ts`/`.tsx` file is checked too** — one written with `>`,
`>>`, `tee` or a `cat <<EOF` heredoc. A file the command merely RELOCATES
(`cp`, `mv`, `install`, `dd`) is not: those bytes were already on disk. Opt out
with `handlers.post_tool_use.validate_eslint_on_write.options.check_bash_writes:
false`, which leaves `Write`/`Edit` checking untouched.

**The write has ALREADY landed on disk.** The denial is a failure report, not
a rollback — the file exists with your content in it. Fix the reported problems
with `Edit` (`npx eslint <file> --fix` clears most of them), and re-issue any
sibling tool calls that were cancelled alongside the denied one.

**This is STRICTER than `lint_on_edit`, which covers the other languages.**
That handler ALLOWs when its linter is missing or when the check times out;
this one DENIES on an ESLint timeout and on any failure to run ESLint at all.
Do not carry "a missing linter never blocks" across to TypeScript.

**Enforcement is gated on `llm:` scripts in `package.json`.** With none
present this handler only advises — and suggests adding `llm:lint` — so silence
is not evidence that a `.ts` file is clean."""

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="ESLint validation on TypeScript file write",
                command=(
                    "Use the Write tool to create file /tmp/acceptance-test-eslint/test.ts "
                    'with content "const x = 1;"'
                ),
                description=(
                    "Triggers ESLint validation after writing TypeScript file. "
                    "If llm: commands exist in package.json, runs ESLint. "
                    "If not, returns advisory about creating llm:lint."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"ESLint", r"test\.ts"],
                safety_notes="Creates temporary TypeScript file in /tmp for validation testing",
                test_type=TestType.ADVISORY,
                setup_commands=["mkdir -p /tmp/acceptance-test-eslint"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-eslint"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="ESLint denies a Bash-authored TypeScript file",
                # A LITERAL shell command, not prose: the Bash write route made
                # this handler's surface machine-executable for the first time
                # (Plan 00260 Task 3.5). The sibling test above must stay prose
                # because it exercises the Write TOOL, which no shell command
                # can express.
                command=(
                    "mkdir -p /tmp/acceptance-test-eslint-bash && "
                    "cat > /tmp/acceptance-test-eslint-bash/broken.ts <<'EOF'\n"
                    "const x: number = ;\n"
                    "EOF"
                ),
                description=(
                    "A heredoc authoring invalid TypeScript is ESLint-checked and DENIED, "
                    "proving the Bash write route is no longer a way past this handler. "
                    "The write lands on disk first, so the denial is a failure report to "
                    "repair with Edit, not a rollback."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"broken\.ts"],
                safety_notes="Writes a temporary TypeScript file under /tmp; removed by cleanup",
                test_type=TestType.BLOCKING,
                setup_commands=["mkdir -p /tmp/acceptance-test-eslint-bash"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-eslint-bash"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
