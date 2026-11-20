"""The generated events-dir suffix matches the daemon's, without bash 4 case folding."""

from __future__ import annotations

import subprocess

import pytest

from claude_code_hooks_daemon.daemon.paths import _get_hostname_suffix
from claude_code_hooks_daemon.install.forwarder_generator import _events_dir_lines


def _bash_suffix(hostname: str) -> str:
    script = "".join(_events_dir_lines()) + 'printf "%s" "$_rl_sfx"\n'
    result = subprocess.run(
        ["bash", "-c", script],
        env={"HOSTNAME": hostname, "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


@pytest.mark.parametrize("hostname", ["Johns-MacBook-Pro", "My Host-A", "lower", "ABC"])
def test_bash_suffix_equals_the_daemon_suffix(
    monkeypatch: pytest.MonkeyPatch, hostname: str
) -> None:
    monkeypatch.setenv("HOSTNAME", hostname)
    assert _bash_suffix(hostname) == _get_hostname_suffix()


def test_the_suffix_lines_use_no_case_modifying_expansion() -> None:
    lines = "".join(_events_dir_lines())
    assert ",," not in lines
    assert "^^" not in lines
