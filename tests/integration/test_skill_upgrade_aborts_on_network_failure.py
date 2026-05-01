"""Plan 00104 Task 5.1 — skill upgrade.sh aborts on network failure (closed).

Decision 3.C requires that the self-bootstrap stanza **never silently
falls back** to the local stale copy when GitHub is unreachable. A
silent fallback would mean a tampered or unreachable release reaches
production undetected — defeating the purpose of bootstrap verification.

This test points the bootstrap base URL at a deliberately-non-existent
``file://`` path (the equivalent of GitHub being unreachable). The
stanza must:

- exit non-zero,
- emit a "failed to download" directive on stderr,
- NOT echo the body marker (script body must not run when bootstrap
  cannot verify its own integrity).

Helpers are duplicated from the sibling self-bootstrap test modules so
each test can evolve independently if either contract shifts.
"""

from __future__ import annotations

import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_UPGRADE_SCRIPT = (
    REPO_ROOT
    / "src"
    / "claude_code_hooks_daemon"
    / "skills"
    / "hooks-daemon"
    / "scripts"
    / "upgrade.sh"
)
BASH = shutil.which("bash") or "/bin/bash"

_BEGIN_MARKER = "# === SELF-BOOTSTRAP BEGIN"
_END_MARKER = "# === SELF-BOOTSTRAP END ==="


def _extract_bootstrap_stanza() -> str:
    text = SKILL_UPGRADE_SCRIPT.read_text(encoding="utf-8")
    start = text.find(_BEGIN_MARKER)
    end = text.find(_END_MARKER)
    assert start != -1, f"could not find {_BEGIN_MARKER!r} in {SKILL_UPGRADE_SCRIPT}"
    assert end != -1, f"could not find {_END_MARKER!r} in {SKILL_UPGRADE_SCRIPT}"
    return text[start : end + len(_END_MARKER)]


def _build_wrapped_script(body_marker: str) -> str:
    stanza = _extract_bootstrap_stanza()
    return textwrap.dedent(f"""\
        #!{BASH}
        set -euo pipefail
        {{stanza}}
        echo "{body_marker}"
        """).replace("{stanza}", stanza)


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_network_failure_aborts_with_directive(tmp_path: Path) -> None:
    """Unreachable bootstrap URL must abort, not silently fall back.

    The base URL points at a path that does not exist. ``curl -fsSL``
    against ``file:///nonexistent/...`` exits non-zero, the stanza
    catches the failure, prints a "failed to download" directive on
    stderr, and exits 1. The body marker must NOT appear on stdout —
    the script body must not run when bootstrap integrity cannot be
    verified.
    """
    script = tmp_path / "upgrade.sh"
    script.write_text(_build_wrapped_script("BODY_RAN"), encoding="utf-8")
    _make_executable(script)

    bogus_url_dir = tmp_path / "definitely-does-not-exist" / "missing-release"

    result = subprocess.run(
        [BASH, str(script)],
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "HOOKS_DAEMON_BOOTSTRAP_BASE_URL": f"file://{bogus_url_dir}",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0, (
        "stanza must abort (non-zero exit) when bootstrap URL is unreachable.\n"
        f"returncode={result.returncode}\nstdout={result.stdout!r}\n"
        f"stderr={result.stderr!r}"
    )
    assert "failed to download" in result.stderr, (
        "stanza must emit a 'failed to download' directive on stderr "
        "so the user knows why the upgrade aborted.\n"
        f"stderr={result.stderr!r}"
    )
    assert "BODY_RAN" not in result.stdout, (
        "script body must NOT run when bootstrap cannot verify integrity — "
        "silent fallback to the local stale copy is the exact failure mode "
        "this stanza prevents.\n"
        f"stdout={result.stdout!r}"
    )
