"""Plan 00122 BUG 1 — bash↔Python hostname-suffix parity (macOS portability).

Both the Python daemon (``daemon/paths.py:_get_hostname_suffix``) and the bash
hook forwarder (``init.sh:_get_hostname_suffix``) independently compute the
runtime-file suffix. If they disagree, the forwarder looks for a different
socket than the daemon created and the daemon becomes unmanageable — exactly
the macOS failure mode (``$HOSTNAME`` unset on macOS/zsh).

The pre-fix bug: when ``$HOSTNAME`` was empty BOTH sides fell back to a
``time``-based MD5 hash, which changed on every call. These tests pin the fix:

  * the bash suffix is DETERMINISTIC across calls when ``$HOSTNAME`` is unset,
  * it is NOT a time-style 8-hex hash, and
  * it MATCHES the Python suffix for the same environment.

The function is extracted from ``init.sh`` (which has side effects on sourcing)
using the same brace-matching approach as ``test_init_sh_venv_resolution.py``.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_SH = REPO_ROOT / "init.sh"

_TIME_HASH_SUFFIX = re.compile(r"^-[a-f0-9]{8}$")
_TIMEOUT_SECONDS = 30


def _extract_function(name: str) -> str:
    """Return the bash source of ``name`` from init.sh via brace matching."""
    text = INIT_SH.read_text()
    start = text.index(f"{name}() {{")
    depth = 0
    end = -1
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        raise RuntimeError(f"Could not find matching brace for {name}")
    return text[start:end]


def _run_bash_suffix(env_overrides: dict[str, str] | None, calls: int = 1) -> list[str]:
    """Source the extracted bash function and echo its result ``calls`` times.

    bash auto-populates ``$HOSTNAME`` as a shell variable on startup even when
    it is absent from the environment, which would mask the unset-HOSTNAME code
    path. So unless an override pins ``HOSTNAME``, the script explicitly
    ``unset``s it to force the fallback branch the macOS bug lives in.
    """
    fn = _extract_function("_get_hostname_suffix")
    invocations = "\n".join(["_get_hostname_suffix"] * calls)
    pins_hostname = bool(env_overrides and "HOSTNAME" in env_overrides)
    preamble = "" if pins_hostname else "unset HOSTNAME\n"
    script = f"#!/bin/bash\nset -u\n{preamble}{fn}\n{invocations}\n"
    env = os.environ.copy()
    env.pop("HOSTNAME", None)
    if env_overrides:
        env.update(env_overrides)
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        check=True,
        timeout=_TIMEOUT_SECONDS,
    )
    return [ln for ln in result.stdout.splitlines() if ln.strip()]


def _run_python_suffix(env_overrides: dict[str, str] | None) -> str:
    code = (
        "from claude_code_hooks_daemon.daemon.paths import "
        "_resolve_hostname_from_env, _get_hostname_suffix; "
        "_resolve_hostname_from_env.cache_clear(); print(_get_hostname_suffix())"
    )
    env = os.environ.copy()
    env.pop("HOSTNAME", None)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    if env_overrides:
        env.update(env_overrides)
    import sys

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=True,
        timeout=_TIMEOUT_SECONDS,
    )
    return result.stdout.strip()


def test_bash_suffix_is_deterministic_when_hostname_unset() -> None:
    """Two consecutive bash invocations with HOSTNAME unset return the SAME suffix."""
    suffixes = _run_bash_suffix(env_overrides=None, calls=2)
    assert len(suffixes) == 2
    assert suffixes[0] == suffixes[1], (
        "init.sh _get_hostname_suffix must be deterministic with HOSTNAME unset; "
        f"got {suffixes!r} (time-based hash regression?)"
    )


def test_bash_suffix_not_time_hash_when_hostname_unset() -> None:
    """With HOSTNAME unset the bash suffix is an OS hostname, not a time hash."""
    (suffix,) = _run_bash_suffix(env_overrides=None, calls=1)
    assert not _TIME_HASH_SUFFIX.match(suffix), (
        f"init.sh produced a time-style hash suffix {suffix!r} — must use the "
        "stable OS hostname instead"
    )


def test_bash_and_python_agree_when_hostname_unset() -> None:
    """The bash forwarder and the Python daemon compute the SAME suffix."""
    (bash_suffix,) = _run_bash_suffix(env_overrides=None, calls=1)
    python_suffix = _run_python_suffix(env_overrides=None)
    assert bash_suffix == python_suffix, (
        "bash init.sh and Python paths.py must agree on the runtime-file suffix "
        f"(HOSTNAME unset): bash={bash_suffix!r} python={python_suffix!r}"
    )


def test_bash_and_python_agree_when_hostname_set() -> None:
    """With an explicit HOSTNAME both sides sanitise it identically."""
    overrides = {"HOSTNAME": "My Host"}
    (bash_suffix,) = _run_bash_suffix(env_overrides=overrides, calls=1)
    python_suffix = _run_python_suffix(env_overrides=overrides)
    assert (
        bash_suffix == python_suffix == "-my-host"
    ), f"explicit HOSTNAME parity failed: bash={bash_suffix!r} python={python_suffix!r}"
