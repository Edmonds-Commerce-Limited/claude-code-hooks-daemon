"""No test run may write a tracked generated doc of ANY checkout of this repository.

Plan 00474 N280: a test run left an older ``<hooksdaemon>`` block in the MAIN
checkout's ``CLAUDE.md``. The conftest guard only protects the checkout the run
belongs to, and it acts after the fact. The jail closes the route structurally:
every process of the run (the pytest process and each Python it spawns) refuses
to open, rename over or delete the protected docs of every checkout, and records
the attempt so the test that made it fails.
"""

from __future__ import annotations

import argparse
import contextlib
import inspect
import os
import shutil
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_init_config
from tests.jail_site import doc_write_jail as jail

_JAIL_SITE_DIR = Path(jail.__file__).resolve().parent


@pytest.fixture
def armed(tmp_path: Path) -> Generator[tuple[Path, Path], None, None]:
    """Arm the jail over ``tmp_path/CLAUDE.md`` and yield (protected file, log)."""
    protected = tmp_path / "CLAUDE.md"
    protected.write_text("original\n", encoding="utf-8")
    log = tmp_path / "jail.log"
    previous = jail.install(frozenset({str(protected.resolve())}), log)
    yield protected, log
    jail.restore(previous)


class TestInProcess:
    """The audit hook inside the pytest process."""

    def test_a_write_open_is_refused_and_leaves_the_file_alone(
        self, armed: tuple[Path, Path]
    ) -> None:
        protected, _ = armed

        with pytest.raises(jail.DocWriteRefused):
            protected.write_text("tampered\n", encoding="utf-8")

        assert protected.read_text(encoding="utf-8") == "original\n"

    def test_an_append_is_refused(self, armed: tuple[Path, Path]) -> None:
        protected, _ = armed

        with pytest.raises(jail.DocWriteRefused), protected.open("a", encoding="utf-8") as handle:
            handle.write("more\n")

        assert protected.read_text(encoding="utf-8") == "original\n"

    def test_reading_is_never_refused(self, armed: tuple[Path, Path]) -> None:
        protected, _ = armed

        assert protected.read_text(encoding="utf-8") == "original\n"

    def test_renaming_over_it_is_refused(self, armed: tuple[Path, Path], tmp_path: Path) -> None:
        protected, _ = armed
        replacement = tmp_path / "CLAUDE.md.new"
        replacement.write_text("replacement\n", encoding="utf-8")

        with pytest.raises(jail.DocWriteRefused):
            replacement.replace(protected)

        assert protected.read_text(encoding="utf-8") == "original\n"

    def test_deleting_it_is_refused(self, armed: tuple[Path, Path]) -> None:
        protected, _ = armed

        with pytest.raises(jail.DocWriteRefused):
            protected.unlink()

        assert protected.exists()

    def test_deleting_a_link_to_it_leaves_the_doc_alone(
        self, armed: tuple[Path, Path], tmp_path: Path
    ) -> None:
        """A delete acts on the link, not its target, so it is not a write to the doc."""
        protected, log = armed
        alias = tmp_path / "alias.md"
        alias.symlink_to(protected)

        alias.unlink()

        assert protected.read_text(encoding="utf-8") == "original\n"
        assert not log.exists()

    def test_rmtree_of_an_unrelated_tree_is_not_mistaken_for_the_protected_doc(
        self, armed: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``shutil.rmtree`` unlinks bare names relative to a directory fd.

        With the working directory holding a protected ``CLAUDE.md``, a bare
        ``CLAUDE.md`` in some OTHER tree is a different file.
        """
        protected, log = armed
        monkeypatch.chdir(protected.parent)
        other = tmp_path / "other-tree"
        (other / "sub").mkdir(parents=True)
        (other / "sub" / "CLAUDE.md").write_text("not the protected one\n", encoding="utf-8")

        shutil.rmtree(other)

        assert not other.exists()
        assert protected.exists()
        assert not log.exists()

    def test_rmtree_of_the_tree_holding_it_is_refused(
        self, armed: tuple[Path, Path], tmp_path: Path
    ) -> None:
        protected, _ = armed

        with pytest.raises(jail.DocWriteRefused):
            shutil.rmtree(protected.parent)

        assert protected.exists()

    def test_a_symlink_to_it_is_refused_too(self, armed: tuple[Path, Path], tmp_path: Path) -> None:
        protected, _ = armed
        alias = tmp_path / "alias.md"
        alias.symlink_to(protected)

        with pytest.raises(jail.DocWriteRefused):
            alias.write_text("tampered\n", encoding="utf-8")

        assert protected.read_text(encoding="utf-8") == "original\n"

    def test_other_files_are_not_touched_by_the_jail(
        self, armed: tuple[Path, Path], tmp_path: Path
    ) -> None:
        other = tmp_path / "other.md"

        other.write_text("fine\n", encoding="utf-8")

        assert other.read_text(encoding="utf-8") == "fine\n"

    def test_a_refusal_is_logged_so_the_test_can_be_failed(self, armed: tuple[Path, Path]) -> None:
        protected, log = armed

        with pytest.raises(jail.DocWriteRefused):
            protected.write_text("tampered\n", encoding="utf-8")

        assert str(protected.resolve()) in log.read_text(encoding="utf-8")

    def test_allowed_lets_the_conftest_restore_through(self, armed: tuple[Path, Path]) -> None:
        protected, log = armed

        with jail.allowed():
            protected.write_text("restored\n", encoding="utf-8")

        assert protected.read_text(encoding="utf-8") == "restored\n"
        assert not log.exists()
        with pytest.raises(jail.DocWriteRefused):
            protected.write_text("again\n", encoding="utf-8")

    def test_a_disarmed_jail_refuses_nothing(self, tmp_path: Path) -> None:
        target = tmp_path / "CLAUDE.md"
        previous = jail.install(frozenset({str(target.resolve())}), tmp_path / "jail.log")
        jail.restore(None)
        try:
            target.write_text("fine\n", encoding="utf-8")
        finally:
            jail.restore(previous)

        assert target.read_text(encoding="utf-8") == "fine\n"


class TestRefusalsAreReported:
    """``refusals_since`` is what the autouse fixture turns into a failure."""

    def test_new_lines_after_an_offset_are_returned(self, armed: tuple[Path, Path]) -> None:
        protected, log = armed
        offset = jail.log_offset(log)

        with pytest.raises(jail.DocWriteRefused):
            protected.write_text("tampered\n", encoding="utf-8")

        refusals = jail.refusals_since(log, offset)
        assert len(refusals) == 1
        assert str(protected.resolve()) in refusals[0]

    def test_nothing_is_reported_when_nothing_was_refused(self, tmp_path: Path) -> None:
        log = tmp_path / "jail.log"

        assert jail.refusals_since(log, jail.log_offset(log)) == []


class TestSubprocesses:
    """The route that matters most: a CLI spawned by a test."""

    def _env(self, protected: Path, log: Path) -> dict[str, str]:
        env = dict(os.environ)
        env.update(jail.environment_for_children(frozenset({str(protected.resolve())}), log))
        return env

    def test_a_spawned_python_cannot_write_a_protected_doc(self, tmp_path: Path) -> None:
        protected = tmp_path / "CLAUDE.md"
        protected.write_text("original\n", encoding="utf-8")
        log = tmp_path / "jail.log"

        completed = subprocess.run(
            [sys.executable, "-c", f"open({str(protected)!r}, 'w').write('tampered')"],
            env=self._env(protected, log),
            capture_output=True,
            text=True,
            check=False,
            cwd=tmp_path,
        )

        assert completed.returncode != 0
        assert "DocWriteRefused" in completed.stderr
        assert protected.read_text(encoding="utf-8") == "original\n"
        assert str(protected.resolve()) in log.read_text(encoding="utf-8")

    def test_regenerate_docs_against_a_protected_project_changes_nothing(
        self, tmp_path: Path
    ) -> None:
        """The route the ledger names: the doc writers pointed at a real checkout."""
        project = tmp_path / "project"
        project.mkdir()
        subprocess.run(["git", "init"], cwd=project, capture_output=True, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://example.com/acme/demo.git"],
            cwd=project,
            capture_output=True,
            check=True,
        )
        (project / ".claude" / "hooks-daemon").mkdir(parents=True)
        init_args = argparse.Namespace(project_root=project, minimal=False, force=False)
        assert cmd_init_config(init_args) == 0
        claude_md = project / "CLAUDE.md"
        claude_md.write_text("# Mine\n", encoding="utf-8")
        hooks_doc = project / ".claude" / "HOOKS-DAEMON.md"
        hooks_doc.write_text("# generated\n", encoding="utf-8")
        log = tmp_path / "jail.log"
        env = dict(os.environ)
        env.update(
            jail.environment_for_children(
                frozenset({str(claude_md.resolve()), str(hooks_doc.resolve())}), log
            )
        )
        program = (
            "import argparse, sys\n"
            "from pathlib import Path\n"
            "from claude_code_hooks_daemon.daemon.cli import cmd_regenerate_docs\n"
            f"args = argparse.Namespace(project_root=Path({str(project)!r}), "
            "include_disabled=False, output=None)\n"
            "sys.exit(cmd_regenerate_docs(args))\n"
        )

        completed = subprocess.run(
            [sys.executable, "-c", program],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            cwd=tmp_path,
        )

        assert claude_md.read_text(encoding="utf-8") == "# Mine\n"
        assert hooks_doc.read_text(encoding="utf-8") == "# generated\n"
        assert log.exists(), completed.stdout + completed.stderr
        assert completed.returncode != 0


class TestCheckoutDiscovery:
    """The jail covers every checkout of the repository, not just this one."""

    def test_a_plain_directory_is_its_own_only_checkout(self, tmp_path: Path) -> None:
        assert jail.checkout_roots(tmp_path) == [tmp_path.resolve()]

    def test_every_linked_worktree_and_the_main_checkout_are_found(self, tmp_path: Path) -> None:
        main = tmp_path / "main"
        main.mkdir()
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
        subprocess.run([*git, "init", "-q"], cwd=main, check=True, capture_output=True)
        subprocess.run(
            [*git, "commit", "-q", "--allow-empty", "-m", "seed"],
            cwd=main,
            check=True,
            capture_output=True,
        )
        linked = tmp_path / "linked"
        subprocess.run(
            [*git, "worktree", "add", "-q", str(linked), "-b", "side"],
            cwd=main,
            check=True,
            capture_output=True,
        )

        from_linked = jail.checkout_roots(linked)
        from_main = jail.checkout_roots(main)

        assert set(from_linked) == {main.resolve(), linked.resolve()}
        assert set(from_main) == set(from_linked)

    def test_protected_paths_name_both_generated_docs_of_each_root(self, tmp_path: Path) -> None:
        paths = jail.protected_paths([tmp_path.resolve()])

        assert paths == frozenset(
            {
                str(tmp_path.resolve() / "CLAUDE.md"),
                str(tmp_path.resolve() / ".claude" / "HOOKS-DAEMON.md"),
            }
        )

    def test_the_protected_names_are_the_conftest_guards_names(self) -> None:
        import tests.conftest as conftest

        assert tuple(conftest._TRACKED_FILES_NO_TEST_MAY_WRITE) == jail.PROTECTED_RELATIVE_PATHS


class TestSiteDirectory:
    """``sitecustomize`` is what arms a spawned Python from its environment."""

    def test_the_site_directory_holds_a_sitecustomize(self) -> None:
        assert (_JAIL_SITE_DIR / "sitecustomize.py").is_file()

    def test_children_are_pointed_at_the_site_directory(self, tmp_path: Path) -> None:
        env = jail.environment_for_children(frozenset({"/x/CLAUDE.md"}), tmp_path / "log")

        assert str(_JAIL_SITE_DIR) in env["PYTHONPATH"].split(os.pathsep)
        assert env[jail.ENV_PROTECTED] == "/x/CLAUDE.md"
        assert env[jail.ENV_LOG] == str(tmp_path / "log")


class TestSessionWiring:
    """``tests/conftest.py`` arms the jail over the real checkouts for the whole run."""

    @staticmethod
    def _session_log() -> Path:
        return Path(os.environ[jail.ENV_LOG])

    def test_this_checkouts_claude_md_cannot_be_written_by_a_test(self) -> None:
        import tests.conftest as conftest

        with jail.consuming_refusals(self._session_log()), pytest.raises(jail.DocWriteRefused):
            (conftest._REPO_ROOT / "CLAUDE.md").write_text("tampered\n", encoding="utf-8")

    def test_every_checkout_of_the_repository_is_protected(self) -> None:
        import tests.conftest as conftest

        expected = jail.protected_paths(jail.checkout_roots(conftest._REPO_ROOT))

        assert set(os.environ[jail.ENV_PROTECTED].split(os.pathsep)) == expected

    def test_a_spawned_python_inherits_the_protection_of_this_run(self) -> None:
        import tests.conftest as conftest

        target = conftest._REPO_ROOT / "CLAUDE.md"
        with jail.consuming_refusals(self._session_log()):
            completed = subprocess.run(
                [sys.executable, "-c", f"open({str(target)!r}, 'a')"],
                capture_output=True,
                text=True,
                check=False,
            )
            logged = self._session_log().read_text(encoding="utf-8")

        assert completed.returncode != 0
        assert "DocWriteRefused" in completed.stderr
        assert str(target) in logged

    def test_an_unconsumed_refusal_fails_the_test_that_caused_it(self) -> None:
        """The swallow-proof half: the fixture reads the log, not the exception."""
        import tests.conftest as conftest

        fixture = inspect.unwrap(conftest.no_test_writes_a_generated_doc_of_any_checkout)
        teardown = fixture()
        next(teardown)
        with jail.consuming_refusals(self._session_log()):
            with contextlib.suppress(jail.DocWriteRefused):
                (conftest._REPO_ROOT / "CLAUDE.md").write_text("x", encoding="utf-8")
            with pytest.raises(AssertionError, match="tried to write a tracked generated doc"):
                next(teardown)
