"""Unit tests for the GoalInjectionHandler (Plan 00269).

RED-first TDD file. The handler detects a ``PLAN.md`` Write/Edit whose
resulting ``**Status**:`` reads ``In Progress`` (active plan dir only, never
``Completed/``), renders the configured goal lines with validated
placeholders, joins them into ONE physical line, and atomically writes a
``<session>.goal-intent`` signal for the ccy PTY supervisor. Latched once per
``(plan, session)`` per daemon process. Never blocks. Opt-in
(``get_default_enabled() -> False``).
"""

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.goal_injection import (
    _HEADER_TEXT,
    _LOGICAL_LINE_SEPARATOR,
    _MAX_JOINED_CHARS,
    _SIGNAL_SUBDIR,
    _SIGNAL_SUFFIX,
    _SOURCE_STATUS_FLIP,
    GoalInjectionHandler,
    render_goal_line,
    write_goal_signal,
)

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
        assert "until completion" not in joined

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
        assert "until completion" not in joined

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


class TestGoalInjectionHandler:
    @pytest.fixture(autouse=True)
    def mock_project_context(self, tmp_path: Path):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection."
                "ProjectContext.daemon_untracked_dir",
                classmethod(lambda cls: tmp_path / "untracked"),
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
        handler._once_per_plan_per_session = False
        plan = self._write_plan()
        handler.handle(self._hook_input(plan))
        self._signal_path().unlink()
        handler.handle(self._hook_input(plan))
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
            "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection." "write_goal_signal",
            lambda *a, **k: None,
        )
        result = handler.handle(self._hook_input(plan))
        assert result.decision == Decision.ALLOW
