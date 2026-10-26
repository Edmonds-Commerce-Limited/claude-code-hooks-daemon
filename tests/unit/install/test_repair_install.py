"""Tests for the ``repair-install`` verb (Plan 00552 Task 3.1 and 3.2).

A merge or rebase can leave conflict markers in the hook stubs, ``init.sh`` or
``settings.json``. The verb restores the first two from the installed daemon's
templates, checks everything with ``bash -n`` / JSON parsing, and runs from a
terminal with no Claude session and no running daemon.
"""

from __future__ import annotations

import argparse
import json
import shutil
import stat
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_repair_install
from claude_code_hooks_daemon.install.forwarder_generator import (
    INIT_PARSE_GUARD_HEADER,
    INIT_REPAIR_HINT,
    REPAIR_INSTALL_VERB,
)
from claude_code_hooks_daemon.install.repair_install import (
    CONFLICT_MARKER_PREFIXES,
    repair_install,
)
from claude_code_hooks_daemon.utils.hook_registration import HOOK_EVENTS_IN_SETTINGS

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFLICTED = "<<<<<<< HEAD\necho ours\n=======\necho theirs\n>>>>>>> other\n"
STUB = "pre-tool-use"


def _make_client(tmp_path: Path) -> Path:
    """A client project whose ``.claude/hooks-daemon`` carries the templates."""
    project = tmp_path / "project"
    daemon = project / ".claude" / "hooks-daemon"
    (daemon / ".claude").mkdir(parents=True)
    shutil.copytree(REPO_ROOT / ".claude" / "hooks", daemon / ".claude" / "hooks")
    shutil.copy(REPO_ROOT / "init.sh", daemon / "init.sh")
    (project / ".claude" / "hooks").mkdir()
    shutil.copy(REPO_ROOT / "init.sh", project / ".claude" / "init.sh")
    for source in (daemon / ".claude" / "hooks").iterdir():
        if source.is_file():
            shutil.copy(source, project / ".claude" / "hooks" / source.name)
    (project / ".claude" / "settings.json").write_text(json.dumps({"hooks": {}}))
    return project


def _ns(project: Path, *, check: bool = False, reconcile: bool = False) -> argparse.Namespace:
    return argparse.Namespace(project_root=project, check=check, reconcile_settings=reconcile)


def _run(project: Path, *, check: bool = False, reconcile: bool = False) -> int:
    return cmd_repair_install(_ns(project, check=check, reconcile=reconcile))


class TestRepairNaming:
    """Task 3.2: the parse guard names the verb through the client wrapper."""

    def test_hint_names_the_verb_via_the_client_wrapper(self) -> None:
        assert REPAIR_INSTALL_VERB == "repair-install"
        assert f".claude/hooks-daemon/bin/hooks-daemon {REPAIR_INSTALL_VERB}" in INIT_REPAIR_HINT

    def test_hint_is_safe_inside_a_double_quoted_bash_string(self) -> None:
        for char in ('"', "$", "`", "\\"):
            assert char not in INIT_REPAIR_HINT

    def test_deployed_stubs_carry_the_new_hint(self) -> None:
        stub = (REPO_ROOT / ".claude" / "hooks" / STUB).read_text()
        assert INIT_PARSE_GUARD_HEADER in stub
        assert INIT_REPAIR_HINT in stub
        assert "rerun the installer" not in stub

    def test_verb_is_registered(self) -> None:
        args = build_parser().parse_args(["repair-install", "--check"])
        assert args.check is True
        assert args.reconcile_settings is False
        assert args.func is cmd_repair_install

    def test_reconcile_flag_is_explicit(self) -> None:
        args = build_parser().parse_args(["repair-install", "--reconcile-settings"])
        assert args.reconcile_settings is True


class TestRedeploy:
    """The stubs and init.sh come back from the installed templates."""

    def test_conflicted_stub_is_restored_and_parses(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = _make_client(tmp_path)
        stub = project / ".claude" / "hooks" / STUB
        stub.write_text(CONFLICTED)
        assert _run(project) == 0
        assert not any(
            line.startswith(CONFLICT_MARKER_PREFIXES) for line in stub.read_text().splitlines()
        )
        assert INIT_PARSE_GUARD_HEADER in stub.read_text()
        assert stub.stat().st_mode & stat.S_IXUSR
        assert f"OK {stub.relative_to(project)}" in capsys.readouterr().out

    def test_conflicted_init_sh_is_restored(self, tmp_path: Path) -> None:
        project = _make_client(tmp_path)
        init = project / ".claude" / "init.sh"
        init.write_text(CONFLICTED)
        assert _run(project) == 0
        assert init.read_text() == (REPO_ROOT / "init.sh").read_text()

    def test_missing_stub_is_recreated(self, tmp_path: Path) -> None:
        project = _make_client(tmp_path)
        stub = project / ".claude" / "hooks" / STUB
        stub.unlink()
        assert _run(project) == 0
        assert stub.is_file()

    def test_a_clean_install_is_unchanged_on_a_second_run(self, tmp_path: Path) -> None:
        project = _make_client(tmp_path)
        assert _run(project) == 0
        before = {p.name: p.read_text() for p in (project / ".claude" / "hooks").iterdir()}
        assert _run(project) == 0
        after = {p.name: p.read_text() for p in (project / ".claude" / "hooks").iterdir()}
        assert before == after

    def test_report_marks_redeployed_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = _make_client(tmp_path)
        (project / ".claude" / "hooks" / STUB).write_text(CONFLICTED)
        _run(project)
        assert f"REDEPLOYED .claude/hooks/{STUB}" in capsys.readouterr().out

    def test_missing_template_directory_fails_fast(self, tmp_path: Path) -> None:
        project = _make_client(tmp_path)
        shutil.rmtree(project / ".claude" / "hooks-daemon" / ".claude" / "hooks")
        assert _run(project) == 1


class TestCheckMode:
    """``--check`` reports and never writes."""

    def test_check_does_not_write_and_exits_one_on_a_broken_stub(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = _make_client(tmp_path)
        stub = project / ".claude" / "hooks" / STUB
        stub.write_text(CONFLICTED)
        assert _run(project, check=True) == 1
        assert stub.read_text() == CONFLICTED
        out = capsys.readouterr().out
        assert f"BROKEN .claude/hooks/{STUB}" in out
        assert f"WOULD REDEPLOY .claude/hooks/{STUB}" in out

    def test_check_exits_zero_on_a_healthy_install(self, tmp_path: Path) -> None:
        project = _make_client(tmp_path)
        assert _run(project) == 0
        assert _run(project, check=True) == 0

    def test_check_exits_one_when_a_stub_is_stale_but_parses(self, tmp_path: Path) -> None:
        project = _make_client(tmp_path)
        (project / ".claude" / "hooks" / STUB).write_text("#!/bin/bash\nexit 0\n")
        assert _run(project, check=True) == 1


class TestSettings:
    """settings.json is checked, never rewritten without the explicit flag."""

    def test_valid_settings_reported_ok(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = _make_client(tmp_path)
        _run(project)
        assert "OK .claude/settings.json" in capsys.readouterr().out

    def test_invalid_json_exits_nonzero_and_is_not_modified(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = _make_client(tmp_path)
        settings = project / ".claude" / "settings.json"
        settings.write_text("{not json")
        assert _run(project) == 1
        assert settings.read_text() == "{not json"
        assert "BROKEN .claude/settings.json" in capsys.readouterr().out

    def test_conflict_marked_settings_never_overwritten_even_with_reconcile(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = _make_client(tmp_path)
        settings = project / ".claude" / "settings.json"
        settings.write_text('<<<<<<< HEAD\n{"hooks": {}}\n=======\n{"hooks": {}}\n>>>>>>> x\n')
        before = settings.read_text()
        assert _run(project, reconcile=True) == 1
        assert settings.read_text() == before
        out = capsys.readouterr().out
        assert "conflict" in out.lower()
        assert "by hand" in out

    def test_without_the_flag_settings_are_never_reconciled(self, tmp_path: Path) -> None:
        project = _make_client(tmp_path)
        settings = project / ".claude" / "settings.json"
        before = settings.read_text()
        _run(project)
        assert settings.read_text() == before

    def test_with_the_flag_missing_registrations_are_added(self, tmp_path: Path) -> None:
        project = _make_client(tmp_path)
        assert _run(project, reconcile=True) == 0
        on_disk = json.loads((project / ".claude" / "settings.json").read_text())
        assert set(on_disk["hooks"]) == set(HOOK_EVENTS_IN_SETTINGS)

    def test_check_with_the_flag_does_not_write(self, tmp_path: Path) -> None:
        project = _make_client(tmp_path)
        settings = project / ".claude" / "settings.json"
        before = settings.read_text()
        _run(project, check=True, reconcile=True)
        assert settings.read_text() == before

    def test_missing_settings_is_reported_broken(self, tmp_path: Path) -> None:
        project = _make_client(tmp_path)
        (project / ".claude" / "settings.json").unlink()
        assert _run(project) == 1


class TestLibrary:
    """The library function behind the verb."""

    def test_report_is_clean_after_repair(self, tmp_path: Path) -> None:
        project = _make_client(tmp_path)
        (project / ".claude" / "init.sh").write_text(CONFLICTED)
        report = repair_install(project, check=False)
        assert report.broken == []
        assert ".claude/init.sh" in report.redeployed

    def test_report_lists_broken_in_check_mode(self, tmp_path: Path) -> None:
        project = _make_client(tmp_path)
        (project / ".claude" / "init.sh").write_text(CONFLICTED)
        report = repair_install(project, check=True)
        assert ".claude/init.sh" in report.broken

    def test_self_install_hooks_are_checked_not_rewritten(self, tmp_path: Path) -> None:
        project = tmp_path / "self"
        shutil.copytree(REPO_ROOT / ".claude" / "hooks", project / ".claude" / "hooks")
        shutil.copy(REPO_ROOT / "init.sh", project / "init.sh")
        (project / ".claude" / "init.sh").symlink_to(project / "init.sh")
        (project / ".claude" / "settings.json").write_text("{}")
        (project / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
        report = repair_install(project, check=False)
        assert report.redeployed == []
