"""Tests for goal-clear attribution (Plan 00501 Task 8.2).

A typed ``/goal clear`` leaves no ``UserPromptSubmit`` (Task 8.1): it is a
``system``/``local_command`` record in the transcript, read at the next Stop.
The ccy supervisor writes a ``<session>.goal-clear-injected`` record before it
types one, so a fresh matching record means the supervisor cleared it, no
record means a human did, and an unreadable record is taken as the
supervisor's, logged at WARNING with one line telling the human to repeat it.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.goal_clear_attribution import (
    CLEARING_TOKENS,
    CLOCK_TOLERANCE_SECONDS,
    FRESH_WINDOW_SECONDS,
    GOAL_CLEAR_RECORD_SUFFIX,
    Attribution,
    ClearRecord,
    ClearRecordUnreadableError,
    GoalClearAttributionError,
    TypedClear,
    attribute_clear,
    attributed_keys,
    find_typed_clears,
    read_clear_record,
    record_path,
)
from claude_code_hooks_daemon.core.session_mode_log import ModeTransition, TransitionAction
from claude_code_hooks_daemon.utils.session_modes import ModeLabel

SESSION = "00000000-0000-0000-0000-000000000000"
CLEAR_AT = datetime(2026, 10, 11, 15, 2, 59, 218000, tzinfo=UTC).timestamp()


def _command(args: str = "clear", *, uuid: str | None = "u-1", stamp: str | None = None) -> str:
    """The first record of the pair, as Claude Code 2.1.296 writes it."""
    record: dict[str, object] = {
        "type": "system",
        "subtype": "local_command",
        "content": (
            "<command-name>/goal</command-name>\n            <command-message>goal"
            f"</command-message>\n            <command-args>{args}</command-args>"
        ),
        "timestamp": stamp if stamp is not None else "2026-10-11T15:02:59.218Z",
    }
    if uuid is not None:
        record["uuid"] = uuid
    return json.dumps(record)


def _stdout(text: str = "Goal cleared: x") -> str:
    return json.dumps(
        {
            "type": "system",
            "subtype": "local_command",
            "content": f"<local-command-stdout>{text}</local-command-stdout>",
            "timestamp": "2026-10-11T15:02:59.218Z",
            "uuid": "u-2",
            "commandRun": {"command": "goal", "args": "clear"},
        }
    )


def _write_record(
    directory: Path,
    *,
    session: str = SESSION,
    ts: float = CLEAR_AT - 1.0,
    command: str = "/goal clear",
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = record_path(directory, SESSION)
    path.write_text(
        json.dumps({"session_id": session, "ts": ts, "command": command}), encoding="utf-8"
    )
    return path


class TestConstants:
    def test_clearing_tokens_are_the_upstream_set(self) -> None:
        assert frozenset({"clear", "stop", "off", "reset", "none", "cancel"}) == CLEARING_TOKENS

    def test_window_is_named_and_bounded(self) -> None:
        assert 0 < CLOCK_TOLERANCE_SECONDS < FRESH_WINDOW_SECONDS <= 300

    def test_record_suffix_is_not_a_goal_clear_trigger(self) -> None:
        # The supervisor globs ``*.goal-clear`` for its triggers; the record must not match.
        assert GOAL_CLEAR_RECORD_SUFFIX == ".goal-clear-injected"
        assert not Path(f"x{GOAL_CLEAR_RECORD_SUFFIX}").match("*.goal-clear")

    def test_record_path_uses_the_session_stem(self, tmp_path: Path) -> None:
        assert record_path(tmp_path, "a/b").name == f"a_b{GOAL_CLEAR_RECORD_SUFFIX}"


class TestFindTypedClears:
    def test_the_real_pair_yields_one_clear(self) -> None:
        clears = find_typed_clears([_command(), _stdout()])
        assert clears == (TypedClear(key="u-1", at=CLEAR_AT, argument="clear"),)

    @pytest.mark.parametrize("args", ["stop", "OFF", " reset ", "None", "cancel"])
    def test_every_alias_is_a_clear(self, args: str) -> None:
        (clear,) = find_typed_clears([_command(args)])
        assert clear.argument == args.strip().lower()

    @pytest.mark.parametrize("args", ["", "finish plan 00501", "clear the backlog"])
    def test_a_set_or_status_is_not_a_clear(self, args: str) -> None:
        assert find_typed_clears([_command(args)]) == ()

    def test_other_commands_and_records_are_ignored(self) -> None:
        other = _command().replace("/goal</command-name>", "/model</command-name>")
        user = json.dumps({"type": "user", "message": {"content": "/goal clear"}})
        no_content = json.dumps({"type": "system", "subtype": "local_command"})
        assert find_typed_clears([other, user, no_content, "", "not json", "[1]"]) == ()

    def test_no_uuid_keys_by_timestamp(self) -> None:
        (clear,) = find_typed_clears([_command(uuid=None)])
        assert clear.key == "ts=2026-10-11T15:02:59.218Z"

    def test_a_clear_without_a_usable_timestamp_raises(self) -> None:
        with pytest.raises(GoalClearAttributionError, match="timestamp"):
            find_typed_clears([_command(stamp="yesterday")])


class TestReadClearRecord:
    def test_missing_is_none(self, tmp_path: Path) -> None:
        assert read_clear_record(tmp_path / "absent") is None

    def test_round_trip(self, tmp_path: Path) -> None:
        path = _write_record(tmp_path)
        assert read_clear_record(path) == ClearRecord(
            session=SESSION, ts=CLEAR_AT - 1.0, command="/goal clear"
        )

    @pytest.mark.parametrize(
        "text",
        [
            "{not json",
            "[]",
            json.dumps({"session_id": SESSION, "ts": 1.0}),
            json.dumps({"session_id": SESSION, "ts": "soon", "command": "/goal clear"}),
            json.dumps({"session_id": SESSION, "ts": True, "command": "/goal clear"}),
            json.dumps({"session_id": 7, "ts": 1.0, "command": "/goal clear"}),
            json.dumps({"session_id": SESSION, "ts": float("nan"), "command": "/goal clear"}),
        ],
    )
    def test_malformed_is_unreadable(self, tmp_path: Path, text: str) -> None:
        path = tmp_path / "rec"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ClearRecordUnreadableError):
            read_clear_record(path)

    def test_an_os_error_is_unreadable(self, tmp_path: Path) -> None:
        path = tmp_path / "rec"
        path.mkdir()
        with pytest.raises(ClearRecordUnreadableError):
            read_clear_record(path)


def _clear(args: str = "clear", at: float = CLEAR_AT) -> TypedClear:
    return TypedClear(key="u-1", at=at, argument=args)


class TestAttributeClear:
    def test_fresh_matching_record_is_the_supervisor_and_is_consumed(self, tmp_path: Path) -> None:
        path = _write_record(tmp_path)
        verdict = attribute_clear(_clear(), session_id=SESSION, directory=tmp_path)
        assert verdict.attribution is Attribution.SUPERVISOR
        assert verdict.line() is None
        assert not path.exists()

    def test_no_record_is_a_human(self, tmp_path: Path) -> None:
        verdict = attribute_clear(_clear(), session_id=SESSION, directory=tmp_path)
        assert verdict.attribution is Attribution.HUMAN
        assert "record=none" in verdict.evidence
        assert verdict.line() is None

    def test_a_stale_record_is_a_human_and_is_kept(self, tmp_path: Path) -> None:
        path = _write_record(tmp_path, ts=CLEAR_AT - FRESH_WINDOW_SECONDS - 1.0)
        verdict = attribute_clear(_clear(), session_id=SESSION, directory=tmp_path)
        assert verdict.attribution is Attribution.HUMAN
        assert "record=stale" in verdict.evidence
        assert path.exists()

    def test_a_record_from_after_the_clear_is_not_fresh(self, tmp_path: Path) -> None:
        _write_record(tmp_path, ts=CLEAR_AT + CLOCK_TOLERANCE_SECONDS + 1.0)
        verdict = attribute_clear(_clear(), session_id=SESSION, directory=tmp_path)
        assert verdict.attribution is Attribution.HUMAN

    def test_within_the_clock_tolerance_is_fresh(self, tmp_path: Path) -> None:
        _write_record(tmp_path, ts=CLEAR_AT + CLOCK_TOLERANCE_SECONDS / 2)
        verdict = attribute_clear(_clear(), session_id=SESSION, directory=tmp_path)
        assert verdict.attribution is Attribution.SUPERVISOR

    def test_a_clear_stamped_before_the_record_is_a_human_and_keeps_the_record(
        self, tmp_path: Path
    ) -> None:
        # Plan 00501 act-mode run: the owner's clear was stamped half a second before
        # the supervisor's record. The record is written BEFORE the supervisor types,
        # so a clear stamped earlier than it cannot be the supervisor's.
        path = _write_record(tmp_path, ts=CLEAR_AT + 0.5)
        verdict = attribute_clear(_clear(), session_id=SESSION, directory=tmp_path)
        assert verdict.attribution is Attribution.HUMAN
        assert "record=stale" in verdict.evidence
        assert path.exists(), "the record still belongs to the supervisor's own clear"

    def test_a_human_clear_then_the_supervisor_clear_are_each_attributed(
        self, tmp_path: Path
    ) -> None:
        # The double clear: the human types, then the supervisor's pending tick types too.
        _write_record(tmp_path, ts=CLEAR_AT + 0.5)
        human = attribute_clear(_clear(), session_id=SESSION, directory=tmp_path)
        supervisor = attribute_clear(
            TypedClear(key="u-3", at=CLEAR_AT + 0.7, argument="clear"),
            session_id=SESSION,
            directory=tmp_path,
        )
        assert (human.attribution, supervisor.attribution) == (
            Attribution.HUMAN,
            Attribution.SUPERVISOR,
        )

    def test_a_stamp_truncated_to_the_millisecond_is_still_the_supervisor(
        self, tmp_path: Path
    ) -> None:
        # The transcript floors to whole milliseconds, so the supervisor's own clear
        # can read up to 1 ms earlier than the record written before it.
        _write_record(tmp_path, ts=CLEAR_AT + 0.0009)
        verdict = attribute_clear(_clear(), session_id=SESSION, directory=tmp_path)
        assert verdict.attribution is Attribution.SUPERVISOR

    def test_a_different_command_is_a_human(self, tmp_path: Path) -> None:
        _write_record(tmp_path)
        verdict = attribute_clear(_clear("stop"), session_id=SESSION, directory=tmp_path)
        assert verdict.attribution is Attribution.HUMAN
        assert "record=mismatch" in verdict.evidence

    def test_a_record_naming_another_session_is_a_human(self, tmp_path: Path) -> None:
        _write_record(tmp_path, session="someone-else")
        verdict = attribute_clear(_clear(), session_id=SESSION, directory=tmp_path)
        assert verdict.attribution is Attribution.HUMAN
        assert "record=mismatch" in verdict.evidence

    def test_unreadable_is_the_supervisor_at_warning_with_one_line(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = record_path(tmp_path, SESSION)
        path.write_text("{garbled", encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            verdict = attribute_clear(_clear(), session_id=SESSION, directory=tmp_path)
        assert verdict.attribution is Attribution.SUPERVISOR_ASSUMED
        assert any(
            r.levelno == logging.WARNING and "unreadable" in r.getMessage() for r in caplog.records
        )
        line = verdict.line()
        assert line is not None
        assert "/goal clear" in line and "again" in line
        assert not path.exists(), "an unreadable record attributes one clear, not every later one"

    def test_a_blank_session_raises(self, tmp_path: Path) -> None:
        with pytest.raises(GoalClearAttributionError, match="session"):
            attribute_clear(_clear(), session_id=" ", directory=tmp_path)


class TestTransition:
    def test_transition_carries_the_attribution(self, tmp_path: Path) -> None:
        verdict = attribute_clear(_clear(), session_id=SESSION, directory=tmp_path)
        transition = verdict.transition(SESSION)
        assert transition.label is ModeLabel.MANUAL_GOALS
        assert transition.action is TransitionAction.GOAL_CLEAR
        assert transition.detail == str(Attribution.HUMAN)
        assert transition.at == CLEAR_AT
        # Round-trips through the log's own parser.
        assert ModeTransition.from_record(transition.to_record()) == transition

    def test_attributed_keys_reads_back_the_clear_key(self, tmp_path: Path) -> None:
        verdict = attribute_clear(_clear(), session_id=SESSION, directory=tmp_path)
        other = ModeTransition(
            at=1.0,
            session_id=SESSION,
            label=ModeLabel.FOCUS,
            action=TransitionAction.ENTER,
            evidence="clear=u-9 but not a goal-clear action",
        )
        assert attributed_keys([verdict.transition(SESSION), other]) == frozenset({"u-1"})
