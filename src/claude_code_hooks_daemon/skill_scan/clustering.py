"""Stage 2a/2b: normalisation and clustering (Plan 00274).

Heuristic fixed by PLAN.md Decision 4: token-set Jaccard similarity over
normalised prompts with a greedy threshold of 0.5 — measured equivalent to
character trigrams on the real corpus and 4-5x faster, with zero
dependencies.
"""

from __future__ import annotations

import re
from typing import Final

from claude_code_hooks_daemon.skill_scan.constants import (
    JACCARD_THRESHOLD,
    NUM_PLACEHOLDER,
    PATH_PLACEHOLDER,
    SHA_PLACEHOLDER,
)
from claude_code_hooks_daemon.skill_scan.models import Cluster, Prompt

_PATH_RE: Final[re.Pattern[str]] = re.compile(r"(?:~?/?[\w.\-]+/)+[\w.\-]*")
_SHA_RE: Final[re.Pattern[str]] = re.compile(r"\b[0-9a-f]{7,40}\b")
_NUM_RE: Final[re.Pattern[str]] = re.compile(r"\b\d+\b")
_WS_RE: Final[re.Pattern[str]] = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Lowercase and replace paths/shas/numbers with placeholders.

    This is what lets 'fix test in tests/unit/x.py' and
    'fix test in tests/unit/y.py' cluster together — and doubles as a
    privacy layer, since path material never reaches the digest verbatim.
    """
    out = text.lower()
    out = _PATH_RE.sub(PATH_PLACEHOLDER, out)
    out = _SHA_RE.sub(SHA_PLACEHOLDER, out)
    out = _NUM_RE.sub(NUM_PLACEHOLDER, out)
    return _WS_RE.sub(" ", out).strip()


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cluster_prompts(prompts: list[Prompt]) -> list[Cluster]:
    """Greedy token-set Jaccard clustering over normalised prompts.

    Returns clusters ranked by distinct-session count then size —
    repetition ACROSS sessions is the skill signal.
    """
    clusters: list[Cluster] = []
    for prompt in prompts:
        tokens = frozenset(normalise(prompt.text).split())
        best: Cluster | None = None
        best_score = 0.0
        for cluster in clusters:
            score = _jaccard(tokens, cluster.key_tokens)
            if score >= JACCARD_THRESHOLD and score > best_score:
                best, best_score = cluster, score
        if best is None:
            clusters.append(Cluster(key_tokens=tokens, prompts=[prompt]))
        else:
            best.prompts.append(prompt)
    clusters.sort(
        key=lambda cluster: (cluster.distinct_sessions, len(cluster.prompts)),
        reverse=True,
    )
    return clusters
