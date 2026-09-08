"""The three-way settings.json merge (Plan 00176 Phase 2).

Today both upgrade routes copy the daemon's `settings.json` over the client's
verbatim, so anything the client added — an extra hook, a custom status line,
their own `permissions` — is gone. The merge replaces that copy.

The safety property is the DIRECTION of the copy, and these tests assert it
directly rather than incidentally: the merge starts from the client's document
and edits the daemon-owned parts of it. It never builds a daemon document and
grafts client keys on, because a merge cannot lose what it does not look at.

Rules under test are decided in MERGE-SPEC.md; the sections are cited per class.
"""

from __future__ import annotations

import copy
from typing import Any

from claude_code_hooks_daemon.install.settings_merge import merge_settings
from claude_code_hooks_daemon.utils.hook_command_migration import canonical_hook_command
from claude_code_hooks_daemon.utils.hook_registration import HOOK_EVENTS_IN_SETTINGS

# A real wired event, taken from the SSoT so this never drifts from the daemon.
_EVENT = "PreToolUse"
_BASH_KEY = HOOK_EVENTS_IN_SETTINGS[_EVENT]
_CANONICAL = canonical_hook_command(_BASH_KEY)


def _daemon_group(command: str = _CANONICAL) -> dict[str, Any]:
    return {"hooks": [{"type": "command", "command": command, "timeout": 60}]}


def _client_group(command: str) -> dict[str, Any]:
    return {"hooks": [{"type": "command", "command": command}]}


def _new_default() -> dict[str, Any]:
    """The daemon's shipped settings.json, in miniature."""
    return {
        "hooks": {
            json_key: [_daemon_group(canonical_hook_command(bash_key))]
            for json_key, bash_key in HOOK_EVENTS_IN_SETTINGS.items()
        },
        "statusLine": {
            "type": "command",
            "command": canonical_hook_command("status-line"),
            "refreshInterval": 1,
        },
        "permissions": {"deny": ["Edit(//tmp/**)"]},
        "enableArtifact": False,
        "plansDirectory": "./CLAUDE/Plan",
    }


def _old_default() -> dict[str, Any]:
    """The previous version's shipped settings.json: a slower status line."""
    old = _new_default()
    old["statusLine"]["refreshInterval"] = 1000
    return old


class TestTheClientDocumentIsTheStartingPoint:
    """MERGE-SPEC "No client-owned key is ever read"."""

    def test_a_key_the_daemon_has_never_heard_of_survives_verbatim(self) -> None:
        client = {"someFutureKey": {"nested": [1, 2, {"deep": True}]}}
        merged, _ = merge_settings(client, _new_default(), _old_default())
        assert merged["someFutureKey"] == {"nested": [1, 2, {"deep": True}]}

    def test_the_client_permissions_block_is_not_replaced(self) -> None:
        client = {"permissions": {"deny": ["Bash(rm:*)"], "allow": ["Read(//etc/**)"]}}
        merged, _ = merge_settings(client, _new_default(), _old_default())
        assert merged["permissions"] == {"deny": ["Bash(rm:*)"], "allow": ["Read(//etc/**)"]}

    def test_the_inputs_are_never_mutated(self) -> None:
        client = {"hooks": {}, "permissions": {"deny": []}}
        before = copy.deepcopy(client)
        merge_settings(client, _new_default(), _old_default())
        assert client == before


class TestTheClientsOwnHooksSurvive:
    def test_an_extra_hook_in_a_daemon_event_array_is_kept(self) -> None:
        """A client gate sharing an event array with our forwarder."""
        client = {"hooks": {_EVENT: [_daemon_group(), _client_group("./ci/extra-gate.sh")]}}
        merged, _ = merge_settings(client, _new_default(), _old_default())
        commands = _commands_for(merged, _EVENT)
        assert "./ci/extra-gate.sh" in commands

    def test_an_event_the_daemon_does_not_wire_is_kept(self) -> None:
        client = {"hooks": {"SomeClientEvent": [_client_group("./ci/theirs.sh")]}}
        merged, _ = merge_settings(client, _new_default(), _old_default())
        assert merged["hooks"]["SomeClientEvent"] == [_client_group("./ci/theirs.sh")]

    def test_a_client_script_living_under_dot_claude_hooks_is_not_ours(self) -> None:
        """MERGE-SPEC Q2: membership of the WIRED SET is what rejects this."""
        theirs = 'bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/my-secret-scan'
        client = {"hooks": {_EVENT: [_daemon_group(), _client_group(theirs)]}}
        merged, _ = merge_settings(client, _new_default(), _old_default())
        assert theirs in _commands_for(merged, _EVENT)

    def test_a_chained_command_is_not_ours(self) -> None:
        """Rebuilding it would silently drop the client's half."""
        chained = f"{_CANONICAL} && ./ci/extra-gate.sh"
        client = {"hooks": {_EVENT: [_client_group(chained)]}}
        merged, _ = merge_settings(client, _new_default(), _old_default())
        assert chained in _commands_for(merged, _EVENT)

    def test_a_hooks_directory_outside_this_repo_is_not_ours(self) -> None:
        """Anchoring is what rejects it — the fragment is present either way."""
        elsewhere = 'bash "$HOME"/dotfiles/.claude/hooks/lint'
        client = {"hooks": {_EVENT: [_client_group(elsewhere)]}}
        merged, _ = merge_settings(client, _new_default(), _old_default())
        assert elsewhere in _commands_for(merged, _EVENT)


class TestTheWiredSetIsCompleteAfterEveryMerge:
    def test_a_missing_wired_event_is_added(self) -> None:
        merged, report = merge_settings({"hooks": {}}, _new_default(), _old_default())
        assert set(HOOK_EVENTS_IN_SETTINGS) <= set(merged["hooks"])
        assert _EVENT in report.hooks_added

    def test_an_empty_client_document_comes_out_fully_wired(self) -> None:
        merged, _ = merge_settings({}, _new_default(), _old_default())
        for json_key, bash_key in HOOK_EVENTS_IN_SETTINGS.items():
            assert canonical_hook_command(bash_key) in _commands_for(merged, json_key)

    def test_an_event_holding_only_a_client_hook_gains_the_forwarder(self) -> None:
        """The key being present is not the same as our forwarder being present."""
        client = {"hooks": {_EVENT: [_client_group("./ci/theirs.sh")]}}
        merged, _ = merge_settings(client, _new_default(), _old_default())
        commands = _commands_for(merged, _EVENT)
        assert _CANONICAL in commands
        assert "./ci/theirs.sh" in commands

    def test_a_hooks_value_that_is_not_a_dict_is_replaced_wholesale(self) -> None:
        merged, _ = merge_settings({"hooks": "nonsense"}, _new_default(), _old_default())
        assert set(HOOK_EVENTS_IN_SETTINGS) <= set(merged["hooks"])


class TestAStaleForwarderIsRepaired:
    """MERGE-SPEC Q2 row three — the gap `reconcile_settings_hooks` cannot close."""

    def test_the_relative_legacy_shape_is_rebuilt_anchored(self) -> None:
        """The false negative a substring test would have left broken."""
        client = {"hooks": {_EVENT: [_client_group(f".claude/hooks/{_BASH_KEY}")]}}
        merged, report = merge_settings(client, _new_default(), _old_default())
        assert _commands_for(merged, _EVENT) == [_CANONICAL]
        assert _EVENT in report.hooks_refreshed

    def test_the_anchored_legacy_shape_is_rebuilt(self) -> None:
        client = {
            "hooks": {_EVENT: [_client_group(f'"$CLAUDE_PROJECT_DIR"/.claude/hooks/{_BASH_KEY}')]}
        }
        merged, _ = merge_settings(client, _new_default(), _old_default())
        assert _commands_for(merged, _EVENT) == [_CANONICAL]

    def test_a_rebuilt_entry_is_identical_to_a_freshly_installed_one(self) -> None:
        stale = {"hooks": {_EVENT: [_client_group(f".claude/hooks/{_BASH_KEY}")]}}
        fresh, _ = merge_settings({}, _new_default(), _old_default())
        repaired, _ = merge_settings(stale, _new_default(), _old_default())
        assert repaired["hooks"][_EVENT] == fresh["hooks"][_EVENT]

    def test_a_correct_forwarder_is_left_alone(self) -> None:
        client = {"hooks": {_EVENT: [_daemon_group()]}}
        _, report = merge_settings(client, _new_default(), _old_default())
        assert _EVENT not in report.hooks_refreshed

    def test_identity_is_the_command_not_the_position(self) -> None:
        """Reordering a client's hooks must not change which entry is ours."""
        client = {"hooks": {_EVENT: [_client_group("./ci/first.sh"), _daemon_group()]}}
        merged, report = merge_settings(client, _new_default(), _old_default())
        assert _commands_for(merged, _EVENT) == ["./ci/first.sh", _CANONICAL]
        assert _EVENT not in report.hooks_refreshed


class TestRecommendedDefaults:
    """MERGE-SPEC key-ownership: `statusLine.command` / `statusLine.refreshInterval`."""

    def test_a_value_still_at_the_old_default_is_upgraded(self) -> None:
        client = {"statusLine": {"type": "command", "refreshInterval": 1000}}
        merged, report = merge_settings(client, _new_default(), _old_default())
        assert merged["statusLine"]["refreshInterval"] == 1
        assert "statusLine.refreshInterval" in report.defaults_upgraded

    def test_a_deliberate_override_is_preserved(self) -> None:
        client = {"statusLine": {"type": "command", "refreshInterval": 5000}}
        merged, report = merge_settings(client, _new_default(), _old_default())
        assert merged["statusLine"]["refreshInterval"] == 5000
        assert "statusLine.refreshInterval" not in report.defaults_upgraded

    def test_a_custom_status_line_command_survives(self) -> None:
        client = {"statusLine": {"type": "command", "command": "./bin/my-status"}}
        merged, _ = merge_settings(client, _new_default(), _old_default())
        assert merged["statusLine"]["command"] == "./bin/my-status"

    def test_an_unrelated_status_line_key_is_preserved(self) -> None:
        client = {"statusLine": {"type": "command", "padding": 0}}
        merged, _ = merge_settings(client, _new_default(), _old_default())
        assert merged["statusLine"]["padding"] == 0


class TestPresenceIsMergedThreeWayToo:
    """MERGE-SPEC Q4b — you can only override something you expressed an opinion about."""

    def test_a_key_new_this_version_is_delivered(self) -> None:
        old = _old_default()
        del old["plansDirectory"]
        merged, report = merge_settings({}, _new_default(), old)
        assert merged["plansDirectory"] == "./CLAUDE/Plan"
        assert "plansDirectory" in report.keys_delivered

    def test_a_key_the_client_deliberately_removed_stays_removed(self) -> None:
        """It is in the old default, so its absence is an expressed opinion."""
        merged, report = merge_settings({}, _new_default(), _old_default())
        assert "plansDirectory" not in merged
        assert "plansDirectory" in report.absences_preserved

    def test_a_client_value_wins_over_the_new_default(self) -> None:
        merged, _ = merge_settings(
            {"plansDirectory": "./docs/plans"}, _new_default(), _old_default()
        )
        assert merged["plansDirectory"] == "./docs/plans"


class TestWithNoBaselineNothingIsGuessed:
    """MERGE-SPEC Q2b — a fresh install, or Layer 2 invoked directly."""

    def test_a_preference_at_the_old_default_is_left_alone(self) -> None:
        """Without the baseline, an accepted default is indistinguishable from a choice."""
        client = {"statusLine": {"type": "command", "refreshInterval": 1000}}
        merged, report = merge_settings(client, _new_default(), None)
        assert merged["statusLine"]["refreshInterval"] == 1000
        assert not report.defaults_upgraded

    def test_an_absent_preference_is_not_delivered(self) -> None:
        merged, _ = merge_settings({}, _new_default(), None)
        assert "plansDirectory" not in merged

    def test_an_absent_security_default_IS_delivered_and_reported(self) -> None:
        """Declining to deliver a deny rule destroys nothing, but withholds a guard."""
        merged, report = merge_settings({}, _new_default(), None)
        assert merged["permissions"] == {"deny": ["Edit(//tmp/**)"]}
        assert "permissions" in report.keys_delivered

    def test_the_wired_set_is_still_completed(self) -> None:
        """The hooks block is force-refreshed regardless of baseline."""
        merged, _ = merge_settings({}, _new_default(), None)
        assert set(HOOK_EVENTS_IN_SETTINGS) <= set(merged["hooks"])


class TestTheReportSaysWhetherAnythingChanged:
    def test_an_already_merged_document_reports_no_change(self) -> None:
        merged, _ = merge_settings({}, _new_default(), _old_default())
        again, report = merge_settings(merged, _new_default(), _old_default())
        assert again == merged
        assert not report.changed

    def test_a_repaired_forwarder_reports_a_change(self) -> None:
        client = {"hooks": {_EVENT: [_client_group(f".claude/hooks/{_BASH_KEY}")]}}
        _, report = merge_settings(client, _new_default(), _old_default())
        assert report.changed


def _commands_for(settings: dict[str, Any], json_key: str) -> list[str]:
    """Every inner-hook command registered under one event, in order."""
    return [
        inner["command"]
        for group in settings["hooks"].get(json_key, [])
        for inner in group.get("hooks", [])
        if "command" in inner
    ]
