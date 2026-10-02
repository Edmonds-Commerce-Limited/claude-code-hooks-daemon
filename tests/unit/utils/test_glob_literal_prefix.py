"""An absolute glob under an existing literal prefix is judged, not refused (GitHub #68).

``cat $F/*/*`` names two wildcard segments, but ``$F`` is a literal prefix that
already narrows the walk to one directory. The filesystem-root refusal belongs
to a walk whose effective base is still the root. Every test forces the process
cwd to ``/``, as the live daemon's is.
"""

from __future__ import annotations

import errno
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.quarantine_artefact_read_guard import (
    QuarantineArtefactReadGuardHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils import shell_expansion

_ARTEFACT = "report-opus-security-DETAIL.md"

#: A shipped default protected stem, assembled so this file does not name it.
_STEM = "sec" + "ret"
_PROTECTED_FILE = f"prod.{_STEM}.txt"

#: A both-edges protected glob, so a hit can only come from the filesystem.
_BOTH_EDGES = (f"*.{_STEM}*",)

#: The lines of the issue's route-1 table, each written into a shell script.
_SCRIPT_LINES = (
    'for f in "${D}/before-${e}-"*.txt; do :; done',
    'ls "${D}/before-${e}.txt"',
    'out="${RUN}/compose-${env}.txt"',
    'echo "${D}/report-${e}.txt"',
    'echo "[FAIL] ${env}/${host}: message"',
    'out="${RUN}/after-${env}.txt"',
    'find "${D}" -name "before-${e}-?*.txt"',
)


@pytest.fixture(autouse=True)
def _daemon_like_process(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The daemon process sits at ``/``; reset the shared data layer around it."""
    reset_data_layer()
    monkeypatch.chdir("/")
    yield
    reset_data_layer()


@pytest.fixture
def fixture_dir(tmp_path: Path) -> Path:
    """Two readable subdirectories each holding ``x``, and one to lock."""
    for sub in ("a", "b"):
        (tmp_path / sub).mkdir()
        (tmp_path / sub / "x").write_text("x\n")
    (tmp_path / "locked").mkdir()
    return tmp_path


def _under_root(path: Path, tail: str) -> str:
    """``path/tail`` as the pattern a walk rooted at ``/`` is given."""
    return f"{str(path).lstrip('/')}/{tail}"


def _through_chain(handler: Any, tool_input: dict[str, Any], tool: str, cwd: Path | None) -> Any:
    chain = HandlerChain()
    chain.add(handler)
    hook_input: dict[str, Any] = {"tool_name": tool, "tool_input": tool_input}
    if cwd is not None:
        hook_input["cwd"] = str(cwd)
    return chain.execute(hook_input, strict_mode=False).result


def _bash(handler: Any, command: str, cwd: Path) -> tuple[Decision, str]:
    result = _through_chain(handler, {"command": command}, "Bash", cwd)
    return result.decision, result.reason or ""


class TestWalkRebasedOntoTheLiteralPrefix:
    """``bounded_recursive_glob`` at the root, under a prefix that exists."""

    def test_two_wildcards_under_an_existing_prefix_are_walked(self, fixture_dir: Path) -> None:
        pattern = _under_root(fixture_dir, "*/*")
        matches = sorted(shell_expansion.bounded_recursive_glob(Path("/"), pattern))
        assert matches == [fixture_dir / "a" / "x", fixture_dir / "b" / "x"]

    def test_many_wildcards_under_an_existing_prefix_are_walked(self, fixture_dir: Path) -> None:
        deep = fixture_dir / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "y").write_text("y\n")
        pattern = _under_root(fixture_dir, "*/*/*/*")
        assert list(shell_expansion.bounded_recursive_glob(Path("/"), pattern)) == [deep / "y"]

    def test_a_recursive_walk_under_a_prefix_is_still_capped_by_entries(
        self, fixture_dir: Path
    ) -> None:
        for index in range(30):
            (fixture_dir / f"extra-{index}").mkdir()
        with pytest.raises(shell_expansion.TooManyToEnumerateError):
            list(
                shell_expansion.bounded_recursive_glob(
                    Path("/"), _under_root(fixture_dir, "**/nothing"), max_entries_visited=10
                )
            )

    def test_a_recursive_walk_under_a_prefix_finds_a_match(self, fixture_dir: Path) -> None:
        pattern = _under_root(fixture_dir, "**/x")
        found = sorted(shell_expansion.bounded_recursive_glob(Path("/"), pattern))
        assert found == [fixture_dir / "a" / "x", fixture_dir / "b" / "x"]

    def test_a_deadline_still_bounds_a_walk_under_a_prefix(self, fixture_dir: Path) -> None:
        with pytest.raises(TimeoutError):
            list(
                shell_expansion.bounded_recursive_glob(
                    Path("/"), _under_root(fixture_dir, "*/*"), deadline=0.0
                )
            )

    def test_a_prefix_that_is_a_file_matches_nothing(self, fixture_dir: Path) -> None:
        pattern = _under_root(fixture_dir, "a/x/*/*")
        assert list(shell_expansion.bounded_recursive_glob(Path("/"), pattern)) == []

    def test_a_prefix_through_dotdot_is_walked_from_where_it_lands(self, fixture_dir: Path) -> None:
        pattern = _under_root(fixture_dir, "a/../*/*")
        matches = sorted(shell_expansion.bounded_recursive_glob(Path("/"), pattern))
        assert matches == [
            fixture_dir / "a" / ".." / "a" / "x",
            fixture_dir / "a" / ".." / "b" / "x",
        ]

    def test_a_prefix_that_resolves_back_to_the_root_narrows_nothing(self) -> None:
        with pytest.raises(shell_expansion.TooManyToEnumerateError):
            list(shell_expansion.bounded_recursive_glob(Path("/"), "usr/../*/*"))

    def test_a_prefix_through_a_symlink_to_the_root_narrows_nothing(
        self, fixture_dir: Path
    ) -> None:
        (fixture_dir / "rootlink").symlink_to("/")
        with pytest.raises(shell_expansion.TooManyToEnumerateError):
            list(
                shell_expansion.bounded_recursive_glob(
                    Path("/"), _under_root(fixture_dir, "rootlink/*/*")
                )
            )

    @pytest.mark.parametrize("pattern", ["*/*", "**", "*/*/*", "**/x"])
    def test_a_root_walk_with_no_prefix_is_still_refused(self, pattern: str) -> None:
        with pytest.raises(shell_expansion.TooManyToEnumerateError):
            list(shell_expansion.bounded_recursive_glob(Path("/"), pattern))


class TestGuardsAllowAGlobUnderAPrefix:
    """The reproduction of GitHub #68, through the whole guard chain."""

    @pytest.mark.parametrize(
        "template",
        [
            "cat {F}/*/*",
            "cat {F}/*/*/*",
            'for x in a b; do cat "$x"{F}/*/*; done',
        ],
    )
    def test_quarantine_guard_allows_it(self, template: str, fixture_dir: Path) -> None:
        command = template.replace("{F}", str(fixture_dir))
        decision, reason = _bash(QuarantineArtefactReadGuardHandler(), command, fixture_dir)
        assert decision != Decision.DENY, reason

    @pytest.mark.parametrize(
        "template",
        [
            "ls {F}/*/*-release",
            'for x in a b; do ls "$x"{F}/*/*-release; done',
        ],
    )
    def test_secret_guard_allows_it(self, template: str, fixture_dir: Path) -> None:
        command = template.replace("{F}", str(fixture_dir))
        decision, reason = _bash(SecretFileGuardHandler(), command, fixture_dir)
        assert decision != Decision.DENY, reason


class TestGuardsStillDenyWhatTheGlobReaches:
    """A protected file the glob really reaches is denied under any prefix."""

    def test_quarantine_guard_denies_an_artefact_one_level_down(self, fixture_dir: Path) -> None:
        (fixture_dir / "a" / _ARTEFACT).write_text("x")
        decision, _ = _bash(
            QuarantineArtefactReadGuardHandler(), f"cat {fixture_dir}/*/*", fixture_dir
        )
        assert decision == Decision.DENY

    def test_quarantine_guard_denies_an_artefact_two_levels_down(self, fixture_dir: Path) -> None:
        nested = fixture_dir / "a" / "deeper"
        nested.mkdir()
        (nested / _ARTEFACT).write_text("x")
        decision, _ = _bash(
            QuarantineArtefactReadGuardHandler(), f"cat {fixture_dir}/*/*/*", fixture_dir
        )
        assert decision == Decision.DENY

    def test_quarantine_guard_denies_through_an_unresolved_variable_prefix(
        self, fixture_dir: Path
    ) -> None:
        """``"$x"`` may be empty, which leaves the absolute path the shell reaches."""
        (fixture_dir / "a" / _ARTEFACT).write_text("x")
        command = f'for x in a b; do cat "$x"{fixture_dir}/*/*; done'
        decision, _ = _bash(QuarantineArtefactReadGuardHandler(), command, fixture_dir)
        assert decision == Decision.DENY

    def test_quarantine_guard_denies_the_variable_as_a_wildcard_under_the_cwd(
        self, fixture_dir: Path
    ) -> None:
        """Whatever ``$x`` holds, ``"$x"a/*`` is relative to the payload cwd."""
        (fixture_dir / "a" / _ARTEFACT).write_text("x")
        decision, _ = _bash(QuarantineArtefactReadGuardHandler(), 'cat "$x"a/*', fixture_dir)
        assert decision == Decision.DENY

    def test_secret_guard_expansion_finds_a_protected_file_under_the_prefix(
        self, fixture_dir: Path
    ) -> None:
        (fixture_dir / "a" / _PROTECTED_FILE).write_text("x")
        found = sfm._expand_glob_token(
            f"{fixture_dir}/*/*.s?{_STEM[2:]}*", _BOTH_EDGES, None, cwd=str(fixture_dir)
        )
        assert found == _BOTH_EDGES[0]

    def test_secret_guard_denies_a_protected_file_under_the_prefix(self, fixture_dir: Path) -> None:
        (fixture_dir / "a" / _PROTECTED_FILE).write_text("x")
        decision, _ = _bash(SecretFileGuardHandler(), f"ls {fixture_dir}/*/*-{_STEM}*", fixture_dir)
        assert decision == Decision.DENY

    @pytest.mark.parametrize("command", ["cat /*/*", "cat /**", "cat /*/*/*"])
    def test_a_glob_at_the_real_root_is_still_denied(self, command: str, fixture_dir: Path) -> None:
        decision, _ = _bash(QuarantineArtefactReadGuardHandler(), command, fixture_dir)
        assert decision == Decision.DENY


class TestWrittenScriptsAreNotExpandedFromTheProcessCwd:
    """Route 1 of the issue's comment: the process cwd (``/``) is never a base."""

    @pytest.mark.parametrize("name", ["step.bash", "step.sh", "step"])
    @pytest.mark.parametrize("line", _SCRIPT_LINES)
    @pytest.mark.parametrize("tool", ["Write", "Edit"])
    @pytest.mark.parametrize("with_cwd", [True, False])
    def test_a_script_line_is_allowed(
        self, name: str, line: str, tool: str, with_cwd: bool, tmp_path: Path
    ) -> None:
        text = f"#!/bin/bash\n{line}\n"
        tool_input: dict[str, Any] = {"file_path": str(tmp_path / name)}
        if tool == "Write":
            tool_input["content"] = text
        else:
            tool_input.update(old_string="a", new_string=text)
        result = _through_chain(
            SecretFileGuardHandler(), tool_input, tool, tmp_path if with_cwd else None
        )
        assert result.decision != Decision.DENY, result.reason

    @pytest.mark.parametrize("line", _SCRIPT_LINES)
    def test_the_same_line_as_a_bash_command_is_allowed(self, line: str, tmp_path: Path) -> None:
        decision, reason = _bash(SecretFileGuardHandler(), line, tmp_path)
        assert decision != Decision.DENY, reason


class TestQuotedRegexInAReadOnlyCommand:
    """Route 2 of the issue's comment: a quoted regular expression is text."""

    _COMMAND = "grep -o -E 'example.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+' notes.txt"

    def test_the_quarantine_guard_allows_it(self, tmp_path: Path) -> None:
        decision, reason = _bash(QuarantineArtefactReadGuardHandler(), self._COMMAND, tmp_path)
        assert decision != Decision.DENY, reason

    def test_the_secret_guard_allows_it(self, tmp_path: Path) -> None:
        decision, reason = _bash(SecretFileGuardHandler(), self._COMMAND, tmp_path)
        assert decision != Decision.DENY, reason


def _deny_lookups_under(monkeypatch: pytest.MonkeyPatch, locked: Path) -> None:
    """Make every ``stat``/``lstat`` of a path under ``locked`` fail with EACCES.

    This container runs as root, which reads a mode-000 directory, so the
    failure is injected where the walker makes its lookups.
    """

    def _guarded(real: Any) -> Any:
        def _lookup(self: Path, *args: Any, **kwargs: Any) -> Any:
            if locked in self.parents:
                raise PermissionError(errno.EACCES, "Permission denied", str(self))
            return real(self, *args, **kwargs)

        return _lookup

    monkeypatch.setattr(Path, "stat", _guarded(Path.stat))
    monkeypatch.setattr(Path, "lstat", _guarded(Path.lstat))


def _deny_listing(monkeypatch: pytest.MonkeyPatch, locked: Path) -> None:
    """Make ``os.scandir`` of ``locked`` fail with EACCES."""
    real_scandir = os.scandir

    def _scandir(path: Any) -> Any:
        if Path(path) == locked:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return real_scandir(path)

    monkeypatch.setattr("claude_code_hooks_daemon.utils.shell_expansion.os.scandir", _scandir)


class TestAnUnreadableSiblingDirectory:
    """A named path inside a directory that cannot be searched is judged by name."""

    def test_the_walk_yields_the_fully_named_candidate_instead_of_an_error(
        self, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _deny_lookups_under(monkeypatch, fixture_dir / "locked")
        errors: list[OSError] = []
        matches = sorted(
            shell_expansion.bounded_recursive_glob(
                Path("/"), _under_root(fixture_dir, "*/x"), errors=errors
            )
        )
        assert errors == []
        assert matches == [
            fixture_dir / "a" / "x",
            fixture_dir / "b" / "x",
            fixture_dir / "locked" / "x",
        ]

    def test_a_literal_tail_below_the_unreadable_directory_is_also_named(
        self, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _deny_lookups_under(monkeypatch, fixture_dir / "locked")
        errors: list[OSError] = []
        matches = list(
            shell_expansion.bounded_recursive_glob(
                Path("/"), _under_root(fixture_dir, "l*/sub/x"), errors=errors
            )
        )
        assert errors == []
        assert matches == [fixture_dir / "locked" / "sub" / "x"]

    @pytest.mark.parametrize("guard", [QuarantineArtefactReadGuardHandler, SecretFileGuardHandler])
    def test_a_command_naming_an_ordinary_file_is_allowed(
        self, guard: Any, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _deny_lookups_under(monkeypatch, fixture_dir / "locked")
        decision, reason = _bash(guard(), f"cat {fixture_dir}/*/x", fixture_dir)
        assert decision != Decision.DENY, reason

    def test_a_protected_name_in_the_unreadable_directory_is_still_denied(
        self, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _deny_lookups_under(monkeypatch, fixture_dir / "locked")
        found = sfm._expand_glob_token(
            f"{fixture_dir}/*/{_ARTEFACT}", ("*-opus-security-DETAIL.md",), None
        )
        assert found == "*-opus-security-DETAIL.md"

    def test_a_readable_protected_file_beside_the_unreadable_one_is_still_denied(
        self, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (fixture_dir / "a" / _ARTEFACT).write_text("x")
        _deny_lookups_under(monkeypatch, fixture_dir / "locked")
        decision, _ = _bash(
            QuarantineArtefactReadGuardHandler(),
            f"cat {fixture_dir}/a/{_ARTEFACT[:-3]}*",
            fixture_dir,
        )
        assert decision == Decision.DENY

    def test_a_directory_that_cannot_be_listed_still_fails_closed(
        self, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Its entries' names are unknown, so a protected one cannot be ruled out."""
        _deny_listing(monkeypatch, fixture_dir / "locked")
        decision, _ = _bash(
            QuarantineArtefactReadGuardHandler(), f"cat {fixture_dir}/*/*", fixture_dir
        )
        assert decision == Decision.DENY

    def test_a_path_the_word_names_outright_stays_an_error(
        self, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No wildcard chose that directory, so there is no sibling to skip past."""
        _deny_lookups_under(monkeypatch, fixture_dir / "locked")
        errors: list[OSError] = []
        matches = list(
            shell_expansion.bounded_recursive_glob(
                Path("/"), _under_root(fixture_dir, "locked/x"), errors=errors
            )
        )
        assert matches == []
        assert [error.errno for error in errors] == [errno.EACCES]

    def test_a_lookup_failing_for_another_reason_still_fails_closed(
        self, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_lstat = Path.lstat

        def _lstat(self: Path, *args: Any, **kwargs: Any) -> Any:
            if self == fixture_dir / "locked" / "x":
                raise OSError(errno.EIO, "Input/output error", str(self))
            return real_lstat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "lstat", _lstat)
        errors: list[OSError] = []
        list(
            shell_expansion.bounded_recursive_glob(
                Path("/"), _under_root(fixture_dir, "*/x"), errors=errors
            )
        )
        assert [error.errno for error in errors] == [errno.EIO]
