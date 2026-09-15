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

import inspect
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


def _silent_hosts(tmp_path: Path) -> Path:
    """An ``/etc/hosts`` the last rung finds nothing in.

    A test asserting that some HIGHER rung refuses a value has to pin this one
    too, or it is really asserting something about the machine it runs on: on a
    Fedora-style host the read is silent and the test passes, while on a
    Debian-style one the ladder continues past the refusal and resolves a real
    name. Refusing a hostile value never meant NOTHING resolves — only that the
    refused rung contributes nothing.
    """
    hosts = tmp_path / "hosts"
    hosts.write_text(_FEDORA_STYLE_HOSTS)
    return hosts


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


class TestThereIsNoConfigFileRouteForTheName:
    """A hostname must never be settable from a tracked config file.

    This is a SECURITY property, not a design preference, so it is pinned as a
    test rather than left to a comment. ``.claude/hooks-daemon.yaml`` is tracked
    in git and routinely public; an option for a per-machine name is an
    invitation to commit one, and the resulting leak is findable only by
    searching history nobody rewrites. Per-machine values come from the
    environment, which is not committed.

    An earlier revision of this module DID have that option. It was removed, and
    these tests exist so it cannot quietly return.
    """

    def test_the_resolver_accepts_no_configured_name(self) -> None:
        """A caller cannot pass a name in, by any keyword."""
        parameters = set(inspect.signature(resolve_host_name).parameters)

        assert parameters == {"hosts_path"}

    def test_no_source_describes_a_config_file(self) -> None:
        """If a CONFIG rung ever reappears, the enum is where it shows up first."""
        assert "config" not in {source.value for source in HostNameSource}

    def test_the_handler_exposes_no_name_option(self) -> None:
        """The registry sets options by untyped setattr onto the instance.

        A declared attribute is how a reader learns an option exists, so the
        absence of one is the honest statement that no option does.
        """
        from claude_code_hooks_daemon.handlers.status_line.host_hostname import (
            HostHostnameHandler,
        )

        assert not hasattr(HostHostnameHandler(), "_host_name")


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


class TestAResolvedNameIsNeverAllowedToBeAnythingButAHostName:
    """The resolved name is printed to a TERMINAL once per second.

    Every rung's input comes from outside this process: an environment variable
    set by a wrapper, or `/etc/hosts` — which inside a container is written by
    the runtime and shaped by whoever built the image. So the value is treated
    as untrusted regardless of which rung produced it, and the check is an
    ALLOWLIST: a blocklist would have to anticipate every escape sequence,
    while nine permitted characters cannot be outflanked by one nobody
    predicted.

    Every case here fails CLOSED — no segment at all, rather than a filtered
    remnant presented as a machine name.
    """

    @pytest.mark.parametrize(
        ("label", "hostile"),
        [
            ("ANSI colour", "\033[31mred-host"),
            ("cursor movement", "host\033[2K\033[1G overwritten"),
            ("OSC window title", "\033]0;pwned\007host"),
            ("bare escape", "host\033"),
            ("carriage return overwrite", "real-host\rFAKE"),
            ("newline breaking the segment", "host\nsecond-line"),
            ("backspace erasure", "safe-host\x08\x08\x08evil"),
            ("bell", "host\a"),
            ("pipe forging a segment break", "host | 🔒 secure"),
            ("shell substitution text", "$(whoami)"),
            ("backtick substitution text", "`id`"),
            ("space-separated injection", "host and more"),
        ],
    )
    def test_a_hostile_env_value_yields_no_segment(
        self, monkeypatch: pytest.MonkeyPatch, label: str, hostile: str, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(_ENV_VAR, hostile)
        _force_runtime(monkeypatch, "podman")

        assert resolve_host_name(hosts_path=_silent_hosts(tmp_path)) is None, (
            f"{label} was not refused"
        )

    def test_an_absurdly_long_value_is_refused_rather_than_truncated(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A truncated unknown is still an unknown, shown with more confidence.

        It would also flood a status line that has a width budget shared with
        every other segment.
        """
        monkeypatch.setenv(_ENV_VAR, "a" * 500)
        _force_runtime(monkeypatch, "podman")

        assert resolve_host_name(hosts_path=_silent_hosts(tmp_path)) is None

    def test_a_refused_rung_does_not_stop_the_ladder(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Refusing a value is not the same as resolving nothing.

        Without this, every test above could pass against a resolver that
        returned ``None`` unconditionally — they assert an absence, and an
        absence is what a broken ladder produces too. Here the env rung is fed a
        hostile value and a LOWER rung has a real answer: the hostile text must
        not appear, and the real name must.
        """
        monkeypatch.setenv(_ENV_VAR, "host\033[31m")
        _force_runtime(monkeypatch, "podman")
        hosts = tmp_path / "hosts"
        hosts.write_text(_DEBIAN_STYLE_HOSTS)

        resolved = resolve_host_name(hosts_path=hosts)

        assert resolved == HostName(
            name="build-box.example.invalid", source=HostNameSource.ETC_HOSTS_HINT
        )

    def test_a_value_at_the_length_limit_is_still_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The boundary is pinned so tightening it later is a visible decision."""
        monkeypatch.setenv(_ENV_VAR, "a" * 64)
        _force_runtime(monkeypatch, "podman")

        resolved = resolve_host_name()

        assert resolved is not None and resolved.name == "a" * 64

    @pytest.mark.parametrize(
        "legitimate",
        ["build-box", "build-box.example.invalid", "HOST-01", "vm_dev_02", "node-1.2.3"],
    )
    def test_real_host_names_are_not_caught_by_the_filter(
        self, monkeypatch: pytest.MonkeyPatch, legitimate: str
    ) -> None:
        """An allowlist that refuses real names is a broken feature, not a safe one."""
        monkeypatch.setenv(_ENV_VAR, legitimate)
        _force_runtime(monkeypatch, "podman")

        resolved = resolve_host_name()

        assert resolved is not None and resolved.name == legitimate

    def test_a_hostile_etc_hosts_alias_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The least trustworthy rung: a file the container runtime writes."""
        _force_runtime(monkeypatch, "podman")
        hosts = tmp_path / "hosts"
        hosts.write_text("127.0.1.1 \033[31minjected\033[0m\n")

        assert resolve_host_name(hosts_path=hosts) is None

    def test_a_hostile_alias_does_not_mask_a_real_one_beside_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """One bad entry must not suppress a good name later on the line.

        Otherwise a single crafted alias would be enough to blank the segment
        for everyone — a denial of the feature rather than an exploit of it.
        """
        _force_runtime(monkeypatch, "podman")
        hosts = tmp_path / "hosts"
        hosts.write_text("127.0.1.1 bad\033[31mname real-box\n")

        resolved = resolve_host_name(hosts_path=hosts)

        assert resolved is not None and resolved.name == "real-box"

    def test_a_nul_byte_is_refused_by_the_sanitiser_itself(self) -> None:
        """Tested against the helper because an env var CANNOT carry a NUL.

        `os.environ` raises `ValueError: embedded null byte` before this code
        would ever see one, so asserting it at the env rung would be testing
        CPython. A hosts file has no such protection, and the sanitiser is
        shared, so this is where the guarantee actually needs to hold.
        """
        assert host_identity._clean_host_name("host\x00trailer") is None

    def test_a_hostile_local_hostname_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """gethostname() is only as trustworthy as whatever set it."""
        _force_runtime(monkeypatch, None)
        monkeypatch.setattr(host_identity.socket, "gethostname", lambda: "host\033[31m")

        assert resolve_host_name() is None

    def test_the_rejected_value_is_never_written_to_a_log(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A log is read in a terminal too, so echoing the payload moves the risk.

        The refusal is recorded; the thing being refused is not.
        """
        monkeypatch.setenv(_ENV_VAR, "\033]0;pwned\007host")
        _force_runtime(monkeypatch, "podman")

        with caplog.at_level("DEBUG"):
            resolve_host_name()

        assert "\033" not in caplog.text
        assert "pwned" not in caplog.text


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
