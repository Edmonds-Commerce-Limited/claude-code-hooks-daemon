"""The scratch TTL clock (Plan 00627 Task 1.4, DESIGN.md section 4)."""

from __future__ import annotations

from claude_code_hooks_daemon.core.scratch_clock import NO_BIRTH_NOTE, entry_age
from claude_code_hooks_daemon.core.scratch_walk import EntryStats, NodeKind

_HOUR = 3600.0
_NOW = 2_000_000_000.0
_NS = 1_000_000_000


def _stats(*, mtime: float, ctime: float) -> EntryStats:
    return EntryStats(
        name="e",
        kind=NodeKind.DIRECTORY,
        root_ctime_ns=int(ctime * _NS),
        newest_mtime_ns=int(mtime * _NS),
    )


class TestActivity:
    def test_the_newest_input_is_the_activity(self) -> None:
        age = entry_age(
            _stats(mtime=_NOW - 30 * _HOUR, ctime=_NOW - 2 * _HOUR),
            now=_NOW,
            ttl_hours=24,
            max_lifetime_hours=168,
        )
        assert age.age_seconds == 2 * _HOUR
        assert not age.due

    def test_an_old_mtime_and_ctime_is_due(self) -> None:
        age = entry_age(
            _stats(mtime=_NOW - 30 * _HOUR, ctime=_NOW - 40 * _HOUR),
            now=_NOW,
            ttl_hours=24,
            max_lifetime_hours=168,
        )
        assert age.age_seconds == 30 * _HOUR
        assert age.due

    def test_exactly_the_ttl_is_due(self) -> None:
        age = entry_age(
            _stats(mtime=_NOW - 24 * _HOUR, ctime=_NOW - 24 * _HOUR),
            now=_NOW,
            ttl_hours=24,
            max_lifetime_hours=168,
        )
        assert age.due

    def test_a_restored_old_mtime_is_kept_young_by_the_root_ctime(self) -> None:
        """``cp -a`` restores old mtimes; the copy's ctime is fresh."""
        age = entry_age(
            _stats(mtime=_NOW - 500 * _HOUR, ctime=_NOW - _HOUR),
            now=_NOW,
            ttl_hours=24,
            max_lifetime_hours=168,
        )
        assert not age.due

    def test_a_recent_birth_keeps_it_young(self) -> None:
        age = entry_age(
            _stats(mtime=_NOW - 50 * _HOUR, ctime=_NOW - 50 * _HOUR),
            now=_NOW,
            ttl_hours=24,
            max_lifetime_hours=168,
            birth=_NOW - _HOUR,
        )
        assert not age.due

    def test_a_negative_age_is_clamped_to_zero(self) -> None:
        age = entry_age(
            _stats(mtime=_NOW + _HOUR, ctime=_NOW + _HOUR),
            now=_NOW,
            ttl_hours=24,
            max_lifetime_hours=168,
        )
        assert age.age_seconds == 0


class TestMaximumLifetime:
    def test_past_the_lifetime_it_is_due_whatever_the_mtime(self) -> None:
        """``touch`` keeps an entry young for ever; the lifetime from birth does not."""
        age = entry_age(
            _stats(mtime=_NOW - 60, ctime=_NOW - 60),
            now=_NOW,
            ttl_hours=24,
            max_lifetime_hours=168,
            birth=_NOW - 200 * _HOUR,
        )
        assert age.lifetime_exceeded is True
        assert age.due

    def test_within_the_lifetime_it_is_not_exceeded(self) -> None:
        age = entry_age(
            _stats(mtime=_NOW - 60, ctime=_NOW - 60),
            now=_NOW,
            ttl_hours=24,
            max_lifetime_hours=168,
            birth=_NOW - 100 * _HOUR,
        )
        assert age.lifetime_exceeded is False
        assert not age.due

    def test_with_no_birth_the_backstop_is_not_evaluated_and_says_so(self) -> None:
        age = entry_age(
            _stats(mtime=_NOW - 60, ctime=_NOW - 60),
            now=_NOW,
            ttl_hours=24,
            max_lifetime_hours=168,
        )
        assert age.lifetime_exceeded is None
        assert NO_BIRTH_NOTE in age.notes
