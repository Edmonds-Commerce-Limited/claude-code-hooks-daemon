"""Tests for hook registration validation utility."""

from __future__ import annotations

from claude_code_hooks_daemon.constants.events import EventID, EventIDMeta
from claude_code_hooks_daemon.utils.hook_registration import (
    HOOK_EVENTS_IN_SETTINGS,
    ReconcileResult,
    detect_duplicate_hooks,
    detect_legacy_hook_commands,
    detect_local_hooks_misplacement,
    reconcile_settings_hooks,
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
        # StatusLine is not in the hooks section; catalogued-but-unwired events
        # (Plan 00170 burn-down) have no forwarder/registration yet.
        if json_key == "StatusLine" or not event_id.wired:
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
    """Verify HOOK_EVENTS_IN_SETTINGS matches the WIRED EventID set (minus StatusLine)."""

    def test_matches_event_id_excluding_status_line(self) -> None:
        """HOOK_EVENTS_IN_SETTINGS must include all WIRED EventID json_keys except StatusLine.

        Catalogued-but-unwired events (Plan 00170 burn-down) are deliberately
        excluded: they have no forwarder or settings registration yet, so
        requiring them here would make hook_registration_checker flag a missing
        hook that does not exist.
        """
        expected_keys = {
            eid.json_key for eid in _all_event_ids() if eid.wired and eid.json_key != "StatusLine"
        }
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

    def test_non_dict_hook_entry_does_not_raise(self) -> None:
        """A non-dict hook entry must be skipped, not crash with AttributeError.

        Regression: event_hooks[0].get(...) assumed a dict; a list/str entry in
        malformed settings.json raised AttributeError, crashing the validator
        that is meant to diagnose the malformed config.
        """
        settings = _build_settings_with_all_hooks()
        settings["hooks"]["Stop"] = ["not-a-dict"]
        issues = validate_hook_commands(settings)
        assert isinstance(issues, list)

    def test_non_dict_inner_hook_does_not_raise(self) -> None:
        """A non-dict inner hook entry must be skipped, not crash."""
        settings = _build_settings_with_all_hooks()
        settings["hooks"]["Stop"] = [{"hooks": ["not-a-dict"]}]
        issues = validate_hook_commands(settings)
        assert isinstance(issues, list)

    def test_non_string_command_does_not_raise(self) -> None:
        """A non-string command must be skipped, not crash on .endswith().

        Regression: command.endswith(...) assumed a str; a null/number command
        in malformed settings.json raised AttributeError.
        """
        settings = _build_settings_with_all_hooks()
        settings["hooks"]["Stop"] = [{"hooks": [{"type": "command", "command": 123}]}]
        issues = validate_hook_commands(settings)
        assert isinstance(issues, list)


class TestValidateHookCommandsWithNativeHooks:
    """A native ``prompt``/``agent`` hook alongside the daemon wrapper is legal.

    Plan 00266 measured this validator misreporting two of the three layouts for
    adding one. Claude Code supports ``type: prompt`` and ``type: agent`` hooks,
    which carry no ``command`` key at all, and documents that all matching hooks
    run in parallel — so coexisting with the daemon's own ``command`` hook is
    the supported arrangement, not a misconfiguration.
    """

    @staticmethod
    def _native() -> dict:
        """A native prompt hook: note there is no ``command`` key."""
        return {"type": "prompt", "prompt": "Is this allowed? $ARGUMENTS"}

    @staticmethod
    def _daemon() -> dict:
        return {
            "type": "command",
            "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/stop',
        }

    def test_native_hook_in_separate_entry_is_not_a_duplicate(self) -> None:
        """Layout A: a native hook as its own matcher entry.

        This is the layout a scoped native hook is FORCED into, because a
        matcher applies per entry. It was reported as
        'Stop has 2 hook entries (expected 1) — likely duplicate registration'.
        """
        settings = _build_settings_with_all_hooks()
        settings["hooks"]["Stop"] = [
            {"hooks": [self._daemon()]},
            {"matcher": "Bash", "hooks": [self._native()]},
        ]
        assert validate_hook_commands(settings) == []

    def test_native_hook_before_daemon_command_is_not_flagged(self) -> None:
        """Layout C: native hook first inside the same entry.

        Only ``inner_hooks[0]`` was inspected, so the native hook's absent
        ``command`` yielded '' and failed the suffix check, reporting
        "command does not end with /.claude/hooks/stop: got ''".
        """
        settings = _build_settings_with_all_hooks()
        settings["hooks"]["Stop"] = [{"hooks": [self._native(), self._daemon()]}]
        assert validate_hook_commands(settings) == []

    def test_native_hook_after_daemon_command_is_not_flagged(self) -> None:
        """Layout B: the one layout that was already clean. Guards it."""
        settings = _build_settings_with_all_hooks()
        settings["hooks"]["Stop"] = [{"hooks": [self._daemon(), self._native()]}]
        assert validate_hook_commands(settings) == []

    def test_two_daemon_commands_across_entries_still_flagged(self) -> None:
        """The real duplicate this check exists for must still be caught.

        Relaxing the entry count must not blind the validator to an actual
        double registration of the daemon wrapper, which fires every hook twice.
        """
        settings = _build_settings_with_all_hooks()
        settings["hooks"]["Stop"] = [
            {"hooks": [self._daemon()]},
            {"hooks": [self._daemon()]},
        ]
        issues = validate_hook_commands(settings)
        assert len(issues) == 1
        assert "Stop" in issues[0]

    def test_two_daemon_commands_in_one_entry_still_flagged(self) -> None:
        """The same duplicate, nested in a single entry, is equally real."""
        settings = _build_settings_with_all_hooks()
        settings["hooks"]["Stop"] = [{"hooks": [self._daemon(), self._daemon()]}]
        issues = validate_hook_commands(settings)
        assert len(issues) == 1
        assert "Stop" in issues[0]

    def test_native_hook_replacing_daemon_wrapper_is_reported(self) -> None:
        """A native hook must sit ALONGSIDE the wrapper, never replace it.

        ``reconcile_settings_hooks`` is additive per EVENT, so once an event
        key exists the daemon's self-heal will not restore a wrapper it no
        longer sees — every handler on that event goes silently dark. The
        previous message for this case blamed a malformed command; it is
        really a missing daemon registration.
        """
        settings = _build_settings_with_all_hooks()
        settings["hooks"]["Stop"] = [{"hooks": [self._native()]}]
        issues = validate_hook_commands(settings)
        assert len(issues) == 1
        assert "Stop" in issues[0]
        assert "no daemon" in issues[0].lower()


class TestDetectLocalHooksMisplacement:
    """Tests for detect_local_hooks_misplacement().

    Policy: hooks config must live exclusively in settings.json. Any hooks
    entry in settings.local.json violates the policy regardless of whether
    it duplicates an entry in settings.json.
    """

    def test_no_hooks_in_local_returns_empty(self) -> None:
        local_settings = {"permissions": {"allow": ["Bash(ls:*)"]}}
        issues = detect_local_hooks_misplacement(local_settings)
        assert issues == []

    def test_empty_local_returns_empty(self) -> None:
        assert detect_local_hooks_misplacement({}) == []

    def test_empty_hooks_dict_returns_empty(self) -> None:
        assert detect_local_hooks_misplacement({"hooks": {}}) == []

    def test_single_hook_in_local_flagged(self) -> None:
        local_settings = {
            "hooks": {
                "PreToolUse": [{"hooks": [{"type": "command", "command": "x"}]}],
            }
        }
        issues = detect_local_hooks_misplacement(local_settings)
        assert len(issues) == 1
        assert "PreToolUse" in issues[0]
        assert "settings.local.json" in issues[0]

    def test_multiple_hooks_in_local_each_flagged(self) -> None:
        local_settings = {
            "hooks": {
                "PreToolUse": [{"hooks": [{"type": "command", "command": "x"}]}],
                "PostToolUse": [{"hooks": [{"type": "command", "command": "y"}]}],
                "Stop": [{"hooks": [{"type": "command", "command": "z"}]}],
            }
        }
        issues = detect_local_hooks_misplacement(local_settings)
        assert len(issues) == 3
        for key in ("PreToolUse", "PostToolUse", "Stop"):
            assert any(key in issue for issue in issues)

    def test_local_hooks_flagged_even_if_unique(self) -> None:
        """A local-only hook (not a duplicate) is still a policy violation."""
        local_settings = {
            "hooks": {
                "Notification": [{"hooks": [{"type": "command", "command": "x"}]}],
            }
        }
        issues = detect_local_hooks_misplacement(local_settings)
        assert len(issues) == 1
        assert "Notification" in issues[0]

    def test_non_dict_hooks_key_returns_empty(self) -> None:
        """Malformed hooks key (not a dict) is not flagged — it's a parse issue."""
        assert detect_local_hooks_misplacement({"hooks": "garbage"}) == []

    def test_message_mentions_moving_to_settings_json(self) -> None:
        """Warning text must include remediation guidance."""
        local_settings = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]}}
        issues = detect_local_hooks_misplacement(local_settings)
        assert len(issues) == 1
        assert "settings.json" in issues[0]


class TestDetectLegacyHookCommands:
    """Tests for detect_legacy_hook_commands().

    A "legacy-style" hook is a settings entry whose command does not invoke
    the daemon's .claude/hooks/{bash_key} wrapper — e.g. a raw python script
    or inline shell. Such setups bypass the daemon entirely; custom logic
    should live in project-level handlers instead.
    """

    def test_all_daemon_wrappers_returns_empty(self) -> None:
        settings = _build_settings_with_all_hooks()
        issues = detect_legacy_hook_commands(settings)
        assert issues == []

    def test_inline_python_command_flagged(self) -> None:
        settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "python /opt/custom/my_hook.py",
                            }
                        ]
                    }
                ]
            }
        }
        issues = detect_legacy_hook_commands(settings)
        assert len(issues) == 1
        assert "PreToolUse" in issues[0]
        assert "project-level handler" in issues[0] or "project handler" in issues[0]

    def test_bash_inline_command_flagged(self) -> None:
        settings = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo hello"}]}]}}
        issues = detect_legacy_hook_commands(settings)
        assert len(issues) == 1
        assert "Stop" in issues[0]

    def test_custom_script_path_flagged(self) -> None:
        settings = {
            "hooks": {
                "PostToolUse": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "/opt/myapp/scripts/hook.sh",
                            }
                        ]
                    }
                ]
            }
        }
        issues = detect_legacy_hook_commands(settings)
        assert len(issues) == 1
        assert "PostToolUse" in issues[0]

    def test_unknown_event_type_with_custom_command_flagged(self) -> None:
        """Unknown event types with custom commands are still legacy setups."""
        settings = {
            "hooks": {
                "UnknownEventXYZ": [{"hooks": [{"type": "command", "command": "python foo.py"}]}]
            }
        }
        issues = detect_legacy_hook_commands(settings)
        assert len(issues) == 1
        assert "UnknownEventXYZ" in issues[0]

    def test_mixed_daemon_and_legacy_only_legacy_flagged(self) -> None:
        settings = _build_settings_with_all_hooks()
        settings["hooks"]["Stop"] = [
            {"hooks": [{"type": "command", "command": "python /opt/x.py"}]}
        ]
        issues = detect_legacy_hook_commands(settings)
        assert len(issues) == 1
        assert "Stop" in issues[0]

    def test_no_hooks_key_returns_empty(self) -> None:
        assert detect_legacy_hook_commands({}) == []

    def test_empty_event_array_ignored(self) -> None:
        assert detect_legacy_hook_commands({"hooks": {"Stop": []}}) == []

    def test_entry_without_hooks_list_ignored(self) -> None:
        """Malformed entries should be tolerated (other validators catch them)."""
        settings = {"hooks": {"Stop": [{"hooks": []}]}}
        assert detect_legacy_hook_commands(settings) == []

    def test_command_with_claude_hooks_path_not_flagged(self) -> None:
        """Any command ending with /.claude/hooks/<script> is a daemon wrapper."""
        settings = {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "/abs/path/.claude/hooks/stop",
                            }
                        ]
                    }
                ]
            }
        }
        assert detect_legacy_hook_commands(settings) == []


class TestReconcileSettingsHooks:
    """SSoT-derived, idempotent MERGE that ADDS missing wired hook registrations.

    Unlike ``validate_settings_hooks`` (detect-only), ``reconcile_settings_hooks``
    returns a NEW settings dict with every missing wired event added, while
    preserving everything else (``permissions``/``env``/``statusLine``/unknown
    keys and any client-added hook entries). Input is never mutated.
    """

    def _wired_json_keys(self) -> set[str]:
        return set(HOOK_EVENTS_IN_SETTINGS.keys())

    def test_adds_all_missing_events_to_empty_settings(self) -> None:
        new_settings, result = reconcile_settings_hooks({})
        assert isinstance(result, ReconcileResult)
        assert result.changed is True
        assert set(result.events_added) == self._wired_json_keys()
        assert set(new_settings["hooks"].keys()) == self._wired_json_keys()

    def test_result_reports_sorted_events(self) -> None:
        _, result = reconcile_settings_hooks({})
        assert result.events_added == sorted(result.events_added)

    def test_reconciled_output_passes_validators(self) -> None:
        new_settings, _ = reconcile_settings_hooks({})
        assert validate_settings_hooks(new_settings) == []
        assert validate_hook_commands(new_settings) == []

    def test_adds_only_missing_events(self) -> None:
        # PreToolUse already present and correct — must not be re-added.
        existing = {
            "hooks": {
                "PreToolUse": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": 'bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/pre-tool-use',
                                "timeout": 60,
                            }
                        ]
                    }
                ]
            }
        }
        _, result = reconcile_settings_hooks(existing)
        assert "PreToolUse" not in result.events_added
        assert self._wired_json_keys() - {"PreToolUse"} == set(result.events_added)

    def test_idempotent_when_all_present(self) -> None:
        full = _build_settings_with_all_hooks()
        new_settings, result = reconcile_settings_hooks(full)
        assert result.changed is False
        assert result.events_added == []
        assert new_settings["hooks"].keys() == full["hooks"].keys()

    def test_preserves_permissions_env_statusline_and_unknown_keys(self) -> None:
        existing = {
            "permissions": {"allow": ["Bash(ls:*)"]},
            "env": {"FOO": "bar"},
            "statusLine": {"type": "command", "command": "my-custom-status"},
            "customKey": {"nested": True},
        }
        new_settings, _ = reconcile_settings_hooks(existing)
        assert new_settings["permissions"] == {"allow": ["Bash(ls:*)"]}
        assert new_settings["env"] == {"FOO": "bar"}
        assert new_settings["statusLine"] == {"type": "command", "command": "my-custom-status"}
        assert new_settings["customKey"] == {"nested": True}

    def test_preserves_existing_client_hook_entries(self) -> None:
        # A client added an extra custom hook entry under an event that already
        # exists — reconciliation must not touch present events.
        custom_entry = {"hooks": [{"type": "command", "command": "/my/custom/script"}]}
        existing = {"hooks": {"PreToolUse": [custom_entry]}}
        new_settings, result = reconcile_settings_hooks(existing)
        assert new_settings["hooks"]["PreToolUse"] == [custom_entry]
        assert "PreToolUse" not in result.events_added

    def test_pre_and_post_tool_use_get_timeout(self) -> None:
        new_settings, _ = reconcile_settings_hooks({})
        for json_key in ("PreToolUse", "PostToolUse"):
            cmd = new_settings["hooks"][json_key][0]["hooks"][0]
            assert cmd["timeout"] == 60
        # A non-timeout event must NOT carry a timeout key.
        session_cmd = new_settings["hooks"]["SessionStart"][0]["hooks"][0]
        assert "timeout" not in session_cmd

    def test_added_commands_use_bash_wrapper_form(self) -> None:
        new_settings, _ = reconcile_settings_hooks({})
        for json_key, bash_key in HOOK_EVENTS_IN_SETTINGS.items():
            cmd = new_settings["hooks"][json_key][0]["hooks"][0]["command"]
            assert cmd == f'bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/{bash_key}'

    def test_input_not_mutated(self) -> None:
        original = {"hooks": {}, "permissions": {"allow": []}}
        reconcile_settings_hooks(original)
        assert original == {"hooks": {}, "permissions": {"allow": []}}

    def test_handles_non_dict_hooks_gracefully(self) -> None:
        # A malformed hooks value is replaced with a fresh, fully-wired block
        # rather than crashing.
        new_settings, result = reconcile_settings_hooks({"hooks": "broken"})
        assert result.changed is True
        assert set(new_settings["hooks"].keys()) == self._wired_json_keys()
