"""Detect a project's dedicated full-QA runner agent (Plan 00518).

``subagent_full_qa_blocker`` denies a full-suite QA command in any sub-agent, so
a project that delegates its full pipeline to one dedicated agent used to be told
to leave the handler off. ``exempt_agent_types`` lets the handler stay on; this
module finds the agent type to list.

The signal is the agent's NAME (frontmatter ``name``, else the file stem): its
tokens, split on ``-`` and ``_``, must contain ``full``, ``runner`` and one of
``qa``/``pipeline``/``gate``/``suite``. That matches ``qa-full-runner`` and
php-qa-ci's ``php-qa-ci_full-pipeline-runner`` and rejects the targeted-only
``qa-runner`` and a ``full-qa-fixer``. A description is prose and cannot be
matched conservatively (``qa-runner``'s says it never runs the full suite).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

logger = logging.getLogger(__name__)

_AGENTS_DIR: Final[tuple[str, ...]] = (".claude", "agents")
_NAME_FIELD: Final[re.Pattern[str]] = re.compile(r"^name:\s*(\S+)\s*$", re.MULTILINE)
_FRONTMATTER_DELIMITER: Final[str] = "---"
_TOKEN_SPLIT: Final[re.Pattern[str]] = re.compile(r"[-_]+")
_REQUIRED_TOKENS: Final[frozenset[str]] = frozenset({"full", "runner"})
_SCOPE_TOKENS: Final[frozenset[str]] = frozenset({"qa", "pipeline", "gate", "suite"})


def _readable_agent_files(agents_dir: Path) -> Iterator[tuple[Path, str]]:
    """Each agent file with its text; one that cannot be read or decoded is left out.

    One broken agent file must not abort the whole optimise review.
    """
    for agent_file in agents_dir.glob("*.md"):
        try:
            text = agent_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            log_and_continue(
                logger,
                e,
                reason=f"an unreadable agent file {agent_file} cannot name a runner type, so it is left out of the proposal",
                level=logging.DEBUG,
            )
            continue
        yield agent_file, text


def _agent_type(agent_file: Path, text: str) -> str:
    """The definition type of an agent file: frontmatter ``name``, else the stem."""
    if text.startswith(_FRONTMATTER_DELIMITER):
        frontmatter = text.split(_FRONTMATTER_DELIMITER, 2)[1]
        match = _NAME_FIELD.search(frontmatter)
        if match:
            return match.group(1)
    return agent_file.stem


def _is_full_qa_runner(agent_type: str) -> bool:
    tokens = {token.lower() for token in _TOKEN_SPLIT.split(agent_type) if token}
    return tokens >= _REQUIRED_TOKENS and bool(tokens & _SCOPE_TOKENS)


def find_full_qa_runner_agents(project_root: Path) -> tuple[str, ...]:
    """Agent types under ``<project_root>/.claude/agents`` that run the full QA suite.

    Returns:
        The distinct matching types, sorted; empty when there is no agents
        directory or no agent qualifies.
    """
    agents_dir = project_root.joinpath(*_AGENTS_DIR)
    if not agents_dir.is_dir():
        return ()
    types = {_agent_type(path, text) for path, text in _readable_agent_files(agents_dir)}
    return tuple(sorted(t for t in types if _is_full_qa_runner(t)))
