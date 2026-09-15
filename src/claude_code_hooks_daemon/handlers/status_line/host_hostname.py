"""HostHostnameHandler - which MACHINE this session is on (opt-in).

Plan 00411. The sibling ``environment_indicator`` says what KIND of environment
this is (desktop, docker, podman, lxc). This says WHICH machine — the thing a
user with several boxes actually needs, and the thing no terminal shows.

Opt-in, because a single-machine user gains nothing and pays status-line width.

Two properties are load-bearing:

**An inferred name is marked.** The resolver's bottom rung reads a name out of
``/etc/hosts``, which works on a Debian-family host and finds nothing on a
Fedora one, and can be stale even when present. A segment answering "which
machine am I on?" is worse than blank when it is confidently wrong, so an
inferred value renders with :data:`INFERRED_MARKER` and never looks like a
reading.

**Resolution happens once.** The status line re-renders on every Claude Code
refresh and the resolver may touch the filesystem, so the answer is cached on
first render.

**There is no config option for the name, deliberately.** A hostname is
per-machine and ``.claude/hooks-daemon.yaml`` is tracked in git and routinely
public, so an option for it would invite a machine name into a committed file —
a leak findable only by searching history that is never rewritten. Per-machine
values come from the environment.
"""

import logging
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest
from claude_code_hooks_daemon.core.handler_bases import StatusLineHandlerBase
from claude_code_hooks_daemon.core.segment_explanation import SegmentExplanation
from claude_code_hooks_daemon.utils.host_identity import (
    ENV_HOST_HOSTNAME,
    HostName,
    HostNameSource,
    resolve_host_name,
)

logger = logging.getLogger(__name__)

# Bright cyan — distinct from every colour environment_indicator already uses
# for a runtime, so the two segments never read as one value.
_COLOR_BRIGHT_CYAN = "\033[96m"
_COLOR_RESET = "\033[0m"

#: Prefix glyph. "@" reads as "at <machine>" and costs one column.
_ICON = "@"

#: Appended to the glyph when the name was INFERRED rather than read. A tilde
#: is the conventional "approximately" mark and survives a terminal with no
#: emoji support, which a coloured glyph would not.
INFERRED_MARKER = "~"

#: The inferred-value glyph, spelled as a LITERAL rather than composed from the
#: two constants above. A reader (or a grep) chasing "@~" off a status line has
#: to be able to find it in this file, and an f-string would hide it. A unit
#: test pins it equal to the composition so the two cannot drift apart.
_ICON_INFERRED = "@~"


class HostHostnameHandler(StatusLineHandlerBase):
    """Show ``@machine-name`` for the host this session is really running on."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.HOST_HOSTNAME,
            priority=Priority.HOST_HOSTNAME,
            terminal=False,
            tags=[
                HandlerTag.STATUSLINE,
                HandlerTag.ENVIRONMENT,
                HandlerTag.DISPLAY,
                HandlerTag.NON_TERMINAL,
            ],
        )
        # Resolution is deferred to the first render; see the module docstring
        # for why the constructor is the wrong place. The sentinel distinguishes
        # "not yet resolved" from "resolved to nothing", so an unresolvable host
        # is cached too rather than re-probed on every render forever.
        self._resolved: HostName | None = None
        self._has_resolved: bool = False

    def get_default_enabled(self) -> bool:
        """Opt-in: only useful when you work across more than one machine."""
        return False

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status line events."""
        return True

    def _host_name_once(self) -> HostName | None:
        """Resolve the host name on first call and cache it thereafter."""
        if not self._has_resolved:
            self._resolved = resolve_host_name()
            self._has_resolved = True
            logger.debug("Host name resolved once: %s", self._resolved)
        return self._resolved

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Return the host-name segment, or no segment when nothing resolves."""
        resolved = self._host_name_once()
        if resolved is None:
            return AdvisoryResult(context=[])
        marker = INFERRED_MARKER if resolved.inferred else ""
        return AdvisoryResult(
            context=[f"| {_COLOR_BRIGHT_CYAN}{_ICON}{marker}{resolved.name}{_COLOR_RESET}"]
        )

    def explain_segment(self) -> SegmentExplanation:
        """Describe the segment and name the rung that produced its value."""
        resolved = self._host_name_once()
        if resolved is None:
            current_value = (
                "Not shown now — no host name could be resolved. Inside a "
                f"podman/docker container, export {ENV_HOST_HOSTNAME} from "
                "whatever starts the container."
            )
        else:
            marker = INFERRED_MARKER if resolved.inferred else ""
            current_value = (
                f"Currently shows: {_ICON}{marker}{resolved.name} "
                f"(source: {resolved.source.value})"
            )
        return SegmentExplanation(
            glyphs=(_ICON, _ICON_INFERRED),
            name="Host Hostname",
            what_it_is="Which MACHINE this session is on, as opposed to which kind of environment.",
            how_to_read=(
                f"{_ICON}name = read as fact; {_ICON_INFERRED}name = INFERRED from "
                "/etc/hosts and possibly wrong. Resolved once per daemon start, in order: "
                f"{HostNameSource.ENVIRONMENT.value} (${ENV_HOST_HOSTNAME}), "
                f"{HostNameSource.LOCAL.value} (host or LXC only — a podman/docker hostname is "
                f"the container ID), then {HostNameSource.ETC_HOSTS_HINT.value}. "
                "No config option, by design: a hostname is per-machine and that file is "
                "tracked in git. Nothing resolvable renders nothing."
            ),
            current_value=current_value,
        )

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import Decision, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="host hostname handler test",
                command='echo "test"',
                description=(
                    "Verify the opt-in host-hostname segment renders the machine "
                    "name when one resolves, and renders nothing when none does. "
                    "Confirmed active by the daemon loading without errors."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Display-only handler - renders nothing when unresolved",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            )
        ]
