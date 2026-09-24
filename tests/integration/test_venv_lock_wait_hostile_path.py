"""Plan 00466 N30 — ``scripts/install/venv.sh``'s ``_venv_detached_build_wait``.

Fed `$(date +%s)` straight into an arithmetic expression computing how many
seconds are left in a detached build's bound. Unlike the venv_bootstrap.sh
call sites, this function already has a clean "I don't know" signal its
caller (``_venv_lock_wait_bound``) treats gracefully: ``return 1`` means
"fall back to the generic wait bound". So the fix here is to plumb that same
signal through a hostile-PATH epoch failure, loudly (via the shared
``_hp_epoch_seconds`` diagnostic), rather than embed an empty `date`
substitution into the arithmetic and silently compute the wrong remaining
time.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_SH = REPO_ROOT / "scripts" / "install" / "venv.sh"
PORTABLE_TIME_SH = REPO_ROOT / "scripts" / "lib" / "portable_time.sh"
BASH = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS = 30


def _build_path_without(dest_dir: Path, missing_names: set[str]) -> Path:
    """Symlink every real PATH executable into ``dest_dir``, except ``missing_names``."""
    seen: set[str] = set()
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        entry_path = Path(entry)
        if not entry_path.is_dir():
            continue
        try:
            entries = list(entry_path.iterdir())
        except OSError:
            continue
        for src in entries:
            name = src.name
            if name in seen or name in missing_names:
                continue
            if src.is_dir() or not os.access(src, os.X_OK):
                continue
            try:
                (dest_dir / name).symlink_to(src)
            except OSError:
                continue
            seen.add(name)
    return dest_dir


@pytest.fixture(scope="module")
def path_without_date(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _build_path_without(tmp_path_factory.mktemp("path-no-date"), {"date"})


def _run(harness: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH, "-c", harness],
        capture_output=True,
        text=True,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )


def _source_prelude(*, force_no_epoch: bool = False, path_without_date: Path | None = None) -> str:
    prelude = f'. "{VENV_SH}"\n'
    if force_no_epoch:
        # `_venv_detached_build_wait` sources portable_time.sh LAZILY, only
        # on its first call -- source it here explicitly first so this
        # override is not clobbered by that later (idempotent) source.
        prelude += f'. "{PORTABLE_TIME_SH}"\n'
        prelude += "_hp_bash_supports_printf_time() { return 1; }\n"
    if path_without_date is not None:
        prelude += f'PATH="{path_without_date}"\n'
    return prelude


def _write_record(daemon_dir: Path, started: int, bound: int) -> None:
    untracked = daemon_dir / "untracked"
    untracked.mkdir(parents=True, exist_ok=True)
    (untracked / ".venv-bootstrap.current").write_text(f"started={started}\nbound={bound}\n")


class TestDetachedBuildWaitUnderHostilePath:
    def test_correct_remaining_time_under_a_path_with_no_date(
        self, tmp_path: Path, path_without_date: Path
    ) -> None:
        daemon_dir = tmp_path / "daemon"
        harness_now = _run(f'. "{PORTABLE_TIME_SH}"\n_hp_epoch_seconds\n')
        now = int(harness_now.stdout.strip())
        _write_record(daemon_dir, started=now - 10, bound=900)

        harness = _source_prelude(path_without_date=path_without_date) + textwrap.dedent(f"""\
            VENV_BUILD_KILL_GRACE_SECONDS=5
            _venv_detached_build_wait "{daemon_dir}"
            """)
        result = _run(harness)

        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        remaining = int(result.stdout.strip())
        # started 10s ago, bound 900s, grace 5s -> ~895s left. Allow slack
        # for test execution time.
        assert 800 <= remaining <= 895, f"remaining={remaining}"

    def test_gracefully_falls_back_when_epoch_is_wholly_unavailable(
        self, tmp_path: Path, path_without_date: Path
    ) -> None:
        """No epoch source at all: must return 1 (the caller's existing
        "fall back to the generic bound" signal) -- never a fabricated
        remaining-time number -- and say why on stderr."""
        daemon_dir = tmp_path / "daemon"
        _write_record(daemon_dir, started=1000, bound=900)

        harness = _source_prelude(
            force_no_epoch=True, path_without_date=path_without_date
        ) + textwrap.dedent(
            f"""\
            VENV_BUILD_KILL_GRACE_SECONDS=5
            rc=0
            _venv_detached_build_wait "{daemon_dir}" || rc=$?
            echo "exit=$rc"
            """
        )
        result = _run(harness)

        assert "exit=1" in result.stdout, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert result.stdout.strip() == "exit=1", "must not also print a fabricated remaining value"
        assert "no epoch-second source" in result.stderr.lower()

    def test_lock_wait_bound_falls_back_to_the_generic_bound(
        self, tmp_path: Path, path_without_date: Path
    ) -> None:
        """The real caller, ``_venv_lock_wait_bound``, must still work end
        to end: with no epoch source, it uses the plain generic bound
        instead of crashing or hanging."""
        daemon_dir = tmp_path / "daemon"
        _write_record(daemon_dir, started=1000, bound=900)

        harness = _source_prelude(
            force_no_epoch=True, path_without_date=path_without_date
        ) + textwrap.dedent(
            f"""\
            VENV_BUILD_KILL_GRACE_SECONDS=5
            _venv_lock_wait_bound "{daemon_dir}" 30
            """
        )
        result = _run(harness)

        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert result.stdout.strip() == "30", f"stdout={result.stdout!r}"
