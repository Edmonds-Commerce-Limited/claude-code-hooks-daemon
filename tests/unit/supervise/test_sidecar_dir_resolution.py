"""Tests for install-mode-aware sidecar directory resolution (Plan 00149 Bug A).

The daemon writes its context sidecar to ``daemon_untracked_dir()/context-sidecar``,
which is install-mode-aware:

- normal client install: ``{project}/.claude/hooks-daemon/untracked/context-sidecar``
- self-install (daemon's own repo): ``{project}/untracked/context-sidecar``

The supervisor's ``_default_sidecar_dir()`` must resolve the SAME directory or it
polls a path the daemon never writes (the v3.34.0 bug: inert compact trigger in
every normal client install). Install mode is detected exactly as the daemon does
in ``ProjectContext``: self-install iff ``{project}/src/claude_code_hooks_daemon``
exists.
"""

from pathlib import Path

import pytest

from tests.unit.supervise._load import load_supervisor_module

_mod = load_supervisor_module()
_SUBDIR = _mod._SIDECAR_SUBDIR


def _make_self_install_marker(project: Path) -> None:
    (project / "src" / "claude_code_hooks_daemon").mkdir(parents=True, exist_ok=True)


class TestDefaultSidecarDir:
    def test_normal_install_uses_daemon_untracked_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No src/claude_code_hooks_daemon → normal install → .claude/hooks-daemon/untracked."""
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

        result = _mod._default_sidecar_dir()

        assert result == tmp_path / ".claude" / "hooks-daemon" / "untracked" / _SUBDIR

    def test_self_install_uses_project_untracked_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """src/claude_code_hooks_daemon present → self-install → {project}/untracked."""
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        _make_self_install_marker(tmp_path)

        result = _mod._default_sidecar_dir()

        assert result == tmp_path / "untracked" / _SUBDIR

    def test_resolution_is_stable_before_any_sidecar_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Normal-mode resolution does not depend on the sidecar dir existing yet."""
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        # Nothing created at all — still resolves to the normal-mode path.
        result = _mod._default_sidecar_dir()
        assert result.parts[-3:] == ("hooks-daemon", "untracked", _SUBDIR)
        assert not result.exists()

    def test_falls_back_to_cwd_when_env_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.chdir(tmp_path)

        result = _mod._default_sidecar_dir()

        # cwd has no src/claude_code_hooks_daemon → normal-mode layout under cwd.
        assert result == tmp_path / ".claude" / "hooks-daemon" / "untracked" / _SUBDIR
