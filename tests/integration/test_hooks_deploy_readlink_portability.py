"""Plan 00123 BUG 4 (MEDIUM) — hooks_deploy.sh same-file check is portable.

``deploy_init_script`` self-install short-circuit compared source and target
with ``readlink -f`` to decide "init.sh already in place, skip". BSD/macOS
``readlink`` has no ``-f``: both sides fell back to the unresolved literal
paths (``$daemon_dir/init.sh`` vs ``$project_root/.claude/init.sh``), which
always differ, so the short-circuit never fired on macOS and init.sh was
redeployed every install — defeating the symlink-identity check.

Fix: use bash's ``-ef`` test operator (same device + inode, resolves symlinks,
bash 3.2-safe). These tests stub a BSD-style ``readlink`` (fails on ``-f``)
and assert the symlinked target is still recognised as already-in-place.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DEPLOY_SH = REPO_ROOT / "scripts" / "install" / "hooks_deploy.sh"
BASH = shutil.which("bash") or "/bin/bash"

_TIMEOUT_SECONDS = 30
_ALREADY_IN_PLACE = "already in place"


def _run_deploy(tmp_path: Path, *, symlinked: bool) -> subprocess.CompletedProcess[str]:
    """Run deploy_init_script in self-install mode under a BSD readlink stub.

    When ``symlinked`` the target ``.claude/init.sh`` is a symlink to the
    source (the real self-install layout); otherwise it is a distinct file.
    """
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()
    # BSD readlink: rejects -f.
    readlink_stub = stub_dir / "readlink"
    readlink_stub.write_text(textwrap.dedent("""\
            #!/bin/bash
            if [ "$1" = "-f" ]; then echo "readlink: illegal option -- f" >&2; exit 1; fi
            command readlink "$@"
            """))
    readlink_stub.chmod(0o755)

    daemon_dir = tmp_path / "daemon"
    daemon_dir.mkdir()
    source_init = daemon_dir / "init.sh"
    source_init.write_text("# init\n")

    project_root = tmp_path / "project"
    (project_root / ".claude").mkdir(parents=True)
    target_init = project_root / ".claude" / "init.sh"
    if symlinked:
        target_init.symlink_to(source_init)
    else:
        target_init.write_text("# different\n")

    harness = textwrap.dedent(f"""\
        export PATH="{stub_dir}:$PATH"
        export OUTPUT_SH_LOADED=1
        print_verbose() {{ echo "$@"; }}
        print_error() {{ echo "$@" >&2; }}
        print_success() {{ echo "$@"; }}
        . "{HOOKS_DEPLOY_SH}"
        deploy_init_script "{project_root}" "{daemon_dir}" "self-install"
        """)
    return subprocess.run(
        [BASH, "-c", harness],
        capture_output=True,
        text=True,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )


def test_symlinked_target_recognised_without_readlink_f(tmp_path: Path) -> None:
    """Symlinked target is detected as already-in-place even when readlink lacks -f."""
    result = _run_deploy(tmp_path, symlinked=True)
    assert (
        result.returncode == 0
    ), f"deploy_init_script must succeed.\n--- stderr ---\n{result.stderr}"
    assert _ALREADY_IN_PLACE in result.stdout, (
        "BUG 4: a symlinked init.sh must be recognised as already-in-place via "
        "the `-ef` operator — BSD readlink lacks -f, so the old path-string "
        f"compare failed on macOS.\n--- stdout ---\n{result.stdout}"
    )


def test_distinct_target_is_deployed(tmp_path: Path) -> None:
    """A genuinely different target must NOT short-circuit (deploy proceeds)."""
    result = _run_deploy(tmp_path, symlinked=False)
    assert result.returncode == 0
    assert _ALREADY_IN_PLACE not in result.stdout, (
        "A distinct target file must not be treated as already-in-place.\n"
        f"--- stdout ---\n{result.stdout}"
    )


def test_no_readlink_f_remains() -> None:
    """No ``readlink -f`` may remain in executable code (BSD has no -f)."""
    offenders: list[str] = []
    for lineno, line in enumerate(HOOKS_DEPLOY_SH.read_text().splitlines(), start=1):
        if line.strip().startswith("#"):
            continue
        if "readlink -f" in line:
            offenders.append(f"{lineno}: {line.strip()}")
    assert (
        not offenders
    ), "BUG 4: `readlink -f` is GNU-only; use the `-ef` test operator:\n" + "\n".join(offenders)
