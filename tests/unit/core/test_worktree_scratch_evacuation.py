"""The all-or-nothing gate for evacuating a worktree's scratch (Plan 00627 Task 6.2 Unit 2).

Evacuation handles root-level entries only (the coordinator's option 3): a
session directory anywhere refuses the whole worktree. Every other entry must
be due and actionable, or not due and held by its TTL alone; anything else is
a blocker named by entry, and the gate decides before anything is packed.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import worktree_scratch_evacuation as gate_mod
from claude_code_hooks_daemon.core.scratch_archive_pack import PackRefused
from claude_code_hooks_daemon.core.scratch_sweep import EntryRow, SweepReport
from claude_code_hooks_daemon.core.scratch_verdict import RepositoryMarker, Verdict
from claude_code_hooks_daemon.core.scratch_walk import NodeKind
from claude_code_hooks_daemon.core.worktree_scratch_evacuation import (
    SESSION_BLOCKER,
    EvacuationGate,
    evacuation_gate,
)

TTL = 24.0
MAX = 1000


def row(
    name: str,
    verdict: Verdict = Verdict.DISPOSABLE,
    *,
    due: bool = True,
    ttl_hold: Verdict | None = None,
    walk_complete: bool = True,
) -> EntryRow:
    return EntryRow(
        name=name,
        kind=NodeKind.DIRECTORY,
        verdict=verdict,
        reasons=(),
        proofs=(),
        repository=RepositoryMarker.NONE,
        git_markers=(),
        walk_complete=walk_complete,
        directories=1,
        files=1,
        bytes=1,
        age_hours=1.0,
        due=due,
        uncovered=(),
        uncovered_count=0,
        ttl_hold=ttl_hold,
    )


def not_due(name: str, held: Verdict = Verdict.DISPOSABLE) -> EntryRow:
    return row(name, Verdict.LIVE, due=False, ttl_hold=held)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "scratch"
    path.mkdir()
    return path


def make(root: Path, *names: str) -> None:
    for name in names:
        (root / name).mkdir()
        (root / name / "f.txt").write_text(name)


def report(root: Path, *rows: EntryRow, complete: bool = True) -> SweepReport:
    reasons = () if complete else ("budget spent",)
    return SweepReport(str(root), rows, complete, reasons, ())


def gate(rep: SweepReport) -> EvacuationGate:
    return evacuation_gate(rep, ttl_hours=TTL, max_inodes=MAX)


class TestEvacuable:
    def test_due_and_not_due_actionable_rows_pass_and_bind_consent(self, root: Path) -> None:
        make(root, "a", "b", "c")
        result = gate(
            report(root, row("a"), row("b", Verdict.UNCERTAIN), not_due("c", Verdict.UNCERTAIN))
        )
        assert result.blockers == ()
        assert result.consent is not None
        assert result.consent.idle_hours == 0
        assert result.consent.ttl_hours == TTL
        assert result.consent.consented == frozenset({str(root / "c")})
        assert result.entries == 3
        assert result.not_due == 1
        assert dict(result.by_verdict) == {"DISPOSABLE": 1, "UNCERTAIN": 2}

    def test_a_plain_file_entry_passes(self, root: Path) -> None:
        (root / "notes.md").write_text("notes")
        file_row = dataclasses.replace(row("notes.md"), kind=NodeKind.FILE)
        assert gate(report(root, file_row)).blockers == ()

    def test_an_empty_root_passes_with_nothing_to_pack(self, root: Path) -> None:
        result = gate(report(root))
        assert result.blockers == ()
        assert result.entries == 0


class TestBlockers:
    def test_an_incomplete_report_blocks(self, root: Path) -> None:
        make(root, "a")
        result = gate(report(root, row("a"), complete=False))
        assert result.blockers
        assert "budget spent" in result.blockers[0]
        assert result.consent is None

    def test_a_session_sub_report_blocks(self, root: Path) -> None:
        name = "s-20261121T000000Z-abcdefgh"
        sub = SweepReport(str(root / name), (), True, (), ())
        rep = dataclasses.replace(report(root), sessions=(sub,))
        assert gate(rep).blockers == (SESSION_BLOCKER.format(name=name),)

    def test_a_session_named_row_blocks(self, root: Path) -> None:
        name = "s-20261121T000000Z-abcdefgh"
        make(root, name)
        result = gate(report(root, row(name, Verdict.STUCK)))
        assert result.blockers == (SESSION_BLOCKER.format(name=name),)

    @pytest.mark.parametrize(
        "verdict",
        [Verdict.PROTECTED, Verdict.KEPT, Verdict.REFERENCED, Verdict.STUCK, Verdict.LIVE],
    )
    def test_a_due_row_with_a_holding_verdict_blocks(self, root: Path, verdict: Verdict) -> None:
        make(root, "a", "b")
        result = gate(report(root, row("a"), row("b", verdict)))
        assert result.blockers == (f"b: {verdict.value}",)
        assert result.consent is None

    def test_a_live_row_with_no_ttl_hold_blocks_even_not_due(self, root: Path) -> None:
        """Minimum age, a working directory, a background record: LIVE with no ttl_hold."""
        make(root, "a")
        result = gate(report(root, row("a", Verdict.LIVE, due=False)))
        assert result.blockers == ("a: LIVE",)

    def test_a_not_due_row_held_as_kept_blocks(self, root: Path) -> None:
        make(root, "a")
        result = gate(report(root, not_due("a", Verdict.KEPT)))
        assert result.blockers == ("a: KEPT (not yet due)",)

    def test_an_incomplete_walk_blocks(self, root: Path) -> None:
        make(root, "a")
        result = gate(report(root, row("a", walk_complete=False)))
        assert result.blockers == ("a: walk incomplete",)

    def test_a_not_due_entry_with_no_birth_stamp_blocks(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make(root, "a")
        monkeypatch.setattr(gate_mod, "birth_stamp", lambda fd, name: None)
        monkeypatch.setattr(
            "claude_code_hooks_daemon.core.scratch_archive_apply.birth_stamp",
            lambda fd, name: None,
        )
        result = gate(report(root, not_due("a")))
        assert result.blockers == ("a: no birth stamp",)
        assert result.consent is None

    def test_a_due_entry_with_no_birth_stamp_blocks(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make(root, "a")
        monkeypatch.setattr(gate_mod, "birth_stamp", lambda fd, name: None)
        assert gate(report(root, row("a"))).blockers == ("a: no birth stamp",)

    def test_a_due_entry_that_is_gone_blocks(self, root: Path) -> None:
        """statx fails: unknown, so a blocker."""
        assert gate(report(root, row("gone"))).blockers == ("gone: no birth stamp",)

    def test_a_foreign_owned_inode_blocks(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make(root, "a")

        def refuse(listing: object, name: str) -> None:
            raise PackRefused("an inode another user owns")

        monkeypatch.setattr(gate_mod, "refuse_foreign_owner", refuse)
        assert gate(report(root, row("a"))).blockers == ("a: an inode another user owns",)

    def test_an_entry_that_cannot_be_walked_blocks(self, root: Path) -> None:
        make(root, "a")
        result = evacuation_gate(report(root, row("a")), ttl_hours=TTL, max_inodes=1)
        assert result.blockers == ("a: cannot be walked",)

    def test_a_root_that_cannot_be_opened_blocks(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope"
        result = gate(report(missing, row("a")))
        assert result.blockers == (f"{missing}: could not be opened",)

    def test_a_name_on_disk_no_row_lists_blocks(self, root: Path) -> None:
        """A skipped name, a leftover claim or a marker: unjudged, so never packed around."""
        make(root, "a", ".sweeping-b")
        (root / ".scratch-keep").write_text("")
        result = gate(report(root, row("a")))
        assert result.blockers == (
            ".scratch-keep: not listed by the classification",
            ".sweeping-b: not listed by the classification",
        )

    def test_a_name_on_disk_blocks_an_otherwise_empty_report(self, root: Path) -> None:
        make(root, "a")
        assert gate(report(root)).blockers == ("a: not listed by the classification",)

    def test_a_session_directory_listed_twice_is_named_once(self, root: Path) -> None:
        name = "s-20261121T000000Z-abcdefgh"
        make(root, name)
        sub = SweepReport(str(root / name), (), True, (), ())
        rep = dataclasses.replace(report(root, row(name, Verdict.STUCK)), sessions=(sub,))
        assert gate(rep).blockers == (SESSION_BLOCKER.format(name=name),)

    def test_the_session_blocker_names_the_human_step(self) -> None:
        text = SESSION_BLOCKER.format(name="s-x")
        assert "by hand" in text
        assert "never" in text

    def test_one_blocker_withholds_consent_for_all(self, root: Path) -> None:
        make(root, "a", "b")
        result = gate(report(root, not_due("a"), row("b", Verdict.PROTECTED)))
        assert result.consent is None
