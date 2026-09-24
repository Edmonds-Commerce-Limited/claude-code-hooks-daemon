"""The pre-deploy phase runs on the Layer 1 route (Plan 00376 Task 1.1).

Every normal upgrade goes through Layer 1 (``scripts/upgrade.sh``), which
checks the target out and only then runs the target's own Layer 2. Layer 2's
"already at the target" test is therefore always true on that route, and its
idempotent path used to exit before the config compatibility check and the
upgrade-guide reading list, so neither ever ran for a real upgrade. Invoked
directly, both ran against the pre-checkout tree, which cannot hold a guide
for the version being installed.

These tests drive the real route end to end in a scratch fixture: a daemon
origin whose ``v{current}`` tag is this working tree and whose next-minor tag
adds an upgrade guide and a post-upgrade task, plus a branch carrying a task
staged under ``UNRELEASED/``. A project installed from ``v{current}`` is
upgraded with the working tree's Layer 1, and the output must show:

* the compatibility check and the reading list, evaluated against the FROM
  version and the TARGET's guides, BEFORE anything is deployed;
* the post-upgrade task list, naming the target's task;
* for a branch install, the staged ``UNRELEASED/`` task in both lists.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404 - trusted system tools (git, bash) for fixtures
import sys
import time
from pathlib import Path
from typing import Final

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.version import __version__

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_LAYER1: Final[Path] = _REPO_ROOT / "scripts" / "upgrade.sh"
_BASH: Final[str] = shutil.which("bash") or "/bin/bash"
_UPGRADE_TIMEOUT_SECONDS: Final[int] = 600
_GIT_TIMEOUT_SECONDS: Final[int] = 120
_BRANCH: Final[str] = "e2e-staged"
_GUIDE_TASK: Final[str] = "01-e2e-fixture-task.md"
_STAGED_TASK: Final[str] = "99-e2e-staged-task.md"
_HOSTNAME_PREFIX: Final[str] = "pre-deploy-e2e-"

_COMPAT_MARKER: Final[str] = "Checking config compatibility with target version"
_READING_MARKER: Final[str] = "REQUIRED READING"
_TASKS_MARKER: Final[str] = "Post-upgrade tasks to carry out"
#: The first deploy action on the idempotent path: nothing before it has
#: touched the project.
_FIRST_DEPLOY_MARKER: Final[str] = "Deploying hooks to project"

_TASK_BODY: Final[str] = """# Task: {title}

**Type**: notification
**Severity**: optional
**Applies to**: all
**Idempotent**: yes

## Why

End-to-end fixture.
"""

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is needed to build the venv"),
]


def _next_minor(version: str) -> str:
    major, minor, _patch = (int(part) for part in version.split("."))
    return f"{major}.{minor + 1}.0"


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=e2e", "-c", "user.email=e2e@example.invalid", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    return result.stdout


def _snapshot_working_tree(dest: Path) -> None:
    """Copy every tracked or unignored file of the working tree into ``dest``.

    The working tree, not HEAD, so the fixture runs the code under test
    whether or not it has been committed.
    """
    listing = _git(_REPO_ROOT, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    for rel in filter(None, listing.split("\0")):
        source = _REPO_ROOT / rel
        if not source.exists() and not source.is_symlink():
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)


def _set_version(tree: Path, old: str, new: str) -> None:
    for rel, pattern in (
        ("pyproject.toml", 'version = "{v}"'),
        ("src/claude_code_hooks_daemon/version.py", '__version__ = "{v}"'),
    ):
        path = tree / rel
        text = path.read_text()
        before = pattern.format(v=old)
        assert before in text, f"{rel} does not carry {before!r}"
        path.write_text(text.replace(before, pattern.format(v=new), 1))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _build_origin(root: Path, current: str, target: str) -> Path:
    """An origin with ``v{current}``, ``v{target}`` and a branch off ``v{current}``."""
    origin = root / "origin"
    origin.mkdir()
    _snapshot_working_tree(origin)
    _git(origin, "init", "-q", "-b", "main")
    # --force: a few files (uv.lock among them) are tracked despite matching
    # .gitignore, and the snapshot holds nothing else that is ignored.
    _git(origin, "add", "-A", "--force")
    _git(origin, "commit", "-q", "--no-verify", "-m", f"v{current}")
    _git(origin, "tag", f"v{current}")

    guide = f"v{current}-to-v{target}"
    guide_dir = origin / "CLAUDE" / "UPGRADES" / "v3" / guide
    _write(guide_dir / f"{guide}.md", f"# {guide}\n")
    _write(guide_dir / "post-upgrade-tasks" / _GUIDE_TASK, _TASK_BODY.format(title="guide task"))
    _set_version(origin, current, target)
    _git(origin, "add", "-A")
    _git(origin, "commit", "-q", "--no-verify", "-m", f"v{target}")
    _git(origin, "tag", f"v{target}")

    _git(origin, "checkout", "-q", "-b", _BRANCH, f"v{current}")
    staged = origin / "CLAUDE" / "UPGRADES" / "UNRELEASED" / "post-upgrade-tasks" / _STAGED_TASK
    _write(staged, _TASK_BODY.format(title="staged task"))
    _git(origin, "add", "-A")
    _git(origin, "commit", "-q", "--no-verify", "-m", "staged task")
    _git(origin, "checkout", "-q", "main")
    return origin


def _build_project(root: Path, origin: Path, current: str) -> tuple[Path, Path]:
    """A client project whose daemon clone sits on ``v{current}``, with no venv yet."""
    project = root / "project"
    (project / ".claude").mkdir(parents=True)
    _git(project, "init", "-q")
    # The daemon refuses to start in a project with no remote origin.
    _git(project, "remote", "add", "origin", "https://example.invalid/project.git")
    shutil.copy2(
        origin / ".claude" / "hooks-daemon.yaml.example", project / ".claude" / "hooks-daemon.yaml"
    )
    daemon_dir = project / ".claude" / "hooks-daemon"
    _git(root, "clone", "-q", str(origin), str(daemon_dir))
    _git(daemon_dir, "checkout", "-q", f"v{current}")
    return project, daemon_dir


def _stop_daemon(daemon_dir: Path, project: Path, env: dict[str, str]) -> None:
    for venv_python in sorted((daemon_dir / "untracked").glob("venv-*py3*/bin/python")):
        subprocess.run(
            [str(venv_python), "-m", "claude_code_hooks_daemon.daemon.cli", "stop"],
            cwd=project,
            capture_output=True,
            text=True,
            check=False,
            timeout=Timeout.DAEMON_SHUTDOWN,
            env=env,
        )


def _upgrade(project: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    """Run Layer 1 with stderr merged into stdout, so marker ORDER is real."""
    return subprocess.run(
        [_BASH, str(_LAYER1), "--project-root", str(project), *args],
        cwd=project,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
        env=env,
        timeout=_UPGRADE_TIMEOUT_SECONDS,
    )


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    for name in (
        "CI",
        "HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP",
        "HOOKS_DAEMON_UNSAFE_TRACK_REF",
        "HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE",
        "HOOKS_DAEMON_UPGRADE_PREVIOUS_VERSION",
        "HOOKS_DAEMON_UPGRADE_SECOND_PASS",
    ):
        env.pop(name, None)
    env["NO_COLOR"] = "1"
    env["HOSTNAME"] = f"{_HOSTNAME_PREFIX}{os.getpid()}-{int(time.time())}"
    env["HOOKS_DAEMON_PYTHON"] = sys.executable
    env.update(extra or {})
    return env


def _position(output: str, marker: str) -> int:
    at = output.find(marker)
    assert at != -1, f"{marker!r} never appeared in the upgrade output:\n{output[-6000:]}"
    return at


def _section(output: str, marker: str) -> str:
    """The output from ``marker`` up to the next blank-line-separated block end."""
    start = _position(output, marker)
    end = output.find("\n\n\n", start)
    return output[start : end if end != -1 else len(output)]


@pytest.fixture
def fixture_tree(tmp_path: Path) -> tuple[Path, Path, str, str]:
    current = __version__
    target = _next_minor(current)
    origin = _build_origin(tmp_path, current, target)
    project, daemon_dir = _build_project(tmp_path, origin, current)
    return project, daemon_dir, current, target


def test_release_route_checks_the_targets_guides_before_deploying(
    fixture_tree: tuple[Path, Path, str, str],
) -> None:
    project, daemon_dir, current, target = fixture_tree
    env = _env()
    try:
        result = _upgrade(project, env, f"v{target}")
    finally:
        _stop_daemon(daemon_dir, project, env)
    combined = result.stdout
    assert result.returncode == 0, f"upgrade failed ({result.returncode}):\n{combined[-6000:]}"

    compat_at = _position(combined, _COMPAT_MARKER)
    reading_at = _position(combined, _READING_MARKER)
    deploy_at = _position(combined, _FIRST_DEPLOY_MARKER)
    assert compat_at < deploy_at, "the compatibility check must run before anything is deployed"
    assert reading_at < deploy_at, "the reading list must be shown before anything is deployed"

    reading = _section(combined, _READING_MARKER)
    assert f"v{current}-to-v{target}.md" in reading, reading
    assert _STAGED_TASK not in reading, "a release install must not list staged documents"

    tasks = _section(combined, _TASKS_MARKER)
    assert _GUIDE_TASK in tasks, tasks


def test_branch_route_includes_the_staged_unreleased_task(
    fixture_tree: tuple[Path, Path, str, str],
) -> None:
    project, daemon_dir, _current, _target = fixture_tree
    env = _env(
        {
            "HOOKS_DAEMON_UNSAFE_TRACK_REF": _BRANCH,
            "HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE": "end-to-end fixture",
        }
    )
    try:
        result = _upgrade(project, env)
    finally:
        _stop_daemon(daemon_dir, project, env)
    combined = result.stdout
    assert result.returncode == 0, f"upgrade failed ({result.returncode}):\n{combined[-6000:]}"

    assert _position(combined, _COMPAT_MARKER) < _position(combined, _FIRST_DEPLOY_MARKER)
    reading = _section(combined, _READING_MARKER)
    assert re.search(rf"UNRELEASED/post-upgrade-tasks/{re.escape(_STAGED_TASK)}", reading), reading

    tasks = _section(combined, _TASKS_MARKER)
    assert _STAGED_TASK in tasks, tasks
