"""The per-release Claude Code version record and its reviewer agent (Plan 00486).

`CLAUDE/development/claude-code-versions.yaml` maps each daemon release to the
Claude Code version it was built and tested against. These tests pin its shape
so the Phase 2 drift check can rely on it, and pin the reviewer agent's
read-only tool list and the RELEASING.md step that wires both together.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from claude_code_hooks_daemon.daemon.contract_status import compare_contract

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORD_PATH = REPO_ROOT / "CLAUDE" / "development" / "claude-code-versions.yaml"
META_PATH = REPO_ROOT / "contracts" / "claude-code-hooks" / "META.json"
AGENT_PATH = REPO_ROOT / ".claude" / "agents" / "claude-code-changelog-reviewer.md"
RELEASING_PATH = REPO_ROOT / "CLAUDE" / "development" / "RELEASING.md"

UNKNOWN = "unknown"
_RELEASE_KEY = re.compile(r"^v\d+\.\d+\.\d+$")
_CC_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@pytest.fixture(scope="module")
def record() -> dict[str, Any]:
    """Parsed record file."""
    data = yaml.safe_load(RECORD_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def releases(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The release map."""
    mapping = record["releases"]
    assert isinstance(mapping, dict)
    return mapping


class TestRecordShape:
    """Every entry is machine-readable and never guesses."""

    def test_record_is_not_empty(self, releases: dict[str, dict[str, Any]]) -> None:
        assert releases

    def test_keys_are_release_tags(self, releases: dict[str, dict[str, Any]]) -> None:
        for key in releases:
            assert _RELEASE_KEY.match(key), key

    def test_claude_code_version_is_a_version_or_unknown(
        self, releases: dict[str, dict[str, Any]]
    ) -> None:
        for key, entry in releases.items():
            value = entry["claude_code_version"]
            assert value == UNKNOWN or _CC_VERSION.match(value), key

    def test_review_date_is_iso_or_unknown(self, releases: dict[str, dict[str, Any]]) -> None:
        for key, entry in releases.items():
            value = entry["review_date"]
            assert value == UNKNOWN or _ISO_DATE.match(str(value)), key

    def test_review_report_exists_when_named(self, releases: dict[str, dict[str, Any]]) -> None:
        for key, entry in releases.items():
            value = entry["review_report"]
            if value != UNKNOWN:
                assert (REPO_ROOT / value).is_file(), f"{key}: {value}"

    def test_reviewed_entry_names_the_version_reviewed_through(
        self, releases: dict[str, dict[str, Any]]
    ) -> None:
        """The session drift advisory compares against `reviewed_through` (Plan 00486 Task 2.1)."""
        for key, entry in releases.items():
            if entry["review_date"] != UNKNOWN:
                assert _CC_VERSION.match(str(entry.get("reviewed_through", ""))), key

    def test_known_version_names_its_evidence(self, releases: dict[str, dict[str, Any]]) -> None:
        for key, entry in releases.items():
            if entry["claude_code_version"] != UNKNOWN:
                assert entry["evidence"], key


class TestAgreesWithContractMeta:
    """META.json's audited version is the record's newest known version."""

    def test_newest_known_version_matches_meta(self, releases: dict[str, dict[str, Any]]) -> None:
        # The existing reader, with a stub fetch so nothing touches the network.
        audited = compare_contract(META_PATH, lambda _url: b"").audited_version
        known = [e["claude_code_version"] for e in releases.values()]
        known = [v for v in known if v != UNKNOWN]
        newest = max(known, key=lambda v: tuple(int(p) for p in v.split(".")))
        assert newest == audited


class TestReviewerAgent:
    """The reviewer is read-only on the repository."""

    def test_agent_exists(self) -> None:
        assert AGENT_PATH.is_file()

    def test_tools_exclude_edit_and_bash(self) -> None:
        text = AGENT_PATH.read_text(encoding="utf-8")
        front = yaml.safe_load(text.split("---")[1])
        tools = {t.strip() for t in front["tools"].split(",")}
        assert front["name"] == "claude-code-changelog-reviewer"
        assert not tools & {"Edit", "Bash", "NotebookEdit"}
        assert {"Read", "Grep"} <= tools


class TestReleasingStep:
    """RELEASING.md wires the record and the reviewer into the pipeline."""

    def test_step_names_record_and_agent(self) -> None:
        text = RELEASING_PATH.read_text(encoding="utf-8")
        assert "claude-code-versions.yaml" in text
        assert "claude-code-changelog-reviewer" in text
