"""Tests for the goal-loop detector's pure logic (Plan 00501 Tasks 6.1, 6.2).

Transcript fixtures are scrubbed: a placeholder session id, ``/workspace``
paths and invented content (``tests/fixtures/goal_loop/``).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.goal_loop import (
    Checkpoint,
    CheckpointInvalidError,
    CycleRing,
    DetectorMode,
    EventKind,
    FingerprintError,
    GoalLoopConfig,
    LoopEvent,
    ResetCause,
    Verdict,
    assess,
    extract_events,
    option_problems,
    read_new_lines,
    repo_fingerprint,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "goal_loop"
PREFIX = "STOPPING BECAUSE:"


def _declares(text: str) -> bool:
    return "[awaiting-human]" in text


def _events(name: str) -> tuple[LoopEvent, ...]:
    lines = (FIXTURES / name).read_text(encoding="utf-8").splitlines()
    return extract_events(lines, stop_prefix=PREFIX, declares_blocked=_declares).events


def _kinds(events: tuple[LoopEvent, ...]) -> list[EventKind]:
    return [event.kind for event in events]


def _ring(name: str, config: GoalLoopConfig | None = None) -> CycleRing:
    ring = CycleRing(window_seconds=(config or GoalLoopConfig()).window_seconds)
    ring.feed(_events(name))
    return ring


# --- 6.1 extraction ------------------------------------------------------------


class TestExtractEvents:
    def test_similar_stops_yield_three_stop_unmet_pairs_after_one_human(self) -> None:
        kinds = _kinds(_events("similar_stops.jsonl"))
        assert kinds == [EventKind.HUMAN] + [EventKind.STOP, EventKind.UNMET] * 3

    def test_sentinel_snapshots_meta_feedback_and_tool_results_are_not_events(self) -> None:
        events = _events("similar_stops.jsonl")
        assert EventKind.GOAL_CLEARED not in _kinds(events)
        assert sum(1 for e in events if e.kind is EventKind.HUMAN) == 1

    def test_stop_text_starts_at_the_prefix(self) -> None:
        first_stop = next(e for e in _events("similar_stops.jsonl") if e.kind is EventKind.STOP)
        assert first_stop.text.startswith(PREFIX)
        assert "Work done so far" not in first_stop.text

    def test_timestamps_are_epoch_seconds_in_order(self) -> None:
        events = _events("similar_stops.jsonl")
        times = [e.at for e in events]
        assert times == sorted(times)
        assert times[0] > 1_700_000_000

    def test_machine_prompts_are_not_human_but_a_typed_prompt_is(self) -> None:
        events = _events("machine_and_human_prompts.jsonl")
        humans = [e for e in events if e.kind is EventKind.HUMAN]
        assert len(humans) == 2
        assert _kinds(events)[-3:] == [EventKind.HUMAN, EventKind.STOP, EventKind.UNMET]

    def test_declared_stops_are_flagged_through_the_injected_matcher(self) -> None:
        stops = [e for e in _events("declared_stops.jsonl") if e.kind is EventKind.STOP]
        assert [s.declared for s in stops] == [True, True]
        plain = [e for e in _events("reworded_stops.jsonl") if e.kind is EventKind.STOP]
        assert not any(s.declared for s in plain)

    def test_goal_clear_snapshot_is_a_goal_cleared_event(self) -> None:
        assert _kinds(_events("goal_cleared.jsonl"))[-1] is EventKind.GOAL_CLEARED

    def test_met_evaluation_is_goal_met(self) -> None:
        record = {
            "type": "attachment",
            "timestamp": "2026-01-05T10:00:00.000Z",
            "attachment": {"type": "goal_status", "met": True, "condition": "c", "reason": "ok"},
        }
        result = extract_events(
            [json.dumps(record)], stop_prefix=PREFIX, declares_blocked=_declares
        )
        assert _kinds(result.events) == [EventKind.GOAL_MET]

    def test_unparseable_and_untimed_lines_are_counted_not_raised(self) -> None:
        untimed = {"type": "attachment", "attachment": {"type": "goal_status", "met": False}}
        result = extract_events(
            ["not json", "[1, 2]", json.dumps(untimed), ""],
            stop_prefix=PREFIX,
            declares_blocked=_declares,
        )
        assert result.events == ()
        assert result.skipped == 3

    def test_text_only_list_content_is_a_prompt(self) -> None:
        record = {
            "type": "user",
            "timestamp": "2026-01-05T10:00:00.000Z",
            "message": {"role": "user", "content": [{"type": "text", "text": "carry on please"}]},
        }
        result = extract_events(
            [json.dumps(record)], stop_prefix=PREFIX, declares_blocked=_declares
        )
        assert _kinds(result.events) == [EventKind.HUMAN]

    def test_assistant_text_without_prefix_is_not_a_stop(self) -> None:
        record = {
            "type": "assistant",
            "timestamp": "2026-01-05T10:00:00.000Z",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Done."}]},
        }
        result = extract_events(
            [json.dumps(record)], stop_prefix=PREFIX, declares_blocked=_declares
        )
        assert result.events == ()


# --- 6.1 checkpointed reads ----------------------------------------------------


class TestReadNewLines:
    def test_first_sight_reads_only_the_bounded_tail_from_a_line_boundary(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "t.jsonl"
        path.write_text("".join(f"line-{i:04d}\n" for i in range(100)), encoding="utf-8")
        lines, checkpoint = read_new_lines(path, None, tail_bytes=35)
        assert lines == ["line-0097", "line-0098", "line-0099"]
        assert checkpoint.offset == path.stat().st_size
        assert checkpoint.inode == path.stat().st_ino

    def test_steady_state_reads_only_appended_complete_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "t.jsonl"
        path.write_text("a\n", encoding="utf-8")
        _, checkpoint = read_new_lines(path, None, tail_bytes=1024)
        with path.open("a", encoding="utf-8") as handle:
            handle.write("b\nc\npartial")
        lines, checkpoint = read_new_lines(path, checkpoint, tail_bytes=1024)
        assert lines == ["b", "c"]
        assert checkpoint.offset == len(b"a\nb\nc\n")
        with path.open("a", encoding="utf-8") as handle:
            handle.write("-done\n")
        lines, _ = read_new_lines(path, checkpoint, tail_bytes=1024)
        assert lines == ["partial-done"]

    def test_a_backlog_beyond_the_tail_is_skipped_to_the_tail(self, tmp_path: Path) -> None:
        path = tmp_path / "t.jsonl"
        path.write_text("a\n", encoding="utf-8")
        _, checkpoint = read_new_lines(path, None, tail_bytes=10)
        with path.open("a", encoding="utf-8") as handle:
            handle.write("".join(f"n{i:03d}\n" for i in range(50)))
        lines, _ = read_new_lines(path, checkpoint, tail_bytes=10)
        assert lines == ["n048", "n049"]

    def test_a_shrunk_file_is_an_invalid_checkpoint_anchored_at_eof(self, tmp_path: Path) -> None:
        path = tmp_path / "t.jsonl"
        path.write_text("aaaa\nbbbb\n", encoding="utf-8")
        _, checkpoint = read_new_lines(path, None, tail_bytes=1024)
        path.write_text("c\n", encoding="utf-8")
        with pytest.raises(CheckpointInvalidError) as caught:
            read_new_lines(path, checkpoint, tail_bytes=1024)
        assert caught.value.anchor.offset == 2
        assert "shrank" in str(caught.value)

    def test_a_replaced_file_is_an_invalid_checkpoint(self, tmp_path: Path) -> None:
        path = tmp_path / "t.jsonl"
        path.write_text("a\n", encoding="utf-8")
        _, checkpoint = read_new_lines(path, None, tail_bytes=1024)
        moved = Checkpoint(path=checkpoint.path, inode=checkpoint.inode + 1, offset=0)
        with pytest.raises(CheckpointInvalidError, match="inode"):
            read_new_lines(path, moved, tail_bytes=1024)

    def test_a_different_path_is_an_invalid_checkpoint(self, tmp_path: Path) -> None:
        path = tmp_path / "t.jsonl"
        path.write_text("a\n", encoding="utf-8")
        other = Checkpoint(path=str(tmp_path / "other.jsonl"), inode=1, offset=0)
        with pytest.raises(CheckpointInvalidError, match="path"):
            read_new_lines(path, other, tail_bytes=1024)

    def test_a_missing_file_raises_oserror(self, tmp_path: Path) -> None:
        with pytest.raises(OSError):
            read_new_lines(tmp_path / "absent.jsonl", None, tail_bytes=1024)


# --- 6.2 config ----------------------------------------------------------------


class TestGoalLoopConfig:
    def test_defaults(self) -> None:
        config = GoalLoopConfig()
        assert config.mode is DetectorMode.OBSERVE
        assert (config.cycle_threshold, config.declared_cycle_threshold) == (3, 2)
        assert config.window_seconds == 30 * 60
        assert config.blocked_hours == 4

    def test_from_options_reads_each_option(self) -> None:
        config = GoalLoopConfig.from_options(
            {
                "mode": "observe",
                "cycle_threshold": 5,
                "declared_cycle_threshold": 3,
                "window_minutes": 10,
                "blocked_hours": 2,
            }
        )
        assert (config.cycle_threshold, config.declared_cycle_threshold) == (5, 3)
        assert config.window_seconds == 600
        assert config.blocked_hours == 2

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("mode", "halt"),
            ("mode", "loud"),
            ("cycle_threshold", 0),
            ("cycle_threshold", True),
            ("cycle_threshold", "3"),
            ("declared_cycle_threshold", -1),
            ("window_minutes", 0),
            ("blocked_hours", 0),
        ],
    )
    def test_invalid_options_are_named_problems(self, key: str, value: object) -> None:
        problems = option_problems({key: value})
        assert set(problems) == {key}
        with pytest.raises(ValueError, match=key):
            GoalLoopConfig.from_options({key: value})

    def test_valid_options_have_no_problems(self) -> None:
        assert option_problems({"mode": "observe", "cycle_threshold": 4}) == {}

    def test_act_is_a_valid_mode(self) -> None:
        assert option_problems({"mode": "act"}) == {}
        assert GoalLoopConfig.from_options({"mode": "act"}).mode is DetectorMode.ACT

    def test_blocked_seconds_is_blocked_hours_in_seconds(self) -> None:
        assert GoalLoopConfig().blocked_seconds == 4 * 3600
        assert GoalLoopConfig(blocked_hours=0.5).blocked_seconds == 1800


# --- 6.2 the ring and the verdict ----------------------------------------------


class TestCycleRing:
    def test_three_similar_cycles_would_enter(self) -> None:
        ring = _ring("similar_stops.jsonl")
        assessment = assess(ring, GoalLoopConfig())
        assert assessment.verdict is Verdict.WOULD_ENTER
        assert (assessment.count, assessment.threshold) == (3, 3)
        assert all(s > 0.8 for s in assessment.similarities)

    def test_reworded_stops_fire_at_low_similarity(self) -> None:
        assessment = assess(_ring("reworded_stops.jsonl"), GoalLoopConfig())
        assert assessment.verdict is Verdict.WOULD_ENTER
        assert all(s < 0.6 for s in assessment.similarities)

    def test_two_declared_cycles_meet_the_declared_threshold(self) -> None:
        assessment = assess(_ring("declared_stops.jsonl"), GoalLoopConfig())
        assert assessment.verdict is Verdict.WOULD_ENTER
        assert (assessment.count, assessment.threshold, assessment.declared) == (2, 2, 2)

    def test_one_below_threshold_is_a_near_miss(self) -> None:
        ring = _ring("goal_cleared.jsonl")
        assert ring.cycles == ()
        events = _events("goal_cleared.jsonl")[:-1]
        ring = CycleRing(window_seconds=1800)
        ring.feed(events)
        assessment = assess(ring, GoalLoopConfig())
        assert assessment.verdict is Verdict.NEAR_MISS
        assert assessment.count == 2

    def test_machine_prompts_do_not_reset_but_a_human_prompt_does(self) -> None:
        ring = CycleRing(window_seconds=1800)
        result = ring.feed(_events("machine_and_human_prompts.jsonl"))
        assert [(r.cause, r.dropped) for r in result.resets] == [(ResetCause.HUMAN_PROMPT, 3)]
        assert len(ring.cycles) == 1
        assert result.new_cycles == 4

    def test_goal_clear_resets_with_its_cause(self) -> None:
        ring = CycleRing(window_seconds=1800)
        result = ring.feed(_events("goal_cleared.jsonl"))
        assert [(r.cause, r.dropped) for r in result.resets] == [(ResetCause.GOAL_CLEARED, 2)]

    def test_goal_met_resets_with_its_cause(self) -> None:
        ring = CycleRing(window_seconds=1800)
        ring.feed(_events("declared_stops.jsonl"))
        result = ring.feed([LoopEvent(kind=EventKind.GOAL_MET, at=2e9)])
        assert [r.cause for r in result.resets] == [ResetCause.GOAL_MET]

    def test_an_empty_ring_reset_is_not_reported(self) -> None:
        ring = CycleRing(window_seconds=1800)
        result = ring.feed([LoopEvent(kind=EventKind.HUMAN, at=1.0)])
        assert result.resets == ()

    def test_unmet_without_a_preceding_stop_is_not_a_cycle(self) -> None:
        ring = CycleRing(window_seconds=1800)
        result = ring.feed([LoopEvent(kind=EventKind.UNMET, at=1.0)])
        assert result.new_cycles == 0

    def test_a_human_between_stop_and_unmet_breaks_the_cycle(self) -> None:
        ring = CycleRing(window_seconds=1800)
        ring.feed(
            [
                LoopEvent(kind=EventKind.STOP, at=1.0, text="STOPPING BECAUSE: x"),
                LoopEvent(kind=EventKind.HUMAN, at=2.0),
                LoopEvent(kind=EventKind.UNMET, at=3.0),
            ]
        )
        assert ring.cycles == ()

    def test_cycles_older_than_the_window_drop_out(self) -> None:
        ring = CycleRing(window_seconds=60)
        events = []
        for at in (0.0, 100.0, 130.0):
            events += [
                LoopEvent(kind=EventKind.STOP, at=at, text="STOPPING BECAUSE: x"),
                LoopEvent(kind=EventKind.UNMET, at=at + 1),
            ]
        ring.feed(events)
        assert [c.at for c in ring.cycles] == [101.0, 131.0]

    def test_mixed_declared_and_plain_uses_the_plain_threshold(self) -> None:
        ring = CycleRing(window_seconds=1800)
        ring.feed(
            [
                LoopEvent(kind=EventKind.STOP, at=1.0, text="a", declared=True),
                LoopEvent(kind=EventKind.UNMET, at=2.0),
                LoopEvent(kind=EventKind.STOP, at=3.0, text="b", declared=False),
                LoopEvent(kind=EventKind.UNMET, at=4.0),
            ]
        )
        assessment = assess(ring, GoalLoopConfig())
        assert (assessment.threshold, assessment.verdict) == (3, Verdict.NEAR_MISS)

    def test_empty_ring_is_quiet(self) -> None:
        assert assess(CycleRing(window_seconds=60), GoalLoopConfig()).verdict is Verdict.QUIET

    def test_restart_count_empties_cycles_and_pending_but_keeps_the_fingerprint(self) -> None:
        ring = _ring("similar_stops.jsonl")
        ring.note_fingerprint("fp-a", new_cycles=0)
        ring.feed([LoopEvent(kind=EventKind.STOP, at=3e9, text="STOPPING BECAUSE: x")])
        ring.restart_count()
        assert ring.cycles == ()
        assert ring.fingerprint == "fp-a"
        result = ring.feed([LoopEvent(kind=EventKind.UNMET, at=3e9 + 1)])
        assert result.new_cycles == 0
        assert ring.note_fingerprint("fp-b", new_cycles=0) is None
        assert ring.fingerprint == "fp-b"


class TestFingerprintOnRing:
    def test_first_fingerprint_is_adopted_without_reset(self) -> None:
        ring = _ring("similar_stops.jsonl")
        assert ring.note_fingerprint("aaa", new_cycles=3) is None
        assert ring.fingerprint == "aaa"
        assert len(ring.cycles) == 3

    def test_same_fingerprint_keeps_the_ring(self) -> None:
        ring = _ring("similar_stops.jsonl")
        ring.note_fingerprint("aaa", new_cycles=3)
        assert ring.note_fingerprint("aaa", new_cycles=1) is None
        assert len(ring.cycles) == 3

    def test_changed_fingerprint_drops_only_the_older_cycles(self) -> None:
        ring = _ring("similar_stops.jsonl")
        ring.note_fingerprint("aaa", new_cycles=2)
        reset = ring.note_fingerprint("bbb", new_cycles=1)
        assert reset is not None
        assert (reset.cause, reset.dropped) == (ResetCause.REPO_CHANGE, 2)
        assert len(ring.cycles) == 1
        assert ring.fingerprint == "bbb"

    def test_a_reset_forgets_the_fingerprint(self) -> None:
        ring = _ring("similar_stops.jsonl")
        ring.note_fingerprint("aaa", new_cycles=3)
        ring.feed([LoopEvent(kind=EventKind.HUMAN, at=2e9)])
        assert ring.fingerprint is None


class TestEvidence:
    def test_evidence_names_counts_window_similarity_fingerprint_and_thresholds(self) -> None:
        ring = _ring("similar_stops.jsonl")
        ring.note_fingerprint("abc123", new_cycles=3)
        text = assess(ring, GoalLoopConfig()).evidence(GoalLoopConfig(), ring.fingerprint)
        for part in (
            "cycles=3",
            "threshold=3",
            "declared=0/3",
            "window=30m",
            "similarity=",
            "fingerprint=abc123",
            "mode=observe",
        ):
            assert part in text


# --- 6.2 the repository fingerprint ---------------------------------------------


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "code.py").write_text("x = 1\n", encoding="utf-8")
    journal = tmp_path / "CLAUDE" / "Plan" / "00999-x" / "JOURNAL"
    journal.mkdir(parents=True)
    (journal / "entry.md").write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


class TestRepoFingerprint:
    def test_stable_for_an_unchanged_tree(self, repo: Path) -> None:
        assert repo_fingerprint(repo) == repo_fingerprint(repo)

    def test_a_tracked_edit_changes_it(self, repo: Path) -> None:
        before = repo_fingerprint(repo)
        (repo / "code.py").write_text("x = 2\n", encoding="utf-8")
        assert repo_fingerprint(repo) != before

    def test_a_commit_changes_it(self, repo: Path) -> None:
        before = repo_fingerprint(repo)
        _git(repo, "commit", "-q", "--allow-empty", "-m", "next")
        assert repo_fingerprint(repo) != before

    def test_journal_edits_and_untracked_files_do_not(self, repo: Path) -> None:
        before = repo_fingerprint(repo)
        (repo / "CLAUDE" / "Plan" / "00999-x" / "JOURNAL" / "entry.md").write_text(
            "two\n", encoding="utf-8"
        )
        scratch = repo / "untracked" / "scratch"
        scratch.mkdir(parents=True)
        (scratch / "note.txt").write_text("n\n", encoding="utf-8")
        (repo / "new_untracked.py").write_text("y = 1\n", encoding="utf-8")
        assert repo_fingerprint(repo) == before

    def test_not_a_repository_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FingerprintError):
            repo_fingerprint(tmp_path)

    def test_a_failed_git_run_raises(self, repo: Path) -> None:
        def failing(cwd: Path, *args: str, timeout: float) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(["git", *args], 124, "", "timed out")

        with pytest.raises(FingerprintError, match="timed out"):
            repo_fingerprint(repo, run=failing)


def test_inode_is_os_stat_inode(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text("a\n", encoding="utf-8")
    _, checkpoint = read_new_lines(path, None, tail_bytes=10)
    assert checkpoint.inode == path.stat().st_ino
    assert checkpoint.path == str(path)
