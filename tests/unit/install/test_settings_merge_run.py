"""The file-level settings merge: what it writes, and when it refuses to.

`merge_settings` is pure; this is the layer around it that reads, validates and
writes, and it is where Plan 00176's Q3 decision lives: escalate on genuine
conflict or validation failure ONLY, never as routine narration. A summary on
every upgrade is the settings.json version of a warning that fires every time,
which trains people to skip it.

The refusal shape matters as much as the trigger. When it escalates it changes
NOTHING, writes the proposed merge alongside, names both paths and returns a
non-zero status the caller carries to the end of its run — it never picks a
side, because an unattended run that guesses is how a customisation disappears
with nobody watching.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.install.settings_merge import (
    MergeStatus,
    run_settings_merge,
)
from claude_code_hooks_daemon.utils.hook_command_migration import canonical_hook_command
from claude_code_hooks_daemon.utils.hook_registration import (
    HOOK_EVENTS_IN_SETTINGS,
    build_hook_registration,
)

_EVENT = "PreToolUse"
_BASH_KEY = HOOK_EVENTS_IN_SETTINGS[_EVENT]
_CANONICAL = canonical_hook_command(_BASH_KEY)


def _shipped() -> dict[str, Any]:
    return {
        "hooks": {
            json_key: build_hook_registration(bash_key)
            for json_key, bash_key in HOOK_EVENTS_IN_SETTINGS.items()
        },
        "statusLine": {"type": "command", "command": "x", "refreshInterval": 1},
        "permissions": {"deny": ["Edit(//tmp/**)"]},
    }


@pytest.fixture
def paths(tmp_path: Path) -> dict[str, Path]:
    new_default = tmp_path / "new-default.json"
    new_default.write_text(json.dumps(_shipped()), encoding="utf-8")
    return {"client": tmp_path / "settings.json", "new_default": new_default, "root": tmp_path}


class TestAFreshInstall:
    def test_an_absent_client_file_gets_the_shipped_settings(self, paths: dict[str, Path]) -> None:
        outcome = run_settings_merge(paths["client"], paths["new_default"])
        assert outcome.status is MergeStatus.INSTALLED
        assert json.loads(paths["client"].read_text(encoding="utf-8")) == _shipped()


class TestNothingToSayIsSaidQuietly:
    def test_an_already_current_file_is_not_rewritten(self, paths: dict[str, Path]) -> None:
        """Rewriting it would churn mtime and invite a pointless backup."""
        paths["client"].write_text(json.dumps(_shipped()), encoding="utf-8")
        before = paths["client"].stat().st_mtime_ns
        outcome = run_settings_merge(paths["client"], paths["new_default"])
        assert outcome.status is MergeStatus.UNCHANGED
        assert paths["client"].stat().st_mtime_ns == before


class TestAMergeThatSucceeds:
    def test_a_client_customisation_survives_and_the_wiring_is_completed(
        self, paths: dict[str, Path]
    ) -> None:
        paths["client"].write_text(
            json.dumps({"permissions": {"deny": ["Bash(rm:*)"]}, "hooks": {}}), encoding="utf-8"
        )
        outcome = run_settings_merge(paths["client"], paths["new_default"])
        written = json.loads(paths["client"].read_text(encoding="utf-8"))
        assert outcome.status is MergeStatus.MERGED
        assert written["permissions"] == {"deny": ["Bash(rm:*)"]}
        assert set(HOOK_EVENTS_IN_SETTINGS) <= set(written["hooks"])

    def test_the_file_it_writes_is_valid_json_with_a_trailing_newline(
        self, paths: dict[str, Path]
    ) -> None:
        paths["client"].write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        run_settings_merge(paths["client"], paths["new_default"])
        assert paths["client"].read_text(encoding="utf-8").endswith("}\n")


class TestEscalationPreservesTheClientFile:
    def test_an_unparseable_client_file_is_never_overwritten(self, paths: dict[str, Path]) -> None:
        """We cannot merge what we cannot read, and guessing would destroy it."""
        paths["client"].write_text("{ not json at all", encoding="utf-8")
        outcome = run_settings_merge(paths["client"], paths["new_default"])
        assert outcome.status is MergeStatus.ESCALATED
        assert paths["client"].read_text(encoding="utf-8") == "{ not json at all"

    def test_the_proposed_merge_is_written_alongside(self, paths: dict[str, Path]) -> None:
        paths["client"].write_text("{ not json at all", encoding="utf-8")
        outcome = run_settings_merge(paths["client"], paths["new_default"])
        assert outcome.proposal_path is not None
        assert outcome.proposal_path.exists()
        assert json.loads(outcome.proposal_path.read_text(encoding="utf-8"))

    def test_both_paths_are_named_so_a_human_can_act(self, paths: dict[str, Path]) -> None:
        paths["client"].write_text("{ not json at all", encoding="utf-8")
        outcome = run_settings_merge(paths["client"], paths["new_default"])
        joined = " ".join(outcome.messages)
        assert str(paths["client"]) in joined
        assert outcome.proposal_path is not None
        assert str(outcome.proposal_path) in joined

    def test_a_client_document_that_is_not_an_object_escalates(
        self, paths: dict[str, Path]
    ) -> None:
        paths["client"].write_text("[1, 2, 3]", encoding="utf-8")
        outcome = run_settings_merge(paths["client"], paths["new_default"])
        assert outcome.status is MergeStatus.ESCALATED
        assert paths["client"].read_text(encoding="utf-8") == "[1, 2, 3]"


class TestTheBaselineIsUsedWhenItIsGivenAndNotGuessedWhenItIsNot:
    def test_an_old_default_upgrades_a_value_still_sitting_at_it(
        self, paths: dict[str, Path]
    ) -> None:
        old = _shipped()
        old["statusLine"]["refreshInterval"] = 1000
        old_path = paths["root"] / "old-default.json"
        old_path.write_text(json.dumps(old), encoding="utf-8")
        paths["client"].write_text(
            json.dumps({"statusLine": {"type": "command", "refreshInterval": 1000}}),
            encoding="utf-8",
        )
        run_settings_merge(paths["client"], paths["new_default"], old_path)
        written = json.loads(paths["client"].read_text(encoding="utf-8"))
        assert written["statusLine"]["refreshInterval"] == 1

    def test_without_one_the_same_value_is_left_alone(self, paths: dict[str, Path]) -> None:
        paths["client"].write_text(
            json.dumps({"statusLine": {"type": "command", "refreshInterval": 1000}}),
            encoding="utf-8",
        )
        run_settings_merge(paths["client"], paths["new_default"])
        written = json.loads(paths["client"].read_text(encoding="utf-8"))
        assert written["statusLine"]["refreshInterval"] == 1000

    def test_an_unreadable_baseline_is_treated_as_no_baseline_not_as_empty(
        self, paths: dict[str, Path]
    ) -> None:
        """An empty baseline would call every client value a deliberate override."""
        missing = paths["root"] / "nope.json"
        paths["client"].write_text(
            json.dumps({"statusLine": {"type": "command", "refreshInterval": 1000}}),
            encoding="utf-8",
        )
        outcome = run_settings_merge(paths["client"], paths["new_default"], missing)
        written = json.loads(paths["client"].read_text(encoding="utf-8"))
        assert written["statusLine"]["refreshInterval"] == 1000
        assert outcome.status is not MergeStatus.ESCALATED


class TestTheGateMustNotContradictTheMergesOwnRule:
    """Found by the end-to-end gate, which is the only place it could be.

    The merge PRESERVES a client hook sharing an event array with our
    forwarder — that is the headline ownership rule. `validate_hook_commands`
    counts every `type: command` hook in that array and calls more than one a
    duplicate registration, so using it as the write gate escalated the upgrade
    for precisely the clients whose customisations this exists to protect, on
    every run, forever. Preserved-but-never-written is worse than the overwrite.
    """

    def test_a_client_hook_beside_our_forwarder_does_not_escalate(
        self, paths: dict[str, Path]
    ) -> None:
        client = {
            "hooks": {
                _EVENT: [
                    {"hooks": [{"type": "command", "command": "./ci/client-only-gate.sh"}]},
                ]
            }
        }
        paths["client"].write_text(json.dumps(client), encoding="utf-8")
        outcome = run_settings_merge(paths["client"], paths["new_default"])
        assert outcome.status is not MergeStatus.ESCALATED, outcome.messages

    def test_and_the_client_hook_is_still_there_afterwards(self, paths: dict[str, Path]) -> None:
        client = {
            "hooks": {
                _EVENT: [
                    {"hooks": [{"type": "command", "command": "./ci/client-only-gate.sh"}]},
                ]
            }
        }
        paths["client"].write_text(json.dumps(client), encoding="utf-8")
        run_settings_merge(paths["client"], paths["new_default"])
        written = json.loads(paths["client"].read_text(encoding="utf-8"))
        commands = [
            inner["command"] for group in written["hooks"][_EVENT] for inner in group["hooks"]
        ]
        assert "./ci/client-only-gate.sh" in commands
        assert _CANONICAL in commands

    def test_a_genuinely_doubled_forwarder_still_escalates(self, paths: dict[str, Path]) -> None:
        """Loosening the gate must not blind it to a real double registration."""
        doubled = {"type": "command", "command": _CANONICAL}
        client = {"hooks": {_EVENT: [{"hooks": [doubled, dict(doubled)]}]}}
        paths["client"].write_text(json.dumps(client), encoding="utf-8")
        outcome = run_settings_merge(paths["client"], paths["new_default"])
        assert outcome.status is MergeStatus.ESCALATED
        assert any("forwarder" in message for message in outcome.messages)


class TestTheMergedResultIsValidatedBeforeItLands:
    def test_a_result_missing_a_wired_event_would_escalate(
        self, paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The gate is real: force a bad result and the client file survives."""
        import claude_code_hooks_daemon.install.settings_merge as module

        monkeypatch.setattr(module, "validate_settings_hooks", lambda _s: ["missing: PreToolUse"])
        original = json.dumps({"hooks": {}})
        paths["client"].write_text(original, encoding="utf-8")
        outcome = run_settings_merge(paths["client"], paths["new_default"])
        assert outcome.status is MergeStatus.ESCALATED
        assert paths["client"].read_text(encoding="utf-8") == original
        assert any("missing: PreToolUse" in message for message in outcome.messages)

    def test_it_says_which_top_level_keys_would_have_changed(
        self, paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Naming the paths alone leaves a human diffing two files by hand."""
        import claude_code_hooks_daemon.install.settings_merge as module

        monkeypatch.setattr(module, "validate_settings_hooks", lambda _s: ["nope"])
        paths["client"].write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        outcome = run_settings_merge(paths["client"], paths["new_default"])
        assert any("hooks" in message and "~" in message for message in outcome.messages)

    def test_an_unparseable_client_gets_no_fabricated_diff(self, paths: dict[str, Path]) -> None:
        """There is nothing to compare against, so claiming a diff would lie."""
        paths["client"].write_text("{ broken", encoding="utf-8")
        outcome = run_settings_merge(paths["client"], paths["new_default"])
        assert not any("would change" in message for message in outcome.messages)
