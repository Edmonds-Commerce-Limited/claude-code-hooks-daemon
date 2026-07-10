"""Unit tests for ccy supervisor deployment (Plan 00147).

``deploy_ccy_supervisor_if_enabled`` copies the standalone PTY supervisor
(``claude-supervise.py``) from the daemon clone's ``.claude/ccy/`` into a target
project's ``.claude/ccy/``, gated by the ``ccy.deploy_supervisor`` tri-state
config flag and the presence of the target ``.claude/ccy/`` directory.
"""

import stat
from pathlib import Path

from claude_code_hooks_daemon.install.ccy_supervisor import (
    SUPERVISOR_SCRIPT_NAME,
    ccy_supervisor_source_path,
    deploy_ccy_supervisor_if_enabled,
)

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
        assert (ccy / SUPERVISOR_SCRIPT_NAME).read_text() == "#!/usr/bin/env python3\n# NEW version\n"

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
