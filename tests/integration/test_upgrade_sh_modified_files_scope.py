"""`upgrade.sh`'s `modified_files` names only what the upgrade itself changed (N588).

Field report (fedora-desktop, v3.73.0): `modified_files` was filled from
`git status --porcelain` over the whole project, so 33 uncommitted files left
by another agent were listed beside the 4 the upgrade wrote. That client's
bash-limits gate exempts every path in `modified_files` as daemon-owned, so
pasting the block as instructed would have silently exempted the 33.

The script now snapshots the dirty set (with a content hash of each dirty
path) before the deploy and lists only paths that are new to the dirty set or
whose content changed. The functions are lifted verbatim out of the REAL
script, because `upgrade.sh` is fetched standalone and cannot source a library
(see test_upgrade_sh_tmp_self_contained.py); a restated copy here would keep
passing after the script changed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_UPGRADE_SH: Final[Path] = _REPO_ROOT / "scripts" / "upgrade.sh"
_BASH: Final[str] = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS: Final[int] = 60

_FUNCTIONS: Final[tuple[str, ...]] = (
    "_dirty_paths",
    "_dirty_path_record",
    "_dirty_path_states",
    "_upgrade_changed_paths",
)
_SNAPSHOT_CALL: Final[str] = '_PRE_UPGRADE_DIRTY="$(_dirty_path_states "$PROJECT_ROOT")"'
_FIRST_DEPLOY_STEP: Final[str] = "# Step 3: Determine daemon directory and mode"


def _source() -> str:
    return _UPGRADE_SH.read_text(encoding="utf-8")


def _function(name: str) -> str:
    source = _source()
    start = source.index(f"{name}() {{")
    return source[start : source.index("\n}\n", start) + len("\n}\n")]


def _git(project: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(project), *args],
        check=True,
        capture_output=True,
        timeout=_TIMEOUT_SECONDS,
    )


def _run(project: Path, body: str) -> subprocess.CompletedProcess[str]:
    script = "\n".join(
        ["set -euo pipefail", *(_function(name) for name in _FUNCTIONS), f'P="{project}"', body]
    )
    return subprocess.run(
        [_BASH, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "client project"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    for name in (
        "unrelated edit.txt",
        "unrelated gone.txt",
        "unrelated old.txt",
        "both edit.txt",
        ".claude/daemon owned.md",
        ".claude/removed.md",
        ".claude/moved.md",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"original {name}\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def _make_unrelated_mess(root: Path) -> None:
    """Another agent's uncommitted work, present before the upgrade starts."""
    (root / "unrelated edit.txt").write_text("someone else's edit\n", encoding="utf-8")
    (root / "unrelated gone.txt").unlink()
    _git(root, "mv", "unrelated old.txt", "unrelated new.txt")
    (root / "notes dir").mkdir()
    (root / "notes dir" / "scratch file.txt").write_text("x\n", encoding="utf-8")
    (root / "unrelated link").symlink_to("unrelated edit.txt")
    (root / "both edit.txt").write_text("someone else's edit\n", encoding="utf-8")


def _do_upgrade_writes(root: Path) -> None:
    """What the deploy itself writes."""
    (root / ".claude" / "daemon owned.md").write_text("new version\n", encoding="utf-8")
    (root / ".claude" / "brand new.md").write_text("new\n", encoding="utf-8")
    (root / ".claude" / "removed.md").unlink()
    _git(root, "mv", ".claude/moved.md", ".claude/moved here.md")
    (root / ".claude" / "new link").symlink_to("daemon owned.md")
    (root / "both edit.txt").write_text("someone else's edit\nplus the upgrade's\n", "utf-8")


def _snapshot(root: Path) -> str:
    result = _run(root, '_dirty_path_states "$P"\n')
    assert result.returncode == 0, result.stderr
    return result.stdout


def _changed_since(root: Path, snapshot: str) -> set[str]:
    snapshot_file = root.parent / "snapshot.txt"
    snapshot_file.write_text(snapshot, encoding="utf-8")
    result = _run(
        root,
        f'_before="$(cat "{snapshot_file}")"\n_upgrade_changed_paths "$P" "$_before"\n',
    )
    assert result.returncode == 0, result.stderr
    return {path for path in result.stdout.rstrip("\n").split(",") if path}


class TestOnlyTheUpgradesOwnChangesAreListed:
    def test_unrelated_dirty_files_are_not_listed(self, project: Path) -> None:
        _make_unrelated_mess(project)
        snapshot = _snapshot(project)
        _do_upgrade_writes(project)

        changed = _changed_since(project, snapshot)

        for unrelated in (
            "unrelated edit.txt",
            "unrelated gone.txt",
            "unrelated old.txt",
            "unrelated new.txt",
            "notes dir/scratch file.txt",
            "unrelated link",
        ):
            assert unrelated not in changed, (
                f"{unrelated!r} was already uncommitted before the upgrade; listing it "
                "lets a client gate exempt it as daemon-owned"
            )

    def test_files_the_upgrade_wrote_are_listed(self, project: Path) -> None:
        _make_unrelated_mess(project)
        snapshot = _snapshot(project)
        _do_upgrade_writes(project)

        changed = _changed_since(project, snapshot)

        assert {
            ".claude/daemon owned.md",
            ".claude/brand new.md",
            ".claude/removed.md",
            ".claude/moved.md",
            ".claude/moved here.md",
            ".claude/new link",
            "both edit.txt",
        } <= changed, changed

    def test_nothing_listed_when_the_upgrade_wrote_nothing(self, project: Path) -> None:
        _make_unrelated_mess(project)
        snapshot = _snapshot(project)

        assert _changed_since(project, snapshot) == set()

    def test_everything_listed_on_a_tree_that_was_clean(self, project: Path) -> None:
        snapshot = _snapshot(project)
        _do_upgrade_writes(project)

        assert _changed_since(project, snapshot) == {
            ".claude/daemon owned.md",
            ".claude/brand new.md",
            ".claude/removed.md",
            ".claude/moved.md",
            ".claude/moved here.md",
            ".claude/new link",
            "both edit.txt",
        }


class TestTheScriptWiring:
    def test_snapshot_is_taken_before_the_first_deploy_step(self) -> None:
        source = _source()
        assert source.index(_SNAPSHOT_CALL) < source.index(_FIRST_DEPLOY_STEP), (
            "the dirty-set snapshot must precede Step 3, which can clone the daemon "
            "into the project and so is the first step that writes there"
        )

    def test_metadata_is_built_from_the_snapshot_not_the_whole_tree(self) -> None:
        source = _source()
        emit = source[
            source.index("# modified_files:") : source.index("_find_new_config_backup() {")
        ]
        assert "_upgrade_changed_paths" in emit
        assert "git status --porcelain" not in emit
