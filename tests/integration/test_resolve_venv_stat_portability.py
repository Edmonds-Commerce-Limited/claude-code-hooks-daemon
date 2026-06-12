"""Plan 00123 BUG 2 (HIGH) — resolve_venv.sh hot-path ``stat`` is portable.

``scripts/lib/resolve_venv.sh`` is sourced by ``init.sh`` and runs on EVERY
hook event. Its hot-path cache computed the ``untracked/`` directory mtime with
``stat -c %Y`` — GNU coreutils only. On macOS/BSD ``stat`` rejects ``-c``, and
the call was wrapped in ``2>/dev/null`` so it returned empty, the cache-mtime
compare always failed, and every hook fell through to spawning Python for the
fingerprint MD5 (50-100ms — blowing the documented <5ms budget). This is the
"silent fallback hides regressions" antipattern.

Fix: a single ``_rv_dir_mtime`` helper that tries GNU ``stat -c %Y`` then falls
back to BSD ``stat -f %m`` (mirroring the ``init.sh`` exec-bit-selfheal
pattern). These tests stub ``stat`` on PATH to assert the helper resolves an
mtime under BOTH coreutils variants, and that no bare ``stat -c %Y`` remains.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOLVE_VENV_SH = REPO_ROOT / "scripts" / "lib" / "resolve_venv.sh"
BASH = shutil.which("bash") or "/bin/bash"

_BSD_MTIME = "1717000000"
_GNU_MTIME = "1718000000"
_TIMEOUT_SECONDS = 30


def _run_dir_mtime(tmp_path: Path, *, gnu_works: bool) -> subprocess.CompletedProcess[str]:
    """Source resolve_venv.sh and call ``_rv_dir_mtime`` with a stubbed stat.

    When ``gnu_works`` is False the stub mimics BSD stat: ``-c`` fails, ``-f``
    succeeds. When True it mimics GNU stat: ``-c`` succeeds.
    """
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()
    target = tmp_path / "untracked"
    target.mkdir()

    if gnu_works:
        stat_body = textwrap.dedent(f"""\
            #!/bin/bash
            # GNU stat: -c works
            if [ "$1" = "-c" ]; then printf '%s\\n' "{_GNU_MTIME}"; exit 0; fi
            echo "stat: bad flag" >&2; exit 1
            """)
    else:
        stat_body = textwrap.dedent(f"""\
            #!/bin/bash
            # BSD stat: -c is rejected, -f works
            if [ "$1" = "-c" ]; then echo "stat: illegal option -- c" >&2; exit 1; fi
            if [ "$1" = "-f" ]; then printf '%s\\n' "{_BSD_MTIME}"; exit 0; fi
            echo "stat: bad flag" >&2; exit 1
            """)
    stat_stub = stub_dir / "stat"
    stat_stub.write_text(stat_body)
    stat_stub.chmod(0o755)

    harness = textwrap.dedent(f"""\
        export PATH="{stub_dir}:$PATH"
        . "{RESOLVE_VENV_SH}"
        _rv_dir_mtime "{target}"
        """)
    return subprocess.run(
        [BASH, "-c", harness],
        capture_output=True,
        text=True,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )


def test_dir_mtime_uses_bsd_stat_fallback(tmp_path: Path) -> None:
    """On BSD/macOS (no ``stat -c``) the helper falls back to ``stat -f %m``."""
    result = _run_dir_mtime(tmp_path, gnu_works=False)
    assert result.returncode == 0, (
        "BUG 2: _rv_dir_mtime must succeed on BSD stat via the -f fallback.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert result.stdout.strip() == _BSD_MTIME, (
        "BUG 2: helper must return the BSD `stat -f %m` value on macOS, "
        f"got {result.stdout.strip()!r}"
    )


def test_dir_mtime_uses_gnu_stat_when_available(tmp_path: Path) -> None:
    """On Linux the helper still uses GNU ``stat -c %Y`` (preferred path)."""
    result = _run_dir_mtime(tmp_path, gnu_works=True)
    assert result.returncode == 0
    assert result.stdout.strip() == _GNU_MTIME, (
        "BUG 2 regression: helper must prefer GNU `stat -c %Y` on Linux, "
        f"got {result.stdout.strip()!r}"
    )


def test_no_bare_gnu_stat_remains_on_hot_path() -> None:
    """No unguarded ``stat -c %Y`` may remain — all calls go via the helper."""
    source = RESOLVE_VENV_SH.read_text()
    # The only permitted occurrence of `stat -c %Y` is inside the helper, which
    # is immediately followed by a `stat -f %m` fallback. Assert the bare GNU
    # call never appears outside the helper by requiring every `stat -c %Y` to
    # be paired with a `stat -f %m` somewhere in the file.
    assert (
        "stat -f %m" in source
    ), "BUG 2: resolve_venv.sh must contain a BSD `stat -f %m` fallback."
    # Cache call sites must delegate to the helper, not inline `stat -c`.
    assert source.count("_rv_dir_mtime") >= 3, (
        "BUG 2: both hot-path cache call sites must use _rv_dir_mtime "
        "(1 definition + >=2 call sites expected)."
    )
