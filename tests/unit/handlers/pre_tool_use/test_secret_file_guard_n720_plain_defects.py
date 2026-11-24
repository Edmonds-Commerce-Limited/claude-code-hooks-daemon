"""Plain defects of N720 (with N719): reproducers from the PR 232 independent review.

Ledger 00474 N720 and N719, and ``subagent-reports/261123-opus-independent-review-pr232.md``:

1. ``shopt -s nocaseglob; cat kit/lib/[I]D_RSA``: a one-character bracket expands
   to a literal name that every later check compared case-exactly, the
   protected-file index's own matcher included (N719).
2. ``cat kit/lib/[x[:lower:]]d_rsa``: a POSIX class not first in its bracket was
   read by an older bracket-naive reader on the Write-script and no-index routes.
3. ``bash -xO dotglob -c ...``: ``-O`` inside a flag cluster did not switch the
   guard to its conservative reading.
4. An extglob word beside a size limit was allowed with an advisory, because the
   "glob left unjudged" check did not count ``@(...)``.

Every case runs in both modes: bash's defaults certain (an all-off snapshot) and
conservative (no snapshot). Synthetic fixtures only: the protected file is a
dummy outside the project, its name assembled so this file never spells one.
"""

from __future__ import annotations

import logging
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
from claude_code_hooks_daemon.utils.shell_snapshot import reset_snapshot_cache

_PROTECTED = "id_" + "rsa"
_UPPER = _PROTECTED.upper()
_SHEBANG = "#!/usr/bin/env bash\n"
_SNAPSHOT_ALL_OFF = (
    "shopt -u dotglob\nshopt -u globstar\nshopt -u nocaseglob\nshopt -s globasciiranges\n"
)
_DEFAULTS_CERTAIN = "defaults-certain"
_CONSERVATIVE = "conservative"
_DENIED_EVERYWHERE = (Decision.DENY, Decision.DENY, Decision.DENY)
_ALLOWED_EVERYWHERE = (Decision.ALLOW, Decision.ALLOW, Decision.ALLOW)


@dataclass(frozen=True)
class Project:
    root: Path
    outside: Path
    kit: Path
    defaults_certain: bool


@pytest.fixture(params=[_DEFAULTS_CERTAIN, _CONSERVATIVE])
def project(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Project]:
    base = tmp_path.resolve()
    outside = base / "outside"
    outside.mkdir()
    (outside / _PROTECTED).write_bytes(b"DUMMY\n")
    (base / "home").mkdir()
    config = base / "claude-config"
    config.mkdir()
    defaults_certain = request.param == _DEFAULTS_CERTAIN
    if defaults_certain:
        (config / "shell-snapshots").mkdir()
        (config / "shell-snapshots" / "snapshot-bash-1-a.sh").write_text(_SNAPSHOT_ALL_OFF)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    root = base / "proj"
    root.mkdir()
    (root / "r.md").write_bytes(b"hello\n")
    kit = root / "kit"
    (kit / "bin").mkdir(parents=True)
    (kit / "lib").mkdir()
    (kit / ".hid").mkdir()
    (kit / "bin" / "late").symlink_to(outside / _PROTECTED)
    (kit / ".hid" / "late2").symlink_to(outside / _PROTECTED)
    (kit / "lib" / _PROTECTED).write_bytes(b"DUMMY\n")
    (kit / "lib" / "notes.txt").write_bytes(b"plain\n")
    monkeypatch.chdir("/")
    monkeypatch.setenv("TMPDIR", str(outside))
    monkeypatch.setenv("HOME", str(base / "home"))
    reset_snapshot_cache()
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
        yield Project(root=root, outside=outside, kit=kit, defaults_certain=defaults_certain)
    link_index.reset_link_indexes()
    protected_file_index.reset_index_cache()
    reset_snapshot_cache()


def _bash(command: str, cwd: Path) -> Decision:
    handler = SecretFileGuardHandler()
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


def _write(content: str, cwd: Path) -> Decision:
    handler = SecretFileGuardHandler()
    hook_input: dict[str, Any] = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(cwd / "plan.bash"), "content": content},
        "cwd": str(cwd),
    }
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


def _every_route(command: str, cwd: Path) -> tuple[Decision, Decision, Decision]:
    """The Bash route, the Write-script route, and the Bash route with no index."""
    with patch.object(SecretFileGuardHandler, "_index", return_value=None):
        unindexed = _bash(command, cwd)
    return _bash(command, cwd), _write(f"{_SHEBANG}{command}\n", cwd), unindexed


class TestItem1CaseBlindFiniteBracket:
    """N720 item 1 with N719: a finite bracket under ``nocaseglob`` naming a protected file."""

    @pytest.mark.parametrize(
        "word",
        [
            f"[{_UPPER[0]}]{_UPPER[1:]}",
            f"{_UPPER[:-1]}[{_UPPER[-1]}]",
            f"[{_UPPER[0]}{_PROTECTED[0]}]{_UPPER[1:]}",
            f"{_UPPER[:2]}[_]{_UPPER[3:]}",
        ],
    )
    def test_a_finite_bracket_under_nocaseglob_naming_a_protected_file_is_denied(
        self, project: Project, word: str
    ) -> None:
        command = f"shopt -s nocaseglob; cat kit/lib/{word}"
        assert _every_route(command, project.root) == _DENIED_EVERYWHERE

    def test_a_finite_bracket_under_nocaseglob_reaching_the_link_is_denied(
        self, project: Project
    ) -> None:
        """Bash reads a pattern component case-blind; ``LATE`` alone would be compared exactly."""
        assert _every_route("shopt -s nocaseglob; cat kit/[B]IN/[L]ATE", project.root) == (
            _DENIED_EVERYWHERE
        )

    @pytest.mark.parametrize(
        ("glob", "path"),
        [
            (["kit", "lib", f"[{_UPPER[0]}]{_UPPER[1:]}"], ["kit", "lib", _PROTECTED]),
            (["kit", "[B]IN", "*"], ["kit", "bin", "late"]),
            (["kit", "lib", f"[x[:lower:]]{_PROTECTED[1:]}"], ["kit", "lib", _PROTECTED]),
        ],
    )
    def test_the_index_matcher_reads_as_the_shared_component_reader(
        self, glob: list[str], path: list[str]
    ) -> None:
        """N719: case-blind unless bash's defaults are certain, and bracket-aware."""
        assert protected_file_index._segments_match(path, glob, ignore_case=True)

    def test_the_index_matcher_compares_a_literal_component_exactly(self) -> None:
        """Bash compares a component with no pattern characters exactly, nocaseglob or not."""
        glob = ["kit", "lib", _UPPER]
        assert not protected_file_index._segments_match(
            ["kit", "lib", _PROTECTED], glob, ignore_case=True
        )

    def test_the_index_matcher_reads_case_exactly_when_defaults_are_certain(self) -> None:
        glob = ["kit", "[B]IN", "*"]
        assert not protected_file_index._segments_match(
            ["kit", "bin", "late"], glob, ignore_case=False
        )

    def test_an_indexed_glob_under_nocaseglob_is_found(self, project: Project) -> None:
        index = protected_file_index.index_for(project.root, SecretFileGuardHandler()._patterns())
        assert index is not None
        word = f"kit/lib/[{_UPPER[0]}]{_UPPER[1:]}"
        assert index.glob_matches(word, [str(project.root)], default_expansion=False)
        assert not index.glob_matches(word, [str(project.root)], default_expansion=True)


class TestGlobasciirangesIsRequired:
    """N719/N720 LOW: certain mode reads ranges in ASCII order, so the snapshot must say so."""

    @pytest.mark.parametrize(
        ("line", "certain"),
        [
            ("shopt -s globasciiranges\n", True),
            ("shopt -u globasciiranges\n", False),
            ("", False),
        ],
    )
    def test_certain_mode_needs_globasciiranges_on(
        self, tmp_path: Path, line: str, certain: bool
    ) -> None:
        from claude_code_hooks_daemon.utils import shell_snapshot

        snapshots = tmp_path / shell_snapshot.SNAPSHOT_DIRNAME
        snapshots.mkdir()
        body = "shopt -u dotglob\nshopt -u globstar\nshopt -u nocaseglob\n" + line
        (snapshots / "snapshot-bash-1-a.sh").write_text(body)
        reset_snapshot_cache()
        assert shell_snapshot.default_glob_semantics("ls", config_dir=tmp_path) is certain
        reset_snapshot_cache()


class TestItem2ClassNotFirstInItsBracket:
    """N720 item 2: the older bracket-naive reader on the Write-script and no-index routes."""

    @pytest.mark.parametrize(
        "word",
        [
            f"[x[:lower:]]{_PROTECTED[1:]}",
            f"{_PROTECTED[:-1]}[x[:lower:]]",
            f"[x[:alpha:]]{_PROTECTED[1:]}",
            f"{_PROTECTED[:2]}[x[:punct:]]{_PROTECTED[3:]}",
        ],
    )
    def test_a_class_bracket_naming_a_protected_file_is_denied_on_every_route(
        self, project: Project, word: str
    ) -> None:
        assert _every_route(f"cat kit/lib/{word}", project.root) == _DENIED_EVERYWHERE

    def test_the_residue_reader_skips_a_whole_class_bracket(self) -> None:
        assert sfm._class_aware_literal_residue(f"[x[:lower:]]{_PROTECTED[1:]}") == (_PROTECTED[1:])

    @pytest.mark.parametrize(
        ("token", "residue"),
        [
            ("ab[]x]cd", "abcd"),
            ("ab[!]x]cd*", "abcd"),
            ("ab[x\\]]cd", "abcd"),
            ("ab[x", "ab[x"),
            ("ab[[:nope]cd", "abcd"),
            ("a?b*", "ab"),
        ],
    )
    def test_the_class_aware_residue_reads_brackets_as_bash_does(
        self, token: str, residue: str
    ) -> None:
        assert sfm._class_aware_literal_residue(token) == residue


class TestItem3aFlagCluster:
    """N720 item 3 (the ``-O`` part only): a literal, visible switch in a flag cluster."""

    @pytest.mark.parametrize(
        "command",
        [
            "bash -xO dotglob -c 'cat kit/*/late2'",
            "bash -eO dotglob -c 'cat kit/*/late2'",
            "bash -xeO dotglob -c 'cat kit/*/late2'",
            "bash -Ox dotglob -c 'cat kit/*/late2'",
            "bash -xOe dotglob -c 'cat kit/*/late2'",
            "sh -xO dotglob -c 'cat kit/*/late2'",
            "bash -xO nocaseglob -c 'cat kit/B?N/late'",
        ],
    )
    def test_an_option_switch_inside_a_flag_cluster_is_denied(
        self, project: Project, command: str
    ) -> None:
        assert _every_route(command, project.root) == _DENIED_EVERYWHERE

    def test_a_flag_cluster_with_no_option_switch_keeps_bash_defaults(
        self, project: Project
    ) -> None:
        if not project.defaults_certain:
            pytest.skip("only bash's certain defaults skip dot names")
        assert _every_route("bash -xe -c 'cat kit/*/late2'", project.root) == _ALLOWED_EVERYWHERE


_NESTED_20 = "echo " + "$(echo " * 20 + "$(cat kit/@(bin)/late)" + ")" * 20


class TestItem4ExtglobBesideASizeLimit:
    """N720 item 4: an extglob word next to a scan size limit is a glob left unjudged."""

    @pytest.mark.parametrize(
        "command",
        [
            f"bash -O extglob -c '{_NESTED_20}'",
            "bash -O extglob -c 'cat kit/@(bin)/late' " + "{1..9}" * 7,
            "bash -O extglob -c 'cat kit/b?n/late' " + "{1..9}" * 7,
            f"bash -c '{_NESTED_20.replace('@(bin)', 'b?n')}'",
        ],
    )
    def test_an_extglob_word_beside_a_size_limit_is_denied(
        self, project: Project, command: str
    ) -> None:
        assert _every_route(command, project.root) == _DENIED_EVERYWHERE

    @pytest.mark.parametrize("word", ["kit/@(bin)/late", "!(x)", "+(a|b)", "*(a)", "?(a)"])
    def test_an_extglob_group_counts_as_a_glob(self, word: str) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": f"echo {word}"},
            "cwd": "/",
        }
        assert guard_module._holds_search_or_glob(hook_input)


class TestLowReversedRange:
    def test_a_reversed_range_logs_one_line_not_a_traceback(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        sfm._component_regex.cache_clear()
        with caplog.at_level(logging.DEBUG):
            assert sfm._component_spells("[z-a]x", "bx") in (True, False)
        refused = [r for r in caplog.records if r.exc_info]
        assert refused == []


class TestEverythingDeniedBeforeStaysDenied:
    """Monotonic: a sample of commands denied before this change stays denied."""

    @pytest.mark.parametrize(
        "command",
        [
            "cat kit/bin/late",
            "cat kit/*/late",
            "cat kit/b?n/late",
            "cat kit/[b]in/late",
            f"cat kit/lib/{_PROTECTED}",
            f"cat kit/lib/{_PROTECTED[:-1]}*",
            f"cat kit/lib/[{_PROTECTED[0]}]{_PROTECTED[1:]}",
            "cat kit/[a[:lower:]]in/late",
            "shopt -s nocaseglob; cat kit/B?N/late",
            "shopt -s dotglob; cat kit/*/late2",
            "bash -O dotglob -c 'cat kit/*/late2'",
            "GLOBIGNORE=zz; cat kit/*/late2",
            "shopt -s extglob\ncat kit/@(bin|zz)/late",
            "env BASHOPTS=dotglob bash -c 'cat kit/*/late2'",
        ],
    )
    def test_a_previously_denied_command_is_still_denied(
        self, project: Project, command: str
    ) -> None:
        assert _every_route(command, project.root) == _DENIED_EVERYWHERE
