"""NpmCommandHandler - enforces llm: prefixed npm commands and blocks direct npx usage.

When llm: commands exist in package.json, enforces their usage (DENY raw commands).
When llm: commands do NOT exist, allows with advisory about creating them.
"""

import re
from pathlib import Path
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler import WorkspaceScope
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.core.workspace import resolve_workspace
from claude_code_hooks_daemon.utils.guides import get_llm_command_guide_path
from claude_code_hooks_daemon.utils.npm import has_llm_commands_in_package_json
from claude_code_hooks_daemon.utils.path_exclusion import resolve_project_root

# A monorepo npm command is normally shaped `cd <workspace> && npm run <x>`:
# the hook's own `cwd` stays at the repo root, so honouring `cwd` alone would
# resolve no manifest and leave enforcement off for exactly the invocations
# that need it. Only a LEADING cd counts -- a cd later in a chain does not
# describe where the npm command ran.
_LEADING_CD_PATTERN = re.compile(
    r"""^\s*cd\s+(?:'(?P<sq>[^']+)'|"(?P<dq>[^"]+)"|(?P<bare>[^\s;&|]+))\s*(?:&&|;)"""
)

# Capture the FULL npm-run script token. Script names legitimately contain
# letters (any case), digits, colons, underscores and hyphens (e.g.
# "build_prod", "test123", "Build", "build:prod"). A narrower class would
# truncate the name (e.g. "build_prod" -> "build") and drive the wrong
# suggestion/echo. SINGLE SOURCE OF TRUTH for the npm-run match, used by both
# matches() and handle().
_NPM_RUN_SCRIPT_PATTERN = r"\bnpm\s+run\s+([A-Za-z0-9:_-]+)"

# Plan 00209 Task 1.4 (DBF audit): pipe_blocker's remediation-output defect
# (echoing unbounded matched text into a deny reason) is not unique to that
# handler. The piped-command branch below echoes the FULL raw command —
# which can be an arbitrarily long heredoc/one-liner that merely happens to
# contain both "npm run X" and a literal "|" — so it gets the same cap.
_MAX_ECHOED_COMMAND_CHARS = 300
_TRUNCATION_SUFFIX = "… [truncated]"


def _truncate_command(command: str) -> str:
    """Cap echoed command text (Task 1.3/1.4): the full text is rarely what
    makes a block actionable, and re-quoting a long command wastes context."""
    if len(command) <= _MAX_ECHOED_COMMAND_CHARS:
        return command
    return command[:_MAX_ECHOED_COMMAND_CHARS] + _TRUNCATION_SUFFIX


# 2 rules (Plan 00116): a piped npm/npx command and a raw non-llm: command are
# distinct deny shapes with distinct remedies, not the same concept.
_NPM_PIPED_RULE = Rule(
    rule_id=RuleID.NPM_PIPED_COMMAND,
    blocked="a piped `npm run`/`npx` command",
    why="Piping npm/npx commands is pointless — llm: cache files hold the full data",
    fix="Run the plain command, then query the cache file with jq",
    verbose=(
        "Piping npm/npx commands is pointless.\n\n"
        "PHILOSOPHY: llm: commands write to cache files in ./var/qa/\n"
        "Piping output to grep/awk/sed is ineffective because:\n"
        "  • Minimal stdout (summary only, not full data)\n"
        "  • Full data in JSON cache files\n"
        "  • Use jq to query cache files directly\n\n"
        "Cache files contain full machine-readable JSON - use jq!"
    ),
)
_NPM_NON_LLM_RULE = Rule(
    rule_id=RuleID.NPM_NON_LLM_COMMAND,
    blocked="a raw `npm run`/`npx` command when llm: wrappers exist",
    why="llm: commands provide LLM-friendly, machine-readable output",
    fix="Use the project's `npm run llm:*` equivalent instead",
    verbose=(
        "PHILOSOPHY: Claude should use llm: prefixed commands which provide:\n"
        "  • Minimal stdout (summary only)\n"
        "  • Verbose JSON logging to ./var/qa/ files\n"
        "  • Machine-readable output\n"
        "  • Caching system for performance\n\n"
        "The llm: commands create cache files you can read directly.\n"
        "No need for grep/awk/sed post-processing!"
    ),
)


class NpmCommandHandler(PreToolUseHandlerBase):
    """Enforce llm: prefixed npm commands and block direct npx tool usage."""

    # PROJECT-scoped: resolves the command's cwd via resolve_workspace()
    # (see CLAUDE/Code/WorkspaceResolution.md).
    workspace_scope: ClassVar[WorkspaceScope] = WorkspaceScope.PROJECT

    ALLOWED_COMMANDS: ClassVar[list[str]] = ["clean", "dev:permissive"]
    SUGGESTIONS: ClassVar[dict[str, str]] = {
        "build": "llm:build",
        "build:permissive": "llm:build:permissive",
        "lint": "llm:lint",
        "lint:fix": "llm:lint:fix",
        "type-check": "llm:type-check",
        "format": "llm:format",
        "format:check": "llm:format:check",
        "test": "llm:test",
        "test:smoke": "llm:browser-test (Playwright) or llm:test:smoke (fast TypeScript)",
        "qa": "llm:qa",
    }

    # Map npx tools to their npm run llm: equivalents
    NPX_TOOL_SUGGESTIONS: ClassVar[dict[str, str]] = {
        "tsc": "llm:type-check",
        "eslint": "llm:lint",
        "prettier": "llm:format:check",
        "cspell": "llm:spell-check",
        "playwright": "llm:test",
        "tsx": "npm run llm:* (if script has wrapper) or ask user which command",
    }

    def __init__(
        self,
        options: dict[str, Any] | None = None,
        project_root: Path | None = None,
    ) -> None:
        """
        Args:
            options: Config-driven handler options (unused here; kept for the
                shared handler-construction signature).
            project_root: Root to probe for `package.json` instead of
                `ProjectContext.project_root()`. A caller that has no live
                `ProjectContext` (e.g. a CLI command reading config files
                directly, Plan 00305 Task 1.1) passes this explicitly so
                construction never touches that singleton.
        """
        super().__init__(
            handler_id=HandlerID.NPM_COMMAND,
            priority=Priority.NPM_COMMAND,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.NPM,
                HandlerTag.NODEJS,
                HandlerTag.JAVASCRIPT,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )
        # The mode at the PROJECT ROOT, probed once. `handle()` never reads
        # this -- it re-decides per invocation from the command's own
        # workspace (Plan 00296). It survives only for `get_acceptance_tests()`,
        # which generates expectations with no hook input and so has no
        # command, no cwd, and no workspace to resolve.
        self.has_llm_commands: bool = has_llm_commands_in_package_json(project_root)
        self._formatter = RuleFormatter()

    def _workspace_root_for(self, hook_input: dict[str, Any], command: str) -> Path:
        """Resolve the workspace the npm command actually runs in.

        A monorepo holds several sibling Node workspaces, each with its own
        ``package.json``. Deciding the mode once against the git root makes
        this handler permanently inert on exactly the repository that went to
        the trouble of defining ``llm:`` wrappers -- enforcement downgrades to
        advisory and nothing says why.

        Two signals locate WHERE the command runs, in order of specificity: a
        leading ``cd <dir> &&``, then the hook's ``cwd``. That location is then
        resolved to a DECLARED project. A repository that declares nothing
        resolves to the project root, which is what the single-project path
        always returned -- so this is a no-op there.
        """
        resolved = resolve_project_root()
        project_root = Path(resolved) if resolved else None

        raw_cwd = hook_input.get(HookInputField.CWD)
        if raw_cwd:
            base = Path(raw_cwd)
        elif project_root is not None:
            base = project_root
        else:
            base = Path.cwd()

        cd_match = _LEADING_CD_PATTERN.match(command)
        if cd_match:
            target = Path(cd_match.group("sq") or cd_match.group("dq") or cd_match.group("bare"))
            base = target if target.is_absolute() else base / target

        # No initialised ProjectContext (unit tests, per resolve_project_root's
        # contract): treat the command's own location as the notional root, so
        # an unrelated formatting test does not depend on daemon bootstrap.
        fallback_root = project_root if project_root is not None else base
        return resolve_workspace(self._project_registry, base, fallback_root).root

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is an npm run or npx command that needs validation."""
        command = get_bash_command(hook_input)
        if not command:
            return False

        # Check if npm/npx command is being piped (grep, awk, sed, tee, etc.)
        # llm: commands write to cache files, so piping is pointless
        # Use lookbehind/lookahead to exclude || (logical OR) from matching as pipe
        pipe_match = re.search(r"\b(npm\s+run|npx)\s+[a-z:]+.*?\s*(?<!\|)\|(?!\|)", command)
        if pipe_match:
            return True  # Block ALL piped npm/npx commands (including llm:)

        # Check for npm run commands
        npm_match = re.search(_NPM_RUN_SCRIPT_PATTERN, command)
        if npm_match:
            npm_cmd = npm_match.group(1)
            # Only match if NOT already llm: command and NOT in whitelist
            return not npm_cmd.startswith("llm:") and npm_cmd not in self.ALLOWED_COMMANDS

        # Check for npx commands (tsc, eslint, prettier, etc.)
        npx_match = re.search(r"\bnpx\s+([a-z]+)", command)
        if npx_match:
            tool_name = npx_match.group(1)
            # Block all npx tools that have llm: equivalents
            return tool_name in self.NPX_TOOL_SUGGESTIONS

        return False

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Block non-llm npm commands, npx tools, and piped commands with suggestion."""
        command = get_bash_command(hook_input)
        if not command:
            return GatingResult(decision=Decision.ALLOW, reason="No command found in hook input")

        # Check if command is being piped (exclude || logical OR)
        pipe_match = re.search(r"\b(npm\s+run|npx)\s+([a-z:]+).*?\s*(?<!\|)\|(?!\|)", command)
        if pipe_match:
            pipe_match.group(1)
            cmd_name = pipe_match.group(2)
            dynamic_detail = (
                f"BLOCKED COMMAND:\n"
                f"  {_truncate_command(command)}\n\n"
                f"INSTEAD:\n"
                f"  1. Run: npm run llm:{cmd_name.replace('llm:', '')}\n"
                f"  2. Query cache with jq: jq '.results[] | select(.success == false)' "
                f"./var/qa/{{type}}-cache.json\n"
                f"  3. Use jq for filtering, counting, extracting data"
            )
            return GatingResult(
                decision=Decision.DENY,
                reason=self._deny_reason(hook_input, _NPM_PIPED_RULE, dynamic_detail),
            )

        # Check if it's npm run command
        npm_match = re.search(_NPM_RUN_SCRIPT_PATTERN, command)
        if npm_match:
            npm_cmd = npm_match.group(1)
            suggested = self.SUGGESTIONS.get(npm_cmd, "llm:qa")
            blocked_cmd = f"npm run {npm_cmd}"
        else:
            # Must be npx command
            npx_match = re.search(r"npx\s+([a-z]+)", command)
            if npx_match:
                tool_name = npx_match.group(1)
                suggested = self.NPX_TOOL_SUGGESTIONS.get(tool_name, "llm:qa")
                blocked_cmd = f"npx {tool_name}"
            else:
                # Fallback if pattern doesn't match
                return GatingResult(
                    decision=Decision.ALLOW, reason="Could not parse npm/npx command"
                )

        # Advisory mode: no llm: commands in this command's own workspace.
        # Decided per invocation, not once at construction: two sibling
        # workspaces in one repository can legitimately be in different modes.
        workspace_root = self._workspace_root_for(hook_input, command)
        if not has_llm_commands_in_package_json(workspace_root):
            guide_path = get_llm_command_guide_path()
            return GatingResult(
                decision=Decision.ALLOW,
                context=[
                    f"⚠️  ADVISORY: Consider creating llm: prefixed npm commands\n\n"
                    f"You're using: {blocked_cmd}\n\n"
                    f"RECOMMENDATION: Create llm: wrappers in package.json for better LLM integration\n"
                    f"  • Minimal stdout (summary only: exit code, counts, timing)\n"
                    f"  • Verbose JSON files in ./var/qa/ (optimized for jq queries)\n"
                    f"  • Machine-readable output (parse with jq, not grep/sed)\n\n"
                    f"Example package.json script:\n"
                    f'  "llm:{npm_cmd if npm_match else suggested}": '
                    f'"<tool> --format json --output-file ./var/qa/<tool>-cache.json"\n\n'
                    f"Full guide: {guide_path}\n\n"
                    f"This command will run for now, but consider adding llm: wrappers."
                ],
            )

        # Enforcement mode: llm: commands exist in package.json
        dynamic_detail = (
            f"BLOCKED COMMAND:\n  {blocked_cmd}\n\nUSE THIS INSTEAD:\n  npm run {suggested}"
        )

        return GatingResult(
            decision=Decision.DENY,
            reason=self._deny_reason(hook_input, _NPM_NON_LLM_RULE, dynamic_detail),
        )

    def get_rules(self) -> list[Rule]:
        """Return the 2 Rule objects backing this handler's blocking behaviour."""
        return [_NPM_PIPED_RULE, _NPM_NON_LLM_RULE]

    def _deny_reason(self, hook_input: dict[str, Any], rule: Rule, dynamic_detail: str) -> str:
        """Build a DENY reason, verbose-first/terse-after per (transcript_path, rule_id).

        Plan 00116, Decision G. The per-invocation diagnostic (the blocked
        command, the suggested replacement) is dynamic and always fully
        present -- only the surrounding "why llm: commands exist" teaching
        prose goes terse on repeat fires.
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

    def get_enforcement_status(self, project_root: Path) -> list[str]:
        """Advisory when ``project_root`` has no ``llm:`` scripts (Plan 00296 T4.1).

        Cheap: one ``package.json`` read via ``has_llm_commands_in_package_json``,
        the same probe ``handle()`` already runs per invocation — no extra cost.
        """
        if has_llm_commands_in_package_json(project_root):
            return []
        return [
            f"npm_command: llm-wrapper enforcement inactive at {project_root} "
            "(no llm: scripts found in package.json) — raw npm run/npx commands "
            "get an advisory only, not a DENY."
        ]

    def get_claude_md(self) -> str | None:
        return (
            "## npm_command — use llm: prefixed npm commands\n\n"
            "Direct `npm run` and `npx` commands are blocked or advised against. "
            "Projects with `llm:` prefixed scripts in `package.json` should use those instead.\n\n"
            "**Why**: `llm:` commands are configured for LLM-friendly output "
            "(no spinners, no colour codes, structured results).\n\n"
            "**Example**: Use `npm run llm:build` instead of `npm run build`.\n\n"
            "If no `llm:` commands exist in `package.json`, the handler operates "
            "in advisory mode (warns but does not block)."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Npm Command."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="npm command enforcement (llm: commands exist)",
                command='echo "npm run build"',
                description=(
                    "Blocks raw npm commands when llm: wrappers exist in package.json. "
                    "If this project has llm: scripts, expect DENY. "
                    "If not, expect ALLOW with advisory."
                ),
                expected_decision=Decision.DENY if self.has_llm_commands else Decision.ALLOW,
                expected_message_patterns=[r"llm:", r"npm"],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
