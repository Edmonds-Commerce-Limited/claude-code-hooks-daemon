"""The handler-key audit: every ``handlers.<event>.<key>`` is checked against the registry.

Plan 00362 Task 1.2. A client upgraded to v3.62.1 with
``stop.hedging_language_detector`` and ``stop.dismissive_language_detector``
still in its config. Both had moved to ``pseudo_events.nitpick.handlers``;
``config-validate`` said ``valid: true``, the upgrade said "no config changes",
and the two detectors silently did not run. Nothing anywhere compared a config
key against what the registry actually knows for that event.

These tests pin the audit that closes the gap, and the migration that moves the
two relocated keys automatically.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from claude_code_hooks_daemon.config.validator import ConfigValidator
from claude_code_hooks_daemon.constants.handlers import (
    RELOCATED_HANDLERS,
    RETIRED_HANDLERS,
    HandlerRelocation,
)
from claude_code_hooks_daemon.install.handler_key_audit import (
    _DEFAULT_PSEUDO_EVENT_BLOCKS,
    HandlerKeyFinding,
    HandlerKeyMigration,
    applied_relocations,
    audit_handler_keys,
    format_findings,
    migrate_relocated_handler_keys,
    scaffold_pseudo_event_blocks,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The template a new project starts from -- what a scaffolded block must agree
#: with, since that is the block every other install ends up carrying.
EXAMPLE_CONFIG = REPO_ROOT / ".claude" / "hooks-daemon.yaml.example"


def _shipped_pseudo_events() -> dict[str, Any]:
    """The ``pseudo_events`` section of the shipped example config."""
    loaded = yaml.safe_load(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
    return loaded["pseudo_events"]


def _config(handlers: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "version": "2.0",
        "daemon": {"log_level": "INFO", "idle_timeout_seconds": 600},
        "handlers": handlers,
        **extra,
    }


def _by_path(findings: list[HandlerKeyFinding]) -> dict[str, HandlerKeyFinding]:
    return {f.path: f for f in findings}


class TestRelocationConstant:
    def test_both_nitpick_detectors_are_relocations(self) -> None:
        assert RELOCATED_HANDLERS["hedging_language_detector"] == HandlerRelocation(
            pseudo_event="nitpick", config_key="hedging_language"
        )
        assert RELOCATED_HANDLERS["dismissive_language_detector"] == HandlerRelocation(
            pseudo_event="nitpick", config_key="dismissive_language"
        )

    def test_every_relocation_is_also_retired(self) -> None:
        """A relocated key is accepted silently at startup, like any retired key."""
        assert set(RELOCATED_HANDLERS) <= set(RETIRED_HANDLERS)

    def test_relocation_target_path(self) -> None:
        assert (
            RELOCATED_HANDLERS["hedging_language_detector"].target_path
            == "pseudo_events.nitpick.handlers.hedging_language"
        )


class TestAuditHandlerKeys:
    def test_clean_config_has_no_findings(self) -> None:
        config = _config(
            {
                "pre_tool_use": {"destructive_git": {"enabled": True, "priority": 10}},
                "stop": {"auto_continue_stop": {"enabled": True, "priority": 10}},
            }
        )
        assert audit_handler_keys(config) == []

    def test_relocated_key_names_its_new_home(self) -> None:
        config = _config({"stop": {"hedging_language_detector": {"enabled": True, "priority": 30}}})
        findings = _by_path(audit_handler_keys(config))
        finding = findings["handlers.stop.hedging_language_detector"]
        assert finding.kind == "relocated"
        assert finding.event == "stop"
        assert finding.key == "hedging_language_detector"
        assert finding.target_path == "pseudo_events.nitpick.handlers.hedging_language"
        assert "pseudo_events.nitpick.handlers.hedging_language" in finding.message
        assert "no longer" in finding.message

    def test_key_under_wrong_event_names_the_right_event(self) -> None:
        config = _config({"stop": {"pipe_blocker": {"enabled": True, "priority": 20}}})
        findings = _by_path(audit_handler_keys(config))
        finding = findings["handlers.stop.pipe_blocker"]
        assert finding.kind == "wrong_event"
        assert finding.target_path == "handlers.pre_tool_use.pipe_blocker"
        assert "pre_tool_use" in finding.message

    def test_pseudo_event_key_under_a_real_event_points_at_the_pseudo_event(self) -> None:
        config = _config({"stop": {"hedging_language": {"enabled": True}}})
        findings = _by_path(audit_handler_keys(config))
        finding = findings["handlers.stop.hedging_language"]
        assert finding.kind == "wrong_event"
        assert finding.target_path == "pseudo_events.nitpick.handlers.hedging_language"

    def test_retired_key_says_no_longer_exists_with_the_reason(self) -> None:
        config = _config({"notification": {"notification_logger": {"enabled": True}}})
        findings = _by_path(audit_handler_keys(config))
        finding = findings["handlers.notification.notification_logger"]
        assert finding.kind == "retired"
        assert finding.target_path is None
        assert "no longer exists" in finding.message
        assert RETIRED_HANDLERS["notification_logger"] in finding.message

    def test_unknown_key_is_reported_as_unknown(self) -> None:
        config = _config({"pre_tool_use": {"no_such_handler_xyz": {"enabled": True}}})
        findings = _by_path(audit_handler_keys(config))
        finding = findings["handlers.pre_tool_use.no_such_handler_xyz"]
        assert finding.kind == "unknown"
        assert "not a handler registered for any event" in finding.message

    def test_unknown_key_suggests_a_close_match(self) -> None:
        config = _config({"pre_tool_use": {"pipe_blockr": {"enabled": True}}})
        findings = _by_path(audit_handler_keys(config))
        assert "pipe_blocker" in findings["handlers.pre_tool_use.pipe_blockr"].message

    def test_every_client_report_key_is_explained(self) -> None:
        """Every key the client report listed gets a finding that is not 'unknown'."""
        reported = {
            "notification": ["notification_logger"],
            "post_tool_use": ["bash_error_detector"],
            "pre_compact": ["transcript_archiver"],
            "pre_tool_use": ["plan_completion_advisor", "task_tdd_advisor", "validate_plan_number"],
            "session_end": ["cleanup"],
            "session_start": ["yolo_container_detection"],
            "status_line": ["usage_tracking"],
            "stop": [
                "task_completion_checker",
                "hedging_language_detector",
                "dismissive_language_detector",
            ],
            "subagent_stop": ["remind_prompt_library", "subagent_completion_logger"],
        }
        config = _config(
            {event: {key: {"enabled": True} for key in keys} for event, keys in reported.items()}
        )
        findings = _by_path(audit_handler_keys(config))
        for event, keys in reported.items():
            for key in keys:
                assert findings[f"handlers.{event}.{key}"].kind in {"retired", "relocated"}, key

    def test_live_key_from_the_report_is_not_flagged(self) -> None:
        config = _config({"pre_tool_use": {"validate_instruction_content": {"enabled": True}}})
        assert audit_handler_keys(config) == []

    def test_non_dict_sections_are_skipped(self) -> None:
        assert audit_handler_keys({"handlers": "nope"}) == []
        assert audit_handler_keys(_config({"stop": "nope"})) == []
        assert audit_handler_keys({}) == []

    def test_unknown_event_is_not_audited(self) -> None:
        """An invalid event name is the schema's problem, not this audit's."""
        assert audit_handler_keys(_config({"not_an_event": {"pipe_blocker": {}}})) == []

    def test_findings_serialise(self) -> None:
        config = _config({"stop": {"hedging_language_detector": {"enabled": True}}})
        as_dict = audit_handler_keys(config)[0].to_dict()
        assert as_dict["path"] == "handlers.stop.hedging_language_detector"
        assert as_dict["kind"] == "relocated"
        assert as_dict["target_path"] == "pseudo_events.nitpick.handlers.hedging_language"

    def test_format_findings_one_line_each(self) -> None:
        config = _config(
            {
                "stop": {
                    "hedging_language_detector": {"enabled": True},
                    "pipe_blocker": {"enabled": True},
                }
            }
        )
        lines = format_findings(audit_handler_keys(config))
        assert len(lines) == 2
        assert all(line.startswith("handlers.stop.") for line in lines)


class TestMigrateRelocatedHandlerKeys:
    def test_moves_both_detectors_preserving_enabled_and_priority(self) -> None:
        config = _config(
            {
                "stop": {
                    "auto_continue_stop": {"enabled": True, "priority": 10},
                    "hedging_language_detector": {"enabled": True, "priority": 30},
                    "dismissive_language_detector": {"enabled": False, "priority": 58},
                }
            }
        )
        migrated, records = migrate_relocated_handler_keys(config)

        assert "hedging_language_detector" not in migrated["handlers"]["stop"]
        assert "dismissive_language_detector" not in migrated["handlers"]["stop"]
        assert migrated["handlers"]["stop"]["auto_continue_stop"] == {
            "enabled": True,
            "priority": 10,
        }
        nitpick = migrated["pseudo_events"]["nitpick"]
        assert nitpick["enabled"] is True
        assert nitpick["triggers"], "a fresh nitpick block must carry its triggers"
        assert nitpick["handlers"]["hedging_language"] == {"enabled": True, "priority": 30}
        assert nitpick["handlers"]["dismissive_language"] == {"enabled": False, "priority": 58}
        assert {r.source_path for r in records} == {
            "handlers.stop.hedging_language_detector",
            "handlers.stop.dismissive_language_detector",
        }
        assert all(r.action == "moved" for r in records)

    def test_input_is_not_mutated(self) -> None:
        config = _config({"stop": {"hedging_language_detector": {"enabled": True}}})
        migrate_relocated_handler_keys(config)
        assert "hedging_language_detector" in config["handlers"]["stop"]
        assert "pseudo_events" not in config

    def test_existing_target_wins_and_stale_copy_is_dropped(self) -> None:
        config = _config(
            {"stop": {"hedging_language_detector": {"enabled": True, "priority": 30}}},
            pseudo_events={
                "nitpick": {
                    "enabled": True,
                    "triggers": ["stop:1/1"],
                    "handlers": {"hedging_language": {"enabled": False}},
                }
            },
        )
        migrated, records = migrate_relocated_handler_keys(config)
        assert migrated["pseudo_events"]["nitpick"]["handlers"]["hedging_language"] == {
            "enabled": False
        }
        assert migrated["pseudo_events"]["nitpick"]["triggers"] == ["stop:1/1"]
        assert "hedging_language_detector" not in migrated["handlers"]["stop"]
        assert len(records) == 1
        assert records[0].action == "dropped_duplicate"

    def test_existing_nitpick_block_keeps_its_own_settings(self) -> None:
        config = _config(
            {"stop": {"dismissive_language_detector": {"enabled": True}}},
            pseudo_events={"nitpick": {"enabled": False, "triggers": ["stop:1/2"]}},
        )
        migrated, _ = migrate_relocated_handler_keys(config)
        nitpick = migrated["pseudo_events"]["nitpick"]
        assert nitpick["enabled"] is False
        assert nitpick["triggers"] == ["stop:1/2"]
        assert nitpick["handlers"]["dismissive_language"] == {"enabled": True}

    def test_without_scaffold_only_the_handler_entry_is_written(self) -> None:
        """Pre-diff migration must not invent triggers the new default will supply."""
        config = _config({"stop": {"hedging_language_detector": {"enabled": False}}})
        migrated, records = migrate_relocated_handler_keys(config, scaffold=False)
        assert migrated["pseudo_events"]["nitpick"] == {
            "handlers": {"hedging_language": {"enabled": False}}
        }
        assert [r.action for r in records] == ["moved"]

    def test_scaffold_fills_missing_block_keys_and_keeps_present_ones(self) -> None:
        config = _config(
            {},
            pseudo_events={"nitpick": {"triggers": ["stop:1/2"], "handlers": {}}},
        )
        scaffolded = scaffold_pseudo_event_blocks(config)
        assert scaffolded["pseudo_events"]["nitpick"]["triggers"] == ["stop:1/2"]
        assert scaffolded["pseudo_events"]["nitpick"]["enabled"] is True
        assert "pseudo_events" not in _config({})
        assert scaffold_pseudo_event_blocks(_config({})) == _config({})

    def test_nothing_to_migrate_returns_equal_config_and_no_records(self) -> None:
        config = _config({"stop": {"auto_continue_stop": {"enabled": True}}})
        migrated, records = migrate_relocated_handler_keys(config)
        assert migrated == config
        assert records == []

    def test_migrated_config_passes_the_audit(self) -> None:
        config = _config(
            {
                "stop": {
                    "hedging_language_detector": {"enabled": True},
                    "dismissive_language_detector": {"enabled": True},
                }
            }
        )
        migrated, _ = migrate_relocated_handler_keys(config)
        assert audit_handler_keys(migrated) == []

    def test_record_serialises_with_a_summary(self) -> None:
        record = HandlerKeyMigration(
            source_path="handlers.stop.hedging_language_detector",
            target_path="pseudo_events.nitpick.handlers.hedging_language",
            action="moved",
        )
        as_dict = record.to_dict()
        assert as_dict["action"] == "moved"
        assert (
            as_dict["summary"] == "handlers.stop.hedging_language_detector -> "
            "pseudo_events.nitpick.handlers.hedging_language"
        )


class TestAppliedRelocations:
    """What the upgrade summary reports: relocations the merge actually performed."""

    def test_reports_keys_the_backup_had_and_the_new_config_moved(self) -> None:
        before = _config({"stop": {"hedging_language_detector": {"enabled": True}}})
        after, _ = migrate_relocated_handler_keys(before)
        applied = applied_relocations(before, after)
        assert [r.source_path for r in applied] == ["handlers.stop.hedging_language_detector"]
        assert applied[0].target_path == "pseudo_events.nitpick.handlers.hedging_language"

    def test_nothing_reported_when_the_key_is_still_there(self) -> None:
        before = _config({"stop": {"hedging_language_detector": {"enabled": True}}})
        assert applied_relocations(before, before) == []

    def test_nothing_reported_when_the_key_vanished_without_a_target(self) -> None:
        before = _config({"stop": {"hedging_language_detector": {"enabled": True}}})
        after = _config({"stop": {}})
        assert applied_relocations(before, after) == []


class TestDefaultBlocksMatchTheShippedConfig:
    """The scaffolded triggers are the shipped ones, pinned rather than claimed.

    Plan 00364 Task 2.3. The constant's comment says "Triggers match the
    reference config" and nothing checked it. A scaffolded block whose
    triggers drifted from what the daemon ships fires on a different cadence
    than every other install, which is the relocated handler half-retired
    again -- the exact failure this module exists to prevent.
    """

    def test_every_default_block_matches_the_example_config(self) -> None:
        shipped = _shipped_pseudo_events()
        for name, block in _DEFAULT_PSEUDO_EVENT_BLOCKS.items():
            assert name in shipped, f"{name} is scaffolded but the example config has no block"
            assert block["triggers"] == shipped[name]["triggers"]
            assert block["enabled"] == shipped[name]["enabled"]

    def test_every_relocation_target_has_a_default_block(self) -> None:
        """Otherwise the migration lands the handler under a block that never fires."""
        targets = {relocation.pseudo_event for relocation in RELOCATED_HANDLERS.values()}
        assert targets <= set(_DEFAULT_PSEUDO_EVENT_BLOCKS)


class TestTheSuggestionHelperIsADeclaredDependency:
    """The audit's "did you mean" hint comes from a PUBLIC helper.

    Plan 00364 Task 2.3. It called ``ConfigValidator._find_similar_names``,
    a private method of another class: a dependency nothing declared, which a
    rename inside the validator would have broken from across the package.
    """

    def test_the_helper_is_public(self) -> None:
        assert hasattr(ConfigValidator, "find_similar_names")
        assert not hasattr(ConfigValidator, "_find_similar_names")

    def test_the_audit_hint_uses_it(self) -> None:
        findings = audit_handler_keys(_config({"stop": {"auto_continue_stopp": True}}))
        assert len(findings) == 1
        assert "Did you mean: auto_continue_stop?" in findings[0].message

    def test_no_close_match_yields_no_hint(self) -> None:
        findings = audit_handler_keys(_config({"stop": {"zzzzzzzzzz": True}}))
        assert len(findings) == 1
        assert "Did you mean" not in findings[0].message


class TestAnUnknownRelocationTargetIsRefused:
    """A relocation target with no default block raises rather than half-landing.

    Plan 00364 Task 2.3. The fallback wrote ``{enabled: True}`` with no
    triggers, and this module's own docstring says a block with handlers but
    no triggers never fires. Silently enabling nothing is the moved handler
    retired a second time; failing loudly during the upgrade is not.
    """

    def test_migrating_to_a_target_without_defaults_raises(self, monkeypatch) -> None:
        monkeypatch.setitem(
            RELOCATED_HANDLERS,
            "auto_continue_stop",
            HandlerRelocation(pseudo_event="no_such_pseudo_event", config_key="moved"),
        )
        config = _config({"stop": {"auto_continue_stop": {"enabled": True}}})

        with pytest.raises(ValueError, match="no_such_pseudo_event"):
            migrate_relocated_handler_keys(config)

    def test_the_sweep_leaves_an_unknown_block_exactly_as_written(self) -> None:
        """``scaffold_pseudo_event_blocks`` walks blocks it has no defaults for.

        It must not raise for them, and must not invent an ``enabled`` key
        either -- there is nothing to fill it from.
        """
        config = _config({}, pseudo_events={"some_other_event": {"handlers": {}}})

        scaffolded = scaffold_pseudo_event_blocks(config)

        assert scaffolded["pseudo_events"]["some_other_event"] == {"handlers": {}}
