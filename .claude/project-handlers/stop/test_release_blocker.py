"""Unit tests for ReleaseBlockerHandler (project-specific handler).

Tests the Stop event handler that blocks session ending while a release is in
flight.

The trigger is ``untracked/release-state.json``, NOT a dirty working tree.
RELEASING.md is unambiguous that the state file is the authority:

    No state file ⇒ no release is in progress. A dirty tree, a bumped
    version, or a plan saying "finish the release" is NOT a substitute.

The handler used to infer a release from modified version files, which is
exactly the inference that sentence forbids. Because the handler is
``terminal=True`` and DENIES, every false positive trapped the session until
the file was committed or the handler was disabled.
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.core import Decision

from .release_blocker import ReleaseBlockerHandler

#: Repo-relative folder the block message points the reader at. Relative on
#: purpose: it is joined to a root derived from ``__file__``, so the assertion
#: holds in this container, on a CI runner, and in any clone.
_CITED_PLAN_FOLDER = "CLAUDE/Plan/Completed/00060-release-blocker-handler"


def _write_state(root: Path, **fields: Any) -> Path:
    """Write a release-state file under ``root`` and return its path."""
    state: dict[str, Any] = {
        "version": "9.9.9",
        "authorised_by_human_at": "2026-01-01T00:00:00Z",
        "publish_authorised": False,
        "last_completed_step": 8,
    }
    state.update(fields)

    directory = root.joinpath(*ReleaseBlockerHandler.RELEASE_STATE_PARTS[:-1])
    directory.mkdir(parents=True, exist_ok=True)
    target = root.joinpath(*ReleaseBlockerHandler.RELEASE_STATE_PARTS)
    target.write_text(json.dumps(state), encoding="utf-8")
    return target


class TestReleaseBlockerHandlerInitialization:
    """Test handler initialization and configuration."""

    def test_handler_name(self) -> None:
        """Handler should have correct name."""
        handler = ReleaseBlockerHandler()
        assert handler.name == "release-blocker"

    def test_priority_is_below_the_terminal_auto_continue_stop(self) -> None:
        """The RELATION is the requirement; the number is an implementation detail.

        This test once asserted ``priority == 12`` with the rationale "before
        AutoContinueStop at 15". Both halves were true when written. When this
        project's config moved AutoContinueStop to 10, the relation broke and
        this handler became unreachable — and the test kept passing, because it
        pinned the number rather than the property. A test that asserts a
        constant cannot notice when the thing that constant was chosen against
        has moved.

        Reading the configured value keeps the two in step: change either and
        this fails.
        """
        import yaml

        config_path = Path(__file__).resolve().parents[3] / ".claude" / "hooks-daemon.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        auto_continue = config["handlers"]["stop"]["auto_continue_stop"]["priority"]

        handler = ReleaseBlockerHandler()

        assert handler.priority < auto_continue, (
            f"release-blocker is at priority {handler.priority}, but the terminal "
            f"auto_continue_stop is at {auto_continue}. The handler chain breaks at "
            "the first matching terminal handler, so this handler would never run — "
            "it would be silently disabled while still appearing in every handler "
            "listing. Lower this handler's priority, or reconsider the config."
        )

    def test_terminal_flag(self) -> None:
        """Handler should be terminal to prevent session ending."""
        handler = ReleaseBlockerHandler()
        assert handler.terminal is True


class TestTheStateFileIsTheAuthority:
    """A dirty tree is not evidence of a release; the state file is."""

    def test_a_dirty_tree_with_no_state_file_allows_the_stop(self, tmp_path: Path) -> None:
        """The false positive that motivated this change.

        Editing ``CHANGELOG.md`` or a published ``RELEASES/*.md`` to correct a
        factual error is ordinary work. The old trigger read those edits as
        "RELEASE IN PROGRESS" and, being terminal and DENY, trapped the session
        until they were committed. RELEASING.md names this exact inference as
        invalid.
        """
        (tmp_path / "CHANGELOG.md").write_text("dirty\n", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text("dirty\n", encoding="utf-8")

        handler = ReleaseBlockerHandler()

        with patch.object(ReleaseBlockerHandler, "_project_root", return_value=str(tmp_path)):
            assert handler.matches({}) is False

    def test_the_state_file_blocks_the_stop_even_with_a_clean_tree(self, tmp_path: Path) -> None:
        """Coverage the old trigger never had.

        After Step 13 commits and pushes, the tree is CLEAN while tagging and
        publishing remain — the most irreversible part of the release. A
        dirty-tree trigger goes blind at precisely that point; the state file
        does not, because it survives until Step 15 verification succeeds.
        """
        _write_state(tmp_path, last_completed_step=13, publish_authorised=True)

        handler = ReleaseBlockerHandler()

        with patch.object(ReleaseBlockerHandler, "_project_root", return_value=str(tmp_path)):
            assert handler.matches({}) is True

    def test_the_working_tree_is_never_inspected(self, tmp_path: Path) -> None:
        """No subprocess, no git, no working-tree read.

        Pinned because the previous implementation shelled out to
        ``git status`` and its fail-safe swallowed every failure — so a broken
        invocation looked identical to "no release in progress". Removing the
        subprocess removes that whole failure mode; this test stops it coming
        back.
        """
        handler = ReleaseBlockerHandler()

        with patch.object(ReleaseBlockerHandler, "_project_root", return_value=str(tmp_path)):
            with patch("subprocess.run") as mock_run:
                handler.matches({})

        assert mock_run.call_count == 0, "the handler must not shell out to inspect the tree"


class TestStatePathResolutionNeverUsesProcessCwd:
    """The daemon's working directory is ``/``; it is never the project.

    The lesson is inherited from the git-scoping bug (Plan 00237): a path this
    handler resolves implicitly resolves to the wrong place, and the fail-safe
    then makes the mistake look like "nothing to report".
    """

    def test_the_project_root_is_preferred_over_the_event_cwd(self, tmp_path: Path) -> None:
        """The state file belongs to the PROJECT, not to the session's cwd.

        A session can be cwd'd into a subdirectory or an agent worktree, whose
        ``untracked/`` is not where ``/release`` wrote the state file.
        """
        _write_state(tmp_path)
        elsewhere = tmp_path / "worktree"
        elsewhere.mkdir()

        handler = ReleaseBlockerHandler()

        with patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root",
            return_value=tmp_path,
        ):
            assert handler.matches({"cwd": str(elsewhere)}) is True

    def test_the_event_cwd_is_the_fallback_when_no_context_exists(self, tmp_path: Path) -> None:
        """Without an initialised ProjectContext the event's cwd is all there is."""
        _write_state(tmp_path)

        handler = ReleaseBlockerHandler()

        with patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root",
            side_effect=RuntimeError("not initialised"),
        ):
            assert handler.matches({"cwd": str(tmp_path)}) is True

    def test_no_resolvable_root_allows_the_stop(self) -> None:
        """Fail-safe: never trap a session because the project could not be found."""
        handler = ReleaseBlockerHandler()

        with patch.object(ReleaseBlockerHandler, "_project_root", return_value=None):
            assert handler.matches({}) is False


class TestUnfinishedReleaseAlwaysBlocks:
    """The human's `/release` invocation is the ONLY authorisation there is.

    Owner ruling (v3.57.0 release): there is no secondary human publish gate.
    The pipeline's blocking gates decide whether the release passes or fails,
    and once prep is complete the correct next action is to PROCEED to tag and
    publish — never to stop and ask. So an unfinished release blocks the Stop
    at EVERY recorded step until Step 15 verification deletes the state file.

    A legacy `publish_authorised` field in an old state file is ignored — its
    value, its type, and its absence all mean the same thing: keep going.
    """

    def test_prep_complete_step_blocks_the_stop(self, tmp_path: Path) -> None:
        """After Step 13 the remaining work is tag + publish — proceed, not ask."""
        _write_state(tmp_path, last_completed_step=13, publish_authorised=False)

        handler = ReleaseBlockerHandler()

        with patch.object(ReleaseBlockerHandler, "_project_root", return_value=str(tmp_path)):
            assert handler.matches({}) is True

    def test_a_prep_step_blocks_the_stop(self, tmp_path: Path) -> None:
        """Prep steps proceed on the state file's authority alone, so keep guarding."""
        _write_state(tmp_path, last_completed_step=12, publish_authorised=False)

        handler = ReleaseBlockerHandler()

        with patch.object(ReleaseBlockerHandler, "_project_root", return_value=str(tmp_path)):
            assert handler.matches({}) is True

    def test_a_legacy_authorisation_field_is_ignored(self, tmp_path: Path) -> None:
        """Whatever an old state file says, the release still has to be finished."""
        for legacy_value in (True, False, "false"):
            _write_state(tmp_path, last_completed_step=13, publish_authorised=legacy_value)

            handler = ReleaseBlockerHandler()

            with patch.object(ReleaseBlockerHandler, "_project_root", return_value=str(tmp_path)):
                assert handler.matches({}) is True, f"blocked regardless of {legacy_value!r}"

    def test_a_missing_authorisation_field_changes_nothing(self, tmp_path: Path) -> None:
        """The field is legacy; its absence is the normal, current shape."""
        state_path = _write_state(tmp_path, last_completed_step=13)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        del state["publish_authorised"]
        state_path.write_text(json.dumps(state), encoding="utf-8")

        handler = ReleaseBlockerHandler()

        with patch.object(ReleaseBlockerHandler, "_project_root", return_value=str(tmp_path)):
            assert handler.matches({}) is True

    def test_a_missing_step_counter_is_treated_as_prep(self, tmp_path: Path) -> None:
        """Unknown progress means the release is unfinished, so guard it.

        This is the safe direction in both senses: the guard stays active, and
        the session is not trapped, because prep can still be carried forward.
        """
        state_path = _write_state(tmp_path)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        del state["last_completed_step"]
        state_path.write_text(json.dumps(state), encoding="utf-8")

        handler = ReleaseBlockerHandler()

        with patch.object(ReleaseBlockerHandler, "_project_root", return_value=str(tmp_path)):
            assert handler.matches({}) is True


class TestMalformedStateFallsToTheGuardActiveSide:
    """Content that parses but does not conform keeps the guard ON.

    That direction is safe only because two other properties hold, and both are
    worth stating: prep can always be carried forward, so a DENY leaves the
    agent something to do; and `stop_hook_active` short-circuits re-entry, so a
    denied Stop costs one turn rather than trapping the session.

    Unreadable or unparseable content is different — there the handler cannot
    tell a release from a stray file, so it stands down. See TestFailSafe.
    """

    def test_an_empty_state_object_is_a_release_in_flight(self, tmp_path: Path) -> None:
        """`{}` is valid JSON and its PRESENCE is the signal.

        RELEASING.md: "State file present => a release IS authorised." The file
        carries no version and no step, but the fact of it is what the document
        makes load-bearing, so the guard holds.
        """
        directory = tmp_path.joinpath(*ReleaseBlockerHandler.RELEASE_STATE_PARTS[:-1])
        directory.mkdir(parents=True, exist_ok=True)
        tmp_path.joinpath(*ReleaseBlockerHandler.RELEASE_STATE_PARTS).write_text(
            "{}", encoding="utf-8"
        )

        handler = ReleaseBlockerHandler()

        with patch.object(ReleaseBlockerHandler, "_project_root", return_value=str(tmp_path)):
            assert handler.matches({}) is True

    def test_a_string_step_counter_keeps_the_guard_on(self, tmp_path: Path) -> None:
        """`"13"` is not an int, so it cannot be compared against the boundary."""
        _write_state(tmp_path, last_completed_step="13", publish_authorised=False)

        handler = ReleaseBlockerHandler()

        with patch.object(ReleaseBlockerHandler, "_project_root", return_value=str(tmp_path)):
            assert handler.matches({}) is True

    def test_a_float_step_counter_keeps_the_guard_on(self, tmp_path: Path) -> None:
        """`13.0` reads as prep-complete to a human but is not an int.

        Pinned so the behaviour is deliberate rather than incidental: a JSON
        writer emitting a float here is malformed, and the guard-active side is
        the side that cannot lose a release.
        """
        _write_state(tmp_path, last_completed_step=13.0, publish_authorised=False)

        handler = ReleaseBlockerHandler()

        with patch.object(ReleaseBlockerHandler, "_project_root", return_value=str(tmp_path)):
            assert handler.matches({}) is True


class TestFailSafe:
    """A guard that cannot read its evidence must never trap the session."""

    def test_a_malformed_state_file_allows_the_stop(self, tmp_path: Path) -> None:
        """Unparseable JSON is not evidence of a release."""
        directory = tmp_path.joinpath(*ReleaseBlockerHandler.RELEASE_STATE_PARTS[:-1])
        directory.mkdir(parents=True, exist_ok=True)
        tmp_path.joinpath(*ReleaseBlockerHandler.RELEASE_STATE_PARTS).write_text(
            "{not json", encoding="utf-8"
        )

        handler = ReleaseBlockerHandler()

        with patch.object(ReleaseBlockerHandler, "_project_root", return_value=str(tmp_path)):
            assert handler.matches({}) is False

    def test_a_non_object_state_file_allows_the_stop(self, tmp_path: Path) -> None:
        """Valid JSON that is not an object cannot carry the documented fields."""
        directory = tmp_path.joinpath(*ReleaseBlockerHandler.RELEASE_STATE_PARTS[:-1])
        directory.mkdir(parents=True, exist_ok=True)
        tmp_path.joinpath(*ReleaseBlockerHandler.RELEASE_STATE_PARTS).write_text(
            "[1, 2, 3]", encoding="utf-8"
        )

        handler = ReleaseBlockerHandler()

        with patch.object(ReleaseBlockerHandler, "_project_root", return_value=str(tmp_path)):
            assert handler.matches({}) is False

    def test_an_unreadable_state_file_allows_the_stop(self, tmp_path: Path) -> None:
        """An OS-level read failure is not evidence of a release either."""
        _write_state(tmp_path)

        handler = ReleaseBlockerHandler()

        with patch.object(ReleaseBlockerHandler, "_project_root", return_value=str(tmp_path)):
            with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
                assert handler.matches({}) is False


class TestReleaseBlockerHandlerMatches:
    """Loop prevention."""

    def test_matches_returns_false_when_stop_hook_active_snake_case(self) -> None:
        """Handler should not match when stop_hook_active=True (prevent infinite loops)."""
        handler = ReleaseBlockerHandler()
        assert handler.matches({"stop_hook_active": True}) is False

    def test_matches_returns_false_when_stop_hook_active_camel_case(self) -> None:
        """Handler should not match when stopHookActive=True (prevent infinite loops)."""
        handler = ReleaseBlockerHandler()
        assert handler.matches({"stopHookActive": True}) is False


class TestTheAbortRouteIsReachable:
    """A failed BLOCKING gate must not trap the session (Plan 00257 Task 3.1).

    RELEASING.md mandates ABORT on any failed gate, and the gates are Steps
    8-12 -- all below ``PREP_COMPLETE_STEP``. So on an abort the publish
    stand-down does not apply and this guard denies the Stop, while the agent's
    only correct move is to report the abort to a human. Found by living it.

    The mechanism out already existed: no state file means no release in
    flight, so deleting it releases the guard. Nothing SAID so. A guard whose
    escape hatch is undocumented is, for the agent hitting it, indistinguishable
    from one that has none -- it retries, gets denied again, and burns turns.

    The fix is deliberately the message and not ``matches()``. There is no
    signal in a Stop event that distinguishes "aborting a failed gate" from
    "avoiding the acceptance suite", and this handler exists specifically to
    stop the latter (see the example-context.md it cites). Detecting an abort
    would mean trusting the agent's own say-so about the one thing it is most
    motivated to misreport. Naming the route costs nothing and removes the trap;
    widening ``matches()`` would remove the guard.
    """

    def test_the_deny_text_names_the_abort_action(self) -> None:
        handler = ReleaseBlockerHandler()

        result = handler.handle({})

        assert "release-state.json" in result.reason, (
            "The deny text must name the state file as the thing to delete when "
            "aborting. Without it the agent is denied the Stop it needs to REPORT "
            "a failed gate, and has no stated way out."
        )
        assert "ABORT" in result.reason, (
            "RELEASING.md's word for a failed blocking gate is ABORT. The deny "
            "text must use it, or an agent reading the abort instruction in "
            "RELEASING.md will not connect it to this block."
        )

    def test_the_abort_route_is_not_offered_as_a_way_to_end_the_session(self) -> None:
        """Making the exit discoverable must not make it attractive.

        This handler was written because agents avoid acceptance testing. A
        message that says "delete this file to stop" without qualification
        converts the guard into an instruction for defeating itself.
        """
        handler = ReleaseBlockerHandler()

        result = handler.handle({})

        lowered = (result.reason or "").lower()
        assert "do not delete" in lowered or "not merely" in lowered, (
            "The deny text names the abort route but does not warn against using "
            "it simply to end the session. The guard exists to prevent exactly "
            "that, so the qualification is not optional."
        )

    def test_deleting_the_state_file_actually_releases_the_guard(self, tmp_path: Path) -> None:
        """The documented route must be the real one.

        Pins message and mechanism together: if resolution ever stops keying on
        the file's existence, the deny text becomes a lie and this fails.
        """
        handler = ReleaseBlockerHandler()
        state_path = tmp_path / "untracked" / "release-state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps({"version": "9.9.9", "last_completed_step": 8}))
        hook_input = {"cwd": str(tmp_path)}

        with patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root",
            return_value=tmp_path,
        ):
            assert handler.matches(hook_input) is True, "guard should be active mid-gate"

            state_path.unlink()

            assert handler.matches(hook_input) is False, (
                "Deleting the state file is the abort route named in the deny text, "
                "so it must release the guard."
            )


class TestReleaseBlockerHandlerHandle:
    """Test handler execution behavior."""

    def test_handle_returns_deny_decision(self) -> None:
        """Handler should return DENY decision to block session ending."""
        handler = ReleaseBlockerHandler()

        result = handler.handle({})

        assert result.decision == Decision.DENY

    def test_handle_returns_clear_reason_message(self) -> None:
        """Handler should return clear reason explaining why session is blocked."""
        handler = ReleaseBlockerHandler()

        result = handler.handle({})

        assert "RELEASE IN PROGRESS" in result.reason
        assert "acceptance tests" in result.reason
        assert "handlers.stop.release_blocker" in result.reason
        assert "enabled: false" in result.reason

    def test_handle_names_the_gate_rather_than_numbering_it(self) -> None:
        """The message cited "RELEASING.md Step 8" for acceptance testing.

        Step 8 is the QA Verification Gate; the Acceptance Testing Gate is Step
        12. The citation was wrong, and it was wrong in the way this file
        already warns about for the test count: a number copied out of a
        document drifts when the document moves, and nothing notices. Gate
        NAMES do not renumber.
        """
        handler = ReleaseBlockerHandler()

        result = handler.handle({})

        assert "Acceptance Testing Gate" in result.reason
        assert "Step 8" not in result.reason

    def test_handle_does_not_assert_a_hardcoded_test_count(self) -> None:
        """A count copied into a block message drifts and then misleads.

        This message asserted "89 EXECUTABLE acceptance tests". The suite is
        described in RELEASING.md, which is the source of truth and moves
        without this file noticing — the same drift CLAUDE.md already records
        for the QA check count ("it drifted to '10' while the suite ran 13").
        Point at the document instead of restating its contents.
        """
        handler = ReleaseBlockerHandler()

        result = handler.handle({})

        assert "89" not in result.reason

    def test_handle_references_a_path_that_exists(self) -> None:
        """A block message must not send the reader to a moved file.

        The plan folder it cited was archived into ``Completed/``, so the path
        in the message stopped resolving. A block is only as useful as the next
        step it points at.
        """
        handler = ReleaseBlockerHandler()

        result = handler.handle({})

        # Derive the repo root from this file, never a hardcoded absolute path.
        # `/workspace` is true only inside this project's own container: on a CI
        # runner the checkout is at `/home/runner/work/<repo>/<repo>`, so a
        # literal `/workspace` made the guard assert on a directory that could
        # not exist and failed for a reason unrelated to what it tests. Same
        # defect class as Plan 00244.
        repo_root = Path(__file__).resolve().parents[3]
        cited = repo_root / _CITED_PLAN_FOLDER
        assert (
            cited.is_dir()
        ), f"the cited plan folder must exist for this assertion to mean anything: {cited}"
        assert result.reason is not None
        assert _CITED_PLAN_FOLDER in result.reason

    def test_handle_names_the_resume_point_from_the_state_file(self, tmp_path: Path) -> None:
        """RELEASING.md says to resume from ``last_completed_step``.

        The block is where that instruction is actually needed, so the message
        must carry the version and the step rather than describing the release
        in the abstract.
        """
        _write_state(tmp_path, version="4.1.2", last_completed_step=9)

        handler = ReleaseBlockerHandler()

        with patch.object(ReleaseBlockerHandler, "_project_root", return_value=str(tmp_path)):
            result = handler.handle({})

        assert "4.1.2" in result.reason
        assert "9" in result.reason
        assert "untracked/release-state.json" in result.reason
