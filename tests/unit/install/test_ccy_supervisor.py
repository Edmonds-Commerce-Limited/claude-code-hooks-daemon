"""Unit tests for ccy supervisor deployment (Plan 00147).

``deploy_ccy_supervisor_if_enabled`` copies the standalone PTY supervisor
(``claude-supervise.py``) from the daemon clone's ``.claude/ccy/`` into a target
project's ``.claude/ccy/``, gated by the ``ccy.deploy_supervisor`` tri-state
config flag and the presence of the target ``.claude/ccy/`` directory.
"""

import stat
import subprocess
from pathlib import Path

from claude_code_hooks_daemon.install.ccy_supervisor import (
    CCY_ENV_NAME,
    SUPERVISOR_SCRIPT_NAME,
    ccy_supervisor_source_path,
    deploy_ccy_supervisor_if_enabled,
)

_WRAPPER_KEY = "CCY_CLAUDE_WRAPPER"

_SOURCE_CONTENT = "#!/usr/bin/env python3\n# canonical supervisor stub\nprint('hi')\n"


def _make_source(daemon_root: Path, content: str = _SOURCE_CONTENT) -> Path:
    """Create ``<daemon_root>/.claude/ccy/claude-supervise.py`` with content."""
    src = daemon_root / ".claude" / "ccy" / SUPERVISOR_SCRIPT_NAME
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(content)
    return src


def _make_target_ccy(project_root: Path) -> Path:
    """Create the target project's ``.claude/ccy/`` directory."""
    ccy = project_root / ".claude" / "ccy"
    ccy.mkdir(parents=True, exist_ok=True)
    return ccy


def _write_config(project_root: Path, body: str) -> Path:
    config_dir = project_root / ".claude"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "hooks-daemon.yaml"
    config_path.write_text(body)
    return config_path


class TestDeployCcySupervisorIfEnabled:
    """Cover the full tri-state deploy table."""

    def test_flag_true_deploys(self, tmp_path: Path) -> None:
        daemon_root = tmp_path / "daemon"
        project_root = tmp_path / "project"
        _make_source(daemon_root)
        _make_target_ccy(project_root)
        config_path = _write_config(project_root, "ccy:\n  deploy_supervisor: true\n")

        result = deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)

        target = project_root / ".claude" / "ccy" / SUPERVISOR_SCRIPT_NAME
        assert result.deployed is True
        assert target.read_text() == _SOURCE_CONTENT
        assert stat.S_IMODE(target.stat().st_mode) == 0o755
        assert result.recommend_enable is False

    def test_flag_false_skips(self, tmp_path: Path) -> None:
        daemon_root = tmp_path / "daemon"
        project_root = tmp_path / "project"
        _make_source(daemon_root)
        _make_target_ccy(project_root)
        config_path = _write_config(project_root, "ccy:\n  deploy_supervisor: false\n")

        result = deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)

        target = project_root / ".claude" / "ccy" / SUPERVISOR_SCRIPT_NAME
        assert result.deployed is False
        assert not target.exists()
        assert any("false" in m.lower() for m in result.messages)

    def test_flag_absent_deploys_and_recommends(self, tmp_path: Path) -> None:
        daemon_root = tmp_path / "daemon"
        project_root = tmp_path / "project"
        _make_source(daemon_root)
        _make_target_ccy(project_root)
        # Config present but no ccy section → deploy_supervisor is None (absent).
        config_path = _write_config(project_root, "version: '2.0'\n")

        result = deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)

        target = project_root / ".claude" / "ccy" / SUPERVISOR_SCRIPT_NAME
        assert result.deployed is True
        assert target.read_text() == _SOURCE_CONTENT
        assert result.recommend_enable is True

    def test_no_ccy_dir_is_noop(self, tmp_path: Path) -> None:
        daemon_root = tmp_path / "daemon"
        project_root = tmp_path / "project"
        _make_source(daemon_root)
        # No target .claude/ccy directory created.
        config_path = _write_config(project_root, "ccy:\n  deploy_supervisor: true\n")

        result = deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)

        assert result.deployed is False
        assert result.recommend_enable is False
        assert not (project_root / ".claude" / "ccy").exists()
        assert any("ccy" in m.lower() for m in result.messages)

    def test_self_install_noop_when_source_equals_target(self, tmp_path: Path) -> None:
        """daemon_root == project_root → source and target are the same file."""
        root = tmp_path / "selfinstall"
        src = _make_source(root)
        config_path = _write_config(root, "ccy:\n  deploy_supervisor: true\n")

        result = deploy_ccy_supervisor_if_enabled(root, root, config_path)

        # File is untouched and no second copy created.
        assert result.deployed is False
        assert src.read_text() == _SOURCE_CONTENT
        assert any("self-install" in m.lower() or "already" in m.lower() for m in result.messages)

    def test_missing_source_skips_gracefully(self, tmp_path: Path) -> None:
        daemon_root = tmp_path / "daemon"
        project_root = tmp_path / "project"
        # daemon_root has NO .claude/ccy/claude-supervise.py
        _make_target_ccy(project_root)
        config_path = _write_config(project_root, "ccy:\n  deploy_supervisor: true\n")

        result = deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)

        assert result.deployed is False
        assert any("source" in m.lower() for m in result.messages)

    def test_refresh_overwrites_stale_supervisor(self, tmp_path: Path) -> None:
        daemon_root = tmp_path / "daemon"
        project_root = tmp_path / "project"
        _make_source(daemon_root, "#!/usr/bin/env python3\n# NEW version\n")
        ccy = _make_target_ccy(project_root)
        (ccy / SUPERVISOR_SCRIPT_NAME).write_text("#!/usr/bin/env python3\n# OLD stale\n")
        config_path = _write_config(project_root, "ccy:\n  deploy_supervisor: true\n")

        result = deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)

        assert result.deployed is True
        assert (
            ccy / SUPERVISOR_SCRIPT_NAME
        ).read_text() == "#!/usr/bin/env python3\n# NEW version\n"

    def test_missing_config_file_treated_as_absent_flag(self, tmp_path: Path) -> None:
        """No config file on disk → model default (None) → deploy + recommend."""
        daemon_root = tmp_path / "daemon"
        project_root = tmp_path / "project"
        _make_source(daemon_root)
        _make_target_ccy(project_root)
        missing = project_root / ".claude" / "hooks-daemon.yaml"

        result = deploy_ccy_supervisor_if_enabled(daemon_root, project_root, missing)

        assert result.deployed is True
        assert result.recommend_enable is True


class TestArmCcySupervisor:
    """Deploy must ARM the supervisor, not just copy it (Plan 00148 hotfix).

    Arming = ensure ``.claude/ccy/ccy.env`` exports ``CCY_CLAUDE_WRAPPER`` so the
    launcher (which sources that file) actually wraps ``claude`` with the
    supervisor. Without this the deployed script is inert.
    """

    def test_flag_true_arms_fresh_ccy_env(self, tmp_path: Path) -> None:
        daemon_root = tmp_path / "daemon"
        project_root = tmp_path / "project"
        _make_source(daemon_root)
        ccy = _make_target_ccy(project_root)
        config_path = _write_config(project_root, "ccy:\n  deploy_supervisor: true\n")

        result = deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)

        env_file = ccy / CCY_ENV_NAME
        assert result.armed is True
        assert env_file.is_file()
        content = env_file.read_text()
        assert _WRAPPER_KEY in content
        assert "--arm" in content

    def test_flag_absent_arms(self, tmp_path: Path) -> None:
        daemon_root = tmp_path / "daemon"
        project_root = tmp_path / "project"
        _make_source(daemon_root)
        ccy = _make_target_ccy(project_root)
        config_path = _write_config(project_root, "version: '2.0'\n")

        result = deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)

        assert result.armed is True
        assert result.recommend_enable is True
        assert (ccy / CCY_ENV_NAME).is_file()

    def test_flag_false_does_not_arm(self, tmp_path: Path) -> None:
        daemon_root = tmp_path / "daemon"
        project_root = tmp_path / "project"
        _make_source(daemon_root)
        ccy = _make_target_ccy(project_root)
        config_path = _write_config(project_root, "ccy:\n  deploy_supervisor: false\n")

        result = deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)

        assert result.armed is False
        assert not (ccy / CCY_ENV_NAME).exists()

    def test_appends_wrapper_to_existing_env_without_wrapper(self, tmp_path: Path) -> None:
        daemon_root = tmp_path / "daemon"
        project_root = tmp_path / "project"
        _make_source(daemon_root)
        ccy = _make_target_ccy(project_root)
        env_file = ccy / CCY_ENV_NAME
        pre = "# existing project ccy env\nexport FOO=bar\n"
        env_file.write_text(pre)
        config_path = _write_config(project_root, "ccy:\n  deploy_supervisor: true\n")

        result = deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)

        content = env_file.read_text()
        assert result.armed is True
        assert "export FOO=bar" in content  # original preserved
        assert _WRAPPER_KEY in content  # armed line appended

    def test_leaves_existing_wrapper_untouched(self, tmp_path: Path) -> None:
        daemon_root = tmp_path / "daemon"
        project_root = tmp_path / "project"
        _make_source(daemon_root)
        ccy = _make_target_ccy(project_root)
        env_file = ccy / CCY_ENV_NAME
        custom = 'export CCY_CLAUDE_WRAPPER="/custom/path/wrapper --"\n'
        env_file.write_text(custom)
        config_path = _write_config(project_root, "ccy:\n  deploy_supervisor: true\n")

        result = deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)

        assert result.armed is False
        assert env_file.read_text() == custom  # byte-identical, user choice respected

    def test_leaves_commented_out_wrapper_untouched(self, tmp_path: Path) -> None:
        """A user who commented out the wrapper to DISABLE it must stay disabled."""
        daemon_root = tmp_path / "daemon"
        project_root = tmp_path / "project"
        _make_source(daemon_root)
        ccy = _make_target_ccy(project_root)
        env_file = ccy / CCY_ENV_NAME
        disabled = '# export CCY_CLAUDE_WRAPPER="/x/claude-supervise.py --arm --"\n'
        env_file.write_text(disabled)
        config_path = _write_config(project_root, "ccy:\n  deploy_supervisor: true\n")

        result = deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)

        assert result.armed is False
        assert env_file.read_text() == disabled

    def test_arming_is_idempotent(self, tmp_path: Path) -> None:
        daemon_root = tmp_path / "daemon"
        project_root = tmp_path / "project"
        _make_source(daemon_root)
        ccy = _make_target_ccy(project_root)
        config_path = _write_config(project_root, "ccy:\n  deploy_supervisor: true\n")

        first = deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)
        after_first = (ccy / CCY_ENV_NAME).read_text()
        second = deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)
        after_second = (ccy / CCY_ENV_NAME).read_text()

        assert first.armed is True
        assert second.armed is False  # wrapper already present
        assert after_first == after_second  # no duplication / drift

    def test_self_install_leaves_tracked_env_untouched(self, tmp_path: Path) -> None:
        """Self-install (source == target) with an already-armed ccy.env no-ops."""
        root = tmp_path / "selfinstall"
        _make_source(root)
        ccy = root / ".claude" / "ccy"
        env_file = ccy / CCY_ENV_NAME
        tracked = (
            'export CCY_CLAUDE_WRAPPER="${CCY_CLAUDE_WRAPPER:-/w/claude-supervise.py --arm --}"\n'
        )
        env_file.write_text(tracked)
        config_path = _write_config(root, "ccy:\n  deploy_supervisor: true\n")

        result = deploy_ccy_supervisor_if_enabled(root, root, config_path)

        assert result.deployed is False  # script self-install no-op
        assert result.armed is False  # env already configured
        assert env_file.read_text() == tracked

    def test_generated_wrapper_sources_to_absolute_supervisor_path(self, tmp_path: Path) -> None:
        """The armed line must resolve, in bash, to an absolute armed wrapper.

        Proves the self-locating ``${BASH_SOURCE[0]}`` form works regardless of
        mount path (podman /workspace vs an arbitrary LXC project dir).
        """
        daemon_root = tmp_path / "daemon"
        project_root = tmp_path / "project"
        _make_source(daemon_root)
        ccy = _make_target_ccy(project_root)
        config_path = _write_config(project_root, "ccy:\n  deploy_supervisor: true\n")

        deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)

        env_file = ccy / CCY_ENV_NAME
        # Source the generated env in bash and print the resolved wrapper. Unset
        # CCY_CLAUDE_WRAPPER first so the ${VAR:-default} exercises the default
        # (an ambient value — e.g. this dogfood session — would otherwise win,
        # which is the intended host-override behaviour, not what we test here).
        proc = subprocess.run(
            [
                "bash",
                "-c",
                f'unset CCY_CLAUDE_WRAPPER; . "{env_file}" && printf "%s" "$CCY_CLAUDE_WRAPPER"',
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        expected = f"{ccy.resolve()}/{SUPERVISOR_SCRIPT_NAME} --arm --"
        assert proc.stdout == expected


class TestEnsureCcyFilesTracked:
    """Deploy must ensure the supervisor files are TRACKABLE, not git-ignored.

    The common ccy `.gitignore` pattern is a blanket `*` that ignores session
    data. Without whitelist exceptions the deployed/armed ``claude-supervise.py``
    and ``ccy.env`` land git-ignored, never get committed, and teammates cloning
    the repo do not get the supervisor — so the system is not "properly set up".
    The deploy whitelists the supervisor files in ``.claude/ccy/.gitignore``.
    """

    def test_absent_gitignore_is_left_alone(self, tmp_path: Path) -> None:
        """No local .gitignore → our files are not locally ignored; we do NOT
        fabricate a blanket-ignore policy file (not this repo's job)."""
        daemon_root = tmp_path / "daemon"
        project_root = tmp_path / "project"
        _make_source(daemon_root)
        ccy = _make_target_ccy(project_root)
        config_path = _write_config(project_root, "ccy:\n  deploy_supervisor: true\n")

        result = deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)

        assert result.gitignore_updated is False
        assert not (ccy / ".gitignore").exists()

    def test_appends_missing_whitelist_to_blanket_ignore(self, tmp_path: Path) -> None:
        daemon_root = tmp_path / "daemon"
        project_root = tmp_path / "project"
        _make_source(daemon_root)
        ccy = _make_target_ccy(project_root)
        gitignore = ccy / ".gitignore"
        gitignore.write_text("# ccy session data\n*\n")  # ignores everything, no whitelist
        config_path = _write_config(project_root, "ccy:\n  deploy_supervisor: true\n")

        result = deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)

        content = gitignore.read_text()
        assert result.gitignore_updated is True
        assert "*" in content  # original blanket ignore preserved
        assert f"!{SUPERVISOR_SCRIPT_NAME}" in content
        assert f"!{CCY_ENV_NAME}" in content

    def test_appends_only_missing_whitelist_lines(self, tmp_path: Path) -> None:
        daemon_root = tmp_path / "daemon"
        project_root = tmp_path / "project"
        _make_source(daemon_root)
        ccy = _make_target_ccy(project_root)
        gitignore = ccy / ".gitignore"
        gitignore.write_text(f"*\n!.gitignore\n!{CCY_ENV_NAME}\n")  # missing the script line
        config_path = _write_config(project_root, "ccy:\n  deploy_supervisor: true\n")

        result = deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)

        content = gitignore.read_text()
        assert result.gitignore_updated is True
        assert content.count(f"!{CCY_ENV_NAME}") == 1  # not duplicated
        assert f"!{SUPERVISOR_SCRIPT_NAME}" in content  # added

    def test_leaves_gitignore_untouched_when_already_whitelisted(self, tmp_path: Path) -> None:
        daemon_root = tmp_path / "daemon"
        project_root = tmp_path / "project"
        _make_source(daemon_root)
        ccy = _make_target_ccy(project_root)
        gitignore = ccy / ".gitignore"
        whitelisted = f"*\n!.gitignore\n!Dockerfile\n!{CCY_ENV_NAME}\n!{SUPERVISOR_SCRIPT_NAME}\n"
        gitignore.write_text(whitelisted)
        config_path = _write_config(project_root, "ccy:\n  deploy_supervisor: true\n")

        result = deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)

        assert result.gitignore_updated is False
        assert gitignore.read_text() == whitelisted

    def test_flag_false_does_not_touch_gitignore(self, tmp_path: Path) -> None:
        daemon_root = tmp_path / "daemon"
        project_root = tmp_path / "project"
        _make_source(daemon_root)
        ccy = _make_target_ccy(project_root)
        config_path = _write_config(project_root, "ccy:\n  deploy_supervisor: false\n")

        result = deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)

        assert result.gitignore_updated is False
        assert not (ccy / ".gitignore").exists()

    def test_whitelist_actually_untracks_files_in_a_real_git_repo(self, tmp_path: Path) -> None:
        """End-to-end: in a real git repo with a blanket-ignore ccy dir, the
        deployed supervisor files are NOT git-ignored afterwards."""
        project_root = tmp_path / "project"
        daemon_root = tmp_path / "daemon"
        _make_source(daemon_root)
        ccy = _make_target_ccy(project_root)
        (ccy / ".gitignore").write_text("*\n")  # blanket ignore, the broken setup
        config_path = _write_config(project_root, "ccy:\n  deploy_supervisor: true\n")

        subprocess.run(["git", "init", "-q", str(project_root)], check=True)

        deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)

        # git check-ignore exits 0 when the path IS ignored, 1 when it is NOT.
        for name in (SUPERVISOR_SCRIPT_NAME, CCY_ENV_NAME):
            check = subprocess.run(
                ["git", "-C", str(project_root), "check-ignore", "-q", f".claude/ccy/{name}"],
            )
            assert check.returncode == 1, f"{name} is still git-ignored after deploy"


class TestCcySupervisorSourcePath:
    """The source-path helper and the real canonical file."""

    def test_source_path_shape(self, tmp_path: Path) -> None:
        assert (
            ccy_supervisor_source_path(tmp_path)
            == tmp_path / ".claude" / "ccy" / SUPERVISOR_SCRIPT_NAME
        )

    def test_canonical_supervisor_exists_in_this_repo(self) -> None:
        """Guard: the tracked canonical supervisor lives where the deploy expects.

        tests/unit/install/test_ccy_supervisor.py -> parents[3] == repo root.
        """
        repo_root = Path(__file__).resolve().parents[3]
        assert ccy_supervisor_source_path(repo_root).is_file()

    def test_deploys_the_real_canonical_supervisor(self, tmp_path: Path) -> None:
        """End-to-end: the REAL 32K supervisor deploys from this repo into a client.

        Uses the actual repo root as daemon_root (as the shell wiring does) and a
        separate tmp project as the target, so it exercises the true source file
        and layout — not a stub.
        """
        repo_root = Path(__file__).resolve().parents[3]
        project_root = tmp_path / "client"
        (project_root / ".claude" / "ccy").mkdir(parents=True)
        config_path = _write_config(project_root, "ccy:\n  deploy_supervisor: true\n")

        result = deploy_ccy_supervisor_if_enabled(repo_root, project_root, config_path)

        target = project_root / ".claude" / "ccy" / SUPERVISOR_SCRIPT_NAME
        assert result.deployed is True
        assert target.read_bytes() == ccy_supervisor_source_path(repo_root).read_bytes()
        assert stat.S_IMODE(target.stat().st_mode) == 0o755
