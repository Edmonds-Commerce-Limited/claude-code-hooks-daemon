"""HookRegistrationCheckerHandler - validate hook registrations on session start.

Checks that all expected hook event types are registered in .claude/settings.json
and detects duplicate registrations across settings.json and settings.local.json.

Runs only on new sessions (not resumes). Advisory only — never blocks.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs
from claude_code_hooks_daemon.utils.hook_command_migration import (
    MigrationResult,
    migrate_settings_to_bash_invocation,
)
from claude_code_hooks_daemon.utils.hook_registration import (
    detect_duplicate_hooks,
    detect_legacy_hook_commands,
    detect_local_hooks_misplacement,
    validate_hook_commands,
    validate_settings_hooks,
)
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session
from claude_code_hooks_daemon.utils.settings_repair import (
    RepairResult,
    repair_settings_registrations,
)

logger = logging.getLogger(__name__)

# Settings file names
_SETTINGS_FILE = "settings.json"
_SETTINGS_LOCAL_FILE = "settings.local.json"
_CLAUDE_DIR = ".claude"


class HookRegistrationCheckerHandler(SessionStartHandlerBase):
    """Validate hook registrations in Claude Code settings on session start.

    Checks:
    - All expected hook event types are registered in settings.json
    - No duplicate registrations across settings.json and settings.local.json
    - Hook commands point to the correct scripts

    Advisory only — reports issues as context, never blocks.
    """

    def __init__(self) -> None:
        """Initialise the hook registration checker handler."""
        super().__init__(
            handler_id=HandlerID.HOOK_REGISTRATION_CHECKER,
            priority=Priority.HOOK_REGISTRATION_CHECKER,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.WORKFLOW,
                HandlerTag.NON_TERMINAL,
                HandlerTag.ENVIRONMENT,
            ],
        )
        # Plan 00102 Phase 2: auto-migrate legacy bare-path commands to
        # ``bash <path>`` form on first new session after upgrade. Opt-out
        # via .claude/hooks-daemon.yaml:
        #   handlers.session_start.hook_registration_checker.options.auto_migrate_settings: false
        #
        # Plan 00185 Phase 2: auto-repair MISSING wired hook registrations by
        # merging them (SSoT-derived) into settings.json. This is what lets an
        # already-installed project stop the "Missing hook registration" flood on
        # its next session without a reinstall. Opt-out via:
        #   handlers.session_start.hook_registration_checker.options.auto_repair_registrations: false
        self.config: dict[str, Any] = {
            "auto_migrate_settings": True,
            "auto_repair_registrations": True,
        }

    def configure(self, config: dict[str, Any]) -> None:
        """Apply per-handler config from the daemon's config loader."""
        self.config.update(config)

    def _get_project_root(self) -> Path | None:
        """Get the project root directory.

        Returns:
            Project root path or None if unavailable
        """
        try:
            return ProjectContext.project_root()
        except RuntimeError as exc:
            logger.debug("Cannot determine project root: %s", exc)
            return None

    def _read_json_file(self, path: Path) -> dict[str, Any]:
        """Read and parse a JSON file.

        Args:
            path: Path to JSON file

        Returns:
            Parsed dict or empty dict on any error
        """
        try:
            if not path.exists():
                return {}
            with path.open() as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            return {}
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.debug("Failed to read %s: %s", path, exc)
            return {}

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Only match on new sessions (not resumes).

        Args:
            hook_input: Hook input dictionary

        Returns:
            True for new sessions, False for resumed sessions
        """
        return not is_resume_session(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Validate hook registrations and report issues.

        Args:
            hook_input: Hook input dictionary

        Returns:
            AdvisoryResult with ALLOW decision and advisory context
        """
        project_root = self._get_project_root()
        if project_root is None:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

        claude_dir = project_root / _CLAUDE_DIR

        # Plan 00102 Phase 2: rewrite legacy bare-path command entries to
        # ``bash <path>`` form before auditing. Migration is idempotent and
        # only writes when at least one entry actually needs rewriting; the
        # audit below sees the post-migration shape.
        migration_result: MigrationResult | None = None
        if self.config.get("auto_migrate_settings", True):
            try:
                migration_result = migrate_settings_to_bash_invocation(claude_dir / _SETTINGS_FILE)
            except OSError as exc:
                logger.warning("Hook command migration aborted: %s", exc)
                migration_result = None

        # Plan 00185 Phase 2: self-heal — add any MISSING wired hook
        # registrations to settings.json (SSoT-derived merge, additive and
        # idempotent) BEFORE the audit below, so the audit sees the repaired
        # shape and the flood stops on this very session. Fail-safe: any
        # read/write error leaves the file untouched and the audit still warns.
        repair_result: RepairResult | None = None
        if self.config.get("auto_repair_registrations", True):
            try:
                repair_result = repair_settings_registrations(claude_dir / _SETTINGS_FILE)
            except OSError as exc:
                logger.warning("Hook registration repair aborted: %s", exc)
                repair_result = None

        # Read settings files
        settings = self._read_json_file(claude_dir / _SETTINGS_FILE)
        local_settings = self._read_json_file(claude_dir / _SETTINGS_LOCAL_FILE)

        # Skip if no settings.json at all (not a hooks daemon project)
        if not settings:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

        # Run all validations
        all_issues: list[str] = []
        all_issues.extend(validate_settings_hooks(settings))
        all_issues.extend(detect_duplicate_hooks(settings, local_settings))
        all_issues.extend(detect_local_hooks_misplacement(local_settings))
        all_issues.extend(validate_hook_commands(settings))
        all_issues.extend(detect_legacy_hook_commands(settings))
        all_issues.extend(detect_legacy_hook_commands(local_settings))

        # Build context
        lines: list[str] = []
        if migration_result is not None and migration_result.migrated:
            events_str = ", ".join(migration_result.events_migrated)
            lines.append(
                "HOOK COMMAND MIGRATION: Rewrote legacy bare-path entries to "
                f"`bash <path>` form ({events_str}). "
                f"Original saved to {_SETTINGS_FILE}{'.bak.pre-bash-migration'} "
                "for rollback. This makes hooks resilient to dropped exec bits "
                "(see Plan 00102)."
            )
            lines.append("")
        if repair_result is not None and repair_result.repaired:
            added_str = ", ".join(repair_result.events_added)
            backup_note = (
                f"Original saved to {repair_result.backup_path.name}"
                if repair_result.backup_path is not None
                else "an existing backup was preserved"
            )
            lines.append(
                "HOOK REGISTRATION REPAIR: Added "
                f"{len(repair_result.events_added)} missing hook registration(s) "
                f"to {_SETTINGS_FILE} ({added_str}). {backup_note}. These are "
                "wired passthrough events the daemon expects (Plan 00170); "
                "adding them stops the recurring session-start registration "
                "warnings without a reinstall (see Plan 00185)."
            )
            lines.append("")
        # Lean SessionStart (Plan 00128): stay silent when the configuration is
        # clean — only speak when there are issues to fix (a migration notice,
        # emitted above, also counts as actionable output).
        if all_issues:
            lines.append(f"HOOK REGISTRATION: {len(all_issues)} issue(s) found")
            lines.append("")
            for issue in all_issues:
                lines.append(f"  WARNING: {issue}")
            lines.append("")
            lines.append(
                "Fix: Consolidate ALL hooks into .claude/settings.json "
                "(remove any hooks entries from .claude/settings.local.json). "
                "For legacy-style scripts, port them to project-level handlers "
                "via `init-project-handlers`."
            )

        return AdvisoryResult(decision=Decision.ALLOW, context=lines)

    def get_claude_md(self) -> str | None:
        """Return agent-facing remediation guidance for hook-config drift."""
        return (
            "## hook_registration_checker — hooks configuration policy\n"
            "\n"
            "On every new session this handler audits hook configuration "
            "across `.claude/settings.json` and `.claude/settings.local.json`. "
            "When it reports issues, fix them — do not ignore the warning.\n"
            "\n"
            "### Policy\n"
            "\n"
            "1. **All hooks live in `settings.json`.** That file is tracked "
            "in version control, visible to teammates, and is the single "
            "source of truth for the daemon.\n"
            "2. **`settings.local.json` must contain ZERO `hooks` entries.** "
            "It exists for per-developer `permissions` and IDE state only. "
            "A `hooks` block there is either (a) invisible to the rest of "
            "the team, or (b) duplicated with `settings.json` — in which "
            "case the hook fires twice per event.\n"
            "3. **Hook commands must invoke the daemon wrapper.** Every "
            "registered `type: command` hook must end with "
            "`/.claude/hooks/{event}`. Anything else (inline Python, custom "
            "shell scripts, bespoke paths) is a legacy setup that bypasses "
            "the daemon entirely. This rule is about COMMAND hooks only: "
            "Claude Code's native `type: prompt` and `type: agent` hooks "
            "carry no command at all and are permitted, provided they sit "
            "ALONGSIDE the wrapper and never replace it — registration "
            "repair is additive per EVENT, so a wrapper that is removed is "
            "never restored and every handler on that event goes dark.\n"
            "\n"
            "### Remediation\n"
            "\n"
            "- **Hooks in `settings.local.json`**: move each `hooks` entry "
            "to `settings.json`, then delete the `hooks` key from "
            "`settings.local.json`. Confirm no duplicates remain.\n"
            "- **Legacy-style commands**: replace them with a project-level "
            "handler. Run "
            f"`{daemon_cli_command_for_docs('init-project-handlers')}` "
            "to scaffold `.claude/project-handlers/`, port the logic into "
            "a handler class, then restore the daemon wrapper in "
            "`settings.json`. The daemon will auto-discover the new handler "
            "on restart.\n"
            "- **Missing hooks**: by default this handler SELF-HEALS — it "
            "merges the full wired registration set into `settings.json` on "
            "session start (additive; preserves `permissions`/`env`/`statusLine` "
            "and any custom hooks; one-shot backup to "
            "`settings.json.bak.pre-registration-repair`), so the flood stops "
            "without a reinstall. Opt out with "
            "`handlers.session_start.hook_registration_checker.options."
            "auto_repair_registrations: false`, then re-run the installer or add "
            "the missing `{event_name}` entry manually.\n"
            "- **Duplicate hooks**: a hook registered in both files fires "
            "twice. Keep the `settings.json` entry and remove the duplicate in "
            "`settings.local.json`.\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="hook registration checker - validates hook settings",
                command='echo "test"',
                description="Validates hook registrations in settings.json on session start",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"HOOK REGISTRATION"],
                safety_notes="Advisory handler - warns but does not block",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session only)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
