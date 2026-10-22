"""The one-line session-mode statement at a session's next prompt (Plan 00501 Task 4.2).

After a daemon restart, the next prompt in each session states every mode that
survived it (registry modes, and a usage pause the registry does not own), and
every mode the restart cleared, in ONE context line, whatever the prompt is.
The registry's notices are pop-once, so this is their only consumer.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.core.session_mode_registry import SessionModeRegistry
from claude_code_hooks_daemon.core.session_mode_statement import pending_mode_statement
from claude_code_hooks_daemon.utils.session_modes import (
    FOCUS_TTL_SECONDS,
    BlockReason,
    Lifetime,
    ModeSource,
    SessionMode,
    SessionModeEntry,
    UsagePauseView,
)

_SID = "sess-restated"
_T0 = 1_000_000.0


def _focus(*, lifetime: Lifetime = Lifetime.SESSION) -> SessionModeEntry:
    return SessionModeEntry(
        mode=SessionMode.FOCUS,
        session_id=_SID,
        entered_at=_T0 - 60,
        expires_at=_T0 + FOCUS_TTL_SECONDS,
        source=ModeSource.HUMAN,
        detail="the release note",
        lifetime=lifetime,
    )


def _loaded(tmp_path: Path, *entries: SessionModeEntry) -> SessionModeRegistry:
    """A registry that loads ``entries`` from disk, as a restarted daemon does."""
    if entries:
        writer = SessionModeRegistry(tmp_path, clock=lambda: _T0 - 60)
        writer.load()
        for entry in entries:
            writer.enter(entry)
    registry = SessionModeRegistry(tmp_path, clock=lambda: _T0)
    registry.load()
    return registry


class _Sources:
    """Counts reads of the lazily-read sources."""

    def __init__(self, pause: UsagePauseView | None = None, unattended: bool = False) -> None:
        self.pause = pause
        self.unattended_value = unattended
        self.pause_reads = 0
        self.mode_reads = 0

    def usage_pause(self) -> UsagePauseView | None:
        self.pause_reads += 1
        return self.pause

    def unattended(self) -> bool:
        self.mode_reads += 1
        return self.unattended_value


def _statement(registry: SessionModeRegistry, sources: _Sources) -> str | None:
    return pending_mode_statement(
        registry, _SID, usage_pause=sources.usage_pause, unattended=sources.unattended
    )


class TestRestartRestatement:
    def test_a_surviving_mode_is_stated_once_in_one_line(self, tmp_path: Path) -> None:
        registry = _loaded(tmp_path, _focus())
        sources = _Sources()
        line = _statement(registry, sources)
        assert line == (
            "SESSION MODE: focus mode on 'the release note' survived a daemon restart "
            "and still applies."
        )
        assert _statement(registry, sources) is None

    def test_cleared_and_surviving_modes_share_the_line(self, tmp_path: Path) -> None:
        cleared = SessionModeEntry(
            mode=SessionMode.BLOCKED,
            session_id=_SID,
            entered_at=_T0 - 60,
            expires_at=_T0 + 600,
            source=ModeSource.AGENT,
            reason=BlockReason.DECLARED,
            lifetime=Lifetime.DAEMON,
        )
        registry = _loaded(tmp_path, _focus(), cleared)
        line = _statement(registry, _Sources())
        assert line is not None
        assert line.count("SESSION MODE:") == 1
        assert "survived a daemon restart" in line
        assert "was cleared by a daemon restart" in line

    def test_a_usage_pause_from_before_the_restart_is_restated(self, tmp_path: Path) -> None:
        registry = _loaded(tmp_path)
        sources = _Sources(pause=UsagePauseView(paused_at=_T0 - 30, until=_T0 + 3600, reason="5h"))
        line = _statement(registry, sources)
        assert line is not None
        assert "usage-paused (5h) survived a daemon restart and still applies" in line
        assert _statement(registry, sources) is None
        assert sources.pause_reads == 1

    def test_a_usage_pause_started_after_the_restart_is_not_restated(self, tmp_path: Path) -> None:
        registry = _loaded(tmp_path)
        sources = _Sources(pause=UsagePauseView(paused_at=_T0 + 5, until=_T0 + 3600, reason="5h"))
        assert _statement(registry, sources) is None

    def test_unattended_is_named_only_beside_a_restart_statement(self, tmp_path: Path) -> None:
        quiet = _loaded(tmp_path / "quiet")
        sources = _Sources(unattended=True)
        assert _statement(quiet, sources) is None
        assert sources.mode_reads == 0

        restarted = _loaded(tmp_path / "restarted", _focus())
        line = _statement(restarted, _Sources(unattended=True))
        assert line is not None
        assert "the daemon is in unattended mode" in line

    def test_an_expiry_alone_is_stated_without_reading_the_daemon_mode(
        self, tmp_path: Path
    ) -> None:
        now = [_T0]
        registry = SessionModeRegistry(tmp_path, clock=lambda: now[0])
        registry.load()
        registry.enter(_focus())
        registry.claim_first_prompt(_SID)
        now[0] = _T0 + FOCUS_TTL_SECONDS + 1
        registry.active(_SID)
        sources = _Sources(unattended=True)
        line = _statement(registry, sources)
        assert line is not None
        assert "focus expired" in line
        assert sources.mode_reads == 0

    def test_nothing_pending_is_no_line(self, tmp_path: Path) -> None:
        assert _statement(_loaded(tmp_path), _Sources()) is None
