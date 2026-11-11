"""The shipped JSON Schemas for the daemon's machine-read ``--json`` output (Plan 00601).

Each schema is a JSON Schema 2020-12 document with a versioned ``$id``, shipped
inside the package. The documents they describe carry ``schema_version``; a
consumer pins the major and refuses an unknown one. These tests validate output
built by the daemon's own producers against the schemas.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from jsonschema import Draft202012Validator

from claude_code_hooks_daemon.core import state_schemas
from claude_code_hooks_daemon.core.session_mode_log import (
    ModeLabel,
    ModeTransition,
    TransitionAction,
)
from claude_code_hooks_daemon.daemon.session_mode_ipc import _entry
from claude_code_hooks_daemon.utils.session_modes import (
    ModeSource,
    SessionMode,
    SessionModeEntry,
)

_REPO = Path(__file__).resolve().parents[3]

_ALL = (
    state_schemas.SCHEMA_MODE_HISTORY,
    state_schemas.SCHEMA_SESSION_STATE,
    state_schemas.SCHEMA_SESSION_STATE_WATCH,
)


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(
        state_schemas.load_schema(name),
        registry=state_schemas.schema_registry(),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def _mode_history_document() -> dict[str, Any]:
    """A document built from the producers' own record shapes."""
    entry = SessionModeEntry(
        mode=SessionMode.FOCUS,
        session_id="abc-123",
        entered_at=1000.0,
        expires_at=2000.0,
        source=ModeSource.HUMAN,
        detail="fix the parser",
    )
    transition = ModeTransition(
        at=1000.0,
        session_id="abc-123",
        label=ModeLabel.FOCUS,
        action=TransitionAction.ENTER,
        evidence="a prompt the human typed",
        detail="fix the parser",
    )
    return {
        "schema_version": state_schemas.SCHEMA_VERSION,
        "sessions": {"abc-123": [_entry(entry)]},
        "transitions": [transition.to_record()],
    }


def _session_state_document() -> dict[str, Any]:
    window = {"used_percentage": 97.5, "resets_at": 1_800_000_000, "observed_at": 1_799_990_000.5}
    return {
        "schema_version": state_schemas.SCHEMA_VERSION,
        "session_id": "abc-123",
        "observed_at": 1_799_990_001.0,
        "modes": _mode_history_document()["sessions"]["abc-123"],
        "last_turn_edge": {
            "kind": "stop_failure",
            "at": 1_799_990_000.0,
            "error": "rate_limit",
            "resolved_at": None,
        },
        "usage": {"five_hour": window, "seven_day": None, "observed_at": 1_799_990_000.5},
        "limit_reset": {"window": "five_hour", "resets_at": 1_800_000_000},
        "usage_pause": None,
    }


class TestShippedSchemas:
    @pytest.mark.parametrize("name", _ALL)
    def test_is_a_valid_2020_12_schema(self, name: str) -> None:
        schema = state_schemas.load_schema(name)
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"

    @pytest.mark.parametrize("name", _ALL)
    def test_id_is_versioned_and_names_the_schema(self, name: str) -> None:
        schema_id = state_schemas.load_schema(name)["$id"]
        assert schema_id.endswith(f"/{name}/{state_schemas.SCHEMA_VERSION}.json")

    @pytest.mark.parametrize("name", _ALL)
    def test_requires_schema_version_pinned_to_the_major(self, name: str) -> None:
        schema = state_schemas.load_schema(name)
        assert "schema_version" in schema["required"]
        pattern = schema["properties"]["schema_version"]["pattern"]
        assert pattern == rf"^{state_schemas.SCHEMA_MAJOR}\.\d+\.\d+$"

    def test_schemas_are_declared_as_package_data(self) -> None:
        pyproject = tomllib.loads((_REPO / "pyproject.toml").read_text(encoding="utf-8"))
        data = pyproject["tool"]["setuptools"]["package-data"]["claude_code_hooks_daemon"]
        assert "schemas/*.json" in data
        directory = Path(state_schemas.__file__).resolve().parents[1] / "schemas"
        assert {p.name for p in directory.glob("*.json")} == {f"{n}.json" for n in _ALL}

    def test_unknown_schema_name_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unknown schema"):
            state_schemas.load_schema("nope")


class TestModeHistorySchema:
    def test_real_producer_output_validates(self) -> None:
        _validator(state_schemas.SCHEMA_MODE_HISTORY).validate(_mode_history_document())

    def test_empty_history_validates(self) -> None:
        document = {"schema_version": "1.0.0", "sessions": {}, "transitions": []}
        _validator(state_schemas.SCHEMA_MODE_HISTORY).validate(document)

    def test_unknown_major_is_refused(self) -> None:
        document = {**_mode_history_document(), "schema_version": "2.0.0"}
        with pytest.raises(jsonschema.ValidationError):
            _validator(state_schemas.SCHEMA_MODE_HISTORY).validate(document)

    def test_missing_schema_version_is_refused(self) -> None:
        document = _mode_history_document()
        del document["schema_version"]
        with pytest.raises(jsonschema.ValidationError):
            _validator(state_schemas.SCHEMA_MODE_HISTORY).validate(document)

    def test_a_later_minor_with_extra_fields_still_validates(self) -> None:
        document = {**_mode_history_document(), "schema_version": "1.4.0", "future": 1}
        _validator(state_schemas.SCHEMA_MODE_HISTORY).validate(document)

    def test_malformed_transition_is_refused(self) -> None:
        document = _mode_history_document()
        del document["transitions"][0]["evidence"]
        with pytest.raises(jsonschema.ValidationError):
            _validator(state_schemas.SCHEMA_MODE_HISTORY).validate(document)


class TestSessionStateSchema:
    def test_full_document_validates(self) -> None:
        _validator(state_schemas.SCHEMA_SESSION_STATE).validate(_session_state_document())

    def test_unknown_session_validates_with_nulls(self) -> None:
        document = {
            "schema_version": "1.0.0",
            "session_id": "never-seen",
            "observed_at": 1.0,
            "modes": [],
            "last_turn_edge": None,
            "usage": {"five_hour": None, "seven_day": None, "observed_at": None},
            "limit_reset": None,
            "usage_pause": None,
        }
        _validator(state_schemas.SCHEMA_SESSION_STATE).validate(document)

    def test_usage_pause_validates(self) -> None:
        document = _session_state_document()
        document["usage_pause"] = {
            "paused_at": 100.0,
            "resume_at": 200.0,
            "window": "seven_day",
            "used_percentage": 91.0,
            "ceiling": 90.0,
            "reason": "ceiling reached",
        }
        _validator(state_schemas.SCHEMA_SESSION_STATE).validate(document)

    @pytest.mark.parametrize("kind", ["start", "stop", "stop_failure"])
    def test_turn_edge_kinds(self, kind: str) -> None:
        document = _session_state_document()
        document["last_turn_edge"] = {"kind": kind, "at": 5.0}
        _validator(state_schemas.SCHEMA_SESSION_STATE).validate(document)

    def test_unknown_turn_edge_kind_is_refused(self) -> None:
        document = _session_state_document()
        document["last_turn_edge"] = {"kind": "teleport", "at": 5.0}
        with pytest.raises(jsonschema.ValidationError):
            _validator(state_schemas.SCHEMA_SESSION_STATE).validate(document)

    def test_unknown_usage_window_is_refused(self) -> None:
        document = _session_state_document()
        document["limit_reset"] = {"window": "hourly", "resets_at": 1}
        with pytest.raises(jsonschema.ValidationError):
            _validator(state_schemas.SCHEMA_SESSION_STATE).validate(document)

    def test_unknown_major_is_refused(self) -> None:
        document = {**_session_state_document(), "schema_version": "2.0.0"}
        with pytest.raises(jsonschema.ValidationError):
            _validator(state_schemas.SCHEMA_SESSION_STATE).validate(document)


class TestWatchLineSchema:
    def test_line_validates_and_round_trips_as_one_json_line(self) -> None:
        line = json.dumps(
            {
                "schema_version": state_schemas.SCHEMA_VERSION,
                "changed": ["last_turn_edge", "usage"],
                "state": _session_state_document(),
            }
        )
        assert "\n" not in line
        _validator(state_schemas.SCHEMA_SESSION_STATE_WATCH).validate(json.loads(line))

    def test_embedded_state_is_checked_against_the_session_state_schema(self) -> None:
        state = _session_state_document()
        del state["session_id"]
        document = {
            "schema_version": state_schemas.SCHEMA_VERSION,
            "changed": ["modes"],
            "state": state,
        }
        with pytest.raises(jsonschema.ValidationError):
            _validator(state_schemas.SCHEMA_SESSION_STATE_WATCH).validate(document)
