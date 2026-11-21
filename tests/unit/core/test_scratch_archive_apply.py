"""The apply pipeline: fresh facts, claim, re-check, pack, verify, record, remove (Plan 00627 Task 3.8).

DESIGN.md section 5.2. The classification is taken fresh inside each run (a
report is never an input), every entry is fingerprinted before it is
classified, and only a due DISPOSABLE or UNCERTAIN entry of a complete report is
claimed. Removal goes through ``scratch_archive_remove`` only.
"""

from __future__ import annotations

import ast
import dataclasses
import errno
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import claude_code_hooks_daemon
from claude_code_hooks_daemon.config.models import ScratchCapsConfig
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
    Pressure,
    apply_sessions,
    apply_sweep,
    consent_to,
    pressure_for,
    pressured_count,
    session_facts,
)
from claude_code_hooks_daemon.core.scratch_archive_claim import CLAIM_PREFIX, open_dir
from claude_code_hooks_daemon.core.scratch_archive_pack import TarTool, find_gnu_tar
from claude_code_hooks_daemon.core.scratch_archive_remove import RemoveRefused
from claude_code_hooks_daemon.core.scratch_archive_restore import restore
from claude_code_hooks_daemon.core.scratch_caps import CapLevel
from claude_code_hooks_daemon.core.scratch_session import ensure_session_dir, new_entry
from claude_code_hooks_daemon.core.scratch_sweep import EntryRow, SweepReport
from claude_code_hooks_daemon.core.scratch_verdict import (
    KEEP_MARKER,
    Proof,
    RepositoryMarker,
    Verdict,
)
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

    def test_an_entry_of_another_owner_is_refused_and_left_in_place(
        self, root: Path, store: ArchiveStore, tar: TarTool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fix B: foreign ownership refuses the pack; the entry is renamed back, never removed."""
        entry(root, "e1")
        before = snapshot(root / "e1")
        real_geteuid = os.geteuid
        fake = FakeFacts([row("e1", Verdict.DISPOSABLE)])
        settings_ = settings(root, tar)
        monkeypatch.setattr(os, "geteuid", lambda: real_geteuid() + 4242)
        result = apply_sweep(store, fake.facts(), settings_)
        monkeypatch.setattr(os, "geteuid", real_geteuid)
        outcome = outcome_of(result, "e1")
        assert outcome.outcome == "refused"
        assert "owned by uid" in outcome.reason
        assert snapshot(root / "e1") == before
        assert not (root / (CLAIM_PREFIX + "e1")).exists()
        assert store.read_index().records == ()
        # Refused before the claim: no claim event, no rename, so a second run
        # neither piles up events nor touches the entry's ctime.
        assert store.read_events().events == ()

    def test_a_foreign_entry_that_is_not_actionable_keeps_its_verdict_outcome(
        self, root: Path, store: ArchiveStore, tar: TarTool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry(root, "e1")
        real_geteuid = os.geteuid
        fake = FakeFacts([row("e1", Verdict.LIVE)])
        settings_ = settings(root, tar)
        monkeypatch.setattr(os, "geteuid", lambda: real_geteuid() + 4242)
        result = apply_sweep(store, fake.facts(), settings_)
        monkeypatch.setattr(os, "geteuid", real_geteuid)
        assert outcome_of(result, "e1").outcome == "not-actionable"

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
            raise RemoveRefused("index unreadable")

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


SESSION = "s-20261101T000000Z-abcdefgh"


@dataclass
class SessionWorld:
    """A parent report holding one session sub-report, with facts a test controls."""

    root: Path
    children: list[EntryRow]
    #: How many parent classifications still list the session.
    present_for: int = 1_000
    classified: int = 0
    identity: tuple[int, int] | None = None
    container_live: bool = False
    container_referenced: bool = False
    child_live: set[str] = field(default_factory=set)

    session_name: str = SESSION
    #: Run once, after the first classification has been read.
    after_first: Callable[[], None] | None = None

    def classify(self) -> SweepReport:
        self.classified += 1
        info = os.lstat(self.root / self.session_name)
        identity = self.identity or (info.st_dev, info.st_ino)
        if self.classified == 1 and self.after_first is not None:
            self.after_first()
        sub = SweepReport(
            str(self.root / self.session_name),
            tuple(self.children),
            True,
            (),
            (),
            identity=identity,
        )
        parent_rows = (row(self.session_name, Verdict.STUCK),)
        sessions = (sub,) if self.classified <= self.present_for else ()
        return SweepReport(str(self.root), parent_rows, True, (), (), sessions=sessions)

    def parent(self) -> ApplyFacts:
        return ApplyFacts(
            classify=self.classify,
            entry_live=lambda name: name == self.session_name and self.container_live,
            referenced=lambda name: False,
        )

    def for_session(self, name: str) -> ApplyFacts:
        return session_facts(
            self.parent(),
            name,
            session_dir=self.root / name,
            child_live=lambda child: child in self.child_live,
            child_referenced=lambda child: False,
            container_referenced=lambda: self.container_referenced,
        )


def run_sessions(world: SessionWorld, store: ArchiveStore, tar: TarTool) -> apply_mod.ApplyResult:
    results = apply_sessions(store, world.parent(), settings(world.root, tar), world.for_session)
    assert [name for name, _ in results] == [SESSION]
    return results[0][1]


class TestSessionChildrenAreArchivedOneByOne:
    """Task 4.3 step 3: --apply packs each due child of a session directory, never the directory."""

    def _world(
        self,
        root: Path,
        *,
        identity: tuple[int, int] | None = None,
        container_live: bool = False,
        container_referenced: bool = False,
    ) -> SessionWorld:
        entry(root / SESSION, "old")
        entry(root / SESSION, "kept")
        entry(root / SESSION, "guarded")
        children = [
            row("old"),
            row("kept", Verdict.KEPT),
            row("guarded", Verdict.PROTECTED),
        ]
        return SessionWorld(
            root,
            children,
            identity=identity,
            container_live=container_live,
            container_referenced=container_referenced,
        )

    def test_a_due_child_is_archived_alone_and_restores_into_its_session(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        world = self._world(root)
        before = snapshot(root / SESSION / "old")
        result = run_sessions(world, store, tar)
        assert outcome_of(result, "old").outcome == "archived"
        assert outcome_of(result, "kept").outcome == "not-actionable"
        assert outcome_of(result, "guarded").outcome == "not-actionable"
        assert (root / SESSION / "kept").is_dir()
        assert (root / SESSION / "guarded").is_dir()
        assert not (root / SESSION / "old").exists()
        (record,) = store.read_index().records
        assert record.original_path == f"untracked/scratch/{SESSION}/old"
        fd = open_dir(root)
        try:
            restore(
                store, record.archive_id, fd, root_path="untracked/scratch", tar=tar, max_inodes=MAX
            )
        finally:
            os.close(fd)
        assert snapshot(root / SESSION / "old") == before

    def test_the_session_directory_itself_is_never_packed(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        world = self._world(root)
        apply_sweep(store, world.parent(), settings(root, tar))
        assert (root / SESSION / "old").is_dir()
        assert store.read_index().records == ()

    def test_a_live_container_holds_every_child(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        result = run_sessions(self._world(root, container_live=True), store, tar)
        assert outcome_of(result, "old").outcome != "archived"
        assert (root / SESSION / "old").is_dir()

    def test_a_referenced_container_holds_every_child(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        result = run_sessions(self._world(root, container_referenced=True), store, tar)
        assert outcome_of(result, "old").outcome != "archived"
        assert (root / SESSION / "old").is_dir()

    def test_a_live_child_is_not_packed(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        world = self._world(root)
        world.child_live = {"old"}
        run_sessions(world, store, tar)
        assert (root / SESSION / "old").is_dir()

    def test_a_keep_marker_added_after_classification_holds_every_child(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        """The apply-time safety re-check reads the session's ``.scratch-keep`` again."""
        world = self._world(root)

        def keep() -> None:
            (root / SESSION / KEEP_MARKER).write_text("hold")

        world.after_first = keep
        result = run_sessions(world, store, tar)
        assert outcome_of(result, "old").outcome != "archived"
        assert (root / SESSION / "old").is_dir()

    def test_a_dangling_keep_link_still_holds(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        world = self._world(root)
        world.after_first = lambda: (root / SESSION / KEEP_MARKER).symlink_to(root / "nowhere")
        run_sessions(world, store, tar)
        assert (root / SESSION / "old").is_dir()

    def test_an_unreadable_keep_marker_holds(
        self, root: Path, store: ArchiveStore, tar: TarTool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An ``lstat`` of the marker that fails other than 'absent' is read as kept."""
        real_lstat = os.lstat

        def lstat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
            if str(path).endswith(KEEP_MARKER):
                raise PermissionError(errno.EACCES, "Permission denied")
            return real_lstat(path, *args, **kwargs)

        monkeypatch.setattr(os, "lstat", lstat)
        run_sessions(self._world(root), store, tar)
        assert (root / SESSION / "old").is_dir()

    def test_a_directory_not_the_one_listed_is_never_acted_in(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        world = self._world(root, identity=(0, 0))
        (root / SESSION / (CLAIM_PREFIX + "left")).mkdir()
        result = run_sessions(world, store, tar)
        assert not result.complete
        assert result.entries == () and result.resumed == ()
        assert (root / SESSION / "old").is_dir()
        assert (root / SESSION / (CLAIM_PREFIX + "left")).is_dir()

    def test_a_session_swapped_for_a_link_is_skipped_and_the_rest_still_run(
        self, root: Path, store: ArchiveStore, tar: TarTool, outside: Path
    ) -> None:
        world = self._world(root)

        def swap() -> None:
            (root / SESSION).rename(root / "moved")
            (root / SESSION).symlink_to(outside)

        world.after_first = swap
        result = run_sessions(world, store, tar)
        assert not result.complete
        assert any("could not be opened" in reason for reason in result.incomplete_reasons)
        assert (root / "moved" / "old").is_dir()
        assert (outside / "keep.txt").read_text() == "outside content"

    def test_a_session_gone_from_the_fresh_listing_acts_on_nothing(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        world = self._world(root)
        # Listed when the loop picks its sessions, gone for the session's own pass.
        world.present_for = 1
        result = run_sessions(world, store, tar)
        assert not result.complete
        assert result.entries == ()
        assert (root / SESSION / "old").is_dir()


class TestEmptySessionDirectoryRemoval:
    """Task 4.3 step 4: after its pass, an empty old session directory is removed."""

    def _session(self, root: Path) -> Path:
        born = NOW - timedelta(days=5)
        return ensure_session_dir(root, "abcdefgh-run", now=born, checkout="c", branch=None).path

    def _sessions(self, root: Path, store: ArchiveStore, tar: TarTool, session: Path) -> str:
        world = SessionWorld(root, [], session_name=session.name)
        hours = dataclasses.replace(settings(root, tar), empty_session_hours=24.0)
        ((_, result),) = apply_sessions(store, world.parent(), hours, world.for_session)
        return " ".join(result.notes)

    def test_an_empty_old_session_directory_is_removed(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        session = self._session(root)
        notes = self._sessions(root, store, tar, session)
        assert not session.exists(), notes

    def test_a_record_inside_it_keeps_it(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        session = self._session(root)
        born = datetime.fromtimestamp((NOW - timedelta(days=5)).timestamp(), UTC)
        new_entry(session, "old", now=born, purpose=None, plan=None, ttl_hours=None)
        (session / "old" / "a.txt").write_text("alpha")
        world = SessionWorld(root, [row("old")], session_name=session.name)
        apply_sessions(store, world.parent(), settings(root, tar), world.for_session)
        assert not (session / "old").exists()
        notes = self._sessions(root, store, tar, session)
        assert session.is_dir(), notes
        assert "held" in notes


TTL = 72.0
PRESSURE = Pressure(idle_hours=0.5, ttl_hours=TTL)


def not_due(
    name: str,
    verdict: Verdict = Verdict.DISPOSABLE,
    *,
    age_hours: float = 10.0,
    directories: int = 1,
) -> EntryRow:
    """A row real classification gives an entry not yet due: LIVE, held by its TTL alone.

    ``verdict`` is what the rest of the ladder says (its ``ttl_hold``).
    """
    return dataclasses.replace(
        row(name, Verdict.LIVE, due=False),
        reasons=("within its TTL",),
        age_hours=age_hours,
        directories=directories,
        ttl_hold=verdict,
        ttl_hold_proofs=(Proof.P1,) if verdict is Verdict.DISPOSABLE else (),
    )


def pressed(root: Path, tar: TarTool, pressure: Pressure | None = PRESSURE) -> ApplySettings:
    return dataclasses.replace(settings(root, tar), pressure=pressure)


class TestPressureMode:
    """Task 5.5: at block, ``--apply`` also packs idle entries that are not yet due."""

    def test_an_idle_entry_not_yet_due_is_packed_under_pressure(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "e1")
        fake = FakeFacts([not_due("e1", age_hours=10.0)])
        result = apply_sweep(store, fake.facts(), pressed(root, tar))
        assert outcome_of(result, "e1").outcome == "archived"
        assert not (root / "e1").exists()

    def test_without_pressure_it_is_left_alone(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "e1")
        fake = FakeFacts([not_due("e1")])
        result = apply_sweep(store, fake.facts(), pressed(root, tar, None))
        assert outcome_of(result, "e1").outcome == "not-actionable"
        assert (root / "e1").is_dir()

    @pytest.mark.parametrize("pressure", [None, PRESSURE])
    @pytest.mark.parametrize("held", [Verdict.DISPOSABLE, Verdict.KEPT, Verdict.REFERENCED])
    def test_a_skipped_ttl_held_entry_reports_its_held_verdict(
        self,
        root: Path,
        store: ArchiveStore,
        tar: TarTool,
        pressure: Pressure | None,
        held: Verdict,
    ) -> None:
        """The outcome names what holds it back underneath, not the TTL's bare LIVE."""
        entry(root, "e1")
        fake = FakeFacts([not_due("e1", held, age_hours=0.1)])
        result = apply_sweep(store, fake.facts(), pressed(root, tar, pressure))
        outcome = outcome_of(result, "e1")
        assert outcome.outcome == "not-actionable"
        assert outcome.reason == f"{held.value} (not yet due: within its TTL)"

    def test_a_liveness_live_entry_still_reports_live(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "e1")
        result = apply_sweep(
            store, FakeFacts([row("e1", Verdict.LIVE, due=False)]).facts(), pressed(root, tar)
        )
        assert outcome_of(result, "e1").reason == "LIVE"

    def test_its_archive_expires_no_sooner_than_ttl_plus_retention(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "e1")
        fake = FakeFacts([not_due("e1", age_hours=10.0)])
        apply_sweep(store, fake.facts(), pressed(root, tar))
        (record,) = store.read_index().records
        remaining = TTL - 10.0
        expected = NOW + timedelta(hours=remaining + RETENTION["DISPOSABLE"])
        assert datetime.fromisoformat(record.expires_at or "") == expected

    def test_a_due_entry_keeps_its_ordinary_expiry(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "e1")
        fake = FakeFacts([row("e1")])
        apply_sweep(store, fake.facts(), pressed(root, tar))
        (record,) = store.read_index().records
        expected = NOW + timedelta(hours=RETENTION["DISPOSABLE"])
        assert datetime.fromisoformat(record.expires_at or "") == expected

    @pytest.mark.parametrize(
        "verdict",
        [v for v in Verdict if v not in apply_mod.ACTIONABLE],
    )
    def test_no_other_verdict_is_ever_packed(
        self, root: Path, store: ArchiveStore, tar: TarTool, verdict: Verdict
    ) -> None:
        entry(root, "e1")
        fake = FakeFacts([not_due("e1", verdict)])
        result = apply_sweep(store, fake.facts(), pressed(root, tar))
        assert outcome_of(result, "e1").outcome == "not-actionable"
        assert (root / "e1").is_dir()

    def test_an_entry_idle_for_less_than_the_minimum_is_left(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "e1")
        fake = FakeFacts([not_due("e1", age_hours=0.2)])
        result = apply_sweep(store, fake.facts(), pressed(root, tar))
        assert outcome_of(result, "e1").outcome == "not-actionable"
        assert (root / "e1").is_dir()

    def test_its_archive_records_the_held_verdict_and_proofs(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "e1")
        fake = FakeFacts([not_due("e1")])
        apply_sweep(store, fake.facts(), pressed(root, tar))
        (record,) = store.read_index().records
        assert record.verdict == "DISPOSABLE"
        assert record.proof_ids == ("P1",)

    def test_an_entry_live_for_a_liveness_reason_is_never_pressured(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "e1")
        in_use = dataclasses.replace(
            row("e1", Verdict.LIVE, due=False),
            reasons=("process 7 has its working directory in the entry",),
            age_hours=10.0,
        )
        fake = FakeFacts([in_use])
        result = apply_sweep(store, fake.facts(), pressed(root, tar))
        assert outcome_of(result, "e1").outcome == "not-actionable"
        assert (root / "e1").is_dir()
        report = SweepReport("root", (in_use,), True, (), ())
        assert pressured_count(report, PRESSURE) == 0

    def test_a_live_entry_is_still_refused(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "e1")
        fake = FakeFacts([not_due("e1")], live={"e1"})
        result = apply_sweep(store, fake.facts(), pressed(root, tar))
        assert outcome_of(result, "e1").outcome != "archived"
        assert (root / "e1").is_dir()

    def test_an_incomplete_classification_packs_nothing(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "e1")
        fake = FakeFacts([not_due("e1")], complete=False)
        result = apply_sweep(store, fake.facts(), pressed(root, tar))
        assert outcome_of(result, "e1").outcome == "not-actionable"
        assert (root / "e1").is_dir()

    def test_largest_directory_count_is_packed_first(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        for name in ("small", "big", "mid"):
            entry(root, name)
        fake = FakeFacts(
            [
                not_due("small", directories=2),
                not_due("big", directories=50),
                row("due"),
                not_due("mid", directories=9),
            ]
        )
        entry(root, "due")
        apply_sweep(store, fake.facts(), pressed(root, tar))
        order = [r.original_path.rsplit("/", 1)[1] for r in store.read_index().records]
        assert order == ["due", "big", "mid", "small"]


class TestPressureFor:
    def test_only_at_block(self) -> None:
        caps = ScratchCapsConfig()
        assert pressure_for(CapLevel.WARN, caps, TTL) is None
        assert pressure_for(CapLevel.OK, caps, TTL) is None
        found = pressure_for(CapLevel.BLOCK, caps, TTL)
        assert found == Pressure(idle_hours=caps.pressure_idle_minutes / 60, ttl_hours=TTL)

    def test_a_root_with_no_ttl_gets_no_pressure(self) -> None:
        assert pressure_for(CapLevel.BLOCK, ScratchCapsConfig(), None) is None

    @pytest.mark.parametrize("mode", ["advise", "off"])
    def test_a_cap_that_does_not_enforce_gets_no_pressure(self, mode: str) -> None:
        caps = ScratchCapsConfig.model_validate({"mode": mode})
        assert pressure_for(CapLevel.BLOCK, caps, TTL) is None


class TestPressuredCount:
    """How many entries pressure would add, for the ``--apply`` confirmation (F-BYPS F1)."""

    def test_counts_only_idle_actionable_entries_not_yet_due(self) -> None:
        session = SweepReport("root/s", (not_due("child", age_hours=10.0),), True, (), ())
        rows = (
            row("due"),
            not_due("idle", age_hours=10.0),
            not_due("fresh", age_hours=0.1),
            not_due("kept", Verdict.KEPT),
        )
        report = SweepReport("root", rows, True, (), (), sessions=(session,))
        assert pressured_count(report, PRESSURE) == 2
        assert pressured_count(report, None) == 0

    def test_consent_binds_exactly_the_counted_entries(self) -> None:
        session = SweepReport("root/s", (not_due("child", age_hours=10.0),), True, (), ())
        rows = (row("due"), not_due("idle", age_hours=10.0), not_due("fresh", age_hours=0.1))
        report = SweepReport("root", rows, True, (), (), sessions=(session,))
        bound = consent_to(report, PRESSURE)
        assert bound is not None
        assert bound.consented == frozenset({"root/idle", "root/s/child"})
        assert pressured_count(report, bound) == len(bound.consented)
        assert consent_to(report, None) is None


class TestPressureIsBoundToConsent:
    """The run never packs a not-due entry the confirmation did not count."""

    def test_an_entry_outside_the_consented_set_is_left(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "counted")
        entry(root, "late")
        bound = dataclasses.replace(PRESSURE, consented=frozenset({str(root / "counted")}))
        fake = FakeFacts([not_due("counted"), not_due("late")])
        result = apply_sweep(store, fake.facts(), pressed(root, tar, bound))
        assert outcome_of(result, "counted").outcome == "archived"
        assert outcome_of(result, "late").outcome == "not-actionable"
        assert (root / "late").is_dir()

    def test_a_due_entry_needs_no_consent(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "due")
        bound = dataclasses.replace(PRESSURE, consented=frozenset())
        result = apply_sweep(store, FakeFacts([row("due")]).facts(), pressed(root, tar, bound))
        assert outcome_of(result, "due").outcome == "archived"
