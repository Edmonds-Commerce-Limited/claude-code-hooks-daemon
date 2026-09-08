"""The optimise procedure must find the config-changes manifests on a CLIENT install.

Plan 00362 Task 1.8 (report section 8). ``optimise-invoke.sh`` told the
procedure to read ``CLAUDE/UPGRADES/config-changes/v*.yaml`` — a path
relative to the PROJECT root. That tree exists at the project root only in
the daemon's own repository; a client project holds the daemon as a checkout
under ``.claude/hooks-daemon/``, so the manifests live at
``.claude/hooks-daemon/CLAUDE/UPGRADES/config-changes/``. The instruction
then said "if the directory does not exist, skip silently", so on every
client install Step 0 skipped and the "new since vX" recommendations never
surfaced.

The script already resolves the daemon CLI for both layouts; it must resolve
the manifests directory the same way and print it, so the procedure reads a
path that exists instead of a path that only exists here.

Behavioural: builds a client-shaped and a self-install-shaped project and
runs the real script in each.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_SKILL_SOURCE: Final[Path] = (
    _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "skills" / "hooks-daemon"
)
_SCRIPT: Final[Path] = _SKILL_SOURCE / "scripts" / "optimise-invoke.sh"
_OPTIMISE_MD: Final[Path] = _SKILL_SOURCE / "optimise.md"
_DEPLOYED_SKILL: Final[Path] = _REPO_ROOT / ".claude" / "skills" / "hooks-daemon"

_MANIFESTS_SUBPATH: Final[Path] = Path("CLAUDE") / "UPGRADES" / "config-changes"
_MANIFESTS_LINE: Final[re.Pattern[str]] = re.compile(
    r"^- Manifests:\s+(?P<path>\S.*)$", re.MULTILINE
)
_GIT: Final[str] = shutil.which("git") or "/usr/bin/git"
_TIMEOUT_SECONDS: Final[int] = 60

#: The project-relative spelling that only resolves in the daemon's own repo.
_PROJECT_RELATIVE_MANIFESTS: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w/])CLAUDE/UPGRADES/config-changes/"
)

_STUB_CLI: Final[str] = "#!/usr/bin/env bash\necho stub\n"


def _git_init(root: Path) -> None:
    subprocess.run(
        [_GIT, "init", "-q", str(root)],
        check=True,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
    )


def _make_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run_script(project_root: Path) -> str:
    env = dict(os.environ)
    result = subprocess.run(
        ["bash", str(_SCRIPT)],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _printed_manifests_dir(stdout: str) -> Path:
    match = _MANIFESTS_LINE.search(stdout)
    assert match is not None, (
        "optimise-invoke.sh does not print a '- Manifests:' line in its Detected "
        "Environment block, so the procedure has no resolved manifest path to read.\n"
        f"stdout was:\n{stdout}"
    )
    return Path(match.group("path").strip())


@pytest.fixture
def client_project(tmp_path: Path) -> Path:
    """A client-shaped install: the daemon is a checkout under .claude/hooks-daemon/."""
    root = tmp_path / "client"
    root.mkdir()
    _git_init(root)
    daemon_dir = root / ".claude" / "hooks-daemon"
    _make_executable(daemon_dir / "bin" / "hooks-daemon", _STUB_CLI)
    manifests = daemon_dir / _MANIFESTS_SUBPATH
    manifests.mkdir(parents=True)
    (manifests / "v3.43.0.yaml").write_text('version: "3.43.0"\ndate: "2026-07-16"\n')
    (root / ".claude" / "hooks-daemon.yaml").write_text("handlers: {}\n")
    return root


@pytest.fixture
def self_install_project(tmp_path: Path) -> Path:
    """A self-install: the project root IS the daemon checkout."""
    root = tmp_path / "daemon"
    root.mkdir()
    _git_init(root)
    _make_executable(root / "bin" / "hooks-daemon", _STUB_CLI)
    (root / _MANIFESTS_SUBPATH).mkdir(parents=True)
    (root / ".claude").mkdir()
    (root / ".claude" / "hooks-daemon.yaml").write_text("handlers: {}\n")
    return root


class TestManifestsDirResolvesOnEveryLayout:
    def test_client_install_points_inside_daemon_checkout(self, client_project: Path) -> None:
        printed = _printed_manifests_dir(_run_script(client_project))
        expected = client_project / ".claude" / "hooks-daemon" / _MANIFESTS_SUBPATH
        assert printed.resolve() == expected.resolve(), (
            f"On a client install the manifests live under the daemon checkout "
            f"({expected}), but the script printed {printed}."
        )
        assert printed.is_dir(), f"printed manifests dir does not exist: {printed}"
        assert sorted(p.name for p in printed.glob("v*.yaml")) == ["v3.43.0.yaml"]

    def test_self_install_points_at_project_root(self, self_install_project: Path) -> None:
        printed = _printed_manifests_dir(_run_script(self_install_project))
        expected = self_install_project / _MANIFESTS_SUBPATH
        assert printed.resolve() == expected.resolve()
        assert printed.is_dir()


class TestProcedureTextReadsTheResolvedPath:
    """The instruction body must reference the printed value, never the repo-only path."""

    @pytest.mark.parametrize(
        "doc",
        [
            pytest.param(_SCRIPT, id="optimise-invoke.sh"),
            pytest.param(_OPTIMISE_MD, id="optimise.md"),
        ],
    )
    def test_source_has_no_project_relative_manifest_path(self, doc: Path) -> None:
        hits = _PROJECT_RELATIVE_MANIFESTS.findall(doc.read_text(encoding="utf-8"))
        assert not hits, (
            f"{doc.name} still refers to the manifests by the project-relative path "
            "'CLAUDE/UPGRADES/config-changes/', which only exists in the daemon's own "
            "repository. Reference the resolved MANIFESTS_DIR (printed by the script) "
            "or the daemon-checkout path instead."
        )

    def test_step_0_names_the_printed_variable(self) -> None:
        text = _SCRIPT.read_text(encoding="utf-8")
        assert "MANIFESTS_DIR" in text
        assert "check-config-migrations" in text, (
            "Step 0 should hand the range comparison to the daemon's own reader "
            "(DAEMON_CLI check-config-migrations) rather than have the procedure "
            "re-implement manifest parsing by hand."
        )

    def test_step_0_does_not_skip_silently(self) -> None:
        text = _SCRIPT.read_text(encoding="utf-8")
        assert "skip this step silently" not in text, (
            "A missing manifests directory on an install is a broken install, not a "
            "project that chose not to vendor the tree; the procedure must say so."
        )

    @pytest.mark.skipif(not _DEPLOYED_SKILL.is_dir(), reason="deployed skill copy absent")
    @pytest.mark.parametrize("name", ["scripts/optimise-invoke.sh", "optimise.md"])
    def test_deployed_copy_matches_source(self, name: str) -> None:
        source = (_SKILL_SOURCE / name).read_text(encoding="utf-8")
        deployed = (_DEPLOYED_SKILL / name).read_text(encoding="utf-8")
        assert deployed == source, (
            f".claude/skills/hooks-daemon/{name} has drifted from its src/ source; "
            "the deployed copy is what this repo runs, the source is what ships."
        )
