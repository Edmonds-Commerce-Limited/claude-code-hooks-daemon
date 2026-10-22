"""Tests for the session-modes registry (Plan 00501 Task 1.2).

The registry holds each session's focus/blocked entries in memory and writes
them through to one file per session, so a daemon restart can tell which modes
survive (``session`` lifetime) and which are cleared (``daemon`` lifetime).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core.session_mode_log import (
    ModeTransition,
    TransitionAction,
    TransitionLog,
)
from claude_code_hooks_daemon.core.session_mode_registry import (
    CORRUPT_SUFFIX,
    FIELD_DETAIL,
    FIELD_ENTERED_AT,
    FIELD_EXPIRES_AT,
    FIELD_LIFETIME,
    FIELD_MODE,
    FIELD_MODES,
    FIELD_REASON,
    FIELD_SESSION_ID,
    FIELD_SOURCE,
    FIELD_VERSION,
    FIRST_PROMPT_WINDOW_SECONDS,
    SCHEMA_VERSION,
    SESSION_MODES_SUFFIX,
    ModeNotice,
    NoticeKind,
    SessionModeRegistry,
    import_legacy_blockage_marker,
)
from claude_code_hooks_daemon.utils.blockage_marker import MARKER_FILENAME, write_marker
from claude_code_hooks_daemon.utils.session_modes import (
    DECLARED_BLOCKED_TTL_SECONDS,
    FOCUS_TTL_SECONDS,
    BlockReason,
    Lifetime,
    ModeLabel,
    ModeSource,
    SessionMode,
    SessionModeEntry,
    declared_blocked_entry,
)
from claude_code_hooks_daemon.utils.usage_pause import MAX_PAUSE_SPAN_SECONDS, PAUSE_GRACE_SECONDS

SID = "session-a"
OTHER = "session-b"
T0 = 1_000_000.0


class FakeClock:
    """A settable clock for the registry."""

    def __init__(self, now: float = T0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def focus(
    session_id: str = SID,
    *,
    entered_at: float = T0,
    ttl: float = FOCUS_TTL_SECONDS,
    task: str = "fix the parser",
    lifetime: Lifetime = Lifetime.SESSION,
) -> SessionModeEntry:
    return SessionModeEntry(
        mode=SessionMode.FOCUS,
        session_id=session_id,
        entered_at=entered_at,
        expires_at=entered_at + ttl,
        source=ModeSource.HUMAN,
        detail=task,
        lifetime=lifetime,
    )


def blocked(
    session_id: str = SID,
    *,
    reason: BlockReason = BlockReason.DECLARED,
    entered_at: float = T0,
    ttl: float = 86_400.0,
    lifetime: Lifetime = Lifetime.SESSION,
) -> SessionModeEntry:
    return SessionModeEntry(
        mode=SessionMode.BLOCKED,
        session_id=session_id,
        entered_at=entered_at,
        expires_at=entered_at + ttl,
        source=ModeSource.AGENT,
        reason=reason,
        lifetime=lifetime,
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    return tmp_path / "context-sidecar"


@pytest.fixture
def registry(state_dir: Path, clock: FakeClock) -> SessionModeRegistry:
    reg = SessionModeRegistry(state_dir, clock=clock)
    reg.load()
    return reg


def read_file(registry: SessionModeRegistry, session_id: str = SID) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(registry.path_for(session_id).read_text(encoding="utf-8"))
    return data


def write_raw(state_dir: Path, name: str, payload: object) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / name
    text = payload if isinstance(payload, str) else json.dumps(payload)
    path.write_text(text, encoding="utf-8")
    return path


def entry_record(entry: SessionModeEntry) -> dict[str, Any]:
    return {
        FIELD_MODE: str(entry.mode),
        FIELD_REASON: None if entry.reason is None else str(entry.reason),
        FIELD_SOURCE: str(entry.source),
        FIELD_LIFETIME: str(entry.lifetime),
        FIELD_ENTERED_AT: entry.entered_at,
        FIELD_EXPIRES_AT: entry.expires_at,
        FIELD_DETAIL: entry.detail,
    }


def file_payload(session_id: str, *entries: SessionModeEntry) -> dict[str, Any]:
    return {
        FIELD_VERSION: SCHEMA_VERSION,
        FIELD_SESSION_ID: session_id,
        FIELD_MODES: [entry_record(entry) for entry in entries],
    }


class TestEnterExitActive:
    def test_empty_session_has_no_modes(self, registry: SessionModeRegistry) -> None:
        assert registry.active(SID) == ()
        assert registry.policy(SID).drives_work is True

    def test_enter_then_active_round_trip(self, registry: SessionModeRegistry) -> None:
        entry = focus()
        registry.enter(entry)
        assert registry.active(SID) == (entry,)

    def test_active_is_in_precedence_order(self, registry: SessionModeRegistry) -> None:
        registry.enter(focus())
        registry.enter(blocked())
        assert [entry.label for entry in registry.active(SID)] == [
            ModeLabel.AWAITING_HUMAN,
            ModeLabel.FOCUS,
        ]

    def test_enter_replaces_the_same_label(self, registry: SessionModeRegistry) -> None:
        registry.enter(focus(task="first"))
        registry.enter(focus(task="second"))
        assert [entry.detail for entry in registry.active(SID)] == ["second"]

    def test_both_block_reasons_coexist(self, registry: SessionModeRegistry) -> None:
        registry.enter(blocked(reason=BlockReason.DECLARED))
        registry.enter(blocked(reason=BlockReason.GOAL_LOOP))
        assert len(registry.active(SID)) == 2

    @pytest.mark.parametrize("mode", [SessionMode.USAGE_PAUSED, SessionMode.UNATTENDED])
    def test_enter_refuses_a_mode_the_registry_does_not_own(
        self, registry: SessionModeRegistry, mode: SessionMode
    ) -> None:
        entry = SessionModeEntry(
            mode=mode,
            session_id=SID,
            entered_at=T0,
            expires_at=T0 + 60,
            source=ModeSource.DAEMON,
        )
        with pytest.raises(ValueError, match="not stored by the session-modes registry"):
            registry.enter(entry)
        assert not registry.path_for(SID).exists()

    def test_exit_returns_the_removed_entry(self, registry: SessionModeRegistry) -> None:
        entry = focus()
        registry.enter(entry)
        assert registry.exit(SID, ModeLabel.FOCUS) == entry
        assert registry.active(SID) == ()

    def test_exit_of_an_absent_label_returns_none(self, registry: SessionModeRegistry) -> None:
        registry.enter(focus())
        assert registry.exit(SID, ModeLabel.AWAITING_HUMAN) is None
        assert registry.exit(OTHER, ModeLabel.FOCUS) is None
        assert len(registry.active(SID)) == 1

    def test_policy_composes_the_active_entries(self, registry: SessionModeRegistry) -> None:
        registry.enter(focus())
        policy = registry.policy(SID)
        assert policy.drives_work is False
        assert policy.focus_task == "fix the parser"

    def test_sessions_are_isolated(self, registry: SessionModeRegistry) -> None:
        registry.enter(focus(SID))
        registry.enter(blocked(OTHER))
        assert [entry.session_id for entry in registry.active(SID)] == [SID]
        assert [entry.session_id for entry in registry.active(OTHER)] == [OTHER]
        registry.exit(SID, ModeLabel.FOCUS)
        assert len(registry.active(OTHER)) == 1


class TestWriteThrough:
    def test_file_carries_the_named_fields(self, registry: SessionModeRegistry) -> None:
        entry = blocked(reason=BlockReason.GOAL_LOOP)
        registry.enter(entry)
        assert read_file(registry) == file_payload(SID, entry)

    def test_file_name_uses_the_safe_stem_and_suffix(
        self, registry: SessionModeRegistry, state_dir: Path
    ) -> None:
        registry.enter(focus("a/b"))
        assert registry.path_for("a/b") == state_dir / f"a_b{SESSION_MODES_SUFFIX}"
        assert registry.path_for("a/b").exists()

    def test_suffix_is_not_json(self) -> None:
        assert SESSION_MODES_SUFFIX == ".session-modes"

    def test_file_lists_entries_in_precedence_order(self, registry: SessionModeRegistry) -> None:
        registry.enter(focus())
        registry.enter(blocked())
        modes = read_file(registry)[FIELD_MODES]
        assert [record[FIELD_MODE] for record in modes] == ["blocked", "focus"]

    def test_exit_of_the_last_entry_deletes_the_file(self, registry: SessionModeRegistry) -> None:
        registry.enter(focus())
        registry.exit(SID, ModeLabel.FOCUS)
        assert not registry.path_for(SID).exists()

    def test_no_temp_files_are_left_behind(
        self, registry: SessionModeRegistry, state_dir: Path
    ) -> None:
        registry.enter(focus())
        registry.enter(blocked())
        assert sorted(path.name for path in state_dir.iterdir()) == [f"{SID}{SESSION_MODES_SUFFIX}"]

    def test_a_failed_write_raises_and_leaves_memory_unchanged(
        self, registry: SessionModeRegistry, state_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first = focus()
        registry.enter(first)

        def refuse_replace(self: Path, target: Path) -> Path:
            raise PermissionError("read-only")

        def refuse_unlink(self: Path, missing_ok: bool = False) -> None:
            if self.suffix == SESSION_MODES_SUFFIX:
                raise PermissionError("read-only")
            original_unlink(self, missing_ok=missing_ok)

        original_unlink = Path.unlink
        with monkeypatch.context() as patch:
            patch.setattr(Path, "replace", refuse_replace)
            patch.setattr(Path, "unlink", refuse_unlink)
            with pytest.raises(OSError):
                registry.enter(blocked())
            with pytest.raises(OSError):
                registry.exit(SID, ModeLabel.FOCUS)
        assert registry.active(SID) == (first,)
        assert read_file(registry) == file_payload(SID, first)
        assert [path.name for path in state_dir.iterdir()] == [f"{SID}{SESSION_MODES_SUFFIX}"]


class TestThreadSafety:
    def test_concurrent_enters_and_exits_stay_consistent(
        self, registry: SessionModeRegistry
    ) -> None:
        sessions = [f"s{index}" for index in range(8)]
        errors: list[BaseException] = []

        def churn(session_id: str) -> None:
            try:
                for _ in range(25):
                    registry.enter(focus(session_id))
                    registry.enter(blocked(session_id))
                    registry.exit(session_id, ModeLabel.FOCUS)
                    registry.policy(session_id)
            except BaseException as error:
                errors.append(error)
                raise

        threads = [threading.Thread(target=churn, args=(sid,)) for sid in sessions]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []
        for session_id in sessions:
            active = registry.active(session_id)
            assert [entry.label for entry in active] == [ModeLabel.AWAITING_HUMAN]
            assert read_file(registry, session_id) == file_payload(session_id, *active)


class TestExpiry:
    def test_expired_entry_drops_out_of_active(
        self, registry: SessionModeRegistry, clock: FakeClock
    ) -> None:
        registry.enter(focus())
        clock.now = T0 + FOCUS_TTL_SECONDS
        assert registry.active(SID) == ()
        assert not registry.path_for(SID).exists()

    def test_expiry_queues_exactly_one_notice(
        self, registry: SessionModeRegistry, clock: FakeClock
    ) -> None:
        entry = focus()
        registry.enter(entry)
        clock.now = T0 + FOCUS_TTL_SECONDS + 1
        registry.active(SID)
        registry.active(SID)
        registry.reap()
        assert registry.take_notices(SID) == (ModeNotice(NoticeKind.EXPIRED, entry),)
        assert registry.take_notices(SID) == ()

    def test_focus_expiry_text_names_the_ttl_and_the_renewal(self) -> None:
        text = ModeNotice(NoticeKind.EXPIRED, focus()).text()
        assert text.startswith("focus expired after 12 h")
        assert "fix the parser" in text
        assert "`hooks-daemon focus <task>`" in text

    def test_blocked_expiry_text_describes_the_entry(self) -> None:
        text = ModeNotice(NoticeKind.EXPIRED, blocked()).text()
        assert text.startswith("awaiting-human since")
        assert text.endswith("expired")

    def test_a_live_entry_stays_while_another_expires(
        self, registry: SessionModeRegistry, clock: FakeClock
    ) -> None:
        registry.enter(focus(ttl=60))
        long_block = blocked(ttl=3600)
        registry.enter(long_block)
        clock.now = T0 + 61
        assert registry.active(SID) == (long_block,)
        assert read_file(registry) == file_payload(SID, long_block)

    def test_reap_drops_expired_entries_across_sessions(
        self, registry: SessionModeRegistry, clock: FakeClock
    ) -> None:
        registry.enter(focus(SID, ttl=60))
        registry.enter(blocked(OTHER, ttl=60))
        survivor = blocked(SID, ttl=3600)
        registry.enter(survivor)
        clock.now = T0 + 120
        assert registry.reap() == 2
        assert not registry.path_for(OTHER).exists()
        assert read_file(registry) == file_payload(SID, survivor)
        assert [notice.kind for notice in registry.take_notices(OTHER)] == [NoticeKind.EXPIRED]
        assert registry.reap() == 0

    def test_enter_drops_an_expired_sibling(
        self, registry: SessionModeRegistry, clock: FakeClock
    ) -> None:
        stale = focus(ttl=60)
        registry.enter(stale)
        clock.now = T0 + 120
        fresh = blocked(entered_at=clock.now)
        registry.enter(fresh)
        assert registry.active(SID) == (fresh,)
        assert registry.take_notices(SID) == (ModeNotice(NoticeKind.EXPIRED, stale),)


class TestPromptRenewal:
    def test_a_genuine_prompt_renews_focus(
        self, registry: SessionModeRegistry, clock: FakeClock
    ) -> None:
        registry.enter(focus())
        clock.now = T0 + FOCUS_TTL_SECONDS - 10
        assert registry.note_prompt(SID, "please keep going") is True
        (renewed,) = registry.active(SID)
        assert renewed.expires_at == clock.now + FOCUS_TTL_SECONDS
        assert read_file(registry)[FIELD_MODES][0][FIELD_EXPIRES_AT] == renewed.expires_at

    @pytest.mark.parametrize(
        "prompt",
        [
            "[tick:failsafe]\nFAILSAFE RECOVERY CHECK",
            "🤖 [ccy-supervisor] continue",
            "",
            None,
        ],
    )
    def test_machine_traffic_does_not_renew(
        self, registry: SessionModeRegistry, clock: FakeClock, prompt: object
    ) -> None:
        entry = focus()
        registry.enter(entry)
        clock.now = T0 + 100
        assert registry.note_prompt(SID, prompt) is False
        assert registry.active(SID) == (entry,)

    def test_blocked_is_not_renewed_by_a_prompt(
        self, registry: SessionModeRegistry, clock: FakeClock
    ) -> None:
        entry = blocked()
        registry.enter(entry)
        clock.now = T0 + 100
        assert registry.note_prompt(SID, "hello") is True
        assert registry.active(SID) == (entry,)

    def test_a_prompt_does_not_revive_an_expired_focus(
        self, registry: SessionModeRegistry, clock: FakeClock
    ) -> None:
        registry.enter(focus())
        clock.now = T0 + FOCUS_TTL_SECONDS + 1
        assert registry.note_prompt(SID, "hello") is True
        assert registry.active(SID) == ()
        assert [notice.kind for notice in registry.take_notices(SID)] == [NoticeKind.EXPIRED]

    def test_a_prompt_with_nothing_renewable_writes_nothing(
        self, registry: SessionModeRegistry
    ) -> None:
        assert registry.note_prompt(SID, "hello") is True
        assert not registry.path_for(SID).exists()


class TestLoad:
    def test_missing_directory_loads_nothing(self, state_dir: Path, clock: FakeClock) -> None:
        reg = SessionModeRegistry(state_dir, clock=clock)
        reg.load()
        assert reg.active(SID) == ()

    def test_load_runs_once(self, registry: SessionModeRegistry) -> None:
        with pytest.raises(RuntimeError, match="once"):
            registry.load()

    def test_session_lifetime_survives_with_one_notice(
        self, state_dir: Path, clock: FakeClock
    ) -> None:
        entry = focus()
        write_raw(state_dir, f"{SID}{SESSION_MODES_SUFFIX}", file_payload(SID, entry))
        reg = SessionModeRegistry(state_dir, clock=clock)
        reg.load()
        assert reg.active(SID) == (entry,)
        assert reg.take_notices(SID) == (ModeNotice(NoticeKind.SURVIVED_RESTART, entry),)
        assert reg.take_notices(SID) == ()

    def test_daemon_lifetime_is_cleared_with_one_notice(
        self, state_dir: Path, clock: FakeClock
    ) -> None:
        cleared = blocked(lifetime=Lifetime.DAEMON)
        kept = focus()
        path = write_raw(
            state_dir, f"{SID}{SESSION_MODES_SUFFIX}", file_payload(SID, cleared, kept)
        )
        reg = SessionModeRegistry(state_dir, clock=clock)
        reg.load()
        assert reg.active(SID) == (kept,)
        assert json.loads(path.read_text(encoding="utf-8")) == file_payload(SID, kept)
        assert set(reg.take_notices(SID)) == {
            ModeNotice(NoticeKind.CLEARED_BY_RESTART, cleared),
            ModeNotice(NoticeKind.SURVIVED_RESTART, kept),
        }

    def test_expired_on_load_is_dropped_with_an_expiry_notice(
        self, state_dir: Path, clock: FakeClock
    ) -> None:
        stale = focus(ttl=60)
        path = write_raw(state_dir, f"{SID}{SESSION_MODES_SUFFIX}", file_payload(SID, stale))
        clock.now = T0 + 120
        reg = SessionModeRegistry(state_dir, clock=clock)
        reg.load()
        assert reg.active(SID) == ()
        assert not path.exists()
        assert reg.take_notices(SID) == (ModeNotice(NoticeKind.EXPIRED, stale),)

    def test_restart_notice_texts(self) -> None:
        survived = ModeNotice(NoticeKind.SURVIVED_RESTART, focus()).text()
        cleared = ModeNotice(NoticeKind.CLEARED_BY_RESTART, blocked()).text()
        assert (
            survived == "focus mode on 'fix the parser' survived a daemon restart and still applies"
        )
        assert cleared.startswith("awaiting-human since")
        assert cleared.endswith("was cleared by a daemon restart")

    def test_other_files_in_the_directory_are_ignored(
        self, state_dir: Path, clock: FakeClock
    ) -> None:
        other = write_raw(state_dir, f"{SID}.json", "{not json")
        reg = SessionModeRegistry(state_dir, clock=clock)
        reg.load()
        assert other.exists()


def _valid_record() -> dict[str, Any]:
    return entry_record(focus())


@pytest.mark.parametrize(
    ("label", "payload"),
    [
        ("not json", "{not json"),
        ("not an object", [1, 2]),
        ("wrong version", {**file_payload(SID, focus()), FIELD_VERSION: 2}),
        ("session id not a string", {**file_payload(SID, focus()), FIELD_SESSION_ID: 7}),
        ("mismatched session id", file_payload(OTHER, focus(OTHER))),
        ("modes not a list", {**file_payload(SID), FIELD_MODES: {}}),
        ("mode record not an object", {**file_payload(SID), FIELD_MODES: ["focus"]}),
        (
            "unknown mode",
            {**file_payload(SID), FIELD_MODES: [{**_valid_record(), FIELD_MODE: "nap"}]},
        ),
        (
            "non-registry mode",
            {**file_payload(SID), FIELD_MODES: [{**_valid_record(), FIELD_MODE: "unattended"}]},
        ),
        (
            "unknown source",
            {**file_payload(SID), FIELD_MODES: [{**_valid_record(), FIELD_SOURCE: "cat"}]},
        ),
        (
            "unknown lifetime",
            {**file_payload(SID), FIELD_MODES: [{**_valid_record(), FIELD_LIFETIME: "forever"}]},
        ),
        (
            "unknown reason",
            {**file_payload(SID), FIELD_MODES: [{**_valid_record(), FIELD_REASON: "bored"}]},
        ),
        (
            "time not a number",
            {**file_payload(SID), FIELD_MODES: [{**_valid_record(), FIELD_ENTERED_AT: "x"}]},
        ),
        (
            "time a bool",
            {**file_payload(SID), FIELD_MODES: [{**_valid_record(), FIELD_EXPIRES_AT: True}]},
        ),
        (
            "time not finite",
            {
                **file_payload(SID),
                FIELD_MODES: [{**_valid_record(), FIELD_EXPIRES_AT: float("inf")}],
            },
        ),
        (
            "detail not a string",
            {**file_payload(SID), FIELD_MODES: [{**_valid_record(), FIELD_DETAIL: 3}]},
        ),
        (
            "missing field",
            {
                **file_payload(SID),
                FIELD_MODES: [
                    {key: value for key, value in _valid_record().items() if key != FIELD_SOURCE}
                ],
            },
        ),
        (
            "entry the model refuses",
            {**file_payload(SID), FIELD_MODES: [{**_valid_record(), FIELD_DETAIL: ""}]},
        ),
        ("duplicate label", file_payload(SID, focus(), focus(task="other"))),
    ],
)
def test_malformed_file_is_logged_and_renamed_corrupt(
    state_dir: Path,
    clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
    label: str,
    payload: object,
) -> None:
    path = write_raw(state_dir, f"{SID}{SESSION_MODES_SUFFIX}", payload)
    healthy = blocked(OTHER)
    write_raw(state_dir, f"{OTHER}{SESSION_MODES_SUFFIX}", file_payload(OTHER, healthy))
    reg = SessionModeRegistry(state_dir, clock=clock)
    with caplog.at_level(logging.WARNING):
        reg.load()
    assert not path.exists(), label
    assert path.with_name(path.name + CORRUPT_SUFFIX).exists(), label
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert any(str(path) in record.getMessage() for record in warnings), label
    assert reg.active(SID) == ()
    assert reg.active(OTHER) == (healthy,)


def test_a_failed_corrupt_rename_is_logged_at_error(
    state_dir: Path,
    clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = write_raw(state_dir, f"{SID}{SESSION_MODES_SUFFIX}", "{not json")

    def refuse(self: Path, target: Path) -> Path:
        raise PermissionError("read-only")

    monkeypatch.setattr(Path, "rename", refuse)
    reg = SessionModeRegistry(state_dir, clock=clock)
    with caplog.at_level(logging.WARNING):
        reg.load()
    assert path.exists()
    assert any(
        record.levelno == logging.ERROR and str(path) in record.getMessage()
        for record in caplog.records
    )
    assert reg.active(SID) == ()


class TestImportLegacyBlockageMarker:
    """The pre-registry awaiting-human marker becomes a registry entry once (Task 2.2)."""

    def test_missing_marker_imports_nothing(
        self, registry: SessionModeRegistry, tmp_path: Path
    ) -> None:
        assert import_legacy_blockage_marker(registry, tmp_path / MARKER_FILENAME) is False
        assert registry.active(SID) == ()

    def test_live_marker_becomes_declared_blocked_and_is_deleted(
        self, registry: SessionModeRegistry, clock: FakeClock, tmp_path: Path
    ) -> None:
        marker = tmp_path / MARKER_FILENAME
        assert write_marker(marker, SID, now=T0 - 60.0) is True
        assert import_legacy_blockage_marker(registry, marker) is True
        assert registry.active(SID) == (declared_blocked_entry(SID, entered_at=T0 - 60.0),)
        assert not marker.exists()

    @pytest.mark.parametrize(
        "recorded_at",
        [T0 - DECLARED_BLOCKED_TTL_SECONDS - 1.0, T0 + 60.0],
        ids=["expired", "future"],
    )
    def test_dead_marker_is_logged_at_info_and_deleted(
        self,
        registry: SessionModeRegistry,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        recorded_at: float,
    ) -> None:
        marker = tmp_path / MARKER_FILENAME
        assert write_marker(marker, SID, now=recorded_at) is True
        with caplog.at_level(logging.INFO):
            assert import_legacy_blockage_marker(registry, marker) is False
        assert registry.active(SID) == ()
        assert not marker.exists()
        assert any(
            record.levelno == logging.INFO and str(marker) in record.getMessage()
            for record in caplog.records
        )

    def test_corrupt_marker_is_a_warning_and_deleted(
        self, registry: SessionModeRegistry, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        marker = tmp_path / MARKER_FILENAME
        marker.write_text("{not json", encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            assert import_legacy_blockage_marker(registry, marker) is False
        assert not marker.exists()
        assert any(
            record.levelno == logging.WARNING and str(marker) in record.getMessage()
            for record in caplog.records
        )


# --- Plan 00501 Phase 4: transition log, snapshot, first-prompt claim -------


@pytest.fixture
def logged(state_dir: Path, clock: FakeClock, tmp_path: Path) -> SessionModeRegistry:
    reg = SessionModeRegistry(
        state_dir, clock=clock, transition_log=TransitionLog(tmp_path / "transitions.jsonl")
    )
    reg.load()
    return reg


def _log(tmp_path: Path) -> list[ModeTransition]:
    return TransitionLog(tmp_path / "transitions.jsonl").recent(100)


class TestTransitionLogging:
    def test_enter_is_logged_with_its_evidence(
        self, logged: SessionModeRegistry, tmp_path: Path
    ) -> None:
        logged.enter(focus(), evidence="prompt command `hooks-daemon focus`")
        [record] = _log(tmp_path)
        assert record.action is TransitionAction.ENTER
        assert record.label is ModeLabel.FOCUS
        assert record.evidence == "prompt command `hooks-daemon focus`"
        assert record.detail == "fix the parser"
        assert record.at == T0

    def test_enter_without_evidence_names_the_source(
        self, logged: SessionModeRegistry, tmp_path: Path
    ) -> None:
        logged.enter(blocked())
        assert _log(tmp_path)[0].evidence == "entered by the agent"

    def test_exit_is_logged(self, logged: SessionModeRegistry, tmp_path: Path) -> None:
        logged.enter(focus(), evidence="cli")
        logged.exit(SID, ModeLabel.FOCUS, evidence="`hooks-daemon focus off`")
        record = _log(tmp_path)[-1]
        assert record.action is TransitionAction.EXIT
        assert record.evidence == "`hooks-daemon focus off`"

    def test_exit_of_an_absent_mode_logs_nothing(
        self, logged: SessionModeRegistry, tmp_path: Path
    ) -> None:
        logged.exit(SID, ModeLabel.FOCUS, evidence="x")
        assert _log(tmp_path) == []

    def test_exit_without_evidence_says_so(
        self, logged: SessionModeRegistry, tmp_path: Path
    ) -> None:
        logged.enter(focus(), evidence="cli")
        logged.exit(SID, ModeLabel.FOCUS)
        assert _log(tmp_path)[-1].evidence == "exited (no evidence given)"

    def test_expiry_is_logged(
        self, logged: SessionModeRegistry, clock: FakeClock, tmp_path: Path
    ) -> None:
        logged.enter(focus(ttl=10), evidence="cli")
        clock.now = T0 + 20
        logged.active(SID)
        record = _log(tmp_path)[-1]
        assert record.action is TransitionAction.EXPIRE
        assert record.at == T0 + 20

    def test_restart_clear_and_load_expiry_are_logged(
        self, state_dir: Path, clock: FakeClock, tmp_path: Path
    ) -> None:
        write_raw(
            state_dir,
            f"{SID}{SESSION_MODES_SUFFIX}",
            file_payload(SID, blocked(lifetime=Lifetime.DAEMON), focus(ttl=5)),
        )
        clock.now = T0 + 10
        reg = SessionModeRegistry(
            state_dir, clock=clock, transition_log=TransitionLog(tmp_path / "transitions.jsonl")
        )
        reg.load()
        actions = {(t.label, t.action) for t in _log(tmp_path)}
        assert actions == {
            (ModeLabel.AWAITING_HUMAN, TransitionAction.RESTART_CLEAR),
            (ModeLabel.FOCUS, TransitionAction.EXPIRE),
        }

    def test_a_failed_log_write_is_warned_and_the_mode_still_changes(
        self,
        state_dir: Path,
        clock: FakeClock,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        class BrokenLog(TransitionLog):
            def append(self, transitions: Sequence[ModeTransition]) -> None:
                raise OSError("disk full")

        reg = SessionModeRegistry(
            state_dir, clock=clock, transition_log=BrokenLog(tmp_path / "x.jsonl")
        )
        reg.load()
        with caplog.at_level(logging.WARNING):
            reg.enter(focus(), evidence="cli")
        assert reg.policy(SID).focus_task == "fix the parser"
        assert "transition" in caplog.text
        assert "disk full" in caplog.text

    def test_no_log_configured_records_nothing(
        self, registry: SessionModeRegistry, tmp_path: Path
    ) -> None:
        registry.enter(focus(), evidence="cli")
        assert not (tmp_path / "transitions.jsonl").exists()
        assert registry.transition_log is None


class TestSnapshot:
    def test_snapshot_holds_every_session_with_a_live_mode(
        self, registry: SessionModeRegistry, clock: FakeClock
    ) -> None:
        registry.enter(focus())
        registry.enter(blocked(OTHER, ttl=10))
        clock.now = T0 + 20
        snapshot = registry.snapshot()
        assert list(snapshot) == [SID]
        assert [e.label for e in snapshot[SID]] == [ModeLabel.FOCUS]


class TestFirstPromptClaim:
    def test_loaded_at_is_the_load_time(self, registry: SessionModeRegistry) -> None:
        assert registry.loaded_at == T0

    def test_loaded_at_before_load_is_an_error(self, state_dir: Path) -> None:
        registry = SessionModeRegistry(state_dir)
        with pytest.raises(RuntimeError, match="load"):
            _ = registry.loaded_at

    def test_each_session_claims_its_first_prompt_once(self, registry: SessionModeRegistry) -> None:
        assert registry.claim_first_prompt(SID) is True
        assert registry.claim_first_prompt(SID) is False
        assert registry.claim_first_prompt(OTHER) is True

    def test_a_claim_inside_the_window_is_kept_by_reap(
        self, registry: SessionModeRegistry, clock: FakeClock
    ) -> None:
        registry.claim_first_prompt(SID)
        clock.now = T0 + FIRST_PROMPT_WINDOW_SECONDS
        registry.reap()
        assert registry.claim_first_prompt(SID) is False

    def test_past_the_window_no_session_claims_and_reap_drops_every_claim(
        self, registry: SessionModeRegistry, clock: FakeClock
    ) -> None:
        """Nothing from before the load can still be live, so the set is pruned to empty."""
        registry.claim_first_prompt(SID)
        clock.now = T0 + FIRST_PROMPT_WINDOW_SECONDS + 1
        assert registry.claim_first_prompt(OTHER) is False
        registry.reap()
        assert registry._first_prompt_claimed == set()

    def test_the_window_covers_the_longest_pause_a_record_can_hold(self) -> None:
        assert FIRST_PROMPT_WINDOW_SECONDS == MAX_PAUSE_SPAN_SECONDS + PAUSE_GRACE_SECONDS
