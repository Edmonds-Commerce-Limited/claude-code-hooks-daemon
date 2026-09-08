"""Shared relevance predicate for the flaggable-content workflow (Plan 00330).

``flaggable_work_advisor``, ``flaggable_content_channel_guard`` and
``quarantine_artefact_read_guard`` all exist to route flaggable material
through the quarantine subagent. Without that agent deployed there is
nothing to delegate to, so the config-optimisation review reports the trio
as "not applicable here" rather than as three shortfalls. One predicate,
three callers, so the three cannot drift on what "deployed" means.
"""

from __future__ import annotations

from typing import Final

from claude_code_hooks_daemon.core.relevance import Relevance, RelevanceContext

#: The agent name the installer ships as ``install/templates/agents/<name>.md``
#: and the handlers' default ``quarantine_agent`` option.
QUARANTINE_AGENT_NAME: Final[str] = "hooks-daemon-opus-security"


def quarantine_agent_relevance(context: RelevanceContext) -> Relevance:
    """Relevant iff the quarantine agent definition is deployed to the project."""
    return Relevance.when(
        context.has_file(".claude", "agents", f"{QUARANTINE_AGENT_NAME}.md"),
        present=f"the {QUARANTINE_AGENT_NAME} quarantine agent is deployed",
        absent=(
            f"no {QUARANTINE_AGENT_NAME} agent under .claude/agents/ "
            "(the flaggable-content workflow is not set up here)"
        ),
    )
