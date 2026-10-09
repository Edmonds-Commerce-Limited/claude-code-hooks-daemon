"""The status-line segment naming the machine the session is really on.

Plan 00411. The segment exists to answer "which machine am I on?" at a glance,
which sets the bar for being wrong: a confidently-wrong name is worse than a
blank one, because the reader acts on it without re-checking. So the tests here
care as much about what is NOT rendered — and about an inferred value being
visibly marked — as about the happy path.
"""

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.handlers.status_line import host_hostname
from claude_code_hooks_daemon.handlers.status_line.host_hostname import HostHostnameHandler
from claude_code_hooks_daemon.utils.cron_hosts import (
    ENV_HOSTNAME_OVERRIDE,
    HOSTNAME_OVERRIDE_ENV_VARS,
)
from claude_code_hooks_daemon.utils.host_identity import HostName, HostNameSource

_ENV_VAR = "HOOKS_DAEMON_HOST_HOSTNAME"


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV_VAR, raising=False)
    for name in HOSTNAME_OVERRIDE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _status_input(role: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"session_id": "test-session"}
    if role is not None:
        payload[HookInputField.SESSION_HOSTNAME] = role
    return payload


def _force_resolution(monkeypatch: pytest.MonkeyPatch, resolved: HostName | None) -> None:
    """Pin what the resolver returns, so the segment is tested in isolation."""
    monkeypatch.setattr(host_hostname, "resolve_host_name", lambda **_kwargs: resolved)


class TestTheSegmentShipsDormant:
    def test_it_is_opt_in(self) -> None:
        """Most users run on one machine and gain nothing but lost width."""
        assert HostHostnameHandler().get_default_enabled() is False


class TestTheGlyphConstantsCannotDrift:
    def test_the_inferred_glyph_is_the_composition_of_its_parts(self) -> None:
        """The inferred glyph is spelled literally so it stays greppable.

        A literal buys discoverability at the cost of a second place to change,
        so the equality is pinned rather than trusted.
        """
        assert host_hostname._ICON_INFERRED == host_hostname._ICON + host_hostname.INFERRED_MARKER


class TestRenderingAReadName:
    def test_an_environment_name_renders(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _force_resolution(monkeypatch, HostName(name="dev-box", source=HostNameSource.ENVIRONMENT))

        result = HostHostnameHandler().handle(_status_input())

        assert len(result.context) == 1
        assert "dev-box" in result.context[0]

    def test_a_read_name_carries_no_inferred_marker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _force_resolution(monkeypatch, HostName(name="dev-box", source=HostNameSource.LOCAL))

        rendered = HostHostnameHandler().handle(_status_input()).context[0]

        assert host_hostname.INFERRED_MARKER not in rendered


class TestRenderingAnInferredName:
    def test_an_inferred_name_is_visibly_marked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The whole safety property of this segment.

        An /etc/hosts hint is right on a Debian-family host and absent on a
        Fedora one; when it IS present it can still be stale. Marking it is what
        stops it being read as a fact.
        """
        _force_resolution(
            monkeypatch, HostName(name="guessed-box", source=HostNameSource.ETC_HOSTS_HINT)
        )

        rendered = HostHostnameHandler().handle(_status_input()).context[0]

        assert "guessed-box" in rendered
        assert host_hostname.INFERRED_MARKER in rendered


class TestRenderingNothing:
    def test_an_unresolvable_host_renders_no_segment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The live case in the environment this was requested from."""
        _force_resolution(monkeypatch, None)

        assert HostHostnameHandler().handle(_status_input()).context == []

    def test_no_placeholder_text_is_emitted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """'unknown' would occupy width to say nothing, every render, forever."""
        _force_resolution(monkeypatch, None)

        rendered = "".join(HostHostnameHandler().handle(_status_input()).context)

        assert "unknown" not in rendered.lower()
        assert "n/a" not in rendered.lower()


class TestResolutionHappensOncePerDaemon:
    def test_the_resolver_is_not_called_again_on_a_second_render(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The status line re-renders constantly; this must not re-probe.

        The resolver reads /etc/hosts on its bottom rung, so calling it per
        render would reintroduce exactly the per-render file read this package
        has a guard test against.
        """
        calls: list[int] = []

        def _counting_resolver(**_kwargs: object) -> HostName:
            calls.append(1)
            return HostName(name="dev-box", source=HostNameSource.LOCAL)

        monkeypatch.setattr(host_hostname, "resolve_host_name", _counting_resolver)
        handler = HostHostnameHandler()

        handler.handle(_status_input())
        handler.handle(_status_input())
        handler.handle(_status_input())

        assert len(calls) == 1

    def test_an_unresolved_result_is_also_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """None is an answer, and re-asking for it costs a file read each time."""
        calls: list[int] = []

        def _counting_resolver(**_kwargs: object) -> None:
            calls.append(1)
            return None

        monkeypatch.setattr(host_hostname, "resolve_host_name", _counting_resolver)
        handler = HostHostnameHandler()

        handler.handle(_status_input())
        handler.handle(_status_input())

        assert len(calls) == 1


class TestNoNameCanBeSuppliedFromConfig:
    def test_the_resolver_is_called_with_no_name_argument(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A hostname must not be settable from a file that gets committed.

        An earlier revision passed a `host_name` config option through to the
        resolver. It was removed: `.claude/hooks-daemon.yaml` is tracked in git
        and routinely public, so the option was an invitation to publish a
        machine name, recoverable afterwards only by searching history nobody
        rewrites. This pins that the handler asks for a name and supplies none.
        """
        seen: dict[str, object] = {}

        def _capturing_resolver(**kwargs: object) -> None:
            seen.update(kwargs)
            return None

        monkeypatch.setattr(host_hostname, "resolve_host_name", _capturing_resolver)

        HostHostnameHandler().handle(_status_input())

        assert seen == {}


class TestARoleOverrideIsShownBeforeTheHost:
    """A session that took a role shows ``<role>@<host>``.

    The role is the session's hostname override (``HOOKS_DAEMON_HOSTNAME``),
    which persistent crons' ``hosts:`` match against. Without it on the status
    line, nothing visible says which role a session is playing.
    """

    def _render(self, monkeypatch: pytest.MonkeyPatch, role: str | None, **resolved: Any) -> str:
        name = resolved.get("name", "dev-box")
        source = resolved.get("source", HostNameSource.ENVIRONMENT)
        _force_resolution(monkeypatch, HostName(name=name, source=source))
        return HostHostnameHandler().handle(_status_input(role)).context[0]

    def test_no_role_renders_the_host_alone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rendered = self._render(monkeypatch, None)

        assert f"{host_hostname._COLOR_BRIGHT_CYAN}{host_hostname._ICON}dev-box" in rendered

    def test_a_short_role_renders_in_full_before_the_at(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rendered = self._render(monkeypatch, "sdlc-runner")

        assert "sdlc-runner@dev-box" in rendered

    def test_a_role_of_exactly_fifteen_characters_is_not_truncated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rendered = self._render(monkeypatch, "a" * 15)

        assert f"{'a' * 15}@dev-box" in rendered

    def test_a_long_role_shows_its_first_ten_characters_and_an_ellipsis(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rendered = self._render(monkeypatch, "github-softwaredev-lifecycle-unattended")

        assert "github-sof...@dev-box" in rendered
        assert "lifecycle" not in rendered

    def test_a_role_equal_to_the_host_is_not_repeated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``CCY_HOST_HOSTNAME`` alone stamps the host's own name, which is no role."""
        rendered = self._render(monkeypatch, "dev-box")

        assert f"{host_hostname._COLOR_BRIGHT_CYAN}{host_hostname._ICON}dev-box" in rendered

    def test_an_inferred_host_keeps_its_marker_after_the_role(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rendered = self._render(
            monkeypatch, "runner", name="guessed-box", source=HostNameSource.ETC_HOSTS_HINT
        )

        assert f"runner{host_hostname._ICON_INFERRED}guessed-box" in rendered

    def test_without_a_stamp_the_role_comes_from_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(ENV_HOSTNAME_OVERRIDE, "runner")

        rendered = self._render(monkeypatch, None)

        assert "runner@dev-box" in rendered

    def test_the_stamp_wins_over_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The daemon's environment is whatever started it, not the session's."""
        monkeypatch.setenv(ENV_HOSTNAME_OVERRIDE, "stale-role")

        rendered = self._render(monkeypatch, "session-role")

        assert "session-role@dev-box" in rendered
        assert "stale-role" not in rendered

    def test_the_role_is_read_on_every_render(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only the host is cached; the role travels on each payload."""
        _force_resolution(monkeypatch, HostName(name="dev-box", source=HostNameSource.LOCAL))
        handler = HostHostnameHandler()

        first = handler.handle(_status_input("role-one")).context[0]
        second = handler.handle(_status_input("role-two")).context[0]

        assert "role-one@dev-box" in first
        assert "role-two@dev-box" in second

    def test_an_unresolvable_host_still_renders_nothing_with_a_role(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _force_resolution(monkeypatch, None)

        assert HostHostnameHandler().handle(_status_input("runner")).context == []


class TestTheSegmentExplainsItsOwnProvenance:
    def test_explain_names_the_rung_that_produced_the_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _force_resolution(
            monkeypatch, HostName(name="dev-box", source=HostNameSource.ETC_HOSTS_HINT)
        )

        explanation = HostHostnameHandler().explain_segment()

        assert "dev-box" in explanation.current_value
        assert HostNameSource.ETC_HOSTS_HINT.value in explanation.current_value

    def test_explain_describes_the_role_before_the_at(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _force_resolution(monkeypatch, HostName(name="dev-box", source=HostNameSource.LOCAL))

        explanation = HostHostnameHandler().explain_segment()

        assert ENV_HOSTNAME_OVERRIDE in explanation.how_to_read

    def test_explain_says_so_when_there_is_nothing_to_show(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _force_resolution(monkeypatch, None)

        explanation = HostHostnameHandler().explain_segment()

        assert explanation.current_value
        assert HostNameSource.ENVIRONMENT.value in explanation.how_to_read


class TestTheHandlerNeverReadsAFileItself:
    def test_the_module_contains_no_direct_read(self) -> None:
        """Mirrors the package-wide guard, stated locally so it is not a surprise.

        The file read lives in the util, behind one-shot resolution. If it ever
        migrates into this module it becomes a per-render read.
        """
        source = Path(host_hostname.__file__).read_text()

        assert "read_text" not in source
        assert "open(" not in source
