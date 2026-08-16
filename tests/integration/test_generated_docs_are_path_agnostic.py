"""Generated TRACKED documentation must never name the machine that rendered it.

Plan 00244, from a client bug report against v3.51.0.

``ClaudeMdInjector`` writes every handler's ``get_claude_md()`` verbatim into
the ``<hooksdaemon>`` block of the project's ``CLAUDE.md`` on every daemon
startup, and auto-commits it. ``DocsGenerator`` writes ``.claude/HOOKS-DAEMON.md``.
Both files are tracked, committed, shared between clones, and in the reporting
project's case public on GitHub.

Guidance destined for those files therefore has the OPPOSITE requirement to
guidance destined for a block reason. A runtime message is ephemeral and read by
an agent on this machine, so Plan 00192 correctly made it an absolute,
copy-paste-runnable path. A tracked document is read by every clone on every
machine, so an absolute path there:

1. writes the author's home directory into a committed file;
2. is wrong for every other clone — a directory that does not exist there;
3. rewrites itself per machine, so the file ping-pongs and conflicts on merge.

**Why this went unnoticed for so long, and why this file renders in CLIENT
mode.** In self-install mode the project root is ``/workspace``, so our own
generated docs render ``/workspace/bin/hooks-daemon …`` — absolute, but
identical for everyone. Our committed artifacts look correct while every client
install leaks. A guard that rendered in self-install mode would reproduce that
blindness exactly, so this one pins ``ProjectContext`` to a client root that
looks like a real developer's checkout.

Two distinct defect classes are both caught here, which is the point of asserting
on the RENDERED TEXT rather than on the call sites:

- **Derived** — the guidance called a runtime path builder, so it names whatever
  root rendered it. Grepping for the builder finds these.
- **Hard-coded** — the guidance contains the literal string ``/workspace``.
  Grepping for the builder does NOT find these, and they are worse: ``/workspace``
  is not merely machine-specific, it is simply false on a client install.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from claude_code_hooks_daemon import handlers as handlers_pkg
from claude_code_hooks_daemon.core import project_context as pc
from claude_code_hooks_daemon.core.handler import Handler

#: A CLIENT project root shaped like a real developer's checkout. Deliberately
#: NOT a temp directory: the failure this guards against is a HOME DIRECTORY
#: reaching a public repository, and a name of that shape makes a failure
#: message say so out loud.
_CLIENT_ROOT: Path = Path("/home/testuser/Projects/example-app")

#: This repository's own self-install root. Guidance shipped to clients must
#: never contain it — on a client machine no such directory exists, so the
#: reader is told to run a command against a path that is not there.
_DOGFOOD_ROOT: str = "/workspace"

#: Where the daemon lives relative to a CLIENT project root. Guidance may name
#: this, because it is true in every client clone.
_PORTABLE_CLIENT_PREFIX: str = ".claude/hooks-daemon/bin/hooks-daemon"


def _repo_root() -> Path:
    """Return the repository root (this file is tests/integration/<name>.py)."""
    return Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _client_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Render every artifact as a CLIENT install, not as this repo.

    ``ProjectContext`` is initialised for real first, so handlers that read
    config during construction still work; only the two accessors that decide
    the rendered path are then redirected. Patching before construction matters
    — a handler is free to resolve its paths in ``__init__``.
    """
    if not getattr(pc.ProjectContext, "_initialized", False):
        pc.ProjectContext.initialize(_repo_root() / ".claude" / "hooks-daemon.yaml")
    monkeypatch.setattr(
        pc.ProjectContext, "project_root", classmethod(lambda cls: _CLIENT_ROOT), raising=False
    )
    monkeypatch.setattr(
        pc.ProjectContext, "self_install_mode", classmethod(lambda cls: False), raising=False
    )


def _discover_handler_classes() -> dict[str, type[Handler]]:
    """Every concrete Handler subclass under the handlers package.

    Discovered, not hardcoded — a hardcoded list is blind to exactly the new
    handler this guard exists to catch.
    """
    found: dict[str, type[Handler]] = {}
    for _finder, module_name, _ispkg in pkgutil.walk_packages(
        handlers_pkg.__path__, prefix=handlers_pkg.__name__ + "."
    ):
        module = importlib.import_module(module_name)
        for attribute_name, attribute in vars(module).items():
            if (
                inspect.isclass(attribute)
                and issubclass(attribute, Handler)
                and attribute is not Handler
                and attribute.__module__ == module.__name__
                and not getattr(attribute, "__abstractmethods__", None)
            ):
                found[attribute_name] = attribute
    return found


def _handler_names() -> list[str]:
    """Sorted handler class names, so parametrised ids are stable."""
    return sorted(_discover_handler_classes())


def _guidance_of(class_name: str) -> str | None:
    """Construct the handler under client mode and return its guidance.

    Constructor failures are raised, never swallowed: a handler that drops out
    of discovery is precisely the silent escape this guard exists to prevent.
    """
    handler: Any = _discover_handler_classes()[class_name]()
    guidance: str | None = handler.get_claude_md()
    return guidance


class TestHandlerGuidanceNamesNoMachine:
    """The property that matters: guidance is true in every clone."""

    @pytest.mark.parametrize("class_name", _handler_names())
    def test_guidance_does_not_embed_the_rendering_project_root(self, class_name: str) -> None:
        """Derived leak: the guidance named whatever root rendered it."""
        guidance = _guidance_of(class_name)
        if guidance is None:
            return
        assert str(_CLIENT_ROOT) not in guidance, (
            f"{class_name}.get_claude_md() embeds the rendering machine's project "
            f"root ({_CLIENT_ROOT}). This string is written verbatim into the "
            f"tracked <hooksdaemon> block of CLAUDE.md and committed, so it would "
            f"publish a developer's home directory and be wrong in every other "
            f"clone. Use the path-agnostic doc builder, not the runtime one."
        )

    @pytest.mark.parametrize("class_name", _handler_names())
    def test_guidance_does_not_hardcode_the_dogfood_root(self, class_name: str) -> None:
        """Hard-coded leak: grepping for the path builders does not find these."""
        guidance = _guidance_of(class_name)
        if guidance is None:
            return
        assert _DOGFOOD_ROOT not in guidance, (
            f"{class_name}.get_claude_md() hard-codes {_DOGFOOD_ROOT!r}, this "
            f"repository's own self-install root. On a client install no such "
            f"directory exists, so the guidance names a path that is simply not "
            f"there. Describe the location relative to the project root instead."
        )


class TestTheGuardCanActuallySeeAClientInstall:
    """A guard that silently rendered in self-install mode would prove nothing.

    This is the blindness that let the defect ship, so it is asserted rather
    than assumed.
    """

    def test_client_mode_is_in_force_while_rendering(self) -> None:
        assert pc.ProjectContext.project_root() == _CLIENT_ROOT
        assert pc.ProjectContext.self_install_mode() is False

    def test_the_runtime_builder_still_leaks_under_this_fixture(self) -> None:
        """Pins WHY the fixture is needed: the runtime builder is unchanged.

        Plan 00192's contract is deliberately untouched — a block reason must
        stay absolute. If this ever stops holding, the fix went too far and
        started rewriting runtime output too.
        """
        from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command

        assert str(_CLIENT_ROOT) in daemon_cli_command("status")


class TestGeneratedHooksDaemonDoc:
    """`.claude/HOOKS-DAEMON.md` is tracked too, and has its own generator."""

    @staticmethod
    def _render() -> str:
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        registry = MagicMock()
        registry.list_handlers.return_value = []
        registry.get_handler_class.side_effect = lambda name: None
        generator = DocsGenerator(config={}, registry=registry)
        rendered: str = generator.generate_markdown()
        return rendered

    def test_document_does_not_embed_the_rendering_project_root(self) -> None:
        assert str(_CLIENT_ROOT) not in self._render(), (
            "The generated .claude/HOOKS-DAEMON.md names the rendering machine's "
            "project root. The file is tracked and committed, so every client "
            "would publish its own absolute path in the header."
        )

    def test_document_does_not_hardcode_the_dogfood_root(self) -> None:
        assert _DOGFOOD_ROOT not in self._render()

    def test_regenerate_hint_still_names_the_wrapper(self) -> None:
        """Path-agnostic must not become path-less — the hint must stay usable."""
        assert _PORTABLE_CLIENT_PREFIX in self._render()
