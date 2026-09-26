"""A shell reserved word in front of a command does not change what runs (Plan 00422 N25).

`do`, `then`, `else`, `elif`, `if`, `while`, `until`, `!`, `{` and `time` can
stand in front of a command, and the command still runs. Splitting
`for i in 1; do git commit -m x; done` on `;` yields the segment
` do git commit -m x`, whose first word is `do`. A site that takes the first
word of a segment as the command, or anchors a pattern at the segment start,
then judges `do` instead of `git`.

`pipe_blocker` was the reported instance. The audit found the same shape in
the sites below; each one gave a different verdict for a command behind a
reserved word than for the same command alone. Some were bypasses (a guard or
advisory stopped firing), some were false positives (an exemption was
withheld). Every test here pins one site to the same verdict with and without
the prefix. `utils/process_probe.py` already handled this through
`_COMMAND_POSITION_MARKERS` and is the reference reading.

The shared primitive is `command_evasion.RESERVED_WORD_PREFIX` (for a pattern
anchored at a segment start) and `command_evasion.strip_reserved_word_prefix`
(for a site that reads the first word). The declared-invariant-pairs Detector
asserts each site keeps using them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.handlers.pre_tool_use.issue_filing_gate import (
    IssueFilingGateHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.project_containment import (
    ProjectContainmentHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.reference_repo_freshness import (
    ReferenceRepoFreshnessHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker import SedBlockerHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate import (
    _is_git_commit_command,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.verification_result_gate import (
    VerificationResultGateHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.worktree_file_copy import (
    WorktreeFileCopyHandler,
)
from claude_code_hooks_daemon.handlers.utils.bash_file_writes import bash_file_writes
from claude_code_hooks_daemon.issue_report.upstream import UPSTREAM_REPO_SLUG
from claude_code_hooks_daemon.utils.bash_flags import detect_safe_mode_flags, split_statements
from claude_code_hooks_daemon.utils.command_evasion import (
    compile_command_name_pattern,
    strip_reserved_word_prefix,
)
from claude_code_hooks_daemon.utils.merge_scope import is_git_merge_pull_rebase_command
from claude_code_hooks_daemon.utils.shell_segmentation import (
    strip_message_bodies,
    strip_quoted_heredoc_bodies,
)

# One spelling per reserved word, each wrapping `{cmd}` the way bash accepts it.
_WRAPPINGS = (
    "for i in 1; do {cmd}; done",
    "if true; then {cmd}; fi",
    "if false; then :; else {cmd}; fi",
    "if false; then :; elif {cmd}; then :; fi",
    "if {cmd}; then :; fi",
    "while {cmd}; do break; done",
    "until {cmd}; do :; done",
    "! {cmd}",
    "{{ {cmd}; }}",
    "time {cmd}",
    "time -p {cmd}",
)


def _wrapped(command: str) -> list[str]:
    return [wrapping.format(cmd=command) for wrapping in _WRAPPINGS]


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": ToolName.BASH, "tool_input": {"command": command}}


class TestTheSharedPrimitive:
    @pytest.mark.parametrize(
        ("segment", "expected"),
        [
            (" do git commit -m x", "git commit -m x"),
            ("then ! grep x f", "grep x f"),
            ("{ time -p pytest", "pytest"),
            ("  elif   make", "make"),
            ("git commit", "git commit"),
            ("done", "done"),
            ("dog food", "dog food"),
            ('"do" x', '"do" x'),
            ("timeout 5 make", "timeout 5 make"),
        ],
    )
    def test_strip_reserved_word_prefix(self, segment: str, expected: str) -> None:
        assert strip_reserved_word_prefix(segment) == expected

    @pytest.mark.parametrize("prefix", ["do ", "then ", "! ", "{ ", "time ", "if ", "while "])
    def test_compile_command_name_pattern_sees_through_the_prefix(self, prefix: str) -> None:
        """Covers every caller: issue_filing_gate, quarantine_artefact_read_guard,
        command_hints and verification_result_gate's non-git signatures."""
        pattern = compile_command_name_pattern("gh issue create")
        assert pattern.search(f"{prefix}gh issue create --title t") is not None

    def test_compile_command_name_pattern_still_needs_the_name(self) -> None:
        pattern = compile_command_name_pattern("gh issue create")
        assert pattern.search("do echo gh issue create") is None


class TestGuardsAndAdvisoriesStillFire:
    """Each of these missed the command behind a reserved word (a bypass)."""

    @pytest.mark.parametrize("command", _wrapped("git commit -m x"))
    def test_staged_lint_gate_sees_the_commit(self, command: str) -> None:
        assert _is_git_commit_command(command) is True

    @pytest.mark.parametrize("command", _wrapped("git pull"))
    def test_merge_scope_sees_the_pull(self, command: str) -> None:
        assert is_git_merge_pull_rebase_command(command) is True

    @pytest.mark.parametrize(
        "command",
        [
            "if true; then pytest; git commit -m x; fi",
            "pytest; for i in 1; do git push; done",
            "time pytest; git commit -m x",
        ],
    )
    def test_verification_result_gate_sees_both_ends(self, command: str) -> None:
        assert VerificationResultGateHandler()._find(command) is not None

    @pytest.mark.parametrize(
        "command", _wrapped(f"gh issue create --repo {UPSTREAM_REPO_SLUG} --body x")
    )
    def test_issue_filing_gate_sees_the_filing(self, command: str) -> None:
        assert IssueFilingGateHandler._filing_segments(command) != []

    @pytest.mark.parametrize(
        "command",
        [
            "grep -l x f; if true; then sed s/a/b/w out f; fi",
            "grep -l x f; for i in 1; do sed s/a/b/ f > g; done",
            "echo hi; time sed s/a/b/w out f",
        ],
    )
    def test_sed_blocker_sees_sed_at_the_head(self, command: str) -> None:
        assert SedBlockerHandler().matches(_bash(command)) is True

    @pytest.mark.parametrize(
        "command",
        [
            "for f in 1; do cp untracked/worktrees/wt1/src/x.py src/x.py; done",
            "if true; then mv untracked/worktrees/wt1/src/x.py src/x.py; fi",
            "time cp untracked/worktrees/wt1/src/x.py src/x.py",
        ],
    )
    def test_worktree_file_copy_sees_the_relocation(self, command: str) -> None:
        assert WorktreeFileCopyHandler().matches(_bash(command)) is True

    @pytest.mark.parametrize("command", _wrapped("mkdir /opt/n25-probe"))
    def test_project_containment_sees_the_destination(self, command: str) -> None:
        assert "/opt/n25-probe" in ProjectContainmentHandler()._destination_targets(command)

    @pytest.mark.parametrize("command", _wrapped("python3 -c \"open('J/x.md','w')\""))
    def test_bash_file_writes_sees_the_program_write(self, command: str) -> None:
        writes = bash_file_writes(command, None, lambda _path: pytest.fail("no read expected"))
        assert "J/x.md" in writes.destinations

    @pytest.mark.parametrize("command", ["cd J && if true; then cd K; fi", "do cd K"])
    def test_bash_file_writes_sees_the_directory_change(self, command: str) -> None:
        writes = bash_file_writes(command, None, lambda _path: pytest.fail("no read expected"))
        assert "K" in writes.directories


class TestExemptionsAreNotWithheld:
    """Each of these judged the reserved word and withheld an exemption (a false positive)."""

    def test_a_heredoc_fed_to_cat_in_a_loop_body_is_blanked(self) -> None:
        command = "for i in 1; do cat > n.md <<'EOF'\nfoo | tail -1\nEOF\ndone"
        assert "tail" not in strip_quoted_heredoc_bodies(command)

    def test_a_commit_message_inside_an_if_is_blanked(self) -> None:
        command = 'if true; then git commit -m "never run git reset --hard"; fi'
        assert "reset" not in strip_message_bodies(command)

    @pytest.mark.parametrize(
        "command",
        ["{ set -euo pipefail; a; b; }", "time set -euo pipefail; a", "! set -euo pipefail; a"],
    )
    def test_bash_flags_reads_an_unconditional_set(self, command: str) -> None:
        flags = detect_safe_mode_flags(split_statements(command))
        assert {"errexit", "pipefail", "nounset"} <= flags

    @pytest.mark.parametrize(
        "command",
        [
            "( set -e ); a",
            "if false; then set -e; fi; a",
            "for i in; do set -e; done; a",
            "if true; then :; else set -e; fi; a",
        ],
    )
    def test_a_conditional_or_subshell_set_does_not_count(self, command: str) -> None:
        """A subshell's `set` ends with it, and one behind `then`/`do`/`else` may
        never run, so crediting either would stand the safety checks down."""
        assert detect_safe_mode_flags(split_statements(command)) == frozenset()


class TestReferenceRepoFreshnessReadsTheRealHead:
    @pytest.fixture
    def handler(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
        handler = ReferenceRepoFreshnessHandler()
        monkeypatch.setattr(handler, "_roots", lambda _root: [tmp_path / "repo"])
        return handler

    @pytest.mark.parametrize(
        "command",
        ["for r in 1; do git -C repo pull; done", "if true; then cd repo; fi"],
    )
    def test_the_remedy_and_a_bare_cd_are_not_reads(
        self, handler: Any, tmp_path: Path, command: str
    ) -> None:
        assert handler._governed_reads(command, tmp_path) == []

    @pytest.mark.parametrize(
        "command",
        ["cd repo && if true; then rg x; fi", "cd repo && time rg x"],
    )
    def test_a_read_from_inside_the_repo_is_seen(
        self, handler: Any, tmp_path: Path, command: str
    ) -> None:
        assert handler._governed_reads(command, tmp_path) == [tmp_path / "repo"]
