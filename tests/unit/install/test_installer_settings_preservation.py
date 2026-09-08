"""The bootstrap installer must not discard a client's settings deterministically.

Plan 00176 Q6 audited the four things that write `settings.json` and found only
one genuine conflict — and it is not a race. `create_settings_json` emits a
FRESH document from `_DAEMON_FORWARDER_HOOKS`, so running it against a project
whose settings have been merged discards the merge every time, with no
concurrency involved. The backup meant the file was recoverable, not that it
was carried forward.

`install.py` is the standalone bootstrap: it runs before any venv exists and
cannot import the daemon, so it cannot call the real merge. What it CAN do is
the property that makes the merge safe — start from the client's document and
edit the daemon-owned parts of it, rather than building a daemon document and
discarding the rest.

**The stated limit**: a client hook sharing an array with a daemon forwarder is
NOT preserved here, because telling one from the other needs the command
discriminator, and duplicating that into a file which already carries a
hand-kept copy of the wired set would double the drift surface. The upgrade
routes, which can import the daemon, do preserve it.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]


def _installer() -> Callable[..., None]:
    """`install.py` is a standalone bootstrap script, not an installed package."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from install import create_settings_json

    return create_settings_json


def _project(tmp_path: Path, existing: str | None) -> Path:
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    if existing is not None:
        (tmp_path / ".claude" / "settings.json").write_text(existing, encoding="utf-8")
    return tmp_path


def _written(project_root: Path) -> dict[str, Any]:
    return json.loads((project_root / ".claude" / "settings.json").read_text(encoding="utf-8"))


class TestClientKeysAreCarriedForward:
    def test_a_permissions_block_survives_a_reinstall(self, tmp_path: Path) -> None:
        """Two of the shipped top-level keys are security controls."""
        root = _project(tmp_path, json.dumps({"permissions": {"deny": ["Bash(rm:*)"]}}))
        _installer()(root)
        assert _written(root)["permissions"] == {"deny": ["Bash(rm:*)"]}

    def test_plans_directory_survives(self, tmp_path: Path) -> None:
        root = _project(tmp_path, json.dumps({"plansDirectory": "./docs/plans"}))
        _installer()(root)
        assert _written(root)["plansDirectory"] == "./docs/plans"

    def test_a_key_the_installer_has_never_heard_of_survives(self, tmp_path: Path) -> None:
        root = _project(tmp_path, json.dumps({"someFutureKey": {"deep": [1, 2]}}))
        _installer()(root)
        assert _written(root)["someFutureKey"] == {"deep": [1, 2]}

    def test_a_custom_status_line_is_not_overwritten(self, tmp_path: Path) -> None:
        root = _project(tmp_path, json.dumps({"statusLine": {"command": "./bin/mine"}}))
        _installer()(root)
        assert _written(root)["statusLine"]["command"] == "./bin/mine"

    def test_an_event_the_daemon_does_not_wire_survives(self, tmp_path: Path) -> None:
        existing = json.dumps({"hooks": {"SomeClientEvent": [{"hooks": [{"command": "./x.sh"}]}]}})
        root = _project(tmp_path, existing)
        _installer()(root)
        assert _written(root)["hooks"]["SomeClientEvent"] == [{"hooks": [{"command": "./x.sh"}]}]


class TestTheDaemonBlockIsStillRefreshed:
    def test_a_stale_forwarder_is_replaced(self, tmp_path: Path) -> None:
        """Preserving must not mean leaving a broken registration in place."""
        existing = json.dumps({"hooks": {"PreToolUse": [{"hooks": [{"command": "old"}]}]}})
        root = _project(tmp_path, existing)
        _installer()(root)
        commands = [
            inner["command"]
            for group in _written(root)["hooks"]["PreToolUse"]
            for inner in group["hooks"]
        ]
        assert "old" not in commands
        assert any(".claude/hooks/pre-tool-use" in command for command in commands)

    def test_every_wired_event_is_present(self, tmp_path: Path) -> None:
        root = _project(tmp_path, json.dumps({"permissions": {"deny": []}}))
        _installer()(root)
        assert "PreToolUse" in _written(root)["hooks"]

    def test_a_status_line_is_supplied_when_the_client_has_none(self, tmp_path: Path) -> None:
        root = _project(tmp_path, json.dumps({"permissions": {"deny": []}}))
        _installer()(root)
        assert ".claude/hooks/status-line" in _written(root)["statusLine"]["command"]


class TestNothingUsableMeansStartFresh:
    def test_an_unparseable_file_does_not_crash_the_install(self, tmp_path: Path) -> None:
        """The backup already holds it; the install still has to produce a file."""
        root = _project(tmp_path, "{ not json")
        _installer()(root)
        assert "PreToolUse" in _written(root)["hooks"]

    def test_a_document_that_is_not_an_object_is_ignored(self, tmp_path: Path) -> None:
        root = _project(tmp_path, "[1, 2, 3]")
        _installer()(root)
        assert "PreToolUse" in _written(root)["hooks"]

    def test_a_fresh_install_is_unaffected(self, tmp_path: Path) -> None:
        root = _project(tmp_path, None)
        _installer()(root)
        written = _written(root)
        assert "PreToolUse" in written["hooks"]
        assert "statusLine" in written

    def test_the_backup_still_holds_the_original(self, tmp_path: Path) -> None:
        root = _project(tmp_path, "{ not json")
        _installer()(root)
        backups = list((root / ".claude").glob("settings.json.bak*"))
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == "{ not json"
