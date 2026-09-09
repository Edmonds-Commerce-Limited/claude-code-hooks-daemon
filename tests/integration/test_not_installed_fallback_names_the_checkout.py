"""The "daemon not installed" answer must say WHICH checkout it is answering for.

A worktree with no `.claude/hooks-daemon.env` never enters self-install mode,
so every wrapper in it returns the not-installed fallback. Nothing in that
answer named a directory, and the Stop-family form of it is
`decision: block` — the same shape a WORKING stop gate returns. So the session
looked protected, a smoke probe passed for the wrong reason, and the only clue
that an entire checkout's handlers were inert was absent (Plan 00364 Task
5.1).

Naming the checkout makes the two readings distinguishable at a glance: an
answer about `/workspace` arriving in a worktree is visibly wrong, where
"Hooks daemon not installed" alone was not.

Both encoders are covered. `emit_hook_error` prefers `jq` and falls back to
`python3`, and a message that appears in only one of them is missing exactly
where the host is unusual.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INIT_SH = _REPO_ROOT / ".claude" / "init.sh"
_RUN_TIMEOUT_SECONDS = 30

#: Tools init.sh may invoke at source time, plus the fallback's own encoder.
_ESSENTIAL_TOOLS = (
    "sh",
    "bash",
    "env",
    "python3",
    "cat",
    "dirname",
    "basename",
    "tr",
    "hostname",
    "stat",
    "date",
    "mkdir",
    "touch",
    "chmod",
    "rm",
    "ls",
    "grep",
    "sed",
    "awk",
    "uname",
    "head",
    "cut",
    "sort",
    "wc",
)


def _curated_bin(tmp_path: Path, *, with_jq: bool) -> Path:
    bindir = tmp_path / ("bin-with-jq" if with_jq else "bin-without-jq")
    bindir.mkdir()
    tools = (*_ESSENTIAL_TOOLS, "jq") if with_jq else _ESSENTIAL_TOOLS
    for tool in tools:
        real = shutil.which(tool)
        if real is not None:
            (bindir / tool).symlink_to(real)
    return bindir


def _sandbox_checkout(tmp_path: Path) -> Path:
    """A throwaway checkout that sources a copy of the real init.sh."""
    checkout = tmp_path / "a-worktree"
    claude_dir = checkout / ".claude"
    # exist_ok: the two-encoder comparison runs twice against ONE checkout,
    # because the checkout path is part of the message being compared.
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "init.sh").write_text(_INIT_SH.read_text())
    return checkout


def _not_installed_answer(tmp_path: Path, event: str, *, with_jq: bool) -> tuple[str, Path]:
    """`(stdout, checkout)` for a not-installed answer to `event`."""
    checkout = _sandbox_checkout(tmp_path)
    bindir = _curated_bin(tmp_path, with_jq=with_jq)
    init_sh = checkout / ".claude" / "init.sh"
    script = (
        f'source "{init_sh}" >/dev/null 2>/dev/null\n'
        "_HOOKS_DAEMON_NOT_INSTALLED=true\n"
        'emit_hook_error "$1" "daemon_not_installed" "no daemon here"\n'
    )
    result = subprocess.run(
        ["bash", "-c", script, "bash", event],
        capture_output=True,
        text=True,
        env={"PATH": str(bindir), "HOME": str(tmp_path)},
        timeout=_RUN_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout, checkout


@pytest.fixture(params=[True, False], ids=["jq", "python3-fallback"])
def with_jq(request: pytest.FixtureRequest) -> bool:
    encoder_available = shutil.which("jq") is not None
    if request.param and not encoder_available:
        pytest.skip("jq is not installed on this machine")
    return bool(request.param)


class TestANonStopEventsAdvisory:
    def test_it_names_the_checkout(self, tmp_path: Path, with_jq: bool) -> None:
        stdout, checkout = _not_installed_answer(tmp_path, "PreToolUse", with_jq=with_jq)
        context = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
        assert str(checkout) in context, context

    def test_it_still_says_what_to_do(self, tmp_path: Path, with_jq: bool) -> None:
        """Naming the checkout must not displace the install instruction."""
        stdout, _ = _not_installed_answer(tmp_path, "PreToolUse", with_jq=with_jq)
        context = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
        assert "hooks-daemon skill" in context


class TestTheStopFamilysBlock:
    """The shape that reads as a working gate, so it needs the name most."""

    @pytest.mark.parametrize("event", ["Stop", "SubagentStop"])
    def test_the_block_reason_names_the_checkout(
        self, tmp_path: Path, event: str, with_jq: bool
    ) -> None:
        stdout, checkout = _not_installed_answer(tmp_path, event, with_jq=with_jq)
        parsed = json.loads(stdout)
        assert parsed["decision"] == "block"
        assert str(checkout) in parsed["reason"], parsed["reason"]


class TestTheEncodersAgree:
    def test_both_produce_the_same_answer(self, tmp_path: Path) -> None:
        """A message present in only one encoder is missing where it is needed."""
        if shutil.which("jq") is None:
            pytest.skip("jq is not installed on this machine")
        with_jq, checkout = _not_installed_answer(tmp_path, "PreToolUse", with_jq=True)
        without_jq, same_checkout = _not_installed_answer(tmp_path, "PreToolUse", with_jq=False)
        assert checkout == same_checkout, "both runs must describe the same checkout"
        assert json.loads(with_jq) == json.loads(without_jq)
