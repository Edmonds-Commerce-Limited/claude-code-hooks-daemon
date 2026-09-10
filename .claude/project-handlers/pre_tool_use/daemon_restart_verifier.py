"""Daemon Restart Verifier — PROJECT-ONLY (Plan 00370).

Advises verifying the daemon can restart before a `git commit` in THIS
repository — the hooks daemon's own dogfooding check: a code change that
breaks the daemon (an import error, say) should not be committed blind.

Re-homed from the built-in `daemon_restart_verifier` handler. It never
belonged in the shared, cross-project library: `matches()` only ever fired
inside the hooks-daemon repository itself, so every OTHER project shipped a
handler that could not do anything for it. A project handler is scoped to
the project that declares it by construction — this FILE only exists in the
hooks-daemon repository's own `.claude/project-handlers/` tree, so the
built-in's `is_hooks_daemon_repo` git-remote check (a forked subprocess,
memoised per Plan 00155 T1) is replaced by a cheap sanity check: this
module's OWN path resolves to a checkout that still has the daemon's source
tree alongside it. A single stat() call, no fork, no memoisation needed.
"""

import re
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.core import (
    AcceptanceTest,
    Decision,
    GatingResult,
    RecommendedModel,
    TestType,
)
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase

# This file lives at <project_root>/.claude/project-handlers/pre_tool_use/,
# three directories below the project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

# A marker only the hooks-daemon repository's own checkout has.
_DAEMON_SOURCE_MARKER = "src/claude_code_hooks_daemon/version.py"


def _looks_like_the_daemon_repo(project_root: Path) -> bool:
    """True when ``project_root`` looks like the hooks-daemon's own checkout."""
    return (project_root / _DAEMON_SOURCE_MARKER).is_file()


class DaemonRestartVerifierHandler(PreToolUseHandlerBase):
    """Advise verifying the daemon restarts before a commit, in this repo."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="daemon-restart-verifier",
            # Every priority 10-23 slot is already taken by a built-in
            # safety handler in THIS project's config (destructive_git
            # through ask_user_question_blocker); 24 is the first free slot
            # after that cluster, verified by
            # tests/integration/test_project_handler_priority_collisions.py
            # rather than assumed.
            priority=24,
            terminal=False,  # Advisory - suggest verification but don't block
            tags=["project", "safety", "workflow", "advisory"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match `git commit` Bash commands, in this repository's own checkout."""
        if hook_input.get("tool_name") != "Bash":
            return False
        if not _looks_like_the_daemon_repo(_PROJECT_ROOT):
            return False
        tool_input = hook_input.get("tool_input")
        command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
        if not command:
            return False
        return bool(re.search(r"\bgit\s+commit\b", command))

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Nudge toward daemon restart verification before a commit.

        Deliberately a SINGLE short line, and nothing else. The commands and
        the rationale live in `get_claude_md()`, resident in CLAUDE.md for
        the whole session, so attaching a second copy to every commit would
        pay for the same advice twice.
        """
        return GatingResult(
            decision=Decision.ALLOW,
            context=["💡 RECOMMENDED: Verify daemon restart before committing"],
        )

    def get_claude_md(self) -> str | None:
        return (
            "## daemon_restart_verifier — restart the daemon before committing\n\n"
            "Before making a `git commit` in the hooks daemon repository, this "
            "project handler advises verifying that the daemon can restart "
            "successfully with the current code changes. This is advisory — it "
            "adds context but does not block the commit.\n\n"
            "**Why**: Unit tests alone don't catch import errors. A handler that "
            "fails to import silently disables protection without any test-time "
            "error. Daemon restart is the definitive check.\n\n"
            "**Run before committing** (in this repo only):\n"
            "`./bin/hooks-daemon restart` then verify status shows RUNNING."
        )

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return [
            AcceptanceTest(
                title="Daemon restart verification advisory",
                command="echo \"git commit -m 'test WIP'\"",
                dispatch_as_bash=True,
                description=(
                    "Suggests verifying daemon restart before git commits " "(advisory only)"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"RECOMMENDED", r"restart"],
                safety_notes="Uses echo - safe to test. Handler matches git commit in command string.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
