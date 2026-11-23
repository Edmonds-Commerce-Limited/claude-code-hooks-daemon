"""Globs the guard read more narrowly than bash: brackets, case, extglob words, dot names (N716).

Ledger 00474 N716 and the PR 230 delta review: with ``kit/bin/late`` (and
``kit/.hid/late2``) a link to a protected dummy, bash reads each word below
through the link while the guard allowed it:

- a POSIX class that is not the first member of its bracket
  (``[a[:lower:]]``), and a ``[^`` inside an open bracket read as negation;
- ``shopt -s nocaseglob`` (``kit/B?N/late``);
- extglob words the old regex captured wrongly or not at all (a quote or an
  escape earlier in the word, a quoted alternative, a nested group, a
  ``bash -c`` body);
- dot names matched through ``GLOBIGNORE`` or ``BASHOPTS`` in the environment.

Every case runs in both modes: with bash's defaults certain (an all-off shell
snapshot) and conservative (no snapshot). Synthetic fixtures only: the
protected file is a dummy outside the project, its name assembled.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.indexed_project import index_project
from tests.load_scaling import scaled_cpu_seconds

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as guard_module
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils import link_index, path_exclusion, protected_file_index
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.resolution_failure import IncompleteScanError
from claude_code_hooks_daemon.utils.shell_snapshot import reset_snapshot_cache

_PROTECTED = "id_" + "rsa"
_SHEBANG = "#!/usr/bin/env bash\n"
#: A shell snapshot recording every glob option the guard models as off (bash's defaults).
_SNAPSHOT_ALL_OFF = "shopt -u dotglob\nshopt -u globstar\nshopt -u nocaseglob\n"
_DEFAULTS_CERTAIN = "defaults-certain"
_CONSERVATIVE = "conservative"


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
    (kit / "a" / "b").mkdir(parents=True)
    (kit / "bin" / "late").symlink_to(outside / _PROTECTED)
    (kit / ".hid" / "late2").symlink_to(outside / _PROTECTED)
    (kit / "a" / "b" / "late3").symlink_to(outside / _PROTECTED)
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


_SCANNED = "scanned"
_REFUSED = "refused"


def _scan_outcome(command: str) -> str:
    """Whether the extglob scan of ``command`` finished or refused (its fail-closed answer)."""
    try:
        sfm._extglob_words(command)
    except IncompleteScanError:
        return _REFUSED
    return _SCANNED


_DENIED_EVERYWHERE = (Decision.DENY, Decision.DENY, Decision.DENY)
_ALLOWED_EVERYWHERE = (Decision.ALLOW, Decision.ALLOW, Decision.ALLOW)


class TestBracketExpressions:
    """One bracket reader: negation only first, classes anywhere, ``]`` first literal, escapes."""

    @pytest.mark.parametrize(
        "word",
        [
            "kit/[a[:lower:]]in/late",
            "kit/[![:digit:]]in/late",
            "kit/[^[:digit:]]in/late",
            "kit/bin/[a[:lower:]]ate",
            "k[a[:lower:]]t/bin/late",
            "kit/[a[=b=]]in/late",
            "kit/[]b]in/late",
            "kit/[!]a]in/late",
            "kit/[a\\]b]in/late",
        ],
    )
    def test_a_bracket_bash_reads_through_the_link_is_denied(
        self, project: Project, word: str
    ) -> None:
        assert _every_route(f"cat {word}", project.root) == _DENIED_EVERYWHERE

    def test_a_bracket_read_from_the_links_parent_is_denied(self, project: Project) -> None:
        assert _every_route("cat [a[:lower:]]in/late", project.kit) == _DENIED_EVERYWHERE

    @pytest.mark.parametrize("word", ["kit/[!b]in/late", "kit/[^b]in/late", "kit/[ac]in/late"])
    def test_a_bracket_excluding_the_link_is_allowed(self, project: Project, word: str) -> None:
        assert _every_route(f"cat {word}", project.root) == _ALLOWED_EVERYWHERE

    @pytest.mark.parametrize(
        ("pattern", "name", "matches"),
        [
            ("[a[^z]", "^", True),
            ("[a[^z]", "[", True),
            ("[a[^z]", "z", True),
            ("[a[^z]", "!", False),
            ("[[^z]", "^", True),
            ("[a[:digit:]]", "1", True),
            ("[a[:digit:]]", "a", True),
            ("[![:digit:]]", "x", True),
            ("[]b]", "]", True),
            ("[]b]", "b", True),
            ("[!]a]", "b", True),
            ("[!]a]", "]", False),
            ("[!]a]", "a", False),
            ("[^]]", "a", True),
            ("[^]]", "]", False),
            ("[a-]", "-", True),
            ("[!a-]", "-", False),
            ("[a", "[a", True),
            ("[a", "a", False),
            ("x[!b]y", "xby", False),
            ("x[!b]y", "xay", True),
        ],
    )
    def test_the_component_reader_matches_at_least_what_bash_does(
        self, pattern: str, name: str, matches: bool
    ) -> None:
        """Bash 5.2's own verdicts, each checked with ``shopt -s nullglob; echo <pattern>``."""
        assert sfm._component_spells(pattern, name) is matches

    def test_link_names_reaches_a_caret_inside_an_open_bracket(self) -> None:
        names = sfm.LinkNames(["kit/x^/late"])
        assert names.reaches("x[a[^z]/late")
        assert names.reaches("x[[^z]/late")

    @pytest.mark.parametrize("word", ["[a[:lower:]]in/late", "[![:digit:]]in/late"])
    def test_link_names_reaches_through_a_class_after_the_first_member(self, word: str) -> None:
        """The over-the-cap route (``named is not None``) reads brackets with the same reader."""
        assert sfm.LinkNames(["kit/bin/late"]).reaches(word)

    def test_a_caret_inside_an_open_bracket_reaching_the_link_is_denied(
        self, project: Project
    ) -> None:
        caret = project.kit / "x^"
        caret.mkdir()
        (caret / "late").symlink_to(project.outside / _PROTECTED)
        assert _every_route("cat kit/x[b[^z]/late", project.root) == _DENIED_EVERYWHERE

    @pytest.mark.parametrize(
        ("pattern", "name"), [("[!b]", "B"), ("[!a-z]in", "Xin"), ("[^x]in", "Xin")]
    )
    def test_a_negated_bracket_read_without_case_matches_either_case(
        self, pattern: str, name: str
    ) -> None:
        """Case unknown is BOTH readings: bash's default matches ``B`` against ``[!b]``."""
        assert sfm._component_spells(pattern, name)

    @pytest.mark.parametrize("word", ["kit/[!x]in/late", "kit/[!a-z]in/late", "kit/[^x]in/late"])
    def test_a_negated_bracket_reaching_an_upper_case_link_is_denied(
        self, project: Project, word: str
    ) -> None:
        upper = project.kit / "Xin"
        upper.mkdir()
        (upper / "late").symlink_to(project.outside / _PROTECTED)
        assert _every_route(f"cat {word}", project.root) == _DENIED_EVERYWHERE

    def test_a_negated_bracket_with_case_options_switched_is_denied(self, project: Project) -> None:
        upper = project.kit / "Xin"
        upper.mkdir()
        (upper / "late").symlink_to(project.outside / _PROTECTED)
        command = "source ./opts.sh; cat kit/[!x]in/late"
        assert _every_route(command, project.root) == _DENIED_EVERYWHERE


class TestNocaseglob:
    @pytest.mark.parametrize(
        "command",
        [
            "shopt -s nocaseglob; cat kit/B?N/late",
            "shopt -s nocaseglob; cat kit/bin/L*",
            "shopt -s nocaseglob; cat kit/[B]in/late",
            "shopt -s nocaseglob; cat K*/bin/late",
            "env BASHOPTS=nocaseglob bash -c 'cat kit/B?N/late'",
        ],
    )
    def test_a_case_blind_glob_reaching_the_link_is_denied(
        self, project: Project, command: str
    ) -> None:
        assert _every_route(command, project.root) == _DENIED_EVERYWHERE

    def test_a_case_blind_glob_naming_a_protected_file_directly_is_denied(
        self, project: Project
    ) -> None:
        (project.kit / "lib" / _PROTECTED).write_bytes(b"DUMMY\n")
        index_project(project.root, SecretFileGuardHandler()._patterns())
        command = f"shopt -s nocaseglob; cat kit/lib/{_PROTECTED.upper()[:-1]}*"
        assert _every_route(command, project.root) == _DENIED_EVERYWHERE

    def test_a_differently_cased_glob_is_allowed_when_bash_defaults_are_certain(
        self, project: Project
    ) -> None:
        if not project.defaults_certain:
            pytest.skip("only bash's certain defaults read case exactly")
        assert _every_route("cat kit/B?N/late", project.root) == _ALLOWED_EVERYWHERE


class TestExtglobWords:
    @pytest.mark.parametrize(
        "word",
        [
            '"k"it/@(bin|zz)/late',
            "k\\it/@(bin|zz)/late",
            'kit/@("bin"|zz)/late',
            "kit/@(b@(i)n)/late",
            "kit/*(@(b)in)/late",
            "kit/@(zz|b[i]n)/late",
            "kit/@(bin)/[l]ate",
            "kit/@(b)[i]n/late",
        ],
    )
    def test_an_extglob_word_reaching_the_link_is_denied(self, project: Project, word: str) -> None:
        command = f"shopt -s extglob\ncat {word}"
        assert _every_route(command, project.root) == _DENIED_EVERYWHERE

    def test_an_extglob_in_a_bash_c_body_is_denied(self, project: Project) -> None:
        command = "env BASHOPTS=extglob bash -c 'cat kit/@(b@(i)n)/late'"
        assert _every_route(command, project.root) == _DENIED_EVERYWHERE

    def test_an_extglob_in_a_double_quoted_body_is_denied(self, project: Project) -> None:
        command = 'bash -O extglob -c "cat \\"k\\"it/@(bin|zz)/late"'
        assert _every_route(command, project.root) == _DENIED_EVERYWHERE

    @pytest.mark.parametrize("word", ["kit/@(lib)/notes.txt", "kit/@(lib|zz)/notes.txt"])
    def test_an_extglob_reaching_no_link_is_allowed(self, project: Project, word: str) -> None:
        assert _every_route(f"shopt -s extglob\ncat {word}", project.root) == _ALLOWED_EVERYWHERE

    @pytest.mark.parametrize(
        "command",
        [
            "shopt -s extglob\n: # @(\ncat kit/@(bin|zz)/late",
            "shopt -s extglob\ncat <<'EOF'\n@(\nEOF\ncat kit/@(bin|zz)/late",
            "echo '@(' ; cat kit/@(bin|zz)/late",
        ],
    )
    def test_an_unclosed_group_earlier_does_not_hide_a_later_word(
        self, project: Project, command: str
    ) -> None:
        assert "kit/@(bin|zz)/late" in sfm._extglob_words(command)
        assert _every_route(command, project.root) == _DENIED_EVERYWHERE

    @pytest.mark.perf_sweep
    @pytest.mark.parametrize(
        "command",
        ["$(" * 20000 + "x", "@(" * 20000 + "x", "'$(" * 5000 + "x", '"$(' * 5000, "(" * 40000],
    )
    def test_a_hostile_nesting_is_scanned_quickly_or_refused(self, command: str) -> None:
        started = time.process_time()
        outcome = _scan_outcome(command)
        assert outcome in (_SCANNED, _REFUSED)
        assert time.process_time() - started < scaled_cpu_seconds(1.0)

    def test_nesting_past_the_scan_budget_is_refused(self) -> None:
        """A refusal is an IncompleteScanError, which the guard denies (fail closed)."""
        assert _scan_outcome("$(" * 20000 + "@(x)") == _REFUSED

    def test_ordinary_nesting_is_scanned(self) -> None:
        command = 'bash -c "echo $(cat $(ls kit/@(bin)/late))"'
        assert _scan_outcome(command) == _SCANNED
        assert "kit/@(bin)/late" in sfm._extglob_words(command)

    def test_the_whole_word_is_captured(self) -> None:
        words = sfm._extglob_words('cat "k"it/@(bin|zz)/late k\\it/@(b@(i)n)/x; ls @("a"|b)')
        assert words == ["kit/@(bin|zz)/late", "kit/@(b@(i)n)/x", "@(a|b)"]


class TestDotNames:
    @pytest.mark.parametrize(
        "command",
        [
            "GLOBIGNORE=zz; cat kit/*/late2",
            "env BASHOPTS=dotglob bash -c 'cat kit/*/late2'",
            "env BASHOPTS=globstar bash -c 'cat kit/**/late3'",
        ],
    )
    def test_dot_names_or_globstar_switched_on_without_shopt_are_denied(
        self, project: Project, command: str
    ) -> None:
        assert _every_route(command, project.root) == _DENIED_EVERYWHERE

    def test_a_plain_wildcard_skips_dot_names_when_bash_defaults_are_certain(
        self, project: Project
    ) -> None:
        if not project.defaults_certain:
            pytest.skip("only bash's certain defaults skip dot names")
        assert _every_route("cat kit/*/late2", project.root) == _ALLOWED_EVERYWHERE
