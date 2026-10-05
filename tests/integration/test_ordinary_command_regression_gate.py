"""Ordinary commands stay ALLOWED by every PreToolUse handler (Plan 00483 R2).

The guards around protected files, containment and sequencing grew for five
weeks by closing one shape at a time, and each closed shape denied an ordinary
command somewhere else (``ls */*/*``, ``for d in dir/*``, ``grep -r`` after a
``cd``). The guard-effort review found no test that held the other direction:
the old false-positive corpora ran against no filesystem, so a verdict that
depends on what is on disk was never exercised.

This gate does. ``tests/fixtures/ordinary_command_corpus.yaml`` lists commands a
careless-but-well-meaning agent types in normal work, and every row is judged by
the full discovered handler chain over a fixture tree that holds protected files
in their usual places: a hidden ignored one at the root, one under ``.claude/``,
a visible ignored one three levels down, and one inside the ignored scratch
directory. Any row that was ALLOWED and now is not fails the change.

A row the current guards wrongly deny is recorded ``xfail`` with the ledger id
or inventory label that explains it. The test is ``xfail(strict=True)``, so the
change that fixes the false positive fails until the marker is removed: the fix
is proved by the row, and the marker never outlives it.

Protected names are assembled from parts. Spelling one in a source file would
make the guard under test deny the authoring of this very file.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = REPO_ROOT / "tests" / "fixtures" / "ordinary_command_corpus.yaml"

#: Fewer rows than this means the corpus lost its breadth, not that it is clean.
MINIMUM_CORPUS_ROWS = 300

_TOOL_BASH = "Bash"
_PATH_FIELD_BY_TOOL = {
    "Read": "file_path",
    "Edit": "file_path",
    "Write": "file_path",
    "Grep": "path",
}

# Protected names, assembled so this file never spells one.
_VAULT_FILE = "vault_" + "passwords.yml"
_KEY_FILE = "id_" + "rsa"
_WORD_LIST = "block-words." + "secret"
_VAULT_PASS = ".vault-" + "pass"

#: (relative path, git-ignored) for every file of the fixture tree.
_FIXTURE_FILES: tuple[tuple[str, bool], ...] = (
    ("README.md", False),
    ("SECURITY.md", False),
    (".gitignore", False),
    ("package.json", False),
    ("src/app.py", False),
    ("src/notes.md", False),
    ("src/util/helpers.py", False),
    ("tests/unit/test_app.py", False),
    ("docs/guide.md", False),
    ("docs/secrets.md", False),
    ("scripts/run.sh", False),
    ("repos/one/x.txt", False),
    ("repos/two/y.txt", False),
    ("worktrees/w1/z.txt", False),
    ("deep/er/est/file.txt", False),
    ("group_vars/all/main.yml", False),
    (".claude/hooks-daemon.yaml", False),
    # Protected files in their usual places, every one of them gitignored.
    (f".claude/{_WORD_LIST}", True),
    (_VAULT_PASS, True),
    (f"group_vars/all/{_VAULT_FILE}", True),
    (f"untracked/{_KEY_FILE}", True),
    ("untracked/repos/one/y.txt", True),
    ("untracked/daemon.log", True),
)

_FIXTURE_GITIGNORE = "\n".join(
    ["untracked/", f".claude/{_WORD_LIST}", _VAULT_PASS, f"group_vars/all/{_VAULT_FILE}", ""]
)


@dataclass(frozen=True)
class Row:
    """One corpus row."""

    id: str
    command: str
    cwd: str
    tool: str
    xfail: str | None


def load_rows(path: Path = CORPUS_PATH) -> list[Row]:
    """Every row of the corpus, validated: a malformed row fails the whole gate."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    rows: list[Row] = []
    for entry in raw["rows"]:
        unknown = set(entry) - {"id", "command", "cwd", "tool", "xfail"}
        assert not unknown, f"row {entry.get('id')!r} has unknown keys {sorted(unknown)}"
        rows.append(
            Row(
                id=entry["id"],
                command=str(entry["command"]),
                cwd=str(entry.get("cwd", "")),
                tool=str(entry.get("tool", _TOOL_BASH)),
                xfail=entry.get("xfail"),
            )
        )
    return rows


ROWS = load_rows()


def _params() -> list[Any]:
    params: list[Any] = []
    for row in ROWS:
        marks = [pytest.mark.xfail(strict=True, reason=row.xfail)] if row.xfail is not None else []
        params.append(pytest.param(row, id=row.id, marks=marks))
    return params


def build_fixture_tree(root: Path) -> None:
    """Create the fixture project at ``root``: files, ignore rules and a git index."""
    for relative, _ignored in _FIXTURE_FILES:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x = 1\n", encoding="utf-8")
    # A comments-only word list is inert: its first line must not become a blocked
    # term that the commit gate then finds in every commit message.
    (root / ".claude" / _WORD_LIST).write_text("# no terms\n", encoding="utf-8")
    (root / "package.json").write_text("{}\n", encoding="utf-8")
    (root / ".gitignore").write_text(_FIXTURE_GITIGNORE, encoding="utf-8")
    (root / ".claude" / "hooks-daemon.yaml").write_text('version: "1.0"\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)


def _initialise_project_context(root: Path) -> None:
    """Point ProjectContext at ``root`` without asking git or GitHub about it."""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=f"{root}\n"),
            MagicMock(returncode=0, stdout="git@github.com:user/test-repo.git\n"),
            MagicMock(returncode=0, stdout=f"{root}\n"),
        ]
        ProjectContext.initialize(root / ".claude" / "hooks-daemon.yaml")


@pytest.fixture(scope="module")
def fixture_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The fixture project, built once for the module."""
    root = tmp_path_factory.mktemp("ordinary-corpus") / "project"
    root.mkdir()
    build_fixture_tree(root)
    return root


@pytest.fixture()
def chain(fixture_root: Path) -> Iterator[EventRouter]:
    """Every discovered handler at its default configuration, over the fixture project."""
    _initialise_project_context(fixture_root)
    router = EventRouter()
    registry = HandlerRegistry()
    registry.discover()
    registry.register_all(router)
    yield router


def _hook_input(row: Row, root: Path) -> dict[str, Any]:
    cwd = root / row.cwd if row.cwd else root
    command = row.command.replace("{ROOT}", str(root))
    base: dict[str, Any] = {
        "hook_event_name": "PreToolUse",
        "tool_name": row.tool,
        "cwd": str(cwd),
        "session_id": "ordinary-command-gate",
    }
    if row.tool == _TOOL_BASH:
        return {**base, "tool_input": {"command": command}}
    field_name = _PATH_FIELD_BY_TOOL[row.tool]
    tool_input: dict[str, Any] = {field_name: command}
    if row.tool == "Write":
        tool_input["content"] = "VALUE = 1\n"
    if row.tool == "Edit":
        tool_input.update(old_string="x = 1", new_string="x = 2")
    return {**base, "tool_input": tool_input}


class TestCorpusShape:
    """The corpus is only worth running if it is wide and well-formed."""

    def test_corpus_is_wide(self) -> None:
        assert len(ROWS) >= MINIMUM_CORPUS_ROWS

    def test_row_ids_are_unique(self) -> None:
        ids = [row.id for row in ROWS]
        assert len(ids) == len(set(ids))

    def test_every_xfail_names_its_cause(self) -> None:
        for row in ROWS:
            if row.xfail is not None:
                assert len(row.xfail) > 10, f"row {row.id} has an xfail with no cause"

    def test_tools_are_known(self) -> None:
        for row in ROWS:
            assert row.tool == _TOOL_BASH or row.tool in _PATH_FIELD_BY_TOOL

    def test_fixture_tree_holds_protected_files_in_usual_places(self, fixture_root: Path) -> None:
        for relative in (
            f".claude/{_WORD_LIST}",
            _VAULT_PASS,
            f"group_vars/all/{_VAULT_FILE}",
            f"untracked/{_KEY_FILE}",
        ):
            assert (fixture_root / relative).is_file(), relative


class TestOrdinaryCommandsStayAllowed:
    """The gate itself: every row is ALLOWED by the whole chain."""

    @pytest.mark.parametrize("row", _params())
    def test_row_is_allowed(self, row: Row, chain: EventRouter, fixture_root: Path) -> None:
        outcome = chain.route(EventType.PRE_TOOL_USE, _hook_input(row, fixture_root))

        assert outcome.result.decision == Decision.ALLOW, (
            f"{row.id}: an ordinary command is denied by {outcome.decided_by!r}\n"
            f"command: {row.command}\n"
            f"reason: {(outcome.result.reason or '')[:600]}\n"
            "A guard change flipped an ALLOW to a deny. Fix the guard; a row is only "
            "dropped by the owner."
        )
