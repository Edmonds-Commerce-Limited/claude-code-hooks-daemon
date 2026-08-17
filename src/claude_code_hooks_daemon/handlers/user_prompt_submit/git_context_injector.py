"""GitContextInjectorHandler - injects git status context into user prompts."""

import time
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.git_repo import run_git

# Ceiling on how long an unchanged status may stay un-injected (Plan 00238
# Task 4.1). Change-detection alone has no floor under it: context can be
# compacted away, and the agent would then have no git context at all until the
# repository happened to change. Re-injecting on this interval bounds that.
_MAX_SUPPRESSION_SECONDS = 900.0

# The state is one small entry per session, and sessions share one daemon that
# runs for days, so the map is capped rather than left to grow. Oldest-first
# eviction: the sessions that stop prompting are the ones that are gone.
_MAX_TRACKED_SESSIONS = 32


class GitContextInjectorHandler(Handler):
    """Inject current git status as context when user submits a prompt.

    Provides awareness of repository state (branch, uncommitted changes) to help
    the agent make better decisions. Non-terminal to allow prompt processing.
    """

    def __init__(self) -> None:
        """Initialise handler as non-terminal context provider."""
        super().__init__(
            handler_id=HandlerID.GIT_CONTEXT_INJECTOR,
            priority=Priority.GIT_CONTEXT_INJECTOR,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.GIT,
                HandlerTag.CONTEXT_INJECTION,
                HandlerTag.NON_TERMINAL,
            ],
        )
        # session id -> (payload last injected for it, monotonic stamp).
        # Per-instance: the daemon holds one handler, so this lives as long as
        # the daemon and is not shared across projects.
        self._last_injected: dict[str, tuple[str, float]] = {}

    def _now(self) -> float:
        """Return a monotonic timestamp (seam for deterministic tests)."""
        return time.monotonic()

    def _should_inject(self, session_id: str, payload: str) -> bool:
        """Record ``payload`` for ``session_id`` and say whether to send it.

        Injects when the payload differs from the one this session last
        received, or when the last injection is older than
        ``_MAX_SUPPRESSION_SECONDS``.
        """
        now = self._now()
        previous = self._last_injected.get(session_id)
        unchanged = previous is not None and previous[0] == payload
        fresh = previous is not None and now - previous[1] < _MAX_SUPPRESSION_SECONDS
        if unchanged and fresh:
            return False

        if session_id not in self._last_injected and len(self._last_injected) >= (
            _MAX_TRACKED_SESSIONS
        ):
            oldest = min(self._last_injected, key=lambda key: self._last_injected[key][1])
            del self._last_injected[oldest]
        self._last_injected[session_id] = (payload, now)
        return True

    def matches(self, _hook_input: dict[str, Any]) -> bool:
        """Match all user prompt submissions.

        Args:
            _hook_input: Hook input dictionary from Claude Code (unused)

        Returns:
            Always True (provide context for all prompts)
        """
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Inject git status as context, but only when it has something to say.

        The duty — git state informs decisions — is why this handler exists.
        Re-sending an unchanged payload on every prompt is not part of that
        duty: the agent already has the identical text from the previous
        prompt, so the second copy costs tokens and teaches nothing
        (Plan 00238 Task 4.1).

        Args:
            hook_input: Hook input dictionary from Claude Code

        Returns:
            HookResult with git status context, or a silent allow when git is
            unavailable or the status is unchanged since this session's last
            injection
        """
        try:
            project_root: str | None = str(ProjectContext.project_root())
        except RuntimeError:
            # ProjectContext not initialized (e.g. running without daemon) - use cwd as fallback
            project_root = None

        try:
            # Read the status WITHOUT taking git's optional index lock. This runs
            # on every prompt in the agent's own working tree, and a plain
            # `git status` refreshes the index and writes it back — so gathering
            # context would contend for `.git/index.lock` with whatever git
            # command the agent is running at that moment (Plan 00246).
            # cwd from ProjectContext (authoritative project root), or cwd fallback
            result = run_git(Path(project_root) if project_root else Path.cwd(), "status")

            # If git command failed (not a repo, git not installed, etc.), silent allow
            if result.returncode != 0:
                return HookResult(decision=Decision.ALLOW)

            # Build context message
            context = "Current git repository status:\n\n"
            context += result.stdout
            context += "\n---\n"
            context += "Consider this context when making changes to the repository."

            session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or "")
            if not self._should_inject(session_id, context):
                return HookResult(decision=Decision.ALLOW)

            return HookResult(decision=Decision.ALLOW, context=[context])

        except OSError:
            # `run_git` reports an absent git or a timeout as a non-zero
            # returncode rather than raising, so the only thing left that can
            # raise here is resolving the fallback cwd — silent allow either way.
            return HookResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="git context injector handler test",
                command='echo "test"',
                description="Tests git context injector handler functionality",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="UserPromptSubmit event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
