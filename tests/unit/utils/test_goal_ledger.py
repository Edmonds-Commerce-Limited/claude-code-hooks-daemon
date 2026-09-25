"""Tests for the daemon-side goal ledger (Plan 00276).

The ledger records every goal emission from ``goal_injection``, detects when
a new goal displaces a still-live one, and retires entries whose plan has
reached a terminal status or left the active plan directory. All reads and
writes are fail-open: a missing or corrupt ledger never raises.
"""

import json
import os
import threading
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.goal_ledger import (
    LEDGER_FILENAME,
    GoalLedger,
)

_SESSION = "sess-1"
_OTHER_SESSION = "sess-2"
_PLAN_A = "00274"
_PLAN_B = "00275"
_GOAL_LINE = "work on the plan"

_STATUS_IN_PROGRESS = "In Progress"
_STATUS_COMPLETE = "Complete"


def _make_plan(plan_dir: Path, number: str, status: str) -> Path:
    folder = plan_dir / f"{number}-example-plan"
    folder.mkdir(parents=True, exist_ok=True)
    plan_md = folder / "PLAN.md"
    plan_md.write_text(
        f"# Plan {number}: example plan\n\n**Status**: {status}\n",
        encoding="utf-8",
    )
    return folder


class TestRecordEmission:
    def test_first_emission_records_entry_and_displaces_nothing(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        displaced = ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        assert displaced == []
        entries = ledger.entries()
        assert len(entries) == 1
        assert entries[0].plan_number == _PLAN_A
        assert entries[0].session_id == _SESSION
        assert entries[0].rendered_line == _GOAL_LINE
        assert entries[0].displaced_by is None
        assert entries[0].retired_at is None

    def test_second_plan_displaces_live_first(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        _make_plan(plan_dir, _PLAN_B, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        displaced = ledger.record_emission(_SESSION, _PLAN_B, _GOAL_LINE, plan_dir)
        assert displaced == [_PLAN_A]
        entry_a = next(e for e in ledger.entries() if e.plan_number == _PLAN_A)
        assert entry_a.displaced_by == _PLAN_B
        assert entry_a.displaced_at is not None

    def test_re_emission_same_plan_does_not_self_displace(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        displaced = ledger.record_emission(_OTHER_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        assert displaced == []
        # Re-fire refreshes the live entry rather than double-counting it.
        live = [e for e in ledger.entries() if e.plan_number == _PLAN_A and e.retired_at is None]
        assert len(live) == 1
        assert live[0].session_id == _OTHER_SESSION

    def test_re_emission_never_reassigns_primary_owner(self, tmp_path: Path) -> None:
        """RV5-m5 / probe_gf5_mutate.py: 'a re-emission hands primary_owner
        to the re-emitter' -- RV4-M1's whole point is that the pin stays
        with whoever's `record_emission` call CREATED the entry, so a
        later re-flip of the same still-live entry by a DIFFERENT session
        must not silently hand that session pinned-owner protection."""
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        ledger.record_emission(_OTHER_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)

        entry = next(e for e in ledger.entries() if e.plan_number == _PLAN_A)
        assert entry.primary_owner == _SESSION, (
            "the re-emitter (_OTHER_SESSION) must never become primary_owner "
            "-- it stays the session that created the entry"
        )

    def test_completed_prior_plan_is_not_reported_as_displaced(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_COMPLETE)
        _make_plan(plan_dir, _PLAN_B, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        displaced = ledger.record_emission(_SESSION, _PLAN_B, _GOAL_LINE, plan_dir)
        assert displaced == []


class TestLivePlanNumbers:
    def test_lists_in_progress_ledgered_plans(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        _make_plan(plan_dir, _PLAN_B, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        ledger.record_emission(_SESSION, _PLAN_B, _GOAL_LINE, plan_dir)
        assert ledger.live_plan_numbers(plan_dir) == [_PLAN_A, _PLAN_B]

    def test_displaced_but_in_progress_plan_stays_live(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        _make_plan(plan_dir, _PLAN_B, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        ledger.record_emission(_SESSION, _PLAN_B, _GOAL_LINE, plan_dir)
        assert _PLAN_A in ledger.live_plan_numbers(plan_dir)

    def test_terminal_status_retires_entry(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        (folder / "PLAN.md").write_text(
            f"# Plan {_PLAN_A}: example plan\n\n**Status**: Complete\n", encoding="utf-8"
        )
        assert ledger.live_plan_numbers(plan_dir) == []
        entry = ledger.entries()[0]
        assert entry.retired_at is not None
        assert entry.retired_reason is not None

    def test_archive_move_retires_entry(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        archive = plan_dir / "Completed"
        archive.mkdir(parents=True, exist_ok=True)
        folder.rename(archive / folder.name)
        assert ledger.live_plan_numbers(plan_dir) == []
        assert ledger.entries()[0].retired_at is not None

    def test_retirement_persists_to_disk(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger_path = tmp_path / LEDGER_FILENAME
        GoalLedger(ledger_path).record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        (folder / "PLAN.md").write_text("**Status**: Cancelled\n", encoding="utf-8")
        GoalLedger(ledger_path).live_plan_numbers(plan_dir)
        # A fresh instance sees the persisted retirement.
        fresh = GoalLedger(ledger_path)
        assert fresh.live_plan_numbers(plan_dir) == []
        assert fresh.entries()[0].retired_at is not None


class TestFailOpen:
    def test_missing_ledger_yields_no_live_plans(self, tmp_path: Path) -> None:
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        assert ledger.live_plan_numbers(tmp_path / "CLAUDE" / "Plan") == []
        assert ledger.entries() == []

    def test_corrupt_ledger_is_tolerated(self, tmp_path: Path) -> None:
        ledger_path = tmp_path / LEDGER_FILENAME
        ledger_path.write_text("{not json", encoding="utf-8")
        ledger = GoalLedger(ledger_path)
        assert ledger.entries() == []
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        # Recording over a corrupt file starts a fresh ledger.
        assert ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir) == []
        assert GoalLedger(ledger_path).entries()[0].plan_number == _PLAN_A

    def test_failed_write_never_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)

        real_os_open = os.open

        def _failing_tmp_open(path: str | Path, flags: int, mode: int = 0o777) -> int:
            # Fail only the private tmp-file open in _save; the sibling lock
            # file must keep working so the OSError branch (not the lock's
            # fail-open) is what this test exercises.
            if ".tmp" in str(path):
                raise OSError("disk full")
            return real_os_open(path, flags, mode)

        # All setup writes are done; every subsequent tmp write fails, so the
        # OSError branch in _save must be exercised and swallowed (logged).
        monkeypatch.setattr(os, "open", _failing_tmp_open)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        assert not (tmp_path / LEDGER_FILENAME).exists()

    def test_nonexistent_plan_dir_never_retires(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        # A misresolved/nonexistent plan dir must NOT retire the entry —
        # retirement is persisted, so a wrong path would wipe the ledger.
        wrong_dir = tmp_path / "not" / "a" / "plan" / "dir"
        assert ledger.live_plan_numbers(wrong_dir) == []
        assert ledger.entries()[0].retired_at is None
        # The entry is still live against the real plan dir.
        assert ledger.live_plan_numbers(plan_dir) == [_PLAN_A]


class TestUnreadableLedgerRaisesADomainException:
    """team-lead review-4-prep: ``_load_raw`` raises ``LedgerUnreadable``
    for a genuinely CORRUPT ledger (never returns None on error -- ``None``
    is reserved for the ordinary "nothing written yet" case), and every
    public caller catches it explicitly, logs a WARNING naming the path
    and cause, and takes its own documented fail-open branch."""

    def _corrupt_ledger(self, tmp_path: Path) -> Path:
        ledger_path = tmp_path / LEDGER_FILENAME
        ledger_path.write_text("{not json", encoding="utf-8")
        return ledger_path

    def test_load_raw_raises_on_corrupt_json(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.utils.goal_ledger import LedgerUnreadable

        ledger = GoalLedger(self._corrupt_ledger(tmp_path))
        with pytest.raises(LedgerUnreadable):
            ledger._load_raw()

    def test_load_raw_returns_none_for_a_missing_file(self, tmp_path: Path) -> None:
        """Missing is NOT unreadable -- it is the ordinary first-ever-use case."""
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        assert ledger._load_raw() is None

    def test_load_raw_raises_on_eacces_from_the_existence_check_itself(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RV4-m3: ``Path.is_file()`` itself can raise (``EACCES`` on an
        unreadable parent directory) -- reverting the existence check to
        run OUTSIDE this try (as a pre-check) lets that escape as a raw,
        unwrapped ``PermissionError`` instead of ``LedgerUnreadable``."""
        from claude_code_hooks_daemon.utils.goal_ledger import LedgerUnreadable

        def _boom(self: Path) -> bool:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(Path, "is_file", _boom)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)

        with pytest.raises(LedgerUnreadable):
            ledger._load_raw()

    def test_live_plan_numbers_does_not_raise_on_eacces_from_plan_md_is_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RV5-m6: ``_plan_state``/``_find_plan_md_text`` kept a raw
        ``PLAN.md.is_file()`` OUTSIDE their own try -- RV4-m3 fixed
        ``_load_raw``'s equivalent but not these two siblings. A live
        ledgered plan whose folder denies search (``EACCES`` on the
        ``is_file`` stat) escaped ``live_plan_numbers`` -- and therefore
        the Stop handler's fail-open promise -- as a raw, unwrapped
        ``PermissionError`` instead of the ``unreadable`` state this
        module already has a name for (never retires anything)."""
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger_path = tmp_path / LEDGER_FILENAME
        ledger = GoalLedger(ledger_path)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)

        real_is_file = Path.is_file
        real_read_text = Path.read_text

        def _is_file_boom(self: Path) -> bool:
            if self.name == "PLAN.md":
                raise PermissionError(13, "Permission denied")
            return real_is_file(self)

        def _read_text_boom(
            self: Path, encoding: str | None = None, errors: str | None = None
        ) -> str:
            if self.name == "PLAN.md":
                raise PermissionError(13, "Permission denied")
            return real_read_text(self, encoding, errors)

        monkeypatch.setattr(Path, "is_file", _is_file_boom)
        monkeypatch.setattr(Path, "read_text", _read_text_boom)

        result = ledger.live_plan_numbers(plan_dir)  # must not raise

        assert result == [], (
            "an unreadable plan cannot be confirmed In Progress on THIS "
            "call, so it is not reported live for it -- but see the "
            "assertion below: it must not be RETIRED either"
        )
        entry = next(e for e in ledger.entries() if e.plan_number == _PLAN_A)
        assert entry.retired_at is None, (
            "a transient EACCES must never retire the entry -- retirement "
            "is persisted, so a misresolved/unreadable folder wiping it "
            "here would be permanent and wrong"
        )

    def test_entries_logs_a_warning_for_a_corrupt_ledger(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        ledger = GoalLedger(self._corrupt_ledger(tmp_path))
        with caplog.at_level("WARNING"):
            result = ledger.entries()
        assert result == []
        assert "goal_ledger" in caplog.text

    def test_session_has_entries_logs_a_warning_and_reads_as_false(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        ledger = GoalLedger(self._corrupt_ledger(tmp_path))
        with caplog.at_level("WARNING"):
            result = ledger.session_has_entries(_SESSION)
        assert result is False
        assert "goal_ledger" in caplog.text

    def test_reassert_session_logs_a_warning_and_returns_false(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        ledger = GoalLedger(self._corrupt_ledger(tmp_path))
        with caplog.at_level("WARNING"):
            result = ledger.reassert_session(_SESSION, _PLAN_A)
        assert result is False
        assert "goal_ledger" in caplog.text

    def test_live_plan_numbers_logs_a_warning_and_reads_as_empty(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        ledger = GoalLedger(self._corrupt_ledger(tmp_path))
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        with caplog.at_level("WARNING"):
            result = ledger.live_plan_numbers(plan_dir)
        assert result == []
        assert "goal_ledger" in caplog.text

    def test_record_emission_logs_a_warning_and_starts_fresh(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        ledger_path = self._corrupt_ledger(tmp_path)
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(ledger_path)
        with caplog.at_level("WARNING"):
            displaced = ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        assert displaced == []
        assert GoalLedger(ledger_path).entries()[0].plan_number == _PLAN_A
        assert "goal_ledger" in caplog.text


class TestLivePlanRefs:
    """Plan 00299: resolved (folder, PLAN.md text) per live plan, for the
    combined-goal renderer."""

    def test_resolves_folder_and_text_for_each_live_plan(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        _make_plan(plan_dir, _PLAN_B, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        ledger.record_emission(_SESSION, _PLAN_B, _GOAL_LINE, plan_dir)
        refs = ledger.live_plan_refs(plan_dir)
        assert [r.plan_number for r in refs] == [_PLAN_A, _PLAN_B]
        assert refs[0].plan_folder == f"{_PLAN_A}-example-plan"
        assert f"**Status**: {_STATUS_IN_PROGRESS}" in refs[0].plan_text

    def test_excludes_terminal_plans(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        _make_plan(plan_dir, _PLAN_B, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        ledger.record_emission(_SESSION, _PLAN_B, _GOAL_LINE, plan_dir)
        (folder / "PLAN.md").write_text(
            f"# Plan {_PLAN_A}: example plan\n\n**Status**: Complete\n", encoding="utf-8"
        )
        refs = ledger.live_plan_refs(plan_dir)
        assert [r.plan_number for r in refs] == [_PLAN_B]

    def test_empty_ledger_yields_no_refs(self, tmp_path: Path) -> None:
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        assert ledger.live_plan_refs(tmp_path / "CLAUDE" / "Plan") == []


class TestNonUtf8PlanMd:
    """RV3-m8: a non-UTF-8 PLAN.md must be treated as unreadable, not crash
    the caller -- review RV-m5 fixed this class for the ledger FILE itself
    (``entries()``); this pins the same tolerance for a live PLAN.md a
    reconciliation pass reads (``_plan_state`` via ``live_plan_numbers``)
    and for ``live_plan_refs``' own text lookup (``_find_plan_md_text``)."""

    def test_live_plan_numbers_tolerates_a_non_utf8_sibling_plan(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        bad_folder = _make_plan(plan_dir, _PLAN_B, _STATUS_IN_PROGRESS)
        (bad_folder / "PLAN.md").write_bytes(b"\xff\xfe\x00\x01not valid utf-8")
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        ledger.record_emission(_SESSION, _PLAN_B, _GOAL_LINE, plan_dir)

        # Must not raise UnicodeDecodeError; the unreadable plan is simply
        # not reported live (nor wrongly retired -- state is "unreadable",
        # never "missing" or "terminal").
        assert ledger.live_plan_numbers(plan_dir) == [_PLAN_A]

    def test_live_plan_refs_tolerates_a_non_utf8_sibling_plan(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        bad_folder = _make_plan(plan_dir, _PLAN_B, _STATUS_IN_PROGRESS)
        (bad_folder / "PLAN.md").write_bytes(b"\xff\xfe\x00\x01not valid utf-8")
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        ledger.record_emission(_SESSION, _PLAN_B, _GOAL_LINE, plan_dir)

        refs = ledger.live_plan_refs(plan_dir)
        assert [r.plan_number for r in refs] == [_PLAN_A]

    def test_find_plan_md_text_skips_a_non_utf8_candidate_directly(self, tmp_path: Path) -> None:
        """RV4-m5: ``_find_plan_md_text``'s OWN ``ValueError`` tolerance,
        pinned directly. Routing through ``live_plan_refs`` (the two tests
        above) never actually reaches this function's except clause --
        ``_plan_state``'s OWN ``(OSError, ValueError)`` catch already marks
        the same undecodable plan unreadable, so ``live_plan_numbers``
        filters it out before ``live_plan_refs`` ever calls
        ``_find_plan_md_text`` for it. Two candidate folders for the SAME
        plan number, the alphabetically-first one undecodable, force this
        function itself to skip a bad candidate and keep looking --
        reverting its except clause to ``except OSError`` alone raises
        ``UnicodeDecodeError`` here instead."""
        from claude_code_hooks_daemon.utils.goal_ledger import _find_plan_md_text

        plan_dir = tmp_path / "CLAUDE" / "Plan"
        bad = plan_dir / f"{_PLAN_A}-a-bad"
        bad.mkdir(parents=True)
        (bad / "PLAN.md").write_bytes(b"\xff\xfe\x00\x01not valid utf-8")
        good = plan_dir / f"{_PLAN_A}-b-good"
        good.mkdir(parents=True)
        (good / "PLAN.md").write_text("**Status**: In Progress\n", encoding="utf-8")

        found = _find_plan_md_text(plan_dir, _PLAN_A)

        assert found is not None
        assert found[0] == good.name


class TestBoundedGrowth:
    def test_retired_entries_are_pruned_beyond_cap(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        ledger_path = tmp_path / LEDGER_FILENAME
        ledger = GoalLedger(ledger_path)
        # Emit far more plans than the cap, each immediately Complete.
        total = 150
        for i in range(total):
            number = f"{60000 + i:05d}"
            _make_plan(plan_dir, number, _STATUS_COMPLETE)
            ledger.record_emission(_SESSION, number, _GOAL_LINE, plan_dir)
        ledger.live_plan_numbers(plan_dir)
        raw = json.loads(ledger_path.read_text(encoding="utf-8"))
        assert len(raw["entries"]) <= 100


class TestStatusParsing:
    """The ledger delegates to PlanDoc.parse — the tested plan-QA parser."""

    def test_terminal_status_with_date_qualifier_retires(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        (folder / "PLAN.md").write_text("**Status**: Complete (2026-05-01)\n", encoding="utf-8")
        assert ledger.live_plan_numbers(plan_dir) == []

    def test_in_progress_with_trailing_icon_stays_live(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        (folder / "PLAN.md").write_text("**Status**: In Progress 🔄\n", encoding="utf-8")
        assert ledger.live_plan_numbers(plan_dir) == [_PLAN_A]

    def test_status_line_inside_fenced_block_is_ignored(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        (folder / "PLAN.md").write_text(
            "**Status**: In Progress\n\n```markdown\n**Status**: Complete\n```\n",
            encoding="utf-8",
        )
        # The fenced Complete must not falsely retire the plan.
        assert ledger.live_plan_numbers(plan_dir) == [_PLAN_A]
        assert ledger.entries()[0].retired_at is None


class TestConcurrentWriters:
    def test_concurrent_emissions_all_recorded(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        ledger_path = tmp_path / LEDGER_FILENAME
        total = 20
        numbers = [f"{70000 + i:05d}" for i in range(total)]
        for number in numbers:
            _make_plan(plan_dir, number, _STATUS_IN_PROGRESS)

        errors: list[BaseException] = []

        def _emit(number: str) -> None:
            try:
                GoalLedger(ledger_path).record_emission(_SESSION, number, _GOAL_LINE, plan_dir)
            except BaseException as exc:  # capture for the assertion below
                errors.append(exc)

        threads = [threading.Thread(target=_emit, args=(n,)) for n in numbers]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        recorded = {e.plan_number for e in GoalLedger(ledger_path).entries()}
        # The flock around each read-modify-write means no emission is lost.
        assert recorded == set(numbers)


class TestHasLiveEntry:
    """Review M2: the persistent answer a fresh (post-restart) handler
    instance needs, in place of an in-memory latch."""

    def test_true_for_a_live_entry_owned_by_this_session(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)

        assert ledger.has_live_entry(_SESSION, _PLAN_A) is True

    def test_false_for_a_different_session(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)

        assert ledger.has_live_entry(_OTHER_SESSION, _PLAN_A) is False

    def test_false_for_a_retired_entry(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        # Rewrite as terminal and reconcile via a live-plan-numbers read.
        _make_plan(plan_dir, _PLAN_A, _STATUS_COMPLETE)
        ledger.live_plan_numbers(plan_dir)

        assert ledger.has_live_entry(_SESSION, _PLAN_A) is False

    def test_false_when_the_ledger_has_never_heard_of_the_plan(self, tmp_path: Path) -> None:
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)

        assert ledger.has_live_entry(_SESSION, _PLAN_A) is False


class TestSessionHasEntries:
    """Review M3: distinguishes a genuinely new session from one that
    already has its own live goal signal."""

    def test_false_for_a_session_the_ledger_has_never_seen(self, tmp_path: Path) -> None:
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)

        assert ledger.session_has_entries(_SESSION) is False

    def test_true_once_the_session_has_emitted(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)

        assert ledger.session_has_entries(_SESSION) is True

    def test_true_even_for_a_retired_entry(self, tmp_path: Path) -> None:
        """A session that fully completed one plan is not "new" either."""
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        _make_plan(plan_dir, _PLAN_A, _STATUS_COMPLETE)
        ledger.live_plan_numbers(plan_dir)

        assert ledger.session_has_entries(_SESSION) is True

    def test_survives_session_id_overwrite_by_a_different_re_emitting_session(
        self, tmp_path: Path
    ) -> None:
        """RV3-n2: ``record_emission`` overwrites the entry's single
        ``session_id`` field with whoever re-emits for the SAME plan next --
        a DIFFERENT session re-flipping plan A must not erase the fact that
        the ORIGINAL session ever recorded anything at all."""
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)

        ledger.record_emission(_OTHER_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)

        entry = next(e for e in ledger.entries() if e.plan_number == _PLAN_A)
        assert entry.session_id == _OTHER_SESSION, "sanity: the field really was overwritten"
        assert ledger.session_has_entries(_SESSION) is True

    def test_survives_pruning_past_the_entry_cap(self, tmp_path: Path) -> None:
        """RV3-n2: ``_prune`` drops the OLDEST retired entries once the
        ledger exceeds its cap -- the session that recorded the dropped
        entry must still read as having recorded SOMETHING, ever, even
        when every SURVIVING entry belongs to other sessions entirely."""
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, "P000", _GOAL_LINE, plan_dir)
        # No PLAN.md folder exists for any of these plan numbers, so each
        # entry reconciles to MISSING (and is retired) on the NEXT call --
        # by the end, well over 100 retired entries exist and _prune has
        # dropped the earliest ones, including _SESSION's very first (and
        # only) entry. Every one of these belongs to a DIFFERENT session,
        # so no surviving entry's own ``session_id``/``sessions`` field
        # could keep _SESSION findable by accident.
        for i in range(1, 105):
            ledger.record_emission(f"other-{i}", f"P{i:03d}", _GOAL_LINE, plan_dir)

        assert not any(
            e.plan_number == "P000" for e in ledger.entries()
        ), "sanity: the first entry really was pruned off the ledger"
        assert ledger.session_has_entries(_SESSION) is True

    def test_false_for_a_reassert_only_session(self, tmp_path: Path) -> None:
        """B4: a session that has ONLY ever been reasserted onto a plan --
        never performed a real emission of its own -- must still read as
        having no entries of its own. Reassertion grants ownership
        additively without the caller having genuinely started anything
        (Plan 00269's "goal survives a restart" contract); conflating that
        with "has entries" would incorrectly block such a session from
        later becoming a stakeholder of a SECOND unrelated live plan too --
        an existing, deliberate behaviour (see
        TestOwnershipSurvivesASecondSession in test_goal_injection.py)."""
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)

        assert ledger.reassert_session(_OTHER_SESSION, _PLAN_A) is True

        assert ledger.session_has_entries(_OTHER_SESSION) is False


class TestReassertSession:
    """Review M3/RV-M1: ADDS a session to a still-live entry's ownership set
    (never a single-owner transfer) with NONE of ``record_emission``'s
    displacement side effects."""

    def test_adds_the_reasserting_session_without_dropping_the_original_owner(
        self, tmp_path: Path
    ) -> None:
        """RV-M1's core defect: a transfer stripped the flipping session's
        own membership the moment a second session reasserted, so it could
        never retract its own signal again."""
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)

        assert ledger.reassert_session(_OTHER_SESSION, _PLAN_A) is True
        entry = next(e for e in ledger.entries() if e.plan_number == _PLAN_A)
        assert set(entry.sessions) == {_SESSION, _OTHER_SESSION}
        assert ledger.has_live_entry(_SESSION, _PLAN_A) is True
        assert ledger.has_live_entry(_OTHER_SESSION, _PLAN_A) is True

    def test_reasserting_the_same_session_twice_does_not_duplicate_it(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)

        ledger.reassert_session(_OTHER_SESSION, _PLAN_A)
        ledger.reassert_session(_OTHER_SESSION, _PLAN_A)

        entry = next(e for e in ledger.entries() if e.plan_number == _PLAN_A)
        assert entry.sessions.count(_OTHER_SESSION) == 1

    def test_false_when_no_live_entry_exists(self, tmp_path: Path) -> None:
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)

        assert ledger.reassert_session(_SESSION, _PLAN_A) is False

    def test_does_not_displace_any_other_live_plan(self, tmp_path: Path) -> None:
        """The defining difference from record_emission: reasserting plan A
        must never mark a DIFFERENT still-live plan B as displaced."""
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        _make_plan(plan_dir, _PLAN_B, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        ledger.record_emission(_OTHER_SESSION, _PLAN_B, _GOAL_LINE, plan_dir)

        ledger.reassert_session(_OTHER_SESSION, _PLAN_A)

        entry_b = next(e for e in ledger.entries() if e.plan_number == _PLAN_B)
        assert entry_b.displaced_by is None


class TestOwningSessions:
    """Review RV-M1/RV-m2: every session a terminal write must refresh."""

    def test_lists_every_session_ever_handed_the_goal(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        ledger.reassert_session(_OTHER_SESSION, _PLAN_A)

        assert set(ledger.owning_sessions(_PLAN_A)) == {_SESSION, _OTHER_SESSION}

    def test_empty_for_a_plan_the_ledger_has_never_heard_of(self, tmp_path: Path) -> None:
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)

        assert ledger.owning_sessions(_PLAN_A) == []

    def test_still_lists_owners_of_an_entry_retired_for_terminal_status(
        self, tmp_path: Path
    ) -> None:
        """RV-m2: a concurrent reconciliation may retire the entry moments
        before this read; the just-retired owners must still be answered,
        not silently dropped by a race."""
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        ledger.reassert_session(_OTHER_SESSION, _PLAN_A)
        (folder / "PLAN.md").write_text(
            f"# Plan {_PLAN_A}: example plan\n\n**Status**: Complete\n", encoding="utf-8"
        )
        ledger.live_plan_numbers(plan_dir)  # reconciles + retires the entry

        assert set(ledger.owning_sessions(_PLAN_A)) == {_SESSION, _OTHER_SESSION}

    def test_empty_for_an_entry_retired_as_archived(self, tmp_path: Path) -> None:
        """Only a TERMINAL-status retirement gets the race-window grace; an
        archived (moved out of the plan dir) entry is genuinely gone."""
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        archive = plan_dir / "Completed"
        archive.mkdir(parents=True, exist_ok=True)
        folder.rename(archive / folder.name)
        ledger.live_plan_numbers(plan_dir)

        assert ledger.owning_sessions(_PLAN_A) == []


class TestOwningSessionsAfterReopen:
    """RV3-M1: a reopened-and-recompleted plan must answer from the LIVE
    entry, or else the MOST RECENTLY retired terminal one -- never the
    first entry in the list, which is what let a reopen retract the
    WRONG (original) session's signal."""

    def test_a_live_entry_always_wins_over_an_older_retired_one(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        # First lifecycle: SESSION flips and completes it.
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        (folder / "PLAN.md").write_text(
            f"# Plan {_PLAN_A}: example plan\n\n**Status**: Complete\n", encoding="utf-8"
        )
        ledger.live_plan_numbers(plan_dir)  # reconciles + retires the first entry
        # Second lifecycle: OTHER_SESSION reopens and re-flips it -- a NEW
        # entry is appended (record_emission only reuses a still-LIVE one).
        (folder / "PLAN.md").write_text(
            f"# Plan {_PLAN_A}: example plan\n\n**Status**: In Progress\n", encoding="utf-8"
        )
        ledger.record_emission(_OTHER_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)

        assert ledger.owning_sessions(_PLAN_A) == [_OTHER_SESSION]

    def test_no_live_entry_picks_the_most_recently_retired_one(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        (folder / "PLAN.md").write_text(
            f"# Plan {_PLAN_A}: example plan\n\n**Status**: Complete\n", encoding="utf-8"
        )
        ledger.live_plan_numbers(plan_dir)
        # Reopen and re-complete with a different session -- both entries
        # end up retired-terminal; only the SECOND lifecycle's owner must
        # be answered.
        (folder / "PLAN.md").write_text(
            f"# Plan {_PLAN_A}: example plan\n\n**Status**: In Progress\n", encoding="utf-8"
        )
        ledger.record_emission(_OTHER_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        (folder / "PLAN.md").write_text(
            f"# Plan {_PLAN_A}: example plan\n\n**Status**: Complete\n", encoding="utf-8"
        )
        ledger.live_plan_numbers(plan_dir)

        assert ledger.owning_sessions(_PLAN_A) == [_OTHER_SESSION]


class TestIsPlanLive:
    """RV3-m6: the Write flip detector needs to know whether the ledger
    ALREADY has a live entry for a plan, independent of which session owns
    it -- git HEAD can lag an uncommitted flip."""

    def test_true_for_a_live_entry(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)

        assert ledger.is_plan_live(_PLAN_A) is True

    def test_false_for_a_plan_never_ledgered(self, tmp_path: Path) -> None:
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)

        assert ledger.is_plan_live(_PLAN_A) is False

    def test_false_for_a_retired_entry(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        (folder / "PLAN.md").write_text(
            f"# Plan {_PLAN_A}: example plan\n\n**Status**: Complete\n", encoding="utf-8"
        )
        ledger.live_plan_numbers(plan_dir)

        assert ledger.is_plan_live(_PLAN_A) is False


class TestUnreadableEncoding:
    """Review RV-m5: a non-UTF-8 ledger file must be treated as corrupt,
    not raise past this fail-open API."""

    def test_non_utf8_ledger_is_tolerated_like_any_other_corrupt_file(self, tmp_path: Path) -> None:
        ledger_path = tmp_path / LEDGER_FILENAME
        ledger_path.write_bytes(b"\xff\xfe\x00\x01not valid utf-8")
        ledger = GoalLedger(ledger_path)

        assert ledger.entries() == []
