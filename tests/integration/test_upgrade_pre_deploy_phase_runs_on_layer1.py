"""The pre-deploy phase and its gate run on every upgrade route (Plan 00376).

Every normal upgrade goes through Layer 1 (``scripts/upgrade.sh``), which
checks the target out and only then runs the target's own Layer 2. Layer 2's
"already at the target" test is therefore always true on that route, and its
idempotent path used to exit before the config compatibility check and the
upgrade-guide reading list, so neither ever ran for a real upgrade (Task 1.1).

These tests drive the real routes end to end in a scratch fixture: a daemon
origin whose ``v{current}`` tag is this working tree, whose next-minor tag
adds an upgrade guide, a pre-upgrade task and a post-upgrade task, whose
next-major tag sits on top of that, plus a branch carrying a task staged under
``UNRELEASED/``. A project installed from ``v{current}`` -- its committed
``HOOKS-DAEMON.md`` says so, and it holds one call site the pre-upgrade task
detects -- is upgraded with the working tree's Layer 1, and:

* without ``--skip-reading-confirmation=<digest>`` the gate stops the upgrade
  with the reading list, the call site at ``file:line`` and the digest; Layer
  1 exits with the gate's code, the daemon checkout is back on ``v{current}``
  and nothing is deployed (Tasks 1.2, 3.1, 3.3); a bare flag does not match;
* with the digest, the compatibility check and the reading list run BEFORE
  anything is deployed, and the post-upgrade task list names the target's
  task, with the call site the post-upgrade task detects (Task 4.1);
* a branch install lists the staged ``UNRELEASED/`` task in both lists;
* a MAJOR upgrade also needs the owner's approval, written by the owner's own
  route and bound to this upgrade; a hand-made marker does not count, and the
  run the approval lets through removes it (Task 3.2).

And the routes review-00376 found open (MAJOR 1, 2 and 4):

* a fresh clone (no daemon checkout, so Layer 1 clones one sitting on origin's
  newest commit) still reads the installed version from ``HOOKS-DAEMON.md``,
  stops, and is put back on it, so the re-run stops again;
* LLM-UPDATE's manual route (the clone checked out to the target by hand)
  still stops, and still needs the owner for a MAJOR target;
* no environment variable switches the gate off, and an inherited handoff is
  ignored;
* a Layer 1 that predates the gate (v3.66.0's) cannot make a stop into a
  partial install: Layer 2 restores the clone itself and says the caller's
  exit status is wrong.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
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
    write_approval,
)
from claude_code_hooks_daemon.utils.one_shot_approval import OneShotApprovalStore
from claude_code_hooks_daemon.version import __version__
from tests.load_scaling import scaled_seconds

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_LAYER1: Final[Path] = _REPO_ROOT / "scripts" / "upgrade.sh"
_LAYER2_REL: Final[str] = "scripts/upgrade_version.sh"
#: The last release whose Layer 1 predates the gate (review MAJOR 2).
_PRE_GATE_RELEASE: Final[str] = "v3.66.0"
_BASH: Final[str] = shutil.which("bash") or "/bin/bash"
#: Idle-host budgets, each multiplied by the host load when used (N344). All
#: three only stop a hang in fixture setup, an upgrade run or a teardown.
_UPGRADE_TIMEOUT_SECONDS: Final[int] = 600
_GIT_TIMEOUT_SECONDS: Final[int] = 120
_DAEMON_STOP_TIMEOUT_SECONDS: Final[int] = 3 * Timeout.DAEMON_SHUTDOWN
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
_PRE_GATE_WARNING: Final[str] = "THE UPGRADE DID NOT COMPLETE"
#: The first deploy action on the idempotent path: nothing before it has
#: touched the project.
_FIRST_DEPLOY_MARKER: Final[str] = "Deploying hooks to project"
_DIGEST_RE: Final[re.Pattern[str]] = re.compile(rf"{re.escape(SKIP_READING_FLAG)}=(\w+)")

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
        timeout=scaled_seconds(_GIT_TIMEOUT_SECONDS),
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


def _build_project(root: Path, origin: Path, current: str, *, clone: bool = True) -> Path:
    """A client project installed from ``v{current}``, with no venv yet.

    ``clone=False`` is the fresh-clone state: config and generated docs are
    committed, the daemon checkout is not.
    """
    project = root / "project"
    (project / ".claude").mkdir(parents=True)
    _git(project, "init", "-q")
    # The daemon refuses to start in a project with no remote origin.
    _git(project, "remote", "add", "origin", "https://example.invalid/project.git")
    shutil.copy2(
        origin / ".claude" / "hooks-daemon.yaml.example", project / ".claude" / "hooks-daemon.yaml"
    )
    _write(
        project / ".claude" / "HOOKS-DAEMON.md",
        f"> Generated on 2026-09-24 (v{current}) by `generate-docs`\n",
    )
    _write(project / _CALL_SITE_FILE, f"set -e\n{_CALL_SITE} | jq .\n")
    if clone:
        daemon_dir = project / ".claude" / "hooks-daemon"
        _git(root, "clone", "-q", str(origin), str(daemon_dir))
        _git(daemon_dir, "checkout", "-q", f"v{current}")
    return project


def _daemon_dir(project: Path) -> Path:
    return project / ".claude" / "hooks-daemon"


def _stop_daemon(project: Path, env: dict[str, str]) -> None:
    for venv_python in sorted((_daemon_dir(project) / "untracked").glob("venv-*py3*/bin/python")):
        subprocess.run(
            [str(venv_python), "-m", "claude_code_hooks_daemon.daemon.cli", "stop"],
            cwd=project,
            capture_output=True,
            text=True,
            check=False,
            timeout=scaled_seconds(_DAEMON_STOP_TIMEOUT_SECONDS),
            env=env,
        )


def _run(argv: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run with stderr merged into stdout, so marker ORDER is real."""
    return subprocess.run(
        argv,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
        env=env,
        timeout=scaled_seconds(_UPGRADE_TIMEOUT_SECONDS),
    )


def _upgrade(
    project: Path, env: dict[str, str], *args: str, layer1: Path = _LAYER1
) -> subprocess.CompletedProcess[str]:
    return _run([_BASH, str(layer1), "--project-root", str(project), *args], project, env)


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    for name in (
        "CI",
        "HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP",
        "HOOKS_DAEMON_UNSAFE_TRACK_REF",
        "HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE",
        "HOOKS_DAEMON_UPGRADE_PREVIOUS_VERSION",
        "HOOKS_DAEMON_UPGRADE_SECOND_PASS",
        "HOOKS_DAEMON_UPGRADE_HANDOFF",
        "UPGRADE_FLAGS",
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


def _digest(output: str) -> str:
    found = _DIGEST_RE.search(output)
    assert found is not None, f"the stop printed no digest:\n{output[-6000:]}"
    return found.group(1)


def _confirm(output: str) -> str:
    return f"{SKIP_READING_FLAG}={_digest(output)}"


@pytest.fixture
def versions() -> tuple[str, str, str]:
    current = __version__
    return current, _next_minor(current), _next_major(current)


@pytest.fixture
def origin(tmp_path: Path, versions: tuple[str, str, str]) -> Path:
    return _build_origin(tmp_path, *versions)


@pytest.fixture
def project(tmp_path: Path, origin: Path, versions: tuple[str, str, str]) -> Path:
    return _build_project(tmp_path, origin, versions[0])


def _head(daemon_dir: Path) -> str:
    return _git(daemon_dir, "rev-parse", "HEAD").strip()


def _commit_of(daemon_dir: Path, tag: str) -> str:
    return _git(daemon_dir, "rev-parse", f"{tag}^{{commit}}").strip()


def _assert_stopped_and_restored(
    result: subprocess.CompletedProcess[str],
    verdict: GateVerdict,
    project: Path,
    current: str,
    *,
    exit_code: int | None = None,
) -> str:
    combined = result.stdout
    expected = verdict.exit_code if exit_code is None else exit_code
    assert (
        result.returncode == expected
    ), f"expected exit {expected}, got {result.returncode}:\n{combined[-6000:]}"
    assert _STOPPED_MARKER in combined, combined[-6000:]
    assert _FIRST_DEPLOY_MARKER not in combined, "a stopped upgrade must deploy nothing"
    assert not (project / ".claude" / "hooks").exists(), "no hook may reach the project"
    daemon_dir = _daemon_dir(project)
    assert _head(daemon_dir) == _commit_of(
        daemon_dir, f"v{current}"
    ), "the daemon checkout must be back on the installed version"
    return combined


def test_release_route_stops_until_the_reading_is_confirmed(
    project: Path, versions: tuple[str, str, str]
) -> None:
    current, target, _major = versions
    env = _env()
    try:
        stopped = _upgrade(project, env, f"v{target}")
        combined = _assert_stopped_and_restored(
            stopped, GateVerdict.NEEDS_ACKNOWLEDGEMENT, project, current
        )
        reading = _section(combined, _READING_MARKER)
        assert f"v{current}-to-v{target}.md" in reading, reading
        assert _PRE_TASK in reading, reading
        assert f"{_CALL_SITE_FILE}:2" in reading, "the call site must be named at file:line"

        # Review MINOR 6: the bare flag is not bound to what was listed.
        bare = _upgrade(project, env, f"v{target}", SKIP_READING_FLAG)
        _assert_stopped_and_restored(bare, GateVerdict.NEEDS_ACKNOWLEDGEMENT, project, current)

        result = _upgrade(project, env, f"v{target}", _confirm(combined))
    finally:
        _stop_daemon(project, env)
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
    project: Path, versions: tuple[str, str, str]
) -> None:
    current = versions[0]
    env = _env(
        {
            "HOOKS_DAEMON_UNSAFE_TRACK_REF": _BRANCH,
            "HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE": "end-to-end fixture",
        }
    )
    untracked = get_untracked_dir(project)
    try:
        stopped = _upgrade(project, env)
        _assert_stopped_and_restored(stopped, GateVerdict.NEEDS_ACKNOWLEDGEMENT, project, current)
        confirm = _confirm(stopped.stdout)
        # Plan 00376 review3 (review4 follow-up): the branch was cut off
        # v{current} with no version bump, so its release is the SAME as the
        # installed one -- an untrusted FROM (the doc marker) that has caught
        # up to the target, review2 BLOCKER 1's unknown range. It needs the
        # owner's approval too, not just the reading confirmed.
        approval_needed = _upgrade(project, env, confirm)
        _assert_stopped_and_restored(approval_needed, GateVerdict.NEEDS_APPROVAL, project, current)
        write_approval(
            untracked,
            to_version=current,
            from_version=current,
            daemon_dir=_daemon_dir(project),
            project_root=project,
        )
        result = _upgrade(project, env, confirm)
    finally:
        _stop_daemon(project, env)
    combined = result.stdout
    assert result.returncode == 0, f"upgrade failed ({result.returncode}):\n{combined[-6000:]}"

    assert _position(combined, _COMPAT_MARKER) < _position(combined, _FIRST_DEPLOY_MARKER)
    reading = _section(combined, _READING_MARKER)
    assert re.search(rf"UNRELEASED/post-upgrade-tasks/{re.escape(_STAGED_TASK)}", reading), reading

    tasks = _section(combined, _TASKS_MARKER)
    assert _STAGED_TASK in tasks, tasks


def test_major_route_needs_the_owners_bound_approval(
    project: Path, versions: tuple[str, str, str]
) -> None:
    current, _target, major = versions
    env = _env()
    untracked = get_untracked_dir(project)
    marker = OneShotApprovalStore(APPROVAL_SUBDIR).path(untracked, major)
    try:
        unread = _upgrade(project, env, f"v{major}")
        confirm = _confirm(unread.stdout)
        stopped = _upgrade(project, env, f"v{major}", confirm)
        combined = _assert_stopped_and_restored(
            stopped, GateVerdict.NEEDS_APPROVAL, project, current
        )
        assert "MAJOR" in combined
        assert f"approve-upgrade {major} --from {current}" in combined
        assert "upgrade_gate_standalone.py" in combined, "the new code's own approval route"

        # Review MAJOR 4: a marker nobody's approval wrote does not count.
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        touched = _upgrade(project, env, f"v{major}", confirm)
        assert "not written by approve-upgrade" in _assert_stopped_and_restored(
            touched, GateVerdict.NEEDS_APPROVAL, project, current
        )

        # The owner's step: what `approve-upgrade` writes once they have typed
        # the phrase at their terminal.
        write_approval(
            untracked,
            to_version=major,
            from_version=current,
            daemon_dir=_daemon_dir(project),
            project_root=project,
        )
        result = _upgrade(project, env, f"v{major}", confirm)
    finally:
        _stop_daemon(project, env)
    assert result.returncode == 0, f"upgrade failed ({result.returncode}):\n{result.stdout[-6000:]}"
    assert not marker.exists(), "one approval, one upgrade: the run it let through removes it"
    assert _head(_daemon_dir(project)) == _commit_of(_daemon_dir(project), f"v{major}")


def test_a_fresh_clone_reads_the_installed_version_and_stops_again_on_rerun(
    tmp_path: Path, origin: Path, versions: tuple[str, str, str]
) -> None:
    """Review MAJOR 1: the clone Layer 1 makes already sits past the target."""
    current, target, _major = versions
    project = _build_project(tmp_path, origin, current, clone=False)
    env = _env({"HOOKS_DAEMON_CLONE_URL": str(origin)})
    first = _upgrade(project, env, f"v{target}")
    _assert_stopped_and_restored(first, GateVerdict.NEEDS_ACKNOWLEDGEMENT, project, current)
    rerun = _upgrade(project, env, f"v{target}")
    _assert_stopped_and_restored(rerun, GateVerdict.NEEDS_ACKNOWLEDGEMENT, project, current)


def test_the_manual_route_still_needs_the_reading_and_the_owner(
    project: Path, versions: tuple[str, str, str]
) -> None:
    """Review MAJOR 1: LLM-UPDATE's manual checkout, then the local Layer 1."""
    current, _target, major = versions
    env = _env()
    _git(_daemon_dir(project), "checkout", "-q", f"v{major}")
    unread = _upgrade(project, env, f"v{major}")
    _assert_stopped_and_restored(unread, GateVerdict.NEEDS_ACKNOWLEDGEMENT, project, current)

    _git(_daemon_dir(project), "checkout", "-q", f"v{major}")
    unapproved = _upgrade(project, env, f"v{major}", _confirm(unread.stdout))
    _assert_stopped_and_restored(unapproved, GateVerdict.NEEDS_APPROVAL, project, current)


def test_no_environment_variable_switches_the_gate_off(
    tmp_path: Path, project: Path, versions: tuple[str, str, str]
) -> None:
    """Review MAJOR 4: the exported phase-done sentinel skipped the whole gate."""
    current, _target, major = versions
    forged = tmp_path / "forged-handoff"
    forged.write_text(f"1 {_commit_of(_daemon_dir(project), f'v{major}')}\n")
    env = _env(
        {
            "HOOKS_DAEMON_PRE_DEPLOY_PHASE_DONE": "1",
            "HOOKS_DAEMON_COMPAT_CHECK_DONE": "1",
            "HOOKS_DAEMON_UPGRADE_HANDOFF": str(forged),
        }
    )
    result = _upgrade(project, env, f"v{major}")
    _assert_stopped_and_restored(result, GateVerdict.NEEDS_ACKNOWLEDGEMENT, project, current)


def _fake_gate_interpreter(tmp_path: Path) -> Path:
    """An interpreter that answers for the gate and is Python for everything else."""
    fake = tmp_path / "fake-python"
    fake.write_text(
        "#!/bin/bash\n"
        'for arg in "$@"; do\n'
        '    case "$arg" in *upgrade_gate_standalone.py) echo "gate-verdict=proceed"; exit 0 ;; esac\n'
        "done\n"
        f'exec "{sys.executable}" "$@"\n'
    )
    fake.chmod(0o755)
    return fake


def _forged_venv(tmp_path: Path, stamp: str) -> Path:
    """A 'venv' whose stamp claims the target is already installed."""
    venv = tmp_path / "forged-venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(sys.executable)
    (venv / ".daemon-version").write_text(f"{stamp}\n")
    return venv


@pytest.mark.parametrize("route", ["fake-interpreter", "forged-venv-python"])
def test_no_interpreter_or_venv_override_answers_for_the_gate(
    tmp_path: Path, project: Path, versions: tuple[str, str, str], route: str
) -> None:
    """Review of e27bd73f: HOOKS_DAEMON_PYTHON picked the gate's interpreter and venv."""
    current, _target, major = versions
    if route == "fake-interpreter":
        python = _fake_gate_interpreter(tmp_path)
    else:
        python = _forged_venv(tmp_path, f"v{major}") / "bin" / "python"
    result = _upgrade(project, _env({"HOOKS_DAEMON_PYTHON": str(python)}), f"v{major}")
    _assert_stopped_and_restored(result, GateVerdict.NEEDS_ACKNOWLEDGEMENT, project, current)


_REAL_TIMEOUT: Final[str] = shutil.which("timeout") or "/usr/bin/timeout"
_REAL_GIT: Final[str] = shutil.which("git") or "/usr/bin/git"
#: What a planted tool prints when it is handed the gate: the old stdout verdict.
_FORGED_VERDICT: Final[str] = (
    'case "$*" in *upgrade_gate_standalone.py*) echo gate-verdict=proceed; exit 0 ;; esac\n'
)
_PLANTED_TOOLS: Final[dict[str, tuple[str, str]]] = {
    "timeout": ("timeout", f'#!/bin/bash\n{_FORGED_VERDICT}exec "{_REAL_TIMEOUT}" "$@"\n'),
    "python": (
        "python3.99",
        '#!/bin/bash\nif [ "$1" = "--version" ]; then echo "Python 3.99.0"; exit 0; fi\n'
        f'{_FORGED_VERDICT}exec "{sys.executable}" "$@"\n',
    ),
    # Lists nothing, so a Detect scan through it finds no call site.
    "git": (
        "git",
        '#!/bin/bash\nif [ "$1" = "-C" ] && [ "$3" = "ls-files" ]; then exit 0; fi\n'
        f'exec "{_REAL_GIT}" "$@"\n',
    ),
}


@pytest.mark.parametrize("tool", sorted(_PLANTED_TOOLS))
def test_a_tool_planted_on_path_does_not_answer_for_the_gate(
    tmp_path: Path, project: Path, versions: tuple[str, str, str], tool: str
) -> None:
    """Fresh review BLOCKER 1: the gate took `timeout`, python and git from PATH.

    Run the way the docs say, from the target's own Layer 1 fetched to a file,
    with the planted tool first on PATH: the gate still stops, and still names
    the call site.
    """
    current, target, major = versions
    to = f"v{major}" if tool != "git" else f"v{target}"
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    name, body = _PLANTED_TOOLS[tool]
    planted = fakebin / name
    planted.write_text(body)
    planted.chmod(0o755)
    layer1 = tmp_path / "fetched-upgrade.sh"
    layer1.write_text(_git(_daemon_dir(project), "show", f"{to}:scripts/upgrade.sh"))
    env = _env({"PATH": f"{fakebin}:{os.environ['PATH']}"})
    result = _upgrade(project, env, to, layer1=layer1)
    combined = _assert_stopped_and_restored(
        result, GateVerdict.NEEDS_ACKNOWLEDGEMENT, project, current
    )
    assert f"{_CALL_SITE_FILE}:2" in _section(combined, _READING_MARKER)


#: A `.pth` line that does what code inside the gate's process could: read the
#: verdict file and nonce from argv and write the verdict itself.
_FORGING_PTH: Final[str] = (
    "import os, sys; a = sys.argv; "
    "(open(a[a.index('--verdict-file') + 1], 'w').write("
    "'nonce=' + a[a.index('--nonce') + 1] + '\\nverdict=proceed\\n'), os._exit(0)) "
    "if '--verdict-file' in a else None\n"
)


def test_code_planted_in_the_installed_venv_does_not_answer_for_the_gate(
    project: Path, versions: tuple[str, str, str]
) -> None:
    """Fresh review BLOCKER 1b: the gate ran on the installed venv's Python.

    That venv sits in the project, where an agent can write, and a `.pth` in
    its site-packages runs inside the gate's own process even under `-I`, so a
    verdict file bound to a nonce proves nothing about it.
    """
    current, _target, major = versions
    env = _env()
    untracked = get_untracked_dir(project)
    try:
        # Plan 00376 review3 (review4 follow-up): review2 BLOCKER 1 made an
        # untrusted FROM (the doc marker, no venv stamp yet) that has caught
        # up to or passed the target an unknown range -- which this bootstrap
        # install (installing the currently-installed release, to build the
        # first venv) now is. It needs the reading confirmed AND the owner's
        # approval, exactly like `test_major_route_needs_the_owners_bound_approval`.
        unread = _upgrade(project, env, f"v{current}")
        confirm = _confirm(unread.stdout)
        stopped = _upgrade(project, env, f"v{current}", confirm)
        _assert_stopped_and_restored(stopped, GateVerdict.NEEDS_APPROVAL, project, current)
        write_approval(
            untracked,
            to_version=current,
            from_version=current,
            daemon_dir=_daemon_dir(project),
            project_root=project,
        )
        installed = _upgrade(project, env, f"v{current}", confirm)
        assert installed.returncode == 0, installed.stdout[-6000:]
        site_packages = sorted(
            (_daemon_dir(project) / "untracked").glob("venv-*/lib/python3*/site-packages")
        )
        assert site_packages, "the install built no venv"
        for directory in site_packages:
            (directory / "zz-forge-gate-verdict.pth").write_text(_FORGING_PTH)
        result = _upgrade(project, env, f"v{major}")
    finally:
        _stop_daemon(project, env)
    assert result.returncode == GateVerdict.NEEDS_ACKNOWLEDGEMENT.exit_code, result.stdout[-6000:]
    assert _STOPPED_MARKER in result.stdout
    daemon_dir = _daemon_dir(project)
    assert _head(daemon_dir) == _commit_of(daemon_dir, f"v{current}")


def test_a_direct_layer2_call_ignores_a_forged_venv_path(
    tmp_path: Path, project: Path, versions: tuple[str, str, str]
) -> None:
    """HOOKS_DAEMON_VENV_PATH to a venv stamped with the target is not 'installed'."""
    current, _target, major = versions
    daemon_dir = _daemon_dir(project)
    _git(daemon_dir, "checkout", "-q", f"v{major}")
    env = _env({"HOOKS_DAEMON_VENV_PATH": str(_forged_venv(tmp_path, f"v{major}"))})
    env.pop("HOOKS_DAEMON_PYTHON")
    result = _run(
        [_BASH, str(daemon_dir / _LAYER2_REL), str(project), str(daemon_dir), f"v{major}"],
        project,
        env,
    )
    _assert_stopped_and_restored(result, GateVerdict.NEEDS_ACKNOWLEDGEMENT, project, current)


def test_a_direct_layer2_call_ignores_an_inherited_handoff_and_its_flags(
    tmp_path: Path, project: Path, versions: tuple[str, str, str]
) -> None:
    """The handoff counts only when this script's parent wrote it."""
    current, target, _major = versions
    env = _env()
    first = _upgrade(project, env, f"v{target}")
    daemon_dir = _daemon_dir(project)
    _git(daemon_dir, "checkout", "-q", f"v{target}")
    forged = tmp_path / "inherited-handoff"
    forged.write_text("1 \n")
    env.update(
        {"HOOKS_DAEMON_UPGRADE_HANDOFF": str(forged), "UPGRADE_FLAGS": _confirm(first.stdout)}
    )
    result = _run(
        [_BASH, str(daemon_dir / _LAYER2_REL), str(project), str(daemon_dir), f"v{target}"],
        project,
        env,
    )
    combined = _assert_stopped_and_restored(
        result, GateVerdict.NEEDS_ACKNOWLEDGEMENT, project, current
    )
    assert "Ignoring the upgrade handoff" in combined


def test_a_pre_gate_layer1_cannot_turn_a_stop_into_a_partial_install(
    tmp_path: Path, project: Path, versions: tuple[str, str, str]
) -> None:
    """Review MAJOR 2: v3.66.0's Layer 1 reports success whatever Layer 2 exits."""
    current, target, _major = versions
    old_layer1 = tmp_path / "old-upgrade.sh"
    old_layer1.write_text(_git(_REPO_ROOT, "show", f"{_PRE_GATE_RELEASE}:scripts/upgrade.sh"))
    result = _upgrade(project, _env(), f"v{target}", layer1=old_layer1)
    combined = _assert_stopped_and_restored(
        result, GateVerdict.NEEDS_ACKNOWLEDGEMENT, project, current, exit_code=0
    )
    warning = _section(combined, _PRE_GATE_WARNING)
    assert f"v{target}:scripts/upgrade.sh" in combined, warning
