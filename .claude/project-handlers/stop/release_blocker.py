"""ReleaseBlockerHandler - PROJECT-SPECIFIC handler for hooks-daemon releases.

This is a project-specific handler that enforces the hooks-daemon release workflow.
It detects when release files are modified and prevents Claude from stopping work
until acceptance tests are complete.

This handler is NOT shipped as a built-in handler - it's specific to this project.

Purpose: Enforce RELEASING.md Step 8 (BLOCKING GATE) - prevent AI agents from skipping
the mandatory 20-30 minute acceptance testing process.

Why This Exists: During v2.13.0 release, Claude repeatedly tried to skip acceptance
testing despite it being mandatory. Acceptance testing caught a real bug that would
have shipped. This handler enforces the workflow.

Priority: 12 (before AutoContinueStop at 15)
Terminal: True (blocks session ending when release detected)
"""

import subprocess
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants.tags import HandlerTag
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class ReleaseBlockerHandler(Handler):
    """Blocks Stop event during releases until acceptance tests complete.

    Detects release context by checking for modified version files (pyproject.toml,
    version.py, README.md, CHANGELOG.md, RELEASES/*.md). When release is detected,
    blocks session ending with clear message referencing RELEASING.md Step 8.

    Prevents infinite loops by checking stop_hook_active flag. Fails safely by
    allowing session end if git commands error or timeout.
    """

    # Release files that indicate release in progress
    RELEASE_FILES: ClassVar[set[str]] = {
        "pyproject.toml",
        "src/claude_code_hooks_daemon/version.py",
        "README.md",
        "CLAUDE.md",
        "CHANGELOG.md",
    }

    def __init__(self) -> None:
        """Initialize ReleaseBlockerHandler with priority 12 (before AutoContinueStop)."""
        super().__init__(
            name="release-blocker",
            priority=12,
            terminal=True,
            tags=[HandlerTag.WORKFLOW, HandlerTag.BLOCKING],
        )

    def matches(self, hook_input: dict) -> bool:
        """Check if handler should trigger.

        Args:
            hook_input: Stop event data

        Returns:
            True if release files are modified and not in infinite loop prevention
            False if no release context or stop_hook_active flag set
        """
        # 1. Prevent infinite loops - check both snake_case and camelCase variants
        if hook_input.get("stop_hook_active") or hook_input.get("stopHookActive"):
            return False

        # 2. Check for modified release files via git status
        try:
            result = subprocess.run(
                ["git", "status", "--short"],
                capture_output=True,
                text=True,
                timeout=Timeout.GIT_CONTEXT,
                check=False,
            )

            # Silent allow on git error
            if result.returncode != 0:
                return False

            # Parse git status output (format: "M  filename")
            for line in result.stdout.splitlines():
                if len(line) < 3:
                    continue

                # Extract filename (skip status characters)
                filename = line[3:].strip()

                # Check if any release file is modified
                if filename in self.RELEASE_FILES:
                    return True

                # Check for RELEASES/vX.Y.Z.md files
                if filename.startswith("RELEASES/v") and filename.endswith(".md"):
                    return True

            return False

        except (subprocess.TimeoutExpired, OSError):
            # Silent allow on error - don't block legitimate session ends due to env issues
            return False

    def handle(self, hook_input: dict) -> HookResult:
        """Block Stop event with clear message about acceptance testing requirement.

        Args:
            hook_input: Stop event data (unused in blocking logic)

        Returns:
            HookResult with DENY decision and explanation referencing RELEASING.md
        """
        reason = (
            "🚫 RELEASE IN PROGRESS: Cannot end session until acceptance tests complete\n\n"
            "Modified release files detected (pyproject.toml, version.py, README.md, "
            "CHANGELOG.md, or RELEASES/*.md).\n\n"
            "Per RELEASING.md Step 8 (BLOCKING GATE): You must execute all 89 EXECUTABLE "
            "acceptance tests before ending this session.\n\n"
            "See CLAUDE/Plan/00060-release-blocker-handler/example-context.md "
            "for examples of AI acceptance test avoidance behavior.\n\n"
            "To disable: handlers.stop.release_blocker (set enabled: false)"
        )
        return HookResult(decision=Decision.DENY, reason=reason)

    def get_acceptance_tests(self) -> list:
        """Return acceptance tests for this handler.

        Note: This handler is difficult to test in acceptance testing because:
        1. Stop event tests require Claude to naturally stop (not triggerable on demand)
        2. Handler triggers based on git status of release files
        3. During actual releases, we WANT the handler to block (that's the point)

        The handler is verified by:
        - Unit tests (comprehensive mocking of git status)
        - Integration tests (response format validation)
        - Daemon load verification (handler registers successfully)
        - Manual testing during actual releases
        """
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="Release blocker handler - verified by unit tests only",
                test_type=TestType.CONTEXT,
                command='echo "placeholder"',
                description=(
                    "This handler cannot be tested via acceptance testing because:\n"
                    "1. Stop events fire when Claude finishes responding (not triggerable)\n"
                    "2. Handler triggers on git status of release files\n"
                    "3. During releases, handler should block (testing would require "
                    "temporarily modifying release files)\n\n"
                    "Verified by: Unit tests + Integration tests + Daemon load"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Stop event handler - verified by unit/integration tests",
                requires_event="Stop event",
            ),
        ]
