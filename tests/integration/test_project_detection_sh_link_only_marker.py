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

import subprocess
import sys
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_PROJECT_DETECTION_SH: Final[Path] = _REPO_ROOT / "scripts" / "install" / "project_detection.sh"
_OUTPUT_SH: Final[Path] = _REPO_ROOT / "scripts" / "install" / "output.sh"

_TIMEOUT_SECONDS: Final[int] = 30


def _run(
    project_root: Path,
    script: str,
    extra_env: dict[str, str] | None = None,
    resolved_python: str | None = sys.executable,
) -> subprocess.CompletedProcess[str]:
    """Run ``script`` after sourcing a copy of project_detection.sh.

    ``resolved_python`` becomes HOOKS_DAEMON_PYTHON, the interpreter the
    prerequisite check would have exported; None leaves it unset.
    """
    lib_dir = project_root / "lib"
    lib_dir.mkdir(exist_ok=True)
    guard_copy = lib_dir / "project_detection.sh"
    guard_copy.write_text(_PROJECT_DETECTION_SH.read_text(encoding="utf-8"), encoding="utf-8")
    (lib_dir / "output.sh").write_text(_OUTPUT_SH.read_text(encoding="utf-8"), encoding="utf-8")
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(project_root)}
    if resolved_python is not None:
        env["HOOKS_DAEMON_PYTHON"] = resolved_python
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", "-c", f'source "{guard_copy}"\n{script}'],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        env=env,
        check=False,
        cwd=str(project_root),
    )


class TestDetectProjectRootIgnoresALinkOnlyMarker:
    def test_a_link_only_marker_does_not_satisfy_the_fallback_signal(self, tmp_path: Path) -> None:
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


class TestDetectInstallModeUsesTheResolvedInterpreter:
    def _write_self_install_config(self, root: Path) -> None:
        (root / ".claude").mkdir()
        (root / ".claude" / "hooks-daemon.yaml").write_text(
            "daemon:\n  self_install_mode: true\n", encoding="utf-8"
        )

    def test_a_python3_first_on_path_is_never_run(self, tmp_path: Path) -> None:
        self._write_self_install_config(tmp_path)
        fake_bin = tmp_path / "fakebin"
        fake_bin.mkdir()
        marker = tmp_path / "fake-python3-ran"
        fake = fake_bin / "python3"
        fake.write_text(f"#!/bin/sh\ntouch {marker}\necho normal\n", encoding="utf-8")
        fake.chmod(0o755)

        result = _run(
            tmp_path,
            f'detect_install_mode "{tmp_path}"',
            extra_env={"PATH": f"{fake_bin}:/usr/bin:/bin"},
        )

        assert result.stdout.strip() == "self-install", result.stderr
        assert not marker.exists()

    def test_no_resolved_interpreter_fails_loudly(self, tmp_path: Path) -> None:
        self._write_self_install_config(tmp_path)

        result = _run(
            tmp_path,
            f'detect_install_mode "{tmp_path}"; echo rc=$?',
            resolved_python=None,
        )

        assert "rc=1" in result.stdout, result.stdout
        assert "no resolved Python interpreter" in result.stderr

    def test_interpreter_without_pyyaml_fails_loudly(self, tmp_path: Path) -> None:
        self._write_self_install_config(tmp_path)
        no_yaml = tmp_path / "no-yaml-python"
        no_yaml.write_text(
            "#!/bin/sh\necho 'PyYAML is not importable from stub' >&2\nexit 1\n",
            encoding="utf-8",
        )
        no_yaml.chmod(0o755)

        result = _run(
            tmp_path,
            f'detect_install_mode "{tmp_path}"; echo rc=$?',
            resolved_python=str(no_yaml),
        )

        assert "rc=1" in result.stdout, result.stdout
        assert "could not read" in result.stderr
