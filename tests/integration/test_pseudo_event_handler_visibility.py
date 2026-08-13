"""Pseudo-event handlers must be visible to every handler-enumeration surface.

Plan 00237, DBF. Nitpick handlers are registered into a chain owned by
``PseudoEventDispatcher`` rather than into an ``EventRouter`` chain, and
``nitpick`` is not a key in ``EVENT_TYPE_MAPPING`` (correctly — it is not a
dispatchable ``EventType``). Both facts are right. The consequence was not: FOUR
separate surfaces enumerate "the handlers" and every one of them silently
excluded the entire pseudo-event category.

| Surface                            | Excluded by                          |
| ---------------------------------- | ------------------------------------ |
| ``ClaudeMdInjector``               | walking ``EventRouter`` chains       |
| ``DaemonController.get_handlers``  | walking ``EventRouter`` chains       |
| ``DocsGenerator``                  | ``EVENT_TYPE_MAPPING`` vs config keys |
| ``PlaybookGenerator``              | ``EVENT_TYPE_MAPPING`` vs module path |

The injector was fixed when a guidance move landed on it and deleted two
CLAUDE.md sections. The other three were found by going looking, and the
playbook is the serious one: the release process has a BLOCKING acceptance
gate, and both nitpick handlers declare real ``get_acceptance_tests()`` that
have never appeared in the playbook that gate is generated from. A handler can
ship indefinitely with acceptance tests that are never run AND never reported
as missing — silence from a generator reads identically to "nothing to report".

**These tests assert OUTCOMES, never mechanisms.** Every mechanism-level
conclusion drawn while investigating this was wrong — twice, confidently, from
reading the code — and settled in seconds by running the thing. So each test
below generates the real artefact and looks for the handler in it. A test that
asserted "the generator consults the pseudo-events config" would pass against a
consult that produced no output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry
from claude_code_hooks_daemon.pseudo_events.registry import pseudo_event_handler_classes

# Both shipped nitpick handlers, by the identity each surface renders.
_NITPICK_CLASS_NAMES = (
    "DismissiveLanguageNitpickHandler",
    "HedgingLanguageNitpickHandler",
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _project_context() -> None:
    """Initialise ProjectContext so handlers reading it can be constructed."""
    if not getattr(ProjectContext, "_initialized", False):
        ProjectContext.initialize(_project_root() / ".claude" / "hooks-daemon.yaml")


def _pseudo_events_config() -> dict[str, Any]:
    """A minimal enabled-nitpick config, matching the shipped shape."""
    return {
        "nitpick": {
            "enabled": True,
            "triggers": ["pre_tool_use:1/5", "stop:1/1"],
            "handlers": {
                "dismissive_language": {"enabled": True},
                "hedging_language": {"enabled": True},
            },
        }
    }


class TestTheSharedRegistryIsTheOneSourceOfTruth:
    """Every surface reads the same list, so a new pseudo-event reaches them all.

    Three ad-hoc "also check the pseudo-events config" blocks is how the
    original state arose: each consumer re-derived the handler set its own way
    and each derivation was separately wrong.
    """

    def test_the_registry_names_the_shipped_nitpick_handlers(self) -> None:
        classes = pseudo_event_handler_classes()

        assert "nitpick" in classes, (
            "The shared pseudo-event registry does not know about nitpick. "
            "Every enumeration surface reads this — an empty or partial registry "
            "makes all of them wrong at once."
        )
        names = {cls.__name__ for cls in classes["nitpick"].values()}
        assert names == set(
            _NITPICK_CLASS_NAMES
        ), f"Expected the two shipped nitpick handlers, got {sorted(names)}."


class TestAcceptanceTestsReachThePlaybook:
    """The BLOCKING release gate must be able to see these handlers' tests."""

    def _playbook(self) -> str:
        from claude_code_hooks_daemon.daemon.playbook_generator import PlaybookGenerator

        registry = HandlerRegistry()
        registry.discover()
        generator = PlaybookGenerator(
            config={},
            registry=registry,
            pseudo_events=_pseudo_events_config(),
        )
        return generator.generate_markdown()

    def test_the_declared_nitpick_tests_appear(self) -> None:
        playbook = self._playbook()

        missing = [
            cls.__name__
            for cls in pseudo_event_handler_classes()["nitpick"].values()
            if cls().name not in playbook
        ]

        assert not missing, (
            f"These pseudo-event handlers declare acceptance tests that do not appear "
            f"in the generated playbook: {missing}. The release acceptance gate is "
            "generated from this document, so a handler missing here is a handler "
            "whose tests are never run and never reported as missing."
        )

    def test_a_handler_with_no_tests_is_not_invented(self) -> None:
        """Guard the guard: presence must come from declared tests, not a stub row.

        A fix that emitted a section header per pseudo-event handler regardless
        of content would satisfy the test above while adding nothing runnable.
        """
        playbook = self._playbook()

        for cls in pseudo_event_handler_classes()["nitpick"].values():
            for declared in cls().get_acceptance_tests():
                assert declared.title in playbook, (
                    f"{cls.__name__} declares the acceptance test {declared.title!r} "
                    "but its TITLE is absent from the playbook — the handler is "
                    "named without its tests being carried through."
                )


class TestActiveHandlerDocsIncludeThem:
    """CLAUDE.md points agents at HOOKS-DAEMON.md as the active-handler summary."""

    @staticmethod
    def _docs(pseudo_events: dict[str, Any]) -> str:
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        registry = HandlerRegistry()
        registry.discover()
        return DocsGenerator(
            config={}, registry=registry, pseudo_events=pseudo_events
        ).generate_markdown()

    def test_nitpick_handlers_appear_in_generated_docs(self) -> None:
        """Identified by CONFIG KEY, matching every other row in the table.

        The table's identity column is the key a reader would edit, not the
        handler's display name — so that is what must be present, and what a
        reader can act on.
        """
        markdown = self._docs(_pseudo_events_config())

        missing = [
            config_key
            for config_key in pseudo_event_handler_classes()["nitpick"]
            if config_key not in markdown
        ]

        assert not missing, (
            f"These live pseudo-event handlers are absent from the generated "
            f"HOOKS-DAEMON.md: {missing}. CLAUDE.md describes that file as 'the "
            "current active handler summary, generated from live config', which it "
            "is not while an entire category is missing from it."
        )

    def test_they_are_grouped_under_their_own_section(self) -> None:
        """A pseudo-event trigger is a ratio on real events, not an event.

        Folding these rows into a real event's table would tell a reader they
        can add a handler there and have it fire the same way, which is exactly
        the confusion that let two handlers sit shadowed under ``stop:``.
        """
        markdown = self._docs(_pseudo_events_config())

        assert "Pseudo Nitpick" in markdown, (
            "Pseudo-event handlers are present but not grouped under their own "
            f"heading. Sections found: {[ln for ln in markdown.splitlines() if ln.startswith('###')]}"
        )

    def test_a_disabled_pseudo_event_is_not_advertised_as_active(self) -> None:
        """The summary is of ACTIVE handlers, so disabling must remove them."""
        disabled = _pseudo_events_config()
        disabled["nitpick"]["enabled"] = False

        markdown = self._docs(disabled)

        assert "Pseudo Nitpick" not in markdown, (
            "The nitpick section appears in the active-handler summary while "
            "pseudo_events.nitpick.enabled is false. Listing a disabled handler as "
            "active is the same defect in the opposite direction."
        )
