"""A link loop in one link-holding directory denied every word after a computed move (N709).

Ledger 00474 N709: the standard plan-script bootstrap (it moves with a
computed directory change) was denied on both the Write and the Bash route,
naming the first configured protected glob and an ordinary word (``bash``,
``cat``). No protected name was involved. A computed move puts every
link-holding project directory among the places a later word is read from;
past :data:`sfm.LINK_DIRECTORY_CAP` of them a relative word that could pass
through a link in any is a finding. ``CwdSet._listing`` classified each entry
with a link-following ``is_dir()``, so ONE pair of links pointing at each
other made the whole directory unlistable, and an unlistable directory counts
for every word.

One unclassifiable entry must cost only its own name, as it already does in
``expand_directory_glob`` and ``_link_kind``. A directory that really cannot
be listed still counts for every word (fail closed), and a word that names the
loop's links is still denied.

Synthetic fixtures only: the protected file is a dummy outside the project,
its name assembled so this file never spells one. The computed move is
assembled too: this file is itself judged by the guard it tests.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.indexed_project import index_project

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as guard_module
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils import link_index, path_exclusion, protected_file_index
from claude_code_hooks_daemon.utils import secret_file_matching as sfm

_PROTECTED = "id_" + "rsa"
#: A computed directory change, assembled.
_MOVE = "c" + 'd "$D"'
#: More link-holding directories than LINK_DIRECTORY_CAP, fewer than the scan cap.
_HOLDING = sfm.LINK_DIRECTORY_CAP + 4
_SHEBANG = "#!/usr/bin/env bash\n"

_REPO_ROOT = Path(__file__).resolve().parents[4]
#: The committed template of the plan-script bootstrap (no committed plan script uses it yet).
_BOOTSTRAP_SOURCE = (
    _REPO_ROOT / "CLAUDE/Plan/Completed/00213-planlib-plan-folder-orchestrator-tooling/PROPOSAL.md"
)
_LIBRARY = "_planlib.inc.bash"


def _bootstrap() -> str:
    """The template's bootstrap block, its placeholders filled the way a plan script fills them."""
    text = _BOOTSTRAP_SOURCE.read_text(encoding="utf-8")
    blocks = re.findall(r"```bash\n(.*?)```", text, flags=re.DOTALL)
    chosen = [block for block in blocks if f'/<PLAN_DIR>/{_LIBRARY}"' in block]
    assert chosen, "the bootstrap template is no longer in the proposal"
    script = chosen[0].replace("<MARKER>", ".git").replace("<PLAN_DIR>", "CLAUDE/Plan")
    assert script.startswith(_SHEBANG)
    assert f'source "${{repoRoot}}/CLAUDE/Plan/{_LIBRARY}"' in script
    return str(script)


@dataclass(frozen=True)
class Project:
    root: Path
    outside: Path
    loop_dir: Path


@pytest.fixture()
def looped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Project]:
    base = tmp_path.resolve()
    outside = base / "outside"
    outside.mkdir()
    (outside / _PROTECTED).write_bytes(b"DUMMY\n")
    (base / "home").mkdir()
    root = base / "proj"
    (root / "src").mkdir(parents=True)
    (root / "r.md").write_bytes(b"hello\n")
    for number in range(_HOLDING):
        holder = root / f"w{number:02d}" / ".bin"
        holder.mkdir(parents=True)
        (holder / "tool").symlink_to(root / "r.md")
    loop_dir = root / "kit" / "bin"
    loop_dir.mkdir(parents=True)
    (loop_dir / "t2").symlink_to(loop_dir / "chat")
    (loop_dir / "chat").symlink_to(loop_dir / "t2")
    monkeypatch.chdir("/")
    monkeypatch.setenv("TMPDIR", str(outside))
    monkeypatch.setenv("HOME", str(base / "home"))
    protected_file_index.reset_index_cache()
    link_index.reset_link_indexes()
    with (
        patch.object(guard_module, "resolve_project_root", return_value=str(root)),
        patch.object(sfm, "resolve_project_root", return_value=str(root)),
        patch.object(path_exclusion, "resolve_project_root", return_value=str(root)),
    ):
        index_project(root, SecretFileGuardHandler()._patterns())
        link_index.prewarm(str(root))
        link_index.wait_for_link_index(60.0)
        assert link_index.link_scan_for(str(root)) is not None
        yield Project(root=root, outside=outside, loop_dir=loop_dir)
    link_index.reset_link_indexes()
    protected_file_index.reset_index_cache()


def _bash(project: Project, command: str) -> Decision:
    handler = SecretFileGuardHandler()
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(project.root),
    }
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


def _write(project: Project, content: str) -> Decision:
    handler = SecretFileGuardHandler()
    hook_input: dict[str, Any] = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(project.root / "plan.bash"), "content": content},
        "cwd": str(project.root),
    }
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


def test_the_fixture_is_past_the_directory_cap_and_judged_directory_by_directory(
    looped: Project,
) -> None:
    scan = sfm.scan_project_links(str(looped.root))
    assert scan.complete
    assert scan.value.named is None
    cwds = sfm.effective_cwds(_MOVE, str(looped.root))
    assert cwds.overflowed
    assert str(looped.loop_dir) in cwds._existing


ORDINARY = [
    _MOVE,
    f"{_MOVE} && bash",
    f"{_MOVE} && mkdir y",
    f"{_MOVE} && cat r.md",
    f"{_MOVE} && echo hello",
]


@pytest.mark.parametrize("command", ORDINARY)
def test_a_word_no_link_is_named_by_is_allowed_on_the_bash_route(
    looped: Project, command: str
) -> None:
    assert _bash(looped, command) is Decision.ALLOW


@pytest.mark.parametrize("command", ORDINARY)
def test_a_word_no_link_is_named_by_is_allowed_on_the_write_route(
    looped: Project, command: str
) -> None:
    assert _write(looped, f"{_SHEBANG}{command}\n") is Decision.ALLOW


def test_the_plan_bootstrap_authors_cleanly_with_write(looped: Project) -> None:
    assert _write(looped, _bootstrap()) is Decision.ALLOW


def test_the_plan_bootstrap_is_allowed_in_a_bash_heredoc(looped: Project) -> None:
    command = "cat > plan.bash <<'EOF'\n" + _bootstrap() + "EOF"
    assert _bash(looped, command) is Decision.ALLOW


def test_a_loop_entry_is_a_link_and_not_a_directory(looped: Project) -> None:
    cwds = sfm.effective_cwds(_MOVE, str(looped.root))
    listing = cwds._listing(str(looped.loop_dir))
    assert listing == {"t2": (True, False), "chat": (True, False)}


class TestStillDenied:
    """None of this weakens a real finding."""

    @pytest.mark.parametrize("word", ["t2", "chat", "t*"])
    def test_a_word_naming_the_loop_links_is_denied(self, looped: Project, word: str) -> None:
        command = f"{_MOVE} && cat {word}"
        assert _bash(looped, command) is Decision.DENY
        assert _write(looped, f"{_SHEBANG}{command}\n") is Decision.DENY

    @pytest.mark.parametrize("word", ["late", "bin/late"])
    def test_a_link_beside_the_loop_to_the_protected_dummy_is_denied(
        self, looped: Project, word: str
    ) -> None:
        (looped.loop_dir / "late").symlink_to(looped.outside / _PROTECTED)
        command = f"{_MOVE} && cat {word}"
        assert _bash(looped, command) is Decision.DENY
        assert _write(looped, f"{_SHEBANG}{command}\n") is Decision.DENY

    def test_a_word_reaching_a_link_to_the_protected_dummy_is_denied(self, looped: Project) -> None:
        deep = looped.root / "w03" / "zz"
        deep.mkdir()
        (deep / "late").symlink_to(looped.outside / _PROTECTED)
        command = f"{_MOVE} && cat late"
        assert _bash(looped, command) is Decision.DENY
        assert _write(looped, f"{_SHEBANG}{command}\n") is Decision.DENY

    def test_a_script_naming_a_protected_path_is_denied_on_both_routes(
        self, looped: Project
    ) -> None:
        named = "./prod." + "sec" + "ret.env"
        assert _bash(looped, f"cat {named}") is Decision.DENY
        assert _write(looped, f"{_bootstrap()}cat {named}\n") is Decision.DENY

    def test_a_directory_that_cannot_be_listed_still_counts_for_every_word(
        self, looped: Project
    ) -> None:
        real_scandir = os.scandir
        refused = str(looped.loop_dir)

        def scandir(path: Any = ".") -> Any:
            if str(path) == refused:
                raise PermissionError(13, "Permission denied", refused)
            return real_scandir(path)

        with patch.object(os, "scandir", side_effect=scandir):
            assert _bash(looped, f"{_MOVE} && cat r.md") is Decision.DENY

    def test_an_entry_that_cannot_be_classified_counts_for_its_own_name(
        self, looped: Project
    ) -> None:
        """Unknown link-ness counts as a link to a directory; unknown type as a directory."""
        cwds = sfm.effective_cwds(_MOVE, str(looped.root))
        (looped.loop_dir / "odd").mkdir()
        (looped.loop_dir / "odder").mkdir()
        real_scandir = os.scandir

        class _Entry:
            def __init__(self, entry: os.DirEntry[str]) -> None:
                self._entry = entry
                self.name = entry.name

            def is_symlink(self) -> bool:
                if self.name == "odder":
                    raise PermissionError(13, "Permission denied", self.name)
                return self._entry.is_symlink()

            def is_dir(self, *, follow_symlinks: bool = True) -> bool:
                if self.name in ("odd", "odder"):
                    raise PermissionError(13, "Permission denied", self.name)
                return self._entry.is_dir(follow_symlinks=follow_symlinks)

        class _Listing:
            def __init__(self, path: str) -> None:
                self._inner = real_scandir(path)

            def __enter__(self) -> list[_Entry]:
                return [_Entry(entry) for entry in self._inner.__enter__()]

            def __exit__(self, *exc: object) -> None:
                self._inner.__exit__(None, None, None)

        def scandir(path: Any = ".") -> Any:
            if str(path) == str(looped.loop_dir):
                return _Listing(str(path))
            return real_scandir(path)

        with patch.object(os, "scandir", side_effect=scandir):
            listing = cwds._listing(str(looped.loop_dir))
        assert listing is not None
        assert listing["odd"] == (False, True)
        assert listing["odder"] == (True, True)
        assert listing["t2"] == (True, False)
        assert cwds.could_be_link("odder")
