"""The apply run's fresh facts: entry liveness and references (Plan 00627 Task 3.8 unit C).

``entry_in_use`` is the claim's liveness re-check. It must look under BOTH the
entry's name and its ``.sweeping-`` claim name, and must NOT read the root's
ctime or any minimum-age signal: the claim's own rename bumps the root's ctime,
so that signal would make every claim refuse itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.scratch_archive_facts import LazyReferences, entry_in_use
from claude_code_hooks_daemon.core.scratch_liveness import BackgroundRecords, ProcessCwdReading
from claude_code_hooks_daemon.core.scratch_references import ReferenceSet

ROOT = Path("/p/untracked/scratch")
QUIET = ProcessCwdReading({1: Path("/elsewhere")}, ())
NO_BACKGROUND = BackgroundRecords(())


def live(
    name: str = "e",
    *,
    reading: ProcessCwdReading = QUIET,
    background: BackgroundRecords = NO_BACKGROUND,
) -> bool:
    return entry_in_use(
        name,
        root=ROOT,
        relative_root="untracked/scratch",
        reading=reading,
        background=background,
    )


class TestEntryInUse:
    def test_nothing_in_use(self) -> None:
        assert live() is False

    @pytest.mark.parametrize("held", ["e", ".sweeping-e", "e/deep", ".sweeping-e/deep"])
    def test_a_cwd_under_either_name_is_live(self, held: str) -> None:
        reading = ProcessCwdReading({1: Path("/elsewhere"), 7: ROOT / held}, ())
        assert live(reading=reading) is True

    def test_a_sibling_sharing_the_prefix_is_not_the_entry(self) -> None:
        reading = ProcessCwdReading({7: ROOT / "ee"}, ())
        assert live(reading=reading) is False

    @pytest.mark.parametrize("held", ["e/log", ".sweeping-e/log", "e/deep/lib.so"])
    def test_a_file_held_open_under_either_name_is_live(self, held: str) -> None:
        """DESIGN.md open-descriptor row: a cwd elsewhere does not hide an open file."""
        reading = ProcessCwdReading({7: Path("/elsewhere")}, (), {7: (ROOT / held,)})
        assert live(reading=reading) is True

    def test_a_file_open_in_a_sibling_sharing_the_prefix_is_not_the_entry(self) -> None:
        reading = ProcessCwdReading({7: Path("/elsewhere")}, (), {7: (ROOT / "ee" / "log",)})
        assert live(reading=reading) is False

    def test_an_unreadable_pid_is_live(self) -> None:
        assert live(reading=ProcessCwdReading({1: Path("/elsewhere")}, (9,))) is True

    def test_no_cwds_at_all_is_live(self) -> None:
        assert live(reading=ProcessCwdReading({}, ())) is True

    def test_unreadable_background_records_are_live(self) -> None:
        assert live(background=BackgroundRecords((), error="torn")) is True

    @pytest.mark.parametrize(
        "command",
        [
            "tail -f /p/untracked/scratch/e/log",
            "tail -f /p/untracked/scratch/.sweeping-e/log",
            "make -C untracked/scratch/e",
            "make -C untracked/scratch/.sweeping-e",
        ],
    )
    def test_a_background_command_naming_either_path_is_live(self, command: str) -> None:
        assert live(background=BackgroundRecords((command,))) is True

    def test_takes_no_age_signal(self) -> None:
        # The signature itself is the pin: no ctime, birth or min-age input exists.
        import inspect

        params = set(inspect.signature(entry_in_use).parameters)
        assert params == {"name", "root", "relative_root", "reading", "background"}


class TestLazyReferences:
    def test_built_once_lazily(self) -> None:
        calls: list[int] = []

        def build() -> ReferenceSet:
            calls.append(1)
            return ReferenceSet(sites={"named": ("README.md",)})

        refs = LazyReferences(build)
        assert calls == []
        assert refs("named") is True
        assert refs("other") is False
        assert calls == [1]

    def test_unknown_set_is_referenced(self) -> None:
        refs = LazyReferences(lambda: ReferenceSet(unknown="git grep failed"))
        assert refs("anything") is True

    def test_an_unsearchable_name_is_referenced(self) -> None:
        refs = LazyReferences(lambda: ReferenceSet())
        assert refs("we ird$name") is True

    def test_a_build_that_raises_is_referenced_every_time(self) -> None:
        def build() -> ReferenceSet:
            raise OSError("no git")

        refs = LazyReferences(build)
        assert refs("a") is True
        assert refs("b") is True


class TestRootNamed:
    """Task 4.3: a session container is held by what names the parent root, not its siblings."""

    def test_a_site_naming_one_child_does_not_name_the_root(self) -> None:
        refs = LazyReferences(lambda: ReferenceSet(sites={"s-x": ("README.md",)}))
        assert refs.root_named() is False

    def test_a_root_site_or_an_unknown_set_names_the_root(self) -> None:
        assert LazyReferences(lambda: ReferenceSet(root_sites=("README.md",))).root_named()
        assert LazyReferences(lambda: ReferenceSet(unknown="no git")).root_named()

    def test_a_failed_build_names_the_root(self) -> None:
        def build() -> ReferenceSet:
            raise OSError("boom")

        assert LazyReferences(build).root_named() is True
