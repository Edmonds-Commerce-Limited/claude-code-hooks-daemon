"""``deploy_slash_commands``/``deploy_single_slash_command`` must never
self-destruct when source and target collapse to the same path.

Plan 00198 (MT-1a): the deprecated ``install.py`` had this exact defect —
no ``source == dest`` guard, so self-install mode unlinked the real file and
symlinked its path to itself. The SAME shape exists in the current,
non-deprecated ``scripts/install/slash_commands.sh``: in self-install mode
``daemon_dir == project_root``, so ``source_commands_dir`` and
``target_commands_dir`` are literally the same directory, and both
functions do ``rm -f "$target_file"; ln -s "$source_file" "$target_file"``
with no guard against that collapse.

Today neither real orchestrator (``install_version.sh``, ``upgrade_version.sh``)
ever calls these with ``self-install`` — both refuse to run in self-install
mode at all (``mode_guard.sh``) — so the defect is latent, not yet observed
in production. It is still a live landmine in documented library code, so it
is fixed here rather than left for the day something wires self-install
through — and THIS file is now the only thing exercising that branch. A
hand-run ``test_slash_commands_manual.sh`` used to nominally cover it; it had
no callers and was removed, which is precisely why the coverage had to become
an automated test rather than a script nobody ran.
"""

import os
import subprocess
from pathlib import Path
from typing import Final

_PROJECT_ROOT: Final[Path] = Path(__file__).parent.parent.parent.parent
_SLASH_COMMANDS_SH: Final[Path] = _PROJECT_ROOT / "scripts" / "install" / "slash_commands.sh"
_COMMAND_CONTENT: Final[str] = "# Test Command\n\nOriginal content that must survive.\n"

#: Subprocess timeout — generous but bounded so a hung shell fails fast.
_TIMEOUT_SECONDS: Final[int] = 30

# Argument-list subprocess.run only (never a raw shell string) — the daemon
# repo's own qa_suppression/security_antipattern handlers enforce this, and
# a trusted local bash invocation is the supported way to exercise a shell
# library function from a pytest module (see test_init_sh_exec_bit_selfheal.py).
_BASH: Final[list[str]] = ["bash", "-c"]


def _run_bash_function(
    function_call: str, cwd: Path, positional_args: list[str]
) -> subprocess.CompletedProcess[str]:
    """Source ``slash_commands.sh`` and run one function call against it.

    ``positional_args`` become ``$1``, ``$2``, ... inside ``function_call`` —
    ``bash -c script $0 $1 $2 ...`` needs a placeholder ``$0`` first, supplied
    here as ``"bash"``.
    """
    script = f'source "{_SLASH_COMMANDS_SH}"\n{function_call}\n'
    return subprocess.run(
        [*_BASH, script, "bash", *positional_args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


def _self_install_project(tmp_path: Path) -> Path:
    """A self-install layout: one project root doubling as the daemon dir."""
    commands_dir = tmp_path / ".claude" / "commands"
    commands_dir.mkdir(parents=True)
    command_file = commands_dir / "test-command.md"
    command_file.write_text(_COMMAND_CONTENT, encoding="utf-8")
    return tmp_path


class TestDeploySlashCommandsSelfInstallSafety:
    """``deploy_slash_commands`` in self-install mode: source == target dir."""

    def test_source_file_survives_self_install_deploy(self, tmp_path: Path) -> None:
        """The real command file must NOT be destroyed by its own deploy."""
        project_root = _self_install_project(tmp_path)
        command_file = project_root / ".claude" / "commands" / "test-command.md"

        result = _run_bash_function(
            'deploy_slash_commands "$1" "$2" "self-install"',
            project_root,
            [str(project_root), str(project_root)],
        )
        assert result.returncode == 0, f"deploy_slash_commands failed: {result.stderr}"

        # FAIL-FAST assertion, not a soft check: if this reads a self-referential
        # symlink instead of real content, the bug has reoccurred. A dangling
        # self-loop raises OSError (ELOOP) on read — that IS the failure mode
        # under test, so it is reported as an assertion, not an uncaught crash.
        assert (
            command_file.is_symlink() or command_file.is_file()
        ), "Command path vanished entirely after self-install deploy"
        try:
            content = command_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise AssertionError(
                f"Source content was destroyed by self-install deploy " f"(unreadable: {exc})"
            ) from exc
        assert (
            content == _COMMAND_CONTENT
        ), f"Source content was destroyed by self-install deploy (got: {content!r})"

    def test_no_self_referential_symlink_created(self, tmp_path: Path) -> None:
        project_root = _self_install_project(tmp_path)
        command_file = project_root / ".claude" / "commands" / "test-command.md"

        _run_bash_function(
            'deploy_slash_commands "$1" "$2" "self-install"',
            project_root,
            [str(project_root), str(project_root)],
        )

        if command_file.is_symlink():
            target = command_file.readlink()
            resolved = Path(os.path.normpath(str(command_file.parent / target)))
            assert resolved != Path(
                os.path.normpath(str(command_file))
            ), f"Symlink {command_file} points at itself: {target}"

    def test_symlink_target_is_not_absolute(self, tmp_path: Path) -> None:
        """A self-install symlink must be repo-relative, never leak the checkout path."""
        project_root = _self_install_project(tmp_path)
        command_file = project_root / ".claude" / "commands" / "test-command.md"

        _run_bash_function(
            'deploy_slash_commands "$1" "$2" "self-install"',
            project_root,
            [str(project_root), str(project_root)],
        )

        if command_file.is_symlink():
            target = command_file.readlink()
            assert (
                not target.is_absolute()
            ), f"Self-install symlink stores an ABSOLUTE target: {target}"

    def test_source_file_survives_single_command_deploy(self, tmp_path: Path) -> None:
        """``deploy_single_slash_command`` has the identical source==dest hazard."""
        project_root = _self_install_project(tmp_path)
        command_file = project_root / ".claude" / "commands" / "test-command.md"

        result = _run_bash_function(
            'deploy_single_slash_command "$1" "$2" "self-install" "test-command"',
            project_root,
            [str(project_root), str(project_root)],
        )
        assert result.returncode == 0, f"deploy_single_slash_command failed: {result.stderr}"

        try:
            content = command_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise AssertionError(
                f"Source content was destroyed by single-command self-install "
                f"deploy (unreadable: {exc})"
            ) from exc
        assert content == _COMMAND_CONTENT, (
            f"Source content was destroyed by single-command self-install deploy "
            f"(got: {content!r})"
        )
