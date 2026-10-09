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


class TestTheRuleIsTheCanonicalOne:
    """The supervisor asks `daemon/install_layout.py` rather than keeping its own test (N386).

    It loads that file by path -- it stays stdlib-only and imports no package --
    from the checkout the script itself sits in, so a project root that
    carries no daemon source at all (a test directory, a stray cwd) still gets
    an answer.
    """

    def test_a_file_at_the_marker_path_is_a_client_install(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        marker = tmp_path / "src" / "claude_code_hooks_daemon"
        marker.parent.mkdir(parents=True)
        marker.write_text("a file, not the source tree", encoding="utf-8")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

        result = _mod._daemon_untracked_dir()

        assert result == tmp_path / ".claude" / "hooks-daemon" / "untracked"

    @pytest.mark.parametrize("self_install", [True, False])
    def test_agrees_with_install_layout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, self_install: bool
    ) -> None:
        from claude_code_hooks_daemon.daemon.install_layout import get_untracked_dir

        if self_install:
            _make_self_install_marker(tmp_path)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

        assert _mod._daemon_untracked_dir() == get_untracked_dir(tmp_path)

    def test_the_rule_is_found_in_a_client_clone_too(self, tmp_path: Path) -> None:
        """A deployed script sits in a client whose daemon clone is under `.claude/hooks-daemon`."""
        client = tmp_path / "client"
        clone_daemon_dir = client / ".claude" / "hooks-daemon" / "src" / "claude_code_hooks_daemon"
        (clone_daemon_dir / "daemon").mkdir(parents=True)
        (clone_daemon_dir / "daemon" / "install_layout.py").write_text(
            (
                Path(str(_mod.__file__)).resolve().parents[2]
                / "src"
                / "claude_code_hooks_daemon"
                / "daemon"
                / "install_layout.py"
            ).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        located = _mod._install_layout_path(client)

        assert located == clone_daemon_dir / "daemon" / "install_layout.py"

    def test_a_checkout_with_no_rule_file_fails_loudly(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            _mod._install_layout_path(tmp_path)
