"""A manifest entry for a handler that has since gone is not recommended (Plan 00586 Task 1.1, A).

`check-config-migrations` reads every manifest between two versions, so an upgrade across
many releases met an `added` entry for a handler a later release retired, relocated or moved
to another event, and recommended adding a key the registry now rejects. A handler name the
audit does not know at all stays recommended: it may be a project or plugin handler.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from claude_code_hooks_daemon.constants import RETIRED_HANDLERS
from claude_code_hooks_daemon.install.config_migrations import generate_migration_advisory

_RETIRED = next(iter(sorted(RETIRED_HANDLERS)))


def _manifest(*keys: str) -> str:
    entries = "".join(
        f'    - key: {key}\n      description: "d"\n      recommended: true\n' for key in keys
    )
    return (
        'version: "3.1.0"\ndate: "2026-01-01"\nbreaking: false\n'
        f"config_changes:\n  added:\n{entries}  renamed: []\n  removed: []\n  changed: []\n"
    )


def _advise(tmp_path: Path, *keys: str) -> list[str]:
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "v3.1.0.yaml").write_text(_manifest(*keys))
    config = tmp_path / "hooks-daemon.yaml"
    config.write_text(yaml.safe_dump({"handlers": {}}))
    advisory = generate_migration_advisory("3.0.0", "3.1.0", config, manifests_dir=manifests)
    return [suggestion.key for suggestion in advisory.suggestions]


class TestAGoneHandlerIsNotRecommended:
    def test_a_retired_handler_is_not_recommended(self, tmp_path: Path) -> None:
        assert _advise(tmp_path, f"handlers.pre_tool_use.{_RETIRED}") == []

    def test_a_retired_handlers_option_is_not_recommended(self, tmp_path: Path) -> None:
        assert _advise(tmp_path, f"handlers.pre_tool_use.{_RETIRED}.options.x") == []

    def test_a_handler_registered_under_another_event_is_not_recommended(
        self, tmp_path: Path
    ) -> None:
        """`sed_blocker` is a pre_tool_use handler, so a session_start entry for it is a dead key."""
        assert _advise(tmp_path, "handlers.session_start.sed_blocker") == []


class TestWhatStaysRecommended:
    def test_a_registered_handler_is_still_recommended(self, tmp_path: Path) -> None:
        assert _advise(tmp_path, "handlers.pre_tool_use.sed_blocker") == [
            "handlers.pre_tool_use.sed_blocker"
        ]

    def test_an_unknown_handler_name_is_still_recommended(self, tmp_path: Path) -> None:
        """Not provably gone: it may be a project or plugin handler, so it is left to the reader."""
        assert _advise(tmp_path, "handlers.pre_tool_use.some_project_handler") == [
            "handlers.pre_tool_use.some_project_handler"
        ]

    def test_a_key_outside_the_handlers_tree_is_still_recommended(self, tmp_path: Path) -> None:
        assert _advise(tmp_path, "daemon.some_new_setting") == ["daemon.some_new_setting"]

    def test_a_placeholder_event_is_still_recommended(self, tmp_path: Path) -> None:
        assert _advise(tmp_path, "handlers.<event>.<handler>.scope") == [
            "handlers.<event>.<handler>.scope"
        ]
