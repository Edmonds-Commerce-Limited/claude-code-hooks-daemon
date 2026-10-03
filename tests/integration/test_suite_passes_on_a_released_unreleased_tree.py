"""No test depends on ``CLAUDE/UPGRADES/UNRELEASED/`` holding content (N326).

Release prep empties ``UNRELEASED/`` into the versioned guide, leaving only the
README scaffolding. A test whose expectation needs a staged callout, manifest
or task passes for weeks, because between releases the directory is never
empty, and fails only at release time. Two instances were found that way.

This runs every test file that mentions the holding area against a copy of the
tracked tree whose ``UNRELEASED/`` is in its just-released state (README
scaffolding only), so such a dependency fails at the commit that adds it.
Files are found by scanning the test tree, so a new reader of the holding area
is covered without anyone remembering to list it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
TESTS_DIR: Final[Path] = REPO_ROOT / "tests"
UNRELEASED_DIR: Final[str] = "CLAUDE/UPGRADES/UNRELEASED"
SCAFFOLDING_NAME: Final[str] = "README.md"
FIXTURE_DIRNAME: Final[str] = "cyber-flag"
RUN_TIMEOUT_SECONDS: Final[int] = 900
FAILURE_TAIL_CHARS: Final[int] = 40000

#: Puts the copy's ``src`` first on the runner's own import path only. A
#: PYTHONPATH would leak into every upgrade the tests launch and shadow the
#: code they install; the interpreters they start resolve the package as usual.
_RUN_IN_COPY: Final[str] = (
    "import sys, pytest; sys.path.insert(0, 'src'); sys.exit(pytest.main(sys.argv[1:]))"
)

#: Spellings by which a test reaches the holding area.
_MENTIONS_HOLDING_AREA: Final[re.Pattern[str]] = re.compile(
    r"unreleased|PENDING_RELEASE_NOTES", re.IGNORECASE
)


def holding_area_readers(tests_dir: Path, *, exclude: Path) -> list[Path]:
    """Test files that mention the holding area, relative to ``tests_dir``'s parent."""
    readers: list[Path] = []
    for path in sorted(tests_dir.rglob("test_*.py")):
        if path == exclude or FIXTURE_DIRNAME in path.parts:
            continue
        if _MENTIONS_HOLDING_AREA.search(path.read_text(encoding="utf-8")):
            readers.append(path.relative_to(tests_dir.parent))
    return readers


def is_staged_content(relative: str) -> bool:
    """True for a tracked file inside ``UNRELEASED/`` that is not README scaffolding."""
    return relative.startswith(f"{UNRELEASED_DIR}/") and Path(relative).name != SCAFFOLDING_NAME


def copy_released_tree(destination: Path, source: Path) -> None:
    """Clone ``source`` (keeping its tags), overlay its working tree, empty ``UNRELEASED/``.

    The clone keeps the release tags the upgrade tests install from. The overlay
    carries uncommitted work, so a test being written is run before it is
    committed. The interpreter's venv is linked in where the QA resolver scans.
    """
    _git(source, "clone", "-q", str(source), str(destination))
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    for relative in filter(None, listing.split("\0")):
        origin = source / relative
        if is_staged_content(relative) or not origin.is_file() or origin.is_symlink():
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)
    for staged in (destination / UNRELEASED_DIR).rglob("*"):
        if staged.is_file() and staged.name != SCAFFOLDING_NAME:
            staged.unlink()
    _git(destination, "add", "-A")
    _git(
        destination,
        "-c",
        "user.name=n326",
        "-c",
        "user.email=n326@example.invalid",
        "-c",
        "core.hooksPath=/dev/null",
        "commit",
        "-q",
        "--no-verify",
        "--allow-empty",
        "-m",
        "released tree",
    )
    venv_link = destination / "untracked" / "venv-released-copy"
    venv_link.parent.mkdir(parents=True, exist_ok=True)
    venv_link.symlink_to(Path(sys.prefix))


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class TestTheCopyIsTheReleasedState:
    def test_staged_content_is_dropped_and_scaffolding_kept(self) -> None:
        assert is_staged_content(f"{UNRELEASED_DIR}/release-notes/001-x.md")
        assert is_staged_content(f"{UNRELEASED_DIR}/config-changes/v9.9.9.yaml")
        assert not is_staged_content(f"{UNRELEASED_DIR}/release-notes/README.md")
        assert not is_staged_content("CLAUDE/UPGRADES/v3/v3.60.0-to-v3.61.0/x.md")

    def test_readers_are_found_by_scanning(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "tests"
        (tests_dir / FIXTURE_DIRNAME).mkdir(parents=True)
        (tests_dir / "test_reads.py").write_text("p = 'CLAUDE/UPGRADES/UNRELEASED'\n")
        (tests_dir / "test_unrelated.py").write_text("x = 1\n")
        (tests_dir / FIXTURE_DIRNAME / "test_flagged.py").write_text("UNRELEASED\n")
        found = holding_area_readers(tests_dir, exclude=tests_dir / "test_self.py")
        assert found == [Path("tests/test_reads.py")]

    def test_there_are_readers_to_run(self) -> None:
        assert holding_area_readers(TESTS_DIR, exclude=Path(__file__).resolve())


@pytest.fixture(scope="module")
def released_tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The tracked tree with ``UNRELEASED/`` in its just-released state."""
    root = tmp_path_factory.mktemp("released")
    copy_released_tree(root, REPO_ROOT)
    return root


@pytest.mark.slow
def test_the_holding_area_readers_pass_with_nothing_staged(released_tree: Path) -> None:
    readers = holding_area_readers(TESTS_DIR, exclude=Path(__file__).resolve())
    staged = [p for p in (released_tree / UNRELEASED_DIR).rglob("*") if p.is_file()]
    assert staged
    assert all(p.name == SCAFFOLDING_NAME for p in staged), staged

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            _RUN_IN_COPY,
            "-q",
            "--color=no",
            "-p",
            "no:cacheprovider",
            *map(str, readers),
        ],
        cwd=released_tree,
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 0, (
        "A test needs content staged in CLAUDE/UPGRADES/UNRELEASED/ and would fail at "
        "release prep, when that directory is emptied. Give it its own fixture.\n"
        f"{result.stdout[-FAILURE_TAIL_CHARS:]}\n{result.stderr[-FAILURE_TAIL_CHARS:]}"
    )
