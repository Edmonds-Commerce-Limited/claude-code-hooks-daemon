"""Tests for hook registration validation utility."""

from __future__ import annotations

from claude_code_hooks_daemon.constants.events import EventID, EventIDMeta
from claude_code_hooks_daemon.utils.hook_registration import (
    HOOK_EVENTS_IN_SETTINGS,
    detect_duplicate_hooks,
    validate_hook_commands,
    validate_settings_hooks,
)


def _all_event_ids() -> list[EventIDMeta]:
    """Get all EventIDMeta instances from EventID."""
    return [
        getattr(EventID, name)
        for name in dir(EventID)
        if isinstance(getattr(EventID, name), EventIDMeta)
    ]


def _build_settings_with_all_hooks() -> dict:
    """Build a settings dict with all expected hooks registered."""
    hooks: dict = {}
    for event_id in _all_event_ids():
        json_key = event_id.json_key
        # StatusLine is not in the hooks section
        if json_key == "StatusLine":
            continue
        hooks[json_key] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": f'"$CLAUDE_PROJECT_DIR"/.claude/hooks/{event_id.bash_key}',
                        "timeout": 60,
                    }
                ]
            }
        ]
    return {"hooks": hooks}


class TestHookEventsConstant:
    """Verify HOOK_EVENTS_IN_SETTINGS matches EventID (minus StatusLine)."""

    def test_matches_event_id_excluding_status_line(self) -> None:
        """HOOK_EVENTS_IN_SETTINGS must include all EventID json_keys except StatusLine."""
        expected_keys = {eid.json_key for eid in _all_event_ids() if eid.json_key != "StatusLine"}
        assert set(HOOK_EVENTS_IN_SETTINGS.keys()) == expected_keys

    def test_bash_keys_match_event_id(self) -> None:
        """Each entry's bash_key must match EventID."""
        for json_key, bash_key in HOOK_EVENTS_IN_SETTINGS.items():
            # Find matching EventID
            matching = [eid for eid in _all_event_ids() if eid.json_key == json_key]
            assert len(matching) == 1, f"No EventID for {json_key}"
            assert matching[0].bash_key == bash_key


class TestValidateSettingsHooks:
    """Tests for validate_settings_hooks()."""

    def test_all_hooks_present_returns_empty(self) -> None:
        settings = _build_settings_with_all_hooks()
        issues = validate_settings_hooks(settings)
        assert issues == []

    def test_missing_one_hook_reports_it(self) -> None:
        settings = _build_settings_with_all_hooks()
        del settings["hooks"]["Stop"]
        issues = validate_settings_hooks(settings)
        assert len(issues) == 1
        assert "Stop" in issues[0]

    def test_missing_multiple_hooks_reports_all(self) -> None:
        settings = _build_settings_with_all_hooks()
        del settings["hooks"]["Stop"]
        del settings["hooks"]["PreToolUse"]
        issues = validate_settings_hooks(settings)
        assert len(issues) == 2

    def test_no_hooks_key_reports_all_missing(self) -> None:
        issues = validate_settings_hooks({})
        assert len(issues) == len(HOOK_EVENTS_IN_SETTINGS)

    def test_empty_hooks_dict_reports_all_missing(self) -> None:
        issues = validate_settings_hooks({"hooks": {}})
        assert len(issues) == len(HOOK_EVENTS_IN_SETTINGS)

    def test_extra_unknown_hooks_not_flagged(self) -> None:
        """Extra hook event types should not cause issues."""
        settings = _build_settings_with_all_hooks()
        settings["hooks"]["CustomEvent"] = [{"hooks": []}]
        issues = validate_settings_hooks(settings)
        assert issues == []


class TestDetectDuplicateHooks:
    """Tests for detect_duplicate_hooks()."""

    def test_no_duplicates_returns_empty(self) -> None:
        settings = _build_settings_with_all_hooks()
        local_settings: dict = {}
        issues = detect_duplicate_hooks(settings, local_settings)
        assert issues == []

    def test_local_has_no_hooks_returns_empty(self) -> None:
        settings = _build_settings_with_all_hooks()
        local_settings = {"permissions": {"allow": []}}
        issues = detect_duplicate_hooks(settings, local_settings)
        assert issues == []

    def test_duplicate_stop_hook_detected(self) -> None:
        settings = _build_settings_with_all_hooks()
        local_settings = {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": ".claude/hooks/stop",
                            }
                        ]
                    }
                ]
            }
        }
        issues = detect_duplicate_hooks(settings, local_settings)
        assert len(issues) == 1
        assert "Stop" in issues[0]
        assert "settings.local.json" in issues[0]

    def test_multiple_duplicates_detected(self) -> None:
        settings = _build_settings_with_all_hooks()
        local_settings = {
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "x"}]}],
                "PreToolUse": [{"hooks": [{"type": "command", "command": "y"}]}],
                "PostToolUse": [{"hooks": [{"type": "command", "command": "z"}]}],
            }
        }
        issues = detect_duplicate_hooks(settings, local_settings)
        assert len(issues) == 3

    def test_local_only_hook_not_flagged_as_duplicate(self) -> None:
        """A hook only in local (not in main) is not a duplicate."""
        settings = _build_settings_with_all_hooks()
        del settings["hooks"]["Stop"]
        local_settings = {
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "x"}]}],
            }
        }
        issues = detect_duplicate_hooks(settings, local_settings)
        assert issues == []

    def test_both_empty_returns_empty(self) -> None:
        issues = detect_duplicate_hooks({}, {})
        assert issues == []


class TestValidateHookCommands:
    """Tests for validate_hook_commands()."""

    def test_all_commands_correct_returns_empty(self) -> None:
        settings = _build_settings_with_all_hooks()
        issues = validate_hook_commands(settings)
        assert issues == []

    def test_wrong_script_name_detected(self) -> None:
        settings = _build_settings_with_all_hooks()
        settings["hooks"]["Stop"] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/wrong-name',
                    }
                ]
            }
        ]
        issues = validate_hook_commands(settings)
        assert len(issues) == 1
        assert "Stop" in issues[0]
        assert "wrong-name" in issues[0]

    def test_no_hooks_key_returns_empty(self) -> None:
        """No hooks key means nothing to validate commands for."""
        issues = validate_hook_commands({})
        assert issues == []

    def test_empty_hooks_array_not_flagged(self) -> None:
        """An event with empty hooks array is a missing hook issue, not a command issue."""
        settings = _build_settings_with_all_hooks()
        settings["hooks"]["Stop"] = []
        issues = validate_hook_commands(settings)
        assert issues == []

    def test_multiple_commands_per_event_detected(self) -> None:
        """Multiple hook entries for one event type is suspicious."""
        settings = _build_settings_with_all_hooks()
        settings["hooks"]["Stop"] = [
            {"hooks": [{"type": "command", "command": ".claude/hooks/stop"}]},
            {"hooks": [{"type": "command", "command": ".claude/hooks/stop"}]},
        ]
        issues = validate_hook_commands(settings)
        assert len(issues) >= 1
        assert "Stop" in issues[0]
        assert "multiple" in issues[0].lower() or "2" in issues[0]
