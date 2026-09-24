"""`project_detection.sh` audited against the self-install CLI symlink (Plan 00455).

Unlike `mode_guard.sh`'s `detect_self_install_mode`, this file's directory
detection was found to already be safe against the self-install daemon's
generated `.claude/hooks-daemon/bin/hooks-daemon` marker:

- `detect_project_root`'s fallback signal requires `.claude/hooks-daemon/.git`
  -- a link-only marker has no `.git` at all, so it can never satisfy this.
- `detect_install_mode` reads `daemon.self_install_mode` out of
  `.claude/hooks-daemon.yaml`; it never inspects `.claude/hooks-daemon/`.

These tests pin that audit finding as a regression test rather than leaving
it as an unverified claim in a plan document.
"""

from __future__ import annotations

import subprocess  # nosec B404 — runs the trusted system `bash`
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_PROJECT_DETECTION_SH: Final[Path] = (
    _REPO_ROOT / "scripts" / "install" / "project_detection.sh"
)
_OUTPUT_SH: Final[Path] = _REPO_ROOT / "scripts" / "install" / "output.sh"

_TIMEOUT_SECONDS: Final[int] = 30


def _run(project_root: Path, script: str) -> subprocess.CompletedProcess[str]:
    lib_dir = project_root / "lib"
    lib_dir.mkdir(exist_ok=True)
    guard_copy = lib_dir / "project_detection.sh"
    guard_copy.write_text(
        _PROJECT_DETECTION_SH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (lib_dir / "output.sh").write_text(_OUTPUT_SH.read_text(encoding="utf-8"), encoding="utf-8")
    return subprocess.run(  # nosec B603 — fixed argv, no shell, trusted input
        ["bash", "-c", f'source "{guard_copy}"\n{script}'],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(project_root)},
        check=False,
        cwd=str(project_root),
    )


class TestDetectProjectRootIgnoresALinkOnlyMarker:
    def test_a_link_only_marker_does_not_satisfy_the_fallback_signal(
        self, tmp_path: Path
    ) -> None:
        """The fallback signal requires .claude/hooks-daemon/.git; the
        self-generated marker (a bare bin/hooks-daemon symlink) has none.
        """
        marker_bin = tmp_path / ".claude" / "hooks-daemon" / "bin"
        marker_bin.mkdir(parents=True)
        (marker_bin / "hooks-daemon").symlink_to(tmp_path / "bin" / "hooks-daemon")
        # No .claude/hooks-daemon.yaml either, so only the fallback applies.

        result = _run(tmp_path, "detect_project_root; echo rc=$?")

        assert "rc=1" in result.stdout, result.stdout
        assert str(tmp_path) not in result.stdout

    def test_a_real_clones_git_dir_still_satisfies_the_fallback_signal(
        self, tmp_path: Path
    ) -> None:
        real_clone_git = tmp_path / ".claude" / "hooks-daemon" / ".git"
        real_clone_git.mkdir(parents=True)

        result = _run(tmp_path, "detect_project_root; echo rc=$?")

        assert result.stdout.strip().splitlines()[0] == str(tmp_path)
        assert "rc=0" in result.stdout


class TestDetectInstallModeReadsOnlyTheConfig:
    def test_ignores_a_link_only_marker_directory(self, tmp_path: Path) -> None:
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "hooks-daemon.yaml").write_text(
            "daemon:\n  self_install_mode: true\n", encoding="utf-8"
        )
        marker_bin = claude_dir / "hooks-daemon" / "bin"
        marker_bin.mkdir(parents=True)
        (marker_bin / "hooks-daemon").symlink_to(tmp_path / "bin" / "hooks-daemon")

        result = _run(tmp_path, f'detect_install_mode "{tmp_path}"')

        assert result.stdout.strip() == "self-install", result.stderr

    def test_reports_normal_when_the_config_says_so_despite_a_real_clone(
        self, tmp_path: Path
    ) -> None:
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "hooks-daemon.yaml").write_text(
            "daemon:\n  self_install_mode: false\n", encoding="utf-8"
        )
        real_clone = claude_dir / "hooks-daemon"
        real_clone.mkdir(parents=True)
        (real_clone / "pyproject.toml").write_text(
            '[project]\nname = "claude-code-hooks-daemon"\n', encoding="utf-8"
        )

        result = _run(tmp_path, f'detect_install_mode "{tmp_path}"')

        assert result.stdout.strip() == "normal", result.stderr
