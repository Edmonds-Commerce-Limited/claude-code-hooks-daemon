"""A global ``--project-root`` must survive the subparser (Plan 00374).

``bin/hooks-daemon`` anchors every invocation to the project the wrapper lives
in by passing ``--project-root`` BEFORE the subcommand, and refuses to run at
all if it cannot derive one — "Refusing to fall back to the working directory:
that would target whichever project you happen to be standing in."

Twenty-five subcommands declare their own ``--project-root`` with
``default=None``, and argparse writes a subparser's defaults into the namespace
whether or not the flag was supplied. So the subparser's ``None`` overwrote the
anchor, and the CLI fell back to auto-detection — the precise behaviour the
wrapper exists to prevent, in the commands most likely to be pointed at another
tree.

``tests/unit/install/test_bin_wrapper_project_anchoring.py`` could not catch
this. Its docstring says the tests "assert the ACTUAL command the wrapper
builds rather than trusting a reading of the shell" — and then trusts a reading
of argparse. The wrapper's argv was always right; the CLI discarded it.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.daemon.cli import apply_global_project_root

_CLI_MODULE: Final[str] = "claude_code_hooks_daemon.daemon.cli"
_CONFIG_ENABLED: Final[str] = "plan_workflow:\n  enabled: true\n"

# `plan-qa --sweep` is the probe because its two outcomes are unambiguous and
# root-dependent: a root with no plan tree is an operational error (2), and
# any root that HAS one here is clean (0). A command whose result is the same
# either way could not tell us which tree it looked at.
_MISSING_PLAN_DIR_EXIT: Final[int] = 2


class TestTheReconciliation:
    """The pure half: which value wins, given what the namespace holds."""

    def test_the_global_value_is_used_when_the_subcommand_supplied_none(self) -> None:
        args = argparse.Namespace(
            global_project_root=Path("/anchor"), project_root=None, func=None
        )

        assert apply_global_project_root(args).project_root == Path("/anchor")

    def test_a_subcommand_value_wins_over_the_global_one(self) -> None:
        """The wrapper's comment promises a caller can still override the anchor."""
        args = argparse.Namespace(
            global_project_root=Path("/anchor"), project_root=Path("/explicit"), func=None
        )

        assert apply_global_project_root(args).project_root == Path("/explicit")

    def test_a_subcommand_without_its_own_flag_still_receives_the_global_value(self) -> None:
        """Most subcommands declare no `--project-root`; they must not lose it."""
        args = argparse.Namespace(global_project_root=Path("/anchor"), func=None)

        assert apply_global_project_root(args).project_root == Path("/anchor")

    def test_no_global_value_leaves_the_namespace_alone(self) -> None:
        """Auto-detection stays the behaviour when nothing was named anywhere."""
        args = argparse.Namespace(global_project_root=None, project_root=None, func=None)

        assert apply_global_project_root(args).project_root is None


class TestNoSubparserPreemptsTheAnchorWithACwdDefault:
    """A subparser default of `Path.cwd()` defeats the reconciliation silently.

    `apply_global_project_root` can only supply the anchor where the
    subcommand left `project_root` unset. A subparser that defaults the flag
    to the working directory therefore never receives it — and lands on
    exactly the behaviour `bin/hooks-daemon` refuses to allow, with the
    fallback hard-coded rather than merely reachable.

    `deploy-plan-workflow` and `agents` both did this. Read from source
    because `main()` builds its parser inline over ~1,450 lines, so there is
    no parser object to introspect; the string is the honest available check
    and it fails loudly if someone reintroduces the shape.
    """

    _CLI_SOURCE: Final[Path] = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "claude_code_hooks_daemon"
        / "daemon"
        / "cli.py"
    )

    def test_no_project_root_argument_defaults_to_the_working_directory(self) -> None:
        source = self._CLI_SOURCE.read_text(encoding="utf-8")
        blocks = source.split('"--project-root",')

        # Bound each block at the add_argument call's own dedented closing
        # paren. Splitting on a bare ")" would stop inside `Path.cwd()` and
        # never see the very default being looked for — which it did.
        offenders = [
            index
            for index, block in enumerate(blocks[1:], start=1)
            if "default=Path.cwd()" in block.split("\n    )")[0]
        ]

        assert not offenders, (
            f"{len(offenders)} `--project-root` argument(s) default to Path.cwd(), "
            "which pre-empts the anchor bin/hooks-daemon passes before the "
            "subcommand. Use default=None and fall back to the working "
            "directory inside the command function instead."
        )


class TestBothArgvOrdersAgree:
    """The behavioural half, at the layer the anchoring suite stops short of.

    Run as a subprocess against the real CLI: the defect lived in argparse's
    namespace construction, which an in-process call with a hand-built
    Namespace cannot reach — measured live, `cmd_plan_qa` called directly with
    the root in its namespace returned 2 while the same root passed on the
    command line returned 0.
    """

    def _rootless_project(self, tmp_path: Path) -> Path:
        """A configured project with NO plan directory, so its verdict is exit 2."""
        root = tmp_path / "elsewhere"
        (root / ".claude").mkdir(parents=True)
        (root / ".claude" / "hooks-daemon.yaml").write_text(_CONFIG_ENABLED)
        return root

    def _run(self, argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", _CLI_MODULE, *argv],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=Timeout.GIT_CONTEXT,
            check=False,
        )

    @pytest.mark.parametrize(
        "argv_builder",
        [
            pytest.param(
                lambda root: ["--project-root", str(root), "plan-qa", "--sweep"],
                id="global-before-subcommand",
            ),
            pytest.param(
                lambda root: ["plan-qa", "--sweep", "--project-root", str(root)],
                id="subcommand-level",
            ),
        ],
    )
    def test_the_named_root_is_the_one_swept(
        self, tmp_path: Path, argv_builder: Callable[[Path], list[str]]
    ) -> None:
        root = self._rootless_project(tmp_path)

        result = self._run(argv_builder(root), cwd=tmp_path)

        assert result.returncode == _MISSING_PLAN_DIR_EXIT, (
            "the CLI swept a tree other than the one named: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "plan tree is clean" not in result.stdout.lower()
