"""DisclosureTracker — per-agent, session-scoped rule disclosure state.

Plan 00116, Phase 2 (Task 2.3).  Decision G (spike-resolved).

Tracks which rules have already had their verbose block delivered to a
specific agent in the current session.  Once a rule is "disclosed" for an
agent, subsequent fires emit only the terse reminder.  Disclosure is cleared
on PreCompact and on clear/new session so that the verbose block is re-delivered
after context loss.

Storage: in-memory ``dict[transcript_path, set[rule_id]]``.

Key design choices (Decision G):
- **Per-agent via transcript_path**: ``session_id`` is shared across all Task
  sub-agents (spike confirmed 440/440 sidechain entries carried the parent
  session_id).  ``transcript_path`` IS per-agent — each sidechain has its own
  transcript file.  Keying by transcript_path gives correct multi-agent
  isolation: sub-agent B never inherits parent agent A's disclosure state.
- **In-memory only**: no state file.  A daemon restart re-discloses (at most
  one extra verbose block per session — acceptable; same failure mode as a
  daemon restart).
- **No file I/O on the transcript**: we only *key* on the path string; we
  never read the file.
- **Thread safety**: a simple ``dict`` is used.  The daemon processes hook
  calls sequentially per agent via the Unix socket; concurrent calls from
  different agents use different transcript_path keys so there is no shared
  mutable state.  If true thread safety is needed in future, a ``threading.Lock``
  can be added without changing the public API.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class DisclosureTracker:
    """Per-agent, session-scoped disclosure state for rule verbose blocks.

    A rule is "disclosed" once its verbose block has been emitted since the
    last reset boundary for that agent.  Boundaries: PreCompact event and
    clear / new session (both carry ``transcript_path``).

    Usage::

        tracker = DisclosureTracker()

        # First fire — not disclosed → emit verbose, then mark
        if not tracker.was_disclosed(transcript_path, rule_id):
            message = formatter.verbose(rule)
            tracker.mark_disclosed(transcript_path, rule_id)
        else:
            message = formatter.terse(rule)

        # On PreCompact / SessionStart clear:
        tracker.reset(transcript_path)
    """

    __slots__ = ("_state",)

    def __init__(self) -> None:
        """Initialise with empty disclosure state."""
        # Outer key: transcript_path (str).
        # Inner value: set of rule_ids already disclosed for that agent.
        self._state: dict[str, set[str]] = {}

    def was_disclosed(self, transcript_path: str, rule_id: str) -> bool:
        """Return True if the verbose block for rule_id has been delivered.

        Args:
            transcript_path: Absolute path to the agent's transcript file.
                             This is the per-agent discriminator (not session_id).
            rule_id:         Rule identifier (from ``RuleID`` constants).

        Returns:
            True if ``mark_disclosed`` was called for this path+rule combination
            since the last ``reset``.  False if no verbose has been delivered yet
            (i.e. the next fire should be verbose).
        """
        agent_state = self._state.get(transcript_path)
        if agent_state is None:
            return False
        return rule_id in agent_state

    def mark_disclosed(self, transcript_path: str, rule_id: str) -> None:
        """Record that the verbose block for rule_id has been delivered.

        Idempotent: calling multiple times is safe and has no effect beyond
        the first call.

        Args:
            transcript_path: Absolute path to the agent's transcript file.
            rule_id:         Rule identifier (from ``RuleID`` constants).
        """
        if transcript_path not in self._state:
            self._state[transcript_path] = set()
        self._state[transcript_path].add(rule_id)
        logger.debug("DisclosureTracker: marked %s disclosed for %s", rule_id, transcript_path)

    def reset(self, transcript_path: str) -> None:
        """Clear all disclosure state for the given agent.

        Called on PreCompact (verbose content was compacted away, so the next
        fire must be verbose again) and on clear / new session.

        Safe to call for an unknown transcript_path (no-op).

        Args:
            transcript_path: Absolute path to the agent's transcript file.
        """
        if transcript_path in self._state:
            del self._state[transcript_path]
            logger.debug("DisclosureTracker: reset state for %s", transcript_path)
