"""`relay/build.sh` must not depend on a second `strip` (N625).

`rustc -C strip=symbols` already strips at link time. A redundant `strip "$OUT"`
afterwards failed intermittently on a CI runner (`[.rodata]: invalid operation`)
and, under `set -e`, aborted the whole relay build and a CI leg. The script now
verifies the binary itself (static, and it runs) instead.

The build needs the musl rustc target. Locally its absence is an honest skip; in
CI (`CI` or `GITHUB_ACTIONS` set) the workflow provisions it, so absence there is
a failure, never a skip.

This lives under tests/integration, not tests/unit, because only the daemon legs
(`daemon: true` in scripts/ci/shard_legs.yaml) run `rustup target add
x86_64-unknown-linux-musl`; the unit legs, and the native arm64 unit run, do not
and must not need a Rust toolchain.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_RELAY_DIR = _REPO_ROOT / "relay"
_TARGET = "x86_64-unknown-linux-musl"


def _in_ci() -> bool:
    return bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))


def _rustc() -> str:
    return os.environ.get("RUSTC", str(Path.home() / ".cargo" / "bin" / "rustc"))


def _musl_toolchain_present() -> bool:
    rustc = _rustc()
    if not Path(rustc).exists() and shutil.which(rustc) is None:
        return False
    result = subprocess.run(
        [rustc, "--print", "target-libdir", "--target", _TARGET],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and Path(result.stdout.strip()).is_dir()


@pytest.fixture
def scratch_repo(tmp_path: Path) -> Path:
    """A copy of the two relay files, so the build writes under tmp, not the repo."""
    if not _musl_toolchain_present():
        reason = f"musl rustc toolchain ({_TARGET}) not available"
        if _in_ci():
            pytest.fail(f"{reason}; CI provisions it, so this is a provisioning failure")
        pytest.skip(reason)
    relay = tmp_path / "relay"
    relay.mkdir()
    for name in ("build.sh", "hooks_relay.rs"):
        shutil.copy(_RELAY_DIR / name, relay / name)
    return tmp_path


def test_build_succeeds_and_never_invokes_strip(scratch_repo: Path) -> None:
    fake_bin = scratch_repo / "fakebin"
    fake_bin.mkdir()
    marker = scratch_repo / "strip-was-called"
    strip = fake_bin / "strip"
    strip.write_text(f'#!/bin/sh\ntouch "{marker}"\necho "strip: invalid operation" >&2\nexit 1\n')
    strip.chmod(0o755)

    env = {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"}
    result = subprocess.run(
        ["bash", str(scratch_repo / "relay" / "build.sh")],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not marker.exists(), "relay/build.sh invoked strip; -C strip=symbols is enough"
    built = scratch_repo / "untracked" / "relay-build" / f"hooks-relay-{_TARGET}"
    assert built.is_file()


def test_build_script_does_not_call_strip() -> None:
    lines = (_RELAY_DIR / "build.sh").read_text().splitlines()
    code = [ln for ln in lines if not ln.lstrip().startswith("#")]
    assert not any(ln.strip().startswith("strip ") for ln in code)
