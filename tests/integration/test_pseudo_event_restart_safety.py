"""Every registered pseudo-event setup must survive a daemon restart.

Plan 00224 — the DBF half. The nitpick setup replayed the ENTIRE transcript
after every daemon restart, because ``NitpickState`` is in-memory and
``last_byte_offset`` returns to ``0`` when the process dies. This repo mandates
a restart after every handler change, so the misfire was the normal case, not
an edge case: on a live session it re-audited 9,696 assistant messages and
re-reported findings the previous daemon had already reported.

The unit test in ``tests/unit/pseudo_events/test_nitpick.py`` fixes the
INSTANCE. This file fixes the CLASS. The difference matters the day someone
registers pseudo-event #2: nitpick's own unit test would stay green while the
new setup silently inherited the same bug. This gate enumerates the
authoritative registry instead, so a new setup cannot join without either
passing the replay test or recording why it is exempt.

Why the registry rather than a source scan: ``_get_pseudo_event_setup_registry``
IS the list of setups the daemon actually runs. A grep for state-holding
classes would be both lossy and imprecise; the registry cannot be.
"""

from __future__ import annotations

import inspect
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.daemon.controller import DaemonController

# The constructor keyword a setup must accept to be defensible against replay.
# A setup that cannot be told when the daemon came up has no way to tell a
# genuinely-new session (audit the backlog) from a restarted one (do not).
_START_TIME_PARAMETER = "started_at"

_TRANSCRIPT_SUFFIX = ".jsonl"


def _registered_setups() -> dict[str, Any]:
    """The setup instances the daemon actually registers, keyed by name."""
    registry = DaemonController._get_pseudo_event_setup_registry()
    return {name: setup_fn for name, (setup_fn, _) in registry.items()}


def _write_pre_start_transcript(path: Path, daemon_start: datetime) -> None:
    """A transcript whose every assistant message predates the daemon."""
    entry = {
        "type": "assistant",
        "uuid": "uuid-written-before-this-daemon-existed",
        "timestamp": (daemon_start - timedelta(hours=3))
        .astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "audited by the PREVIOUS daemon process"}],
        },
    }
    path.write_text(json.dumps(entry) + "\n")


class TestEveryPseudoEventSetupIsRestartSafe:
    """A restarted daemon must not re-report what a previous one already did."""

    # name -> reason. A setup belongs here ONLY if it reads no durable external
    # record, so replay is impossible by construction rather than by defence.
    _EXEMPT_FROM_REPLAY_GUARD: ClassVar[dict[str, str]] = {}

    def test_the_registry_is_not_empty(self) -> None:
        """Vacuity guard: this suite must not pass by checking nothing."""
        assert _registered_setups(), (
            "No pseudo-event setups discovered. Either the registry moved or "
            "discovery broke — a guard that enumerates nothing reports success "
            "for every possible defect."
        )

    def test_every_setup_is_either_defensible_or_recorded_exempt(self) -> None:
        """A setup cannot join the registry without a verdict on replay."""
        undefended: list[str] = []
        for name, setup in _registered_setups().items():
            if name in self._EXEMPT_FROM_REPLAY_GUARD:
                continue
            parameters = inspect.signature(type(setup).__init__).parameters
            if _START_TIME_PARAMETER not in parameters:
                undefended.append(name)

        assert not undefended, (
            f"Pseudo-event setup(s) {sorted(undefended)} accept no "
            f"{_START_TIME_PARAMETER!r} argument, so they cannot distinguish a "
            "genuinely-new session (whose backlog SHOULD be audited) from a "
            "restarted daemon (whose backlog was already audited). Either accept "
            f"{_START_TIME_PARAMETER!r} and filter on it, or add an entry to "
            "_EXEMPT_FROM_REPLAY_GUARD explaining why this setup reads no "
            "durable record and therefore cannot replay."
        )

    def test_no_stale_exemptions(self) -> None:
        """An exemption naming an unregistered setup is a lie in the table."""
        registered = set(_registered_setups())
        stale = set(self._EXEMPT_FROM_REPLAY_GUARD) - registered
        assert not stale, (
            f"_EXEMPT_FROM_REPLAY_GUARD names unregistered setup(s) {sorted(stale)}. "
            "Remove the entries — a stale exemption silently widens the hole it "
            "was meant to document."
        )

    def test_every_exemption_states_a_reason(self) -> None:
        blank = [n for n, reason in self._EXEMPT_FROM_REPLAY_GUARD.items() if not reason.strip()]
        assert not blank, f"Exemption(s) {sorted(blank)} carry no reason."

    def test_a_cold_setup_does_not_replay_messages_older_than_itself(self) -> None:
        """The property itself, applied to every non-exempt registered setup."""
        daemon_start = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

        for name, setup in _registered_setups().items():
            if name in self._EXEMPT_FROM_REPLAY_GUARD:
                continue

            with tempfile.NamedTemporaryFile(
                suffix=_TRANSCRIPT_SUFFIX, mode="w", delete=False
            ) as handle:
                path = Path(handle.name)
            _write_pre_start_transcript(path, daemon_start)

            try:
                cold = type(setup)(started_at=daemon_start)
                result = cold(
                    {HookInputField.TRANSCRIPT_PATH: str(path)},
                    f"session-restarted-{name}",
                )
            finally:
                path.unlink()

            assert result is None, (
                f"Pseudo-event {name!r} audited a message written before it "
                "started. A daemon has no basis for calling a pre-existing "
                "message new, and re-auditing it replays a finding the previous "
                "daemon already reported to the user."
            )

    def test_the_guard_would_fail_a_setup_that_ignores_its_start_time(self) -> None:
        """The guard must be able to fail — a check that cannot fail proves nothing."""
        setups = _registered_setups()
        name, setup = next(iter(setups.items()))

        with tempfile.NamedTemporaryFile(
            suffix=_TRANSCRIPT_SUFFIX, mode="w", delete=False
        ) as handle:
            path = Path(handle.name)
        daemon_start = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
        _write_pre_start_transcript(path, daemon_start)

        try:
            # Pre-fix behaviour: a daemon that believes it started long ago
            # audits the whole backlog. Same code path, start time moved.
            replaying = type(setup)(started_at=daemon_start - timedelta(days=1))
            result = replaying(
                {HookInputField.TRANSCRIPT_PATH: str(path)},
                f"session-replay-{name}",
            )
        finally:
            path.unlink()

        assert result is not None, (
            "The replay guard never fires, so the assertion above would pass "
            "for any implementation. Check that the fixture transcript is still "
            "shaped like a real one."
        )
