"""Tests for the daemon-CLI command resolver (Plan 00192 Phase 1).

Every piece of agent-facing guidance used to emit
``$PYTHON -m claude_code_hooks_daemon.daemon.cli <subcommand>``. ``$PYTHON`` is
never set in an agent's shell and the PATH ``python3`` cannot import the
package from the isolated fingerprint-keyed venv, so every documented line
failed with ``-m: command not found`` (exit 127).

Worse than failing: the error names neither Python nor the venv, so agents
concluded the package was uninstalled and "fixed" it — ``pip install`` into the
wrong environment, Dockerfile edits, rebuilding a venv that was never broken.

These tests pin the replacement contract: a resolver that returns an ABSOLUTE,
runnable path to the deployed wrapper for the CURRENT install mode, and never
emits a shell variable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import project_context as pc
from claude_code_hooks_daemon.utils import cli_command

_SELF_INSTALL_ROOT = Path("/selfinstall-project")
_CLIENT_ROOT = Path("/client-project")


def _set_mode(monkeypatch: pytest.MonkeyPatch, *, root: Path, self_install: bool) -> None:
    """Pin ProjectContext to a known root and install mode."""
    monkeypatch.setattr(pc.ProjectContext, "_initialized", True, raising=False)
    monkeypatch.setattr(
        pc.ProjectContext, "project_root", classmethod(lambda cls: root), raising=False
    )
    monkeypatch.setattr(
        pc.ProjectContext,
        "self_install_mode",
        classmethod(lambda cls: self_install),
        raising=False,
    )


class TestDaemonBinPath:
    """The wrapper lives inside the DAEMON's own directory in both modes."""

    def test_self_install_resolves_to_project_root_bin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, root=_SELF_INSTALL_ROOT, self_install=True)
        assert cli_command.daemon_bin_path() == _SELF_INSTALL_ROOT / "bin" / "hooks-daemon"

    def test_client_install_resolves_inside_claude_hooks_daemon(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, root=_CLIENT_ROOT, self_install=False)
        expected = _CLIENT_ROOT / ".claude" / "hooks-daemon" / "bin" / "hooks-daemon"
        assert cli_command.daemon_bin_path() == expected

    def test_client_wrapper_never_lands_in_the_clients_project_root(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A client's own repo root must not gain a daemon-owned bin/ dir."""
        _set_mode(monkeypatch, root=_CLIENT_ROOT, self_install=False)
        assert cli_command.daemon_bin_path().parent != _CLIENT_ROOT / "bin"

    @pytest.mark.parametrize("self_install", [True, False])
    def test_path_is_always_absolute(
        self, monkeypatch: pytest.MonkeyPatch, self_install: bool
    ) -> None:
        root = _SELF_INSTALL_ROOT if self_install else _CLIENT_ROOT
        _set_mode(monkeypatch, root=root, self_install=self_install)
        assert cli_command.daemon_bin_path().is_absolute()


class TestDaemonCliCommand:
    """The emitted string must be copy-paste runnable as printed."""

    def test_bare_command_is_the_absolute_wrapper_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, root=_SELF_INSTALL_ROOT, self_install=True)
        assert cli_command.daemon_cli_command() == "/selfinstall-project/bin/hooks-daemon"

    def test_arguments_are_appended_in_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_mode(monkeypatch, root=_SELF_INSTALL_ROOT, self_install=True)
        result = cli_command.daemon_cli_command("plan-qa", "--sweep")
        assert result == "/selfinstall-project/bin/hooks-daemon plan-qa --sweep"

    def test_client_mode_command_targets_the_daemon_clone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, root=_CLIENT_ROOT, self_install=False)
        result = cli_command.daemon_cli_command("status")
        assert result == "/client-project/.claude/hooks-daemon/bin/hooks-daemon status"

    @pytest.mark.parametrize("self_install", [True, False])
    def test_never_emits_a_shell_variable(
        self, monkeypatch: pytest.MonkeyPatch, self_install: bool
    ) -> None:
        """The whole point of Plan 00192 — regression guard."""
        root = _SELF_INSTALL_ROOT if self_install else _CLIENT_ROOT
        _set_mode(monkeypatch, root=root, self_install=self_install)
        result = cli_command.daemon_cli_command("plan-qa", "--lint", "x.md")
        assert "$" not in result
        assert "PYTHON" not in result
        assert "-m claude_code_hooks_daemon" not in result

    def test_no_trailing_whitespace_when_called_without_arguments(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, root=_CLIENT_ROOT, self_install=False)
        result = cli_command.daemon_cli_command()
        assert result == result.strip()


class TestUninitialisedProjectContext:
    """Guidance strings must never crash, and never regress to ``$PYTHON``.

    ``ProjectContext.project_root()`` raises when the daemon has not been
    initialised — which is the case in unit tests and in any tooling that
    renders handler guidance outside a running daemon. Raising from a *docstring
    builder* would take down callers over cosmetics, so the resolver degrades to
    the project-root-relative wrapper path. That is still runnable from the
    project root (the documented working directory for every daemon command),
    and is strictly better than emitting a variable that is never set.
    """

    def _uninitialise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pc.ProjectContext, "_initialized", False, raising=False)
        monkeypatch.setattr(pc.ProjectContext, "_instance", None, raising=False)

    def test_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._uninitialise(monkeypatch)
        cli_command.daemon_cli_command("status")

    def test_falls_back_to_relative_client_wrapper_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._uninitialise(monkeypatch)
        result = cli_command.daemon_cli_command("plan-qa", "--sweep")
        assert result == ".claude/hooks-daemon/bin/hooks-daemon plan-qa --sweep"

    def test_fallback_still_contains_no_shell_variable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._uninitialise(monkeypatch)
        result = cli_command.daemon_cli_command("status")
        assert "$" not in result
        assert "PYTHON" not in result


class TestDaemonCliCommandForDocs:
    """The variant destined for TRACKED files (Plan 00244).

    A tracked document is read by every clone on every machine, so it must not
    assert the path of the machine that generated it. That is the OPPOSITE of
    what the runtime builder above must do, which is why there are two.
    """

    def test_client_mode_is_relative_to_the_project_root(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, root=_CLIENT_ROOT, self_install=False)
        result = cli_command.daemon_cli_command_for_docs("status")
        assert result == ".claude/hooks-daemon/bin/hooks-daemon status"

    def test_self_install_mode_names_the_project_root_wrapper(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Self-install keeps the wrapper at the project root, not under .claude."""
        _set_mode(monkeypatch, root=_SELF_INSTALL_ROOT, self_install=True)
        result = cli_command.daemon_cli_command_for_docs("status")
        assert result == "bin/hooks-daemon status"

    @pytest.mark.parametrize("self_install", [True, False])
    def test_never_embeds_the_rendering_project_root(
        self, monkeypatch: pytest.MonkeyPatch, self_install: bool
    ) -> None:
        """The whole point of Plan 00244 — regression guard.

        The leak this replaced wrote a developer's home directory into a
        tracked, committed, sometimes public file.
        """
        root = _SELF_INSTALL_ROOT if self_install else _CLIENT_ROOT
        _set_mode(monkeypatch, root=root, self_install=self_install)
        result = cli_command.daemon_cli_command_for_docs("plan-qa", "--sweep")
        assert str(root) not in result

    @pytest.mark.parametrize("self_install", [True, False])
    def test_is_never_an_absolute_path(
        self, monkeypatch: pytest.MonkeyPatch, self_install: bool
    ) -> None:
        root = _SELF_INSTALL_ROOT if self_install else _CLIENT_ROOT
        _set_mode(monkeypatch, root=root, self_install=self_install)
        assert not cli_command.daemon_cli_command_for_docs("status").startswith("/")

    @pytest.mark.parametrize("self_install", [True, False])
    def test_never_emits_a_shell_variable(
        self, monkeypatch: pytest.MonkeyPatch, self_install: bool
    ) -> None:
        """Plan 00192's contract holds for BOTH builders.

        Path-agnostic must not be bought with a variable the reader's shell
        never sets — that was the original defect Plan 00192 removed.
        """
        root = _SELF_INSTALL_ROOT if self_install else _CLIENT_ROOT
        _set_mode(monkeypatch, root=root, self_install=self_install)
        result = cli_command.daemon_cli_command_for_docs("status")
        assert "$" not in result
        assert "~" not in result

    def test_arguments_are_appended_in_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_mode(monkeypatch, root=_CLIENT_ROOT, self_install=False)
        result = cli_command.daemon_cli_command_for_docs("plan-qa", "--lint", "x.md")
        assert result == ".claude/hooks-daemon/bin/hooks-daemon plan-qa --lint x.md"

    def test_no_trailing_whitespace_when_called_without_arguments(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, root=_CLIENT_ROOT, self_install=False)
        result = cli_command.daemon_cli_command_for_docs()
        assert result == result.strip()

    def test_uninitialised_context_degrades_to_the_client_form(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Docs are rendered by tooling outside a running daemon too.

        A path-builder must never take its caller down over cosmetics, so the
        uninitialised case degrades rather than raising. Client form is the safe
        default: it is what the overwhelming majority of readers have.
        """
        monkeypatch.setattr(pc.ProjectContext, "_initialized", False, raising=False)
        monkeypatch.setattr(pc.ProjectContext, "_instance", None, raising=False)
        result = cli_command.daemon_cli_command_for_docs("status")
        assert result == ".claude/hooks-daemon/bin/hooks-daemon status"


class TestTheTwoBuildersStayDistinct:
    """Guard against a well-meaning future 'unification' of the two builders.

    They look near-identical and serve opposite requirements, so collapsing
    them is a natural-looking refactor that silently reintroduces one of the
    two bugs — depending on which direction it collapses.
    """

    def test_runtime_builder_is_absolute_and_doc_builder_is_not(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, root=_CLIENT_ROOT, self_install=False)
        assert cli_command.daemon_cli_command("status").startswith("/")
        assert not cli_command.daemon_cli_command_for_docs("status").startswith("/")

    def test_the_doc_form_is_a_suffix_of_the_runtime_form(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same wrapper, same arguments — only the root differs."""
        _set_mode(monkeypatch, root=_CLIENT_ROOT, self_install=False)
        assert cli_command.daemon_cli_command("plan-qa", "--sweep").endswith(
            cli_command.daemon_cli_command_for_docs("plan-qa", "--sweep")
        )


class TestWrapperNameConstant:
    """No magic strings — the deployed name is a single named constant."""

    def test_wrapper_name_is_exported(self) -> None:
        assert cli_command.WRAPPER_NAME == "hooks-daemon"

    def test_bin_dir_name_is_exported(self) -> None:
        assert cli_command.BIN_DIR_NAME == "bin"
