"""Adversarial runs of the apply pipeline (Plan 00627 Task 3.8 unit D).

DESIGN.md section 5.2. A run killed after any step converges on the next run;
a swap, a write, a new reference or a new process between the steps leaves the
entry whole; and nothing outside the sweep root and the store is ever touched.
The helpers are copied from ``test_scratch_archive_apply.py`` (a test module is
never imported).
"""

from __future__ import annotations

import os
import random
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import scratch_archive_apply as apply_mod
from claude_code_hooks_daemon.core import scratch_archive_claim as claim_mod
from claude_code_hooks_daemon.core import scratch_archive_remove as remove_mod
from claude_code_hooks_daemon.core.scratch_archive import ArchiveRecord, ArchiveStore
from claude_code_hooks_daemon.core.scratch_archive_apply import (
    STEP_APPEND,
    STEP_CLAIM,
    STEP_PACK,
    ApplyFacts,
    ApplyResult,
    ApplySettings,
    EntryOutcome,
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
#: Path -> (kind, content, inode, mtime_ns): byte- AND inode-identical.
Deep = dict[str, tuple[str, bytes, int, int]]
#: The deletions one entry from :func:`entry` takes: a.txt, link, b.bin, sub, the root.
ENTRY_DELETES = 5


class Crash(BaseException):
    """A kill between two steps: not an ``Exception``, so nothing in the pipeline catches it."""


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
    on_classify: Callable[[], None] | None = None
    on_reference_check: Callable[[str], None] | None = None

    def classify(self) -> SweepReport:
        self.classified += 1
        if self.on_classify is not None:
            self.on_classify()
        reasons = () if self.complete else ("budget spent",)
        return SweepReport("root", tuple(self.rows), self.complete, reasons, ())

    def is_referenced(self, name: str) -> bool:
        if self.on_reference_check is not None:
            self.on_reference_check(name)
        return name in self.referenced

    def facts(self) -> ApplyFacts:
        return ApplyFacts(
            classify=self.classify,
            entry_live=lambda name: name in self.live,
            referenced=self.is_referenced,
        )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    path = tmp_path / "project"
    (path / "untracked" / "scratch").mkdir(parents=True)
    (path / "src").mkdir()
    (path / "src" / "code.py").write_text("print('project')\n")
    return path


@pytest.fixture
def root(project: Path) -> Path:
    return project / "untracked" / "scratch"


@pytest.fixture
def store_dir(project: Path) -> Path:
    return project / "untracked" / "scratch-archive"


@pytest.fixture
def store(store_dir: Path) -> Iterator[ArchiveStore]:
    with ArchiveStore.open(store_dir) as opened:
        with opened.lock():
            yield opened


@pytest.fixture
def tar() -> TarTool:
    return find_gnu_tar()


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    path = tmp_path / "outside"
    (path / "deep").mkdir(parents=True)
    (path / "keep.txt").write_text("outside content")
    (path / "deep" / "inner.bin").write_bytes(b"\x00outside\xff")
    return path


def settings(root: Path, tar: TarTool) -> ApplySettings:
    return ApplySettings(
        root=root,
        original_prefix="untracked/scratch",
        checkout="main",
        tar=tar,
        max_inodes=MAX,
        retention_hours=RETENTION,
        clock=lambda: NOW,
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


def deep_snapshot(top: Path, *, skip: tuple[Path, ...] = ()) -> Deep:
    """Every node under ``top`` (``top`` itself included), never following a link."""
    out: Deep = {}
    info = top.lstat()
    out["."] = ("dir", b"", info.st_ino, info.st_mtime_ns)
    for dirpath, dirnames, filenames in os.walk(top):
        dirnames[:] = [d for d in dirnames if Path(dirpath) / d not in skip]
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            if path in skip:
                continue
            info = path.lstat()
            rel = str(path.relative_to(top))
            if path.is_symlink():
                out[rel] = ("link", str(path.readlink()).encode(), info.st_ino, info.st_mtime_ns)
            elif path.is_dir():
                out[rel] = ("dir", b"", info.st_ino, info.st_mtime_ns)
            else:
                out[rel] = ("file", path.read_bytes(), info.st_ino, info.st_mtime_ns)
    return out


def outcome_of(result: ApplyResult, name: str) -> EntryOutcome:
    matches = [o for o in result.entries if o.name == name]
    assert len(matches) == 1, result.entries
    return matches[0]


def records_naming(store: ArchiveStore, name: str) -> list[ArchiveRecord]:
    return [r for r in store.read_index().records if r.original_path == f"untracked/scratch/{name}"]


def restore_into(root: Path, store: ArchiveStore, archive_id: str, tar: TarTool) -> None:
    fd = open_dir(root)
    try:
        restore(store, archive_id, fd, root_path="untracked/scratch", tar=tar, max_inodes=MAX)
    finally:
        os.close(fd)


def assert_converged(
    root: Path, store: ArchiveStore, tar: TarTool, name: str, before: Snapshot
) -> None:
    """Gone with a restorable record, or intact with none; never half-way, never claimed."""
    assert not (root / (CLAIM_PREFIX + name)).exists()
    assert not (root / (CLAIM_PREFIX + name)).is_symlink()
    records = records_naming(store, name)
    if (root / name).exists():
        assert snapshot(root / name) == before
        assert records == []
        return
    assert records, "the entry is gone but no record names it"
    restore_into(root, store, records[-1].archive_id, tar)
    assert snapshot(root / name) == before


def crash_at(step: str) -> Callable[[str, str], None]:
    def after_step(seen: str, name: str) -> None:
        if seen == step:
            raise Crash(f"killed after {step} of {name}")

    return after_step


class TestKilledBetweenSteps:
    @pytest.mark.parametrize("step", [STEP_CLAIM, STEP_PACK, STEP_APPEND])
    def test_a_rerun_after_a_kill_converges(
        self, root: Path, store: ArchiveStore, tar: TarTool, step: str
    ) -> None:
        entry(root, "e1")
        before = snapshot(root / "e1")
        with pytest.raises(Crash):
            apply_sweep(
                store,
                FakeFacts([row("e1")]).facts(),
                settings(root, tar),
                after_step=crash_at(step),
            )
        # The kill left the claim in place: the rerun must finish or undo it.
        assert (root / (CLAIM_PREFIX + "e1")).exists()
        apply_sweep(store, FakeFacts([row("e1")]).facts(), settings(root, tar))
        assert_converged(root, store, tar, "e1", before)

    @pytest.mark.parametrize("step", [STEP_CLAIM, STEP_PACK, STEP_APPEND])
    def test_a_kill_then_a_not_actionable_rerun_still_converges(
        self, root: Path, store: ArchiveStore, tar: TarTool, step: str
    ) -> None:
        # The rerun's classification no longer says "go": resume alone must converge.
        entry(root, "e1")
        before = snapshot(root / "e1")
        with pytest.raises(Crash):
            apply_sweep(
                store,
                FakeFacts([row("e1")]).facts(),
                settings(root, tar),
                after_step=crash_at(step),
            )
        apply_sweep(store, FakeFacts([row("e1", Verdict.LIVE)]).facts(), settings(root, tar))
        assert_converged(root, store, tar, "e1", before)

    @pytest.mark.parametrize("deletes_before_kill", range(ENTRY_DELETES))
    def test_a_kill_mid_remove_converges(
        self,
        root: Path,
        store: ArchiveStore,
        tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
        deletes_before_kill: int,
    ) -> None:
        entry(root, "e1")
        before = snapshot(root / "e1")
        real_delete = remove_mod._delete
        calls = {"n": 0}

        def killing_delete(dir_fd: int, name: str, *, directory: bool, inside: bool) -> None:
            if calls["n"] == deletes_before_kill:
                raise Crash(f"killed before delete {calls['n'] + 1}")
            calls["n"] += 1
            real_delete(dir_fd, name, directory=directory, inside=inside)

        monkeypatch.setattr(remove_mod, "_delete", killing_delete)
        with pytest.raises(Crash):
            apply_sweep(store, FakeFacts([row("e1")]).facts(), settings(root, tar))
        monkeypatch.setattr(remove_mod, "_delete", real_delete)
        result = apply_sweep(store, FakeFacts([row("e1")]).facts(), settings(root, tar))
        # The record was appended before the kill: resume finishes the removal.
        assert [r.outcome for r in result.resumed] == ["removed"], result.resumed
        assert not (root / "e1").exists()
        assert_converged(root, store, tar, "e1", before)

    def test_two_kills_in_a_row_still_converge(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "e1")
        before = snapshot(root / "e1")
        for step in (STEP_PACK, STEP_CLAIM):
            with pytest.raises(Crash):
                apply_sweep(
                    store,
                    FakeFacts([row("e1")]).facts(),
                    settings(root, tar),
                    after_step=crash_at(step),
                )
        apply_sweep(store, FakeFacts([row("e1")]).facts(), settings(root, tar))
        assert_converged(root, store, tar, "e1", before)


class TestOrdinaryErrorsMidStep:
    """An ``OSError`` (not a kill) inside a step: the run goes on and the entry is whole."""

    def _converges_after(
        self, root: Path, store: ArchiveStore, tar: TarTool, before: Snapshot
    ) -> ApplyResult:
        result = apply_sweep(store, FakeFacts([row("e1")]).facts(), settings(root, tar))
        assert_converged(root, store, tar, "e1", before)
        return result

    def test_the_claims_re_fingerprint_failing(
        self,
        root: Path,
        store: ArchiveStore,
        tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        entry(root, "e1")
        entry(root, "e2")
        before = snapshot(root / "e1")

        def failing(*args: object, **kwargs: object) -> object:
            raise OSError(5, "injected I/O error")

        monkeypatch.setattr(claim_mod, "fingerprint_at", failing)
        rows = [row("e1"), row("e2")]
        result = apply_sweep(store, FakeFacts(rows).facts(), settings(root, tar))
        assert outcome_of(result, "e1").outcome != "archived"
        # The run went on to the next entry rather than stopping with a claim held.
        assert outcome_of(result, "e2").outcome != "archived"
        assert not (root / (CLAIM_PREFIX + "e1")).exists()
        assert snapshot(root / "e1") == before
        monkeypatch.undo()
        self._converges_after(root, store, tar, before)

    def test_pack_failing_with_an_os_error(
        self,
        root: Path,
        store: ArchiveStore,
        tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        entry(root, "e1")
        before = snapshot(root / "e1")

        def failing(*args: object, **kwargs: object) -> object:
            raise OSError(28, "injected: no space left")

        monkeypatch.setattr(apply_mod, "pack", failing)
        result = apply_sweep(store, FakeFacts([row("e1")]).facts(), settings(root, tar))
        assert outcome_of(result, "e1").outcome == "renamed-back"
        assert snapshot(root / "e1") == before
        assert store.read_index().records == ()
        monkeypatch.undo()
        self._converges_after(root, store, tar, before)

    def test_the_record_append_failing(
        self,
        root: Path,
        store: ArchiveStore,
        tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        entry(root, "e1")
        before = snapshot(root / "e1")

        def failing(record: ArchiveRecord) -> None:
            raise OSError(28, "injected: no space left")

        monkeypatch.setattr(store, "append", failing)
        result = apply_sweep(store, FakeFacts([row("e1")]).facts(), settings(root, tar))
        assert outcome_of(result, "e1").outcome == "left-claimed"
        monkeypatch.undo()
        self._converges_after(root, store, tar, before)

    def test_a_delete_failing_with_an_os_error(
        self,
        root: Path,
        store: ArchiveStore,
        tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        entry(root, "e1")
        before = snapshot(root / "e1")
        real_delete = remove_mod._delete
        calls = {"n": 0}

        def failing_rmdir(*args: object, **kwargs: object) -> None:
            raise OSError(16, "injected: busy")

        real_rmdir = os.rmdir
        real_unlink = os.unlink

        def flaky_delete(dir_fd: int, name: str, *, directory: bool, inside: bool) -> None:
            # The third deletion meets an I/O error inside the real _delete.
            calls["n"] += 1
            monkeypatch.setattr(os, "rmdir", failing_rmdir if calls["n"] == 3 else real_rmdir)
            monkeypatch.setattr(os, "unlink", failing_rmdir if calls["n"] == 3 else real_unlink)
            real_delete(dir_fd, name, directory=directory, inside=inside)

        monkeypatch.setattr(remove_mod, "_delete", flaky_delete)
        result = apply_sweep(store, FakeFacts([row("e1")]).facts(), settings(root, tar))
        assert outcome_of(result, "e1").outcome == "left-claimed"
        monkeypatch.undo()
        self._converges_after(root, store, tar, before)


class TestLinksAreNeverFollowed:
    def test_a_disposable_link_entry_loses_only_the_link(
        self, root: Path, store: ArchiveStore, tar: TarTool, outside: Path
    ) -> None:
        (root / "e1").symlink_to(outside, target_is_directory=True)
        before_outside = deep_snapshot(outside)
        result = apply_sweep(store, FakeFacts([row("e1")]).facts(), settings(root, tar))
        assert outcome_of(result, "e1").outcome == "archived"
        assert not (root / "e1").is_symlink()
        assert deep_snapshot(outside) == before_outside

    def test_a_link_deep_inside_is_archived_as_a_link(
        self, root: Path, store: ArchiveStore, tar: TarTool, outside: Path
    ) -> None:
        entry(root, "e1")
        (root / "e1" / "sub" / "out").symlink_to(outside, target_is_directory=True)
        (root / "e1" / "outfile").symlink_to(outside / "keep.txt")
        before = snapshot(root / "e1")
        before_outside = deep_snapshot(outside)
        result = apply_sweep(store, FakeFacts([row("e1")]).facts(), settings(root, tar))
        assert outcome_of(result, "e1").outcome == "archived"
        assert deep_snapshot(outside) == before_outside
        (record,) = records_naming(store, "e1")
        restore_into(root, store, record.archive_id, tar)
        assert snapshot(root / "e1") == before
        assert deep_snapshot(outside) == before_outside


class TestSwappedBetweenSteps:
    def test_an_entry_swapped_for_a_symlink_after_its_fingerprint_is_not_followed(
        self, root: Path, store: ArchiveStore, tar: TarTool, outside: Path
    ) -> None:
        entry(root, "e1")
        before_outside = deep_snapshot(outside)

        def swap() -> None:
            shutil.rmtree(root / "e1")
            (root / "e1").symlink_to(outside, target_is_directory=True)

        fake = FakeFacts([row("e1")], on_classify=swap)
        result = apply_sweep(store, fake.facts(), settings(root, tar))
        assert outcome_of(result, "e1").outcome != "archived"
        assert (root / "e1").is_symlink()
        assert (root / "e1").readlink() == outside
        assert deep_snapshot(outside) == before_outside
        assert store.read_index().records == ()

    def test_a_subdirectory_swapped_for_a_symlink_is_not_followed(
        self, root: Path, store: ArchiveStore, tar: TarTool, outside: Path
    ) -> None:
        entry(root, "e1")
        before_outside = deep_snapshot(outside)

        def swap() -> None:
            shutil.rmtree(root / "e1" / "sub")
            (root / "e1" / "sub").symlink_to(outside, target_is_directory=True)

        fake = FakeFacts([row("e1")], on_classify=swap)
        result = apply_sweep(store, fake.facts(), settings(root, tar))
        assert outcome_of(result, "e1").outcome == "renamed-back"
        assert (root / "e1" / "sub").is_symlink()
        assert deep_snapshot(outside) == before_outside
        assert store.read_index().records == ()

    def test_an_entry_swapped_for_a_symlink_while_claimed_is_not_removed_through(
        self, root: Path, store: ArchiveStore, tar: TarTool, outside: Path
    ) -> None:
        # After pack, the claimed tree is replaced by a link to outside: removal must refuse.
        entry(root, "e1")
        before_outside = deep_snapshot(outside)
        claimed = root / (CLAIM_PREFIX + "e1")

        def swap(step: str, name: str) -> None:
            if step == STEP_APPEND:
                shutil.rmtree(claimed)
                claimed.symlink_to(outside, target_is_directory=True)

        result = apply_sweep(
            store, FakeFacts([row("e1")]).facts(), settings(root, tar), after_step=swap
        )
        assert outcome_of(result, "e1").outcome != "archived"
        assert deep_snapshot(outside) == before_outside
        apply_sweep(store, FakeFacts([row("e1")]).facts(), settings(root, tar))
        assert deep_snapshot(outside) == before_outside


class TestFactsChangeBetweenSteps:
    def test_a_reference_appearing_during_classification_keeps_the_entry(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "e1")
        before = snapshot(root)
        fake = FakeFacts([row("e1")])
        fake.on_classify = lambda: fake.referenced.add("e1")
        result = apply_sweep(store, fake.facts(), settings(root, tar))
        assert outcome_of(result, "e1").outcome in {"renamed-back", "stuck"}
        assert snapshot(root) == before
        assert store.read_index().records == ()

    def test_a_process_arriving_during_classification_keeps_the_entry(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry(root, "e1")
        before = snapshot(root)
        fake = FakeFacts([row("e1")])
        fake.on_classify = lambda: fake.live.add("e1")
        result = apply_sweep(store, fake.facts(), settings(root, tar))
        assert outcome_of(result, "e1").outcome in {"renamed-back", "stuck"}
        assert snapshot(root) == before
        assert store.read_index().records == ()

    def test_a_write_after_pack_is_never_removed(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        # The archive no longer matches the tree: the write must survive both runs.
        entry(root, "e1")
        claimed = root / (CLAIM_PREFIX + "e1")

        def write(step: str, name: str) -> None:
            if step == STEP_PACK:
                (claimed / "late.txt").write_text("written after pack")

        result = apply_sweep(
            store, FakeFacts([row("e1")]).facts(), settings(root, tar), after_step=write
        )
        assert outcome_of(result, "e1").outcome != "archived"
        apply_sweep(store, FakeFacts([row("e1", Verdict.LIVE)]).facts(), settings(root, tar))
        assert (root / "e1" / "late.txt").read_text() == "written after pack"
        assert (root / "e1" / "a.txt").read_text() == "alpha e1"

    def test_a_write_during_the_reference_check_is_kept_by_the_archive_or_the_tree(
        self, root: Path, store: ArchiveStore, tar: TarTool
    ) -> None:
        # The reference check runs after the claim's re-fingerprint; a write then
        # must either be in the archive or still be on disk.
        entry(root, "e1")
        claimed = root / (CLAIM_PREFIX + "e1")
        fake = FakeFacts([row("e1")])

        def write(name: str) -> None:
            (claimed / "late.txt").write_text("late")

        fake.on_reference_check = write
        apply_sweep(store, fake.facts(), settings(root, tar))
        fake.on_reference_check = None
        apply_sweep(store, FakeFacts([row("e1", Verdict.LIVE)]).facts(), settings(root, tar))
        if not (root / "e1").exists():
            (record,) = records_naming(store, "e1")
            restore_into(root, store, record.archive_id, tar)
        assert (root / "e1" / "late.txt").read_text() == "late"


ALL_VERDICTS = list(Verdict)
KEPT = {Verdict.LIVE, Verdict.PROTECTED, Verdict.STUCK, Verdict.REFERENCED}


@pytest.mark.parametrize("seed", range(12))
def test_nothing_outside_the_root_and_the_store_is_ever_touched(
    seed: int,
    tmp_path: Path,
    project: Path,
    root: Path,
    store_dir: Path,
    store: ArchiveStore,
    tar: TarTool,
    outside: Path,
) -> None:
    rng = random.Random(seed)
    rows: list[EntryRow] = []
    kept: list[str] = []
    for index in range(rng.randint(3, 10)):
        name = f"e{index}"
        shape = rng.choice(["tree", "file", "outlink", "innerlink"])
        if shape == "tree":
            entry(root, name)
        elif shape == "file":
            (root / name).write_bytes(rng.randbytes(rng.randint(0, 64)))
        elif shape == "outlink":
            (root / name).symlink_to(outside, target_is_directory=True)
        else:
            entry(root, name)
            (root / name / "out").symlink_to(outside / "keep.txt")
        verdict = rng.choice(ALL_VERDICTS)
        rows.append(row(name, verdict, due=rng.random() < 0.8))
        if verdict in KEPT:
            kept.append(name)
    # Every seed carries the hard cases: a due, disposable link to outside, and one inside.
    (root / "forced-out").symlink_to(outside, target_is_directory=True)
    entry(root, "forced-in")
    (root / "forced-in" / "out").symlink_to(outside / "keep.txt")
    rows += [row("forced-out"), row("forced-in")]
    fake = FakeFacts(rows)
    if rng.random() < 0.3:
        victim = rng.choice(rows).name
        fake.referenced.add(victim)
        kept.append(victim)
    kept_before = {name: deep_snapshot_of(root / name) for name in kept}
    world_before = deep_snapshot(tmp_path, skip=(root, store_dir))
    apply_sweep(store, fake.facts(), settings(root, tar))
    apply_sweep(store, fake.facts(), settings(root, tar))
    assert deep_snapshot(tmp_path, skip=(root, store_dir)) == world_before
    for name in kept:
        assert deep_snapshot_of(root / name) == kept_before[name], name
    assert not [p for p in root.iterdir() if p.name.startswith(CLAIM_PREFIX)]
    # The property is not vacuous: every due, actionable, unreferenced entry went.
    for r in rows:
        if r.due and r.verdict in {Verdict.DISPOSABLE, Verdict.UNCERTAIN} and r.name not in kept:
            assert not (root / r.name).is_symlink() and not (root / r.name).exists(), r.name


def deep_snapshot_of(path: Path) -> Deep:
    """A whole entry: a link or a file is one node, a directory its whole tree."""
    info = path.lstat()
    if path.is_symlink():
        return {".": ("link", str(path.readlink()).encode(), info.st_ino, info.st_mtime_ns)}
    if path.is_file():
        return {".": ("file", path.read_bytes(), info.st_ino, info.st_mtime_ns)}
    return deep_snapshot(path)
