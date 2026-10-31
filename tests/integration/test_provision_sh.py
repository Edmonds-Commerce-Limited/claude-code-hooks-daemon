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

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import psutil
import pytest

from claude_code_hooks_daemon.config.models import TransportConfig
from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint
from claude_code_hooks_daemon.install.background_sync import SYNC_STATE_DIR_NAME
from claude_code_hooks_daemon.install.forwarder_generator import (
    INIT_SH_ANCHOR,
    generate_forwarder_content,
)
from claude_code_hooks_daemon.utils.safe_signal import DaemonStop, stop_verified_daemon
from tests.venv_bootstrap_sandbox import (
    BASH,
    CLONE_VERSION,
    TIMEOUT_SECONDS,
    UV_CONSOLE_SCRIPT,
    UV_EDITABLE_PTH,
    UV_EMBEDDED_PATH_FILES,
    UV_SITE_PACKAGES,
    Sandbox,
    snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVISION_SH = REPO_ROOT / "provision.sh"
INSTALL_SH = REPO_ROOT / "install.sh"

#: The tag main's HEAD carries. A provision that follows ``main`` lands here.
MAIN_VERSION = "9.9.9"
#: A tag whose commit's version.py names some OTHER version.
LYING_TAG_VERSION = "3.70.0"
#: A release that carries the pre-deploy gate and an upgrade guide for 3.61.0 -> 3.62.0.
GATED_VERSION = "3.62.0"
GUIDE_NAME = f"v{CLONE_VERSION}-to-v{GATED_VERSION}"
#: What a release needs for ``upgrade_gate_standalone.py`` to run from its own tree.
GATE_FILES = (
    "scripts/install/env_sanitise.sh",
    "src/claude_code_hooks_daemon/install/upgrade_gate_standalone.py",
    "src/claude_code_hooks_daemon/install/upgrade_gate.py",
    "src/claude_code_hooks_daemon/install/upgrade_guides.py",
    "src/claude_code_hooks_daemon/install/upgrade_tasks.py",
    "src/claude_code_hooks_daemon/install/version_parse.py",
    "src/claude_code_hooks_daemon/install/install_stamp.py",
    "src/claude_code_hooks_daemon/utils/path_containment.py",
    "src/claude_code_hooks_daemon/utils/path_predicates.py",
    "src/claude_code_hooks_daemon/utils/escape_hatch.py",
    "src/claude_code_hooks_daemon/utils/deliberate_swallow.py",
)

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
        (source / ".gitignore").write_text("untracked/\n__pycache__/\n")
        _git(source, "init", "-q", "-b", "main")
        _git(source, "add", "-A")
        _git(source, "commit", "-q", "-m", f"release {CLONE_VERSION}")
        _git(source, "tag", f"v{CLONE_VERSION}")
        _git(source, "tag", f"v{LYING_TAG_VERSION}")
        self._commit_gated_release(source)
        version_py = source / "src" / "claude_code_hooks_daemon" / "version.py"
        version_py.write_text(f'__version__ = "{MAIN_VERSION}"\n')
        (source / "uv.lock").write_text("# lock v2\n")
        _git(source, "commit", "-q", "-am", "main moves on")
        _git(source, "tag", f"v{MAIN_VERSION}")
        _git(tmp_path, "clone", "-q", "--bare", str(source), str(self.origin))

    @staticmethod
    def _commit_gated_release(source: Path) -> None:
        """Tag a release that carries the pre-deploy gate and a guide for 3.61.0 -> 3.62.0."""
        _git(source, "checkout", "-q", "-b", "gated")
        for rel in GATE_FILES:
            dest = source / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / rel, dest)
        guide = source / "CLAUDE" / "UPGRADES" / "v3" / GUIDE_NAME / f"{GUIDE_NAME}.md"
        guide.parent.mkdir(parents=True)
        guide.write_text("# 3.61.0 to 3.62.0\n\nRead this before upgrading.\n")
        version_py = source / "src" / "claude_code_hooks_daemon" / "version.py"
        version_py.write_text(f'__version__ = "{GATED_VERSION}"\n')
        _git(source, "add", "-A")
        _git(source, "commit", "-q", "-m", f"release {GATED_VERSION}")
        _git(source, "tag", f"v{GATED_VERSION}")
        _git(source, "checkout", "-q", "main")

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
        self,
        extra_env: dict[str, str] | None = None,
        *,
        args: tuple[str, ...] = (),
        uv_fails: bool = False,
        uv_wrapper: str | None = None,
        cli_hook: str | None = None,
        binary_pth: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        self.box.stub_uv(fail=uv_fails, embed_build_paths=True, binary_pth=binary_pth)
        if uv_wrapper is not None:
            self._wrap_uv(uv_wrapper)
        hook_env = {} if cli_hook is None else {"SANDBOX_CLI_HOOK": cli_hook}
        return self.box.run(
            ["bash", str(self.project / ".claude" / "provision.sh"), *args],
            extra_env={**self.git_env, **hook_env, **(extra_env or {})},
        )

    def _wrap_uv(self, body: str) -> None:
        """Run ``body`` (bash) before every stub ``uv`` build, then the stub itself."""
        stub = self.box.root / "uv-stub" / "uv"
        real = stub.with_name("uv-real")
        stub.rename(real)
        stub.write_text(f'#!/bin/bash\n{body}\nexec "{real}" "$@"\n')
        stub.chmod(0o755)

    def expect(self, version: str) -> None:
        """Change the version the project's config names, as a pull would."""
        (self.project / ".claude" / "hooks-daemon.yaml").write_text(_configured(version))
        _git(self.project, "commit", "-q", "--allow-empty", "-am", f"expect {version}")

    def head(self) -> str:
        return _git(self.clone, "rev-parse", "HEAD").strip()

    def clone_tracked_state(self) -> str:
        """HEAD and the clone's own status: what a refused or rolled-back sync leaves."""
        return self.head() + _git(self.clone, "status", "--porcelain", "--", ".", ":!untracked")

    def starts(self) -> int:
        return len(self.box.start_log.read_text().splitlines())

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


def _provisioned_at(p: Provisioning, version: str) -> None:
    p.expect(version)
    result = p.provision()
    assert result.returncode == 0, result.stdout + result.stderr
    assert p.clone_version() == version


def _out(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


class TestAnExistingCloneAtTheExpectedVersion:
    def test_says_so_and_exits_zero_without_touching_the_clone(self, fresh: Provisioning) -> None:
        assert fresh.provision().returncode == 0
        before = snapshot(fresh.clone)

        result = fresh.provision()

        assert result.returncode == 0, _out(result)
        assert f"already at v{CLONE_VERSION}" in _out(result)
        assert snapshot(fresh.clone) == before
        assert fresh.starts() == 1, "an equal version must not restart the daemon"


class TestSyncingAnExistingClone:
    def test_a_clean_clone_syncs_to_a_newer_tag(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        before = fresh.head()
        fresh.expect(MAIN_VERSION)

        result = fresh.provision()

        out = _out(result)
        assert result.returncode == 0, out
        assert fresh.clone_version() == MAIN_VERSION
        assert fresh.head() != before
        described = _git(fresh.clone, "describe", "--tags", "--exact-match").strip()
        assert described == f"v{MAIN_VERSION}"
        assert fresh.box.resolves()
        assert fresh.starts() == 2, "the daemon was restarted exactly once by the sync"
        assert fresh.tracked_changes() == ""
        assert list((fresh.clone / "untracked").glob(".sync-backup-*")) == []
        assert f"v{CLONE_VERSION}" in out and f"v{MAIN_VERSION}" in out

    def test_a_clean_clone_syncs_to_an_older_tag(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, MAIN_VERSION)
        fresh.expect(CLONE_VERSION)

        result = fresh.provision()

        assert result.returncode == 0, _out(result)
        assert fresh.clone_version() == CLONE_VERSION
        described = _git(fresh.clone, "describe", "--tags", "--exact-match").strip()
        assert described == f"v{CLONE_VERSION}"
        assert fresh.tracked_changes() == ""

    def test_gitignored_files_do_not_block_a_sync(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        cache = fresh.clone / "src" / "__pycache__"
        cache.mkdir(parents=True)
        (cache / "x.pyc").write_bytes(b"\0")
        fresh.expect(MAIN_VERSION)

        result = fresh.provision()

        assert result.returncode == 0, _out(result)
        assert fresh.clone_version() == MAIN_VERSION

    def test_the_url_is_still_the_fixed_one_whatever_the_environment_says(
        self, fresh: Provisioning
    ) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect(MAIN_VERSION)

        result = fresh.provision(
            {
                "DAEMON_REPO": "file:///nonexistent/evil.git",
                "HOOKS_DAEMON_CLONE_URL": "file:///nonexistent/evil.git",
            }
        )

        assert result.returncode == 0, _out(result)
        assert fresh.clone_version() == MAIN_VERSION

    def test_a_bare_tag_ref_is_fetched_and_nothing_else(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect(MAIN_VERSION)
        assert fresh.provision().returncode == 0

        branches = _git(fresh.clone, "branch", "--list", "--all").strip()
        assert "main" not in branches and "gated" not in branches


class TestASyncRefusesAndChangesNothing:
    @pytest.mark.parametrize("damage", ["tracked-edit", "untracked-file"])
    def test_a_modified_clone_is_refused(self, fresh: Provisioning, damage: str) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        if damage == "tracked-edit":
            (fresh.clone / "pyproject.toml").write_text("# local edit\n")
        else:
            (fresh.clone / "stray.txt").write_text("mine\n")
        fresh.expect(MAIN_VERSION)
        before = fresh.clone_tracked_state()
        starts = fresh.starts()

        result = fresh.provision()

        out = _out(result)
        assert result.returncode != 0
        assert "local changes" in out
        assert "upgrade" in out, "the refusal names the manual route"
        assert fresh.clone_tracked_state() == before
        assert fresh.clone_version() == CLONE_VERSION
        assert fresh.starts() == starts

    def test_a_foreign_origin_is_refused(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        _git(fresh.clone, "remote", "set-url", "origin", "https://example.invalid/evil.git")
        fresh.expect(MAIN_VERSION)
        before = fresh.head()

        result = fresh.provision()

        out = _out(result)
        assert result.returncode != 0
        assert "origin" in out and "example.invalid" in out
        assert fresh.head() == before
        assert fresh.clone_version() == CLONE_VERSION

    def test_a_clone_that_is_not_a_git_checkout_is_refused(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        shutil.rmtree(fresh.clone / ".git")
        fresh.expect(MAIN_VERSION)

        result = fresh.provision()

        assert result.returncode != 0
        assert "not a git checkout" in _out(result)
        assert fresh.clone_version() == CLONE_VERSION
        assert not (fresh.clone / ".git").exists()

    def test_a_tag_whose_version_py_disagrees_aborts_before_checkout(
        self, fresh: Provisioning
    ) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect(LYING_TAG_VERSION)
        before = fresh.clone_tracked_state()
        tags_before = _git(fresh.clone, "tag", "--list")
        starts = fresh.starts()

        result = fresh.provision()

        out = _out(result)
        assert result.returncode != 0
        assert LYING_TAG_VERSION in out and CLONE_VERSION in out
        assert fresh.clone_tracked_state() == before
        assert fresh.starts() == starts
        assert _git(fresh.clone, "tag", "--list") == tags_before

    def test_an_unreleased_tag_leaves_the_clone_as_it_was(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect("3.99.99")
        before = fresh.clone_tracked_state()

        result = fresh.provision()

        assert result.returncode != 0
        assert "v3.99.99" in _out(result)
        assert fresh.clone_tracked_state() == before

    def test_an_unknown_argument_is_refused(self, fresh: Provisioning) -> None:
        result = fresh.provision(args=("--force",))

        assert result.returncode != 0
        assert "--force" in _out(result)
        assert not (fresh.clone / ".git").exists()


DIGEST = re.compile(r"--skip-reading-confirmation=(\S+)")


class TestTheTargetsPreDeployGate:
    def test_a_target_that_needs_reading_stops_with_nothing_changed(
        self, fresh: Provisioning
    ) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect(GATED_VERSION)
        before = fresh.clone_tracked_state()
        starts = fresh.starts()
        uv_calls = len(fresh.box.uv_calls())

        result = fresh.provision()

        out = _out(result)
        assert result.returncode != 0
        assert GUIDE_NAME in out, "the gate's listing is printed"
        assert DIGEST.search(out) is not None
        assert "bash .claude/provision.sh --skip-reading-confirmation=" in out
        assert fresh.clone_tracked_state() == before
        assert fresh.clone_version() == CLONE_VERSION
        assert fresh.starts() == starts
        assert len(fresh.box.uv_calls()) == uv_calls

    def test_the_digest_flag_lets_the_sync_proceed(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect(GATED_VERSION)
        stopped = fresh.provision()
        match = DIGEST.search(_out(stopped))
        assert match is not None, _out(stopped)

        result = fresh.provision(args=(f"--skip-reading-confirmation={match.group(1)}",))

        assert result.returncode == 0, _out(result)
        assert fresh.clone_version() == GATED_VERSION
        assert fresh.starts() == 2

    def test_a_wrong_digest_does_not_proceed(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect(GATED_VERSION)

        result = fresh.provision(args=("--skip-reading-confirmation=0000",))

        assert result.returncode != 0
        assert fresh.clone_version() == CLONE_VERSION

    def test_a_target_that_predates_the_gate_syncs_and_says_so(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect(MAIN_VERSION)

        result = fresh.provision()

        assert result.returncode == 0, _out(result)
        assert "predates the pre-deploy gate" in _out(result)


STAGE_DIR_NAME = "sync-stage"
PREVIOUS_DIR_NAME = "sync-previous"
SWITCH_MARKER_NAME = ".provision-switching"
#: What provision itself writes under the live clone while it syncs: the stage,
#: the background sync's record and the switch marker. Nothing else may change.
SYNC_OWN_PATHS = (
    f"untracked/{STAGE_DIR_NAME}",
    f"untracked/{SYNC_STATE_DIR_NAME}",
    f"untracked/{SWITCH_MARKER_NAME}",
    # Every venv build records its result and log here (.venv-bootstrap.result,
    # .venv-bootstrap-<fp>.log).
    "untracked/.venv-bootstrap",
)
#: A stand-in for the state the daemon keeps under its untracked/ directory.
DAEMON_STATE = "untracked/handler-state.json"
DAEMON_STATE_TEXT = '{"kept": true}\n'

#: Run in a subprocess by a wrapper: _live_state of argv[2], as JSON, into argv[3].
_SNAPSHOT_PROGRAM = (
    "import json, sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
    "from tests.venv_bootstrap_sandbox import snapshot; "
    "excluded = tuple(sys.argv[4:]); "
    "state = {k: v for k, v in snapshot(Path(sys.argv[2])).items() "
    "if not k.startswith(excluded)}; "
    "Path(sys.argv[3]).write_text(json.dumps(state))"
)


def _daemon_pid(p: Provisioning) -> int:
    return int(p.box.pid.read_text().strip())


def _live_state(clone: Path) -> dict[str, str]:
    """Every path of the live clone with its bytes, except what the sync itself writes."""
    return {k: v for k, v in snapshot(clone).items() if not k.startswith(SYNC_OWN_PATHS)}


def _record_live_state(p: Provisioning, out: Path) -> str:
    """A bash command that writes the live clone's _live_state to ``out`` as JSON.

    ``out`` is double-quoted, so a ``$$`` in it names the writing shell.
    """
    argv = [sys.executable, "-c", _SNAPSHOT_PROGRAM, str(REPO_ROOT), str(p.clone)]
    return f'{shlex.join(argv)} "{out}" {shlex.join(SYNC_OWN_PATHS)}'


def _aside(p: Provisioning) -> Path:
    """Where the old clone is renamed to for the instant of the swap."""
    return p.clone.with_name(p.clone.name + ".sync-previous")


def _no_switch_left(p: Provisioning) -> bool:
    untracked = p.clone / "untracked"
    return not any(
        path.exists()
        for path in (
            untracked / STAGE_DIR_NAME,
            untracked / PREVIOUS_DIR_NAME,
            untracked / SWITCH_MARKER_NAME,
            _aside(p),
        )
    )


def _with_daemon_state(p: Provisioning) -> Path:
    state = p.clone / DAEMON_STATE
    state.write_text(DAEMON_STATE_TEXT)
    return state


def _when_restarting_the_new_version(p: Provisioning, command: str) -> str:
    """A CLI hook that runs ``command`` when the daemon is restarted from the target."""
    version_py = p.clone / "src" / "claude_code_hooks_daemon" / "version.py"
    return (
        f'if [ "$1" = restart ] && grep -q \'"{MAIN_VERSION}"\' "{version_py}"; '
        f"then {command}; fi"
    )


class TestTheSwitchIsADirectorySwap:
    """The target is staged and built beside the live clone, then swapped in by rename."""

    def test_the_live_clone_is_byte_identical_while_the_target_is_built(
        self, fresh: Provisioning
    ) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        _with_daemon_state(fresh)
        old_daemon = _daemon_pid(fresh)
        fresh.expect(MAIN_VERSION)
        before = _live_state(fresh.clone)
        seen = fresh.box.root / "seen"
        seen.mkdir()
        during_build = (
            f'printf "%s\\n" "$UV_PROJECT_ENVIRONMENT" >> "{seen}/targets"\n'
            f'{_record_live_state(fresh, seen / "build-$$.json")}\n'
            f'if [ -d /proc/{old_daemon} ]; then echo up; else echo down; fi >> "{seen}/daemon"'
        )
        at_stop = f'if [ "$1" = stop ]; then {_record_live_state(fresh, seen / "stop.json")}; fi'

        result = fresh.provision(uv_wrapper=during_build, cli_hook=at_stop)

        assert result.returncode == 0, _out(result)
        builds = sorted(seen.glob("build-*.json"))
        assert builds, "the target was built"
        for build in builds:
            assert json.loads(build.read_text()) == before, "the live clone changed mid-build"
        assert json.loads((seen / "stop.json").read_text()) == before, "or before the stop"
        targets = (seen / "targets").read_text().splitlines()
        assert all(f"/{STAGE_DIR_NAME}/" in target for target in targets), "never built in place"
        assert set((seen / "daemon").read_text().split()) == {"up"}, "the old daemon served"
        assert fresh.clone_version() == MAIN_VERSION
        assert _no_switch_left(fresh)

    def test_the_staged_venv_is_moved_into_place_bound_to_the_live_path(
        self, fresh: Provisioning
    ) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect(MAIN_VERSION)
        stage = fresh.clone / "untracked" / STAGE_DIR_NAME
        builds_before = len(fresh.box.uv_calls())

        result = fresh.provision()

        assert result.returncode == 0, _out(result)
        assert len(fresh.box.uv_calls()) == builds_before + 1, "built once, in the stage"
        venv = fresh.clone / "untracked" / f"venv-{python_venv_fingerprint(fresh.clone)}"
        assert venv.is_dir(), "named for the live path, as the resolver looks for it"
        for rel in UV_EMBEDDED_PATH_FILES:
            assert str(stage) not in (venv / rel).read_text(), rel
        pth = venv / UV_SITE_PACKAGES / UV_EDITABLE_PTH
        assert pth.read_text() == f"{fresh.clone}/src\n"
        assert (venv / UV_CONSOLE_SCRIPT).read_text().startswith(f"#!{venv}/bin/python\n")
        metadata = json.loads((venv / ".daemon-metadata.json").read_text())
        assert metadata["python_path"] == f"{venv}/bin/python"
        assert metadata["fingerprint"] == python_venv_fingerprint(fresh.clone)
        assert fresh.box.resolves()

    def test_the_previous_copy_is_kept_until_the_new_daemon_answers(
        self, fresh: Provisioning
    ) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect(MAIN_VERSION)
        kept = fresh.box.root / "previous-at-restart"
        previous_version_py = (
            fresh.clone
            / "untracked"
            / PREVIOUS_DIR_NAME
            / "src/claude_code_hooks_daemon/version.py"
        )

        result = fresh.provision(
            cli_hook=_when_restarting_the_new_version(
                fresh, f'cat "{previous_version_py}" > "{kept}"'
            )
        )

        assert result.returncode == 0, _out(result)
        assert f'"{CLONE_VERSION}"' in kept.read_text(), "the old copy was there at the restart"
        assert fresh.clone_version() == MAIN_VERSION
        assert fresh.starts() == 2
        assert _no_switch_left(fresh), "and removed once the new daemon answered"

    def test_the_daemons_untracked_state_is_carried_across(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        state = _with_daemon_state(fresh)
        other_view = fresh.box.other_view_venv()
        other_view_before = snapshot(other_view)
        fresh.expect(MAIN_VERSION)

        result = fresh.provision()

        assert result.returncode == 0, _out(result)
        assert fresh.clone_version() == MAIN_VERSION
        assert state.read_text() == DAEMON_STATE_TEXT
        assert snapshot(other_view) == other_view_before

    def test_a_target_venv_that_cannot_be_built_never_stops_the_old_daemon(
        self, fresh: Provisioning
    ) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        before = _live_state(fresh.clone)
        old_daemon = _daemon_pid(fresh)
        fresh.expect(MAIN_VERSION)

        result = fresh.provision(uv_fails=True)

        out = _out(result)
        assert result.returncode != 0
        assert "venv" in out
        assert "never stopped" in out
        assert _live_state(fresh.clone) == before
        assert fresh.clone_version() == CLONE_VERSION
        assert fresh.box.resolves()
        assert fresh.starts() == 1, "nothing was restarted"
        assert psutil.pid_exists(old_daemon), "the old daemon is still the one running"
        assert fresh.tracked_changes() == ""
        assert _no_switch_left(fresh)

    def test_a_new_daemon_that_does_not_start_is_swapped_back(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        _with_daemon_state(fresh)
        before = _live_state(fresh.clone)
        fresh.expect(MAIN_VERSION)

        result = fresh.provision(
            cli_hook=_when_restarting_the_new_version(
                fresh, 'echo "simulated: the new daemon does not start" >&2; exit 1'
            )
        )

        out = _out(result)
        assert result.returncode != 0
        assert f"previous version v{CLONE_VERSION}" in out
        assert _live_state(fresh.clone) == before, "the old clone, venv and state are back"
        assert fresh.clone_version() == CLONE_VERSION
        assert fresh.box.resolves()
        assert fresh.starts() == 2, "the old daemon was started again"
        assert _no_switch_left(fresh)


#: A uv wrapper that fails every build outside the stage: the in-place rebuild.
FAIL_IN_PLACE_BUILDS = (
    f'case "$UV_PROJECT_ENVIRONMENT" in */{STAGE_DIR_NAME}/*) ;; '
    '*) echo "error: simulated failure of the in-place rebuild" >&2; exit 2 ;; esac'
)


def _in_place_builds(p: Provisioning) -> list[str]:
    return [call for call in p.box.uv_calls() if f"/{STAGE_DIR_NAME}/" not in call]


class TestARelocatedVenvThatFailsItsCheckIsRebuilt:
    """The relocated venv is checked before the new daemon starts; a failure rebuilds it."""

    def test_a_path_the_rebind_cannot_see_is_rebuilt_and_the_sync_completes(
        self, fresh: Provisioning
    ) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect(MAIN_VERSION)
        in_place_before = len(_in_place_builds(fresh))

        result = fresh.provision(args=BACKGROUND, binary_pth=True)

        assert result.returncode == 0, _out(result)
        assert fresh.clone_version() == MAIN_VERSION
        assert len(_in_place_builds(fresh)) == in_place_before + 1, "rebuilt in place, once"
        venv = fresh.clone / "untracked" / f"venv-{python_venv_fingerprint(fresh.clone)}"
        pth = venv / UV_SITE_PACKAGES / UV_EDITABLE_PTH
        assert pth.read_bytes().startswith(f"{fresh.clone}/src\n".encode())
        state = _state(fresh, MAIN_VERSION)
        assert state["status"] == "synced"
        assert "rebuilt" in state["detail"] and "Cannot import" in state["detail"]
        assert fresh.starts() == 2, "the new daemon was started once"
        assert _no_switch_left(fresh)

    def test_a_rebuild_that_fails_too_ends_on_the_old_version(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        _with_daemon_state(fresh)
        before = _live_state(fresh.clone)
        fresh.expect(MAIN_VERSION)

        result = fresh.provision(args=BACKGROUND, binary_pth=True, uv_wrapper=FAIL_IN_PLACE_BUILDS)

        assert result.returncode != 0
        assert fresh.clone_version() == CLONE_VERSION
        assert _live_state(fresh.clone) == before
        assert fresh.box.resolves()
        assert fresh.starts() == 2, "the new daemon never started; the old one was started again"
        state = _state(fresh, MAIN_VERSION)
        assert state["status"] == "failed"
        assert "rebuilding" in state["detail"] and "Cannot import" in state["detail"]
        assert _no_switch_left(fresh)


def _kill_provision(p: Provisioning) -> str:
    """Kill the provision that holds the switch marker, as a reboot would."""
    return f'kill -9 "$(cat "{p.clone}/untracked/{SWITCH_MARKER_NAME}")"'


def _interrupt_earlier(p: Provisioning, shape: str) -> None:
    """Turn the state a sync killed at the restart leaves into an earlier one.

    Each step undoes one rename of the swap, so each shape is exactly what a
    kill between those two renames leaves: the swap is old clone -> aside,
    stage -> live, aside -> untracked/sync-previous.
    """
    if shape == "swapped-unconfirmed":
        return
    # Before the restart, no daemon was running from the swapped-in clone.
    _stop_the_daemon(p)
    aside = _aside(p)
    (p.clone / "untracked" / PREVIOUS_DIR_NAME).rename(aside)
    if shape == "between-second-and-third-rename":
        return
    p.clone.rename(aside / "untracked" / STAGE_DIR_NAME)
    # A hook that ran in the gap re-creates the skeleton init.sh makes.
    (p.clone / "untracked").mkdir(parents=True)
    (p.clone / "untracked" / ".exec-bit-checked").touch()
    if shape == "between-first-and-second-rename":
        return
    shutil.rmtree(p.clone)
    aside.rename(p.clone)


class TestAnInterruptedSwitchIsRecoveredByTheNextRun:
    @pytest.mark.parametrize(
        "shape",
        [
            "swapped-unconfirmed",
            "between-second-and-third-rename",
            "between-first-and-second-rename",
            "carried-not-swapped",
        ],
    )
    def test_the_previous_version_is_put_back(self, fresh: Provisioning, shape: str) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        state = _with_daemon_state(fresh)
        before = _live_state(fresh.clone)
        fresh.expect(MAIN_VERSION)
        killed = fresh.provision(
            cli_hook=_when_restarting_the_new_version(fresh, _kill_provision(fresh))
        )
        assert killed.returncode < 0, _out(killed)
        assert (fresh.clone / "untracked" / PREVIOUS_DIR_NAME).is_dir()
        _interrupt_earlier(fresh, shape)
        fresh.expect(CLONE_VERSION)

        result = fresh.provision()

        out = _out(result)
        assert result.returncode == 0, out
        assert "RECOVERED" in out and f"v{CLONE_VERSION}" in out
        assert _live_state(fresh.clone) == before
        assert state.read_text() == DAEMON_STATE_TEXT
        assert fresh.box.resolves()
        assert _no_switch_left(fresh)

    def test_an_interrupted_sync_is_recovered_then_completed(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect(MAIN_VERSION)
        killed = fresh.provision(
            cli_hook=_when_restarting_the_new_version(fresh, _kill_provision(fresh))
        )
        assert killed.returncode < 0, _out(killed)

        result = fresh.provision()

        out = _out(result)
        assert result.returncode == 0, out
        assert "RECOVERED" in out and "SYNCED" in out
        assert fresh.clone_version() == MAIN_VERSION
        assert _no_switch_left(fresh)

    def test_an_interrupted_background_sync_is_recorded_and_not_retried(
        self, fresh: Provisioning
    ) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect(MAIN_VERSION)
        killed = fresh.provision(
            args=BACKGROUND,
            cli_hook=_when_restarting_the_new_version(fresh, _kill_provision(fresh)),
        )
        assert killed.returncode < 0, _out(killed)

        result = fresh.provision(args=BACKGROUND)

        assert result.returncode == 0, _out(result)
        assert fresh.clone_version() == CLONE_VERSION
        state = _state(fresh, MAIN_VERSION)
        assert state["status"] == "failed"
        assert "put back" in state["detail"]
        assert fresh.box.resolves()
        assert _no_switch_left(fresh)
        assert not (_sync_dir(fresh) / "lock.d").exists(), _out(result)

    def test_a_switch_another_live_process_is_making_is_left_alone(
        self, fresh: Provisioning
    ) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect(MAIN_VERSION)
        before = _live_state(fresh.clone)
        aside = _aside(fresh)
        (aside / "untracked").mkdir(parents=True)
        (aside / "untracked" / SWITCH_MARKER_NAME).write_text(f"{os.getpid()}\n")

        result = fresh.provision()

        out = _out(result)
        assert result.returncode != 0
        assert f"pid {os.getpid()}" in out
        assert aside.is_dir()
        assert _live_state(fresh.clone) == before
        assert fresh.clone_version() == CLONE_VERSION


class TestNoHookStartsADaemonMidSwitch:
    """init.sh refuses a lazy start while provision is switching the clone."""

    def test_a_live_switch_marker_answers_starting_and_starts_nothing(
        self, fresh: Provisioning
    ) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        _stop_the_daemon(fresh)
        (fresh.clone / "untracked" / SWITCH_MARKER_NAME).write_text(f"{os.getpid()}\n")
        starts = fresh.starts()

        result = fresh.box.hook("PreToolUse")

        assert "the daemon is starting" in _out(result)
        assert "provision is switching" in result.stderr
        assert "ENSURE_DAEMON_OK" not in result.stdout
        assert fresh.starts() == starts, "no start was even attempted"

    def test_a_marker_left_by_a_dead_sync_does_not_block_a_start(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        _stop_the_daemon(fresh)
        (fresh.clone / "untracked" / SWITCH_MARKER_NAME).write_text(f"{_a_dead_pid()}\n")
        starts = fresh.starts()

        result = fresh.box.hook("PreToolUse")

        assert "provision is switching" not in result.stderr
        assert fresh.starts() == starts + 1, "the hook went on to start the daemon"


BACKGROUND = ("--background",)


def _sync_dir(p: Provisioning) -> Path:
    return p.clone / "untracked" / SYNC_STATE_DIR_NAME


def _state(p: Provisioning, version: str) -> dict[str, str]:
    """The key=value state the background sync to ``version`` recorded."""
    path = _sync_dir(p) / f"v{version}.state"
    assert path.is_file(), f"no state recorded at {path}"
    return dict(line.split("=", 1) for line in path.read_text().splitlines())


def _a_dead_pid() -> int:
    return int(Path("/proc/sys/kernel/pid_max").read_text()) + 1


class TestTheBackgroundSync:
    """Plan 00477 Tasks 5.2 and 5.4: ``--background`` is the sync version_check starts."""

    def test_a_pulled_newer_version_syncs_restarts_and_records_it(
        self, fresh: Provisioning
    ) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect(MAIN_VERSION)

        result = fresh.provision(args=BACKGROUND)

        assert result.returncode == 0, _out(result)
        assert fresh.clone_version() == MAIN_VERSION
        assert fresh.starts() == 2, "the daemon was restarted exactly once, at the new version"
        assert fresh.tracked_changes() == ""
        state = _state(fresh, MAIN_VERSION)
        assert state["status"] == "synced"
        assert state["from"] == CLONE_VERSION
        assert state["target"] == MAIN_VERSION
        assert not (_sync_dir(fresh) / "lock.d").exists(), "the lock is released"

    def test_a_sync_failure_keeps_the_old_daemon_and_records_why(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        before = fresh.clone_tracked_state()
        fresh.expect(MAIN_VERSION)

        result = fresh.provision(args=BACKGROUND, uv_fails=True)

        assert result.returncode != 0
        assert fresh.clone_tracked_state() == before
        assert fresh.clone_version() == CLONE_VERSION
        assert fresh.box.resolves(), "the old venv is untouched"
        assert fresh.starts() == 1, "the old daemon was never stopped"
        state = _state(fresh, MAIN_VERSION)
        assert state["status"] == "failed"
        assert "venv" in state["detail"]
        assert not (_sync_dir(fresh) / "lock.d").exists()

    def test_a_target_already_attempted_is_never_attempted_again(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect(MAIN_VERSION)
        assert fresh.provision(args=BACKGROUND, uv_fails=True).returncode != 0
        starts = fresh.starts()

        result = fresh.provision(args=BACKGROUND)

        assert result.returncode == 0, _out(result)
        assert "already attempted" in _out(result)
        assert fresh.clone_version() == CLONE_VERSION
        assert fresh.starts() == starts
        assert _state(fresh, MAIN_VERSION)["status"] == "failed", "the failure stays on record"

    def test_a_sync_already_running_is_not_joined(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect(MAIN_VERSION)
        lock = _sync_dir(fresh) / "lock.d"
        lock.mkdir(parents=True)
        (lock / "pid").write_text(f"{os.getpid()}\n")
        before = fresh.clone_tracked_state()

        result = fresh.provision(args=BACKGROUND)

        assert result.returncode == 0, _out(result)
        assert "already running" in _out(result)
        assert fresh.clone_tracked_state() == before
        assert not (
            _sync_dir(fresh) / f"v{MAIN_VERSION}.state"
        ).exists(), "not claimed, so a later session tries again"
        assert lock.is_dir(), "another sync's lock is not taken from it"

    def test_a_lock_whose_holder_is_gone_is_taken_over(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect(MAIN_VERSION)
        lock = _sync_dir(fresh) / "lock.d"
        lock.mkdir(parents=True)
        (lock / "pid").write_text(f"{_a_dead_pid()}\n")

        result = fresh.provision(args=BACKGROUND)

        assert result.returncode == 0, _out(result)
        assert fresh.clone_version() == MAIN_VERSION
        assert not lock.exists()

    def test_a_refused_clone_is_recorded_as_a_failure(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        (fresh.clone / "pyproject.toml").write_text("# local edit\n")
        fresh.expect(MAIN_VERSION)

        result = fresh.provision(args=BACKGROUND)

        assert result.returncode != 0
        state = _state(fresh, MAIN_VERSION)
        assert state["status"] == "failed"
        assert "local changes" in state["detail"]

    def test_a_target_that_needs_reading_is_recorded_and_changes_nothing(
        self, fresh: Provisioning
    ) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect(GATED_VERSION)
        before = fresh.clone_tracked_state()
        starts = fresh.starts()

        result = fresh.provision(args=BACKGROUND)

        assert result.returncode != 0
        assert fresh.clone_tracked_state() == before
        assert fresh.starts() == starts
        assert _state(fresh, GATED_VERSION)["status"] == "needs-reading"

    def test_a_fresh_checkout_is_never_provisioned_in_the_background(
        self, fresh: Provisioning
    ) -> None:
        result = fresh.provision(args=BACKGROUND)

        assert result.returncode != 0
        assert "existing clone" in _out(result)
        assert not (fresh.clone / ".git").exists()

    def test_a_downgrade_is_never_synced_in_the_background(self, fresh: Provisioning) -> None:
        _provisioned_at(fresh, MAIN_VERSION)
        fresh.expect(CLONE_VERSION)
        before = fresh.clone_tracked_state()

        result = fresh.provision(args=BACKGROUND)

        assert result.returncode != 0
        assert "downgrade" in _out(result).lower()
        assert fresh.clone_tracked_state() == before
        assert not _sync_dir(fresh).exists() or not any(_sync_dir(fresh).glob("*.state"))

    def test_the_daemons_own_repository_never_syncs(self, tmp_path: Path) -> None:
        p = _make(tmp_path, _configured(MAIN_VERSION))
        try:
            version_py = p.project / "src" / "claude_code_hooks_daemon" / "version.py"
            version_py.parent.mkdir(parents=True)
            version_py.write_text(f'__version__ = "{CLONE_VERSION}"\n')

            result = p.provision(args=BACKGROUND)

            assert result.returncode != 0
            assert "bootstrap-self-install" in _out(result)
            assert not (p.clone / ".git").exists()
        finally:
            p.box.cleanup()


def _outcome(p: Provisioning, version: str, timeout: float = 60.0) -> dict[str, str]:
    """The state a background sync recorded once it stopped running."""
    path = _sync_dir(p) / f"v{version}.state"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            state = _state(p, version)
            if state.get("status") != "running":
                return state
        time.sleep(0.1)
    raise AssertionError(f"the background sync to {version} did not finish within {timeout}s")


SESSION_START_SOURCE = REPO_ROOT / ".claude" / "hooks" / "session-start"
#: The venv build the sync runs is made this slow, so the hook is seen to answer first.
SLOW_BUILD_SECONDS = 5.0
#: How long the stand-in daemon gets to exit on SIGTERM.
STOP_GRACE_SECONDS = 10.0


def _deploy_session_start(p: Provisioning, *, relay: bool = False) -> Path:
    """The session-start forwarder as the installer deploys it into the project."""
    content = generate_forwarder_content(
        SESSION_START_SOURCE.read_text(),
        "session-start",
        TransportConfig(relay_enabled=relay),
        p.clone / "untracked",
        p.project,
    )
    hooks = p.project / ".claude" / "hooks"
    hooks.mkdir(exist_ok=True)
    forwarder = hooks / "session-start"
    forwarder.write_text(content)
    forwarder.chmod(0o755)
    return forwarder


def _stop_the_daemon(p: Provisioning) -> None:
    """End the stand-in daemon, so the clone has no daemon running from it."""
    stopped = stop_verified_daemon(
        int(p.box.pid.read_text().strip()),
        project_root=p.project.resolve(),
        grace_seconds=STOP_GRACE_SECONDS,
    )
    assert stopped in (DaemonStop.TERMINATED, DaemonStop.KILLED), stopped
    # The stand-in's socket outlives it; a real daemon removes its own on stop.
    p.box.socket.unlink(missing_ok=True)


class TestTheSessionStartHookStartsIt:
    """Plan 00477 Task 5.2: the tracked session-start forwarder starts the sync, detached."""

    def test_a_pulled_upgrade_is_synced_after_the_hook_has_answered(
        self, fresh: Provisioning
    ) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect(MAIN_VERSION)
        forwarder = _deploy_session_start(fresh)
        fresh.box.stub_uv(sleep=SLOW_BUILD_SECONDS, embed_build_paths=True)

        hook = subprocess.run(
            [BASH, str(forwarder)],
            input='{"hook_event_name": "SessionStart", "synthetic_source": "test-probe"}',
            capture_output=True,
            text=True,
            env=fresh.box.env(fresh.git_env),
            cwd=fresh.project,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
        state_after_hook = _sync_dir(fresh) / f"v{MAIN_VERSION}.state"
        answered_first = (
            not state_after_hook.exists() or _state(fresh, MAIN_VERSION)["status"] == "running"
        )

        assert hook.returncode == 0, hook.stdout + hook.stderr
        assert answered_first, "the hook waited for the sync instead of answering"
        state = _outcome(fresh, MAIN_VERSION)
        log = _sync_dir(fresh) / f"v{MAIN_VERSION}.log"
        assert state["status"] == "synced", log.read_text()
        assert fresh.clone_version() == MAIN_VERSION
        assert fresh.starts() == 2
        assert "SYNCED" in log.read_text()

    def test_the_start_comes_before_the_relay_hot_path(self, fresh: Provisioning) -> None:
        """A relay-enabled project never sources init.sh at session start."""
        content = _deploy_session_start(fresh, relay=True).read_text()

        launch = content.index('provision.sh" --background')
        assert launch < content.index("# --- relay hot path (generated")
        assert launch < content.index(INIT_SH_ANCHOR)

    def test_a_sync_waits_for_a_running_daemon_and_otherwise_claims_nothing(
        self, fresh: Provisioning
    ) -> None:
        _provisioned_at(fresh, CLONE_VERSION)
        fresh.expect(MAIN_VERSION)
        _stop_the_daemon(fresh)
        before = fresh.clone_tracked_state()

        result = fresh.provision(args=BACKGROUND)

        assert result.returncode == 0, _out(result)
        assert "No daemon is running from the clone" in _out(result)
        assert fresh.clone_tracked_state() == before
        assert not (_sync_dir(fresh) / f"v{MAIN_VERSION}.state").exists()
        assert not (_sync_dir(fresh) / "lock.d").exists()


class TestTheGateConstantsAreUpgradesOwn:
    @pytest.mark.parametrize(
        "name", ["GATE_PYTHON_FLOOR", "GATE_TIMEOUT_SECONDS", "GATE_NEEDS_ACKNOWLEDGEMENT"]
    )
    def test_provision_runs_the_gate_with_the_values_upgrade_does(self, name: str) -> None:
        pattern = re.compile(rf'^(?:readonly )?{name}="?([^"\n]+)"?$', re.MULTILINE)
        upgrade = pattern.search((REPO_ROOT / "scripts" / "upgrade_version.sh").read_text())
        provision = pattern.search(PROVISION_SH.read_text())

        assert upgrade is not None and provision is not None
        assert provision.group(1) == upgrade.group(1)
