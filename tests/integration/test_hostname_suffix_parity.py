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


# ---------------------------------------------------------------------------
# No THIRD implementation: a test may not re-derive the suffix either
# ---------------------------------------------------------------------------
#
# The four tests above pin bash against Python for the two PRODUCTION helpers.
# They cannot see a TEST that computes the suffix a third way, and Plan 00250
# found one doing exactly that: test_relay_guard_fail_open.py read
# `os.environ.get("HOSTNAME", "localhost")`, omitting the middle rung
# (socket.gethostname()) that both real implementations have.
#
# That omission is invisible wherever HOSTNAME is exported — every dev container
# — and only bites where it is not, such as a GitHub runner, where bash
# auto-populates HOSTNAME as a non-exported SHELL variable. The failure surfaced
# as an unreachable socket with no mention of a hostname anywhere.
#
# So: reading $HOSTNAME from the environment inside tests/ is denied unless the
# line carries a marker saying why it is not deriving a runtime path.

_HOSTNAME_ENV_READ = re.compile(r"""os\.environ(?:\.get\(|\[)\s*["']HOSTNAME["']""")

_HOSTNAME_EXEMPT_MARKER = "# hostname-suffix-exempt:"

_TESTS_ROOT = REPO_ROOT / "tests"


def _unexempted_hostname_reads() -> list[str]:
    """Return ``path:line`` for every unexempted ``$HOSTNAME`` read under tests/."""
    findings: list[str] = []
    for path in sorted(_TESTS_ROOT.rglob("*.py")):
        # This file DEFINES the pattern and exercises it in its own vacuity
        # fixtures, so scanning itself would report guaranteed hits.
        if path == Path(__file__).resolve():
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            # A comment can legitimately quote the offending shape when
            # explaining why it is wrong — that is documentation, not a third
            # implementation.
            if line.lstrip().startswith("#"):
                continue
            if not _HOSTNAME_ENV_READ.search(line):
                continue
            marker, _, reason = line.partition(_HOSTNAME_EXEMPT_MARKER)
            # A marker with no reason after it does not exempt: the point of the
            # marker is the justification, not the token.
            if marker != line and reason.strip():
                continue
            findings.append(f"{path.relative_to(REPO_ROOT)}:{lineno}")
    return findings


def test_no_test_re_derives_the_hostname_suffix() -> None:
    """No test reads $HOSTNAME to build a runtime path without justifying it."""
    findings = _unexempted_hostname_reads()
    assert not findings, (
        "These lines read $HOSTNAME directly, which omits the socket.gethostname() "
        "rung that init.sh and paths.py both have — they will disagree with the "
        "daemon wherever HOSTNAME is unexported (CI runners, macOS/zsh). Call "
        "`paths._get_hostname_suffix()` instead, or append "
        f"`{_HOSTNAME_EXEMPT_MARKER} <reason>` if the read is not deriving a "
        f"runtime path: {findings}"
    )


class TestTheGuardIsNotVacuous:
    """The scan above passes trivially if its regex matches nothing real."""

    def test_the_regex_matches_the_shape_that_caused_the_bug(self) -> None:
        offending = 'hostname_suffix = "-" + os.environ.get("HOSTNAME", "localhost").lower()'
        assert _HOSTNAME_ENV_READ.search(offending)

    def test_the_regex_matches_subscript_access_too(self) -> None:
        assert _HOSTNAME_ENV_READ.search('name = os.environ["HOSTNAME"]')

    def test_a_marker_without_a_reason_does_not_exempt(self) -> None:
        line = f'x = os.environ.get("HOSTNAME")  {_HOSTNAME_EXEMPT_MARKER}'
        marker, _, reason = line.partition(_HOSTNAME_EXEMPT_MARKER)
        assert marker != line and not reason.strip()

    def test_the_scan_actually_reaches_test_files(self) -> None:
        assert len(list(_TESTS_ROOT.rglob("*.py"))) > 100
