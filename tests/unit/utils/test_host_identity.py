"""Resolving the hostname of the machine a session is REALLY on.

The hard case is a container. A container gets its own UTS namespace, so its
``hostname`` is the container ID and says nothing about where the user is
sitting. Plan 00411 probed one (rootless podman, Debian 12 guest, Fedora 44
host) and established the host name is not readable from inside it at all:
no ``/run/host``, no container socket, a zero-byte ``/run/.containerenv``, and
no reverse DNS for the gateway.

So resolution is a LADDER, and the tests below pin each rung and the
precedence between them. The bottom rung — reading a name out of ``/etc/hosts``
— is the one that needs the most care: it works on a Debian-family host (which
writes ``127.0.1.1 <hostname>`` at install) and finds nothing on a Fedora one
(where ``systemd-hostnamed`` leaves the file generic). That is why it yields an
INFERRED value rather than a read one, and why "returns nothing" is a pinned
behaviour rather than an accident.
"""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils import host_identity
from claude_code_hooks_daemon.utils.host_identity import (
    HostName,
    HostNameSource,
    host_name_from_hosts_file,
    resolve_host_name,
)

_ENV_VAR = "HOOKS_DAEMON_HOST_HOSTNAME"

# The two /etc/hosts shapes that actually differ in the field.
_FEDORA_STYLE_HOSTS = """\
127.0.0.1\tlocalhost localhost.localdomain localhost4 localhost4.localdomain4
::1\tlocalhost localhost.localdomain localhost6 localhost6.localdomain6
10.88.0.37\t189d2cfbf5e9 some-container-name
"""

_DEBIAN_STYLE_HOSTS = """\
127.0.0.1\tlocalhost
127.0.1.1\tbuild-box.example.invalid build-box
::1\tlocalhost ip6-localhost ip6-loopback
"""


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let the real environment leak into a resolution test."""
    monkeypatch.delenv(_ENV_VAR, raising=False)


def _force_runtime(monkeypatch: pytest.MonkeyPatch, runtime: str | None) -> None:
    """Pin the detected container runtime for the duration of one test."""
    monkeypatch.setattr(host_identity, "detect_container_runtime", lambda: runtime)


class TestTheEnvironmentVariableIsTheOnlyAuthoritativeRouteInAContainer:
    """Rung 1 — an explicit hand-off from outside the namespace."""

    def test_the_env_var_is_used_and_marked_authoritative(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_ENV_VAR, "dev-workstation")
        _force_runtime(monkeypatch, "podman")

        resolved = resolve_host_name()

        assert resolved == HostName(name="dev-workstation", source=HostNameSource.ENVIRONMENT)
        assert resolved is not None and not resolved.inferred

    def test_the_env_var_beats_a_configured_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_ENV_VAR, "from-env")
        _force_runtime(monkeypatch, "podman")

        resolved = resolve_host_name(configured="from-config")

        assert resolved is not None and resolved.name == "from-env"

    def test_surrounding_whitespace_is_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_ENV_VAR, "  padded-host\n")
        _force_runtime(monkeypatch, "podman")

        resolved = resolve_host_name()

        assert resolved is not None and resolved.name == "padded-host"

    def test_an_empty_env_var_is_not_a_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An exporter that ran and found nothing must not win the ladder.

        Setting the variable to "" is what a wrapper does when its own lookup
        failed. Treating that as an answer would render a blank name and stop
        the lower rungs from ever being tried.
        """
        monkeypatch.setenv(_ENV_VAR, "   ")
        _force_runtime(monkeypatch, None)
        monkeypatch.setattr(host_identity.socket, "gethostname", lambda: "real-desktop")

        resolved = resolve_host_name()

        assert resolved == HostName(name="real-desktop", source=HostNameSource.LOCAL)


class TestTheConfiguredOverrideIsRungTwo:
    """Rung 2 — a per-machine value written into the project config."""

    def test_config_is_used_when_no_env_var_is_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _force_runtime(monkeypatch, "podman")

        resolved = resolve_host_name(configured="configured-host")

        assert resolved == HostName(name="configured-host", source=HostNameSource.CONFIG)
        assert resolved is not None and not resolved.inferred

    def test_config_beats_the_local_hostname(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A desktop user who overrides the name means it."""
        _force_runtime(monkeypatch, None)
        monkeypatch.setattr(host_identity.socket, "gethostname", lambda: "ignored")

        resolved = resolve_host_name(configured="chosen")

        assert resolved is not None and resolved.name == "chosen"

    def test_a_blank_configured_value_falls_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _force_runtime(monkeypatch, None)
        monkeypatch.setattr(host_identity.socket, "gethostname", lambda: "real-desktop")

        resolved = resolve_host_name(configured="  ")

        assert resolved == HostName(name="real-desktop", source=HostNameSource.LOCAL)

    @pytest.mark.parametrize("value", [12345, True, ["a-list"], {"a": "dict"}, object()])
    def test_a_non_string_config_value_yields_nothing_rather_than_raising(
        self, value: object
    ) -> None:
        """`host_name: 12345` in YAML is a plausible thing for a human to write.

        The value reaches a handler through the registry's untyped ``setattr``,
        so nothing upstream guarantees it is text. Calling ``.strip()`` on it
        would raise inside a status-line render — which repeats once per second,
        so the cost of that exception is a permanently broken status line rather
        than one bad frame. Tested against the private helper because that is
        where the defence lives; the public parameter is honestly typed for its
        real caller.
        """
        assert host_identity._non_blank(value) is None


class TestTheLocalHostnameIsUsedOnlyWhereItMeansSomething:
    """Rung 3 — ``gethostname()`` is the truth on a host, a lie in a container."""

    def test_a_desktop_uses_its_own_hostname(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _force_runtime(monkeypatch, None)
        monkeypatch.setattr(host_identity.socket, "gethostname", lambda: "my-desktop")

        resolved = resolve_host_name()

        assert resolved == HostName(name="my-desktop", source=HostNameSource.LOCAL)
        assert resolved is not None and not resolved.inferred

    def test_lxc_uses_its_own_hostname_deliberately(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LXC is treated as host-equivalent, by decision rather than oversight.

        An LXC guest is normally a long-lived named machine, so its hostname is
        the answer the user wanted. Podman and Docker containers are ephemeral
        and named by ID, so theirs is not.
        """
        _force_runtime(monkeypatch, "lxc")
        monkeypatch.setattr(host_identity.socket, "gethostname", lambda: "my-lxc-guest")

        resolved = resolve_host_name()

        assert resolved == HostName(name="my-lxc-guest", source=HostNameSource.LOCAL)

    @pytest.mark.parametrize("runtime", ["podman", "docker", "generic"])
    def test_a_namespaced_container_never_reports_its_own_hostname(
        self, monkeypatch: pytest.MonkeyPatch, runtime: str, tmp_path: Path
    ) -> None:
        """The whole point of the plan: the container ID is not an answer."""
        _force_runtime(monkeypatch, runtime)
        monkeypatch.setattr(host_identity.socket, "gethostname", lambda: "189d2cfbf5e9")
        hosts = tmp_path / "hosts"
        hosts.write_text(_FEDORA_STYLE_HOSTS)

        resolved = resolve_host_name(hosts_path=hosts)

        assert resolved is None


class TestTheEtcHostsReadIsTheLastRungAndIsOnlyAHint:
    """Rung 4 — real, useful, and host-distro-dependent."""

    def test_a_debian_style_host_file_yields_an_inferred_name(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _force_runtime(monkeypatch, "podman")
        hosts = tmp_path / "hosts"
        hosts.write_text(_DEBIAN_STYLE_HOSTS)

        resolved = resolve_host_name(hosts_path=hosts)

        assert resolved is not None
        assert resolved == HostName(
            name="build-box.example.invalid", source=HostNameSource.ETC_HOSTS_HINT
        )
        assert resolved.inferred

    def test_a_fedora_style_host_file_yields_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The case that disproved the heuristic as a mechanism.

        This is the shape of the file in the very environment the feature was
        requested from. Returning nothing here is the correct answer, and
        pinning it stops a future 'improvement' reaching for the container name
        on the last line.
        """
        _force_runtime(monkeypatch, "podman")
        hosts = tmp_path / "hosts"
        hosts.write_text(_FEDORA_STYLE_HOSTS)

        assert resolve_host_name(hosts_path=hosts) is None

    def test_a_missing_hosts_file_is_not_an_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _force_runtime(monkeypatch, "podman")

        assert resolve_host_name(hosts_path=tmp_path / "absent") is None

    def test_an_unreadable_hosts_file_is_not_an_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A directory where a file was expected raises OSError on read."""
        _force_runtime(monkeypatch, "podman")
        directory = tmp_path / "hosts"
        directory.mkdir()

        assert resolve_host_name(hosts_path=directory) is None


class TestParsingAHostsFile:
    """The pure half, exercised directly so the edges are cheap to pin."""

    def test_localhost_aliases_are_never_the_answer(self) -> None:
        assert host_name_from_hosts_file(_FEDORA_STYLE_HOSTS) is None

    def test_the_debian_self_alias_is_found(self) -> None:
        assert host_name_from_hosts_file(_DEBIAN_STYLE_HOSTS) == "build-box.example.invalid"

    def test_a_non_loopback_line_is_ignored(self) -> None:
        """Only 127.x lines describe the machine itself.

        A LAN entry names some OTHER host, and a container inherits a pile of
        them from the host's file — picking one would name the wrong machine
        with total confidence.
        """
        assert host_name_from_hosts_file("10.0.3.186\tsome-other-box\n") is None

    def test_comments_are_ignored(self) -> None:
        assert host_name_from_hosts_file("# 127.0.1.1 commented-out\n") is None

    def test_an_inline_comment_does_not_become_a_hostname(self) -> None:
        assert host_name_from_hosts_file("127.0.1.1 realname # trailing note\n") == "realname"

    def test_ipv6_loopback_is_not_treated_as_a_self_alias(self) -> None:
        """``::1`` carries only localhost aliases in practice.

        Including it would make the Fedora-style file above return
        ``localhost.localdomain`` on some systems, which is worse than nothing.
        """
        assert host_name_from_hosts_file("::1\tlocalhost some-name\n") is None

    def test_blank_and_malformed_lines_are_skipped(self) -> None:
        assert host_name_from_hosts_file("\n   \n127.0.1.1\n") is None

    def test_the_first_matching_line_wins(self) -> None:
        text = "127.0.1.1 first-name\n127.0.1.1 second-name\n"
        assert host_name_from_hosts_file(text) == "first-name"
