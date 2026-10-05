"""Glob expansion bases are the project root and the payload cwd (issues #64, #66).

The live daemon's own process cwd is ``/``. It used to be added as a glob base,
so an ordinary command whose text held a ``**`` or multi-wildcard token was
refused with TooManyToEnumerateError (a deny) at the filesystem root. Unit
tests missed it because pytest's process cwd is the project root. Every test
here forces the process cwd to ``/``.
"""

from __future__ import annotations

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

_QUARANTINE_GLOBS = ("*-opus-security-DETAIL*", "*-opus-security-DETAIL.md")

# A default protected name, assembled so this file does not itself name it.
_PROTECTED = "." + "vault" + "-pass"

#: The #66 command: a double-quoted python program whose text holds a
#: two-wildcard path and a dict-literal residue.
_ISSUE_66_COMMAND = "python3 -c \"print('untracked/scratch/repro/*/data.json', {}.get('php','?'))\""


@pytest.fixture(autouse=True)
def _daemon_like_process(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The daemon process sits at ``/``; reset the shared data layer around it."""
    reset_data_layer()
    monkeypatch.chdir("/")
    yield
    reset_data_layer()


def _through_chain(handler: Any, command: str, cwd: Path) -> tuple[Decision, str]:
    chain = HandlerChain()
    chain.add(handler)
    hook_input = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }
    result = chain.execute(hook_input, strict_mode=False)
    return result.result.decision, result.result.reason or ""


class TestQuarantineGuardUsesPayloadCwd:
    """Issue #64."""

    @pytest.mark.parametrize(
        "command",
        [
            "grep -rn !a/** docs",
            "grep -rn --exclude-dir=nothing/** needle untracked/scratch",
            "cat !a/*/*/x",
        ],
    )
    def test_an_unquoted_glob_over_an_absent_prefix_is_allowed(
        self, command: str, tmp_path: Path
    ) -> None:
        (tmp_path / "docs").mkdir()
        decision, reason = _through_chain(QuarantineArtefactReadGuardHandler(), command, tmp_path)
        assert decision != Decision.DENY, reason

    def test_strict_matcher_never_raises_at_process_cwd_root(self, tmp_path: Path) -> None:
        assert (
            sfm.find_protected_mention_strict(
                "grep -rn !a/** docs", _QUARANTINE_GLOBS, cwd=str(tmp_path)
            )
            is None
        )

    def test_an_unquoted_glob_matching_an_artefact_in_the_payload_cwd_is_denied(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "report-opus-security-DETAIL.md").write_text("x")
        decision, _ = _through_chain(
            QuarantineArtefactReadGuardHandler(), "cat *-opus-security-DETAIL*", tmp_path
        )
        assert decision == Decision.DENY

    def test_a_recursive_glob_reaching_an_artefact_below_the_payload_cwd_is_denied(
        self, tmp_path: Path
    ) -> None:
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        (nested / "x-opus-security-DETAIL.md").write_text("x")
        decision, _ = _through_chain(
            QuarantineArtefactReadGuardHandler(), "cat a/**/*-opus-security-DETAIL*", tmp_path
        )
        assert decision == Decision.DENY


class TestSecretGuardUsesPayloadCwd:
    """Issue #66."""

    def test_the_issue_66_command_is_allowed(self, tmp_path: Path) -> None:
        decision, reason = _through_chain(SecretFileGuardHandler(), _ISSUE_66_COMMAND, tmp_path)
        assert decision != Decision.DENY, reason

    def test_an_unquoted_glob_matching_a_protected_file_in_the_payload_cwd_is_denied(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / _PROTECTED).write_text("x")
        decision, _ = _through_chain(SecretFileGuardHandler(), f"cat {_PROTECTED[:-1]}*", tmp_path)
        assert decision == Decision.DENY

    def test_an_unquoted_glob_reaching_a_protected_file_below_the_cwd_is_denied(
        self, tmp_path: Path
    ) -> None:
        nested = tmp_path / "conf" / "prod"
        nested.mkdir(parents=True)
        (nested / _PROTECTED).write_text("x")
        decision, _ = _through_chain(
            SecretFileGuardHandler(), f"cat conf/*/{_PROTECTED[:-1]}*", tmp_path
        )
        assert decision == Decision.DENY
