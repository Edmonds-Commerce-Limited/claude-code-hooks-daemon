"""More link-holding directories than the walkers list (Plan 00623, N669/N670).

A project with many link-holding directories (``node_modules/.bin`` in every
package) stopped ``_scan_from_index`` at :data:`LINK_SCAN_DIRECTORY_CAP`, so
every computed move followed by a reader was denied. Past that cap the index's
verified link PATHS judge a word by name instead: a word whose leading
components spell the tail of any link path is denied, as is any ``..``.
Directory links stay real bases under their own hard bound.

The caps are monkeypatched small so the fixture stays fast. Synthetic fixtures
only: the protected file is a dummy outside the project, its name assembled so
this file never spells one.
"""

from __future__ import annotations

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
#: The patched per-scan directory cap; the fixture holds more link-holding directories.
_CAP = 8
_HOLDING = 20
_LAST = f"w{_HOLDING - 1:02d}"

ORDINARY = [
    'cd "$D" && cat r.md',
    "cd - && cat r.md",
    "cd && cat r.md",
    "cd $(echo x) && ls",
    'cd "$(mktemp -d)" && ls',
    'cd "$TMPDIR" && python3 x.py',
    'cd "$(dirname "$0")" && ./run.sh',
    'cd "$D" && cat src/main.py',
    'cd "$D" && ls -la',
    'cd "$D" && npm test',
]

REACHING = [
    'cd "$D" && cat late',
    'cd "$D" && cat zz/late',
    f'cd "$D" && cat {_LAST}/zz/late',
    'cd "$D" && cat l*',
    'cd "$D" && cat z*/late',
    'cd "$D" && cat ./zz//late',
    'cd "$D" && cat dl/' + _PROTECTED,
    'cd "$D" && cat ../zz/late',
    'cd "$D" && cat src/../zz/late',
    'cd "$D" && cd zz && cat late',
    'cd "$D" && grep -r x dl',
    'cd "$D" && grep -r x .',
    "cd ~ && cat late",
    "cd - && head late",
]


@dataclass(frozen=True)
class Project:
    root: Path
    outside: Path


@pytest.fixture()
def many(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Project]:
    base = tmp_path.resolve()
    outside = base / "outside"
    outside.mkdir()
    (outside / _PROTECTED).write_bytes(b"DUMMY\n")
    (base / "home").mkdir()
    root = base / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_bytes(b"x\n")
    (root / "r.md").write_bytes(b"hello\n")
    for number in range(_HOLDING):
        holder = root / f"w{number:02d}" / ".bin"
        holder.mkdir(parents=True)
        # Like node_modules/.bin: a link that stays inside the project.
        (holder / "tool").symlink_to(root / "r.md")
    monkeypatch.chdir("/")
    monkeypatch.setenv("TMPDIR", str(outside))
    monkeypatch.setenv("HOME", str(base / "home"))
    monkeypatch.setattr(sfm, "LINK_SCAN_DIRECTORY_CAP", _CAP)
    protected_file_index.reset_index_cache()
    link_index.reset_link_indexes()
    with (
        patch.object(guard_module, "resolve_project_root", return_value=str(root)),
        patch.object(sfm, "resolve_project_root", return_value=str(root)),
        patch.object(path_exclusion, "resolve_project_root", return_value=str(root)),
    ):
        index_project(root, SecretFileGuardHandler()._patterns())
        yield Project(root=root, outside=outside)
    link_index.reset_link_indexes()
    protected_file_index.reset_index_cache()


@pytest.fixture()
def reaching(many: Project) -> Project:
    """A link to the dummy, and a directory link out, in the LAST holding tree."""
    deep = many.root / _LAST / "zz"
    deep.mkdir()
    (deep / "late").symlink_to(many.outside / _PROTECTED)
    (deep / "dl").symlink_to(many.outside)
    return many


def _built(project: Project) -> None:
    link_index.prewarm(str(project.root))
    link_index.wait_for_link_index(60.0)
    assert link_index.link_scan_for(str(project.root)) is not None


def _decision(project: Project, command: str) -> Decision:
    handler = SecretFileGuardHandler()
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(project.root),
    }
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


def test_the_fixture_holds_more_link_directories_than_the_cap(many: Project) -> None:
    _built(many)
    indexed = link_index.link_scan_for(str(many.root))
    assert indexed is not None and indexed.complete
    assert len(indexed.value.holding) > _CAP


@pytest.mark.parametrize("command", ORDINARY)
def test_an_ordinary_command_is_allowed_past_the_cap(many: Project, command: str) -> None:
    _built(many)
    assert _decision(many, command) is Decision.ALLOW


@pytest.mark.parametrize("command", ORDINARY)
def test_an_ordinary_command_is_allowed_with_a_link_out_elsewhere(
    reaching: Project, command: str
) -> None:
    _built(reaching)
    assert _decision(reaching, command) is Decision.ALLOW


@pytest.mark.parametrize("command", REACHING)
def test_a_word_reaching_a_link_to_the_protected_dummy_is_denied(
    reaching: Project, command: str
) -> None:
    _built(reaching)
    assert _decision(reaching, command) is Decision.DENY


@pytest.mark.parametrize("command", REACHING)
def test_a_link_made_after_the_build_is_seen(many: Project, command: str) -> None:
    _built(many)
    deep = many.root / _LAST / "zz"
    deep.mkdir()
    (deep / "late").symlink_to(many.outside / _PROTECTED)
    (deep / "dl").symlink_to(many.outside)
    assert _decision(many, command) is Decision.DENY


@pytest.mark.parametrize("command", ['cd "$D" && cat r.md', "cd - && cat r.md"])
def test_a_cold_index_still_denies(many: Project, command: str) -> None:
    with patch.object(link_index, "link_scan_for", return_value=None):
        assert _decision(many, command) is Decision.DENY


@pytest.mark.parametrize("command", ['cd "$D" && cat r.md', "cd - && cat r.md"])
def test_an_overflowed_index_still_denies(
    many: Project, command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(link_index, "BUILD_DIRECTORY_CAP", 4)
    _built(many)
    assert _decision(many, command) is Decision.DENY


def test_more_directory_links_than_their_bound_deny(
    many: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each directory link is a place a ``cd`` can land outside the index: hard-bounded."""
    monkeypatch.setattr(sfm, "INDEXED_DIRECTORY_LINK_CAP", 1)
    (many.root / "w00" / "d1").symlink_to(many.outside)
    (many.root / "w01" / "d2").symlink_to(many.outside)
    _built(many)
    assert not sfm.scan_project_links(str(many.root)).complete
    assert _decision(many, 'cd "$D" && cat r.md') is Decision.DENY


def test_more_links_than_their_bound_deny(many: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sfm, "INDEXED_LINK_CAP", _HOLDING - 1)
    _built(many)
    assert not sfm.scan_project_links(str(many.root)).complete
    assert _decision(many, 'cd "$D" && cat r.md') is Decision.DENY


def test_under_the_cap_the_scan_is_unchanged(
    many: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """At or under the cap every directory is still a real base, judged word by word."""
    monkeypatch.setattr(sfm, "LINK_SCAN_DIRECTORY_CAP", 512)
    _built(many)
    scan = sfm.scan_project_links(str(many.root))
    assert scan.complete
    assert scan.value.named is None
    assert len(scan.value.directories) == _HOLDING


def test_past_the_cap_the_holding_directories_are_judged_by_name(many: Project) -> None:
    _built(many)
    scan = sfm.scan_project_links(str(many.root))
    assert scan.complete
    assert scan.value.named is not None
    assert scan.value.directories == ()


def test_a_search_from_a_holding_directory_is_judged_over_every_indexed_file(
    many: Project,
) -> None:
    """Past the cap the holding directories are not places a search is put, so it is lost."""
    nested = many.root / _LAST / ".bin" / "sub"
    nested.mkdir()
    (nested / _PROTECTED).write_bytes(b"DUMMY\n")
    index_project(many.root, SecretFileGuardHandler()._patterns())
    _built(many)
    assert _decision(many, 'cd "$D" && grep -r x sub') is Decision.DENY


#: Release 3.76.0 review 2 F4: an apostrophe makes a body line unparseable on its own.
_APOSTROPHE = "it" + "'" + "s"

#: A quoted heredoc body no command runs, now or later (prose to `.md`), holding
#: text that reads as a computed move, and a relative word spelling a link name.
UNRUN_BODIES = [
    f"cat > notes.md <<'EOF'\n{_APOSTROPHE} `sudo -D/--chdir` text\nsee .bin/tool\nEOF",
    f"cat > notes.md <<'EOF'\n{_APOSTROPHE} `cd d && cat x`\nsee .bin/tool\nEOF",
    "cat > notes.md <<'EOF'\ncd \"$D\"\nsee .bin/tool\nEOF",
    "cat > notes.md <<'EOF'\ncd -\nsee .bin/tool\nEOF",
    "cat <<'EOF' > notes.md\ncd ~\nsee .bin/tool\nEOF",
    "git commit -F - <<'EOF'\ncd \"$D\"\nsee .bin/tool\nEOF",
]

#: Prose whose option words sit in no command position: a loose (unbalanced) segment.
LOOSE_PROSE = [
    f"cat > notes.txt <<'EOF'\n{_APOSTROPHE} sudo -D x\nsee .bin/tool\nEOF",
    f"cat > notes.txt <<'EOF'\n{_APOSTROPHE} env --chdir x\nsee .bin/tool\nEOF",
    "git commit -m 'x sudo -D y && z'; cat .bin/tool",
    "echo 'a env -C y && b'; cat .bin/tool",
]

#: The same moves where something RUNS them, or after the heredoc ends.
RUN_BODIES = [
    "bash <<'EOF'\ncd \"$D\" && cat late\nEOF",
    "sh <<'EOF'\ncd \"$D\" && cat late\nEOF",
    "python3 <<'EOF'\ncd \"$D\" && cat late\nEOF",
    "ssh h <<'EOF'\ncd \"$D\" && cat late\nEOF",
    "cat <<'EOF' | bash\ncd \"$D\" && cat late\nEOF",
    "cat <<'EOF' > >(bash)\ncd \"$D\" && cat late\nEOF",
    "cat <<EOF\n$(cd \"$D\" && cat late)\nEOF",
    "$(cat <<'EOF'\ncd \"$D\" && cat late\nEOF\n)",
    f"bash <<'EOF'\necho {_APOSTROPHE}\ncd \"$D\" && cat late\nEOF",
    "cat > run.sh <<'EOF'\ncd \"$D\" && cat late\nEOF",
    "cat > notes.md <<'EOF'\nhello\nEOF\ncd \"$D\" && cat late",
    f"cat > notes.md <<'EOF'\n{_APOSTROPHE}\nEOF\ncat {_LAST}/zz/late",
]

#: Loose (unbalanced) segments whose move IS in command position after a quote opens.
LOOSE_MOVES = [
    "bash -c 'cd \"$D\" && cat late'",
    "sh -c \"cd $D && cat late\"",
    "sudo bash -c 'cd \"$D\" && cat late'",
    "eval \"cd $D && cat late\"",
    "ssh h 'cd \"$D\" && cat late'",
    "bash -c 'sudo -D \"$D\" cat late && true'",
    "bash -c 'true && env -C \"$D\" cat late'",
    "bash -c 'FOO=1 cd \"$D\" && cat late'",
    "bash -c '(cd \"$D\" && cat late)'",
    "bash -c 'builtin cd \"$D\" && cat late'",
]


class TestQuotedHeredocPastTheCap:
    """Review 2 F4: data in a quoted heredoc body moves nowhere, so it never overflows."""

    @pytest.mark.parametrize("command", UNRUN_BODIES)
    def test_an_unrun_body_is_allowed(self, many: Project, command: str) -> None:
        _built(many)
        assert _decision(many, command) is Decision.ALLOW

    @pytest.mark.parametrize("command", UNRUN_BODIES)
    def test_an_unrun_body_makes_no_move(self, many: Project, command: str) -> None:
        _built(many)
        assert not sfm.effective_cwds(command, str(many.root)).overflowed

    @pytest.mark.parametrize("command", LOOSE_PROSE)
    def test_prose_in_a_loose_segment_is_allowed(self, many: Project, command: str) -> None:
        _built(many)
        assert _decision(many, command) is Decision.ALLOW

    @pytest.mark.parametrize("command", RUN_BODIES)
    def test_a_run_body_still_denies(self, reaching: Project, command: str) -> None:
        _built(reaching)
        assert _decision(reaching, command) is Decision.DENY

    @pytest.mark.parametrize("command", LOOSE_MOVES)
    def test_a_loose_move_after_a_quote_still_denies(
        self, reaching: Project, command: str
    ) -> None:
        _built(reaching)
        assert _decision(reaching, command) is Decision.DENY

    def test_the_reason_names_no_move_the_decision_never_saw(self, reaching: Project) -> None:
        """Review 2 F4 (c): the cause is computed from the text the decision judged."""
        _built(reaching)
        handler = SecretFileGuardHandler()
        command = f"cat > notes.md <<'EOF'\ncd \"$D\"\nEOF\ncat {_LAST}/zz/late"
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": str(reaching.root),
        }
        result = handler.handle(hook_input)
        assert result.decision is Decision.DENY
        assert "existing directories" not in (result.reason or "")


class TestLinkNames:
    """The name rule on its own: a word whose leading components spell a link path's tail."""

    @pytest.fixture()
    def names(self) -> sfm.LinkNames:
        return sfm.LinkNames(("/p/a/.bin/tool", "/p/b/zz/late", "/p/c/[x]"))

    @pytest.mark.parametrize(
        "word",
        [
            "late",
            "zz/late",
            "zz/late/more",
            "b/zz/late",
            "./zz//late",
            "l*",
            "z?/late",
            "*/late",
            "[z]z/late",
            ".bin/tool",
            "..",
            "x/../y",
            "[x]",
            "@(late)",
        ],
    )
    def test_it_reaches(self, names: sfm.LinkNames, word: str) -> None:
        assert names.reaches(word)

    @pytest.mark.parametrize(
        "word", ["r.md", "src/main.py", "zz", "zz/other", "a/late", "bin/tool", "*.md", "x"]
    )
    def test_it_does_not_reach(self, names: sfm.LinkNames, word: str) -> None:
        assert not names.reaches(word)
