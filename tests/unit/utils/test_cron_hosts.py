"""The effective hostname a ``persistent_crons`` job's ``hosts:`` is matched against.

Plan 00470 Task 6.1 (owner ruling; issues #60, #62). One resolver and one
matcher serve every consumer of the declared jobs, so these pin them once:

* precedence: ``HOOKS_DAEMON_HOSTNAME``, then ``CCY_HOST_HOSTNAME``, then the
  system hostname;
* the session's own value -- stamped on the hook payload -- beats the
  evaluating process's environment, because the daemon is a long-lived process
  whose environment is NOT the session's;
* fnmatch-style matching: exact, ``*``, ``?``, ``[...]``, case-sensitive.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.utils.cron_hosts import (
    ENV_HOSTNAME_OVERRIDE,
    effective_hostname,
    hostname_matches,
    hostname_override,
    hostname_override_of_process,
    resolve_hostname_from_environ,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOOKS_DAEMON_HOSTNAME", raising=False)
    monkeypatch.delenv("CCY_HOST_HOSTNAME", raising=False)


class TestResolveFromEnviron:
    def test_falls_back_to_the_system_hostname(self) -> None:
        assert resolve_hostname_from_environ({}) == socket.gethostname()

    def test_ccy_host_hostname_beats_the_system_hostname(self) -> None:
        assert resolve_hostname_from_environ({"CCY_HOST_HOSTNAME": "laptop"}) == "laptop"

    def test_hooks_daemon_hostname_beats_ccy_host_hostname(self) -> None:
        environ = {"HOOKS_DAEMON_HOSTNAME": "cchd-sdlc-runner", "CCY_HOST_HOSTNAME": "laptop"}
        assert resolve_hostname_from_environ(environ) == "cchd-sdlc-runner"

    def test_an_empty_or_blank_value_is_skipped(self) -> None:
        environ = {"HOOKS_DAEMON_HOSTNAME": "  ", "CCY_HOST_HOSTNAME": "laptop"}
        assert resolve_hostname_from_environ(environ) == "laptop"

    def test_the_value_is_stripped(self) -> None:
        assert resolve_hostname_from_environ({"HOOKS_DAEMON_HOSTNAME": " a \n"}) == "a"


class TestOverride:
    def test_none_when_neither_variable_is_set(self) -> None:
        assert hostname_override({}) is None

    def test_the_first_non_empty_variable_wins(self) -> None:
        assert hostname_override({"CCY_HOST_HOSTNAME": "laptop"}) == "laptop"
        both = {"HOOKS_DAEMON_HOSTNAME": "runner", "CCY_HOST_HOSTNAME": "laptop"}
        assert hostname_override(both) == "runner"


class TestEffectiveHostname:
    def test_reads_this_process_environment_without_a_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOOKS_DAEMON_HOSTNAME", "runner")
        assert effective_hostname(None) == "runner"
        assert effective_hostname({}) == "runner"

    def test_the_payload_value_beats_the_process_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOOKS_DAEMON_HOSTNAME", "daemon-own-env")
        payload = {HookInputField.SESSION_HOSTNAME: "session-env"}
        assert effective_hostname(payload) == "session-env"

    @pytest.mark.parametrize("bad", ["", "   ", None, 7, ["x"]])
    def test_an_unusable_payload_value_is_ignored(
        self, bad: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOOKS_DAEMON_HOSTNAME", "runner")
        assert effective_hostname({HookInputField.SESSION_HOSTNAME: bad}) == "runner"


class TestMatching:
    def test_exact_match(self) -> None:
        assert hostname_matches(["cchd-sdlc-runner"], "cchd-sdlc-runner")

    def test_no_match(self) -> None:
        assert not hostname_matches(["cchd-sdlc-runner"], "laptop")

    def test_any_entry_may_match(self) -> None:
        assert hostname_matches(["a", "b"], "b")

    def test_star_glob(self) -> None:
        assert hostname_matches(["cchd-*"], "cchd-sdlc-runner")
        assert not hostname_matches(["cchd-*"], "other-sdlc-runner")

    def test_question_mark_glob(self) -> None:
        assert hostname_matches(["runner-?"], "runner-1")
        assert not hostname_matches(["runner-?"], "runner-10")

    def test_bracket_glob(self) -> None:
        assert hostname_matches(["runner-[12]"], "runner-2")
        assert not hostname_matches(["runner-[12]"], "runner-3")

    def test_matching_is_case_sensitive(self) -> None:
        assert not hostname_matches(["Runner"], "runner")

    def test_no_entries_match_nothing(self) -> None:
        assert not hostname_matches([], "anything")


class TestProcessEnviron:
    """The relay hands the daemon a byte stream, so the session's environment is
    read from the connected process itself."""

    def test_reads_the_override_from_another_process(self, tmp_path: Path) -> None:
        env = {**os.environ, ENV_HOSTNAME_OVERRIDE: "cchd-sdlc-runner"}
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            env=env,
            stdin=subprocess.DEVNULL,
        )
        try:
            assert hostname_override_of_process(child.pid) == "cchd-sdlc-runner"
        finally:
            child.kill()
            child.wait()

    def test_a_process_with_no_override_yields_none(self) -> None:
        env = {k: v for k, v in os.environ.items() if k not in {"HOOKS_DAEMON_HOSTNAME"}}
        env.pop("CCY_HOST_HOSTNAME", None)
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            env=env,
            stdin=subprocess.DEVNULL,
        )
        try:
            assert hostname_override_of_process(child.pid) is None
        finally:
            child.kill()
            child.wait()

    def test_an_unreadable_process_yields_none(self) -> None:
        assert hostname_override_of_process(2**22 + 12345) is None

    def test_a_non_positive_pid_yields_none(self) -> None:
        assert hostname_override_of_process(0) is None
        assert hostname_override_of_process(-1) is None
