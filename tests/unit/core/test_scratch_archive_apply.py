"""The apply pipeline: fresh facts, claim, re-check, pack, verify, record, remove (Plan 00627 Task 3.8).

DESIGN.md section 5.2. The classification is taken fresh inside each run (a
report is never an input), every entry is fingerprinted before it is
classified, and only a due DISPOSABLE or UNCERTAIN entry of a complete report is
claimed. Removal goes through ``scratch_archive_remove`` only.
"""

from __future__ import annotations

import ast
import dataclasses
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import claude_code_hooks_daemon
from claude_code_hooks_daemon.core import scratch_archive_apply as apply_mod
from claude_code_hooks_daemon.core.scratch_archive import (
    AdoptEvent,
    ArchiveStore,
    ClaimEvent,
    StoreRefused,
    new_archive_id,
)
from claude_code_hooks_daemon.core.scratch_archive_apply import (
    ApplyFacts,
    ApplySettings,
    apply_sweep,
)
from claude_code_hooks_daemon.core.scratch_archive_claim import CLAIM_PREFIX, open_dir
from claude_code_hooks_daemon.core.scratch_archive_pack import TarTool, find_gnu_tar
from claude_code_hooks_daemon.core.scratch_archive_restore import restore
from claude_code_hooks_daemon.core.scratch_sweep import EntryRow, SweepReport
from claude_code_hooks_daemon.core.scratch_verdict import Proof, RepositoryMarker, Verdict
from claude_code_hooks_daemon.core.scratch_walk import NodeKind

MAX = 1000
RETENTION = {"DISPOSABLE": 12.0, "UNCERTAIN": 168.0}
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
Snapshot = dict[str, tuple[str, bytes]]


def row(name: str, verdict: Verdict = Verdict.DISPOSABLE, *, due: bool = True) -> EntryRow:
    return EntryRow(
        name=name,
        kind=NodeKind.DIRECTORY,
        verdict=verdict,
        reasons=(),
        proofs=(Proof.P1,) if verdict is Verdict.DISPOSABLE else (),
        repository=RepositoryMarker.NONE,
        git_markers=(),
        walk_complete=True,
        directories=1,
        files=1,
        bytes=1,
        age_hours=100.0,
        due=due,
        uncovered=(),
        uncovered_count=0,
    )


@dataclass
class FakeFacts:
    """Fresh-fact sources a test controls; each call is counted."""

    rows: list[EntryRow]
    complete: bool = True
    live: set[str] = field(default_factory=set)
    referenced: set[str] = field(default_factory=set)
    classified: int = 0
    on_classify: Callable[[], object] | None = None

    def classify(self) -> SweepReport:
        self.classified += 1
        if self.on_classify is not None:
            self.on_classify()
        reasons = () if self.complete else ("budget spent",)
        return SweepReport("root", tuple(self.rows), self.complete, reasons, ())

    def facts(self) -> ApplyFacts:
        return ApplyFacts(
            classify=self.classify,
            entry_live=lambda name: name in self.live,
            referenced=lambda name: name in self.referenced,
        )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    path = tmp_path / "project"
    (path / "untracked" / "scratch").mkdir(parents=True)
    return path


@pytest.fixture
def root(project: Path) -> Path:
    return project / "untracked" / "scratch"


@pytest.fixture
def store(project: Path) -> Iterator[ArchiveStore]:
    with ArchiveStore.open(project / "untracked" / "scratch-archive") as opened:
        with opened.lock():
            yield opened


@pytest.fixture
def tar() -> TarTool:
    return find_gnu_tar()


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    path = tmp_path / "outside"
    path.mkdir()
    (path / "keep.txt").write_text("outside content")
    return path


def settings(
    root: Path, tar: TarTool, clock: Callable[[], datetime] = lambda: NOW
) -> ApplySettings:
    return ApplySettings(
        root=root,
        original_prefix="untracked/scratch",
        checkout="main",
        tar=tar,
        max_inodes=MAX,
        retention_hours=RETENTION,
        clock=clock,
    )


def entry(root: Path, name: str) -> Path:
    path = root / name
    (path / "sub").mkdir(parents=True)
    (path / "a.txt").write_text("alpha " + name)
    (path / "sub" / "b.bin").write_bytes(bytes(range(64)))
    (path / "link").symlink_to("a.txt")
    return path


def snapshot(top: Path) -> Snapshot:
    out: Snapshot = {}
    for dirpath, dirnames, filenames in os.walk(top):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            rel = str(path.relative_to(top))
            if path.is_symlink():
                out[rel] = ("link", str(path.readlink()).encode())
            elif path.is_dir():
                out[rel] = ("dir", b"")
            else:
                out[rel] = ("file", path.read_bytes())
    return out


def outcome_of(result: apply_mod.ApplyResult, name: str) -> apply_mod.EntryOutcome:
    matches = [o for o in result.entries if o.name == name]
    assert len(matches) == 1, result.entries
    return matches[0]


class TestArchivesWhatIsActionable:
    @pytest.mark.parametrize("verdict", [Verdict.DISPOSABLE, Verdict.UNCERTAIN])
    def test_a_due_entry_is_archived_recorded_and_removed(
        self, root: Path, store: ArchiveStore, tar: TarTool, verdict: Verdict
    ) -> None:
        entry(root, "e1")
        before = snapshot(root / "e1")
        fake = FakeFacts([row("e1", verdict)])
        result = apply_sweep(store, fake.facts(), settings(root, tar))
        outcome = outcome_of(result, "e1")
        assert outcome.outcome == "archived"
        assert not (root / "e1").exists()
        assert not (root / (CLAIM_PREFIX + "e1")).exists()
        (record,) = store.read_index().records
        assert record.archive_id == outcome.archive_id
        assert record.original_path == "untracked/scratch/e1"
        assert record.verdict == verdict.value
        assert record.checkout == "main"
        assert record.restore_command == f"hooks-daemon scratch-sweep restore {record.archive_id}"
        expected_expiry = NOW + timedelta(hours=RETENTION[verdict.value])
        assert datetime.fromisoformat(record.expires_at or "") == expected_expiry
        fd = open_dir(root)
        try:
            restore(
                store,
                record.archive_id,
                fd,
                root_path="untracked/scratch",
                tar=tar,
                max_inodes=MAX,
            )
        finally:
            os.close(fd)
        assert snapshot(root / "e1") == before

    @pytest.mark.parametrize(
        "verdict",
        [Verdict.LIVE, Verdict.STUCK, Verdict.PROTECTED, Verdict.REFERENCED],
    )
    def test_any_other_verdict_is_never_touched(
        self, root: Path, store: ArchiveStore, tar: TarTool, verdict: Verdict
    ) -> None:
        entry(root, "e1")
        before = snapshot(root)
        result = apply_sweep(store, FakeFacts([row("e1", verdict)]).facts(), settings(root, tar))
        assert outcome_of(result, "e1").outcome == "not-actionable"
        assert snapshot(root) == before
        assert store.read_index().records == ()

    def test_a_disposable_entry_that_is_not_due_is_not_touched(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "e1")
        before = snapshot(root)
        result = apply_sweep(store, FakeFacts([row("e1", due=False)]).facts(), settings(root, tar))
        assert outcome_of(result, "e1").outcome == "not-actionable"
        assert snapshot(root) == before

    def test_an_incomplete_report_claims_nothing(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "e1")
        before = snapshot(root)
        fake = FakeFacts([row("e1")], complete=False)
        result = apply_sweep(store, fake.facts(), settings(root, tar))
        assert not result.complete
        assert "budget spent" in result.incomplete_reasons
        assert outcome_of(result, "e1").outcome == "not-actionable"
        assert snapshot(root) == before
        assert store.read_index().records == ()


class TestFreshFacts:
    def test_classification_is_taken_inside_every_run(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        fake = FakeFacts([])
        apply_sweep(store, fake.facts(), settings(root, tar))
        apply_sweep(store, fake.facts(), settings(root, tar))
        assert fake.classified == 2

    def test_an_entry_modified_after_its_fingerprint_is_not_removed(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "e1")
        # The fingerprint is taken BEFORE classification; a write during it is caught.
        fake = FakeFacts(
            [row("e1")], on_classify=lambda: (root / "e1" / "new.txt").write_text("new")
        )
        result = apply_sweep(store, fake.facts(), settings(root, tar))
        assert outcome_of(result, "e1").outcome == "renamed-back"
        assert (root / "e1" / "new.txt").read_text() == "new"
        assert store.read_index().records == ()

    def test_an_entry_that_appears_during_classification_is_not_claimed(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        fake = FakeFacts([row("late")], on_classify=lambda: entry(root, "late"))
        result = apply_sweep(store, fake.facts(), settings(root, tar))
        assert outcome_of(result, "late").outcome == "not-fingerprinted"
        assert (root / "late" / "a.txt").exists()

    def test_a_process_cwd_inside_at_claim_time_renames_it_back(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "e1")
        fake = FakeFacts([row("e1")], live={"e1"})
        result = apply_sweep(store, fake.facts(), settings(root, tar))
        outcome = outcome_of(result, "e1")
        assert outcome.outcome == "renamed-back"
        assert "live" in outcome.reason
        assert (root / "e1" / "a.txt").exists()
        assert store.read_index().records == ()

    def test_a_reference_that_appears_after_classification_renames_it_back(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "e1")
        fake = FakeFacts([row("e1")], referenced={"e1"})
        result = apply_sweep(store, fake.facts(), settings(root, tar))
        assert outcome_of(result, "e1").outcome == "renamed-back"
        assert (root / "e1" / "a.txt").exists()

    def test_a_failing_fact_source_refuses_the_entry(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "e1")

        def broken(name: str) -> bool:
            raise OSError("proc unreadable")

        facts = ApplyFacts(
            classify=FakeFacts([row("e1")]).classify, entry_live=broken, referenced=lambda n: False
        )
        result = apply_sweep(store, facts, settings(root, tar))
        assert outcome_of(result, "e1").outcome == "renamed-back"
        assert (root / "e1" / "a.txt").exists()


class TestOnlyTheRemoverDeletes:
    def test_the_apply_module_calls_no_deleting_primitive(self) -> None:
        source = (
            Path(claude_code_hooks_daemon.__file__).parent / "core" / "scratch_archive_apply.py"
        )
        tree = ast.parse(source.read_text())
        banned = {"unlink", "rmdir", "rmtree", "remove", "removedirs", "truncate"}
        called = {
            node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        }
        assert not (called & banned)

    def test_store_lock_is_required(self, root: Path, project: Path, tar: TarTool) -> None:
        with ArchiveStore.open(project / "untracked" / "scratch-archive") as unlocked:
            with pytest.raises(Exception, match="lock"):
                apply_sweep(unlocked, FakeFacts([]).facts(), settings(root, tar))

    def test_nothing_outside_the_root_changes(
        self, root: Path, store: ArchiveStore, tar: TarTool, outside: Path
    ) -> None:
        entry(root, "e1")
        (root / "e1" / "out").symlink_to(outside)
        (root / "e2").symlink_to(outside / "keep.txt")
        before = snapshot(outside)
        mtime = (outside / "keep.txt").stat().st_mtime_ns
        result = apply_sweep(store, FakeFacts([row("e1"), row("e2")]).facts(), settings(root, tar))
        assert outcome_of(result, "e1").outcome == "archived"
        assert outcome_of(result, "e2").outcome == "archived"
        assert not (root / "e2").is_symlink()
        assert snapshot(outside) == before
        assert (outside / "keep.txt").stat().st_mtime_ns == mtime


def later(hours: float) -> Callable[[], datetime]:
    return lambda: NOW + timedelta(hours=hours)


def archive_e1(root: Path, store: ArchiveStore, tar: TarTool) -> str:
    entry(root, "e1")
    result = apply_sweep(store, FakeFacts([row("e1")]).facts(), settings(root, tar))
    outcome = outcome_of(result, "e1")
    assert outcome.outcome == "archived"
    return outcome.archive_id


def _mkdir_on_an_unrecorded_inode(root: Path, store: ArchiveStore, name: str) -> Path:
    """Make ``root/name`` on an inode no claim event records.

    ext4 hands a just-freed inode number straight back, so a directory made where a
    removed claim stood can carry the recorded number, and is then the sweep's own
    claim, not a foreign one. A directory that lands on a recorded number is kept
    aside (holding that number) and the name is made again.
    """
    recorded = {
        int(event.root_ino) for event in store.read_events().events if isinstance(event, ClaimEvent)
    }
    target = root / name
    for attempt in range(len(recorded) + 1):
        target.mkdir()
        if target.stat().st_ino not in recorded:
            return target
        target.rename(root.parent / f"inode-holder-{attempt}")
    raise AssertionError("every new directory landed on a recorded inode")


class _Killed(Exception):
    """A simulated kill between two apply steps."""


class TestResumeReclaimExpireOrder:
    def test_a_leftover_claim_is_resumed_then_judged_in_the_same_run(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "e1")

        def crash(step: str, name: str) -> None:
            if step == apply_mod.STEP_CLAIM:
                raise _Killed(step)

        with pytest.raises(_Killed):
            apply_sweep(
                store, FakeFacts([row("e1")]).facts(), settings(root, tar), after_step=crash
            )
        assert (root / (CLAIM_PREFIX + "e1")).exists()
        result = apply_sweep(store, FakeFacts([row("e1")]).facts(), settings(root, tar))
        assert [r.outcome for r in result.resumed] == ["renamed-back"]
        assert outcome_of(result, "e1").outcome == "archived"
        assert not (root / "e1").exists()

    def test_a_claim_name_no_sweep_recorded_is_foreign_and_untouched(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        """D-PATH F1: an agent's own ``.sweeping-notes`` is never resumed or re-claimed."""
        entry(root, CLAIM_PREFIX + "notes")
        before = snapshot(root / (CLAIM_PREFIX + "notes"))
        rows = [row("notes"), row(CLAIM_PREFIX + "notes")]
        result = apply_sweep(store, FakeFacts(rows).facts(), settings(root, tar))
        assert [(r.name, r.outcome) for r in result.resumed] == [("notes", "foreign")]
        assert snapshot(root / (CLAIM_PREFIX + "notes")) == before
        assert sorted(p.name for p in root.iterdir()) == [CLAIM_PREFIX + "notes"]
        assert store.read_index().records == ()

    def test_a_claim_that_cannot_be_recorded_is_never_made(
        self, root: Path, store: ArchiveStore, tar: TarTool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The claim event is written BEFORE the rename: no record, no claim."""
        entry(root, "e1")

        def refuse(*args: object, **kwargs: object) -> None:
            raise StoreRefused("events file unwritable")

        monkeypatch.setattr(store, "append_event", refuse)
        result = apply_sweep(store, FakeFacts([row("e1")]).facts(), settings(root, tar))
        assert outcome_of(result, "e1").outcome == "refused"
        assert (root / "e1" / "a.txt").exists()
        assert not (root / (CLAIM_PREFIX + "e1")).exists()

    def test_a_resume_that_raises_is_reported_stuck_and_the_run_goes_on(
        self, root: Path, store: ArchiveStore, tar: TarTool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry(root, CLAIM_PREFIX + "x")
        entry(root, "e1")

        def refuse(*args: object, **kwargs: object) -> object:
            raise apply_mod.RemoveRefused("index unreadable")

        monkeypatch.setattr(apply_mod, "resume_claimed", refuse)
        result = apply_sweep(store, FakeFacts([row("e1")]).facts(), settings(root, tar))
        assert [(r.name, r.outcome) for r in result.resumed] == [("x", "stuck")]
        assert (root / (CLAIM_PREFIX + "x") / "a.txt").exists()
        assert outcome_of(result, "e1").outcome == "archived"

    def test_an_archive_past_retention_expires_last(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        archive_id = archive_e1(root, store, tar)
        result = apply_sweep(store, FakeFacts([]).facts(), settings(root, tar, later(13)))
        assert [(o.archive_id, o.outcome) for o in result.expired] == [(archive_id, "expired")]

    def test_an_archive_whose_claim_is_still_present_never_expires(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        archive_id = archive_e1(root, store, tar)
        # A claim name present (no sweep recorded this one, so it is foreign) still holds.
        claimed = _mkdir_on_an_unrecorded_inode(root, store, CLAIM_PREFIX + "e1")
        (claimed / "a.txt").write_text("alpha e1")
        (root / "e1").mkdir()
        result = apply_sweep(store, FakeFacts([]).facts(), settings(root, tar, later(13)))
        assert [r.outcome for r in result.resumed] == ["foreign"]
        assert [(o.archive_id, o.outcome) for o in result.expired] == [(archive_id, "held")]
        assert archive_id in {r.archive_id for r in store.read_index().records}

    def test_an_archive_a_tracked_file_still_names_never_expires(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        archive_id = archive_e1(root, store, tar)
        fake = FakeFacts([], referenced={"e1"})
        result = apply_sweep(store, fake.facts(), settings(root, tar, later(13)))
        assert [(o.archive_id, o.outcome) for o in result.expired] == [(archive_id, "held")]

    def test_an_archive_from_another_root_is_held(
        self, root: Path, project: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        archive_id = archive_e1(root, store, tar)
        other = dataclasses.replace(settings(root, tar, later(13)), original_prefix="untracked/x")
        result = apply_sweep(store, FakeFacts([]).facts(), other)
        assert [(o.archive_id, o.outcome) for o in result.expired] == [(archive_id, "held")]

    def test_an_archive_from_a_sub_root_is_held_by_the_parent_root(
        self, root: Path, project: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        # Its record's directory is untracked/scratch/sub, never the swept prefix, so
        # the parent root cannot see whether anything still holds it: kept, not expired.
        entry(root, "e1")
        sub = dataclasses.replace(settings(root, tar), original_prefix="untracked/scratch/sub")
        packed = apply_sweep(store, FakeFacts([row("e1")]).facts(), sub)
        archive_id = outcome_of(packed, "e1").archive_id
        (record,) = store.read_index().records
        assert record.original_path == "untracked/scratch/sub/e1"
        result = apply_sweep(store, FakeFacts([]).facts(), settings(root, tar, later(13)))
        assert [(o.archive_id, o.outcome) for o in result.expired] == [(archive_id, "held")]

    def test_unfinished_adoptions_are_reported_not_finished(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        event = AdoptEvent(
            archive_id=new_archive_id(),
            original_path="untracked/scratch/t.tar",
            tarball="t.tar",
            at=NOW.isoformat(),
        )
        store.append_event(event)
        result = apply_sweep(store, FakeFacts([]).facts(), settings(root, tar))
        assert result.unfinished_adoptions == (event,)
        assert any("unfinished adoption" in note for note in result.notes)

    def test_a_failed_record_append_leaves_the_claim_for_the_next_run(
        self, root: Path, store: ArchiveStore, tar: TarTool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry(root, "e1")
        before = snapshot(root / "e1")

        def refuse(record: object) -> None:
            raise StoreRefused("disk full")

        monkeypatch.setattr(store, "append", refuse)
        result = apply_sweep(store, FakeFacts([row("e1")]).facts(), settings(root, tar))
        assert outcome_of(result, "e1").outcome == "left-claimed"
        monkeypatch.undo()
        again = apply_sweep(store, FakeFacts([]).facts(), settings(root, tar))
        assert [r.outcome for r in again.resumed] == ["renamed-back"]
        assert snapshot(root / "e1") == before
        assert again.audit.unrecorded_archives
