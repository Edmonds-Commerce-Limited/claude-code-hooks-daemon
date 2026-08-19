"""ReleaseBlockerHandler - PROJECT-SPECIFIC handler for hooks-daemon releases.

This is a project-specific handler that enforces the hooks-daemon release
workflow. It detects that a release is in flight and prevents Claude from
stopping work until the release is finished.

This handler is NOT shipped as a built-in handler - it's specific to this
project.

Purpose: enforce the Acceptance Testing Gate in RELEASING.md - prevent AI
agents from skipping the mandatory acceptance testing process.

Why This Exists: during the v2.13.0 release, Claude repeatedly tried to skip
acceptance testing despite it being mandatory. Acceptance testing caught a real
bug that would have shipped. This handler enforces the workflow.

## The trigger is the release state file, not the working tree

RELEASING.md designates `untracked/release-state.json` as the authority on
whether a release is in progress, and says so in terms that exclude the
alternative:

    No state file ⇒ no release is in progress. A dirty tree, a bumped
    version, or a plan saying "finish the release" is NOT a substitute.

This handler used to infer a release from modified version files - the exact
inference that sentence forbids. Because the handler is `terminal=True` and
DENIES, each false positive trapped the session until the offending file was
committed or the handler was switched off. Narrowing the file set twice did not
fix it, because the file set was never the problem: a working tree cannot
express intent, so no subset of it can answer the question being asked.

Reading the state file is also STRICTER at the point that matters. Once Step 13
has committed and pushed, the tree is clean while tagging and publishing remain
- the least reversible part of a release. A dirty-tree trigger is blind exactly
there. The state file survives until Step 15 verification succeeds, so the
guard covers the whole window.

The one place the guard must stand down is where RELEASING.md requires the
agent to stop: with prep complete and `publish_authorised` still false, the
only correct next action is to ask a human. Denying that Stop would forbid it.

WHAT THIS TRADES AWAY. RELEASING.md also documents a "Manual Release (Bypass
Skill)" sequence that writes no state file, and on that path this handler is
inert. That is accepted deliberately: `CLAUDE.md` forbids manual releases
outright, `/release` is required to write the state file as its FIRST action,
and building the guard around the forbidden path is precisely what produced
the false positives. A guard aimed at a path nobody may take costs real
sessions and protects nothing.

Resolving the project root before the event's `cwd` also closes a latent
trapped-OPEN case: an agent running in `.claude/worktrees/<name>/` has a cwd
whose `untracked/` is empty, so a cwd-first lookup would find no state file
during a genuine release and wave the session through.

Priority: 8 — BELOW this project's AutoContinueStop, which is terminal.

That number is not arbitrary and must not be raised. AutoContinueStop is
terminal and matches nearly every Stop event, so the chain breaks there: any
Stop handler with a higher priority number never runs at all. This handler once
sat at 12, chosen when the daemon's config template put AutoContinueStop at 15
— which the template still does. This project's `.claude/hooks-daemon.yaml`
sets it to 10 instead, and that made this handler unreachable, silently, for as
long as both values have disagreed. Nothing reported it, because a shadowed
handler and a handler that did not match look identical from outside: no output
either way.

`tests/integration/test_stop_chain_terminal_shadowing.py` now fails by name if
any Stop handler drifts back above the terminal one.

Terminal: True (blocks session ending when a release is in flight)
"""

import json
import logging
from pathlib import Path
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants.tags import HandlerTag
from claude_code_hooks_daemon.core import Decision, Handler, HookResult

logger = logging.getLogger(__name__)


class ReleaseBlockerHandler(Handler):
    """Blocks Stop event while a release is in flight.

    Detects release context by reading `untracked/release-state.json`, which
    `/release` writes as its first action and deletes only once the release is
    verified. When a release is in flight, blocks session ending with a message
    naming the version and the step to resume from.

    Prevents infinite loops by checking stop_hook_active. Fails safely by
    allowing the session to end whenever the state file is absent, unreadable
    or malformed — a guard that cannot read its evidence must never trap a
    session.
    """

    #: Location of the release state file, relative to the PROJECT ROOT.
    #: RELEASING.md gives this path literally; it is not the daemon's own
    #: untracked dir, which differs between self-install and client installs.
    RELEASE_STATE_PARTS: ClassVar[tuple[str, ...]] = ("untracked", "release-state.json")

    #: The step after which the remaining work is tagging and publishing.
    #: RELEASING.md gates those on an explicit human "yes, publish", so once
    #: this step is complete and authorisation is absent, stopping to ask is
    #: the REQUIRED action and must not be denied.
    PREP_COMPLETE_STEP: ClassVar[int] = 13

    _FIELD_VERSION: ClassVar[str] = "version"
    _FIELD_PUBLISH_AUTHORISED: ClassVar[str] = "publish_authorised"
    _FIELD_LAST_COMPLETED_STEP: ClassVar[str] = "last_completed_step"

    _UNKNOWN: ClassVar[str] = "unknown"

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
    def _project_root(hook_input: dict) -> str | None:
        """Resolve the project whose release state should be inspected.

        Prefers the daemon's own project root, and only then the `cwd` the
        event carries. That order is the opposite of what a working-tree check
        wants, and deliberately so: the state file belongs to the PROJECT, but
        a session's cwd can be a subdirectory or an agent worktree whose
        `untracked/` is not where `/release` wrote it.

        Never relies on the process working directory. The daemon is
        long-lived with a cwd of `/`, so anything resolved implicitly resolves
        outside the repository — the failure mode that once made this handler
        unable to fire at all.

        Returns None when neither source yields a root, which the caller treats
        as "cannot tell" and allows the stop.
        """
        try:
            from claude_code_hooks_daemon.core.project_context import ProjectContext

            return str(ProjectContext.project_root())
        except (RuntimeError, AttributeError) as exc:
            logger.debug(
                "release-blocker: no ProjectContext (%s), falling back to the event cwd", exc
            )

        cwd = hook_input.get("cwd")
        if isinstance(cwd, str) and cwd:
            return cwd

        return None

    def _read_release_state(self, hook_input: dict) -> dict[str, Any] | None:
        """Return the parsed release state, or None when no release is in flight.

        Every failure path returns None and logs. A missing file is the
        documented meaning of "no release in progress", so it is not an error
        and is not logged as one; an unreadable or malformed file IS worth
        saying out loud, because a guard that has stopped working must not look
        identical to a guard with nothing to report.
        """
        root = self._project_root(hook_input)
        if root is None:
            logger.warning("release-blocker: no project root resolved, allowing stop")
            return None

        state_path = Path(root).joinpath(*self.RELEASE_STATE_PARTS)

        try:
            raw = state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            logger.warning(
                "release-blocker: could not read %s (%s), allowing stop", state_path, exc
            )
            return None

        try:
            state = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning(
                "release-blocker: %s is not valid JSON (%s), allowing stop", state_path, exc
            )
            return None

        if not isinstance(state, dict):
            logger.warning(
                "release-blocker: %s does not contain a JSON object, allowing stop", state_path
            )
            return None

        return state

    def _is_awaiting_publish_authorisation(self, state: dict[str, Any]) -> bool:
        """True when the correct next action is to stop and ask a human.

        RELEASING.md gates tagging and publishing on an explicit human "yes,
        publish" and requires the agent to ask "every time, even inside an
        authorised `/release` run". Once prep is complete without that
        authorisation, denying the Stop would forbid the only permitted move.

        An absent or non-integer step counter is treated as prep still running:
        the guard stays active, and that cannot trap the session because prep
        can be carried forward.

        Only a real boolean counts as consent. ``bool()`` would not do here:
        ``bool("false")`` is True, so a STRING in that field would be read as
        authorisation granted, and the handler would go on denying the very Stop
        the agent needs in order to ask a human. Anything that is not a boolean
        is absence of consent — which is also the documented default.
        """
        step = state.get(self._FIELD_LAST_COMPLETED_STEP)
        if not isinstance(step, int):
            return False

        authorised = state.get(self._FIELD_PUBLISH_AUTHORISED)
        if not isinstance(authorised, bool):
            authorised = False

        return step >= self.PREP_COMPLETE_STEP and not authorised

    @staticmethod
    def _stopped_on_a_tool_error(hook_input: dict) -> bool:
        """True when the session stopped straight after a failed tool call.

        This guard is terminal at priority 8, so whatever it says is the ONLY
        thing the agent hears — it shadows `auto_continue_stop` at 10 entirely.
        That is correct for an ordinary stop, and wrong for this one: the
        tool-error branch answers with a specific, actionable directive (Read
        the file, then retry), and replacing it with "a release is in progress"
        tells the agent nothing about the error it just hit. Both handlers deny
        the stop, so standing down here costs the release nothing — the session
        continues either way, and this guard fires again on the next stop
        attempt, which by then carries no tool error.

        Reuses `get_transcript_reader` rather than re-parsing the transcript, so
        the two handlers cannot disagree about what "a tool error" means.
        """
        try:
            from claude_code_hooks_daemon.utils.stop_hook_helpers import get_transcript_reader
        except ImportError as exc:  # pragma: no cover - daemon always ships this
            logger.debug("release-blocker: no transcript helper (%s), staying active", exc)
            return False

        reader = get_transcript_reader(hook_input)
        if reader is None:
            return False
        return bool(reader.last_tool_result_was_error())

    def matches(self, hook_input: dict) -> bool:
        """Check if handler should trigger.

        Args:
            hook_input: Stop event data

        Returns:
            True if a release is in flight and the session must not end.
            False if no release state file exists, it cannot be read, the
            release is waiting on a human publish decision, or the
            stop_hook_active flag is set.
        """
        # Prevent infinite loops - check both snake_case and camelCase variants
        if hook_input.get("stop_hook_active") or hook_input.get("stopHookActive"):
            return False

        if self._stopped_on_a_tool_error(hook_input):
            logger.info("release-blocker: standing down so tool-error recovery can answer")
            return False

        state = self._read_release_state(hook_input)
        if state is None:
            return False

        if self._is_awaiting_publish_authorisation(state):
            logger.info(
                "release-blocker: release %s awaits human publish authorisation, allowing stop",
                state.get(self._FIELD_VERSION, self._UNKNOWN),
            )
            return False

        return True

    def handle(self, hook_input: dict) -> HookResult:
        """Block Stop event, naming the release and where to resume it.

        Args:
            hook_input: Stop event data, used to locate the release state file

        Returns:
            HookResult with DENY decision and explanation referencing RELEASING.md
        """
        state = self._read_release_state(hook_input) or {}
        version = state.get(self._FIELD_VERSION, self._UNKNOWN)
        last_step = state.get(self._FIELD_LAST_COMPLETED_STEP, self._UNKNOWN)

        state_file = "/".join(self.RELEASE_STATE_PARTS)

        reason = (
            "🚫 RELEASE IN PROGRESS: cannot end session while a release is unfinished\n\n"
            f"{state_file} records an authorised release of version {version}, "
            f"with last_completed_step: {last_step}. Resume from that step rather "
            "than restarting the release, and do not re-litigate whether it should "
            "happen — the file IS the authorisation.\n\n"
            "Per the Acceptance Testing Gate in RELEASING.md (BLOCKING): you must "
            "execute the full acceptance playbook, and all acceptance tests must "
            "pass, before ending this session. "
            "RELEASING.md is the source of truth for what that covers — generate "
            "the current set with `./bin/hooks-daemon generate-playbook` rather "
            "than trusting a count quoted here, which would drift.\n\n"
            "Abandoning a part-done release is its own broken state: version "
            "bumped, UNRELEASED/ directories moved, nothing tagged. Finish it, or "
            "revert it deliberately.\n\n"
            "The exception: if prep is complete and publish_authorised is still "
            "false, stopping to ask a human IS the required action and this "
            "handler stands down by itself.\n\n"
            "ABORTING a failed gate: RELEASING.md mandates ABORT on any failed "
            "BLOCKING gate, and those gates are Steps 8-12 — below the step at "
            "which this guard stands down, so it will keep denying the Stop you "
            f"need in order to REPORT the abort. The route out is to delete "
            f"{state_file}: with no state file there is no release in flight, "
            "which is exactly true once a release is abandoned. Then tell the "
            "human WHICH gate failed and what must be fixed, and say plainly "
            "that the release is ABORTED.\n\n"
            "Do NOT delete it merely to end the session. First try the cheaper "
            "move: most gate failures are yours to fix — fix, re-run the gate, "
            "and continue (the FAIL-FAST cycle restarts acceptance testing from "
            "the beginning by design). Deleting the file discards the recorded "
            "authorisation, so no later session can resume this release; it is "
            "the abort action, not a pause button.\n\n"
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
        2. Handler triggers on the presence of the release state file, which only
           `/release` should create
        3. During actual releases, we WANT the handler to block (that's the point)

        The handler is verified by:
        - Unit tests (state file present/absent/malformed, authorisation gate)
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
                    "2. Handler triggers on untracked/release-state.json, which only\n"
                    "   /release should create — synthesising one would assert an\n"
                    "   authorisation no human gave\n"
                    "3. During releases, handler should block (testing would require "
                    "temporarily faking release state)\n\n"
                    "Verified by: Unit tests + Integration tests + Daemon load"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Stop event handler - verified by unit/integration tests",
                requires_event="Stop event",
            ),
        ]
