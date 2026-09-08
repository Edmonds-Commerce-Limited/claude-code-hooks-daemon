"""`--force` was when a settings.json was most likely to be worth keeping.

`create_settings_json` took its backup under `if settings_file.exists() and not
force`, so the one invocation that reinstalls **over an existing install** was
the one that overwrote the client's file with no copy and no warning. A fresh
install, where there is usually nothing to lose, got the backup instead.

The flag is gone rather than corrected: the daemon owns this file and rewrites
it on every invocation, so forcing never changed what was written — it only
ever skipped the backup. A parameter whose sole effect was to disable a safety
step is better removed than re-tuned, and its absence is asserted below so it
cannot come back quietly.

Same class as Plan 00176 Task 2.0, which found `upgrade_version.sh` copying
settings.json from two places and the more-travelled one being the less safe.
"""

from __future__ import annotations

import inspect
import json
import sys
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

_CLIENT = json.dumps({"statusLine": {"command": "mine"}, "permissions": {"allow": ["Bash"]}}) + "\n"


def _installer() -> Callable[..., None]:
    """`install.py` is a standalone bootstrap script, not an installed package."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from install import create_settings_json

    return create_settings_json


def _project(tmp_path: Path, *, existing: str | None) -> Path:
    (tmp_path / ".claude").mkdir()
    if existing is not None:
        (tmp_path / ".claude" / "settings.json").write_text(existing, encoding="utf-8")
    return tmp_path


def _backups(project_root: Path) -> list[Path]:
    return sorted((project_root / ".claude").glob("settings.json.bak*"))


class TestAnExistingFileIsAlwaysCopiedFirst:
    def test_a_backup_is_taken(self, tmp_path: Path) -> None:
        project_root = _project(tmp_path, existing=_CLIENT)
        _installer()(project_root)
        assert len(_backups(project_root)) == 1

    def test_the_backup_holds_what_was_there(self, tmp_path: Path) -> None:
        """A backup that does not contain the old bytes is not a backup."""
        project_root = _project(tmp_path, existing=_CLIENT)
        _installer()(project_root)
        assert _backups(project_root)[0].read_text(encoding="utf-8") == _CLIENT

    def test_the_new_file_still_lands(self, tmp_path: Path) -> None:
        project_root = _project(tmp_path, existing=_CLIENT)
        _installer()(project_root)
        written = json.loads((project_root / ".claude" / "settings.json").read_text())
        assert "hooks" in written
        assert written["statusLine"]["command"] != "mine"


class TestNothingToCopy:
    def test_a_fresh_install_leaves_no_backup_litter(self, tmp_path: Path) -> None:
        project_root = _project(tmp_path, existing=None)
        _installer()(project_root)
        assert _backups(project_root) == []


class TestASecondInstallDoesNotOverwriteTheFirstBackup:
    def test_both_copies_survive(self, tmp_path: Path) -> None:
        """The first backup is the one holding the client's ORIGINAL file."""
        project_root = _project(tmp_path, existing=_CLIENT)
        create_settings_json = _installer()
        create_settings_json(project_root)
        create_settings_json(project_root)
        assert len(_backups(project_root)) == 2
        contents = [path.read_text(encoding="utf-8") for path in _backups(project_root)]
        assert _CLIENT in contents

    def test_three_installs_inside_one_second_keep_three_copies(self, tmp_path: Path) -> None:
        """The timestamp is second-resolution, so it alone cannot separate them."""
        project_root = _project(tmp_path, existing=_CLIENT)
        create_settings_json = _installer()
        for _ in range(3):
            create_settings_json(project_root)
        assert len(_backups(project_root)) == 3
        assert _CLIENT in [path.read_text(encoding="utf-8") for path in _backups(project_root)]


class TestTheFlagCannotComeBack:
    def test_create_settings_json_takes_no_force_parameter(self) -> None:
        """Its only effect was to skip the backup, so it must stay gone."""
        assert "force" not in inspect.signature(_installer()).parameters
