"""Tests for the tool-disable advisory (Plan 00293 Task 3.1).

Opt-in, ships disabled. At session start, for each tool the project declared
in ``tool_policy.never_want``, the advisory checks whether the source-level
disable is actually in place in ``.claude/settings.json`` and, when it is
not, names the exact settings change. It NEVER edits settings itself.
"""

import json
from pathlib import Path
from typing import Any

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


def _handler(root: Path) -> ToolDisableAdvisorHandler:
    handler = ToolDisableAdvisorHandler()
    handler._workspace_root = root
    return handler


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

    def test_broken_settings_file_does_not_crash(self, tmp_path: Path) -> None:
        root = _project(tmp_path, config_yaml=_NEVER_WANT_YAML)
        (root / ".claude" / "settings.json").write_text("{broken")
        result = _handler(root).handle(_SESSION_START)
        assert result.decision == Decision.ALLOW


class TestGuidance:
    def test_get_claude_md_documents_the_advisory(self) -> None:
        guidance = ToolDisableAdvisorHandler().get_claude_md()
        assert guidance is not None
        assert "tool_disable_advisor" in guidance
        assert "never_want" in guidance
