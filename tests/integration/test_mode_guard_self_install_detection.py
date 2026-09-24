"""`mode_guard.sh`'s self-install detection, re-keyed on a real clone (Plan 00455).

`detect_self_install_mode` decided "normal mode" purely from
`.claude/hooks-daemon/` EXISTING. The self-install daemon now generates a bare
`bin/hooks-daemon` symlink under that same path so external tools find the CLI
at the conventional location (Plan 00455 Task 1.3) -- so a self-install
checkout that has started its daemon at least once now has a
`.claude/hooks-daemon/` directory too, and the old check would misclassify it
as a normal install. `ensure_normal_mode_only` (which guards `install.sh` /
`upgrade.sh` against running inside this repository) would then stop firing.

The fix re-keys the directory-existence check on a REAL clone -- the same
discriminator the Python side uses (`project_root_is_daemon_repo`): a real
client clone has `pyproject.toml` under `.claude/hooks-daemon/`, the
self-generated marker never does (it is `bin/hooks-daemon` alone).
"""

from __future__ import annotations

import subprocess  # nosec B404 — runs the trusted system `bash`
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_MODE_GUARD_SH: Final[Path] = _REPO_ROOT / "scripts" / "install" / "mode_guard.sh"

_TIMEOUT_SECONDS: Final[int] = 30

_DAEMON_PYPROJECT: Final[str] = (
    '[project]\nname = "claude-code-hooks-daemon"\nversion = "1.0.0"\n'
)


def _self_install_layout(project_root: Path) -> None:
    """The two markers `detect_self_install_mode` requires, at project root."""
    (project_root / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
    (project_root / "pyproject.toml").write_text(_DAEMON_PYPROJECT, encoding="utf-8")


def _run(project_root: Path, script: str) -> subprocess.CompletedProcess[str]:
    """Source `mode_guard.sh` (a copy, so `BASH_SOURCE` resolves under it) and
    run `script` against its functions, with `project_root` passed by value.
    """
    guard_copy = project_root / "mode_guard.sh"
    guard_copy.write_text(_MODE_GUARD_SH.read_text(encoding="utf-8"), encoding="utf-8")
    (project_root / "output.sh").write_text(
        (_REPO_ROOT / "scripts" / "install" / "output.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return subprocess.run(  # nosec B603 — fixed argv, no shell, trusted input
        ["bash", "-c", f'source "{guard_copy}"\n{script}'],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(project_root)},
        check=False,
    )


class TestDetectSelfInstallMode:
    def test_reports_self_install_with_no_claude_hooks_daemon_dir(
        self, tmp_path: Path
    ) -> None:
        """Baseline: the original, still-valid positive case."""
        _self_install_layout(tmp_path)

        result = _run(tmp_path, f'get_install_mode "{tmp_path}"')

        assert result.stdout.strip() == "self-install", result.stderr

    def test_reports_self_install_with_a_link_only_marker_present(
        self, tmp_path: Path
    ) -> None:
        """The bug this plan fixes: a self-generated symlink is not a clone."""
        _self_install_layout(tmp_path)
        marker_bin = tmp_path / ".claude" / "hooks-daemon" / "bin"
        marker_bin.mkdir(parents=True)
        (marker_bin / "hooks-daemon").symlink_to(tmp_path / "bin" / "hooks-daemon")

        result = _run(tmp_path, f'get_install_mode "{tmp_path}"')

        assert result.stdout.strip() == "self-install", result.stderr

    def test_reports_normal_for_a_real_client_clone(self, tmp_path: Path) -> None:
        """Negative direction: a genuine client clone must still be normal."""
        _self_install_layout(tmp_path)
        real_clone = tmp_path / ".claude" / "hooks-daemon"
        real_clone.mkdir(parents=True)
        (real_clone / "pyproject.toml").write_text(_DAEMON_PYPROJECT, encoding="utf-8")

        result = _run(tmp_path, f'get_install_mode "{tmp_path}"')

        assert result.stdout.strip() == "normal", result.stderr

    def test_reports_normal_without_self_install_source_markers(
        self, tmp_path: Path
    ) -> None:
        """Control: an ordinary project (no daemon source at all) is normal."""
        result = _run(tmp_path, f'get_install_mode "{tmp_path}"')

        assert result.stdout.strip() == "normal", result.stderr


class TestEnsureNormalModeOnly:
    """`ensure_normal_mode_only` is what stops install/upgrade running inside
    this repository -- the guard the link-only marker must not switch off.
    """

    def test_aborts_in_self_install_mode_with_the_marker_present(
        self, tmp_path: Path
    ) -> None:
        _self_install_layout(tmp_path)
        marker_bin = tmp_path / ".claude" / "hooks-daemon" / "bin"
        marker_bin.mkdir(parents=True)
        (marker_bin / "hooks-daemon").symlink_to(tmp_path / "bin" / "hooks-daemon")

        result = _run(tmp_path, f'PROJECT_ROOT="{tmp_path}" ensure_normal_mode_only')

        # ensure_normal_mode_only exits the whole process on detection (it must
        # ABORT the caller, not merely return), so the process exit code IS the
        # signal -- a trailing `echo` after it would never run.
        assert "SELF-INSTALL MODE DETECTED" in result.stderr
        assert result.returncode == 1

    def test_allows_a_real_client_clone_through(self, tmp_path: Path) -> None:
        real_clone = tmp_path / ".claude" / "hooks-daemon"
        real_clone.mkdir(parents=True)
        (real_clone / "pyproject.toml").write_text(_DAEMON_PYPROJECT, encoding="utf-8")

        result = _run(
            tmp_path, f'PROJECT_ROOT="{tmp_path}" ensure_normal_mode_only; echo rc=$?'
        )

        assert "SELF-INSTALL MODE DETECTED" not in result.stderr
        assert "rc=0" in result.stdout

    def test_uses_the_passed_argument_not_only_the_global(self, tmp_path: Path) -> None:
        """The $1 the callers pass must actually be honoured (Plan 00455 side
        finding): install_version.sh/upgrade_version.sh call
        `ensure_normal_mode_only "$DAEMON_DIR"`, which the old implementation
        silently discarded in favour of the `$PROJECT_ROOT` global alone.
        """
        _self_install_layout(tmp_path)
        marker_bin = tmp_path / ".claude" / "hooks-daemon" / "bin"
        marker_bin.mkdir(parents=True)
        (marker_bin / "hooks-daemon").symlink_to(tmp_path / "bin" / "hooks-daemon")

        # No $PROJECT_ROOT global at all -- only the positional argument.
        result = _run(tmp_path, f'ensure_normal_mode_only "{tmp_path}"')

        assert "SELF-INSTALL MODE DETECTED" in result.stderr
        assert result.returncode == 1
