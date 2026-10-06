"""Plan 00477 Phase 2 - ``.claude/provision.sh`` provisions a fresh clone.

A fresh checkout of a project that uses the daemon carries the tracked assets
but not the gitignored daemon clone. ``provision.sh`` (tracked, so it exists
before the daemon does) clones the TAG the project's config names, builds the
venv through the existing venv-build path, and starts the daemon, without
writing a tracked file.

The fixture reuses ``tests/venv_bootstrap_sandbox.py`` (a stub ``uv`` builds the
venv; a stand-in daemon binds the socket). The clone source is a local bare
repository holding two tags, reached through git's own ``url.<base>.insteadOf``
rewrite of the trusted URL: the script never reads its clone URL from the
environment, so there is no seam in the script for a test to use.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.venv_bootstrap_sandbox import CLONE_VERSION, Sandbox, snapshot

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVISION_SH = REPO_ROOT / "provision.sh"
INSTALL_SH = REPO_ROOT / "install.sh"

#: The tag main's HEAD carries. A provision that follows ``main`` lands here.
MAIN_VERSION = "9.9.9"
#: A tag whose commit's version.py names some OTHER version.
LYING_TAG_VERSION = "3.70.0"

HEADER = f"> Generated on 2026-09-01 (v{CLONE_VERSION}) by the hooks daemon\n"

SETTINGS_WITH_HOOKS = (
    '{"hooks": {"PreToolUse": [{"hooks": [{"type": "command", '
    '"command": "$CLAUDE_PROJECT_DIR/.claude/hooks/pre-tool-use"}]}]}}\n'
)

_GIT_IDENTITY = ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid"]


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *_GIT_IDENTITY, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _trusted_url() -> str:
    match = re.search(r'^DAEMON_REPO="([^"]+)"', INSTALL_SH.read_text(), re.MULTILINE)
    assert match is not None, "install.sh no longer declares DAEMON_REPO"
    return match.group(1)


class Provisioning:
    """A configured project with no daemon clone, and a local origin to provision from."""

    def __init__(self, tmp_path: Path, config: str | None, header: str | None = HEADER) -> None:
        self.box = Sandbox(tmp_path)
        self.project = self.box.project
        self.origin = tmp_path / "origin.git"
        self._build_origin(tmp_path)
        self._build_project(config, header)
        self._link_git(tmp_path)

    def _build_origin(self, tmp_path: Path) -> None:
        source = tmp_path / "origin-src"
        shutil.copytree(self.box.clone, source)
        shutil.rmtree(self.box.clone)
        _git(source, "init", "-q", "-b", "main")
        _git(source, "add", "-A")
        _git(source, "commit", "-q", "-m", f"release {CLONE_VERSION}")
        _git(source, "tag", f"v{CLONE_VERSION}")
        _git(source, "tag", f"v{LYING_TAG_VERSION}")
        version_py = source / "src" / "claude_code_hooks_daemon" / "version.py"
        version_py.write_text(f'__version__ = "{MAIN_VERSION}"\n')
        _git(source, "commit", "-q", "-am", "main moves on")
        _git(source, "tag", f"v{MAIN_VERSION}")
        _git(tmp_path, "clone", "-q", "--bare", str(source), str(self.origin))

    def _build_project(self, config: str | None, header: str | None) -> None:
        claude = self.project / ".claude"
        shutil.copy2(PROVISION_SH, claude / "provision.sh")
        (claude / ".gitignore").write_text("hooks-daemon/\n")
        (claude / "settings.json").write_text(SETTINGS_WITH_HOOKS)
        if config is not None:
            (claude / "hooks-daemon.yaml").write_text(config)
        if header is not None:
            (claude / "HOOKS-DAEMON.md").write_text(f"# Hooks Daemon\n\n{header}")
        _git(self.project, "init", "-q", "-b", "main")
        _git(self.project, "add", "-A")
        _git(self.project, "commit", "-q", "-m", "tracked assets")

    def _link_git(self, tmp_path: Path) -> None:
        """The sandbox PATH holds a fixed tool set; provisioning also needs git."""
        real = shutil.which("git")
        assert real is not None
        (self.box.root / "tools" / "git").symlink_to(real)
        gitconfig = tmp_path / "gitconfig"
        gitconfig.write_text(
            f'[url "file://{self.origin}"]\n\tinsteadOf = {_trusted_url()}\n'
            '[protocol "file"]\n\tallow = always\n'
        )
        self.git_env = {"GIT_CONFIG_GLOBAL": str(gitconfig), "GIT_CONFIG_NOSYSTEM": "1"}

    @property
    def clone(self) -> Path:
        return self.box.clone

    def provision(
        self, extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        self.box.stub_uv()
        return self.box.run(
            ["bash", str(self.project / ".claude" / "provision.sh")],
            extra_env={**self.git_env, **(extra_env or {})},
        )

    def tracked_changes(self) -> str:
        return _git(self.project, "status", "--porcelain")

    def clone_version(self) -> str:
        text = (self.clone / "src" / "claude_code_hooks_daemon" / "version.py").read_text()
        match = re.search(r'__version__ = "([^"]+)"', text)
        assert match is not None
        return match.group(1)


def _configured(version: str) -> str:
    return f'version: "2.0"\ndaemon:\n  expected_version: "{version}"\n  log_level: INFO\n'


@pytest.fixture
def fresh(tmp_path: Path) -> Iterator[Provisioning]:
    p = Provisioning(tmp_path, _configured(CLONE_VERSION))
    yield p
    p.box.cleanup()


def _make(tmp_path: Path, config: str | None, header: str | None = HEADER) -> Provisioning:
    return Provisioning(tmp_path, config, header)


class TestProvisioning:
    def test_installs_exactly_the_tag_the_config_names_never_main(
        self, fresh: Provisioning
    ) -> None:
        result = fresh.provision()

        assert result.returncode == 0, result.stdout + result.stderr
        assert fresh.clone_version() == CLONE_VERSION != MAIN_VERSION
        described = _git(fresh.clone, "describe", "--tags", "--exact-match").strip()
        assert described == f"v{CLONE_VERSION}"
        assert (fresh.clone / ".git" / "shallow").exists(), "a full-history clone was taken"

    def test_builds_the_venv_and_starts_the_daemon(self, fresh: Provisioning) -> None:
        result = fresh.provision()

        assert result.returncode == 0, result.stdout + result.stderr
        assert fresh.box.resolves()
        assert len(fresh.box.uv_calls()) == 1
        assert len(fresh.box.start_log.read_text().splitlines()) == 1
        assert fresh.box.socket.exists()

    def test_says_no_session_restart_is_needed(self, fresh: Provisioning) -> None:
        result = fresh.provision()

        out = result.stdout + result.stderr
        assert CLONE_VERSION in out
        assert "no session restart" in out.lower()
        assert "restart your session" not in out.lower()

    def test_does_not_claim_no_restart_is_needed_when_settings_register_no_hooks(
        self, fresh: Provisioning
    ) -> None:
        (fresh.project / ".claude" / "settings.json").write_text("{}\n")
        _git(fresh.project, "commit", "-q", "-am", "settings without hooks")

        result = fresh.provision()

        out = result.stdout + result.stderr
        assert result.returncode == 0, out
        assert "does not register the hooks" in out
        assert "no session restart" not in out.lower()

    def test_the_next_hook_finds_the_daemon_already_running(self, fresh: Provisioning) -> None:
        assert fresh.provision().returncode == 0

        hook = fresh.box.hook()

        assert "ENSURE_DAEMON_OK" in hook.stdout, hook.stdout + hook.stderr
        assert len(fresh.box.start_log.read_text().splitlines()) == 1, "a second start was needed"

    def test_writes_no_tracked_file(self, fresh: Provisioning) -> None:
        assert fresh.tracked_changes() == ""

        result = fresh.provision()

        assert result.returncode == 0, result.stdout + result.stderr
        assert fresh.tracked_changes() == ""

    def test_falls_back_to_the_header_for_a_project_that_predates_the_key(
        self, tmp_path: Path
    ) -> None:
        p = _make(tmp_path, 'version: "2.0"\ndaemon:\n  log_level: INFO\n')
        try:
            result = p.provision()

            assert result.returncode == 0, result.stdout + result.stderr
            assert p.clone_version() == CLONE_VERSION
        finally:
            p.box.cleanup()

    def test_ignores_every_environment_variable_that_could_name_another_source(
        self, fresh: Provisioning
    ) -> None:
        result = fresh.provision(
            {
                "DAEMON_REPO": "file:///nonexistent/evil.git",
                "DAEMON_BRANCH": "main",
                "HOOKS_DAEMON_CLONE_URL": "file:///nonexistent/evil.git",
                "HOOKS_DAEMON_EXPECTED_VERSION": MAIN_VERSION,
            }
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert fresh.clone_version() == CLONE_VERSION

    def test_the_clone_url_is_the_one_the_installer_trusts(self) -> None:
        script = PROVISION_SH.read_text()

        assert f'"{_trusted_url()}"' in script


class TestRefusals:
    def test_refuses_when_the_version_is_unknown_and_changes_nothing(self, tmp_path: Path) -> None:
        p = _make(tmp_path, "daemon:\n  log_level: INFO\n", header=None)
        try:
            result = p.provision()

            out = result.stdout + result.stderr
            assert result.returncode != 0
            assert "unknown" in out.lower()
            assert "expected_version" in out
            assert not (p.clone / ".git").exists()
            assert p.tracked_changes() == ""
        finally:
            p.box.cleanup()

    @pytest.mark.parametrize(
        "bad", ["main", "3.61", "v3.61.0", "3.61.0-rc1", "3.61.0 --upload-pack=x", "$(id)"]
    )
    def test_refuses_a_version_that_is_not_x_y_z(self, tmp_path: Path, bad: str) -> None:
        p = _make(tmp_path, f'daemon:\n  expected_version: "{bad}"\n')
        try:
            result = p.provision()

            out = result.stdout + result.stderr
            assert result.returncode != 0
            assert "X.Y.Z" in out
            assert not (p.clone / ".git").exists()
            assert p.box.uv_calls() == []
        finally:
            p.box.cleanup()

    def test_refuses_and_points_at_upgrade_when_a_provisioned_clone_exists(
        self, fresh: Provisioning
    ) -> None:
        assert fresh.provision().returncode == 0
        before = snapshot(fresh.clone)

        result = fresh.provision()

        out = result.stdout + result.stderr
        assert result.returncode != 0
        assert "upgrade" in out
        assert snapshot(fresh.clone) == before

    def test_refuses_and_points_at_repair_when_a_clone_has_no_venv_for_this_path(
        self, fresh: Provisioning
    ) -> None:
        assert fresh.provision().returncode == 0
        for venv in (fresh.clone / "untracked").glob("venv-*"):
            shutil.rmtree(venv)
        before = snapshot(fresh.clone)

        result = fresh.provision()

        out = result.stdout + result.stderr
        assert result.returncode != 0
        assert "repair" in out
        assert snapshot(fresh.clone) == before

    def test_a_tag_that_does_not_exist_fails_with_the_tag_named_and_leaves_no_clone(
        self, tmp_path: Path
    ) -> None:
        p = _make(tmp_path, _configured("3.99.99"))
        try:
            result = p.provision()

            out = result.stdout + result.stderr
            assert result.returncode != 0
            assert "v3.99.99" in out
            assert not (p.clone / ".git").exists()
            assert p.tracked_changes() == ""
        finally:
            p.box.cleanup()

    def test_a_tag_whose_source_names_another_version_is_refused_and_removed(
        self, tmp_path: Path
    ) -> None:
        p = _make(tmp_path, _configured(LYING_TAG_VERSION))
        try:
            result = p.provision()

            out = result.stdout + result.stderr
            assert result.returncode != 0
            assert LYING_TAG_VERSION in out and CLONE_VERSION in out
            assert not (p.clone / ".git").exists()
            assert not (p.clone / "src").exists()
            assert p.box.uv_calls() == []
        finally:
            p.box.cleanup()

    def test_refuses_inside_the_daemons_own_repository(self, tmp_path: Path) -> None:
        p = _make(tmp_path, _configured(CLONE_VERSION))
        try:
            version_py = p.project / "src" / "claude_code_hooks_daemon" / "version.py"
            version_py.parent.mkdir(parents=True)
            version_py.write_text(f'__version__ = "{CLONE_VERSION}"\n')

            result = p.provision()

            out = result.stdout + result.stderr
            assert result.returncode != 0
            assert "bootstrap-self-install" in out
            assert not (p.clone / ".git").exists()
        finally:
            p.box.cleanup()

    def test_a_failed_venv_build_keeps_the_clone_and_names_repair(
        self, fresh: Provisioning
    ) -> None:
        fresh.box.stub_uv(fail=True)
        result = fresh.box.run(
            ["bash", str(fresh.project / ".claude" / "provision.sh")], extra_env=fresh.git_env
        )

        out = result.stdout + result.stderr
        assert result.returncode != 0
        assert (fresh.clone / ".git").exists()
        assert "repair" in out
        assert fresh.tracked_changes() == ""
