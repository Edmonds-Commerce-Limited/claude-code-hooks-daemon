"""The upgrader flags a still-enabled ``daemon_stats`` on a config predating v3.40.

Plan 00362 Task 1.8 (report section 8). Since v3.43.0 the "📦 vX → vY"
upgrade arrow is carried by ``upgrade_notifier``; ``daemon_stats`` renders
only the developer health line and defaults OFF (since v3.40.0). A client
whose config predates v3.40 typically holds
``handlers.status_line.daemon_stats.enabled: true`` from the old template,
and the release notes ask such projects to turn it off. The upgrader knows
both the version range and the config, so ``check-config-migrations`` must
say so — and ONLY to the projects that actually hold the override.

These tests run against the REAL shipped manifest tree, not a fixture, so
the assertion is about what a client will actually see.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import yaml

from claude_code_hooks_daemon.install.config_cli import run_check_config_migrations
from claude_code_hooks_daemon.install.config_migrations import (
    AdvisorySuggestion,
    generate_migration_advisory,
)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_MANIFESTS_DIR: Final[Path] = _REPO_ROOT / "CLAUDE" / "UPGRADES" / "config-changes"

_DAEMON_STATS_KEY: Final[str] = "handlers.status_line.daemon_stats.enabled"
_ARROW_HANDLER: Final[str] = "upgrade_notifier"

#: The report's exact scenario: a config from before v3.40 upgraded to v3.62.1.
_FROM: Final[str] = "3.41.0"
_TO: Final[str] = "3.62.1"


def _write_config(tmp_path: Path, config: dict[str, Any]) -> Path:
    path = tmp_path / "hooks-daemon.yaml"
    path.write_text(yaml.safe_dump(config))
    return path


def _daemon_stats_suggestions(
    tmp_path: Path, config: dict[str, Any], *, from_version: str = _FROM
) -> list[AdvisorySuggestion]:
    advisory = generate_migration_advisory(
        from_version, _TO, _write_config(tmp_path, config), manifests_dir=_MANIFESTS_DIR
    )
    return [s for s in advisory.suggestions if "daemon_stats" in s.key]


class TestStillEnabledDaemonStatsIsFlagged:
    def test_enabled_override_is_flagged_with_the_arrow_reason(self, tmp_path: Path) -> None:
        hits = _daemon_stats_suggestions(
            tmp_path,
            {"handlers": {"status_line": {"daemon_stats": {"enabled": True, "priority": 30}}}},
        )
        assert len(hits) == 1, hits
        hit = hits[0]
        assert hit.key == _DAEMON_STATS_KEY
        assert hit.recommended is True
        assert hit.recommended_value is False
        assert hit.current_value is True
        assert hit.migration_note is not None
        assert _ARROW_HANDLER in hit.migration_note, (
            "the advisory must carry the release-note reason: the upgrade arrow "
            "now lives in upgrade_notifier"
        )

    def test_flagged_from_before_v3_40_too(self, tmp_path: Path) -> None:
        hits = _daemon_stats_suggestions(
            tmp_path,
            {"handlers": {"status_line": {"daemon_stats": {"enabled": True}}}},
            from_version="3.39.0",
        )
        assert [h.key for h in hits] == [_DAEMON_STATS_KEY]


class TestOnlyTheOverrideIsFlagged:
    """A project already at the default gets no nudge — the advisory is targeted."""

    def test_explicitly_disabled_is_not_flagged(self, tmp_path: Path) -> None:
        hits = _daemon_stats_suggestions(
            tmp_path,
            {"handlers": {"status_line": {"daemon_stats": {"enabled": False}}}},
        )
        assert hits == []

    def test_absent_key_is_not_flagged(self, tmp_path: Path) -> None:
        hits = _daemon_stats_suggestions(tmp_path, {"handlers": {"status_line": {}}})
        assert hits == [], (
            "a config that never set daemon_stats already inherits the OFF default; "
            "telling it to turn daemon_stats off is noise"
        )

    def test_block_without_enabled_is_not_flagged(self, tmp_path: Path) -> None:
        hits = _daemon_stats_suggestions(
            tmp_path,
            {"handlers": {"status_line": {"daemon_stats": {"priority": 30}}}},
        )
        assert hits == []


class TestUpgradeSummaryText:
    """What scripts/upgrade.sh prints under 'Newly-available / recommended config options'."""

    def test_text_names_the_key_and_the_reason(self, tmp_path: Path) -> None:
        config = _write_config(
            tmp_path,
            {"handlers": {"status_line": {"daemon_stats": {"enabled": True}}}},
        )
        result = run_check_config_migrations(
            _FROM, _TO, config, output_format="text", manifests_dir=_MANIFESTS_DIR
        )
        text: str = result["text"]
        assert result["has_suggestions"] is True
        assert _DAEMON_STATS_KEY in text
        assert "Recommended: enabled = false  (your config: true)" in text
        assert _ARROW_HANDLER in text
