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

Priority: 8 — BELOW this project's AutoContinueStop, which is terminal.

That number is not arbitrary and must not be raised. AutoContinueStop is
terminal and matches nearly every Stop event, so the chain breaks there: any
Stop handler with a higher priority number never runs at all. This handler
previously sat at 12, chosen when the daemon's config template put
AutoContinueStop at 15 — which the template still does. This project's
`.claude/hooks-daemon.yaml` sets it to 10 instead, and that made this handler
unreachable, silently, for as long as both values have disagreed. Nothing
reported it, because a shadowed handler and a handler that did not match look
identical from outside: no output either way.

`tests/integration/test_stop_chain_terminal_shadowing.py` now fails by name if
any Stop handler drifts back above the terminal one.

Terminal: True (blocks session ending when release detected)
"""

import logging
import subprocess
from typing import ClassVar

from claude_code_hooks_daemon.constants.tags import HandlerTag
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision, Handler, HookResult

logger = logging.getLogger(__name__)


class ReleaseBlockerHandler(Handler):
    """Blocks Stop event during releases until acceptance tests complete.

    Detects release context by checking for modified version files (pyproject.toml,
    version.py, README.md, CHANGELOG.md, RELEASES/*.md). When release is detected,
    blocks session ending with clear message referencing RELEASING.md Step 8.

    Prevents infinite loops by checking stop_hook_active flag. Fails safely by
    allowing session end if git commands error or timeout.
    """

    # Files whose modification genuinely means a release is under way.
    #
    # Deliberately NARROW (Plan 00234 finding H-1). `README.md` and `CLAUDE.md`
    # were once in this set and had to come out: this handler is terminal and
    # DENIES the Stop event, so an ordinary docs edit left uncommitted trapped
    # the session until the file was committed or the handler disabled.
    # `CLAUDE.md` was the worse of the two — the daemon REGENERATES and
    # auto-commits it, so the daemon could trap the session by its own routine
    # action.
    #
    # What remains is the set a release cannot avoid touching. A real release
    # edits README.md too, but always alongside a version file, so narrowing
    # costs no coverage — pinned by a test.
    RELEASE_FILES: ClassVar[set[str]] = {
        "pyproject.toml",
        "src/claude_code_hooks_daemon/version.py",
        "CHANGELOG.md",
    }

    def __init__(self) -> None:
        """Initialise with a priority BELOW the terminal AutoContinueStop.

        See the module docstring: anything above it is unreachable, and this
        handler spent that period silently disabled.
        """
        super().__init__(
            name="release-blocker",
            priority=8,
            terminal=True,
            tags=[HandlerTag.WORKFLOW, HandlerTag.BLOCKING],
        )

    @staticmethod
    def _repo_root(hook_input: dict) -> str | None:
        """Resolve the repository to inspect, never relying on process cwd.

        Prefers the ``cwd`` Claude Code sends with the event, since that is
        the session's actual working directory. Falls back to the daemon's
        own project root, which is correct for a single-project daemon and is
        the only option when the event carries no cwd.

        Returns None when neither is available, which the caller treats as
        "cannot tell" and allows the stop — a release guard must never trap a
        session because it could not locate the repository.
        """
        cwd = hook_input.get("cwd")
        if isinstance(cwd, str) and cwd:
            return cwd

        try:
            from claude_code_hooks_daemon.core.project_context import ProjectContext

            return str(ProjectContext.project_root())
        except (RuntimeError, AttributeError):
            return None

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

        # 2. Check for modified release files via git status.
        #
        # `git -C <root>`, never a bare `git status`. The daemon is a
        # long-lived process whose working directory is `/` — not the project
        # — so a bare invocation runs outside any repository, exits non-zero,
        # and is swallowed by the fail-safe below. That combination made this
        # handler unable to fire even once its priority was corrected: the
        # ordering bug hid a second bug behind it, and the fail-safe made both
        # look like "no release in progress".
        repo_root = self._repo_root(hook_input)
        if repo_root is None:
            logger.warning("release-blocker: no project root resolved, allowing stop")
            return False

        try:
            result = subprocess.run(
                ["git", "-C", repo_root, "status", "--short"],
                capture_output=True,
                text=True,
                timeout=Timeout.GIT_CONTEXT,
                check=False,
            )

            # Fail-safe: never trap a session because git misbehaved. Logged
            # rather than silent, so a handler that has stopped working says so
            # instead of looking exactly like a handler with nothing to report.
            if result.returncode != 0:
                logger.warning(
                    "release-blocker: git status failed in %s (rc=%d), allowing stop",
                    repo_root,
                    result.returncode,
                )
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
            "Modified release files detected (pyproject.toml, version.py, "
            "CHANGELOG.md, or RELEASES/*.md).\n\n"
            "Per RELEASING.md Step 8 (BLOCKING GATE): you must execute the full "
            "acceptance playbook before ending this session. RELEASING.md is the "
            "source of truth for what that covers — generate the current set with "
            "`./bin/hooks-daemon generate-playbook` rather than trusting a count "
            "quoted here, which would drift.\n\n"
            "See CLAUDE/Plan/Completed/00060-release-blocker-handler/example-context.md "
            "for examples of AI acceptance test avoidance behaviour.\n\n"
            "To disable: handlers.stop.release_blocker (set enabled: false)"
        )
        return HookResult(decision=Decision.DENY, reason=reason)

    def get_claude_md(self) -> str | None:
        return None

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
