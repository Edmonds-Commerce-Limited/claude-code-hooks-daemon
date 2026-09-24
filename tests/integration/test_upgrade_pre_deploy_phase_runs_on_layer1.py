"""The pre-deploy phase and its gate run on the Layer 1 route (Plan 00376).

Every normal upgrade goes through Layer 1 (``scripts/upgrade.sh``), which
checks the target out and only then runs the target's own Layer 2. Layer 2's
"already at the target" test is therefore always true on that route, and its
idempotent path used to exit before the config compatibility check and the
upgrade-guide reading list, so neither ever ran for a real upgrade (Task 1.1).

These tests drive the real route end to end in a scratch fixture: a daemon
origin whose ``v{current}`` tag is this working tree, whose next-minor tag
adds an upgrade guide, a pre-upgrade task and a post-upgrade task, whose
next-major tag sits on top of that, plus a branch carrying a task staged under
``UNRELEASED/``. A project installed from ``v{current}`` -- holding one call
site the pre-upgrade task detects -- is upgraded with the working tree's
Layer 1, and:

* without ``--skip-reading-confirmation`` the gate stops the upgrade with the
  reading list and the call site at ``file:line``, Layer 1 exits with the
  gate's code, the daemon checkout is back on ``v{current}`` and nothing is
  deployed (Tasks 1.2, 3.1, 3.3);
* with the flag, the compatibility check and the reading list run BEFORE
  anything is deployed, and the post-upgrade task list names the target's
  task, with the call site the post-upgrade task detects (Task 4.1);
* a branch install lists the staged ``UNRELEASED/`` task in both lists;
* a MAJOR upgrade also needs the owner's one-shot approval, which the run it
  lets through consumes (Task 3.2).
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
from claude_code_hooks_daemon.daemon.install_layout import get_untracked_dir
from claude_code_hooks_daemon.install.upgrade_gate import (
    APPROVAL_SUBDIR,
    SKIP_READING_FLAG,
    GateVerdict,
)
from claude_code_hooks_daemon.utils.one_shot_approval import OneShotApprovalStore
from claude_code_hooks_daemon.version import __version__

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_LAYER1: Final[Path] = _REPO_ROOT / "scripts" / "upgrade.sh"
_BASH: Final[str] = shutil.which("bash") or "/bin/bash"
_UPGRADE_TIMEOUT_SECONDS: Final[int] = 600
_GIT_TIMEOUT_SECONDS: Final[int] = 120
_BRANCH: Final[str] = "e2e-staged"
_GUIDE_TASK: Final[str] = "01-e2e-fixture-task.md"
_PRE_TASK: Final[str] = "01-e2e-pre-task.md"
_STAGED_TASK: Final[str] = "99-e2e-staged-task.md"
_HOSTNAME_PREFIX: Final[str] = "pre-deploy-e2e-"
#: A call site in the fixture project that both fixture tasks detect.
_CALL_SITE_FILE: Final[str] = "tools/qa.sh"
_CALL_SITE: Final[str] = "e2e-fixture-command --json"

_GATE_MARKER: Final[str] = "Pre-deploy gate"
_COMPAT_MARKER: Final[str] = "Checking config compatibility with target version"
_READING_MARKER: Final[str] = "REQUIRED READING"
_STOPPED_MARKER: Final[str] = "UPGRADE STOPPED before anything was deployed"
_TASKS_MARKER: Final[str] = "Post-upgrade tasks to carry out"
#: The first deploy action on the idempotent path: nothing before it has
#: touched the project.
_FIRST_DEPLOY_MARKER: Final[str] = "Deploying hooks to project"

_TASK_BODY: Final[str] = """# Task: {title}

**Type**: notification
**Severity**: optional
**Applies to**: all
**Idempotent**: yes
**Detect**: `e2e-fixture-command[^\\n]*--json`
**Detect in**: `*.sh`

## Why

End-to-end fixture.

## How to detect if this applies to you

The gate runs the pattern.

## How to handle

Nothing.

## How to confirm

Nothing.
"""

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is needed to build the venv"),
]


def _next_minor(version: str) -> str:
    major, minor, _patch = (int(part) for part in version.split("."))
    return f"{major}.{minor + 1}.0"


def _next_major(version: str) -> str:
    return f"{int(version.split('.')[0]) + 1}.0.0"


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


def _build_origin(root: Path, current: str, target: str, major: str) -> Path:
    """``v{current}``, ``v{target}``, ``v{major}`` on top, and a branch off ``v{current}``."""
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
    _write(guide_dir / "pre-upgrade-tasks" / _PRE_TASK, _TASK_BODY.format(title="pre task"))
    _set_version(origin, current, target)
    _git(origin, "add", "-A")
    _git(origin, "commit", "-q", "--no-verify", "-m", f"v{target}")
    _git(origin, "tag", f"v{target}")

    _set_version(origin, target, major)
    _git(origin, "add", "-A")
    _git(origin, "commit", "-q", "--no-verify", "-m", f"v{major}")
    _git(origin, "tag", f"v{major}")

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
    _write(project / _CALL_SITE_FILE, f"set -e\n{_CALL_SITE} | jq .\n")
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
    origin = _build_origin(tmp_path, current, target, _next_major(current))
    project, daemon_dir = _build_project(tmp_path, origin, current)
    return project, daemon_dir, current, target


def _head(daemon_dir: Path) -> str:
    return _git(daemon_dir, "rev-parse", "HEAD").strip()


def _commit_of(daemon_dir: Path, tag: str) -> str:
    return _git(daemon_dir, "rev-parse", f"{tag}^{{commit}}").strip()


def _assert_stopped_and_restored(
    result: subprocess.CompletedProcess[str],
    verdict: GateVerdict,
    project: Path,
    daemon_dir: Path,
    current: str,
) -> str:
    combined = result.stdout
    assert result.returncode == verdict.exit_code, (
        f"Layer 1 must exit with the gate's code {verdict.exit_code}, "
        f"got {result.returncode}:\n{combined[-6000:]}"
    )
    assert _STOPPED_MARKER in combined, combined[-6000:]
    assert _FIRST_DEPLOY_MARKER not in combined, "a stopped upgrade must deploy nothing"
    assert not (project / ".claude" / "hooks").exists(), "no hook may reach the project"
    assert _head(daemon_dir) == _commit_of(
        daemon_dir, f"v{current}"
    ), "the daemon checkout must be back on the previous version"
    return combined


def test_release_route_stops_until_the_reading_is_confirmed(
    fixture_tree: tuple[Path, Path, str, str],
) -> None:
    project, daemon_dir, current, target = fixture_tree
    env = _env()
    try:
        stopped = _upgrade(project, env, f"v{target}")
        combined = _assert_stopped_and_restored(
            stopped, GateVerdict.NEEDS_ACKNOWLEDGEMENT, project, daemon_dir, current
        )
        reading = _section(combined, _READING_MARKER)
        assert f"v{current}-to-v{target}.md" in reading, reading
        assert _PRE_TASK in reading, reading
        assert f"{_CALL_SITE_FILE}:2" in reading, "the call site must be named at file:line"
        assert SKIP_READING_FLAG in combined

        result = _upgrade(project, env, f"v{target}", SKIP_READING_FLAG)
    finally:
        _stop_daemon(daemon_dir, project, env)
    combined = result.stdout
    assert result.returncode == 0, f"upgrade failed ({result.returncode}):\n{combined[-6000:]}"

    gate_at = _position(combined, _GATE_MARKER)
    compat_at = _position(combined, _COMPAT_MARKER)
    reading_at = _position(combined, _READING_MARKER)
    deploy_at = _position(combined, _FIRST_DEPLOY_MARKER)
    assert gate_at < deploy_at, "the gate must decide before anything is deployed"
    assert compat_at < deploy_at, "the compatibility check must run before anything is deployed"
    assert reading_at < deploy_at, "the reading list must be shown before anything is deployed"

    reading = _section(combined, _READING_MARKER)
    assert _STAGED_TASK not in reading, "a release install must not list staged documents"

    tasks = _section(combined, _TASKS_MARKER)
    assert _GUIDE_TASK in tasks, tasks
    assert f"{_CALL_SITE_FILE}:2" in tasks, "the post-upgrade report must run detection too"


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
        result = _upgrade(project, env, SKIP_READING_FLAG)
    finally:
        _stop_daemon(daemon_dir, project, env)
    combined = result.stdout
    assert result.returncode == 0, f"upgrade failed ({result.returncode}):\n{combined[-6000:]}"

    assert _position(combined, _COMPAT_MARKER) < _position(combined, _FIRST_DEPLOY_MARKER)
    reading = _section(combined, _READING_MARKER)
    assert re.search(rf"UNRELEASED/post-upgrade-tasks/{re.escape(_STAGED_TASK)}", reading), reading

    tasks = _section(combined, _TASKS_MARKER)
    assert _STAGED_TASK in tasks, tasks


def test_major_route_needs_the_owners_one_shot_approval(
    fixture_tree: tuple[Path, Path, str, str],
) -> None:
    project, daemon_dir, current, _target = fixture_tree
    major = _next_major(current)
    env = _env()
    store = OneShotApprovalStore(APPROVAL_SUBDIR)
    marker = store.path(get_untracked_dir(project), major)
    try:
        stopped = _upgrade(project, env, f"v{major}", SKIP_READING_FLAG)
        combined = _assert_stopped_and_restored(
            stopped, GateVerdict.NEEDS_APPROVAL, project, daemon_dir, current
        )
        assert "MAJOR" in combined
        assert f"approve-upgrade {major}" in combined

        # The owner's step, as `hooks-daemon approve-upgrade` records it.
        store.record(get_untracked_dir(project), major)
        result = _upgrade(project, env, f"v{major}", SKIP_READING_FLAG)
    finally:
        _stop_daemon(daemon_dir, project, env)
    assert result.returncode == 0, f"upgrade failed ({result.returncode}):\n{result.stdout[-6000:]}"
    assert not marker.exists(), "the approval is one-shot: the run it let through consumes it"
    assert _head(daemon_dir) == _commit_of(daemon_dir, f"v{major}")
