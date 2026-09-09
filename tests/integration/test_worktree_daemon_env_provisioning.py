"""A worktree needs its own `.claude/hooks-daemon.env`, and nothing wrote one.

`.claude/hooks-daemon.env` is gitignored, so `git worktree add` never brings
it across. `init.sh` sources it to learn `HOOKS_DAEMON_ROOT_DIR`, and only
enters self-install mode when it exists — without it every wrapper in the
worktree answered with its "Hooks daemon not installed" fallback.

That failure is quiet in the worst way: the fallback for Stop/SubagentStop is
`decision: block`, which is what a WORKING stop gate also returns, so a smoke
probe passes for the wrong reason and the worktree looks protected while no
handler has run at all (Plan 00364 Task 5.1, from the Phase 4 agent's
finding).

`scripts/setup_worktree.sh` provisions the file, through `install.py`'s own
`create_daemon_env` rather than a second copy of its content. Two properties
are pinned here: the file the installer writes really does put init.sh into
self-install mode for the checkout that sources it, and the setup script
really does write one.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SETUP_WORKTREE = _REPO_ROOT / "scripts" / "setup_worktree.sh"


def _installer() -> Any:
    """`install.py`, imported the way the dogfooding tests import it."""
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    import install

    return install


def _sourced_root_dir(env_file: Path, project_path: Path) -> str:
    """`HOOKS_DAEMON_ROOT_DIR` as init.sh would resolve it after sourcing.

    Mirrors init.sh's own two lines: source the file with `PROJECT_PATH`
    already set, then apply the `.claude/hooks-daemon` default for anything it
    did not set.
    """
    script = (
        f'PROJECT_PATH="{project_path}"\n'
        f'source "{env_file}"\n'
        'echo "${HOOKS_DAEMON_ROOT_DIR:-$PROJECT_PATH/.claude/hooks-daemon}"\n'
    )
    completed = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    return completed.stdout.strip()


class TestTheEnvFileTheInstallerWrites:
    def test_it_puts_init_sh_into_self_install_mode(self, tmp_path: Path) -> None:
        checkout = tmp_path / "worktree-plan-00364"
        (checkout / ".claude").mkdir(parents=True)

        _installer().create_daemon_env(checkout, daemon_root="$PROJECT_PATH")

        env_file = checkout / ".claude" / "hooks-daemon.env"
        assert env_file.is_file()
        assert _sourced_root_dir(env_file, checkout) == str(checkout)

    def test_it_names_no_checkout_of_its_own(self, tmp_path: Path) -> None:
        """`$PROJECT_PATH` is deliberately UNexpanded in the file.

        init.sh expands it against the checkout doing the sourcing, so the
        same bytes are correct in the main checkout and in every worktree —
        and the file can never point at another checkout's daemon.
        """
        checkout = tmp_path / "worktree-plan-00364"
        (checkout / ".claude").mkdir(parents=True)

        _installer().create_daemon_env(checkout, daemon_root="$PROJECT_PATH")

        content = (checkout / ".claude" / "hooks-daemon.env").read_text()
        assert 'HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH"' in content
        assert str(checkout) not in content


class TestTheSetupScriptProvisionsIt:
    def test_it_writes_the_env_file_for_the_new_worktree(self) -> None:
        """Structural: running the real script would create a real worktree.

        The behaviour above is covered against the installer function this
        calls; what is checked here is that the setup script still calls it,
        for the worktree directory, so the step cannot be dropped silently.
        """
        script = _SETUP_WORKTREE.read_text()
        assert "create_daemon_env" in script, (
            "setup_worktree.sh must provision .claude/hooks-daemon.env — without "
            "it init.sh never enters self-install mode in the new worktree"
        )
        assert "hooks-daemon.env" in script

    def test_it_writes_the_file_rather_than_copying_one(self) -> None:
        """A copy across checkouts is blocked by `worktree_file_copy`, and is
        also wrong: it would carry whatever the source checkout's file happens
        to say, including a hand-edit."""
        offenders = [
            line
            for line in _SETUP_WORKTREE.read_text().splitlines()
            if "hooks-daemon.env" in line and ("cp " in line or "rsync " in line)
        ]
        assert not offenders, f"the env file must be written fresh, not copied: {offenders}"
