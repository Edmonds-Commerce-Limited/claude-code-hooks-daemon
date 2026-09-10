"""Tests for the tool-disable advisory (Plan 00293 Task 3.1).

Opt-in, ships disabled. At session start, for each tool the project declared
in ``tool_policy.never_want``, the advisory checks whether the source-level
disable is actually in place in ``.claude/settings.json`` and, when it is
not, names the exact settings change. It NEVER edits settings itself.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.session_start.tool_disable_advisor import (
    ToolDisableAdvisorHandler,
)

_SESSION_START: dict[str, Any] = {"hook_event_name": "SessionStart", "source": "startup"}


def _project(
    tmp_path: Path, *, config_yaml: str = "", settings: dict[str, Any] | None = None
) -> Path:
    root = tmp_path / "proj"
    (root / ".claude").mkdir(parents=True)
    if config_yaml:
        (root / ".claude" / "hooks-daemon.yaml").write_text(config_yaml)
    if settings is not None:
        (root / ".claude" / "settings.json").write_text(json.dumps(settings))
    return root


class _RootedToolDisableAdvisorHandler(ToolDisableAdvisorHandler):
    """Test double declaring `_workspace_root` so it is a known instance attribute.

    The handler itself reads `_workspace_root` dynamically via
    `getattr(self, "_workspace_root", None)`, so assigning it here inside
    `__init__` (rather than from outside the class) mirrors that.
    """

    def __init__(self, root: Path) -> None:
        super().__init__()
        self._workspace_root = root


def _handler(root: Path) -> ToolDisableAdvisorHandler:
    return _RootedToolDisableAdvisorHandler(root)


_NEVER_WANT_YAML = "tool_policy:\n  never_want:\n    - {tool: Artifact, reason: no publishing}\n"


class TestInitialization:
    def test_identity_and_priority(self) -> None:
        handler = ToolDisableAdvisorHandler()
        assert handler.handler_id == HandlerID.TOOL_DISABLE_ADVISOR
        assert handler.priority == Priority.TOOL_DISABLE_ADVISOR

    def test_ships_disabled(self) -> None:
        assert ToolDisableAdvisorHandler().get_default_enabled() is False

    def test_never_terminal(self) -> None:
        assert ToolDisableAdvisorHandler().terminal is False


class TestMatches:
    def test_no_declarations_means_no_match(self, tmp_path: Path) -> None:
        handler = _handler(_project(tmp_path))
        assert handler.matches(_SESSION_START) is False

    def test_declaration_matches_session_start(self, tmp_path: Path) -> None:
        handler = _handler(_project(tmp_path, config_yaml=_NEVER_WANT_YAML))
        assert handler.matches(_SESSION_START) is True


class TestAdvice:
    def test_missing_disable_names_the_exact_change(self, tmp_path: Path) -> None:
        root = _project(tmp_path, config_yaml=_NEVER_WANT_YAML, settings={})
        result = _handler(root).handle(_SESSION_START)
        assert result.decision == Decision.ALLOW
        text = "\n".join(result.context)
        assert "Artifact" in text
        assert "enableArtifact" in text

    def test_enable_artifact_false_satisfies_the_declaration(self, tmp_path: Path) -> None:
        root = _project(tmp_path, config_yaml=_NEVER_WANT_YAML, settings={"enableArtifact": False})
        result = _handler(root).handle(_SESSION_START)
        text = "\n".join(result.context)
        assert "enableArtifact" not in text or "in place" in text

    def test_deny_rule_satisfies_a_generic_tool(self, tmp_path: Path) -> None:
        yaml = "tool_policy:\n  never_want:\n    - {tool: NotebookEdit}\n"
        root = _project(
            tmp_path,
            config_yaml=yaml,
            settings={"permissions": {"deny": ["NotebookEdit"]}},
        )
        result = _handler(root).handle(_SESSION_START)
        assert all("permissions.deny" not in line or "in place" in line for line in result.context)

    def test_satisfied_artifact_flags_blocker_demotion_option(self, tmp_path: Path) -> None:
        """Disable in place but the blocker's own enforcement off → the
        advisory names the source_disable option and the blocker by name."""
        root = _project(tmp_path, config_yaml=_NEVER_WANT_YAML, settings={"enableArtifact": False})
        result = _handler(root).handle(_SESSION_START)
        text = "\n".join(result.context)
        assert "artifact_publish_blocker" in text

    def test_source_disable_already_on_suppresses_the_demotion_hint(self, tmp_path: Path) -> None:
        """This repo's own dogfood shape: enforcement already lives in the
        blocker's option, so the advisory must not re-suggest it."""
        yaml = (
            _NEVER_WANT_YAML
            + "handlers:\n"
            + "  pre_tool_use:\n"
            + "    artifact_publish_blocker:\n"
            + "      enabled: true\n"
            + "      options: {source_disable: true}\n"
        )
        root = _project(tmp_path, config_yaml=yaml, settings={"enableArtifact": False})
        result = _handler(root).handle(_SESSION_START)
        text = "\n".join(result.context)
        assert "in place" in text
        assert "can also enforce" not in text

    def test_never_edits_settings(self, tmp_path: Path) -> None:
        root = _project(tmp_path, config_yaml=_NEVER_WANT_YAML, settings={})
        _handler(root).handle(_SESSION_START)
        assert json.loads((root / ".claude" / "settings.json").read_text()) == {}

    def test_invalid_daemon_config_degrades_to_silent(self, tmp_path: Path) -> None:
        """An unloadable hooks-daemon.yaml (already reported elsewhere) must
        make this advisory silent, not raise out of the SessionStart chain."""
        root = _project(tmp_path, config_yaml="version: 1.0\n")
        handler = _handler(root)
        assert handler.matches(_SESSION_START) is False

    def test_broken_settings_file_does_not_crash(self, tmp_path: Path) -> None:
        root = _project(tmp_path, config_yaml=_NEVER_WANT_YAML)
        (root / ".claude" / "settings.json").write_text("{broken")
        result = _handler(root).handle(_SESSION_START)
        assert result.decision == Decision.ALLOW


class TestConfigReloadHygiene:
    """Task 2.11 (Plan 00295): handle() previously re-derived tool_policy via
    a redundant self.matches(hook_input) call on top of its own lookup,
    re-parsing+re-validating hooks-daemon.yaml from disk a second time for
    the exact same event -- up to three loads per event once matches() (the
    framework's own separate call) is counted."""

    def test_handle_loads_config_at_most_once_for_tool_policy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A `handle()` call that only needs tool_policy (the 'missing
        disable' path, which never reaches the separate
        _blocker_source_disable_on() load) must load config exactly once,
        not twice."""
        root = _project(tmp_path, config_yaml=_NEVER_WANT_YAML, settings={})
        handler = _handler(root)

        calls = {"n": 0}
        real_load = Config.load_or_default

        def _counting_load(*args: Any, **kwargs: Any) -> Config:
            calls["n"] += 1
            return real_load(*args, **kwargs)

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.session_start."
            "tool_disable_advisor.Config.load_or_default",
            _counting_load,
        )

        result = handler.handle(_SESSION_START)

        assert result.decision == Decision.ALLOW
        assert calls["n"] == 1

    def test_blocker_source_disable_on_survives_unloadable_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_blocker_source_disable_on() must degrade to False rather than
        raise when the config it loads is invalid -- the SAME resilience
        contract _tool_policy() already provides, so a crash here does not
        take down the SessionStart chain."""
        root = _project(tmp_path, config_yaml=_NEVER_WANT_YAML, settings={"enableArtifact": False})
        handler = _handler(root)

        def _raise(*args: Any, **kwargs: Any) -> Config:
            raise ValueError("simulated malformed config")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.session_start."
            "tool_disable_advisor.Config.load_or_default",
            _raise,
        )

        assert handler._blocker_source_disable_on() is False


class TestGuidance:
    def test_get_claude_md_documents_the_advisory(self) -> None:
        guidance = ToolDisableAdvisorHandler().get_claude_md()
        assert guidance is not None
        assert "tool_disable_advisor" in guidance
        assert "never_want" in guidance
