"""Unit tests for the GoalInjectionHandler (Plan 00269).

RED-first TDD file. The handler detects a ``PLAN.md`` Write/Edit that is a
REAL TRANSITION to ``**Status**: In Progress`` (ledger 00466 N3) -- an Edit
whose replaced span never touched the Status line, or a Write that merely
rewrites an already-In-Progress plan, must emit nothing even though the
post-write file still reads In Progress (active plan dir only, never
``Completed/``). A genuine flip renders the configured goal lines with
validated placeholders, joins them into ONE physical line, and atomically
writes a ``<session>.goal-intent`` signal for the ccy PTY supervisor. Latched
once per ``(plan, session)`` per daemon process. Never blocks. Opt-in
(``get_default_enabled() -> False``).
"""

import json
from pathlib import Path
from typing import Any

import pytest
from tests.support.git_fixtures import run_git as _git

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.goal_injection import (
    _CLEAR_SUFFIX,
    _HEADER_TEXT,
    _LOGICAL_LINE_SEPARATOR,
    _MAX_JOINED_CHARS,
    _SIGNAL_SUBDIR,
    _SIGNAL_SUFFIX,
    _SOURCE_CLI,
    _SOURCE_STATUS_FLIP,
    GoalInjectionHandler,
    LivePlan,
    clear_goal_signal,
    render_combined_goal_line,
    render_goal_line,
    write_goal_signal,
)
from claude_code_hooks_daemon.utils.goal_ledger import LEDGER_FILENAME, GoalLedger

_PLAN_FOLDER = "00269-supervisor-goal-message-injection"
_PLAN_NUMBER = "00269"
_SESSION = "sess-abc-123"


def _plan_md(status: str = "In Progress") -> str:
    return (
        "# Plan 00269: supervisor goal message injection\n\n"
        f"**Status**: {status}\n**Created**: 2026-08-26\n\n## Overview\n\nBody.\n"
    )


class TestRenderGoalLine:
    def test_default_render_contains_header_and_work_line(self) -> None:
        joined = render_goal_line(_PLAN_NUMBER, "my title", f"CLAUDE/Plan/{_PLAN_FOLDER}")
        assert joined is not None
        assert joined.startswith(_HEADER_TEXT)
        assert f"Work on Plan {_PLAN_NUMBER}" in joined
        assert "my title" in joined
        assert _PLAN_FOLDER in joined

    def test_default_work_line_sanctions_a_total_block_stop(self) -> None:
        """The built-in work line must offer TWO terminal conditions —
        completion OR a total block — not completion alone.

        With only "until completion", a plan blocked on human input has no
        sanctioned stopping point: the agent tries to stop, the Stop-hook
        challenge cites the still-live goal, the agent re-engages, finds
        nothing to do, and loops. Naming the total block as a valid stop
        (and telling the agent to state it) is what breaks that loop.
        """
        joined = render_goal_line(_PLAN_NUMBER, "t", "CLAUDE/Plan/x")
        assert joined is not None
        assert "until complete" in joined  # completion is still an exit
        assert "totally blocked" in joined  # the second exit
        assert "valid stop" in joined  # a total block is a legitimate stop
        assert "state it" in joined  # stop and report the blocker (loop-breaker)

    def test_total_block_clause_survives_the_join_cap_for_realistic_inputs(self) -> None:
        """The loop-breaking clause lives at the tail, and the joined line is
        hard-truncated at the cap — so a long-but-realistic plan title/path
        must not push the clause off the end.
        """
        long_title = "a" * 60
        long_path = "CLAUDE/Plan/00282-some-fairly-long-plan-folder-name"
        joined = render_goal_line(_PLAN_NUMBER, long_title, long_path)
        assert joined is not None
        assert len(joined) <= _MAX_JOINED_CHARS
        assert "totally blocked" in joined
        assert "valid stop" in joined
        assert "state it" in joined

    def test_render_is_single_physical_line(self) -> None:
        joined = render_goal_line(_PLAN_NUMBER, "t", "CLAUDE/Plan/x")
        assert joined is not None
        assert "\n" not in joined
        assert "\r" not in joined

    def test_disabled_builtin_lines_absent_by_default(self) -> None:
        joined = render_goal_line(_PLAN_NUMBER, "t", "CLAUDE/Plan/x")
        assert joined is not None
        assert "standing authorisation" not in joined
        assert "code-review sub-agents" not in joined

    def test_builtin_line_enabled_by_id_without_restating_text(self) -> None:
        joined = render_goal_line(
            _PLAN_NUMBER,
            "t",
            "CLAUDE/Plan/x",
            raw_lines=[{"id": "subagents-encouraged", "enabled": True}],
        )
        assert joined is not None
        assert "standing authorisation" in joined

    def test_additive_project_line_appended(self) -> None:
        joined = render_goal_line(
            _PLAN_NUMBER,
            "t",
            "CLAUDE/Plan/x",
            raw_lines=[{"id": "motto", "text": "Reports go to {plan_path}/REPORTS/."}],
        )
        assert joined is not None
        assert "Reports go to CLAUDE/Plan/x/REPORTS/." in joined

    def test_additive_project_line_overrides_builtin_by_id(self) -> None:
        joined = render_goal_line(
            _PLAN_NUMBER,
            "t",
            "CLAUDE/Plan/x",
            raw_lines=[{"id": "work-until-complete", "text": "Custom work line."}],
        )
        assert joined is not None
        assert "Custom work line." in joined
        assert "totally blocked" not in joined  # the built-in default was replaced

    def test_replace_mode_uses_only_project_lines_but_keeps_header(self) -> None:
        joined = render_goal_line(
            _PLAN_NUMBER,
            "t",
            "CLAUDE/Plan/x",
            mode="replace",
            raw_lines=[{"id": "only", "text": "Only line."}],
        )
        assert joined is not None
        assert joined.startswith(_HEADER_TEXT)
        assert "Only line." in joined
        assert "totally blocked" not in joined  # replace mode dropped the built-in default

    def test_replace_mode_empty_yields_header_only(self) -> None:
        joined = render_goal_line(_PLAN_NUMBER, "t", "CLAUDE/Plan/x", mode="replace")
        assert joined == _HEADER_TEXT

    def test_header_not_overridable_even_by_id(self) -> None:
        joined = render_goal_line(
            _PLAN_NUMBER,
            "t",
            "CLAUDE/Plan/x",
            raw_lines=[{"id": "header", "text": "EVIL"}],
        )
        assert joined is not None
        assert joined.startswith(_HEADER_TEXT)
        assert "EVIL" not in joined

    def test_unknown_placeholder_skips_line(self) -> None:
        joined = render_goal_line(
            _PLAN_NUMBER,
            "t",
            "CLAUDE/Plan/x",
            raw_lines=[{"id": "bad", "text": "uses {nonexistent} token"}],
        )
        assert joined is not None
        assert "nonexistent" not in joined

    def test_invalid_plan_number_returns_none(self) -> None:
        assert render_goal_line("269", "t", "CLAUDE/Plan/x") is None
        assert render_goal_line("00269x", "t", "CLAUDE/Plan/x") is None

    def test_title_control_chars_stripped(self) -> None:
        joined = render_goal_line(_PLAN_NUMBER, "ti\x1btle\nx", "CLAUDE/Plan/x")
        assert joined is not None
        assert "\x1b" not in joined
        assert "\n" not in joined

    def test_joined_length_capped(self) -> None:
        long_lines = [{"id": f"l{i}", "text": "y" * 200} for i in range(6)]
        joined = render_goal_line(_PLAN_NUMBER, "t", "CLAUDE/Plan/x", raw_lines=long_lines)
        assert joined is not None
        assert len(joined) <= _MAX_JOINED_CHARS

    def test_logical_line_count_capped_pre_join(self) -> None:
        many = [{"id": f"l{i}", "text": f"line {i}"} for i in range(20)]
        joined = render_goal_line(_PLAN_NUMBER, "t", "CLAUDE/Plan/x", raw_lines=many)
        assert joined is not None
        # header + at most 7 more logical lines
        assert joined.count(_LOGICAL_LINE_SEPARATOR) <= 8

    def test_malformed_raw_line_entries_skipped(self) -> None:
        joined = render_goal_line(
            _PLAN_NUMBER,
            "t",
            "CLAUDE/Plan/x",
            raw_lines=["not-a-dict", {"text": "no id"}, {"id": "ok", "text": "Fine."}],
        )
        assert joined is not None
        assert "Fine." in joined


class TestRenderCombinedGoalLine:
    """Plan 00299: single live plan degrades byte-for-byte; N>1 combines."""

    def test_empty_list_returns_none(self) -> None:
        assert render_combined_goal_line([]) is None

    def test_single_plan_matches_render_goal_line_byte_for_byte(self) -> None:
        combined = render_combined_goal_line(
            [LivePlan(plan_number=_PLAN_NUMBER, plan_title="my title", plan_path="CLAUDE/Plan/x")]
        )
        single = render_goal_line(_PLAN_NUMBER, "my title", "CLAUDE/Plan/x")
        assert combined == single

    def test_two_plans_names_both_numbers(self) -> None:
        combined = render_combined_goal_line(
            [
                LivePlan(plan_number="00296", plan_title="a", plan_path="CLAUDE/Plan/00296-a"),
                LivePlan(plan_number="00298", plan_title="b", plan_path="CLAUDE/Plan/00298-b"),
            ]
        )
        assert combined is not None
        assert combined.startswith(_HEADER_TEXT)
        assert "00296" in combined
        assert "00298" in combined
        assert "Plan(s)" in combined

    def test_two_plans_sorted_regardless_of_input_order(self) -> None:
        first = render_combined_goal_line(
            [
                LivePlan(plan_number="00298", plan_title="b", plan_path="p"),
                LivePlan(plan_number="00296", plan_title="a", plan_path="p"),
            ]
        )
        second = render_combined_goal_line(
            [
                LivePlan(plan_number="00296", plan_title="a", plan_path="p"),
                LivePlan(plan_number="00298", plan_title="b", plan_path="p"),
            ]
        )
        assert first == second

    def test_invalid_plan_number_returns_none(self) -> None:
        assert (
            render_combined_goal_line(
                [
                    LivePlan(plan_number="00296", plan_title="a", plan_path="p"),
                    LivePlan(plan_number="bad", plan_title="b", plan_path="p"),
                ]
            )
            is None
        )

    def test_combined_line_is_single_physical_line_and_capped(self) -> None:
        combined = render_combined_goal_line(
            [
                LivePlan(plan_number="00296", plan_title="a", plan_path="p"),
                LivePlan(plan_number="00298", plan_title="b", plan_path="p"),
            ]
        )
        assert combined is not None
        assert "\n" not in combined
        assert len(combined) <= _MAX_JOINED_CHARS

    def test_project_line_still_applied_for_multi_plan(self) -> None:
        combined = render_combined_goal_line(
            [
                LivePlan(plan_number="00296", plan_title="a", plan_path="p"),
                LivePlan(plan_number="00298", plan_title="b", plan_path="p"),
            ],
            raw_lines=[{"id": "motto", "text": "Fixed motto."}],
        )
        assert combined is not None
        assert "Fixed motto." in combined


class TestWriteGoalSignal:
    @pytest.fixture(autouse=True)
    def mock_project_context(self, tmp_path: Path):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection."
                "ProjectContext.daemon_untracked_dir",
                classmethod(lambda cls: tmp_path),
            )
            self._untracked = tmp_path
            yield

    def _read(self, session_id: str) -> dict[str, Any]:
        path = self._untracked / _SIGNAL_SUBDIR / f"{session_id}{_SIGNAL_SUFFIX}"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_writes_schema_fields(self) -> None:
        path = write_goal_signal(_SESSION, _PLAN_NUMBER, "joined line", _SOURCE_STATUS_FLIP)
        assert path is not None and path.exists()
        data = self._read(_SESSION)
        assert data["session_id"] == _SESSION
        assert data["plan_number"] == _PLAN_NUMBER
        assert data["rendered_lines"] == ["joined line"]
        assert data["source"] == _SOURCE_STATUS_FLIP
        assert isinstance(data["ts"], float)

    def test_unsafe_session_chars_sanitised_in_filename(self) -> None:
        path = write_goal_signal("a/b c", _PLAN_NUMBER, "x", _SOURCE_STATUS_FLIP)
        assert path is not None
        assert path.name == f"a_b_c{_SIGNAL_SUFFIX}"

    def test_emitting_a_goal_drops_a_pending_clear_trigger(self) -> None:
        """A NEW goal must not be retracted by a clear the supervisor never ate.

        The exclusion between the two signals used to run one way only:
        ``clear_goal_signal`` unlinks ``.goal-intent``, but the writer left a
        pending ``.goal-clear`` in place. Both files could therefore coexist,
        and the supervisor's "goal wins, the clear waits a tick" precedence
        merely DEFERS the clear by one tick rather than resolving it — tick 1
        injects the new goal, tick 2 types ``/goal clear`` and retracts it.

        The window opens whenever one plan is retired and another started
        before the session next goes idle, which is ordinary workflow here.
        """
        assert clear_goal_signal(_SESSION) is True
        clear_path = self._untracked / _SIGNAL_SUBDIR / f"{_SESSION}{_CLEAR_SUFFIX}"
        assert clear_path.exists(), "precondition: a clear trigger is pending"

        path = write_goal_signal(_SESSION, _PLAN_NUMBER, "joined line", _SOURCE_STATUS_FLIP)

        assert path is not None and path.exists()
        assert not clear_path.exists(), (
            "a pending .goal-clear survived a new goal emission — the next idle "
            "tick would retract the goal that was just set"
        )

    def test_dropping_a_pending_clear_is_scoped_to_this_session(self) -> None:
        """Emitting for one session must not retract ANOTHER session's goal."""
        other = "other-session"
        assert clear_goal_signal(other) is True
        other_clear = self._untracked / _SIGNAL_SUBDIR / f"{other}{_CLEAR_SUFFIX}"
        assert other_clear.exists()

        write_goal_signal(_SESSION, _PLAN_NUMBER, "joined line", _SOURCE_STATUS_FLIP)

        assert other_clear.exists(), "another session's pending clear was consumed"


class TestGoalInjectionHandler:
    @pytest.fixture(autouse=True)
    def mock_project_context(self, tmp_path: Path):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection."
                "ProjectContext.daemon_untracked_dir",
                classmethod(lambda cls: tmp_path / "untracked"),
            )
            mp.setattr(
                "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection."
                "ProjectContext.project_root",
                classmethod(lambda cls: tmp_path),
            )
            self._untracked = tmp_path / "untracked"
            self._project = tmp_path
            yield

    @pytest.fixture
    def handler(self) -> GoalInjectionHandler:
        return GoalInjectionHandler()

    def _write_plan(self, status: str = "In Progress", folder: str = _PLAN_FOLDER) -> Path:
        plan_dir = self._project / "CLAUDE" / "Plan" / folder
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_file = plan_dir / "PLAN.md"
        plan_file.write_text(_plan_md(status), encoding="utf-8")
        return plan_file

    def _hook_input(self, file_path: Path, tool: str = "Write") -> dict[str, Any]:
        return {
            "tool_name": tool,
            "tool_input": {"file_path": str(file_path)},
            "session_id": _SESSION,
        }

    def _signal_path(self) -> Path:
        return self._untracked / _SIGNAL_SUBDIR / f"{_SESSION}{_SIGNAL_SUFFIX}"

    # ---- metadata -------------------------------------------------------

    def test_init_identity(self, handler: GoalInjectionHandler) -> None:
        assert handler.name == HandlerID.GOAL_INJECTION.display_name
        assert handler.priority == Priority.GOAL_INJECTION
        assert handler.terminal is False

    def test_default_disabled(self, handler: GoalInjectionHandler) -> None:
        assert handler.get_default_enabled() is False

    def test_get_claude_md_present(self, handler: GoalInjectionHandler) -> None:
        text = handler.get_claude_md()
        assert text is not None
        assert "goal_injection" in text

    def test_acceptance_tests_defined(self, handler: GoalInjectionHandler) -> None:
        assert handler.get_acceptance_tests()

    # ---- matches --------------------------------------------------------

    def test_matches_active_plan_write(self, handler: GoalInjectionHandler) -> None:
        plan = self._write_plan()
        assert handler.matches(self._hook_input(plan)) is True

    def test_matches_edit_tool(self, handler: GoalInjectionHandler) -> None:
        plan = self._write_plan()
        assert handler.matches(self._hook_input(plan, tool="Edit")) is True

    def test_plan_shaped_path_outside_the_project_does_not_match(
        self, handler: GoalInjectionHandler, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """Plan 00320 Task 2.1: the trigger is a project plan, not a SHAPE.

        The pattern is applied with ``search``, so any absolute path merely
        CONTAINING ``<plan_dir>/NNNNN-name/PLAN.md`` matched wherever it lived
        — and the rendered goal then re-pointed it at the PROJECT's plan dir.
        A scratch plan under /tmp therefore emitted a live operational goal
        naming a project path that does not exist, which is unsatisfiable: no
        work can complete a plan whose folder is absent. This is exactly how
        `CLAUDE/Plan/00099-test` reached the live ledger during the v3.60.0
        release, from an acceptance fixture writing under
        /tmp/acceptance-test-recovcron/.
        """
        outside = tmp_path_factory.mktemp("outside-project") / "CLAUDE" / "Plan" / "00099-test"
        outside.mkdir(parents=True)
        stray = outside / "PLAN.md"
        stray.write_text(_plan_md("In Progress"), encoding="utf-8")

        assert handler.matches(self._hook_input(stray)) is False

    def test_plan_shaped_path_outside_the_project_emits_no_signal(
        self, handler: GoalInjectionHandler, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """Belt and braces: even if handle() is reached directly, an
        out-of-project plan must not write a goal signal."""
        outside = tmp_path_factory.mktemp("outside-project") / "CLAUDE" / "Plan" / "00099-test"
        outside.mkdir(parents=True)
        stray = outside / "PLAN.md"
        stray.write_text(_plan_md("In Progress"), encoding="utf-8")

        result = handler.handle(self._hook_input(stray))

        assert result.decision == Decision.ALLOW
        assert not self._signal_path().exists()

    def test_unreadable_plan_logs_a_warning_and_emits_nothing(
        self, handler: GoalInjectionHandler, caplog: pytest.LogCaptureFixture
    ) -> None:
        """team-lead review-4-prep: _read_plan raises PlanUnreadable for a
        genuinely corrupt/non-UTF-8 file; handle() catches it explicitly,
        logs a WARNING, and emits nothing -- the documented fail-open
        branch for a file this handler cannot make sense of."""
        plan_dir = self._project / "CLAUDE" / "Plan" / _PLAN_FOLDER
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_file = plan_dir / "PLAN.md"
        plan_file.write_bytes(b"\xff\xfe\x00\x01not valid utf-8")

        with caplog.at_level("WARNING"):
            result = handler.handle(self._hook_input(plan_file))

        assert result.decision == Decision.ALLOW
        assert not self._signal_path().exists()
        assert "goal_injection" in caplog.text

    def test_matches_honours_non_default_plan_dir_from_facade(
        self, handler: GoalInjectionHandler
    ) -> None:
        """A project-configured plan_workflow.directory (via the ProjectLayout
        facade) is honoured for the trigger pattern, not the CLAUDE/Plan/
        literal (Plan 00288 Task 4.2)."""
        from claude_code_hooks_daemon.core.project_layout import ProjectLayout

        handler._project_layout = ProjectLayout(
            source_dirs=(),
            test_dirs=(),
            config_dirs=("config",),
            vendor_dirs=frozenset(),
            agent_docs_dir="CLAUDE",
            human_docs_dir="docs",
            plan_dir="Plans",
            plan_archive_dirs=("Completed",),
        )
        plan_dir = self._project / "Plans" / _PLAN_FOLDER
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_file = plan_dir / "PLAN.md"
        plan_file.write_text(_plan_md(), encoding="utf-8")
        assert handler.matches(self._hook_input(plan_file)) is True
        # The old default location no longer matches once a non-default
        # plan_dir is configured.
        default_plan = self._write_plan()
        assert handler.matches(self._hook_input(default_plan)) is False

    def test_no_match_completed_plan(self, handler: GoalInjectionHandler) -> None:
        plan_dir = self._project / "CLAUDE" / "Plan" / "Completed" / _PLAN_FOLDER
        plan_dir.mkdir(parents=True)
        plan = plan_dir / "PLAN.md"
        plan.write_text(_plan_md(), encoding="utf-8")
        assert handler.matches(self._hook_input(plan)) is False

    def test_no_match_non_plan_file(self, handler: GoalInjectionHandler) -> None:
        other = self._project / "notes.md"
        other.write_text("x", encoding="utf-8")
        assert handler.matches(self._hook_input(other)) is False

    def test_no_match_bash_tool(self, handler: GoalInjectionHandler) -> None:
        assert handler.matches({"tool_name": "Bash", "tool_input": {"command": "ls"}}) is False

    # ---- handle ---------------------------------------------------------

    def test_in_progress_write_produces_signal(self, handler: GoalInjectionHandler) -> None:
        plan = self._write_plan()
        result = handler.handle(self._hook_input(plan))
        assert result.decision == Decision.ALLOW
        data = json.loads(self._signal_path().read_text(encoding="utf-8"))
        assert data["plan_number"] == _PLAN_NUMBER
        assert data["source"] == _SOURCE_STATUS_FLIP
        assert len(data["rendered_lines"]) == 1
        joined = data["rendered_lines"][0]
        assert joined.startswith(_HEADER_TEXT)
        assert "\n" not in joined

    def test_non_in_progress_status_writes_nothing(self, handler: GoalInjectionHandler) -> None:
        plan = self._write_plan(status="Not Started")
        result = handler.handle(self._hook_input(plan))
        assert result.decision == Decision.ALLOW
        assert not self._signal_path().exists()

    def test_latch_once_per_plan_per_session(self, handler: GoalInjectionHandler) -> None:
        plan = self._write_plan()
        handler.handle(self._hook_input(plan))
        self._signal_path().unlink()
        handler.handle(self._hook_input(plan))
        assert not self._signal_path().exists()

    def test_latch_is_per_session(self, handler: GoalInjectionHandler) -> None:
        plan = self._write_plan()
        handler.handle(self._hook_input(plan))
        self._signal_path().unlink()
        other = self._hook_input(plan)
        other["session_id"] = "other-session"
        handler.handle(other)
        other_path = self._untracked / _SIGNAL_SUBDIR / f"other-session{_SIGNAL_SUFFIX}"
        assert other_path.exists()

    def test_latch_disabled_via_option_refires(self, handler: GoalInjectionHandler) -> None:
        """RV3-m6 makes a repeated Write to an already-ledgered-live plan
        route through the reassert path (itself now latched, RV3-m4), so a
        genuine Edit-based flip is used here to isolate what this test is
        actually about: the ``_once_per_plan_per_session`` OPTION governing
        the flip path's own latch, independent of either newer gate."""
        handler._once_per_plan_per_session = False
        plan = self._write_plan()
        flip = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(plan),
                "old_string": "**Status**: Not Started",
                "new_string": "**Status**: In Progress",
            },
            "session_id": _SESSION,
        }
        handler.handle(flip)
        self._signal_path().unlink()
        handler.handle(flip)
        assert self._signal_path().exists()

    def test_missing_plan_file_is_harmless(self, handler: GoalInjectionHandler) -> None:
        ghost = self._project / "CLAUDE" / "Plan" / "00001-ghost" / "PLAN.md"
        result = handler.handle(self._hook_input(ghost))
        assert result.decision == Decision.ALLOW
        assert not self._signal_path().exists()

    def test_project_options_are_applied(self, handler: GoalInjectionHandler) -> None:
        handler._lines = [{"id": "motto", "text": "Motto for {plan_number}."}]
        plan = self._write_plan()
        handler.handle(self._hook_input(plan))
        data = json.loads(self._signal_path().read_text(encoding="utf-8"))
        assert f"Motto for {_PLAN_NUMBER}." in data["rendered_lines"][0]

    def test_never_blocks_even_on_write_failure(
        self, handler: GoalInjectionHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plan = self._write_plan()
        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection.write_goal_signal",
            lambda *a, **k: None,
        )
        result = handler.handle(self._hook_input(plan))
        assert result.decision == Decision.ALLOW

    def test_failed_write_does_not_latch(
        self, handler: GoalInjectionHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A write failure (``write_goal_signal`` returns None) must not set
        the once-per-(plan, session) latch -- otherwise the session never
        retries and never gets a signal, even after the failure clears."""
        plan = self._write_plan()
        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection.write_goal_signal",
            lambda *a, **k: None,
        )
        handler.handle(self._hook_input(plan))
        assert not self._signal_path().exists()

        monkeypatch.undo()
        handler.handle(self._hook_input(plan))
        assert self._signal_path().exists()

    def test_successful_write_still_latches(self, handler: GoalInjectionHandler) -> None:
        """A successful write DOES set the latch -- no duplicate write on a
        second qualifying event for the same (plan, session)."""
        plan = self._write_plan()
        handler.handle(self._hook_input(plan))
        assert self._signal_path().exists()
        first_mtime = self._signal_path().stat().st_mtime_ns

        self._signal_path().unlink()
        handler.handle(self._hook_input(plan))
        assert (
            not self._signal_path().exists()
        ), f"second write happened despite latch (first mtime {first_mtime})"


class TestGoalLedgerIntegration:
    """Plan 00276: emissions are ledgered and displacement is advised."""

    @pytest.fixture(autouse=True)
    def mock_project_context(self, tmp_path: Path):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection."
                "ProjectContext.daemon_untracked_dir",
                classmethod(lambda cls: tmp_path / "untracked"),
            )
            mp.setattr(
                "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection."
                "ProjectContext.project_root",
                classmethod(lambda cls: tmp_path),
            )
            self._untracked = tmp_path / "untracked"
            self._project = tmp_path
            yield

    @pytest.fixture
    def handler(self) -> GoalInjectionHandler:
        return GoalInjectionHandler()

    def _write_plan(self, folder: str, status: str = "In Progress") -> Path:
        plan_dir = self._project / "CLAUDE" / "Plan" / folder
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_file = plan_dir / "PLAN.md"
        plan_file.write_text(_plan_md(status), encoding="utf-8")
        return plan_file

    def _hook_input(self, file_path: Path) -> dict[str, Any]:
        return {
            "tool_name": "Write",
            "tool_input": {"file_path": str(file_path)},
            "session_id": _SESSION,
        }

    def _ledger_entries(self) -> list[dict[str, Any]]:
        from claude_code_hooks_daemon.utils.goal_ledger import LEDGER_FILENAME

        raw = json.loads((self._untracked / LEDGER_FILENAME).read_text(encoding="utf-8"))
        return list(raw["entries"])

    def test_emission_is_recorded_in_ledger(self, handler: GoalInjectionHandler) -> None:
        plan = self._write_plan("00274-first-plan")
        handler.handle(self._hook_input(plan))
        entries = self._ledger_entries()
        assert len(entries) == 1
        assert entries[0]["plan_number"] == "00274"
        assert entries[0]["session_id"] == _SESSION

    def test_displacement_marks_entry_and_advises(self, handler: GoalInjectionHandler) -> None:
        first = self._write_plan("00274-first-plan")
        second = self._write_plan("00275-second-plan")
        handler.handle(self._hook_input(first))
        result = handler.handle(self._hook_input(second))
        assert result.decision == Decision.ALLOW
        assert result.context, "displacement must inject advisory context"
        advisory = "\n".join(result.context)
        assert "00274" in advisory
        assert "displaced" in advisory.lower()
        entry = next(e for e in self._ledger_entries() if e["plan_number"] == "00274")
        assert entry["displaced_by"] == "00275"

    def test_no_advisory_when_prior_plan_completed(self, handler: GoalInjectionHandler) -> None:
        first = self._write_plan("00274-first-plan")
        handler.handle(self._hook_input(first))
        self._write_plan("00274-first-plan", status="Complete")
        second = self._write_plan("00275-second-plan")
        result = handler.handle(self._hook_input(second))
        assert result.context == []

    def test_ledger_failure_never_blocks(self, handler: GoalInjectionHandler) -> None:
        plan = self._write_plan("00274-first-plan")

        def _boom(cls: object) -> Path:
            raise RuntimeError("no project context")

        # A local context rather than the function-scoped `monkeypatch`
        # fixture, because `mock_project_context` above has ALREADY patched
        # this same attribute (Plan 00348). Two patches on one attribute unwind
        # in fixture-teardown order, not nesting order: the fixture's context
        # exits first and restores the original, then the test-level undo
        # faithfully restores what IT recorded -- the fixture's lambda -- which
        # then stays on the class for the rest of the process. The failure
        # lands in whatever reads ProjectContext next, naming a tmp_path from
        # this file. Entering and exiting here keeps the unwind properly
        # nested.
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection."
                "ProjectContext.daemon_untracked_dir",
                classmethod(_boom),
            )
            result = handler.handle(self._hook_input(plan))

        assert result.decision == Decision.ALLOW

    def test_retirement_refresh_propagates_ledger_failure(
        self, handler: GoalInjectionHandler
    ) -> None:
        """Unlike the real-flip path above, ``_maybe_refresh_on_retirement``
        has no substantive fallback to perform on a ``ProjectContext``
        failure, so review RV-n2 (round 2) has it propagate rather than
        catch-and-log -- catching here would be ``error_hiding``'s own
        ``log-and-continue`` anti-pattern, not a fix for the return-None
        one it replaced. The failure is left to ``core/chain.py``'s
        documented per-handler fail-open boundary, one level up."""
        plan = self._write_plan("00274-first-plan")
        handler.handle(self._hook_input(plan))
        completed = self._write_plan("00274-first-plan", status="Complete")

        def _boom(cls: object) -> Path:
            raise RuntimeError("no project context")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection."
                "ProjectContext.daemon_untracked_dir",
                classmethod(_boom),
            )
            with pytest.raises(RuntimeError, match="no project context"):
                handler.handle(self._hook_input(completed))

    def test_reassert_propagates_ledger_failure(self, handler: GoalInjectionHandler) -> None:
        """Same contract as the retirement-refresh test above, for
        ``_maybe_reassert_for_new_session`` -- a session touching an
        already-live plan without flipping it, under a ``ProjectContext``
        failure."""
        plan = self._write_plan("00274-first-plan")
        handler.handle(self._hook_input(plan))
        # An Edit whose old_string carries no Status line and whose
        # reconstructed pre-edit text is still In Progress is "not a flip"
        # (``_is_real_flip_to_in_progress``), which is what routes to
        # ``_maybe_reassert_for_new_session`` rather than the real-flip path
        # above -- a Write here would instead read as a flip (no git HEAD
        # to compare against in this fixture) and exercise the wrong branch.
        touch = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(plan),
                "old_string": "Body.",
                "new_string": "Body. Touched.",
            },
            "session_id": "other-session",
        }

        def _boom(cls: object) -> Path:
            raise RuntimeError("no project context")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection."
                "ProjectContext.daemon_untracked_dir",
                classmethod(_boom),
            )
            with pytest.raises(RuntimeError, match="no project context"):
                handler.handle(touch)


class TestCombinedGoalSignal:
    """Plan 00299: the signal reflects EVERY live ledgered plan, not just
    the newest — and a plan retiring refreshes it to drop that plan."""

    @pytest.fixture(autouse=True)
    def mock_project_context(self, tmp_path: Path):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection."
                "ProjectContext.daemon_untracked_dir",
                classmethod(lambda cls: tmp_path / "untracked"),
            )
            mp.setattr(
                "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection."
                "ProjectContext.project_root",
                classmethod(lambda cls: tmp_path),
            )
            self._untracked = tmp_path / "untracked"
            self._project = tmp_path
            yield

    @pytest.fixture
    def handler(self) -> GoalInjectionHandler:
        return GoalInjectionHandler()

    def _write_plan(self, folder: str, status: str = "In Progress") -> Path:
        plan_dir = self._project / "CLAUDE" / "Plan" / folder
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_file = plan_dir / "PLAN.md"
        plan_file.write_text(
            f"# Plan {folder.split('-', 1)[0]}: {folder}\n\n**Status**: {status}\n",
            encoding="utf-8",
        )
        return plan_file

    def _hook_input(self, file_path: Path) -> dict[str, Any]:
        return {
            "tool_name": "Write",
            "tool_input": {"file_path": str(file_path)},
            "session_id": _SESSION,
        }

    def _signal(self) -> dict[str, Any]:
        path = self._untracked / _SIGNAL_SUBDIR / f"{_SESSION}{_SIGNAL_SUFFIX}"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_second_plan_signal_names_both_live_plans(self, handler: GoalInjectionHandler) -> None:
        first = self._write_plan("00296-first")
        second = self._write_plan("00298-second")
        handler.handle(self._hook_input(first))
        handler.handle(self._hook_input(second))
        data = self._signal()
        joined = data["rendered_lines"][0]
        assert "00296" in joined
        assert "00298" in joined
        assert data["plan_number"] == "00296,00298"

    def test_third_plan_signal_names_all_three(self, handler: GoalInjectionHandler) -> None:
        for folder in ("00296-a", "00297-b", "00298-c"):
            handler.handle(self._hook_input(self._write_plan(folder)))
        joined = self._signal()["rendered_lines"][0]
        assert "00296" in joined
        assert "00297" in joined
        assert "00298" in joined

    def test_completing_one_plan_refreshes_signal_to_drop_it(
        self, handler: GoalInjectionHandler
    ) -> None:
        first = self._write_plan("00296-first")
        second = self._write_plan("00298-second")
        handler.handle(self._hook_input(first))
        handler.handle(self._hook_input(second))
        # First plan reaches a terminal status; re-writing it should refresh
        # the combined signal to drop it while the second stays.
        completed_first = self._write_plan("00296-first", status="Complete")
        handler.handle(self._hook_input(completed_first))
        joined = self._signal()["rendered_lines"][0]
        assert "00296" not in joined
        assert "00298" in joined

    def test_completing_a_plan_after_a_daemon_restart_still_refreshes_signal(
        self,
    ) -> None:
        """Review M2: the retirement refresh keyed on the in-memory
        ``self._fired`` latch, which a daemon restart (a fresh handler
        instance) empties. Ledger 00466 N3's flip-only rule made a
        non-flip write stop re-latching too, so nothing ever re-armed it
        -- a plan flipped in one daemon lifetime and completed in the
        next silently never dropped out of the combined signal. The
        refresh must be keyed on the persistent ``GoalLedger`` instead."""
        first = self._write_plan("00296-first")
        second = self._write_plan("00298-second")
        daemon_one = GoalInjectionHandler()
        daemon_one.handle(self._hook_input(first))
        daemon_one.handle(self._hook_input(second))

        # A fresh handler instance simulates a daemon restart: in-memory
        # `_fired` is empty, but the ledger/untracked dir persist.
        daemon_two = GoalInjectionHandler()
        completed_first = self._write_plan("00296-first", status="Complete")
        daemon_two.handle(self._hook_input(completed_first))

        joined = self._signal()["rendered_lines"][0]
        assert "00296" not in joined
        assert "00298" in joined

    def test_terminal_write_for_unledgered_plan_is_a_no_op(
        self, handler: GoalInjectionHandler
    ) -> None:
        """A terminal-status write for a plan this session never emitted a
        goal for must not touch the signal at all (nothing to refresh)."""
        plan = self._write_plan("00299-never-in-progress", status="Complete")
        result = handler.handle(self._hook_input(plan))
        assert result.decision == Decision.ALLOW
        assert not (self._untracked / _SIGNAL_SUBDIR / f"{_SESSION}{_SIGNAL_SUFFIX}").exists()

    def test_retiring_the_only_live_plan_removes_the_signal(
        self, handler: GoalInjectionHandler
    ) -> None:
        """Plan 00320: emptying the ledger must RETRACT the sidecar, not just
        decline to rewrite it.

        Writing nothing leaves the file written moments earlier still on disk
        asserting the retired goal, so the ledger reads zero live entries while
        the sidecar — the file the Stop challenge actually reads — keeps naming
        a plan nobody is working on. Observed live during the v3.60.0 release:
        a goal retired three seconds after emission was still challenging the
        session's stop twenty-nine minutes later.
        """
        signal_path = self._untracked / _SIGNAL_SUBDIR / f"{_SESSION}{_SIGNAL_SUFFIX}"
        only = self._write_plan("00296-only")
        handler.handle(self._hook_input(only))
        assert signal_path.exists(), "precondition: the goal signal was written"

        handler.handle(self._hook_input(self._write_plan("00296-only", status="Complete")))

        assert not signal_path.exists(), (
            "sidecar survived the retirement of the last live plan — the ledger "
            "and the sidecar now disagree about whether any goal is live"
        )

    def test_retiring_the_only_live_plan_writes_a_clear_signal(
        self, handler: GoalInjectionHandler
    ) -> None:
        """Plan 00321: removing the sidecar is not enough — the upstream
        `/goal` slot still holds the condition.

        Deleting `<session>.goal-intent` stops the goal being RE-injected, but
        Claude Code's `/goal` slot is last-writer-wins and keeps the condition
        until something types a clearing form. So an emptied ledger must also
        drop a `<session>.goal-clear` trigger for the supervisor to act on.
        """
        clear_path = self._untracked / _SIGNAL_SUBDIR / f"{_SESSION}{_CLEAR_SUFFIX}"
        only = self._write_plan("00296-only")
        handler.handle(self._hook_input(only))
        assert not clear_path.exists(), "precondition: no clear pending while the plan is live"

        handler.handle(self._hook_input(self._write_plan("00296-only", status="Complete")))

        assert clear_path.exists(), (
            "no .goal-clear trigger written — the upstream /goal slot would keep "
            "the retired condition and challenge every stop"
        )

    def test_no_clear_signal_while_another_plan_stays_live(
        self, handler: GoalInjectionHandler
    ) -> None:
        """A goal is still owed, so nothing may clear the slot."""
        clear_path = self._untracked / _SIGNAL_SUBDIR / f"{_SESSION}{_CLEAR_SUFFIX}"
        handler.handle(self._hook_input(self._write_plan("00296-first")))
        handler.handle(self._hook_input(self._write_plan("00298-second")))

        handler.handle(self._hook_input(self._write_plan("00296-first", status="Complete")))

        assert not clear_path.exists()

    def test_a_render_failure_does_not_retract_a_still_live_goal(
        self, handler: GoalInjectionHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only an EMPTY ledger retracts — a failed render must change nothing.

        ``render_combined_goal_line`` returns None for two quite different
        situations: no live plans, and a live set it could not render (e.g. a
        malformed plan number). Routing both to the retract path meant a render
        failure silently cleared a goal that was still owed, which is the same
        ledger/slot disagreement Plan 00320 fixed, just reached another way.
        """
        clear_path = self._untracked / _SIGNAL_SUBDIR / f"{_SESSION}{_CLEAR_SUFFIX}"
        handler.handle(self._hook_input(self._write_plan("00296-first")))
        handler.handle(self._hook_input(self._write_plan("00298-second")))

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection."
            "render_combined_goal_line",
            lambda *a, **k: None,
        )
        handler.handle(self._hook_input(self._write_plan("00296-first", status="Complete")))

        assert not clear_path.exists(), (
            "a render failure retracted the goal while 00298 was still live — "
            "the ledger would report a live plan with an empty /goal slot"
        )

    def test_retirement_leaves_signal_intact_while_another_plan_stays_live(
        self, handler: GoalInjectionHandler
    ) -> None:
        """The retraction must be scoped to an EMPTY ledger.

        Retiring one of two live plans still has something to assert, so the
        sidecar must be rewritten rather than removed. This pins the boundary
        the fix must not cross.
        """
        signal_path = self._untracked / _SIGNAL_SUBDIR / f"{_SESSION}{_SIGNAL_SUFFIX}"
        first = self._write_plan("00296-first")
        second = self._write_plan("00298-second")
        handler.handle(self._hook_input(first))
        handler.handle(self._hook_input(second))

        handler.handle(self._hook_input(self._write_plan("00296-first", status="Complete")))

        assert signal_path.exists(), "a still-live plan must keep its signal"
        assert "00298" in self._signal()["rendered_lines"][0]


class TestStatusFlipDetection:
    """N3 (ledger 00466): fire only on a REAL transition to In Progress.

    The handler previously matched the post-write STATE ("does the file now
    read In Progress"), so the first Write/Edit in a session to any plan that
    was ALREADY In Progress fired -- a table row, a task tick, a typo fix.
    These tests pin the transition contract: an Edit whose replaced span
    never touched the Status line, or a Write that merely rewrites an
    already-In-Progress plan, must emit nothing -- no signal, no ledger
    record, no displacement advisory -- even though the post-write file
    still reads In Progress.
    """

    @pytest.fixture(autouse=True)
    def mock_project_context(self, tmp_path: Path):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection."
                "ProjectContext.daemon_untracked_dir",
                classmethod(lambda cls: tmp_path / "untracked"),
            )
            mp.setattr(
                "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection."
                "ProjectContext.project_root",
                classmethod(lambda cls: tmp_path),
            )
            self._untracked = tmp_path / "untracked"
            self._project = tmp_path
            yield

    @pytest.fixture
    def handler(self) -> GoalInjectionHandler:
        return GoalInjectionHandler()

    def _plan_path(self, folder: str = _PLAN_FOLDER) -> Path:
        plan_dir = self._project / "CLAUDE" / "Plan" / folder
        plan_dir.mkdir(parents=True, exist_ok=True)
        return plan_dir / "PLAN.md"

    def _signal_path(self, session: str = _SESSION) -> Path:
        return self._untracked / _SIGNAL_SUBDIR / f"{session}{_SIGNAL_SUFFIX}"

    def _edit_hook_input(self, file_path: Path, old_string: str, new_string: str) -> dict[str, Any]:
        return {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(file_path),
                "old_string": old_string,
                "new_string": new_string,
            },
            "session_id": _SESSION,
        }

    def _write_hook_input(self, file_path: Path) -> dict[str, Any]:
        return {
            "tool_name": "Write",
            "tool_input": {"file_path": str(file_path)},
            "session_id": _SESSION,
        }

    def _init_repo(self) -> None:
        _git(self._project, "init")
        _git(self._project, "config", "user.email", "t@example.com")
        _git(self._project, "config", "user.name", "T")

    # ---- Edit: the transition is read from old_string/new_string alone ---

    def test_edit_unrelated_to_status_line_on_in_progress_plan_emits_nothing(
        self, handler: GoalInjectionHandler
    ) -> None:
        """A table-row/typo edit to an already-In-Progress plan is silent."""
        plan = self._plan_path()
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")

        result = handler.handle(
            self._edit_hook_input(
                plan,
                old_string="## Overview\n\nBody.",
                new_string="## Overview\n\nBody.\n\n| a | b |\n| - | - |",
            )
        )

        assert result.decision == Decision.ALLOW
        assert result.context == []
        assert not self._signal_path().exists()

    def test_edit_flipping_status_line_to_in_progress_emits(
        self, handler: GoalInjectionHandler
    ) -> None:
        """The old contract, pinned: a real Not Started -> In Progress flip."""
        plan = self._plan_path()
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")

        result = handler.handle(
            self._edit_hook_input(
                plan,
                old_string="**Status**: Not Started",
                new_string="**Status**: In Progress",
            )
        )

        assert result.decision == Decision.ALLOW
        assert self._signal_path().exists()

    def test_edit_whose_replaced_span_already_read_in_progress_emits_nothing(
        self, handler: GoalInjectionHandler
    ) -> None:
        """The replaced span itself proves the line was already In Progress
        -- e.g. correcting the Created date in the same replaced chunk."""
        plan = self._plan_path()
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")

        result = handler.handle(
            self._edit_hook_input(
                plan,
                old_string="**Status**: In Progress\n**Created**: 2026-08-26",
                new_string="**Status**: In Progress\n**Created**: 2026-08-27",
            )
        )

        assert result.decision == Decision.ALLOW
        assert not self._signal_path().exists()

    def test_edit_whose_old_string_is_only_the_status_value_still_emits(
        self, handler: GoalInjectionHandler
    ) -> None:
        """Review m4: ``old_string`` may carry just the VALUE ("Not Started"),
        with no ``**Status**:`` prefix in the replaced span -- e.g. the agent
        quoted the minimal unique context. ``PlanDoc.parse(old_string)`` alone
        then finds no Status line and reads "never touched it", missing a
        genuine flip. The pre-edit text must be reconstructed from what is
        already on disk (undo this edit against the post-edit file) rather
        than answered from ``old_string`` in isolation."""
        plan = self._plan_path()
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")

        result = handler.handle(
            self._edit_hook_input(plan, old_string="Not Started", new_string="In Progress")
        )

        assert result.decision == Decision.ALLOW
        assert self._signal_path().exists()

    def test_edit_whose_old_string_value_was_already_in_progress_emits_nothing(
        self, handler: GoalInjectionHandler
    ) -> None:
        """The reconstruction control: undoing a value-only edit that never
        changed the status (e.g. correcting unrelated nearby text tagged with
        the same value-only ``old_string``/``new_string`` pair) must still
        read as no flip."""
        plan = self._plan_path()
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")

        result = handler.handle(
            self._edit_hook_input(plan, old_string="In Progress", new_string="In Progress")
        )

        assert result.decision == Decision.ALLOW
        assert not self._signal_path().exists()

    def test_new_string_colliding_with_unrelated_text_does_not_falsely_flip(
        self, handler: GoalInjectionHandler
    ) -> None:
        """Review RV-m1: the plan is ALREADY In Progress, and a table cell
        elsewhere reads "Not Started". Undoing the FIRST occurrence of
        ``new_string`` ("In Progress") in the post-edit text lands on the
        REAL Status line (the table cell comes first in this fixture's
        layout only by coincidence of where it is placed) unless every
        occurrence is tried and filtered to the one reversal that leaves
        ``old_string`` unique -- the actual edit here never touched the
        Status line at all."""
        plan = self._plan_path()
        plan.write_text(
            "# Plan 00269: supervisor goal message injection\n\n"
            "**Status**: In Progress\n\n"
            "| Task | State |\n| --- | --- |\n| A | Not Started |\n",
            encoding="utf-8",
        )

        result = handler.handle(
            self._edit_hook_input(plan, old_string="Not Started", new_string="In Progress")
        )

        assert result.decision == Decision.ALLOW
        assert not self._signal_path().exists()

    def test_replace_all_colliding_with_unrelated_text_does_not_falsely_flip(
        self, handler: GoalInjectionHandler
    ) -> None:
        """RV3-m1: the plan is ALREADY In Progress, and one table cell reads
        'Not Started'. The fixture is the file exactly as a real
        ``replace_all('Not Started' -> 'In Progress')`` Edit would leave it
        on disk -- pre_edit's ONE 'Not Started' occurrence transformed, not
        hand-authored -- so the Status line's own occurrence of the target
        text is UNCHANGED by the edit (it was already 'In Progress'), and a
        blind full reversal wrongly reverses it too. The prior version of
        this test used a fixture no Edit tool call could ever produce (its
        'post-edit' text still contained ``old_string`` everywhere), so it
        exercised the safe early-exit rather than the collision logic."""
        plan = self._plan_path()
        pre_edit = (
            "# Plan 00269: supervisor goal message injection\n\n"
            "**Status**: In Progress\n\n"
            "| Task | State |\n| --- | --- |\n| A | Not Started |\n"
        )
        plan.write_text(pre_edit.replace("Not Started", "In Progress"), encoding="utf-8")

        edit = self._edit_hook_input(plan, old_string="Not Started", new_string="In Progress")
        edit["tool_input"]["replace_all"] = True

        result = handler.handle(edit)

        assert result.decision == Decision.ALLOW
        assert not self._signal_path().exists()

    def test_replace_all_colliding_with_two_unrelated_cells_does_not_falsely_flip(
        self, handler: GoalInjectionHandler
    ) -> None:
        """RV3-m1's C2b: same collision, with TWO 'Not Started' cells
        genuinely flipped by the same replace_all -- the ambiguity check
        must hold regardless of how many OTHER sites the edit touches."""
        plan = self._plan_path()
        pre_edit = (
            "# Plan 00269: supervisor goal message injection\n\n"
            "**Status**: In Progress\n\n"
            "| Task | State |\n| --- | --- |\n"
            "| A | Not Started |\n| B | Not Started |\n"
        )
        plan.write_text(pre_edit.replace("Not Started", "In Progress"), encoding="utf-8")

        edit = self._edit_hook_input(plan, old_string="Not Started", new_string="In Progress")
        edit["tool_input"]["replace_all"] = True

        result = handler.handle(edit)

        assert result.decision == Decision.ALLOW
        assert not self._signal_path().exists()

    def test_replace_all_single_occurrence_on_status_line_still_detected(
        self, handler: GoalInjectionHandler
    ) -> None:
        """RV3-m1's regression control: when the Status line is the ONLY
        occurrence of ``new_string`` (no colliding cell anywhere), the
        ambiguity check must not needlessly suppress the flip -- there is
        nothing to disambiguate when there is only one candidate site."""
        plan = self._plan_path()
        pre_edit = (
            "# Plan 00269: supervisor goal message injection\n\n"
            "**Status**: Not Started\n\nBody.\n"
        )
        plan.write_text(pre_edit.replace("Not Started", "In Progress"), encoding="utf-8")

        edit = self._edit_hook_input(plan, old_string="Not Started", new_string="In Progress")
        edit["tool_input"]["replace_all"] = True

        result = handler.handle(edit)

        assert result.decision == Decision.ALLOW
        assert self._signal_path().exists()

    # ---- RV3-m2: the post-state check must agree with PlanDoc, not a
    # literal-only regex that cannot see past a fenced/second Status line --

    def test_task_tick_on_a_not_started_plan_with_a_fenced_status_example_stays_silent(
        self, handler: GoalInjectionHandler
    ) -> None:
        """C7b: a fenced example line reading '**Status**: In Progress'
        must not make an unrelated task-tick edit look like a flip.

        RV4-m5: the fixture holds the POST-edit content (``new_string``
        already applied) -- PostToolUse dispatches AFTER the tool has
        already landed the edit on disk, and a fixture still carrying
        ``old_string`` makes ``_is_transition_via_reconstruction`` bail out
        at "new_string not found" before the fenced-example defence this
        test names is ever exercised (the same fixture defect RV3-m1
        raised)."""
        plan = self._plan_path()
        plan.write_text(
            "# Plan 00269: supervisor goal message injection\n\n"
            "**Status**: Not Started\n\n"
            "Example:\n\n```markdown\n**Status**: In Progress\n```\n\n"
            "- [x] a\n",
            encoding="utf-8",
        )

        result = handler.handle(
            self._edit_hook_input(plan, old_string="- [ ] a", new_string="- [x] a")
        )

        assert result.decision == Decision.ALLOW
        assert not self._signal_path().exists()

    def test_editing_a_second_status_line_to_in_progress_on_an_in_progress_plan_stays_silent(
        self, handler: GoalInjectionHandler
    ) -> None:
        """C8: the REAL Status line already reads In Progress; a per-phase
        second '**Status**:' line moving to In Progress is not the flip
        PlanDoc (and thus this handler) cares about.

        RV4-m5: the fixture holds the POST-edit content, same reasoning as
        C7b above -- otherwise reconstruction bails out on a missing
        ``new_string`` before this test exercises anything."""
        plan = self._plan_path()
        plan.write_text(
            "# Plan 00269: supervisor goal message injection\n\n"
            "**Status**: In Progress\n\n"
            "### Phase 2\n\n**Status**: In Progress\n",
            encoding="utf-8",
        )

        result = handler.handle(
            self._edit_hook_input(
                plan,
                old_string="### Phase 2\n\n**Status**: Not Started",
                new_string="### Phase 2\n\n**Status**: In Progress",
            )
        )

        assert result.decision == Decision.ALLOW
        assert not self._signal_path().exists()

    def test_flip_to_in_progress_with_a_date_qualifier_is_still_detected(
        self, handler: GoalInjectionHandler
    ) -> None:
        """C11: a bonus of switching the post-state check to PlanDoc (RV3-m2)
        -- a Status line carrying a trailing date qualifier, which the old
        literal-only regex could never match, is a real flip PlanDoc
        recognises correctly (this was a MISSED flip on main too)."""
        plan = self._plan_path()
        plan.write_text(
            "# Plan 00269: supervisor goal message injection\n\n"
            "**Status**: In Progress (2026-09-24)\n",
            encoding="utf-8",
        )

        result = handler.handle(
            self._edit_hook_input(
                plan,
                old_string="**Status**: Not Started",
                new_string="**Status**: In Progress (2026-09-24)",
            )
        )

        assert result.decision == Decision.ALLOW
        assert self._signal_path().exists()

    # ---- RV3-m6: the Write path must not fire on a plan already ledgered
    # live, even when git HEAD lags an uncommitted flip --

    def test_write_of_a_plan_already_live_in_the_ledger_but_uncommitted_does_not_displace(
        self, handler: GoalInjectionHandler
    ) -> None:
        """C5g: S1 flips 00304 (uncommitted -- HEAD still reads Not
        Started), then S2 flips 00305 (marking 00304 displaced). Teammate
        S3 then Writes 00304 -- this must NOT be misread as a FRESH flip:
        that would wrongly emit a new ledger record for 00304, marking the
        still-live 00305 displaced in turn. The ledger, not git HEAD, is
        authoritative for whether 00304 has already started."""
        self._init_repo()
        first = self._plan_path("00304-first")
        first.write_text(_plan_md("Not Started"), encoding="utf-8")
        second = self._plan_path("00305-second")
        second.write_text(_plan_md("Not Started"), encoding="utf-8")
        _git(self._project, "add", "-A")
        _git(self._project, "commit", "-m", "create plans")

        def _write_as(file_path: Path, session: str) -> dict[str, Any]:
            return {
                "tool_name": "Write",
                "tool_input": {"file_path": str(file_path)},
                "session_id": session,
            }

        first.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(_write_as(first, "S1"))  # S1's flip, uncommitted
        second.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(_write_as(second, "S2"))  # S2 flips 00305, displacing 00304

        result = handler.handle(_write_as(first, "S3"))

        assert result.decision == Decision.ALLOW
        assert result.context == [], "re-Writing 00304 must not re-displace 00305"
        entry_305 = next(
            e
            for e in GoalLedger(self._untracked / LEDGER_FILENAME).entries()
            if e.plan_number == "00305"
        )
        assert entry_305.displaced_by is None

    def test_genuine_flip_still_detected_when_new_string_is_unambiguous(
        self, handler: GoalInjectionHandler
    ) -> None:
        """The regression control for RV-m1's fix: when ``new_string``
        occurs exactly once, the (now candidate-based) reconstruction must
        still detect a real flip -- this is the pre-existing m4 contract."""
        plan = self._plan_path()
        plan.write_text(
            "# Plan 00269: supervisor goal message injection\n\n"
            "**Status**: In Progress\n\n"
            "Body.\n",
            encoding="utf-8",
        )

        result = handler.handle(
            self._edit_hook_input(plan, old_string="Not Started", new_string="In Progress")
        )

        assert result.decision == Decision.ALLOW
        assert self._signal_path().exists()

    # ---- Write: the transition is read against git HEAD -------------------

    def test_write_creating_a_brand_new_in_progress_plan_emits(
        self, handler: GoalInjectionHandler
    ) -> None:
        """No repository at all: HEAD carries nothing, so this reads as a
        genuine flip -- matches the pre-existing single-plan contract."""
        plan = self._plan_path()
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")

        result = handler.handle(self._write_hook_input(plan))

        assert result.decision == Decision.ALLOW
        assert self._signal_path().exists()

    def test_write_rewriting_an_already_committed_in_progress_plan_emits_nothing(
        self, handler: GoalInjectionHandler
    ) -> None:
        """The exact live scenario (ledger 00466 N3): the plan was already
        In Progress at HEAD; this Write only adds a section."""
        self._init_repo()
        plan = self._plan_path()
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")
        _git(self._project, "add", "-A")
        _git(self._project, "commit", "-m", "flip to in progress")

        plan.write_text(_plan_md("In Progress") + "\n## Notes\n\nMore.\n", encoding="utf-8")

        result = handler.handle(self._write_hook_input(plan))

        assert result.decision == Decision.ALLOW
        assert result.context == []
        assert not self._signal_path().exists()

    def test_write_rewriting_an_uncommitted_plan_to_in_progress_emits(
        self, handler: GoalInjectionHandler
    ) -> None:
        """A real repo exists, but this path was never committed: HEAD has
        nothing for it, so the write still reads as a genuine flip."""
        self._init_repo()
        plan = self._plan_path()
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")

        result = handler.handle(self._write_hook_input(plan))

        assert result.decision == Decision.ALLOW
        assert self._signal_path().exists()

    def test_write_rewriting_a_committed_not_started_plan_to_in_progress_emits(
        self, handler: GoalInjectionHandler
    ) -> None:
        self._init_repo()
        plan = self._plan_path()
        plan.write_text(_plan_md("Not Started"), encoding="utf-8")
        _git(self._project, "add", "-A")
        _git(self._project, "commit", "-m", "create plan")

        plan.write_text(_plan_md("In Progress"), encoding="utf-8")

        result = handler.handle(self._write_hook_input(plan))

        assert result.decision == Decision.ALLOW
        assert self._signal_path().exists()

    # ---- Terminal flip refresh/retract path is unaffected ------------------

    def test_terminal_flip_still_refreshes_combined_signal(
        self, handler: GoalInjectionHandler
    ) -> None:
        """The retirement-refresh path never runs through the new gate (it
        only applies to a still-In-Progress result) and must keep working."""
        first = self._plan_path("00296-first")
        first.write_text("# Plan 00296: first\n\n**Status**: In Progress\n", encoding="utf-8")
        second = self._plan_path("00298-second")
        second.write_text("# Plan 00298: second\n\n**Status**: In Progress\n", encoding="utf-8")
        handler.handle(self._write_hook_input(first))
        handler.handle(self._write_hook_input(second))

        first.write_text("# Plan 00296: first\n\n**Status**: Complete\n", encoding="utf-8")
        handler.handle(self._write_hook_input(first))

        data = json.loads(self._signal_path().read_text(encoding="utf-8"))
        joined = data["rendered_lines"][0]
        assert "00296" not in joined
        assert "00298" in joined


class TestGroundTruthSnapshotResolution:
    """Plan 00466 RV3-n5: a PreToolUse snapshot of the plan's pre-write
    status (keyed by ``tool_use_id``), consumed here as ground truth in
    place of ``old_string``/``new_string`` + git-HEAD inference.

    C3b and m4d's C3 (review 3, subagent-reports/260924-n466-goalflip-
    review3-opus-5-5.md) are both cases where a REAL flip is missed because
    "In Progress" also appears somewhere else in the document (a table
    cell, a title) -- from the Edit payload alone the two pre-edit texts
    really are indistinguishable, so the existing reconstruction correctly
    stays conservative. A pre-write snapshot removes the ambiguity
    entirely: it never reconstructs anything, it just reports what the
    file said a moment before the write. The restart-fallback tests pin
    that the OLD inference (and its conservative answer) is still exactly
    what runs when no snapshot exists for this ``tool_use_id``.
    """

    @pytest.fixture(autouse=True)
    def mock_project_context(self, tmp_path: Path):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection."
                "ProjectContext.daemon_untracked_dir",
                classmethod(lambda cls: tmp_path / "untracked"),
            )
            mp.setattr(
                "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection."
                "ProjectContext.project_root",
                classmethod(lambda cls: tmp_path),
            )
            self._untracked = tmp_path / "untracked"
            self._project = tmp_path
            yield

    @pytest.fixture
    def handler(self) -> GoalInjectionHandler:
        return GoalInjectionHandler()

    def _plan_path(self, folder: str = _PLAN_FOLDER) -> Path:
        plan_dir = self._project / "CLAUDE" / "Plan" / folder
        plan_dir.mkdir(parents=True, exist_ok=True)
        return plan_dir / "PLAN.md"

    def _signal_path(self, session: str = _SESSION) -> Path:
        return self._untracked / _SIGNAL_SUBDIR / f"{session}{_SIGNAL_SUFFIX}"

    def _edit_hook_input(
        self, file_path: Path, old_string: str, new_string: str, *, tool_use_id: str = ""
    ) -> dict[str, Any]:
        hook_input: dict[str, Any] = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(file_path),
                "old_string": old_string,
                "new_string": new_string,
            },
            "session_id": _SESSION,
        }
        if tool_use_id:
            hook_input["tool_use_id"] = tool_use_id
        return hook_input

    def test_c3b_table_cell_collision_is_resolved_by_the_snapshot(
        self, handler: GoalInjectionHandler
    ) -> None:
        """RV3-n5's C3b: the Status line genuinely flips (replace_all), and
        an UNRELATED table cell already read "In Progress" before and after
        -- the reconstruction's full-vs-partial-reversal verdicts disagree
        (main's conservative answer), but a pre-write snapshot resolves it
        as the real flip it is."""
        from claude_code_hooks_daemon.plan_qa.model import PlanStatus
        from claude_code_hooks_daemon.utils.plan_status_snapshot import (
            hash_plan_text,
            plan_status_snapshots,
        )

        plan = self._plan_path()
        pre_edit = (
            "# Plan 00269: supervisor goal message injection\n\n"
            "**Status**: Not Started\n\n"
            "| Task | State |\n| --- | --- |\n| A | In Progress |\n"
        )
        plan.write_text(pre_edit.replace("Not Started", "In Progress"), encoding="utf-8")

        edit = self._edit_hook_input(
            plan, old_string="Not Started", new_string="In Progress", tool_use_id="tu-c3b"
        )
        edit["tool_input"]["replace_all"] = True
        # RV5-M2: the recorded hash is of the PREDICTED post-image (what
        # this same edit, applied forward, produces) -- here that is
        # exactly the text already written to disk above.
        post_edit = pre_edit.replace("Not Started", "In Progress")
        plan_status_snapshots.record("tu-c3b", PlanStatus.NOT_STARTED, hash_plan_text(post_edit))

        result = handler.handle(edit)

        assert result.decision == Decision.ALLOW
        assert self._signal_path().exists()

    def test_m4d_title_collision_is_resolved_by_the_snapshot(
        self, handler: GoalInjectionHandler
    ) -> None:
        """m4d's C3 (review 2/3): the plan title itself contains "In
        Progress" ("Track In Progress plans"), so undoing each occurrence
        of ``new_string`` individually produces disagreeing verdicts even
        after the per-candidate uniqueness filter -- a real flip is missed.
        A pre-write snapshot needs no reconstruction at all."""
        from claude_code_hooks_daemon.plan_qa.model import PlanStatus
        from claude_code_hooks_daemon.utils.plan_status_snapshot import (
            hash_plan_text,
            plan_status_snapshots,
        )

        plan = self._plan_path()
        pre_edit = "# Plan 00269: Track In Progress plans\n\n" "**Status**: Not Started\n\nBody.\n"
        plan.write_text(pre_edit.replace("Not Started", "In Progress"), encoding="utf-8")

        edit = self._edit_hook_input(
            plan, old_string="Not Started", new_string="In Progress", tool_use_id="tu-m4d"
        )
        # RV5-M2: the recorded hash is of the PREDICTED post-image (what
        # this same edit, applied forward, produces) -- here that is
        # exactly the text already written to disk above.
        post_edit = pre_edit.replace("Not Started", "In Progress")
        plan_status_snapshots.record("tu-m4d", PlanStatus.NOT_STARTED, hash_plan_text(post_edit))

        result = handler.handle(edit)

        assert result.decision == Decision.ALLOW
        assert self._signal_path().exists()

    def test_no_snapshot_falls_back_to_inference_and_logs_it(
        self, handler: GoalInjectionHandler, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Restart-fallback: no snapshot was ever recorded for this
        ``tool_use_id`` (a daemon restart between Pre and Post dispatch of
        the SAME tool call empties the in-memory store). The unambiguous
        case still flips correctly via the old inference, and the fallback
        use is logged."""
        plan = self._plan_path()
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")

        with caplog.at_level("INFO", logger="claude_code_hooks_daemon"):
            result = handler.handle(
                self._edit_hook_input(
                    plan,
                    old_string="**Status**: Not Started",
                    new_string="**Status**: In Progress",
                    tool_use_id="tu-never-recorded",
                )
            )

        assert result.decision == Decision.ALLOW
        assert self._signal_path().exists()
        assert any(
            "falling back to old_string/new_string and git-HEAD inference" in record.message
            for record in caplog.records
        )

    def test_no_snapshot_ambiguous_case_stays_conservative(
        self, handler: GoalInjectionHandler
    ) -> None:
        """Restart-fallback, ambiguous shape: without a snapshot, the C3b
        table-cell collision is answered exactly as main answers it today
        -- conservatively, as no flip -- rather than silently changing
        behaviour whenever a snapshot happens to be unavailable."""
        plan = self._plan_path()
        pre_edit = (
            "# Plan 00269: supervisor goal message injection\n\n"
            "**Status**: Not Started\n\n"
            "| Task | State |\n| --- | --- |\n| A | In Progress |\n"
        )
        plan.write_text(pre_edit.replace("Not Started", "In Progress"), encoding="utf-8")

        edit = self._edit_hook_input(
            plan, old_string="Not Started", new_string="In Progress", tool_use_id="tu-c3b-no-snap"
        )
        edit["tool_input"]["replace_all"] = True

        result = handler.handle(edit)

        assert result.decision == Decision.ALLOW
        assert not self._signal_path().exists()

    def test_empty_tool_use_id_also_falls_back(self, handler: GoalInjectionHandler) -> None:
        """A payload carrying no ``tool_use_id`` at all (empty string, the
        store's own documented no-op key) must fall back exactly like a
        genuinely missing snapshot -- never raise, never misbehave."""
        plan = self._plan_path()
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")

        result = handler.handle(
            self._edit_hook_input(
                plan, old_string="**Status**: Not Started", new_string="**Status**: In Progress"
            )
        )

        assert result.decision == Decision.ALLOW
        assert self._signal_path().exists()

    def test_a_snapshot_stale_from_another_sessions_flip_is_discarded(
        self, handler: GoalInjectionHandler
    ) -> None:
        """RV4-m2 / probe_gf4_race.py's F3: S1's Pre for a plain checkbox
        tick on P runs while P still reads Not Started. Before S1's own
        edit lands, S2 REALLY flips P for real, then S3 REALLY flips R --
        which displaces P (a new plan starting displaces the previously
        live one). S1's tick then lands on the now-In-Progress (and now
        DISPLACED) P, dispatched against S1's stale snapshot.

        Trusting that snapshot blindly makes S1's non-flip tick look like
        ITS OWN fresh flip of P -- ``record_emission`` re-arms an existing
        live entry on every real emission (``displaced_by = None``), which
        would ERASE P's own legitimate displacement by R. The snapshot
        must instead be discarded as stale (P changed underneath), falling
        back to inference, which correctly reads this as "not a
        transition" and leaves P's displacement exactly as R set it."""
        from claude_code_hooks_daemon.plan_qa.model import PlanStatus
        from claude_code_hooks_daemon.utils.plan_status_snapshot import (
            hash_plan_text,
            plan_status_snapshots,
        )

        p = self._plan_path("00300-p")
        p_pre_edit = "# Plan 00300: p\n\n**Status**: Not Started\n\n## Tasks\n\n- [ ] a\n"
        p.write_text(p_pre_edit, encoding="utf-8")
        # S1's Pre snapshot: P read Not Started at this moment.
        plan_status_snapshots.record("tu-race", PlanStatus.NOT_STARTED, hash_plan_text(p_pre_edit))

        # S2 really flips P for real (no snapshot -- inference fallback).
        p.write_text(
            p_pre_edit.replace("**Status**: Not Started", "**Status**: In Progress"),
            encoding="utf-8",
        )
        handler.handle(
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(p),
                    "old_string": "**Status**: Not Started",
                    "new_string": "**Status**: In Progress",
                },
                "session_id": "S2",
            }
        )

        # S3 really flips R -- this displaces P, the now-previous live plan.
        r = self._plan_path("00304-r")
        r.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(r),
                    "old_string": "**Status**: Not Started",
                    "new_string": "**Status**: In Progress",
                },
                "session_id": "S3",
            }
        )
        ledger = GoalLedger(self._untracked / LEDGER_FILENAME)
        entry_p_before = next(e for e in ledger.entries() if e.plan_number == "00300")
        assert entry_p_before.displaced_by == "00304", "precondition: R's flip displaces P"

        # S1's tick lands on the now-In-Progress, now-DISPLACED P,
        # dispatched against the stale "tu-race" snapshot recorded before
        # S2's flip.
        p.write_text(p.read_text(encoding="utf-8").replace("- [ ] a", "- [x] a"), encoding="utf-8")
        handler.handle(
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(p),
                    "old_string": "- [ ] a",
                    "new_string": "- [x] a",
                },
                "session_id": "S1",
                "tool_use_id": "tu-race",
            }
        )

        entry_p_after = next(e for e in ledger.entries() if e.plan_number == "00300")
        assert entry_p_after.displaced_by == "00304", (
            "P's own displacement by R was erased by S1's non-flip tick -- "
            "the stale snapshot from before S2's real flip was trusted "
            "instead of discarded, and S1's dispatch re-armed P's ledger "
            "entry as though it were a fresh flip"
        )

    # ---- RV5-M2: time-free freshness (probe_gf5_timebound.py's T1/T3/T4/T7) --

    def test_snapshot_freshness_never_consults_the_clock(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RV5-M2 / 'the bound never expires' mutant: ``_snapshot_is_fresh``
        is a pure hash comparison now, with no wall-clock or monotonic-
        clock read anywhere in it -- pinned directly (not through the full
        ``handle()`` flow, which legitimately calls ``time.time()`` of its
        OWN, for the signal file's timestamp field, once a flip is already
        decided) by making every clock read raise and calling it with both
        a matching and a mismatching snapshot."""
        from claude_code_hooks_daemon.plan_qa.model import PlanStatus
        from claude_code_hooks_daemon.utils.plan_status_snapshot import (
            PlanStatusSnapshot,
            hash_plan_text,
        )

        def _boom(*_a: object, **_kw: object) -> float:
            raise AssertionError("RV5-M2: freshness must never consult a clock")

        monkeypatch.setattr("time.time", _boom)
        monkeypatch.setattr("time.monotonic", _boom)

        fresh = PlanStatusSnapshot(PlanStatus.NOT_STARTED, hash_plan_text("post"))
        stale = PlanStatusSnapshot(PlanStatus.NOT_STARTED, hash_plan_text("something else"))

        assert GoalInjectionHandler._snapshot_is_fresh("post", fresh) is True
        assert GoalInjectionHandler._snapshot_is_fresh("post", stale) is False

    def test_t1_replace_all_bulk_flip_survives_an_arbitrary_pre_post_gap(
        self, handler: GoalInjectionHandler
    ) -> None:
        """probe_gf5_timebound.py T1: a genuine bulk ``replace_all`` flip,
        with an unrelated table cell that already reads "In Progress"
        before AND after (so reconstruction alone is ambiguous, RV3-m1).
        The store carries no time field at all (see
        ``test_snapshot_freshness_never_consults_the_clock`` above), so
        this is the same test at any Pre -> Post gap, including past the
        OLD 5 s bound (T1's 6 s case) -- however long a person takes to
        answer a permission prompt cannot matter here."""
        from claude_code_hooks_daemon.plan_qa.model import PlanStatus
        from claude_code_hooks_daemon.utils.plan_status_snapshot import (
            hash_plan_text,
            plan_status_snapshots,
        )

        plan = self._plan_path("00300-c")
        pre_edit = "# Plan 00300: c\n\n**Status**: Not Started\n\n| 1.1 | Not Started |\n"
        post_edit = pre_edit.replace("Not Started", "In Progress")
        plan.write_text(pre_edit, encoding="utf-8")
        plan_status_snapshots.record("tu-t1", PlanStatus.NOT_STARTED, hash_plan_text(post_edit))

        plan.write_text(post_edit, encoding="utf-8")
        edit = self._edit_hook_input(
            plan, old_string="Not Started", new_string="In Progress", tool_use_id="tu-t1"
        )
        edit["tool_input"]["replace_all"] = True

        result = handler.handle(edit)

        assert result.decision == Decision.ALLOW
        assert self._signal_path().exists(), (
            "the genuine bulk flip must be detected via the snapshot's hash "
            "match, with no clock read anywhere in the freshness path"
        )

    def test_t3_write_with_unchanged_status_is_not_a_flip(
        self, handler: GoalInjectionHandler
    ) -> None:
        """probe_gf5_timebound.py T3: P already reads In Progress on disk
        (its flip landed while nothing was watching) and is not yet
        ledgered; S1 rewrites it with the Write tool WITHOUT changing its
        Status. The snapshot's ground truth (status already In Progress
        pre-write, predicted post-image unchanged) must read this as no
        transition at all -- not misread as N3's original bug (a bogus
        flip, a GOAL DISPLACED advisory, a spurious ledger entry)."""
        from claude_code_hooks_daemon.plan_qa.model import PlanStatus
        from claude_code_hooks_daemon.utils.plan_status_snapshot import (
            hash_plan_text,
            plan_status_snapshots,
        )

        plan = self._plan_path("00300-p")
        pre_edit = "# Plan 00300: p\n\n**Status**: In Progress\n\n## Tasks\n\n- [ ] a\n"
        plan.write_text(pre_edit, encoding="utf-8")
        post_edit = pre_edit + "\nA note.\n"
        plan_status_snapshots.record("tu-t3", PlanStatus.IN_PROGRESS, hash_plan_text(post_edit))

        plan.write_text(post_edit, encoding="utf-8")
        result = handler.handle(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(plan), "content": post_edit},
                "session_id": "S1",
                "tool_use_id": "tu-t3",
            }
        )

        assert result.decision == Decision.ALLOW
        assert not result.context, "a same-status rewrite must not raise a goal advisory"
        assert not self._signal_path("S1").exists(), (
            "S1 only rewrote P's body -- Status never changed, so S1 must "
            "not receive a /goal for a plan it never actually flipped"
        )

    def test_t4_write_reopening_a_complete_plan_is_a_genuine_flip(
        self, handler: GoalInjectionHandler
    ) -> None:
        """probe_gf5_timebound.py T4: P was flipped and committed In
        Progress, then completed (uncommitted) -- git HEAD still reads In
        Progress. S1 reopens P with a Write that sets it back to In
        Progress: a REAL Complete -> In Progress flip. The inference
        fallback would read this as no-transition (HEAD already says In
        Progress, RV3-m6's exact lag); the snapshot's ground truth (status
        was Complete immediately pre-write) must still catch it correctly,
        with no clock involved."""
        from claude_code_hooks_daemon.plan_qa.model import PlanStatus
        from claude_code_hooks_daemon.utils.plan_status_snapshot import (
            hash_plan_text,
            plan_status_snapshots,
        )

        plan = self._plan_path("00300-p")
        pre_edit = "# Plan 00300: p\n\n**Status**: Complete\n\n## Tasks\n\n- [ ] a\n"
        plan.write_text(pre_edit, encoding="utf-8")
        post_edit = (
            pre_edit.replace("**Status**: Complete", "**Status**: In Progress") + "\nReopened.\n"
        )
        plan_status_snapshots.record("tu-t4", PlanStatus.COMPLETE, hash_plan_text(post_edit))

        plan.write_text(post_edit, encoding="utf-8")
        result = handler.handle(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(plan), "content": post_edit},
                "session_id": "S1",
                "tool_use_id": "tu-t4",
            }
        )

        assert result.decision == Decision.ALLOW
        assert self._signal_path("S1").exists(), (
            "reopening a Complete plan back to In Progress is a genuine "
            "flip -- S1 must get a /goal naming it, regardless of what git "
            "HEAD (still In Progress from before the completion) would "
            "have implied via the inference fallback"
        )

    def test_t7_deletion_edit_is_resolved_by_the_snapshot(
        self, handler: GoalInjectionHandler
    ) -> None:
        """probe_gf5_timebound.py T7: a deletion Edit (``new_string=""``)
        yields NO reconstruction candidates at all
        (:func:`_reconstruct_pre_edit_candidates` returns ``[]`` for it),
        so the OLD reverse-reconstruction design could never judge its
        snapshot's freshness and silently fell back to the (now-removed)
        time bound. RV5-M2's forward prediction needs no reversal -- it
        just applies the deletion forward -- so a deletion Edit is resolved
        exactly like any other shape."""
        from claude_code_hooks_daemon.plan_qa.model import PlanStatus
        from claude_code_hooks_daemon.utils.plan_status_snapshot import (
            hash_plan_text,
            plan_status_snapshots,
        )

        plan = self._plan_path("00300-p")
        pre_edit = "# Plan 00300: p\n\n**Status**: Not Started\n\n- [ ] a\n"
        post_edit = pre_edit.replace("- [ ] a\n", "")
        plan.write_text(pre_edit, encoding="utf-8")
        plan_status_snapshots.record("tu-t7", PlanStatus.NOT_STARTED, hash_plan_text(post_edit))

        plan.write_text(post_edit, encoding="utf-8")
        edit = self._edit_hook_input(
            plan, old_string="- [ ] a\n", new_string="", tool_use_id="tu-t7"
        )

        result = handler.handle(edit)

        assert result.decision == Decision.ALLOW
        assert not self._signal_path().exists(), (
            "deleting a checklist line never touches Status -- must not be "
            "misread as a flip just because the deletion Edit has no "
            "reconstruction candidates"
        )


class _ReassertionFixtures:
    """Shared fixture plumbing for the reassertion test classes below.

    RV4-n5: this used to be ``TestNewSessionReassertion``'s own body, with
    every sibling class SUBCLASSING it to reuse the fixtures -- pytest then
    collected and RE-RAN ``TestNewSessionReassertion``'s own tests once per
    subclass too (108 ``def test_`` methods, 117 collected). A leading
    underscore keeps this out of pytest's ``Test*`` collection, so every
    class below inherits ONLY the fixtures, not each other's test methods.
    """

    @pytest.fixture(autouse=True)
    def mock_project_context(self, tmp_path: Path):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection."
                "ProjectContext.daemon_untracked_dir",
                classmethod(lambda cls: tmp_path / "untracked"),
            )
            mp.setattr(
                "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection."
                "ProjectContext.project_root",
                classmethod(lambda cls: tmp_path),
            )
            self._untracked = tmp_path / "untracked"
            self._project = tmp_path
            yield

    @pytest.fixture
    def handler(self) -> GoalInjectionHandler:
        return GoalInjectionHandler()

    def _plan_path(self, folder: str) -> Path:
        plan_dir = self._project / "CLAUDE" / "Plan" / folder
        plan_dir.mkdir(parents=True, exist_ok=True)
        return plan_dir / "PLAN.md"

    def _signal(self, session: str) -> dict[str, Any]:
        path = self._untracked / _SIGNAL_SUBDIR / f"{session}{_SIGNAL_SUFFIX}"
        return json.loads(path.read_text(encoding="utf-8"))

    def _edit_input(self, file_path: Path, session: str, old: str, new: str) -> dict[str, Any]:
        return {
            "tool_name": "Edit",
            "tool_input": {"file_path": str(file_path), "old_string": old, "new_string": new},
            "session_id": session,
        }

    def _clear_path(self, session: str) -> Path:
        return self._untracked / _SIGNAL_SUBDIR / f"{session}{_CLEAR_SUFFIX}"

    def _intent_path(self, session: str) -> Path:
        return self._untracked / _SIGNAL_SUBDIR / f"{session}{_SIGNAL_SUFFIX}"


class TestNewSessionReassertion(_ReassertionFixtures):
    """Review M3: Plan 00269 Task 2.1 deliberately chose "the first edit to
    an already-In-Progress plan in a NEW session re-fires" -- that is what
    made the goal survive a session restart. N3 requires a genuine
    TRANSITION to fire the full flip path, which silently dropped this: a
    resumed session got no `/goal` at all until a real flip or a manual
    `inject-goal`. Restored through ``GoalLedger.reassert_session`` --
    ownership transfer only, no displacement bookkeeping -- gated on this
    session having NO ledger entries at all, so it never fires for a
    session that already has its own live goal.
    """

    def test_a_new_session_touching_an_already_live_plan_gets_its_own_signal(
        self, handler: GoalInjectionHandler
    ) -> None:
        plan = self._plan_path("00296-first")
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")
        original_session = "sess-original"
        handler.handle(
            self._edit_input(
                plan, original_session, "**Status**: Not Started", "**Status**: In Progress"
            )
        )
        assert self._signal(original_session)  # sanity: the flip emitted

        new_session = "sess-new"
        result = handler.handle(
            self._edit_input(
                plan, new_session, "## Overview\n\nBody.", "## Overview\n\nBody.\n\nmore."
            )
        )

        assert result.decision == Decision.ALLOW
        assert not any("GOAL DISPLACED" in c for c in result.context)
        signal = self._signal(new_session)
        assert "00296" in signal["rendered_lines"][0]

    def test_a_session_with_its_own_live_goal_does_not_reassert_an_unrelated_plan(
        self, handler: GoalInjectionHandler
    ) -> None:
        """The condition is "zero entries for THIS session", not merely "not
        a flip" -- a session that already flipped its OWN plan must not
        implicitly reassert an unrelated plan on a later non-flip touch."""
        own_plan = self._plan_path("00297-own")
        own_plan.write_text(_plan_md("In Progress"), encoding="utf-8")
        session = "sess-busy"
        handler.handle(
            self._edit_input(
                own_plan, session, "**Status**: Not Started", "**Status**: In Progress"
            )
        )

        other_plan = self._plan_path("00296-other")
        other_plan.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(
                other_plan, "sess-original", "**Status**: Not Started", "**Status**: In Progress"
            )
        )

        result = handler.handle(
            self._edit_input(
                other_plan, session, "## Overview\n\nBody.", "## Overview\n\nBody.\n\nmore."
            )
        )

        assert result.decision == Decision.ALLOW
        signal = self._signal(session)
        assert "00296" not in signal["rendered_lines"][0]
        assert "00297" in signal["rendered_lines"][0]

    def test_reasserting_does_not_displace_another_live_plan(
        self, handler: GoalInjectionHandler
    ) -> None:
        plan_a = self._plan_path("00296-a")
        plan_a.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(plan_a, "sess-a", "**Status**: Not Started", "**Status**: In Progress")
        )
        plan_b = self._plan_path("00298-b")
        plan_b.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(plan_b, "sess-b", "**Status**: Not Started", "**Status**: In Progress")
        )

        new_session = "sess-new"
        handler.handle(
            self._edit_input(
                plan_a, new_session, "## Overview\n\nBody.", "## Overview\n\nBody.\n\nmore."
            )
        )

        ledger = GoalLedger(self._untracked / LEDGER_FILENAME)
        entry_b = next(e for e in ledger.entries() if e.plan_number == "00298")
        assert entry_b.displaced_by is None


class TestOwnershipSurvivesASecondSession(_ReassertionFixtures):
    """Review RV-M1: the ORIGINAL flipping session's own retraction must
    keep working after a SECOND session reasserts the same (or another)
    live plan -- the pre-fix single-owner ``reassert_session`` transfer
    broke this the moment a second session touched the plan.
    """

    def test_original_session_still_retracts_after_a_second_session_reasserts(
        self, handler: GoalInjectionHandler
    ) -> None:
        """Single plan: LEAD flips it, TEAMMATE ticks it (reasserts), LEAD
        completes it -- LEAD's OWN signal must drop the plan."""
        plan = self._plan_path("00296-single")
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(plan, "LEAD", "**Status**: Not Started", "**Status**: In Progress")
        )
        handler.handle(self._edit_input(plan, "TEAMMATE", "- [ ] a", "- [x] a"))

        plan.write_text(_plan_md("Complete"), encoding="utf-8")
        handler.handle(
            self._edit_input(plan, "LEAD", "**Status**: In Progress", "**Status**: Complete")
        )

        lead_signal_path = self._untracked / _SIGNAL_SUBDIR / f"LEAD{_SIGNAL_SUFFIX}"
        assert not lead_signal_path.exists(), (
            "LEAD's own signal survived after LEAD completed the only plan it "
            "(and TEAMMATE) ever held -- a transfer-based reassert would have "
            "stripped LEAD's ownership the moment TEAMMATE touched the plan"
        )

    def test_original_session_retracts_one_of_two_plans_after_reassertion(
        self, handler: GoalInjectionHandler
    ) -> None:
        """Two plans: LEAD flips both, TEAMMATE ticks one, LEAD completes
        that one -- LEAD's OWN combined signal must drop it but keep the
        other."""
        first = self._plan_path("00296-a")
        first.write_text(_plan_md("In Progress"), encoding="utf-8")
        second = self._plan_path("00298-b")
        second.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(first, "LEAD", "**Status**: Not Started", "**Status**: In Progress")
        )
        handler.handle(
            self._edit_input(second, "LEAD", "**Status**: Not Started", "**Status**: In Progress")
        )
        handler.handle(self._edit_input(first, "TEAMMATE", "- [ ] a", "- [x] a"))

        first.write_text(_plan_md("Complete"), encoding="utf-8")
        handler.handle(
            self._edit_input(first, "LEAD", "**Status**: In Progress", "**Status**: Complete")
        )

        joined = self._signal("LEAD")["rendered_lines"][0]
        assert "00296" not in joined
        assert "00298" in joined

    def test_second_session_can_own_a_second_plan_it_never_flipped(
        self, handler: GoalInjectionHandler
    ) -> None:
        """A session with no plan of its OWN (never real-flipped anything)
        touching a SECOND already-live plan must also become a stakeholder
        of it -- not just the first plan it happened to touch."""
        first = self._plan_path("00296-a")
        first.write_text(_plan_md("In Progress"), encoding="utf-8")
        second = self._plan_path("00298-b")
        second.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(first, "LEAD", "**Status**: Not Started", "**Status**: In Progress")
        )
        handler.handle(
            self._edit_input(second, "LEAD", "**Status**: Not Started", "**Status**: In Progress")
        )

        handler.handle(self._edit_input(first, "S2", "- [ ] a", "- [x] a"))
        handler.handle(self._edit_input(second, "S2", "- [ ] a", "- [x] a"))
        second.write_text(_plan_md("Complete"), encoding="utf-8")
        handler.handle(
            self._edit_input(second, "S2", "**Status**: In Progress", "**Status**: Complete")
        )

        joined = self._signal("S2")["rendered_lines"][0]
        assert "00298" not in joined
        assert "00296" in joined


class TestResumedSameSessionReassertion(_ReassertionFixtures):
    """Review RV-m3: a SAME-session-id resume (Claude Code's --resume /
    --continue) must also get its own signal restored, not just a
    genuinely new session id -- Plan 00269's own motivating case was a
    session resuming after a restart, which keeps its session id."""

    def test_same_session_id_after_a_restart_gets_its_signal_rewritten(
        self, handler: GoalInjectionHandler
    ) -> None:
        plan = self._plan_path("00296-first")
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")
        daemon_one = GoalInjectionHandler()
        daemon_one.handle(
            self._edit_input(plan, "S1", "**Status**: Not Started", "**Status**: In Progress")
        )
        signal_path = self._untracked / _SIGNAL_SUBDIR / f"S1{_SIGNAL_SUFFIX}"
        assert signal_path.exists(), "precondition: the real flip wrote S1's own signal"
        signal_path.unlink()  # simulate the supervisor consuming it

        # Fresh handler instance simulates a daemon restart -- _fired and
        # the new in-memory reassert latch are both empty, but the SAME
        # session id (a --resume) touches the plan again with a non-flip
        # edit.
        daemon_two = GoalInjectionHandler()
        daemon_two.handle(self._edit_input(plan, "S1", "- [ ] a", "- [x] a"))

        assert signal_path.exists(), (
            "a resumed session with the SAME session id never got its own "
            "signal file rewritten after a restart consumed it"
        )
        assert "00296" in json.loads(signal_path.read_text(encoding="utf-8"))["rendered_lines"][0]


class TestReview3Fixes(_ReassertionFixtures):
    """Review 3 (Plan 00466, subagent-reports/260924-n466-goalflip-review3-
    opus-5-5.md): RV3-M1 (major), RV3-m3, RV3-m4, RV3-m5.
    """

    # ---- RV3-M1: transition-based retirement + owning_sessions picks the
    # right entry --------------------------------------------------------

    def test_reopened_plan_completed_by_a_different_session_retracts_that_session(
        self, handler: GoalInjectionHandler
    ) -> None:
        """A4: S1 flips and completes 00296. S2 reopens it and completes it
        again. S2 -- not S1, who has nothing to do with the reopen -- must
        get its `.goal-clear`."""
        plan = self._plan_path("00296-first")
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(plan, "S1", "**Status**: Not Started", "**Status**: In Progress")
        )
        plan.write_text(_plan_md("Complete"), encoding="utf-8")
        handler.handle(
            self._edit_input(plan, "S1", "**Status**: In Progress", "**Status**: Complete")
        )
        assert self._clear_path("S1").exists()
        self._clear_path("S1").unlink()

        # S2 reopens (Complete -> In Progress) and completes it again.
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(plan, "S2", "**Status**: Complete", "**Status**: In Progress")
        )
        plan.write_text(_plan_md("Complete"), encoding="utf-8")
        handler.handle(
            self._edit_input(plan, "S2", "**Status**: In Progress", "**Status**: Complete")
        )

        assert self._clear_path(
            "S2"
        ).exists(), "S2 reopened and recompleted the plan -- it must get its own .goal-clear"
        assert not self._clear_path(
            "S1"
        ).exists(), "S1 has nothing to do with the reopen and must not be re-signalled"

    def test_reopened_plan_completion_does_not_signal_an_unrelated_owner(
        self, handler: GoalInjectionHandler
    ) -> None:
        """A4b: as above, plus a second live plan owned only by S3 -- S1
        must not be handed a fresh goal naming a plan it never touched."""
        plan = self._plan_path("00296-first")
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(plan, "S1", "**Status**: Not Started", "**Status**: In Progress")
        )
        plan.write_text(_plan_md("Complete"), encoding="utf-8")
        handler.handle(
            self._edit_input(plan, "S1", "**Status**: In Progress", "**Status**: Complete")
        )
        self._clear_path("S1").unlink(missing_ok=True)

        other = self._plan_path("00298-other")
        other.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(other, "S3", "**Status**: Not Started", "**Status**: In Progress")
        )

        plan.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(plan, "S2", "**Status**: Complete", "**Status**: In Progress")
        )
        plan.write_text(_plan_md("Complete"), encoding="utf-8")
        handler.handle(
            self._edit_input(plan, "S2", "**Status**: In Progress", "**Status**: Complete")
        )

        assert not self._intent_path("S1").exists(), (
            "S1 must not receive a fresh goal-intent naming 00298 -- it never " "touched that plan"
        )
        assert not self._clear_path("S1").exists()

    def test_note_on_an_already_complete_plan_signals_nobody(
        self, handler: GoalInjectionHandler
    ) -> None:
        """X2: S1 completed 00296 and consumed its .goal-clear. An unrelated
        session edits the still-Complete, not-yet-archived plan (a note, no
        status change) -- this must not resurrect a signal for S1."""
        plan = self._plan_path("00296-first")
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(plan, "S1", "**Status**: Not Started", "**Status**: In Progress")
        )
        plan.write_text(_plan_md("Complete"), encoding="utf-8")
        handler.handle(
            self._edit_input(plan, "S1", "**Status**: In Progress", "**Status**: Complete")
        )
        self._clear_path("S1").unlink()  # simulate the supervisor consuming it

        handler.handle(
            self._edit_input(plan, "X", "## Overview\n\nBody.", "## Overview\n\nBody.\n\nNote.")
        )

        assert not self._clear_path(
            "S1"
        ).exists(), "an edit that changed no status must not re-signal S1 at all"

    def test_note_on_an_already_complete_plan_does_not_clear_a_manual_goal(
        self, handler: GoalInjectionHandler
    ) -> None:
        """X7: S1 completed 00296, then ran a manual inject-goal for an
        unledgered 00301 -- a later note-only edit to the still-Complete
        00296 must not type `/goal clear` over S1's manual goal."""
        plan = self._plan_path("00296-first")
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(plan, "S1", "**Status**: Not Started", "**Status**: In Progress")
        )
        plan.write_text(_plan_md("Complete"), encoding="utf-8")
        handler.handle(
            self._edit_input(plan, "S1", "**Status**: In Progress", "**Status**: Complete")
        )
        self._clear_path("S1").unlink()
        # Simulate the manual inject-goal CLI tool's own write for 00301.
        write_goal_signal("S1", "00301", "manual goal for 00301", _SOURCE_CLI)
        assert self._intent_path("S1").exists()

        handler.handle(
            self._edit_input(plan, "X", "## Overview\n\nBody.", "## Overview\n\nBody.\n\nNote.")
        )

        assert not self._clear_path("S1").exists(), (
            "the note-only edit must not tell the supervisor to clear S1's "
            "manual goal for an unrelated plan"
        )
        assert self._intent_path("S1").exists(), "S1's manual goal-intent must survive untouched"

    # ---- RV3-m3: a session's OWN combined signal names a plan it does not
    # own -- it must become an owner of every plan it is told about -------

    def test_a_session_becomes_an_owner_of_every_plan_its_own_signal_names(
        self, handler: GoalInjectionHandler
    ) -> None:
        """X1: S1 flips 00296. S3 flips 00298 and its OWN combined signal
        names both 00296 and 00298 -- S3 must become an owner of 00296 too,
        so S1 completing 00296 later refreshes S3's stale text."""
        first = self._plan_path("00296-first")
        first.write_text(_plan_md("In Progress"), encoding="utf-8")
        second = self._plan_path("00298-second")
        second.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(first, "S1", "**Status**: Not Started", "**Status**: In Progress")
        )
        handler.handle(
            self._edit_input(second, "S3", "**Status**: Not Started", "**Status**: In Progress")
        )
        joined = self._signal("S3")["rendered_lines"][0]
        assert "00296" in joined and "00298" in joined  # sanity: combined text

        first.write_text(_plan_md("Complete"), encoding="utf-8")
        handler.handle(
            self._edit_input(first, "S1", "**Status**: In Progress", "**Status**: Complete")
        )

        refreshed = self._signal("S3")["rendered_lines"][0]
        assert "00296" not in refreshed, "S3 was never refreshed for a plan its own text named"
        assert "00298" in refreshed

    # ---- RV3-m4: the flip path must set the reassert latch too, and both
    # latch maps must be bounded ------------------------------------------

    def test_a_same_session_edit_right_after_its_own_flip_emits_nothing(
        self, handler: GoalInjectionHandler
    ) -> None:
        """B2/C9: the session that just flipped a plan adds a table row in
        the SAME daemon lifetime -- this must not write a second signal."""
        plan = self._plan_path("00296-first")
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(plan, "S1", "**Status**: Not Started", "**Status**: In Progress")
        )
        first_mtime = self._intent_path("S1").stat().st_mtime_ns
        self._intent_path("S1").unlink()

        handler.handle(self._edit_input(plan, "S1", "- [ ] a", "- [x] a"))

        assert not self._intent_path("S1").exists(), (
            f"a redundant signal was written after the flip's own latch "
            f"should already cover this (first_mtime={first_mtime})"
        )

    def test_reassert_latch_map_is_bounded(self, handler: GoalInjectionHandler) -> None:
        """B5: many distinct sessions reasserting must not grow the
        in-memory reassert latch map without bound."""
        plan = self._plan_path("00296-first")
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(
                plan, "sess-original", "**Status**: Not Started", "**Status**: In Progress"
            )
        )

        for i in range(400):
            handler.handle(self._edit_input(plan, f"sess-{i}", "- [ ] a", "- [x] a"))

        assert len(handler._reasserted) <= 256

    # ---- RV3-m5: plan ownership must be bounded, and refreshing many
    # owners must render the combined text ONCE, not once per owner -------

    def test_plan_ownership_is_bounded(self, handler: GoalInjectionHandler) -> None:
        """A5: 150 distinct sessions each reassert the same live plan --
        ``sessions`` must not grow without bound (the 100-entry ledger cap
        bounds ENTRIES, not owners within one)."""
        plan = self._plan_path("00296-first")
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(
                plan, "sess-original", "**Status**: Not Started", "**Status**: In Progress"
            )
        )

        for i in range(150):
            handler.handle(self._edit_input(plan, f"teammate-{i}", "- [ ] a", "- [x] a"))

        ledger = GoalLedger(self._untracked / LEDGER_FILENAME)
        owners = ledger.owning_sessions("00296")
        assert len(owners) < 151, "plan ownership grew without bound across 150 reasserts"

    def test_refreshing_many_owners_renders_the_combined_text_once(
        self, handler: GoalInjectionHandler
    ) -> None:
        """A5's timing half: refreshing N owners on a terminal write must
        not re-derive the combined text (a full live-plan-dir scan) once
        PER owner -- it should render once and write N times."""
        import time as _time

        plan = self._plan_path("00296-first")
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(
                plan, "sess-original", "**Status**: Not Started", "**Status**: In Progress"
            )
        )
        for i in range(150):
            handler.handle(self._edit_input(plan, f"teammate-{i}", "- [ ] a", "- [x] a"))

        plan.write_text(_plan_md("Complete"), encoding="utf-8")
        started = _time.monotonic()
        handler.handle(
            self._edit_input(
                plan, "sess-original", "**Status**: In Progress", "**Status**: Complete"
            )
        )
        elapsed = _time.monotonic() - started

        assert elapsed < 0.1, f"retirement refresh took {elapsed:.3f}s for ~150 owners"

    # ---- RV3-m8: a non-UTF-8 sibling plan must not crash a real dispatch -

    def test_non_utf8_sibling_plan_does_not_crash_a_reassert(
        self, handler: GoalInjectionHandler
    ) -> None:
        first = self._plan_path("00296-first")
        first.write_text(_plan_md("In Progress"), encoding="utf-8")
        bad = self._plan_path("00298-bad")
        bad.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(first, "S1", "**Status**: Not Started", "**Status**: In Progress")
        )
        handler.handle(
            self._edit_input(bad, "S3", "**Status**: Not Started", "**Status**: In Progress")
        )
        bad.write_bytes(b"\xff\xfe\x00\x01not valid utf-8")

        # A fresh session touches the (still-readable) first plan without
        # flipping it -- the reassert path must tolerate the unreadable
        # sibling when it renders the combined signal.
        result = handler.handle(self._edit_input(first, "S9", "- [ ] a", "- [x] a"))

        assert result.decision == Decision.ALLOW


class TestReview4Fixes(_ReassertionFixtures):
    """Review 4 (Plan 00466, subagent-reports/260924-n466-goalflip-review4-
    opus-5-5.md): RV4-M1 (major) -- the RV3-m5 owner cap (50) combined with
    RV3-m3's combined-signal absorption could evict the FLIPPING session
    from its own plan's owner set once enough OTHER sessions touched any
    live plan, so completing the plan never refreshed the flipper's own
    `/goal`. Fixed by pinning the flipper as the entry's ``primary_owner``,
    exempt from the FIFO cap, and by always refreshing the completing
    write's own session regardless of what the ledger's owner set says.
    """

    @staticmethod
    def _tick(handler: GoalInjectionHandler, path: Path, session: str, old: str, new: str):
        text = path.read_text(encoding="utf-8")
        assert text.count(old) == 1, f"fixture drift: {old!r} x{text.count(old)}"
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        edit_input = {
            "tool_name": "Edit",
            "tool_input": {"file_path": str(path), "old_string": old, "new_string": new},
            "session_id": session,
        }
        return handler.handle(edit_input)

    def test_flipper_survives_absorption_past_the_owner_cap(
        self, handler: GoalInjectionHandler
    ) -> None:
        """probe_gf4_evict2.py's E2: L flips 00296, S flips 00298. 50
        teammates tick 00298 -- each becomes an owner of BOTH live plans
        via ``_extend_ownership``'s combined-signal absorption (RV3-m3).
        Before the fix, the 50-owner FIFO cap evicted L (the original
        flipper of 00296) once the 50th teammate was absorbed. L must
        still be refreshed when L itself completes 00296."""
        a = self._plan_path("00296-a")
        a.write_text(_plan_md("In Progress"), encoding="utf-8")
        b_path = self._plan_path("00298-b")
        b_body = "# Plan 00298: b\n\n**Status**: Not Started\n\n## Tasks\n\ncounter: 0\n"
        b_path.write_text(b_body, encoding="utf-8")

        handler.handle(
            self._edit_input(a, "L", "**Status**: Not Started", "**Status**: In Progress")
        )
        self._tick(handler, b_path, "S", "**Status**: Not Started", "**Status**: In Progress")

        for i in range(50):
            self._tick(handler, b_path, f"TM{i:03d}", f"counter: {i}", f"counter: {i + 1}")

        ledger = GoalLedger(self._untracked / LEDGER_FILENAME)
        entry_a = next(e for e in ledger.entries() if e.plan_number == "00296")
        assert "L" in entry_a.sessions, (
            "L (the flipper) was evicted from its own plan's owner set by "
            "absorbing 50 unrelated teammates -- primary_owner must pin it"
        )

        a.write_text(_plan_md("Complete"), encoding="utf-8")
        handler.handle(self._edit_input(a, "L", "**Status**: In Progress", "**Status**: Complete"))

        # 00298 is still live, so L's OWN signal is refreshed to the new
        # combined view (matching probe_gf4_evict2.py: "L gets names
        # 00298, which is correct") -- not cleared outright, and crucially
        # not left stale still naming the plan L itself just completed.
        joined = self._signal("L")["rendered_lines"][0]
        assert "00296" not in joined, (
            "L's own signal still names the plan it just completed -- it "
            "was silently skipped by the retirement refresh"
        )
        assert "00298" in joined

    def test_a_non_owner_completer_gets_no_goal(self, handler: GoalInjectionHandler) -> None:
        """RV5-M1/K1: U never owned 00296 and has no goal of its own. U
        completing 00296 (a teammate's Plan Completion Checklist box) while
        00298 is still live must NOT hand U a `/goal` naming 00298 -- U
        never had a stake in either plan, and nothing later would ever
        retract it (main's behaviour: no signal at all)."""
        a = self._plan_path("00296-a")
        b = self._plan_path("00298-b")
        a.write_text(_plan_md("In Progress"), encoding="utf-8")
        b_not_started = "# Plan 00298: b\n\n**Status**: Not Started\n\n## Tasks\n\ncounter: 0\n"
        b.write_text(b_not_started, encoding="utf-8")
        handler.handle(
            self._edit_input(a, "S2", "**Status**: Not Started", "**Status**: In Progress")
        )
        # PostToolUse dispatches AFTER the tool already landed the edit, so
        # b's on-disk content must already read the POST-edit ("In
        # Progress") state before this call -- otherwise `new_string` is
        # not found in the post-edit text and the reconstruction check
        # reads this as "not a transition" (B silently never goes live).
        b.write_text(b_not_started.replace("Not Started", "In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(b, "S3", "**Status**: Not Started", "**Status**: In Progress")
        )

        a.write_text(_plan_md("Complete"), encoding="utf-8")
        handler.handle(self._edit_input(a, "U", "**Status**: In Progress", "**Status**: Complete"))

        assert not self._intent_path("U").exists(), (
            "U never owned 00296 -- completing it must not hand U a /goal "
            "for 00298 or any other plan"
        )
        assert not self._clear_path("U").exists()

        # And that must hold PERMANENTLY, not just until the next retirement:
        b.write_text(_plan_md("Complete"), encoding="utf-8")
        handler.handle(self._edit_input(b, "S3", "**Status**: In Progress", "**Status**: Complete"))

        assert not self._intent_path("U").exists(), (
            "U must still have no goal after 00298 also completes -- RV5-M1's "
            "regression left U permanently naming a plan it never owned"
        )

    def test_a_manual_goal_survives_an_unrelated_plans_completion(
        self, handler: GoalInjectionHandler
    ) -> None:
        """RV5-M1/K2: U holds a manually injected goal for 00400
        (`inject-goal`, no ledger entry). U then completes 00296, the only
        LEDGERED live plan. U's manual goal must be left completely
        untouched -- U was never an owner of 00296, so this retirement has
        no business touching U's signal at all."""
        a = self._plan_path("00296-a")
        a.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(a, "S2", "**Status**: Not Started", "**Status**: In Progress")
        )
        write_goal_signal("U", "00400", "manual goal for 00400", _SOURCE_CLI)

        a.write_text(_plan_md("Complete"), encoding="utf-8")
        handler.handle(self._edit_input(a, "U", "**Status**: In Progress", "**Status**: Complete"))

        assert not self._clear_path("U").exists(), (
            "U's manual inject-goal signal must not be cleared by a plan U "
            "never owned completing"
        )
        signal = self._signal("U")
        assert signal["rendered_lines"] == ["manual goal for 00400"]

    def test_terminal_transition_ignores_a_fenced_in_progress_example_in_the_post_edit_text(
        self, handler: GoalInjectionHandler
    ) -> None:
        """RV3-m2 pin: ``handle()``'s post-write gate (:meth:`GoalInjectionHandler.
        handle`, the ``PlanDoc.parse(plan_text).status`` check right before
        the retirement branch) must decide "still In Progress?" from the
        REAL Status line, not a literal ``'**Status**: In Progress' in
        plan_text`` substring check -- probe_gf4_mutate.py's "RV3-m2 post-
        state by literal substring, not PlanDoc" mutant. C7b/C8 above pin
        the pre-write side of this same distinction; this pins the
        POST-write side the retirement path depends on.

        The plan's real Status line reads Complete, but the body also
        carries a fenced example reading '**Status**: In Progress' (the
        same collision shape C7b uses). The literal-substring mutant would
        see that fenced text and wrongly conclude the plan is still In
        Progress, skipping the retirement refresh entirely -- L's own
        signal would stay stale, still naming the plan it just completed,
        instead of being retracted.

        A pre-write snapshot is recorded for this same ``tool_use_id`` so
        the INNER real-transition check (:meth:`_resolve_transition`) is
        answered from ground truth rather than reconstruction -- the fenced
        example's byte-identical Status line would otherwise also trip
        RV3-m1's per-candidate uniqueness filter there, which is a
        different, already-pinned defence (C7b/C8) and not what this test
        targets.

        RV5-m5: ``old_string='**Status**: In Progress'`` occurs TWICE in
        this plan's own pre-edit text (the real line and the fenced
        example) -- a real Edit tool call with a non-unique ``old_string``
        is REJECTED before this handler ever sees it, so that shape is not
        a call this handler needs to survive. The edit below instead uses
        ``old_string='**Status**: In Progress\\n\\nExample'``, unique in
        the pre-edit text, so this pin exercises the same genuine snapshot
        (hash) path a real Edit call would take."""
        from claude_code_hooks_daemon.plan_qa.model import PlanStatus
        from claude_code_hooks_daemon.utils.plan_status_snapshot import (
            hash_plan_text,
            plan_status_snapshots,
        )

        plan = self._plan_path("00296-a")
        plan.write_text(_plan_md("In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(plan, "L", "**Status**: Not Started", "**Status**: In Progress")
        )
        assert self._signal("L")  # sanity: the flip emitted

        pre_edit = (
            "# Plan 00296: a\n\n**Status**: In Progress\n\n"
            "Example:\n\n```markdown\n**Status**: In Progress\n```\n\nBody.\n"
        )
        old_string = "**Status**: In Progress\n\nExample"
        new_string = "**Status**: Complete\n\nExample"
        post_edit = pre_edit.replace(old_string, new_string)
        plan.write_text(post_edit, encoding="utf-8")
        # RV5-M2: the recorded hash is of the PREDICTED post-image, which
        # is exactly what the write above just landed on disk.
        plan_status_snapshots.record(
            "tu-rv3m2-pin", PlanStatus.IN_PROGRESS, hash_plan_text(post_edit)
        )
        edit_input = self._edit_input(plan, "L", old_string, new_string)
        edit_input["tool_use_id"] = "tu-rv3m2-pin"
        handler.handle(edit_input)

        assert self._clear_path("L").exists(), (
            "a fenced '**Status**: In Progress' example in the post-edit "
            "text made the retirement refresh look skippable -- the real "
            "(non-fenced) Status line reads Complete and must still "
            "retract L's own signal"
        )

    def test_a_retirement_refreshed_owner_becomes_an_owner_of_the_plans_its_text_names(
        self, handler: GoalInjectionHandler
    ) -> None:
        """RV5-m4/K4: S1 flips A (00296), S3 flips B (00298). S1 completes
        A while B is still live -- the retirement refresh writes S1's
        combined text naming B, but (before this fix) never made S1 an
        OWNER of B. So B's own later completion left S1 stale, still
        naming a plan long since retired -- breaking RV3-m3's own
        invariant that a session reading a plan's number in its own text
        is refreshed when that plan completes."""
        a = self._plan_path("00296-a")
        b = self._plan_path("00298-b")
        a.write_text(_plan_md("In Progress"), encoding="utf-8")
        b_not_started = "# Plan 00298: b\n\n**Status**: Not Started\n\n## Tasks\n\ncounter: 0\n"
        b.write_text(b_not_started, encoding="utf-8")
        handler.handle(
            self._edit_input(a, "S1", "**Status**: Not Started", "**Status**: In Progress")
        )
        # PostToolUse dispatches AFTER the tool already landed the edit --
        # b's on-disk content must read the POST-edit state first.
        b.write_text(b_not_started.replace("Not Started", "In Progress"), encoding="utf-8")
        handler.handle(
            self._edit_input(b, "S3", "**Status**: Not Started", "**Status**: In Progress")
        )

        a.write_text(_plan_md("Complete"), encoding="utf-8")
        handler.handle(self._edit_input(a, "S1", "**Status**: In Progress", "**Status**: Complete"))
        joined = self._signal("S1")["rendered_lines"][0]
        assert "00298" in joined  # sanity: S1's combined text names B

        b.write_text(_plan_md("Complete"), encoding="utf-8")
        handler.handle(self._edit_input(b, "S3", "**Status**: In Progress", "**Status**: Complete"))

        assert self._clear_path("S1").exists(), (
            "S1's combined text named B -- S1 must have been made an owner "
            "of B, so B's own completion retracts S1's now-stale signal"
        )
