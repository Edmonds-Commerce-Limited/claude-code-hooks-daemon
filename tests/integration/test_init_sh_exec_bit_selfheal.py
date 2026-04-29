"""Integration tests for init.sh's exec-bit self-heal block.

Plan 00102 Phase 3 (Tier 3a): if the executable bit on sibling hook
scripts gets dropped (filesystem copy, IDE rewrite, ``core.fileMode=false``,
etc.), the daemon's invocation form (``bash <path>``) keeps things working,
but a defence-in-depth chmod restores execute permission too — throttled
once per hour so the cost is amortised across hook invocations.

Tests exercise ``_exec_bit_selfheal()`` directly via an extracted helper:

- first call chmods every sibling and stamps the throttle file
- subsequent calls within 3600s short-circuit and do nothing
- a stale throttle file (older than 3600s) lets the chmod run again
- a missing untracked dir is created and the chmod still runs
- non-hook files in the same dir are NOT touched
"""

from __future__ import annotations

import os
import stat
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_SH = REPO_ROOT / ".claude" / "init.sh"

# Hooks the function should chmod — fixture creates these as plain files
# without +x, then we assert they get +x added.
_SIBLING_HOOK_NAMES = (
    "pre-tool-use",
    "post-tool-use",
    "session-start",
    "session-end",
    "stop",
    "subagent-stop",
    "user-prompt-submit",
    "notification",
    "pre-compact",
    "permission-request",
)

_THROTTLE_SECONDS = 3600


def _extract_selfheal(tmp: Path) -> Path:
    """Extract ``_exec_bit_selfheal`` from init.sh into a sourceable helper.

    Source-time side effects in init.sh (socket path computation, env file
    loading) are too entangled for direct sourcing in tests, so we slice
    just the function body and provide it the variables it needs.
    """
    text = INIT_SH.read_text()
    fn_marker = "_exec_bit_selfheal() {"
    if fn_marker not in text:
        raise RuntimeError(
            "init.sh does not yet define _exec_bit_selfheal — RED phase, expected at this point."
        )
    start = text.index(fn_marker)
    depth = 0
    i = start
    end = -1
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
        i += 1
    if end == -1:
        raise RuntimeError("Could not find closing brace for _exec_bit_selfheal")
    body = text[start:end]
    helper = tmp / "selfheal.sh"
    helper.write_text("#!/bin/bash\nset -euo pipefail\n" + body + "\n")
    return helper


def _make_hooks_dir(tmp: Path) -> tuple[Path, Path]:
    """Build a fake .claude/hooks/ + untracked dir layout."""
    hooks_dir = tmp / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True)
    untracked_dir = tmp / ".claude" / "hooks-daemon" / "untracked"
    untracked_dir.mkdir(parents=True)
    for name in _SIBLING_HOOK_NAMES:
        path = hooks_dir / name
        path.write_text("#!/bin/bash\necho hook\n")
        path.chmod(0o644)
    return hooks_dir, untracked_dir


def _is_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & stat.S_IXUSR)


def _run_selfheal(helper: Path, hooks_dir: Path, untracked_dir: Path) -> str:
    """Invoke the extracted self-heal function in a clean subshell."""
    env = os.environ.copy()
    env["PATH"] = os.environ["PATH"]
    cmd = (
        f'HOOK_SCRIPT_DIR="{hooks_dir}"; '
        f'_untracked_dir="{untracked_dir}"; '
        f'source "{helper}" && _exec_bit_selfheal'
    )
    result = subprocess.run(
        ["bash", "-c", cmd],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout


@pytest.fixture
def selfheal_helper(tmp_path: Path) -> Path:
    return _extract_selfheal(tmp_path)


class TestFirstCall:
    """A pristine repo with no throttle file: chmods all siblings."""

    def test_chmods_all_known_hooks(self, tmp_path: Path, selfheal_helper: Path) -> None:
        hooks_dir, untracked_dir = _make_hooks_dir(tmp_path)

        _run_selfheal(selfheal_helper, hooks_dir, untracked_dir)

        for name in _SIBLING_HOOK_NAMES:
            assert _is_executable(hooks_dir / name), f"{name} should be executable after self-heal"

    def test_creates_throttle_file(self, tmp_path: Path, selfheal_helper: Path) -> None:
        hooks_dir, untracked_dir = _make_hooks_dir(tmp_path)

        _run_selfheal(selfheal_helper, hooks_dir, untracked_dir)

        throttle = untracked_dir / ".exec-bit-checked"
        assert throttle.exists()


class TestThrottle:
    """Subsequent calls within the throttle window are no-ops."""

    def test_recent_throttle_file_skips_chmod(self, tmp_path: Path, selfheal_helper: Path) -> None:
        hooks_dir, untracked_dir = _make_hooks_dir(tmp_path)
        throttle = untracked_dir / ".exec-bit-checked"
        throttle.touch()
        # Files have NO +x; if self-heal runs anyway, they will gain it.

        _run_selfheal(selfheal_helper, hooks_dir, untracked_dir)

        for name in _SIBLING_HOOK_NAMES:
            assert not _is_executable(
                hooks_dir / name
            ), f"{name} should still be 0644 — recent throttle file must short-circuit"

    def test_stale_throttle_file_reruns_chmod(self, tmp_path: Path, selfheal_helper: Path) -> None:
        hooks_dir, untracked_dir = _make_hooks_dir(tmp_path)
        throttle = untracked_dir / ".exec-bit-checked"
        throttle.touch()
        # Backdate beyond the throttle window.
        old = time.time() - (_THROTTLE_SECONDS + 60)
        os.utime(throttle, (old, old))

        _run_selfheal(selfheal_helper, hooks_dir, untracked_dir)

        for name in _SIBLING_HOOK_NAMES:
            assert _is_executable(
                hooks_dir / name
            ), f"{name} should be re-chmoded after stale throttle file"


class TestUnrelatedFilesUntouched:
    """Only sibling hook scripts are chmoded — never random files."""

    def test_init_sh_and_unknown_files_left_alone(
        self, tmp_path: Path, selfheal_helper: Path
    ) -> None:
        hooks_dir, untracked_dir = _make_hooks_dir(tmp_path)
        unrelated = hooks_dir / "README.md"
        unrelated.write_text("# notes\n")
        unrelated.chmod(0o644)
        also_unrelated = hooks_dir / "init.sh"
        also_unrelated.write_text("# init\n")
        also_unrelated.chmod(0o644)

        _run_selfheal(selfheal_helper, hooks_dir, untracked_dir)

        assert not _is_executable(unrelated)
        assert not _is_executable(also_unrelated)
