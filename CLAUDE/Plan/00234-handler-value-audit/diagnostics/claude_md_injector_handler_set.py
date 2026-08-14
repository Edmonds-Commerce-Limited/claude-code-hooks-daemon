"""Diagnostic: what handler set does ClaudeMdInjector actually receive?"""

import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.config import Config
from claude_code_hooks_daemon.core.claude_md_injector import ClaudeMdInjector
from claude_code_hooks_daemon.daemon.cli import _build_initialised_controller

logging.disable(logging.CRITICAL)
cfg = Config.load(Path("/workspace/.claude/hooks-daemon.yaml"))

captured: dict[str, list[Any]] = {}


def spy(self: Any, workspace_root: Path, handlers: list[Any]) -> None:
    captured["handlers"] = list(handlers)
    self._workspace_root = workspace_root
    self._handlers = handlers


with (
    patch.object(ClaudeMdInjector, "__init__", spy),
    patch.object(ClaudeMdInjector, "inject", lambda _self: None),
):
    controller = _build_initialised_controller(cfg, Path("/workspace"))

handlers = captured.get("handlers", [])
names = [getattr(h, "name", "?") for h in handlers]
print(f"handlers passed to injector: {len(names)}")
print(f"nitpick among them: {[n for n in names if 'nitpick' in n]}")
print(f"dispatcher: {controller._pseudo_dispatcher!r}")
if controller._pseudo_dispatcher is not None:
    for handler in controller._pseudo_dispatcher.all_handlers():
        guidance = handler.get_claude_md()
        print(f"  live pseudo handler {handler.name}: get_claude_md -> {type(guidance).__name__}")

real = ClaudeMdInjector.__new__(ClaudeMdInjector)
real._workspace_root = Path("/workspace")
real._handlers = handlers
sections = real._collect_sections()
print(f"_collect_sections -> {len(sections)} sections")
print(f"  nitpick sections: {[n for n, _ in sections if 'nitpick' in n]}")
block = real._build_section(sections)
print(f"_build_section contains dismissive: {'nitpick.dismissive_language' in block}")
print(f"_build_section contains hedging: {'nitpick.hedging_language' in block}")

original = (Path("/workspace") / "CLAUDE.md").read_text(encoding="utf-8")
updated = real._replace_or_append_section(original, block)
print(f"after replace, contains dismissive: {'nitpick.dismissive_language' in updated}")
formatted = real._format_fail_safe(updated)
print(f"after mdformat, contains dismissive: {'nitpick.dismissive_language' in formatted}")
print(f"content-loss guard passes: {real._is_user_content_preserved(original, updated)}")
