"""Tier 1 acceptance: `bash <path>` makes the hook +x bit irrelevant.

Plan 00102 — the headline behavioural claim: when `core.fileMode=false`,
a Windows clone, a tarball transfer, or an IDE save mode-strip drops the
executable bit on `.claude/hooks/*`, hooks must still fire because we
invoke them via `bash <abs-path>` from settings.json. The kernel never
has to honour the +x bit — `bash` reads the file as plain data.

These tests use a temporary copy of the real `.claude/hooks/pre-tool-use`
wrapper so we don't mutate the live dogfood install.
"""

import shutil
import subprocess
from pathlib import Path

from claude_code_hooks_daemon.constants import Timeout

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_HOOK_SCRIPT = _PROJECT_ROOT / ".claude" / "hooks" / "pre-tool-use"
_NON_EXECUTABLE_MODE = 0o644
_EXIT_PERMISSION_DENIED = 126


def test_direct_invocation_fails_without_exec_bit(tmp_path: Path) -> None:
    """Sanity check: without +x, direct invocation IS broken.

    Establishes the bug actually happens when the exec bit is dropped —
    if this test ever stops failing in the broken state, the OS or shell
    has changed and the rest of the suite needs revisiting.

    Python's subprocess raises PermissionError before the kernel even
    spawns the process; a shell would surface returncode 126. Either
    way, the invocation is broken.
    """
    copy = tmp_path / "pre-tool-use"
    shutil.copy(_HOOK_SCRIPT, copy)
    copy.chmod(_NON_EXECUTABLE_MODE)

    try:
        result = subprocess.run(
            [str(copy)],
            input="{}",
            capture_output=True,
            text=True,
            check=False,
        )
    except PermissionError:
        return

    assert result.returncode != 0, (
        "Sanity: direct invocation of a non-executable script must fail. "
        f"Got returncode={result.returncode}, stdout={result.stdout!r}, stderr={result.stderr!r}"
    )


def test_bash_invocation_succeeds_without_exec_bit(tmp_path: Path) -> None:
    """The fix: `bash <path>` runs even when the script lacks +x.

    The bash interpreter reads the script as data, so the kernel
    permission check on the file's executable bit never runs. Whatever
    else happens (daemon up, daemon down, network error), it must not
    be a Permission denied at the process-spawn layer.
    """
    copy = tmp_path / "pre-tool-use"
    shutil.copy(_HOOK_SCRIPT, copy)
    copy.chmod(_NON_EXECUTABLE_MODE)

    result = subprocess.run(
        ["bash", str(copy)],
        input='{"tool_name":"Bash","tool_input":{"command":"echo hi"}}',
        capture_output=True,
        text=True,
        check=False,
        timeout=Timeout.VALIDATION_CHECK,
    )

    assert "Permission denied" not in result.stderr, (
        "bash <path> must NOT produce a Permission denied error when the "
        f"exec bit is dropped. stderr={result.stderr!r}"
    )
    assert (
        result.returncode != _EXIT_PERMISSION_DENIED
    ), f"Got exit 126 (Permission denied). stderr={result.stderr!r}"
