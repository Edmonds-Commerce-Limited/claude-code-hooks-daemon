"""A self-install build installs the ``dev`` extra; a client install does not.

Plan 00555 Task 3.1. ``pyproject.toml`` declares ``dev`` as an optional-
dependencies extra, so a plain ``uv sync`` omits it and a self-install
checkout (where the daemon is developed) is left without pytest, mypy and
the rest. The layout rule is the one ``bin/hooks-daemon`` uses: the daemon
dir is a client install only when it is ``.claude/hooks-daemon``.

Stubs ``uv`` on PATH, as ``test_venv_sh_sync_is_frozen.py`` does.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
VENV_SH: Final[Path] = REPO_ROOT / "scripts" / "install" / "venv.sh"
BASH: Final[str] = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS: Final[int] = 30


def _sync_calls(tmp_path: Path, daemon_dir: Path) -> list[str]:
    daemon_dir.mkdir(parents=True)
    (daemon_dir / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.0.0"\n')
    venv_path = daemon_dir / "untracked" / "venv-test-py311-00000000"

    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()
    uv_log = tmp_path / "uv_calls.log"
    uv_log.write_text("")
    uv_stub = stub_dir / "uv"
    uv_stub.write_text(textwrap.dedent(f"""\
        #!/bin/bash
        printf '%s\\n' "$*" >> "{uv_log}"
        mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"
        exit 0
        """))
    uv_stub.chmod(0o755)
    stat_stub = stub_dir / "stat"
    stat_stub.write_text("#!/bin/bash\nprintf '%s\\n' 'ext2/ext3'\nexit 0\n")
    stat_stub.chmod(0o755)

    harness = textwrap.dedent(f"""\
        set -euo pipefail
        . "{VENV_SH}"
        export PATH="{stub_dir}:$PATH"
        create_venv_at_path "{daemon_dir}" "{venv_path}"
        """)
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env.pop("UV_LINK_MODE", None)
    env.pop("HOOKS_DAEMON_PYTHON", None)
    result = subprocess.run(
        [BASH, "-c", harness],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, f"{result.stdout!r} {result.stderr!r}"
    calls = [c for c in uv_log.read_text().splitlines() if "sync" in c.split()]
    assert calls, "the stub uv never saw a sync"
    return calls


class TestDevExtrasFollowTheInstallLayout:
    def test_a_self_install_sync_installs_the_dev_extra(self, tmp_path: Path) -> None:
        for call in _sync_calls(tmp_path, tmp_path / "checkout"):
            assert "--extra dev" in call, f"self-install sync lacks the dev extra: {call!r}"
            assert "--frozen" in call.split()

    def test_a_client_install_sync_does_not(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "project" / ".claude" / "hooks-daemon"
        for call in _sync_calls(tmp_path, daemon_dir):
            assert "--extra" not in call.split(), f"client sync installs extras: {call!r}"
