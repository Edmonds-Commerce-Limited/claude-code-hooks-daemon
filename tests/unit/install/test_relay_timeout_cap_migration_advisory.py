"""The upgrade advisory reports a relay timeout over the new cap before it bites.

Plan 00466 round 3: ``daemon.transport.timeout_seconds`` is now capped at
``Timeout.RELAY_TIMEOUT_CAP``, so the relay's wait plus its hand-off ends
before Claude Code cancels the hook. A config main accepted may hold more.
The daemon starts with the cap and warns, but the upgrade is where a client
can fix the config before the warning ever fires, so ``check-config-
migrations`` names the key, the cap and the value to set.

These run against the REAL manifest tree, UNRELEASED staging included, so
the assertion is about what a client upgrading to this release will see.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import pytest
import yaml

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.install.config_cli import run_check_config_migrations
from claude_code_hooks_daemon.install.config_migrations import (
    AdvisorySuggestion,
    generate_migration_advisory,
    load_manifests_between,
)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_MANIFESTS_DIR: Final[Path] = _REPO_ROOT / "CLAUDE" / "UPGRADES" / "config-changes"

_KEY: Final[str] = "daemon.transport.timeout_seconds"
_FROM: Final[str] = "3.66.0"
_TO: Final[str] = "3.68.0"


def _config(timeout: object | None) -> dict[str, Any]:
    transport: dict[str, Any] = {"relay_enabled": True}
    if timeout is not None:
        transport["timeout_seconds"] = timeout
    return {"daemon": {"transport": transport}}


def _write_config(tmp_path: Path, config: dict[str, Any]) -> Path:
    path = tmp_path / "hooks-daemon.yaml"
    path.write_text(yaml.safe_dump(config))
    return path


def _cap_suggestions(tmp_path: Path, timeout: object | None) -> list[AdvisorySuggestion]:
    advisory = generate_migration_advisory(
        _FROM,
        _TO,
        _write_config(tmp_path, _config(timeout)),
        manifests_dir=_MANIFESTS_DIR,
        include_unreleased=True,
    )
    return [s for s in advisory.suggestions if s.key == _KEY]


class TestTheManifestCarriesTheCap:
    def test_the_maximum_is_the_cap_the_daemon_enforces(self) -> None:
        entries = [
            entry
            for manifest in load_manifests_between(
                _FROM, _TO, manifests_dir=_MANIFESTS_DIR, include_unreleased=True
            )
            for entry in manifest.config_changes.changed
            if entry.key == _KEY
        ]
        assert [entry.maximum for entry in entries] == [Timeout.RELAY_TIMEOUT_CAP]


class TestAValueOverTheCapIsFlagged:
    def test_it_names_the_cap_and_the_value(self, tmp_path: Path) -> None:
        hits = _cap_suggestions(tmp_path, Timeout.RELAY_TIMEOUT_CAP + 1)
        assert len(hits) == 1, hits
        hit = hits[0]
        assert hit.recommended is True
        assert hit.recommended_value == Timeout.RELAY_TIMEOUT_CAP
        assert hit.current_value == Timeout.RELAY_TIMEOUT_CAP + 1
        assert hit.migration_note is not None
        assert str(Timeout.RELAY_TIMEOUT_CAP) in hit.migration_note

    def test_the_upgrade_text_says_what_to_set(self, tmp_path: Path) -> None:
        over = Timeout.RELAY_TIMEOUT_CAP + 15
        result = run_check_config_migrations(
            _FROM,
            _TO,
            _write_config(tmp_path, _config(over)),
            output_format="text",
            manifests_dir=_MANIFESTS_DIR,
            include_unreleased=True,
        )
        text: str = result["text"]
        assert _KEY in text
        assert (
            f"Recommended: timeout_seconds = {Timeout.RELAY_TIMEOUT_CAP}  (your config: {over})"
            in text
        ), text


class TestAValueWithinTheCapIsNotFlagged:
    @pytest.mark.parametrize("timeout", [None, 1, 30, Timeout.RELAY_TIMEOUT_CAP])
    def test_it_is_left_alone(self, tmp_path: Path, timeout: int | None) -> None:
        assert _cap_suggestions(tmp_path, timeout) == []

    @pytest.mark.parametrize("timeout", ["sixty", True, [60]])
    def test_a_value_that_is_not_a_number_is_not_compared(
        self, tmp_path: Path, timeout: object
    ) -> None:
        """Config validation reports such a value; the cap has nothing to say."""
        assert _cap_suggestions(tmp_path, timeout) == []
