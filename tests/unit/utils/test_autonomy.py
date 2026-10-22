"""Tests for ``autonomy_allowed`` and its verdict (Plan 00498 Task 2.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

import claude_code_hooks_daemon.core.data_layer as data_layer
from claude_code_hooks_daemon.config.models import AutonomyConfig, Config
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.core import ProjectContext
from claude_code_hooks_daemon.utils import autonomy
from claude_code_hooks_daemon.utils.autonomy import (
    autonomy_allowed,
    autonomy_verdict,
    current_environment,
    environment_label,
)
from claude_code_hooks_daemon.utils.session_modes import SessionPolicy
from tests.support.autonomy import awaiting_human_entry, focus_entry, pin_session_modes

_CONTAINERS_ONLY = Config(
    autonomy=AutonomyConfig(environments=["docker", "podman", "lxc", "generic"])
)


class TestEnvironment:
    def test_no_runtime_is_the_bare_host(self) -> None:
        assert environment_label(None) == "host"

    def test_a_runtime_is_its_own_label(self) -> None:
        assert environment_label("lxc") == "lxc"

    def test_an_unknown_runtime_is_a_generic_container_never_the_host(self) -> None:
        assert environment_label("kubernetes") == "generic"

    def test_uses_the_runtime_cached_at_startup_without_re_detecting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _never_detect() -> str | None:
            raise AssertionError("the runtime is probed again on every event")

        monkeypatch.setattr(ProjectContext, "container_runtime", classmethod(lambda cls: "lxc"))
        monkeypatch.setattr(autonomy, "detect_container_runtime", _never_detect)
        assert current_environment() == "lxc"

    def test_a_cached_host_is_the_host_not_a_reason_to_detect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _never_detect() -> str | None:
            raise AssertionError("the runtime is probed again on every event")

        monkeypatch.setattr(ProjectContext, "container_runtime", classmethod(lambda cls: None))
        monkeypatch.setattr(autonomy, "detect_container_runtime", _never_detect)
        assert current_environment() == "host"

    def test_detects_when_no_project_context_is_initialised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _uninitialised(cls: type[ProjectContext]) -> str | None:
            raise RuntimeError("ProjectContext not initialized")

        monkeypatch.setattr(ProjectContext, "container_runtime", classmethod(_uninitialised))
        monkeypatch.setattr(autonomy, "detect_container_runtime", lambda: "podman")
        assert current_environment() == "podman"
        monkeypatch.setattr(autonomy, "detect_container_runtime", lambda: None)
        assert current_environment() == "host"


class TestVerdict:
    @pytest.fixture(autouse=True)
    def _no_role_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOOKS_DAEMON_HOSTNAME", raising=False)
        monkeypatch.delenv("CCY_HOST_HOSTNAME", raising=False)

    def test_default_config_allows_everywhere(self) -> None:
        assert autonomy_verdict(config=Config(), environment="host").allowed is True

    def test_host_is_refused_by_a_containers_only_config(self) -> None:
        verdict = autonomy_verdict(config=_CONTAINERS_ONLY, environment="host")
        assert verdict.allowed is False
        assert verdict.environment == "host"

    def test_a_container_is_allowed_by_a_containers_only_config(self) -> None:
        assert autonomy_verdict(config=_CONTAINERS_ONLY, environment="docker").allowed is True

    def test_the_payload_hostname_alias_overrides_the_environment(self) -> None:
        config = Config(autonomy=AutonomyConfig(environments=[], hosts=["cchd-sdlc-runner"]))
        payload = {HookInputField.SESSION_HOSTNAME: "cchd-sdlc-runner"}
        verdict = autonomy_verdict(payload, config=config, environment="host")
        assert verdict.allowed is True

    def test_an_environment_variable_alias_is_read_without_a_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOOKS_DAEMON_HOSTNAME", "role-x")
        config = Config(autonomy=AutonomyConfig(environments=[], hosts=["role-*"]))
        assert autonomy_verdict(config=config, environment="host").allowed is True

    def test_the_explanation_names_the_environment_and_the_remedy(self) -> None:
        text = autonomy_verdict(config=_CONTAINERS_ONLY, environment="host").explain()
        assert "host" in text
        assert "autonomy.environments" in text


class TestAutonomyAllowedLoadsTheProjectConfig:
    @staticmethod
    def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
        config_path = tmp_path / "hooks-daemon.yaml"
        config_path.write_text(body)
        monkeypatch.setattr(ProjectContext, "config_path", classmethod(lambda cls: config_path))
        monkeypatch.delenv("HOOKS_DAEMON_HOSTNAME", raising=False)
        monkeypatch.delenv("CCY_HOST_HOSTNAME", raising=False)

    def test_off_on_the_host_when_the_project_says_containers_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._project(
            tmp_path, monkeypatch, "version: '2.0'\nautonomy:\n  environments: [docker]\n"
        )
        monkeypatch.setattr(autonomy, "detect_container_runtime", lambda: None)
        assert autonomy_allowed() is False

    def test_on_in_a_listed_container(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._project(
            tmp_path, monkeypatch, "version: '2.0'\nautonomy:\n  environments: [docker]\n"
        )
        monkeypatch.setattr(autonomy, "detect_container_runtime", lambda: "docker")
        assert autonomy_allowed() is True

    def test_on_when_the_project_has_no_autonomy_block(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._project(tmp_path, monkeypatch, "version: '2.0'\n")
        monkeypatch.setattr(autonomy, "detect_container_runtime", lambda: None)
        assert autonomy_allowed() is True

    def test_an_unloadable_config_keeps_the_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._project(tmp_path, monkeypatch, "autonomy: [not a mapping\n")
        monkeypatch.setattr(autonomy, "detect_container_runtime", lambda: None)
        assert autonomy_allowed() is True

    def test_no_project_context_keeps_the_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ProjectContext.reset()
        monkeypatch.setattr(autonomy, "detect_container_runtime", lambda: None)
        assert autonomy_allowed() is True


#: ``explain()`` for an environment the config does not list, byte for byte as it
#: read before session modes existed (Plan 00501 Phase 1 changes no verdict).
_TODAYS_OFF_TEXT = (
    "AUTONOMY OFF: this session runs in the 'host' environment (hostname 'h1'), which "
    "this project's `autonomy:` config does not list, so no crons, failsafe-recovery "
    "advice, goal injection, goal-ledger stop challenges or stand-in crons run here. Do "
    "only what you were asked in this conversation, and stop when it is done. Guards are "
    "unaffected. To change it, list this environment under `autonomy.environments` in "
    ".claude/hooks-daemon.yaml, or name a role alias under `autonomy.hosts`."
)

_SID = "session-1"


class TestSessionModes:
    """The verdict honours the session's modes (Plan 00501 Task 1.3)."""

    @pytest.fixture(autouse=True)
    def _pinned_hostname(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOOKS_DAEMON_HOSTNAME", "h1")
        monkeypatch.delenv("CCY_HOST_HOSTNAME", raising=False)

    @staticmethod
    def _payload(session_id: str = _SID) -> dict[str, str]:
        return {HookInputField.SESSION_ID: session_id}

    def test_no_mode_keeps_todays_verdicts_and_text(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pin_session_modes(monkeypatch, tmp_path)
        for config, environment, expected in (
            (Config(), "host", True),
            (_CONTAINERS_ONLY, "host", False),
            (_CONTAINERS_ONLY, "docker", True),
        ):
            verdict = autonomy_verdict(self._payload(), config=config, environment=environment)
            assert verdict.allowed is expected
            assert verdict.environment_allowed is expected
            assert verdict.session.entries == ()
        off = autonomy_verdict(self._payload(), config=_CONTAINERS_ONLY, environment="host")
        assert off.explain() == _TODAYS_OFF_TEXT

    def test_no_mode_matches_a_payload_with_no_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pin_session_modes(monkeypatch, tmp_path)
        with_session = autonomy_verdict(
            self._payload(), config=_CONTAINERS_ONLY, environment="host"
        )
        without = autonomy_verdict({}, config=_CONTAINERS_ONLY, environment="host")
        assert with_session == without

    def test_a_focus_mode_pauses_autonomy_where_the_environment_allows_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pin_session_modes(monkeypatch, tmp_path, focus_entry(_SID, "ship 1.3"))
        verdict = autonomy_verdict(self._payload(), config=Config(), environment="host")
        assert verdict.environment_allowed is True
        assert verdict.allowed is False
        assert autonomy_allowed(self._payload()) is False

    def test_a_blocked_mode_pauses_autonomy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pin_session_modes(monkeypatch, tmp_path, awaiting_human_entry(_SID))
        assert (
            autonomy_verdict(self._payload(), config=Config(), environment="docker").allowed
            is False
        )

    def test_another_sessions_mode_changes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pin_session_modes(monkeypatch, tmp_path, focus_entry("someone-else"))
        assert (
            autonomy_verdict(self._payload(), config=Config(), environment="host").allowed is True
        )

    def test_the_paused_text_names_the_mode_its_exit_and_the_guards(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pin_session_modes(monkeypatch, tmp_path, focus_entry(_SID, "ship 1.3"))
        text = autonomy_verdict(self._payload(), config=Config(), environment="host").explain()
        assert text.startswith("AUTONOMY PAUSED FOR THIS SESSION: focus mode on 'ship 1.3', ")
        assert "no crons, failsafe-recovery advice, goal injection" in text
        assert "Guards are unaffected." in text
        assert "`hooks-daemon focus off`" in text
        assert "AUTONOMY OFF" not in text

    def test_both_reasons_keep_todays_text_and_add_the_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pin_session_modes(monkeypatch, tmp_path, focus_entry(_SID, "ship 1.3"))
        text = autonomy_verdict(
            self._payload(), config=_CONTAINERS_ONLY, environment="host"
        ).explain()
        assert text.startswith(
            _TODAYS_OFF_TEXT + " This session is also in focus mode on 'ship 1.3'"
        )
        assert "`hooks-daemon focus off`" in text

    def test_an_explicit_policy_is_used_without_reading_the_registry(self) -> None:
        ProjectContext.reset()
        policy = SessionPolicy.from_entries((focus_entry(_SID),))
        verdict = autonomy_verdict(
            self._payload(), config=Config(), environment="host", session=policy
        )
        assert verdict.allowed is False
        assert verdict.session is policy

    def test_a_payload_with_no_session_reads_no_registry(self) -> None:
        ProjectContext.reset()
        for payload in ({}, {HookInputField.SESSION_ID: None}, {HookInputField.SESSION_ID: "  "}):
            verdict = autonomy_verdict(payload, config=Config(), environment="host")
            assert verdict.allowed is True
            assert verdict.session.entries == ()

    def test_a_session_with_no_project_context_fails_loud(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ProjectContext.reset()
        monkeypatch.setattr(data_layer, "_data_layer", data_layer.DaemonDataLayer())
        with pytest.raises(RuntimeError, match="ProjectContext"):
            autonomy_verdict(self._payload(), config=Config(), environment="host")
