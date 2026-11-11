"""The ownership sentence leads the injected block (Plan 00599)."""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.core.claude_md_injector import ClaudeMdInjector
from claude_code_hooks_daemon.core.ownership import OWNERSHIP_SENTENCE

_HEADER = "## Hooks Daemon — Active Handler Guidance"


class _Handler:
    name = "h"

    def get_claude_md(self) -> str | None:
        return "## h\n\nguidance"


def test_block_without_statement_is_unchanged() -> None:
    block = ClaudeMdInjector._build_section([], [], [])
    assert OWNERSHIP_SENTENCE not in block


def test_statement_sits_between_heading_and_intro() -> None:
    block = ClaudeMdInjector._build_section([], [], [], ownership_statement=OWNERSHIP_SENTENCE)
    assert block.index(_HEADER) < block.index(OWNERSHIP_SENTENCE)
    assert block.index(OWNERSHIP_SENTENCE) < block.index("The handlers listed below")


def test_custom_statement_is_used_verbatim() -> None:
    block = ClaudeMdInjector._build_section([], [], [], ownership_statement="Mine except vendor/.")
    assert "Mine except vendor/." in block


def test_injector_generates_block_with_statement() -> None:
    injector = ClaudeMdInjector(
        workspace_root=Path(), handlers=[_Handler()], ownership_statement=OWNERSHIP_SENTENCE
    )
    block = injector._generated_block()
    assert block is not None
    assert OWNERSHIP_SENTENCE in block


def test_injector_without_statement_omits_it() -> None:
    injector = ClaudeMdInjector(workspace_root=Path(), handlers=[_Handler()])
    block = injector._generated_block()
    assert block is not None
    assert OWNERSHIP_SENTENCE not in block
