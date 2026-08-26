"""Stage 3: the model invocation boundary (Plan 00274).

``ModelInvoker`` is the injectable dependency (Plan 00266 pattern) so the
pipeline and its tests never spawn a real CLI. ``ClaudeCliInvoker`` shells
out to headless ``claude -p`` (PLAN.md Decision 5: CLI-auth only in v1; no
API-key fallback). Every failure degrades to an error string — never a raise
(00266 fail-open rule).
"""

from __future__ import annotations

import json
import logging

# SECURITY: subprocess invokes only the trusted local `claude` CLI with a
# list argv and no shell.
import subprocess
from dataclasses import dataclass
from typing import Protocol

from claude_code_hooks_daemon.skill_scan.constants import (
    CLAUDE_CLI_BINARY,
    MODEL_ERROR_DETAIL_MAX_CHARS,
    MODEL_TIMEOUT_SECONDS,
    NOT_LOGGED_IN_MARKER,
)

logger = logging.getLogger(__name__)

_WORKLOADS_KEY = "workloads"
_CORRECTIONS_KEY = "corrections"
_NAME_KEY = "name"
_PURPOSE_KEY = "purpose"
_EVIDENCE_KEY = "evidence_cluster_ids"
_CODE_FENCE = "```"

_NO_AUTH_REMEDY = (
    " (headless claude -p has no auth here - log in with `claude` or run "
    "`bin/hooks-daemon skill-scan` from an authenticated environment)"
)


class ModelInvoker(Protocol):
    """Anything that can turn a prompt into (output, error)."""

    def invoke(self, prompt: str) -> tuple[str | None, str | None]:
        """Return (stdout, None) on success or (None, reason) on failure."""
        ...


@dataclass(frozen=True)
class Suggestion:
    """One model-proposed skill or doc candidate."""

    name: str
    purpose: str
    evidence_cluster_ids: tuple[int, ...]


@dataclass(frozen=True)
class ModelSuggestions:
    """Parsed model output: workloads (skills) vs corrections (docs)."""

    workloads: tuple[Suggestion, ...]
    corrections: tuple[Suggestion, ...]


class ClaudeCliInvoker:
    """Headless ``claude -p --model <model>`` invocation, fail-open."""

    def __init__(self, model: str) -> None:
        self._model = model

    def invoke(self, prompt: str) -> tuple[str | None, str | None]:
        """One bounded headless model call. Returns (output, error)."""
        argv = [CLAUDE_CLI_BINARY, "-p", prompt, "--model", self._model]
        try:
            # SECURITY: list argv, trusted local CLI, no shell interpretation.
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=MODEL_TIMEOUT_SECONDS,
                check=False,
            )
        except FileNotFoundError:
            return None, f"{CLAUDE_CLI_BINARY} CLI not found on PATH"
        except subprocess.TimeoutExpired:
            return None, f"{CLAUDE_CLI_BINARY} CLI timed out after {MODEL_TIMEOUT_SECONDS}s"
        if result.returncode != 0:
            detail = (result.stderr.strip() or result.stdout.strip())[
                :MODEL_ERROR_DETAIL_MAX_CHARS
            ]
            error = f"{CLAUDE_CLI_BINARY} CLI exited {result.returncode}: {detail}"
            if NOT_LOGGED_IN_MARKER in detail:
                error += _NO_AUTH_REMEDY
            return None, error
        return result.stdout.strip(), None


def _parse_suggestion_list(raw: object) -> tuple[Suggestion, ...]:
    if not isinstance(raw, list):
        return ()
    suggestions: list[Suggestion] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get(_NAME_KEY)
        purpose = item.get(_PURPOSE_KEY)
        if not isinstance(name, str) or not name:
            continue
        evidence_raw = item.get(_EVIDENCE_KEY)
        evidence = (
            tuple(entry for entry in evidence_raw if isinstance(entry, int))
            if isinstance(evidence_raw, list)
            else ()
        )
        suggestions.append(
            Suggestion(
                name=name,
                purpose=purpose if isinstance(purpose, str) else "",
                evidence_cluster_ids=evidence,
            )
        )
    return tuple(suggestions)


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if not text.startswith(_CODE_FENCE):
        return text
    lines = text.splitlines()
    body = [line for line in lines if not line.startswith(_CODE_FENCE)]
    return "\n".join(body).strip()


def parse_model_output(raw: str) -> ModelSuggestions | None:
    """Strict-JSON parse of the model's answer, ``None`` on garbage.

    Degrade-to-raw-notes is the CALLER's job: a ``None`` here means the raw
    text should be appended to the report as unparsed model notes.
    """
    try:
        parsed = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError:
        logger.debug("Model output was not valid JSON")
        return None
    if not isinstance(parsed, dict):
        return None
    return ModelSuggestions(
        workloads=_parse_suggestion_list(parsed.get(_WORKLOADS_KEY)),
        corrections=_parse_suggestion_list(parsed.get(_CORRECTIONS_KEY)),
    )
