"""Plan 00104 Task 5.1 — skill upgrade.sh checksum mismatch abort (closed).

Decision 3.C requires the self-bootstrap stanza to refuse executing a
downloaded ``upgrade.sh`` whose sha256 does not match
``bootstrap-checksums.txt``. A tampered release artifact (or a
release-pipeline bug producing inconsistent checksums) MUST abort the
upgrade rather than silently exec into untrusted code.

This test stages a fresh ``upgrade.sh`` whose actual sha256 differs
from the value advertised in ``bootstrap-checksums.txt``. The stale
wrapper detects its own checksum mismatch (correctly), downloads the
fresh script (succeeds), recomputes the sha (mismatch with manifest),
and aborts with a "checksum mismatch" directive on stderr.

Helpers are duplicated from the sibling self-bootstrap test modules so
each test can evolve independently if either contract shifts.
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


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_checksum_mismatch_aborts_with_directive(tmp_path: Path) -> None:
    """Manifest sha must match downloaded sha — otherwise abort.

    Setup:
    - stale wrapper: ``STALE_BODY_RAN`` (its sha will not match the
      manifest, triggering the download path).
    - fresh wrapper actually served: ``FRESH_BODY_RAN`` (a different
      sha than what the manifest claims).
    - manifest claims an unrelated 64-hex sha for ``upgrade.sh``.

    Expected: stale detects mismatch, downloads "fresh", recomputes
    the sha, finds it does not match the manifest claim, prints
    "checksum mismatch" on stderr, exits non-zero, neither body runs.
    """
    fake_manifest_sha = "0" * 64

    stale_text = _build_wrapped_script("STALE_BODY_RAN")
    # Plan 00105 Phase 4: the bootstrap stanza now uses
    # `awk -v name="$(basename "$0")" '$2 == name'` for an exact basename match
    # against the manifest. The stale wrapper MUST be named `upgrade.sh` so its
    # basename matches the manifest entry — staging it under a dedicated
    # subdirectory keeps it isolated from the fresh release/ directory below.
    stale_dir = tmp_path / "stale-install"
    stale_dir.mkdir()
    stale_path = stale_dir / "upgrade.sh"
    stale_path.write_bytes(stale_text.encode("utf-8"))
    _make_executable(stale_path)

    release_dir = tmp_path / "release"
    release_dir.mkdir()
    fresh_text = _build_wrapped_script("FRESH_BODY_RAN")
    (release_dir / "upgrade.sh").write_bytes(fresh_text.encode("utf-8"))
    actual_fresh_sha = _sha256_hex(fresh_text.encode("utf-8"))
    assert (
        actual_fresh_sha != fake_manifest_sha
    ), "test bug: fake manifest sha collides with real fresh sha"
    (release_dir / "bootstrap-checksums.txt").write_text(
        f"{fake_manifest_sha}  upgrade.sh\n", encoding="utf-8"
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

    assert result.returncode != 0, (
        "stanza must abort (non-zero exit) when downloaded sha does not "
        "match the manifest sha.\n"
        f"returncode={result.returncode}\nstdout={result.stdout!r}\n"
        f"stderr={result.stderr!r}"
    )
    assert "checksum mismatch" in result.stderr, (
        "stanza must emit a 'checksum mismatch' directive on stderr — "
        "the user must know the download was tampered with or the "
        "release manifest is inconsistent.\n"
        f"stderr={result.stderr!r}"
    )
    assert "FRESH_BODY_RAN" not in result.stdout, (
        "downloaded body must NOT execute on checksum mismatch — that "
        "would mean the bootstrap exec'd into untrusted code.\n"
        f"stdout={result.stdout!r}"
    )
    assert "STALE_BODY_RAN" not in result.stdout, (
        "stale body must NOT execute either — bootstrap aborted before "
        "reaching the original script's body.\n"
        f"stdout={result.stdout!r}"
    )
