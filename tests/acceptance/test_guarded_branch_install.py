r"""Plan 00291 Task 3.4 — the guarded branch install, end to end, in client mode.

Drives the PRODUCTION Layer 2 (``scripts/upgrade_version.sh``) against a real
client-shaped project whose daemon dir is a clone of this repository, with
the gate armed, and asserts every clause of the owner ruling that only a
built venv can prove:

  - the venv's ``.daemon-version`` and ``.daemon-metadata.json`` carry the
    ``vX.Y.Z+<ref>.<sha>`` stamp;
  - the banner is printed;
  - ``status`` names the non-release install;
  - the ``version_check`` handler flags it on a new session;
  - the migration advisory reads the UNRELEASED staging manifests.

Marked ``slow``: ``ensure_venv`` runs ``uv sync`` and a daemon is started.
The fast, no-venv half of the gate (Layer 1, refusals, the library) lives in
``tests/integration/test_branch_install_gate.py``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UPGRADE_VERSION_SH = REPO_ROOT / "scripts" / "upgrade_version.sh"
BASH = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS = 300
_REF = "acceptance-branch"
_REASON = "Plan 00291 acceptance test"

_STAGED_MANIFEST = """\
version: "99.0.0"
date: "UNRELEASED"
breaking: false
config_changes:
  added:
    - key: "handlers.pre_tool_use.staged_acceptance_handler.enabled"
      description: "Staged for the next release"
      example_yaml: "handlers:\\n  pre_tool_use:\\n    staged_acceptance_handler:\\n      enabled: true\\n"
  renamed: []
  removed: []
  changed: []
"""


def _run(args: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


def _clone_daemon(daemon_dir: Path) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "clone",
            "--no-hardlinks",
            "--local",
            "--quiet",
            str(REPO_ROOT),
            str(daemon_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(daemon_dir), "config", "protocol.file.allow", "always"],
        check=True,
        capture_output=True,
        text=True,
    )


def _pyproject_version(daemon_dir: Path) -> str:
    for line in (daemon_dir / "pyproject.toml").read_text().splitlines():
        if line.startswith("version"):
            return line.split('"')[1]
    raise AssertionError("pyproject.toml has no version line")


@pytest.mark.slow
def test_guarded_branch_install_is_stamped_and_flagged_everywhere(tmp_path: Path) -> None:
    if shutil.which("uv") is None:
        pytest.skip("uv not installed in this environment")

    project_root = tmp_path / "client"
    (project_root / ".claude").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=project_root, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.invalid/fake.git"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )
    daemon_dir = project_root / ".claude" / "hooks-daemon"
    _clone_daemon(daemon_dir)
    # The canary state: a committed config, no venv, no running daemon.
    shutil.copy(
        daemon_dir / ".claude" / "hooks-daemon.yaml.example",
        project_root / ".claude" / "hooks-daemon.yaml",
    )
    staged = daemon_dir / "CLAUDE" / "UPGRADES" / "UNRELEASED" / "config-changes"
    staged.mkdir(parents=True, exist_ok=True)
    (staged / "v99.0.0.yaml").write_text(_STAGED_MANIFEST)

    short_sha = subprocess.run(
        ["git", "-C", str(daemon_dir), "rev-parse", "--short", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    expected_stamp = f"v{_pyproject_version(daemon_dir)}+{_REF}.{short_sha}"

    env = {k: v for k, v in os.environ.items() if not k.startswith("HOOKS_DAEMON_UNSAFE")}
    env["HOSTNAME"] = f"hooks-daemon-branch-test-{os.getpid()}-{int(time.time())}"
    env.pop("CI", None)
    env.pop("HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP", None)
    env["NO_COLOR"] = "1"
    env["HOOKS_DAEMON_UNSAFE_TRACK_REF"] = _REF
    env["HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE"] = _REASON

    venv_python: Path | None = None
    try:
        # Layer 1 hands Layer 2 the resolved commit; the clone already sits on
        # it, which is the state every Layer-1-driven upgrade arrives in.
        result = _run(
            [BASH, str(UPGRADE_VERSION_SH), str(project_root), str(daemon_dir), short_sha],
            cwd=project_root,
            env=env,
        )
        assert result.returncode == 0, (
            f"upgrade_version.sh failed ({result.returncode})\n--- stdout ---\n"
            f"{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
        assert "NON-RELEASE INSTALL" in result.stdout
        assert _REASON in result.stdout
        assert expected_stamp in result.stdout

        venvs = sorted((daemon_dir / "untracked").glob("venv-*py3*"))
        assert venvs, "no fingerprint-keyed venv was built"
        venv_path = venvs[0]
        venv_python = venv_path / "bin" / "python"
        assert (venv_path / ".daemon-version").read_text().strip() == expected_stamp
        metadata = json.loads((venv_path / ".daemon-metadata.json").read_text())
        assert metadata["daemon_version"] == expected_stamp

        cli = [str(venv_python), "-m", "claude_code_hooks_daemon.daemon.cli"]
        status = _run([*cli, "status"], cwd=project_root, env=env)
        assert "Daemon: RUNNING" in status.stdout, status.stdout + status.stderr
        assert f"Install: NON-RELEASE {expected_stamp}" in status.stdout
        assert f"tracking '{_REF}'" in status.stdout

        advisory = _run(
            [
                str(venv_python),
                "-c",
                "import json, sys\n"
                "from claude_code_hooks_daemon.handlers.session_start.version_check import "
                "VersionCheckHandler\n"
                "h = VersionCheckHandler()\n"
                "r = h.handle({'hook_event_name': 'SessionStart', 'session_id': 's',"
                " 'transcript_path': '/nonexistent/none.jsonl', 'cwd': sys.argv[1]})\n"
                "print(json.dumps(r.context))\n",
                str(project_root),
            ],
            cwd=project_root,
            env=env,
        )
        assert advisory.returncode == 0, advisory.stderr
        context = "\n".join(json.loads(advisory.stdout))
        assert expected_stamp in context
        assert "not a release" in context.lower()

        migrations = _run(
            [
                *cli,
                "check-config-migrations",
                "--from",
                "0.0.1",
                "--to",
                "99.0.0",
                "--config",
                str(project_root / ".claude" / "hooks-daemon.yaml"),
                "--manifests-dir",
                str(daemon_dir / "CLAUDE" / "UPGRADES" / "config-changes"),
                "--format",
                "json",
            ],
            cwd=project_root,
            env=env,
        )
        assert migrations.returncode == 1, migrations.stdout + migrations.stderr
        keys = {s["key"] for s in json.loads(migrations.stdout)["suggestions"]}
        assert (
            "handlers.pre_tool_use.staged_acceptance_handler.enabled" in keys
        ), "a branch install must read the UNRELEASED staging manifests as pending"
    finally:
        if venv_python is not None and venv_python.is_file():
            _run(
                [str(venv_python), "-m", "claude_code_hooks_daemon.daemon.cli", "stop"],
                cwd=project_root,
                env=env,
            )
