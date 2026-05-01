"""Plan 00104 Task 5.1 — skill upgrade.sh recursion guard (closed).

The self-bootstrap stanza re-execs into the freshly-downloaded
``upgrade.sh`` with a ``--already-bootstrapped`` flag. The fresh script
must skip its own bootstrap stanza when that flag is present, otherwise
each upgrade would loop indefinitely (download → exec → download → exec).

This test invokes a freshly-built wrapper script with
``--already-bootstrapped`` and a deliberately-broken
``HOOKS_DAEMON_BOOTSTRAP_BASE_URL`` (points at a non-existent path).
The bootstrap stanza must be skipped entirely — the broken URL is
never touched, the body marker is echoed, and exit is clean.

Helpers are duplicated from ``test_skill_upgrade_self_bootstraps.py``
so each test module can evolve independently if either contract
shifts.
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


def test_already_bootstrapped_flag_skips_bootstrap_stanza(tmp_path: Path) -> None:
    """``--already-bootstrapped`` must short-circuit the bootstrap entirely.

    With a deliberately-broken base URL: if the recursion guard fails,
    the stanza tries to reach the broken URL and the script exits
    non-zero with a network error. With the guard working, the broken
    URL is never touched and the body marker echoes cleanly.
    """
    script = tmp_path / "upgrade.sh"
    script.write_text(_build_wrapped_script("BODY_RAN"), encoding="utf-8")
    _make_executable(script)

    bogus_url_dir = tmp_path / "definitely-does-not-exist"

    result = subprocess.run(
        [BASH, str(script), "--already-bootstrapped"],
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "HOOKS_DAEMON_BOOTSTRAP_BASE_URL": f"file://{bogus_url_dir}",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        "recursion guard must skip the network entirely when "
        "--already-bootstrapped is passed.\n"
        f"returncode={result.returncode}\nstdout={result.stdout!r}\n"
        f"stderr={result.stderr!r}"
    )
    assert "BODY_RAN" in result.stdout, (
        "post-bootstrap body must execute when guard fires.\n" f"stdout={result.stdout!r}"
    )
    # Confirm we did NOT hit the network — no curl-style failure noise.
    assert "failed to download" not in result.stderr, (
        "stanza must not attempt any download when --already-bootstrapped "
        "is passed (would imply infinite recursion risk).\n"
        f"stderr={result.stderr!r}"
    )
