"""Dependabot watches the actions and the Python lock (Plan 00572 Task 4.1).

The repository's default branch carries over a hundred known-vulnerable
dependency advisories and nothing proposes the upgrades. A grouped weekly
update per ecosystem keeps that to one pull request each instead of one per
package.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / ".github" / "dependabot.yml"


def _updates() -> dict[str, dict[str, object]]:
    document = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert document["version"] == 2
    return {str(u["package-ecosystem"]): u for u in document["updates"]}


def test_github_actions_and_python_lock_are_both_watched() -> None:
    updates = _updates()
    assert {"github-actions", "uv"} <= set(updates)


def test_the_python_entry_points_at_the_directory_holding_uv_lock() -> None:
    directory = str(_updates()["uv"]["directory"]).strip("/")
    assert (ROOT / directory / "uv.lock").is_file()


def test_every_entry_is_scheduled_and_grouped() -> None:
    for name, update in _updates().items():
        schedule = update["schedule"]
        assert isinstance(schedule, dict) and schedule.get("interval"), name
        groups = update.get("groups")
        assert isinstance(groups, dict) and groups, f"{name} has no group"
        for group in groups.values():
            assert group.get("patterns") == ["*"], name
