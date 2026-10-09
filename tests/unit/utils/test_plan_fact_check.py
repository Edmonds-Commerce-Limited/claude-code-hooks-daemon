"""Tests for the plan fact-check state and diff (Plan 00480 Tasks 4.1/4.2, 00474 N359).

The debounced fire records NOTHING about delivery: it stores a "pending
fact-check" record. :func:`deliver_pending` (run on the next hook event) turns
each record into an instruction for the session and keeps it as an *offered*
record; only :func:`confirm_dispatch` (the session really dispatched the agent)
advances the checked content.
"""

import logging
import threading
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.plan_fact_check import (
    CORRECTION_MAX_CHANGED_LINES,
    CORRECTION_WINDOW_SECONDS,
    MAX_OFFERS,
    REOFFER_AFTER_SECONDS,
    PendingFactCheck,
    PlanFactCheckState,
    PlanFactCheckStateError,
    confirm_dispatch,
    deliver_pending,
    plan_folder_match,
    process_quiet_plan,
    snapshot_hash,
    snapshot_plan,
)

FOLDER = "00480-demo"
BARRIER_WAIT_SECONDS = 10
THREAD_JOIN_SECONDS = 20


def _plan(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "CLAUDE" / "Plan" / FOLDER
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _seeded(tmp_path: Path, base: str = "base\n") -> tuple[Path, PlanFactCheckState]:
    """A plan whose ``base`` content is already recorded as checked (past first sight)."""
    root = _plan(tmp_path, {"PLAN.md": base})
    state = PlanFactCheckState(tmp_path / "state")
    process_quiet_plan(root, FOLDER, state, trigger_count=1, now=0.0)
    return root, state


def _edit(root: Path, text: str) -> None:
    (root / "PLAN.md").write_text(text, encoding="utf-8")


def _confirm(state: PlanFactCheckState, now: float = 1.0) -> list[str]:
    return confirm_dispatch(state, f"check this diff: {state.diff_path(FOLDER)}", now=now)


class TestPlanFolderMatch:
    def test_matches_a_plan_document(self) -> None:
        match = plan_folder_match("/p/CLAUDE/Plan/00480-demo/PLAN.md", "CLAUDE/Plan")
        assert match is not None
        assert match.folder == "00480-demo"
        assert match.plan_root == Path("/p/CLAUDE/Plan/00480-demo")

    def test_matches_a_supporting_document(self) -> None:
        assert plan_folder_match("/p/CLAUDE/Plan/00480-demo/DESIGN.md", "CLAUDE/Plan")

    @pytest.mark.parametrize(
        "path",
        [
            "/p/src/module.py",
            "/p/CLAUDE/Plan/README.md",
            "/p/CLAUDE/Plan/Completed/00001-old/PLAN.md",
            "/p/CLAUDE/Plan/00480-demo/subagent-reports/r.md",
            "/p/CLAUDE/Plan/00480-demo/JOURNAL/26-10-02.md",
            "/p/CLAUDE/Plan/00480-demo/data.json",
        ],
    )
    def test_ignores_everything_else(self, path: str) -> None:
        assert plan_folder_match(path, "CLAUDE/Plan") is None

    def test_honours_a_configured_plan_dir(self) -> None:
        assert plan_folder_match("/p/plans/00001-x/PLAN.md", "plans") is not None
        assert plan_folder_match("/p/CLAUDE/Plan/00001-x/PLAN.md", "plans") is None


class TestSnapshot:
    def test_collects_markdown_and_skips_excluded(self, tmp_path: Path) -> None:
        root = _plan(
            tmp_path,
            {
                "PLAN.md": "a",
                "DESIGN.md": "b",
                "notes.txt": "c",
                "JOURNAL/d.md": "d",
                "subagent-reports/r.md": "e",
            },
        )
        assert snapshot_plan(root) == {"PLAN.md": "a", "DESIGN.md": "b"}

    def test_hash_depends_on_content_and_names(self) -> None:
        assert snapshot_hash({"A.md": "x"}) == snapshot_hash({"A.md": "x"})
        assert snapshot_hash({"A.md": "x"}) != snapshot_hash({"A.md": "y"})
        assert snapshot_hash({"A.md": "x"}) != snapshot_hash({"B.md": "x"})


class TestState:
    def test_nothing_recorded_initially(self, tmp_path: Path) -> None:
        state = PlanFactCheckState(tmp_path / "state")
        assert state.read_checked(FOLDER) is None
        assert state.read_pending(FOLDER) is None
        assert state.read_offered(FOLDER) is None
        assert state.offered_folders() == []
        assert state.outstanding(FOLDER) is False

    def test_checked_round_trips(self, tmp_path: Path) -> None:
        state = PlanFactCheckState(tmp_path / "state")
        files = {"PLAN.md": "hello"}
        state.record_checked(FOLDER, files, checked_at=12.5)
        checked = state.read_checked(FOLDER)
        assert checked is not None
        assert checked.content_hash == snapshot_hash(files)
        assert checked.files == files
        assert checked.checked_at == 12.5

    def test_checked_without_a_time_reads_back_none(self, tmp_path: Path) -> None:
        state = PlanFactCheckState(tmp_path / "state")
        state.record_checked(FOLDER, {"PLAN.md": "hello"})
        checked = state.read_checked(FOLDER)
        assert checked is not None
        assert checked.checked_at is None


class TestProcessQuietPlan:
    def test_first_sight_records_a_baseline_and_owes_nothing(self, tmp_path: Path) -> None:
        """N359 item 3: no checked content yet means no whole-folder diff, only a baseline."""
        root = _plan(tmp_path, {"PLAN.md": "line one\n", "NIGGLES.md": "big\n"})
        state = PlanFactCheckState(tmp_path / "state")
        assert process_quiet_plan(root, FOLDER, state, trigger_count=3, now=100.0) is None
        assert state.read_pending(FOLDER) is None
        checked = state.read_checked(FOLDER)
        assert checked is not None
        assert checked.files == snapshot_plan(root)
        assert checked.checked_at is None

    def test_second_fire_stores_pending_with_the_edit_only(self, tmp_path: Path) -> None:
        root, state = _seeded(tmp_path, "keep\n")
        _edit(root, "keep\nline one\n")
        pending = process_quiet_plan(root, FOLDER, state, trigger_count=3, now=100.0)
        assert pending is not None
        assert "+line one" in pending.diff
        assert "+keep" not in pending.diff
        assert pending.trigger_count == 3
        assert pending.content_hash == snapshot_hash({"PLAN.md": "keep\nline one\n"})
        assert state.read_pending(FOLDER) == pending

    def test_diff_is_since_the_last_checked_content(self, tmp_path: Path) -> None:
        root = _plan(tmp_path, {"PLAN.md": "old\n"})
        state = PlanFactCheckState(tmp_path / "state")
        state.record_checked(FOLDER, snapshot_plan(root))
        (root / "PLAN.md").write_text("old\nnew claim\n", encoding="utf-8")
        pending = process_quiet_plan(root, FOLDER, state, trigger_count=1, now=1.0)
        assert pending is not None
        assert "+new claim" in pending.diff
        assert "+old" not in pending.diff

    def test_unchanged_since_checked_stores_nothing(self, tmp_path: Path) -> None:
        root = _plan(tmp_path, {"PLAN.md": "same\n"})
        state = PlanFactCheckState(tmp_path / "state")
        state.record_checked(FOLDER, snapshot_plan(root))
        assert process_quiet_plan(root, FOLDER, state, trigger_count=2, now=1.0) is None
        assert state.read_pending(FOLDER) is None

    def test_fire_does_not_advance_the_checked_hash(self, tmp_path: Path) -> None:
        """Only a confirmed dispatch marks content as checked."""
        root, state = _seeded(tmp_path, "v1\n")
        _edit(root, "v2\n")
        assert process_quiet_plan(root, FOLDER, state, trigger_count=1, now=1.0) is not None
        checked = state.read_checked(FOLDER)
        assert checked is not None
        assert checked.files == {"PLAN.md": "v1\n"}

    def test_a_vanished_plan_stores_nothing(self, tmp_path: Path) -> None:
        state = PlanFactCheckState(tmp_path / "state")
        missing = tmp_path / "CLAUDE" / "Plan" / FOLDER
        assert process_quiet_plan(missing, FOLDER, state, trigger_count=1, now=1.0) is None
        assert state.read_pending(FOLDER) is None


class TestDelivery:
    def _pending(self, tmp_path: Path, text: str = "claim\n") -> tuple[Path, PlanFactCheckState]:
        root, state = _seeded(tmp_path)
        _edit(root, text)
        process_quiet_plan(root, FOLDER, state, trigger_count=1, now=1.0)
        return root, state

    def test_pending_folders_lists_owed_checks(self, tmp_path: Path) -> None:
        _, state = self._pending(tmp_path)
        assert state.pending_folders() == [FOLDER]

    def test_pending_folders_empty_without_state_dir(self, tmp_path: Path) -> None:
        assert PlanFactCheckState(tmp_path / "nope").pending_folders() == []

    def test_delivery_returns_instruction_naming_agent_plan_and_diff_file(
        self, tmp_path: Path
    ) -> None:
        root, state = self._pending(tmp_path)
        messages = deliver_pending(state, now=2.0)
        assert len(messages) == 1
        text = messages[0]
        assert "plan-fact-checker" in text
        assert str(root / "PLAN.md") in text
        assert "REFUTED" in text
        diff_file = tmp_path / "state" / f"{FOLDER}.diff"
        assert str(diff_file) in text
        assert "+claim" in diff_file.read_text(encoding="utf-8")

    def test_delivery_without_a_clock_uses_wall_time(self, tmp_path: Path) -> None:
        _, state = self._pending(tmp_path)
        assert len(deliver_pending(state)) == 1

    def test_delivery_does_not_advance_checked_until_the_dispatch_is_seen(
        self, tmp_path: Path
    ) -> None:
        """N359 item 4: a lost message must not lose the check."""
        root, state = self._pending(tmp_path)
        deliver_pending(state, now=2.0)
        assert state.read_pending(FOLDER) is None
        checked = state.read_checked(FOLDER)
        assert checked is not None
        assert checked.files == {"PLAN.md": "base\n"}
        assert _confirm(state, now=3.0) == [FOLDER]
        checked = state.read_checked(FOLDER)
        assert checked is not None
        assert checked.files == snapshot_plan(root)
        assert checked.checked_at == 3.0
        assert state.offered_folders() == []

    def test_an_undelivered_check_is_re_offered_after_the_wait(self, tmp_path: Path) -> None:
        _, state = self._pending(tmp_path)
        assert len(deliver_pending(state, now=10.0)) == 1
        assert deliver_pending(state, now=10.0 + REOFFER_AFTER_SECONDS - 1) == []
        again = deliver_pending(state, now=10.0 + REOFFER_AFTER_SECONDS + 1)
        assert len(again) == 1
        assert FOLDER in again[0]

    def test_re_offer_stops_after_the_cap_without_losing_the_content(self, tmp_path: Path) -> None:
        root, state = self._pending(tmp_path)
        now = 10.0
        delivered = 0
        for _ in range(MAX_OFFERS + 2):
            delivered += len(deliver_pending(state, now=now))
            now += REOFFER_AFTER_SECONDS + 1
        assert delivered == MAX_OFFERS
        assert state.offered_folders() == []
        checked = state.read_checked(FOLDER)
        assert checked is not None
        assert checked.files == {"PLAN.md": "base\n"}  # still owed, folded into the next diff
        _edit(root, "claim\nmore\n")
        pending = process_quiet_plan(root, FOLDER, state, trigger_count=1, now=now + 10_000)
        assert pending is not None
        assert "+claim" in pending.diff

    def test_a_dispatch_naming_another_diff_confirms_nothing(self, tmp_path: Path) -> None:
        _, state = self._pending(tmp_path)
        deliver_pending(state, now=2.0)
        assert confirm_dispatch(state, "some other prompt", now=3.0) == []
        assert state.offered_folders() == [FOLDER]

    def test_a_newer_pending_check_supersedes_the_offer(self, tmp_path: Path) -> None:
        root, state = self._pending(tmp_path)
        deliver_pending(state, now=2.0)
        _edit(root, "claim\nsecond\n")
        process_quiet_plan(root, FOLDER, state, trigger_count=1, now=3.0)
        assert state.outstanding(FOLDER)
        assert len(deliver_pending(state, now=4.0)) == 1
        offered = state.read_offered(FOLDER)
        assert offered is not None
        assert "+second" in offered.diff
        assert offered.offers == 1

    def test_each_pending_record_is_delivered_once(self, tmp_path: Path) -> None:
        _, state = self._pending(tmp_path)
        assert len(deliver_pending(state, now=2.0)) == 1
        assert deliver_pending(state, now=2.0) == []

    def test_next_diff_is_since_the_confirmed_content(self, tmp_path: Path) -> None:
        root, state = self._pending(tmp_path, "old\n")
        deliver_pending(state, now=2.0)
        _confirm(state, now=2.0)
        _edit(root, "old\nnew claim\n")
        late = 2.0 + 2 * CORRECTION_WINDOW_SECONDS
        process_quiet_plan(root, FOLDER, state, trigger_count=1, now=late)
        deliver_pending(state, now=late + 1)
        diff = (tmp_path / "state" / f"{FOLDER}.diff").read_text(encoding="utf-8")
        assert "+new claim" in diff
        assert "+old" not in diff

    def test_archived_plan_is_delivered_under_its_resolved_path(self, tmp_path: Path) -> None:
        """N359 item 2: never name a path that does not exist."""
        root, state = self._pending(tmp_path)
        archived = root.parent / "Completed" / FOLDER
        archived.parent.mkdir()
        root.rename(archived)
        messages = deliver_pending(state, now=2.0)
        assert len(messages) == 1
        assert str(archived / "PLAN.md") in messages[0]
        assert str(root / "PLAN.md") not in messages[0]

    def test_a_vanished_plan_drops_the_record(self, tmp_path: Path) -> None:
        root, state = self._pending(tmp_path)
        (root / "PLAN.md").unlink()
        root.rmdir()
        assert deliver_pending(state, now=2.0) == []
        assert state.pending_folders() == []
        assert state.offered_folders() == []

    def test_an_offer_for_a_plan_that_vanished_is_dropped_on_re_offer(
        self, tmp_path: Path
    ) -> None:
        root, state = self._pending(tmp_path)
        deliver_pending(state, now=2.0)
        (root / "PLAN.md").unlink()
        root.rmdir()
        assert deliver_pending(state, now=2.0 + REOFFER_AFTER_SECONDS + 1) == []
        assert state.offered_folders() == []

    def test_unreadable_offer_is_set_aside_on_re_offer(self, tmp_path: Path) -> None:
        state = PlanFactCheckState(tmp_path)
        bad = tmp_path / f"{FOLDER}.offered.json"
        bad.write_text("{nope", encoding="utf-8")
        assert deliver_pending(state, now=10_000_000_000.0) == []
        assert not bad.exists()
        assert (tmp_path / f"{FOLDER}.offered.json.unreadable").is_file()

    def test_unreadable_offer_is_set_aside_on_confirm(self, tmp_path: Path) -> None:
        state = PlanFactCheckState(tmp_path)
        (tmp_path / f"{FOLDER}.offered.json").write_text("{nope", encoding="utf-8")
        assert confirm_dispatch(state, "anything", now=1.0) == []
        assert (tmp_path / f"{FOLDER}.offered.json.unreadable").is_file()

    def test_unreadable_pending_is_set_aside_not_raised(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        state = PlanFactCheckState(tmp_path)
        bad = tmp_path / f"{FOLDER}.pending.json"
        bad.write_text("{nope", encoding="utf-8")
        with caplog.at_level(logging.INFO, logger="claude_code_hooks_daemon.utils.plan_fact_check"):
            assert deliver_pending(state) == []
        assert not bad.exists()
        assert (tmp_path / f"{FOLDER}.pending.json.unreadable").is_file()
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 1
        assert warnings[0].levelno == logging.WARNING
        assert warnings[0].exc_info is None
        assert f"{FOLDER}.pending.json" in warnings[0].getMessage()

    def test_old_format_record_is_never_re_read(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        state = PlanFactCheckState(tmp_path)
        (tmp_path / f"{FOLDER}.pending.json").write_text('{"folder": "x"}', encoding="utf-8")
        deliver_pending(state)
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="claude_code_hooks_daemon.utils.plan_fact_check"):
            assert deliver_pending(state) == []
        assert state.pending_folders() == []
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_two_concurrent_deliveries_hand_out_exactly_one_instruction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """N374: both events list the record before either takes it; only one may deliver."""
        _, state = self._pending(tmp_path)
        barrier = threading.Barrier(2)
        listing = state.pending_folders

        def listed_by_both() -> list[str]:
            folders = listing()
            barrier.wait(timeout=BARRIER_WAIT_SECONDS)
            return folders

        monkeypatch.setattr(state, "pending_folders", listed_by_both)
        results: list[list[str]] = []

        def deliver() -> None:
            results.append(deliver_pending(state, now=2.0))

        threads = [threading.Thread(target=deliver) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=THREAD_JOIN_SECONDS)

        assert sorted(len(messages) for messages in results) == [0, 1]
        assert state.read_pending(FOLDER) is None
        assert not list(tmp_path.glob("state/.*.tmp"))

    def test_a_record_that_vanished_after_listing_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state = PlanFactCheckState(tmp_path)
        monkeypatch.setattr(state, "pending_folders", lambda: [FOLDER])
        assert deliver_pending(state) == []

    def test_an_unreadable_record_that_vanished_after_listing_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state = PlanFactCheckState(tmp_path)
        pending = tmp_path / f"{FOLDER}.pending.json"
        pending.write_text("{nope", encoding="utf-8")
        listing = state.pending_folders

        def listed_then_taken() -> list[str]:
            folders = listing()
            pending.unlink()
            return folders

        monkeypatch.setattr(state, "pending_folders", listed_then_taken)
        assert deliver_pending(state) == []

    def test_a_claimed_unreadable_record_is_set_aside(self, tmp_path: Path) -> None:
        state = PlanFactCheckState(tmp_path)
        (tmp_path / f"{FOLDER}.pending.json").write_text("{nope", encoding="utf-8")
        assert deliver_pending(state) == []
        assert (tmp_path / f"{FOLDER}.pending.json.unreadable").is_file()
        assert not list(tmp_path.glob(".*.tmp"))

    def test_valid_record_after_a_malformed_one_is_delivered(self, tmp_path: Path) -> None:
        root, state = _seeded(tmp_path)
        (tmp_path / "state" / "00001-aaa.pending.json").write_text('{"folder": "x"}', "utf-8")
        _edit(root, "claim\n")
        process_quiet_plan(root, FOLDER, state, trigger_count=1, now=1.0)
        assert state.pending_folders() == ["00001-aaa", FOLDER]
        messages = deliver_pending(state, now=2.0)
        assert len(messages) == 1
        assert FOLDER in messages[0]
        assert state.pending_folders() == []


class TestCorrectionLoop:
    """N359 item 5: a check plus its corrections is one check, not a chain."""

    def _checked_at(self, tmp_path: Path, at: float) -> tuple[Path, PlanFactCheckState]:
        root, state = _seeded(tmp_path, "base\n")
        state.record_checked(FOLDER, snapshot_plan(root), checked_at=at)
        return root, state

    def test_a_small_edit_right_after_a_check_owes_nothing_and_is_absorbed(
        self, tmp_path: Path
    ) -> None:
        root, state = self._checked_at(tmp_path, 100.0)
        _edit(root, "base corrected\n")
        assert process_quiet_plan(root, FOLDER, state, trigger_count=1, now=160.0) is None
        assert state.pending_folders() == []
        checked = state.read_checked(FOLDER)
        assert checked is not None
        assert checked.files == {"PLAN.md": "base corrected\n"}
        assert checked.checked_at == 100.0  # the window does not slide

    def test_the_same_edit_after_the_window_is_checked(self, tmp_path: Path) -> None:
        root, state = self._checked_at(tmp_path, 100.0)
        _edit(root, "base corrected\n")
        late = 100.0 + CORRECTION_WINDOW_SECONDS + 1
        assert process_quiet_plan(root, FOLDER, state, trigger_count=1, now=late) is not None

    def test_a_large_edit_inside_the_window_is_still_checked(self, tmp_path: Path) -> None:
        root, state = self._checked_at(tmp_path, 100.0)
        _edit(root, "base\n" + "new claim\n" * (CORRECTION_MAX_CHANGED_LINES + 1))
        assert process_quiet_plan(root, FOLDER, state, trigger_count=1, now=160.0) is not None

    def test_an_edit_while_an_earlier_check_is_outstanding_is_not_absorbed(
        self, tmp_path: Path
    ) -> None:
        root, state = self._checked_at(tmp_path, 100.0)
        state.store_pending(
            PendingFactCheck(FOLDER, "h", "d", 1, 1.0, str(root), {"PLAN.md": "x"})
        )
        _edit(root, "base corrected\n")
        assert process_quiet_plan(root, FOLDER, state, trigger_count=1, now=160.0) is not None


class TestCorruptState:
    def test_corrupt_checked_state_fails_loudly(self, tmp_path: Path) -> None:
        state = PlanFactCheckState(tmp_path)
        (tmp_path / f"{FOLDER}.checked.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(PlanFactCheckStateError):
            state.read_checked(FOLDER)

    def test_malformed_pending_state_fails_loudly(self, tmp_path: Path) -> None:
        state = PlanFactCheckState(tmp_path)
        (tmp_path / f"{FOLDER}.pending.json").write_text('{"folder": "x"}', encoding="utf-8")
        with pytest.raises(PlanFactCheckStateError):
            state.read_pending(FOLDER)

    def test_unsafe_folder_name_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            PlanFactCheckState(tmp_path).read_checked("../escape")
