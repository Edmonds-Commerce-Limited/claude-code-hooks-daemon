"""Plan 00104 Task 5.1 — skill upgrade.sh self-bootstrap (closed).

The 2026-05-01 field report (Issue #1) showed that a stale skill
``upgrade.sh`` ships the user a broken upgrade flow that no in-repo fix
can save once installed. Decision 3.C of Plan 00104 fixes this by
embedding a self-bootstrap stanza in the skill ``upgrade.sh`` that
sha256-verifies against the latest GitHub release and re-execs the
fresh script when the local copy is stale.

This test pins the **stale → fresh** path: a staged "stale" wrapper
script (echoes ``STALE_BODY_RAN`` after the bootstrap stanza) detects
its checksum mismatch against ``bootstrap-checksums.txt``, downloads
the staged fresh version (echoes ``FRESH_BODY_RAN``), verifies the
download, and re-execs with ``--already-bootstrapped``. The test
asserts the fresh body executed AND the stale body did not.

The test extracts the bootstrap stanza from the real skill
``upgrade.sh`` so it stays in lock-step with the production contract.
If the stanza markers move, every test in this family fails the
extraction assert with a clear message.
"""

from __future__ import annotations

import hashlib
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
    """Slice the BEGIN/END self-bootstrap block out of the real skill upgrade.sh.

    Tests that fail this extraction must be updated alongside the
    production stanza — never the other way around.
    """
    text = SKILL_UPGRADE_SCRIPT.read_text(encoding="utf-8")
    start = text.find(_BEGIN_MARKER)
    end = text.find(_END_MARKER)
    assert start != -1, f"could not find {_BEGIN_MARKER!r} in {SKILL_UPGRADE_SCRIPT}"
    assert end != -1, f"could not find {_END_MARKER!r} in {SKILL_UPGRADE_SCRIPT}"
    return text[start : end + len(_END_MARKER)]


def _build_wrapped_script(body_marker: str) -> str:
    """Wrap the bootstrap stanza with a marker echo so test scripts are tiny.

    The wrapper is the minimal context the stanza needs: shebang +
    ``set -euo pipefail`` (matching the real skill) + the stanza +
    a single ``echo`` so the test can verify which body executed.
    """
    stanza = _extract_bootstrap_stanza()
    return textwrap.dedent(f"""\
        #!{BASH}
        set -euo pipefail
        {{stanza}}
        echo "{body_marker}"
        """).replace("{stanza}", stanza)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_skill_upgrade_self_bootstraps(tmp_path: Path) -> None:
    """Stale skill replaces itself with the fresh release and runs that.

    Stale wrapper sha != checksums entry → bootstrap downloads
    ``upgrade.sh`` from the staged base URL, verifies it, and re-execs.
    The fresh wrapper's bootstrap stanza is short-circuited by
    ``--already-bootstrapped`` and its body echoes the marker.
    """
    fresh_text = _build_wrapped_script("FRESH_BODY_RAN")
    fresh_bytes = fresh_text.encode("utf-8")
    fresh_sha = _sha256_hex(fresh_bytes)

    stale_text = _build_wrapped_script("STALE_BODY_RAN")
    stale_path = tmp_path / "stale_upgrade.sh"
    stale_path.write_bytes(stale_text.encode("utf-8"))
    _make_executable(stale_path)

    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "upgrade.sh").write_bytes(fresh_bytes)
    (release_dir / "bootstrap-checksums.txt").write_text(
        f"{fresh_sha}  upgrade.sh\n", encoding="utf-8"
    )

    result = subprocess.run(
        [BASH, str(stale_path)],
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "HOOKS_DAEMON_BOOTSTRAP_BASE_URL": f"file://{release_dir}",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"self-bootstrap should succeed end-to-end.\n"
        f"returncode={result.returncode}\nstdout={result.stdout!r}\n"
        f"stderr={result.stderr!r}"
    )
    assert "FRESH_BODY_RAN" in result.stdout, (
        "fresh body must execute after self-bootstrap.\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "STALE_BODY_RAN" not in result.stdout, (
        "stale body must NOT execute — bootstrap should exec into fresh.\n"
        f"stdout={result.stdout!r}"
    )
