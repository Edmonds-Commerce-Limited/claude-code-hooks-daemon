"""A raw clone of this repository heals itself with no human step (Plan 00488 Task 3.4).

``.claude/hooks-daemon.env`` is gitignored, so a fresh ``git clone`` of the
daemon's own repository has none. init.sh used to look for the daemon in
``.claude/hooks-daemon/`` (a client layout), find nothing, and answer "Not
installed, use the skill to install" -- wrong advice here, and it never reached
the venv self-heal. A checkout that IS the daemon's source tree now derives the
root the env file would have supplied (the project itself) and reaches the
self-heal, which builds the venv in the background.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.venv_bootstrap_sandbox import (
    BASH,
    REPO_ROOT,
    Sandbox,
    assert_never_suggests_install_or_force,
)

GITHUB_REMOTE = "https://github.com/example/claude-code-hooks-daemon.git"


def _make_self_install_clone(box: Sandbox) -> None:
    """Re-lay the sandbox as this repository's own source tree, with no env file."""
    for child in box.clone.iterdir():
        shutil.move(str(child), str(box.project / child.name))
    shutil.rmtree(box.clone)
    box.clone = box.project
    (box.project / "install.py").write_text("# the client installer\n")
    (box.project / "pyproject.toml").write_text(
        '[project]\nname = "claude-code-hooks-daemon"\nversion = "3.61.0"\n'
        'requires-python = ">=3.11"\n'
    )
    script = box.project / "scripts" / "bootstrap-self-install.sh"
    shutil.copy2(REPO_ROOT / "scripts" / "bootstrap-self-install.sh", script)
    git = shutil.which("git")
    assert git is not None
    (box.root / "tools" / "git").symlink_to(git)
    subprocess.run([git, "init", "-q", str(box.project)], check=True)
    subprocess.run(
        [git, "-C", str(box.project), "remote", "add", "origin", GITHUB_REMOTE], check=True
    )


@pytest.fixture
def clone(tmp_path: Path) -> Iterator[Sandbox]:
    box = Sandbox(tmp_path)
    _make_self_install_clone(box)
    yield box
    box.cleanup()


def _context(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 0, result.stderr
    return str(json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"])


def _root_dir_after_sourcing(box: Sandbox, extra_env: dict[str, str] | None = None) -> str:
    """The daemon root init.sh settled on (an EXIT trap, since its guards may exit)."""
    init_sh = box.project / ".claude" / "init.sh"
    script = (
        "trap 'echo \"ROOT=$HOOKS_DAEMON_ROOT_DIR\"' EXIT\n"
        f'source "{init_sh}" > /dev/null 2>&1\n'
    )
    return box.run([BASH, "-c", script], extra_env=extra_env).stdout.strip()


class TestARawSelfInstallClone:
    def test_builds_its_venv_with_no_env_file_and_says_so(self, clone: Sandbox) -> None:
        clone.stub_uv(sleep=2)
        assert not (clone.project / ".claude" / "hooks-daemon.env").exists()

        context = _context(clone.hook())

        assert "build has started" in context.lower(), context
        assert "bootstrap-self-install" not in context, context
        assert_never_suggests_install_or_force(context)
        assert "not installed" not in context.lower(), context
        clone.wait_for_build()
        assert len(clone.uv_calls()) == 1
        assert f"target={clone.project}/untracked/venv-" in clone.uv_calls()[0]

    def test_the_next_hook_starts_the_daemon(self, clone: Sandbox) -> None:
        clone.stub_uv()
        clone.hook()
        clone.wait_for_build()

        assert "ENSURE_DAEMON_OK" in clone.hook().stdout

    def test_writes_nothing_outside_the_untracked_runtime(self, clone: Sandbox) -> None:
        clone.stub_uv()
        clone.hook()
        clone.wait_for_build()

        assert not (clone.project / ".claude" / "hooks-daemon.env").exists()
        assert not (clone.project / ".claude" / "hooks-daemon").exists()

    def test_the_status_line_says_building_not_failed(self, clone: Sandbox) -> None:
        clone.stub_uv(sleep=2)
        init_sh = clone.project / ".claude" / "init.sh"

        result = clone.run(
            [
                BASH,
                "-c",
                f'source "{init_sh}"\n'
                "_is_ci_environment() { return 1; }\n_is_ci_enforced() { return 1; }\n"
                'ensure_daemon || echo "TEXT=$_HOOKS_DAEMON_STATUS_DOWN_TEXT"',
            ]
        )

        assert "TEXT=⏳ HOOKS DAEMON VENV BUILDING" in result.stdout, result.stdout + result.stderr
        clone.wait_for_build()

    def test_without_uv_it_names_the_missing_condition_and_changes_nothing(
        self, clone: Sandbox
    ) -> None:
        context = _context(clone.hook())

        assert "uv:" in context, context
        assert clone.uv_calls() == []
        assert_never_suggests_install_or_force(context)


class TestTheDerivationNeverMisfires:
    def test_a_client_project_keeps_its_own_clone_root(self, tmp_path: Path) -> None:
        box = Sandbox(tmp_path)
        try:
            assert _root_dir_after_sourcing(box) == f"ROOT={box.clone}"
        finally:
            box.cleanup()

    def test_a_client_project_that_vendors_the_source_tree_keeps_its_clone(
        self, clone: Sandbox
    ) -> None:
        """A real clone under .claude/hooks-daemon outranks the markers at the root."""
        vendored = clone.project / ".claude" / "hooks-daemon"
        vendored.mkdir()
        (vendored / "pyproject.toml").write_text("[project]\nname = 'x'\n")

        assert _root_dir_after_sourcing(clone) == f"ROOT={vendored}"

    @pytest.mark.parametrize(
        "marker",
        [
            "install.py",
            "scripts/bootstrap-self-install.sh",
            "scripts/venv_bootstrap.sh",
            "src/claude_code_hooks_daemon",
        ],
    )
    def test_a_tree_missing_one_of_this_projects_markers_is_not_derived(
        self, clone: Sandbox, marker: str
    ) -> None:
        target = clone.project / marker
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

        assert _root_dir_after_sourcing(clone) == f"ROOT={clone.project}/.claude/hooks-daemon"

    def test_a_different_project_with_the_same_directory_name_is_not_derived(
        self, clone: Sandbox
    ) -> None:
        (clone.project / "pyproject.toml").write_text('[project]\nname = "someone-elses-app"\n')

        assert _root_dir_after_sourcing(clone) == f"ROOT={clone.project}/.claude/hooks-daemon"

    def test_an_explicit_root_from_the_environment_wins(self, clone: Sandbox) -> None:
        root = _root_dir_after_sourcing(clone, {"HOOKS_DAEMON_ROOT_DIR": "/custom/root"})
        assert root == "ROOT=/custom/root"
