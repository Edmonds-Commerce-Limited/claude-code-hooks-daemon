"""Integration tests for emit_hook_error's jq-less fallback (Plan 00156 review, F7).

``emit_hook_error`` prefers ``jq`` to build its JSON, but falls back to a
``jq``-absent path. Plan 00156 removed ``jq`` from the hot-path transport, so a
genuinely ``jq``-less host is now plausible and this fallback can really fire.

The pre-fix fallback interpolated ``$error_details`` straight into a JSON string
with no escaping and emitted ``hookSpecificOutput`` (fail-open) even for
Stop/SubagentStop. These tests pin the fixed contract:

1. **Valid JSON for adversarial input** — details containing quotes, backslashes
   and newlines must still yield parseable JSON (no injection into the document).
2. **Stop/SubagentStop fail CLOSED** — the fallback must emit ``decision: block``
   for Stop-family events, matching the jq path (never fail-open on a Stop).
3. **Other events fail open** — ``hookSpecificOutput`` with advisory context.

To force the fallback, ``jq`` must be truly absent from ``PATH`` (a broken shim
would leave ``command -v jq`` true and take the jq branch). We therefore run in a
sandbox project with a curated ``PATH`` that omits ``jq`` but keeps every tool
init.sh needs at source time plus ``python3`` (the fallback's encoder).
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

# Tools init.sh may invoke at source time + emit_hook_error's encoder (python3).
# jq is deliberately excluded so `command -v jq` is false and the fallback fires.
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


def _curated_bin_without_jq(tmp_path: Path) -> Path:
    """A bin dir symlinking essential tools but NOT jq; returned for PATH use."""
    bindir = tmp_path / "curated-bin"
    bindir.mkdir()
    for tool in _ESSENTIAL_TOOLS:
        real = shutil.which(tool)
        if real is not None:
            (bindir / tool).symlink_to(real)
    return bindir


def _sandbox_project(tmp_path: Path) -> Path:
    """Throwaway project (no .git) that sources a copy of the real init.sh."""
    proj = tmp_path / "proj"
    claude_dir = proj / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "init.sh").write_text(_INIT_SH.read_text())
    (claude_dir / "hooks-daemon.env").write_text(
        'export HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH/root"\n'
    )
    return proj


def _emit(
    tmp_path: Path, event: str, error_type: str, details: str
) -> subprocess.CompletedProcess[str]:
    """Source init.sh with jq absent, then call emit_hook_error; capture stdout."""
    proj = _sandbox_project(tmp_path)
    bindir = _curated_bin_without_jq(tmp_path)
    init_sh = proj / ".claude" / "init.sh"
    script = f'source "{init_sh}" >/dev/null 2>/dev/null\nemit_hook_error "$1" "$2" "$3"'
    env = {"PATH": str(bindir), "HOME": str(tmp_path)}
    return subprocess.run(
        ["bash", "-c", script, "bash", event, error_type, details],
        capture_output=True,
        text=True,
        env=env,
        timeout=_RUN_TIMEOUT_SECONDS,
    )


def test_fallback_absent_jq_is_actually_taken(tmp_path: Path) -> None:
    """Precondition: with the curated PATH, `command -v jq` is false in-sandbox.

    If jq leaked into PATH the other tests would silently exercise the jq branch
    instead of the fallback, so assert the fallback is genuinely reachable.
    """
    bindir = _curated_bin_without_jq(tmp_path)
    probe = subprocess.run(
        ["bash", "-c", "command -v jq"],
        capture_output=True,
        text=True,
        env={"PATH": str(bindir)},
        timeout=_RUN_TIMEOUT_SECONDS,
    )
    assert probe.returncode != 0, f"jq unexpectedly on curated PATH: {probe.stdout!r}"


def test_fallback_emits_valid_json_for_adversarial_details(tmp_path: Path) -> None:
    """Details with quotes/backslashes/newlines must not break the JSON document."""
    nasty = 'boom "quoted" \\ backslash\nsecond line\ttab'
    result = _emit(tmp_path, "PreToolUse", "daemon_startup_failed", nasty)

    assert result.returncode == 0, result.stderr
    # Must parse — the pre-fix fallback produced invalid JSON here.
    parsed = json.loads(result.stdout)
    context = parsed["hookSpecificOutput"]["additionalContext"]
    assert nasty in context
    assert parsed["hookSpecificOutput"]["hookEventName"] == "PreToolUse"


@pytest.mark.parametrize("event", ["Stop", "SubagentStop"])
def test_fallback_stop_fails_closed(tmp_path: Path, event: str) -> None:
    """Stop-family events must emit decision=block (fail closed), like the jq path."""
    result = _emit(tmp_path, event, "daemon_startup_failed", "daemon down")

    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert parsed.get("decision") == "block", parsed
    assert "hookSpecificOutput" not in parsed


def test_fallback_non_stop_fails_open(tmp_path: Path) -> None:
    """Non-Stop events fail open with advisory context (no decision key)."""
    result = _emit(tmp_path, "PostToolUse", "socket_timeout", "slow")

    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert "decision" not in parsed
    assert parsed["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
