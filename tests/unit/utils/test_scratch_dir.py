"""The sanctioned scratch directory is created, not assumed (Plan 00333).

`project_containment` denies a write outside the repository root and points the
agent at `untracked/scratch/`. In a project where that directory does not exist,
the guidance names nothing — the guard would block a real need and offer a path
that is not there. Owner ruling: create it, and make sure it is ignored.

Two properties matter and are asserted separately, because a directory that
exists but is TRACKED is worse than no directory at all: scratch would then flow
into review and history.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.utils.scratch_dir import (
    SCRATCH_IGNORE_CONTENT,
    ensure_scratch_dir,
)


class TestItCreatesWhatIsMissing:
    def test_the_scratch_directory_is_created(self, tmp_path: Path) -> None:
        ensure_scratch_dir(tmp_path)

        assert (tmp_path / "untracked" / "scratch").is_dir()

    def test_the_parent_is_created_too(self, tmp_path: Path) -> None:
        ensure_scratch_dir(tmp_path)

        assert (tmp_path / "untracked").is_dir()

    def test_an_ignore_file_is_written(self, tmp_path: Path) -> None:
        ensure_scratch_dir(tmp_path)

        assert (tmp_path / "untracked" / ".gitignore").read_text(
            encoding="utf-8"
        ) == SCRATCH_IGNORE_CONTENT

    def test_the_ignore_file_ignores_everything_but_itself(self, tmp_path: Path) -> None:
        """The two lines are the whole point: `*` keeps scratch out of git, and
        `!.gitignore` keeps the rule itself tracked so the next checkout has it."""
        ensure_scratch_dir(tmp_path)
        lines = SCRATCH_IGNORE_CONTENT.split()

        assert "*" in lines
        assert "!.gitignore" in lines

    def test_it_reports_that_it_acted(self, tmp_path: Path) -> None:
        assert ensure_scratch_dir(tmp_path) is True


class TestItIsIdempotent:
    def test_a_second_call_reports_no_change(self, tmp_path: Path) -> None:
        ensure_scratch_dir(tmp_path)

        assert ensure_scratch_dir(tmp_path) is False

    def test_a_second_call_does_not_raise(self, tmp_path: Path) -> None:
        ensure_scratch_dir(tmp_path)
        ensure_scratch_dir(tmp_path)

        assert (tmp_path / "untracked" / "scratch").is_dir()


class TestItNeverDestroys:
    def test_an_existing_ignore_file_is_left_alone(self, tmp_path: Path) -> None:
        """A project may already ignore `untracked/` from the repo root, or have
        its own rules here. Overwriting them would be a silent policy change,
        and the daemon has no business making one."""
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        existing = untracked / ".gitignore"
        existing.write_text("# hand-written\n*.log\n", encoding="utf-8")

        ensure_scratch_dir(tmp_path)

        assert existing.read_text(encoding="utf-8") == "# hand-written\n*.log\n"

    def test_existing_scratch_content_survives(self, tmp_path: Path) -> None:
        scratch = tmp_path / "untracked" / "scratch"
        scratch.mkdir(parents=True)
        kept = scratch / "notes.md"
        kept.write_text("# in progress", encoding="utf-8")

        ensure_scratch_dir(tmp_path)

        assert kept.read_text(encoding="utf-8") == "# in progress"


class TestScratchPathResolvesAbsolutelyOnAnyMachine:
    """Two constraints pull opposite ways, and each was violated in turn.

    ABSOLUTE when executed: the playbook renders each ``AcceptanceTest.command``
    verbatim for a tester to follow, and a Write instruction spelled
    ``untracked/scratch/x.py`` is denied by ``AbsolutePathHandler`` (priority
    12, terminal) before the handler under test is consulted -- so the test
    reports the wrong rule and can never pass. ``/tmp`` worked precisely
    BECAUSE it was absolute; migrating in-repo has to keep that property, not
    just change the location.

    But NOT the rendering machine's root: the playbook is followed in client
    installs too, so a baked-in ``/workspace/...`` instructs a tester to write
    outside their own project. That is pinned by
    ``tests/integration/test_generated_docs_are_path_agnostic.py``, whose
    docstring names this exact failure.

    ``$CLAUDE_PROJECT_DIR`` is the only spelling satisfying both, and is
    already the convention in the surrounding acceptance tests.
    """

    def test_it_is_rooted_at_the_project_dir_variable(self) -> None:
        from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

        assert scratch_path("fixture", "x.py") == (
            "$CLAUDE_PROJECT_DIR/untracked/scratch/fixture/x.py"
        )

    def test_the_bare_directory_is_available(self) -> None:
        from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

        assert scratch_path() == "$CLAUDE_PROJECT_DIR/untracked/scratch"

    def test_it_never_names_a_concrete_machine_root(self) -> None:
        """The regression guard for the second constraint: no matter what the
        live ProjectContext says, the rendered text must not carry it."""
        from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

        rendered = scratch_path("fixture")

        assert "/workspace" not in rendered
        assert rendered.startswith("$")

    def test_it_does_not_depend_on_project_context(self, monkeypatch) -> None:
        """Rendering guidance must work outside a running daemon -- unit
        tests and tooling both do it. Reading ProjectContext here would make
        a path builder raise, taking its caller down over cosmetics."""

        def _raise() -> Path:
            raise RuntimeError("ProjectContext not initialised")

        from claude_code_hooks_daemon.core.project_context import ProjectContext
        from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

        monkeypatch.setattr(ProjectContext, "project_root", staticmethod(_raise))

        assert scratch_path("fixture") == "$CLAUDE_PROJECT_DIR/untracked/scratch/fixture"

    def test_it_creates_the_ignore_file_when_only_the_directory_exists(
        self, tmp_path: Path
    ) -> None:
        """The half-built case: a project with an `untracked/` directory that
        nothing ignores. Leaving it would let scratch reach review."""
        (tmp_path / "untracked").mkdir()

        assert ensure_scratch_dir(tmp_path) is True
        assert (tmp_path / "untracked" / ".gitignore").is_file()
