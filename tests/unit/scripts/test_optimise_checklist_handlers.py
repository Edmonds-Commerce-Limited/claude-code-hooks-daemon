"""The config-optimisation checklist may only score handlers that exist (Plan 00323).

The step's instruction body is a shell heredoc, so nothing type-checks the
handler names it scores against the registry. Four of them
(`bash_error_detector`, `yolo_container_detection`, `validate_plan_number`,
`plan_completion_advisor`) were deleted by Plan 00237 and stayed in the
checklist: a fully-configured project scored 25/29 forever, and the step
recommended "enabling" handlers no config key can enable.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants.handlers import RETIRED_HANDLERS, HandlerID

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_SCRIPT: Final[Path] = (
    _REPO_ROOT
    / "src"
    / "claude_code_hooks_daemon"
    / "skills"
    / "hooks-daemon"
    / "scripts"
    / "optimise-invoke.sh"
)

#: A dotted config reference to a handler, e.g. handlers.pre_tool_use.tdd_enforcement.
_DOTTED_HANDLER: Final[re.Pattern[str]] = re.compile(
    r"handlers\.(?P<event>[a-z_]+)\.(?P<name>[a-z][a-z0-9_]+)"
)

#: Dotted references that address something other than a handler name.
_NOT_A_HANDLER_NAME: Final[frozenset[str]] = frozenset({"enabled", "options"})


def _script_text() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


def _live_config_keys() -> frozenset[str]:
    return frozenset(
        getattr(HandlerID, attr).config_key for attr in dir(HandlerID) if attr.isupper()
    )


class TestChecklistNamesAreLive:
    def test_no_retired_handler_is_named(self) -> None:
        text = _script_text()
        named = sorted(name for name in RETIRED_HANDLERS if re.search(rf"\b{name}\b", text))
        assert not named, (
            f"The config-optimisation checklist scores retired handlers {named}. "
            "Nothing can enable them, so every project carries a permanent "
            "phantom deficit and is advised to add dead config keys. Remove "
            "them from the checklist and adjust the area denominators and the "
            "overall total."
        )

    def test_every_dotted_reference_resolves(self) -> None:
        live = _live_config_keys()
        unknown = sorted(
            {
                match.group("name")
                for match in _DOTTED_HANDLER.finditer(_script_text())
                if match.group("name") not in _NOT_A_HANDLER_NAME
                and match.group("name") not in live
            }
        )
        assert not unknown, (
            f"The config-optimisation checklist names handlers that are not in "
            f"the registry: {unknown}."
        )
