r"""Plan 00105 Phase 1 — H-1 acceptance gate that runs ``install.sh`` end-to-end.

The v3.10.0 SEV-1 (``print_info`` writing to stdout, corrupting every
``VAR=$(ensure_venv ...)`` capture in ``scripts/install_version.sh``) escaped
because the v3.10.0 H-1 gate synthesised state via ``write-venv-metadata``
directly instead of running the production ``install.sh`` →
``install_version.sh`` → ``ensure_venv`` chain. v3.10.1 was a hotfix.

This file closes that gap. It builds a fresh fixture project with no prior
``.claude/`` and no venv, then drives ``scripts/install_version.sh`` against a
git worktree of the repo. After the install completes it asserts:

  (a) ``install_version.sh`` exits 0 — proves no helper corrupted the
      ``VAR=$(...)`` capture mid-script.
  (b) ``${VENV_PATH}/.daemon-metadata.json`` exists with ``python_path``
      pointing at the venv's own ``bin/python`` (the v3.9.x field bug).
  (c) The freshly-installed daemon reports ``Daemon: RUNNING`` — proves the
      whole install path produced a working daemon.

Any future bug class in the install chain — print-before-echo, missing
dependency, broken helper — fails this gate before tagging.

The test is marked ``slow`` because ``ensure_venv`` runs ``uv sync`` and the
install starts a daemon. It must remain in the H-1 release-time playbook
(see ``CLAUDE/development/RELEASING.md`` Step 12.0).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_VERSION_SH = REPO_ROOT / "scripts" / "install_version.sh"
BASH = shutil.which("bash") or "/bin/bash"

# Match the dogfood daemon's process-name pattern so we can verify our test
# daemon by PID without confusing it with the dogfood instance. The
# enforce_single_daemon_process knob is OFF in the example config (which we
# copy in via install_version.sh Step 7), so the dogfood daemon is safe.
_TEST_HOSTNAME_PREFIX = "hooks-daemon-test-"
_INSTALL_TIMEOUT_SECONDS = 180


def _make_test_hostname() -> str:
    """Generate a unique hostname for daemon path isolation.

    The daemon paths are HOSTNAME-keyed:
    ``{project}/.claude/hooks-daemon/untracked/daemon-{hostname}.{sock,pid,log}``.
    Using a unique hostname per test prevents collision with the dogfood
    daemon and with concurrent test runs.
    """
    return f"{_TEST_HOSTNAME_PREFIX}{os.getpid()}-{int(time.time())}"


def _create_daemon_worktree(daemon_dir: Path) -> None:
    """Create a git worktree of the repo at HEAD as ``daemon_dir``.

    Layer 1 (``install.sh``) clones into ``$PROJECT_ROOT/.claude/hooks-daemon``;
    the post-install validator (``ClientInstallValidator._verify_daemon_directory``)
    hard-codes that path when checking ``src/`` and ``untracked/``. Anything
    else fails Step 12. The fixture therefore mirrors the real layout: the
    worktree IS the daemon dir, located inside ``.claude/`` of the fresh project.

    Worktrees share the .git/objects directory with the source repo, so
    creation is fast — the disk-heavy work is just checking out the working
    tree. The worktree contains every file ``install_version.sh`` needs
    (``pyproject.toml``, ``uv.lock``, ``src/``, ``scripts/``, ``.claude/``).
    """
    subprocess.run(
        ["git", "-C", str(REPO_ROOT), "worktree", "add", "--detach", str(daemon_dir), "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )


def _remove_daemon_worktree(worktree_path: Path) -> None:
    """Best-effort worktree teardown — never raise from cleanup."""
    if not worktree_path.exists():
        return
    subprocess.run(
        ["git", "-C", str(REPO_ROOT), "worktree", "remove", "--force", str(worktree_path)],
        check=False,
        capture_output=True,
        text=True,
    )


def _stop_test_daemon(venv_python: Path, project_root: Path, env: dict[str, str]) -> None:
    """Best-effort daemon shutdown — never raise from cleanup.

    The ``env`` MUST include the same ``HOSTNAME`` the install ran under,
    otherwise the CLI computes a different socket/pid path and "stops"
    the wrong (non-existent) daemon while the test daemon keeps running.
    """
    if not venv_python.is_file():
        return
    subprocess.run(
        [str(venv_python), "-m", "claude_code_hooks_daemon.daemon.cli", "stop"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=Timeout.DAEMON_RESTART_VERIFY_TIMEOUT_SEC,
        env=env,
    )


def _wait_for_daemon_status(
    venv_python: Path,
    project_root: Path,
    env: dict[str, str],
    target: str,
    timeout: float,
) -> tuple[bool, str]:
    """Poll the daemon CLI until ``target`` appears in stdout or timeout.

    The ``env`` MUST include the same ``HOSTNAME`` the install ran under,
    because daemon socket/pid/log paths are HOSTNAME-keyed. Without this,
    the status query targets a different daemon path and always reports
    "Daemon not running" even when our isolated daemon IS running.

    Returns (matched, last_stdout).
    """
    deadline = time.monotonic() + timeout
    last_stdout = ""
    last_stderr = ""
    last_returncode: int | None = None
    while time.monotonic() < deadline:
        result = subprocess.run(
            [str(venv_python), "-m", "claude_code_hooks_daemon.daemon.cli", "status"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=Timeout.DAEMON_SHUTDOWN,
            env=env,
        )
        last_stdout = result.stdout
        last_stderr = result.stderr
        last_returncode = result.returncode
        if target in result.stdout:
            return True, result.stdout
        time.sleep(0.5)
    return False, (
        f"returncode={last_returncode}\n" f"stdout:\n{last_stdout}\n" f"stderr:\n{last_stderr}\n"
    )


@pytest.mark.slow
def test_install_sh_end_to_end_produces_running_daemon(tmp_path: Path) -> None:
    """Plan 00105 Phase 1 Task 1.1 — the canonical install end-to-end gate.

    Builds a fresh fixture project (no ``.claude/``, no venv), runs
    ``install_version.sh`` against it under controlled environment variables
    (``HOSTNAME`` isolated, ``CI`` unset so ``ensure_venv`` does not skip),
    and asserts:

      (a) exit code 0
      (b) ``.daemon-metadata.json`` exists with ``python_path`` pointing at
          the venv's own ``bin/python`` (NOT a system ``/usr/bin/python3``)
      (c) ``daemon-cli status`` reports ``Daemon: RUNNING``

    Any future regression in the install chain — including the v3.10.0
    print-before-echo class — fails this gate before tag time.
    """
    if not INSTALL_VERSION_SH.is_file():
        pytest.skip(f"install_version.sh missing at {INSTALL_VERSION_SH}")
    if shutil.which("uv") is None:
        pytest.skip("uv not installed in this environment")

    project_root = tmp_path / "fresh-project"
    project_root.mkdir()
    # install_version.sh's Step 1 requires .claude/ and .git/ at PROJECT_ROOT.
    # Both must exist BEFORE the install runs — the installer populates the
    # contents (settings.json, hooks-daemon.yaml, hooks/, skills/) but does
    # not bootstrap these top-level dirs. A fresh install in real usage has
    # them because Layer 1 (install.sh) runs from a project that already has
    # `.claude/` and is a git repo.
    (project_root / ".claude").mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project_root, check=True, capture_output=True)
    # Daemon config validation requires a git remote 'origin'. Layer 1 in
    # real life clones into an existing project that already has one. The
    # remote URL is never contacted — only its presence is checked — so a
    # placeholder URL satisfies validation without network dependency.
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.invalid/fake.git"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )

    # DAEMON_DIR must mirror the real install layout: Layer 1 clones into
    # PROJECT_ROOT/.claude/hooks-daemon, and ClientInstallValidator hard-codes
    # that path when checking src/ and untracked/. Anything else fails Step 12.
    daemon_dir = project_root / ".claude" / "hooks-daemon"
    _create_daemon_worktree(daemon_dir)
    venv_python: Path | None = None
    env = os.environ.copy()

    try:
        # Daemon path isolation — keeps the test daemon distinct from the
        # dogfood daemon's socket/pid/log files even if they share project
        # root paths in untracked/.
        env["HOSTNAME"] = _make_test_hostname()
        # CI=true would short-circuit ensure_venv into the no-op return,
        # which produces an empty VAR capture and aborts the install. We
        # explicitly drop CI so the install runs the real venv-bootstrap path.
        env.pop("CI", None)
        env.pop("HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP", None)
        # The installer prints user-facing instructions in colour; pin a
        # plain locale so colour codes do not corrupt our assertions.
        env["NO_COLOR"] = "1"
        # PROJECT_ROOT must NOT trigger the self-install-mode guard. Empty
        # tmp dir has no src/ and no pyproject.toml — that is what we want.

        # cwd=project_root is critical: the daemon-cli that install_version.sh
        # launches at Step 11 resolves project_dir from CWD when computing
        # socket/pid/log paths. If we left CWD at /workspace (the pytest
        # invocation directory), the test daemon would collide with the
        # dogfood daemon's paths and the post-install status query would
        # report "NOT RUNNING" against the wrong daemon.
        result = subprocess.run(
            [BASH, str(INSTALL_VERSION_SH), str(project_root), str(daemon_dir)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=_INSTALL_TIMEOUT_SECONDS,
            cwd=project_root,
        )

        # Assertion (a): exit code 0 — no helper corrupted any VAR=$(...) capture.
        if result.returncode != 0:
            pytest.fail(
                "install_version.sh must exit 0 against a fresh fixture. "
                f"returncode={result.returncode}\n"
                f"--- stdout ---\n{result.stdout}\n"
                f"--- stderr ---\n{result.stderr}\n"
                "If you see 'ensure_venv returned empty path' or any "
                "unexpected text intermixed in a captured value, this is "
                "the v3.10.0 print-before-echo bug class recurring."
            )

        # Locate the venv install_version.sh just created. The fingerprint
        # is computed from the system Python's (version|base_prefix|machine)
        # tuple — we do not need to recompute it; we just glob for the
        # single venv-* directory under the worktree's untracked/.
        venv_candidates = sorted((daemon_dir / "untracked").glob("venv-py*"))
        assert venv_candidates, (
            f"install_version.sh must produce a fingerprint-keyed venv under "
            f"{daemon_dir}/untracked/. Found nothing matching 'venv-py*'. "
            f"Worktree untracked/ contents: "
            f"{list((daemon_dir / 'untracked').iterdir()) if (daemon_dir / 'untracked').exists() else '(missing)'}"
        )
        venv_path = venv_candidates[0]
        venv_python = venv_path / "bin" / "python"

        # Assertion (b): metadata file exists with venv-resident python_path.
        metadata_path = venv_path / ".daemon-metadata.json"
        assert metadata_path.is_file(), (
            f"install_version.sh must produce {metadata_path}. "
            f"Found venv contents: {list(venv_path.iterdir())}"
        )
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        expected_python_path = str(venv_python)
        assert metadata["python_path"] == expected_python_path, (
            f"python_path must point at the venv's own bin/python, not the "
            f"system interpreter that invoked the CLI (the v3.9.x field bug). "
            f"expected={expected_python_path!r}, got={metadata['python_path']!r}"
        )
        assert "/usr/bin/" not in metadata["python_path"], (
            f"python_path must NEVER be a system /usr/bin/ path. "
            f"Got: {metadata['python_path']!r}"
        )

        # Assertion (c): daemon RUNNING. install_version.sh's Step 11
        # (restart_daemon_verified) already checks this, but we re-check
        # explicitly here so the contract is visible at this layer too —
        # a future install_version.sh that skips Step 11 must still pass
        # this acceptance gate.
        assert venv_python.is_file(), f"venv Python must exist after install: {venv_python}"
        running, last_stdout = _wait_for_daemon_status(
            venv_python, project_root, env, "Daemon: RUNNING", timeout=Timeout.DAEMON_SHUTDOWN
        )
        assert running, (
            "daemon-cli status must report 'Daemon: RUNNING' after install. "
            f"Last status output:\n{last_stdout}\n"
            f"--- install stdout (tail) ---\n{result.stdout[-2000:]}\n"
            f"--- install stderr (tail) ---\n{result.stderr[-2000:]}"
        )

    finally:
        if venv_python is not None:
            _stop_test_daemon(venv_python, project_root, env)
        _remove_daemon_worktree(daemon_dir)
