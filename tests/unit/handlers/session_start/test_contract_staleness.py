"""Plan 00271 Task 1.7 — contract-staleness SessionStart advisory.

Sibling of ``version_check``: when the installed Claude Code version exceeds
``contracts/claude-code-hooks/META.json``'s
``last_audited_claude_code_version``, advise running the refresh procedure so
the vendored contract cannot rot silently (Decision 3: advisory, never
auto-refresh — extraction from prose docs must be verified, not trusted).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.session_start.contract_staleness import (
    ContractStalenessHandler,
)


def _hook_input(source: str = "startup") -> dict[str, Any]:
    return {"hook_event_name": "SessionStart", "source": source}


@pytest.fixture
def handler(tmp_path: Path) -> ContractStalenessHandler:
    h = ContractStalenessHandler()
    h.meta_path = tmp_path / "META.json"
    h.meta_path.write_text(
        json.dumps(
            {
                "last_audited_claude_code_version": "2.1.246",
                "refresh_procedure": "docs/guides/HOOK-CONTRACT-REFRESH.md",
            }
        )
    )
    # The refresh procedure is maintainer work, so the default fixture is the
    # daemon repo itself (Plan 00322); client installs get their own class.
    h.self_install_reader = lambda: True
    # Isolate the drift check from the repository's real record and from the
    # real advisory cache: absent record, cache under tmp_path.
    h.versions_path = tmp_path / "absent" / "claude-code-versions.yaml"
    h.cache_path = tmp_path / "cache.json"
    return h


_RECORD = """\
releases:
  v3.59.0:
    claude_code_version: "2.1.252"
    review_date: unknown
    review_report: unknown
  v3.68.0:
    claude_code_version: unknown
    review_date: "2026-10-03"
    reviewed_through: "2.1.288"
  v3.60.0:
    claude_code_version: "2.1.260"
    review_date: "2026-09-01"
    reviewed_through: "2.1.270"
"""


class TestInit:
    def test_identity(self) -> None:
        h = ContractStalenessHandler()
        assert h.handler_id == HandlerID.CONTRACT_STALENESS
        assert h.priority == Priority.CONTRACT_STALENESS
        assert h.terminal is False

    def test_meta_path_defaults_to_vendored_contract(self) -> None:
        h = ContractStalenessHandler()
        assert h.meta_path.name == "META.json"
        assert h.meta_path.parent.name == "claude-code-hooks"


class TestMatches:
    def test_matches_new_session(self, handler: ContractStalenessHandler) -> None:
        assert handler.matches(_hook_input()) is True

    def test_skips_resume_session(self, handler: ContractStalenessHandler) -> None:
        assert handler.matches(_hook_input(source="resume")) is False

    def test_skips_other_events(self, handler: ContractStalenessHandler) -> None:
        assert handler.matches({"hook_event_name": "Stop"}) is False

    def test_skips_none_input(self, handler: ContractStalenessHandler) -> None:
        assert handler.matches(None) is False

    def test_respects_disabled_config(self, handler: ContractStalenessHandler) -> None:
        handler.configure({"enabled": False})
        assert handler.matches(_hook_input()) is False


class TestHandle:
    def test_silent_when_installed_matches_audited(self, handler: ContractStalenessHandler) -> None:
        handler.installed_version_reader = lambda: "2.1.246"
        result = handler.handle(_hook_input())
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_silent_when_installed_older(self, handler: ContractStalenessHandler) -> None:
        handler.installed_version_reader = lambda: "2.1.200"
        assert handler.handle(_hook_input()).context == []

    def test_advises_when_installed_newer(self, handler: ContractStalenessHandler) -> None:
        handler.installed_version_reader = lambda: "2.2.0"
        result = handler.handle(_hook_input())
        assert result.decision == Decision.ALLOW
        text = "\n".join(result.context)
        assert "2.1.246" in text
        assert "2.2.0" in text
        assert "HOOK-CONTRACT-REFRESH.md" in text
        assert "hooks-daemon contract-status" in text, "Plan 00327: the mechanised step is named"

    def test_silent_when_version_unreadable(self, handler: ContractStalenessHandler) -> None:
        handler.installed_version_reader = lambda: None
        assert handler.handle(_hook_input()).context == []

    def test_silent_when_meta_missing(self, tmp_path: Path) -> None:
        h = ContractStalenessHandler()
        h.meta_path = tmp_path / "absent" / "META.json"
        h.versions_path = tmp_path / "absent" / "claude-code-versions.yaml"
        h.installed_version_reader = lambda: "9.9.9"
        assert h.handle(_hook_input()).context == []

    def test_silent_when_meta_malformed(self, tmp_path: Path) -> None:
        h = ContractStalenessHandler()
        h.meta_path = tmp_path / "META.json"
        h.meta_path.write_text("not json")
        h.versions_path = tmp_path / "absent" / "claude-code-versions.yaml"
        h.installed_version_reader = lambda: "9.9.9"
        assert h.handle(_hook_input()).context == []

    def test_non_numeric_versions_stay_silent(self, handler: ContractStalenessHandler) -> None:
        handler.installed_version_reader = lambda: "dev-build"
        assert handler.handle(_hook_input()).context == []


class TestVendoredMetaIsCurrent:
    """Plan 00327 Task 3.1: the advisory is silent against the REAL META.json.

    Uses the vendored ``contracts/claude-code-hooks/META.json`` (no fixture)
    with the installed version pinned to the version that audit recorded, so
    a new session on that Claude Code sees nothing. A later Claude Code
    release re-arms the advisory by design; this pins that the refresh
    itself cleared it.
    """

    def test_new_session_on_the_audited_version_is_silent(self) -> None:
        h = ContractStalenessHandler()
        assert h.meta_path.is_file(), "vendored META.json must ship with the repository"
        meta = json.loads(h.meta_path.read_text(encoding="utf-8"))
        audited = meta["last_audited_claude_code_version"]
        assert audited == "2.1.272"
        h.installed_version_reader = lambda: audited
        h.self_install_reader = lambda: True
        assert h.matches(_hook_input()) is True
        result = h.handle(_hook_input())
        assert result.decision == Decision.ALLOW
        assert result.context == []


class TestClientInstallAdvisory:
    """Plan 00322: a client cannot perform the maintainer refresh procedure.

    In a client install the vendored contract lives under
    ``.claude/hooks-daemon/`` — a path the upgrade contract forbids editing
    and overwrites on the next upgrade. Pointing a client at the refresh
    procedure asks for a change that is both out of scope and self-erasing,
    so the client message must name actions a client can actually take.
    """

    @pytest.fixture
    def client_handler(self, handler: ContractStalenessHandler) -> ContractStalenessHandler:
        handler.self_install_reader = lambda: False
        handler.installed_version_reader = lambda: "2.2.0"
        return handler

    def test_still_reports_the_staleness(self, client_handler: ContractStalenessHandler) -> None:
        text = "\n".join(client_handler.handle(_hook_input()).context)
        assert "2.1.246" in text
        assert "2.2.0" in text

    def test_does_not_cite_the_maintainer_refresh_procedure(
        self, client_handler: ContractStalenessHandler
    ) -> None:
        text = "\n".join(client_handler.handle(_hook_input()).context)
        assert "HOOK-CONTRACT-REFRESH.md" not in text

    def test_names_the_actions_a_client_can_take(
        self, client_handler: ContractStalenessHandler
    ) -> None:
        text = "\n".join(client_handler.handle(_hook_input()).context)
        assert "skill=hooks-daemon, args=upgrade" in text
        assert "bug-report" in text

    def test_warns_against_editing_the_daemon_clone(
        self, client_handler: ContractStalenessHandler
    ) -> None:
        text = "\n".join(client_handler.handle(_hook_input()).context)
        assert ".claude/hooks-daemon/" in text

    @pytest.mark.parametrize(
        "failure",
        [
            RuntimeError("ProjectContext not initialized"),
            OSError("marker unreadable"),
        ],
        ids=["runtime-error", "os-error"],
    )
    def test_defaults_to_the_client_message_when_mode_is_unknown(
        self, handler: ContractStalenessHandler, failure: Exception
    ) -> None:
        """An unresolvable install mode must not leak maintainer guidance.

        Both arms the handler catches are pinned: the maintainer procedure
        edits daemon-owned paths a client install must never touch, so
        "cannot tell" has to resolve to the client answer either way.
        """

        def _explode() -> bool:
            raise failure

        handler.self_install_reader = _explode
        handler.installed_version_reader = lambda: "2.2.0"
        text = "\n".join(handler.handle(_hook_input()).context)
        assert "HOOK-CONTRACT-REFRESH.md" not in text
        assert "skill=hooks-daemon, args=upgrade" in text


class TestReviewDriftAdvisory:
    """Plan 00486 Task 2.1: running Claude Code newer than the last reviewed version.

    The second check of this handler. The record
    (``CLAUDE/development/claude-code-versions.yaml``) exists only in the
    daemon repository, so every path where it is absent, or where this is a
    client install, must be silent -- never an error, never an advisory.
    """

    @pytest.fixture
    def drift_handler(
        self, handler: ContractStalenessHandler, tmp_path: Path
    ) -> ContractStalenessHandler:
        handler.versions_path = tmp_path / "claude-code-versions.yaml"
        handler.versions_path.write_text(_RECORD, encoding="utf-8")
        # The contract is audited far ahead of every version these tests run,
        # so only the drift check can speak (the both-stale test overrides it).
        handler.meta_path.write_text(
            json.dumps({"last_audited_claude_code_version": "2.1.400"}), encoding="utf-8"
        )
        handler.installed_version_reader = lambda: "2.1.246"
        return handler

    def _text(self, h: ContractStalenessHandler) -> str:
        result = h.handle(_hook_input())
        assert result.decision == Decision.ALLOW
        return "\n".join(result.context)

    def test_advises_when_running_newer_than_newest_reviewed(
        self, drift_handler: ContractStalenessHandler
    ) -> None:
        drift_handler.installed_version_reader = lambda: "2.1.300"
        text = self._text(drift_handler)
        assert "2.1.300" in text
        assert "2.1.288" in text, "the newest reviewed_through across all entries"
        assert "claude-code-changelog-reviewer" in text
        assert "claude-code-versions.yaml" in text
        assert "RELEASING.md" in text

    def test_silent_when_running_the_reviewed_version(
        self, drift_handler: ContractStalenessHandler
    ) -> None:
        drift_handler.installed_version_reader = lambda: "2.1.288"
        assert self._text(drift_handler) == ""

    def test_silent_when_running_older_than_reviewed(
        self, drift_handler: ContractStalenessHandler
    ) -> None:
        drift_handler.installed_version_reader = lambda: "2.1.280"
        assert self._text(drift_handler) == ""

    def test_advises_once_per_unreviewed_version(
        self, drift_handler: ContractStalenessHandler
    ) -> None:
        drift_handler.installed_version_reader = lambda: "2.1.300"
        assert "claude-code-changelog-reviewer" in self._text(drift_handler)
        assert self._text(drift_handler) == "", "second session on the same version"
        drift_handler.installed_version_reader = lambda: "2.1.301"
        assert "2.1.301" in self._text(drift_handler), "a newer unreviewed version re-arms"

    def test_dedupe_survives_the_installed_version_cache_write(
        self, drift_handler: ContractStalenessHandler, tmp_path: Path
    ) -> None:
        """The marker shares the cache file with the probed version; neither clobbers the other."""
        cache_file = tmp_path / "cache.json"
        drift_handler.installed_version_reader = lambda: "2.1.300"
        self._text(drift_handler)
        assert json.loads(cache_file.read_text(encoding="utf-8"))["drift_advised_version"] == (
            "2.1.300"
        )
        assert drift_handler.write_cache({"installed_version": "2.1.300"}) is True
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
        assert cache["drift_advised_version"] == "2.1.300"
        assert cache["installed_version"] == "2.1.300"

    def test_corrupt_record_raises_rather_than_hiding(
        self, drift_handler: ContractStalenessHandler
    ) -> None:
        """An existing record that is not YAML is a repository defect, not silence."""
        drift_handler.versions_path.write_text("not: [valid", encoding="utf-8")
        drift_handler.installed_version_reader = lambda: "2.1.300"
        with pytest.raises(ValueError, match="not valid YAML"):
            drift_handler.handle(_hook_input())

    def test_record_that_is_a_directory_is_treated_as_absent(
        self, drift_handler: ContractStalenessHandler, tmp_path: Path
    ) -> None:
        drift_handler.versions_path = tmp_path
        drift_handler.installed_version_reader = lambda: "2.1.300"
        assert self._text(drift_handler) == ""

    def test_unwritable_marker_still_advises(
        self, drift_handler: ContractStalenessHandler, tmp_path: Path
    ) -> None:
        blocker = tmp_path / "file"
        blocker.write_text("x")
        drift_handler.cache_path = blocker / "cache.json"
        drift_handler.installed_version_reader = lambda: "2.1.300"
        assert "claude-code-changelog-reviewer" in self._text(drift_handler)

    def test_silent_when_record_absent(self, drift_handler: ContractStalenessHandler) -> None:
        """A client install has no record: no error, no advisory."""
        drift_handler.versions_path = drift_handler.versions_path.parent / "absent.yaml"
        drift_handler.installed_version_reader = lambda: "2.1.300"
        assert self._text(drift_handler) == ""

    def test_silent_in_client_install_even_if_record_present(
        self, drift_handler: ContractStalenessHandler
    ) -> None:
        drift_handler.self_install_reader = lambda: False
        drift_handler.installed_version_reader = lambda: "2.1.300"
        assert "claude-code-changelog-reviewer" not in self._text(drift_handler)

    def test_silent_when_install_mode_unresolvable(
        self, drift_handler: ContractStalenessHandler
    ) -> None:
        def _explode() -> bool:
            raise RuntimeError("ProjectContext not initialized")

        drift_handler.self_install_reader = _explode
        drift_handler.installed_version_reader = lambda: "2.1.300"
        assert "claude-code-changelog-reviewer" not in self._text(drift_handler)

    @pytest.mark.parametrize(
        "body",
        [
            "- a list\n- not a mapping\n",
            "releases: nope\n",
            "releases:\n  v3.1.0: just-a-string\n",
            "releases:\n  v3.1.0:\n    review_date: unknown\n",
            'releases:\n  v3.1.0:\n    review_date: "2026-10-03"\n    reviewed_through: unknown\n',
            'releases:\n  v3.1.0:\n    review_date: "2026-10-03"\n    reviewed_through: "dev"\n',
        ],
        ids=[
            "not-a-mapping",
            "releases-not-a-mapping",
            "entry-not-a-mapping",
            "nothing-reviewed",
            "reviewed-through-unknown",
            "reviewed-through-non-numeric",
        ],
    )
    def test_silent_when_record_has_no_usable_reviewed_version(
        self, drift_handler: ContractStalenessHandler, body: str
    ) -> None:
        drift_handler.versions_path.write_text(body, encoding="utf-8")
        drift_handler.installed_version_reader = lambda: "2.1.300"
        assert self._text(drift_handler) == ""

    def test_silent_when_installed_version_unreadable(
        self, drift_handler: ContractStalenessHandler
    ) -> None:
        drift_handler.installed_version_reader = lambda: None
        assert self._text(drift_handler) == ""

    def test_drift_advisory_does_not_depend_on_contract_meta(
        self, drift_handler: ContractStalenessHandler, tmp_path: Path
    ) -> None:
        """The two checks are independent: no META must not hide the drift advisory."""
        drift_handler.meta_path = tmp_path / "absent" / "META.json"
        drift_handler.installed_version_reader = lambda: "2.1.300"
        assert "claude-code-changelog-reviewer" in self._text(drift_handler)

    def test_both_advisories_when_both_stale(self, drift_handler: ContractStalenessHandler) -> None:
        drift_handler.installed_version_reader = lambda: "2.1.401"
        text = self._text(drift_handler)
        assert "HOOK-CONTRACT-REFRESH.md" in text
        assert "claude-code-changelog-reviewer" in text

    def test_real_record_is_silent_on_the_reviewed_version(self) -> None:
        """Against the repository's real record (Plan 00486 backfill: through 2.1.288)."""
        h = ContractStalenessHandler()
        assert h.versions_path.is_file(), "the record ships in the daemon repository"
        h.installed_version_reader = lambda: "2.1.288"
        h.self_install_reader = lambda: True
        assert "claude-code-changelog-reviewer" not in "\n".join(h.handle(_hook_input()).context)


class TestVersionParsing:
    def test_parses_claude_version_output(self) -> None:
        h = ContractStalenessHandler()
        assert h.parse_version_output("2.1.246 (Claude Code)") == "2.1.246"

    def test_rejects_garbage(self) -> None:
        h = ContractStalenessHandler()
        assert h.parse_version_output("no version here") is None


class TestContract:
    def test_guidance_and_acceptance_hooks(self) -> None:
        h = ContractStalenessHandler()
        assert h.get_claude_md() is None, "exempt in test_claude_md_guidance_coverage: fires once"
        tests = h.get_acceptance_tests()
        assert isinstance(tests, list)
        assert any("review" in t.title.lower() for t in tests)
