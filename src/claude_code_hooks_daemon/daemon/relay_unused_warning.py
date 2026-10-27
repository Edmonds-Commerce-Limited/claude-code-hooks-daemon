"""The warning line an answer carries when the relay guard fell through (Plan 00529).

The generated relay guard takes the bash path when the configured relay binary
is missing or cannot run, and init.sh then puts the binary's path in the request
envelope (``RequestEnvelopeField.RELAY_UNUSED``). Every answer to such a request
names the binary and the fix, until the fix is run.

The line is added to the SERIALISED response, never to the ``HookResult``. Some
formatters turn context into a decision: a PermissionRequest ALLOW that carries
context emits ``decision.behavior = "allow"``, so a silent "no opinion" would
become an approval. Here only a text key is ever added, which the decision-view
test pins for every relay-eligible event.
"""

import copy
import functools
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants.events import wired_event_metas
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.response_schemas import RESPONSE_SCHEMAS
from claude_code_hooks_daemon.install.relay_deploy import relay_binary_missing_warning
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command
from claude_code_hooks_daemon.utils.relay_host import relay_fix_subcommand

RELAY_UNUSED_WARNING_PREFIX: Final[str] = "WARNING: "

_HOOK_SPECIFIC_OUTPUT: Final[str] = "hookSpecificOutput"
_HOOK_EVENT_NAME: Final[str] = "hookEventName"
_ADDITIONAL_CONTEXT: Final[str] = "additionalContext"
_SYSTEM_MESSAGE: Final[str] = "systemMessage"
#: The same separators the response encoders use for each channel.
_CONTEXT_SEPARATOR: Final[str] = "\n\n"
_SYSTEM_MESSAGE_SEPARATOR: Final[str] = "\n"


@functools.cache
def _relay_eligible_events() -> frozenset[EventType]:
    return frozenset(m.wire_key for m in wired_event_metas() if m.relay_eligible)


def is_relay_eligible_event(event: EventType) -> bool:
    """True when the event's forwarder carries the relay guard."""
    return event in _relay_eligible_events()


def relay_unused_warning_text(binary: str) -> str:
    """The warning line: the text ``status``, the status line and SessionStart use."""
    return RELAY_UNUSED_WARNING_PREFIX + relay_binary_missing_warning(
        Path(binary), daemon_cli_command("transport", relay_fix_subcommand())
    )


def _has_context_channel(event: EventType) -> bool:
    """True when the event's response schema declares hookSpecificOutput.additionalContext."""
    schema = RESPONSE_SCHEMAS.get(event.value)
    if schema is None:
        return False
    hook_output = schema.get("properties", {}).get(_HOOK_SPECIFIC_OUTPUT, {})
    return _ADDITIONAL_CONTEXT in hook_output.get("properties", {})


def _appended(existing: object, line: str, separator: str) -> str:
    if isinstance(existing, str) and existing:
        return existing + separator + line
    return line


def add_relay_unused_warning(
    response: dict[str, Any], event: EventType, binary: str
) -> dict[str, Any]:
    """Return a copy of ``response`` carrying the unused-relay warning line.

    The line goes to ``hookSpecificOutput.additionalContext`` when the event's
    schema has that field, else to the top-level ``systemMessage``. No other
    key is added or changed, so the decision is the one ``response`` carried.

    Raises:
        ValueError: ``event`` is not relay-eligible; its forwarder has no relay
            guard, so a marker on it is a protocol defect.
    """
    if not is_relay_eligible_event(event):
        raise ValueError(f"{event.value} is not relay-eligible; it cannot carry relay_unused")
    line = relay_unused_warning_text(binary)
    warned = copy.deepcopy(response)
    if _has_context_channel(event):
        hook_output = warned.setdefault(_HOOK_SPECIFIC_OUTPUT, {_HOOK_EVENT_NAME: event.value})
        hook_output[_ADDITIONAL_CONTEXT] = _appended(
            hook_output.get(_ADDITIONAL_CONTEXT), line, _CONTEXT_SEPARATOR
        )
    else:
        warned[_SYSTEM_MESSAGE] = _appended(
            warned.get(_SYSTEM_MESSAGE), line, _SYSTEM_MESSAGE_SEPARATOR
        )
    return warned


__all__ = [
    "RELAY_UNUSED_WARNING_PREFIX",
    "add_relay_unused_warning",
    "is_relay_eligible_event",
    "relay_unused_warning_text",
]
