"""Stage 2c: the bounded, redacted digest and the model prompt (Plan 00274).

The digest is the privacy bulwark: everything the model ever sees passes
through here. Representatives are normalisation-truncated, secret-redacted
via ``utils.secret_redaction`` and capped by cluster count and total chars.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.skill_scan.constants import (
    COMMANDS_SUBDIR,
    DEFAULT_MAX_CLUSTERS,
    MARKDOWN_SUFFIX,
    MAX_PAYLOAD_CHARS,
    SKILLS_SUBDIR,
)
from claude_code_hooks_daemon.skill_scan.models import Cluster
from claude_code_hooks_daemon.utils.secret_redaction import redact_text

_NO_INVENTORY = "(none)"
_NEWLINE_REPLACEMENT = " "


def build_digest(
    clusters: list[Cluster],
    terms: tuple[str, ...],
    max_clusters: int = DEFAULT_MAX_CLUSTERS,
) -> str:
    """One line per cluster: id, count, distinct sessions, redacted rep."""
    lines: list[str] = []
    for idx, cluster in enumerate(clusters[:max_clusters], start=1):
        rep = redact_text(
            cluster.representative.replace("\n", _NEWLINE_REPLACEMENT), terms
        )
        lines.append(
            f"[{idx}] count={len(cluster.prompts)} sessions={cluster.distinct_sessions} "
            f"rep={rep!r}"
        )
    digest = "\n".join(lines)
    return digest[:MAX_PAYLOAD_CHARS]


def existing_skill_names(project_root: Path) -> list[str]:
    """Names of existing ``.claude/skills/`` and ``.claude/commands/`` entries.

    These are fed to the model so it never suggests what already exists
    (existing-skill suppression). Markdown command files are listed by stem;
    directories by name.
    """
    names: list[str] = []
    for subdir in (SKILLS_SUBDIR, COMMANDS_SUBDIR):
        directory = project_root.joinpath(*subdir)
        if not directory.is_dir():
            continue
        for entry in sorted(directory.iterdir()):
            if entry.name.endswith(MARKDOWN_SUFFIX):
                names.append(entry.name[: -len(MARKDOWN_SUFFIX)])
            else:
                names.append(entry.name)
    return names


def build_model_prompt(digest: str, existing: list[str]) -> str:
    """The rubric prompt around the digest (PLAN.md Decisions 5 and 7)."""
    inventory = ", ".join(existing) if existing else _NO_INVENTORY
    return (
        "You are analysing clustered human prompts from a software project's "
        "Claude Code session transcripts. Each CLUSTERS line is one cluster: "
        "an id, how many times a near-identical prompt occurred, across how "
        "many distinct sessions, and a truncated redacted representative.\n\n"
        "Identify TWO kinds of signal:\n"
        "(a) repeated WORKLOADS - near-identical repeated requests or repeated "
        "multi-step workflows that would make a good Claude Code SKILL;\n"
        "(b) recurring CORRECTIONS or points of confusion the user has to "
        "re-explain - these usually want a doc/CLAUDE.md/rules line rather "
        "than a skill.\n\n"
        "Prefer clusters spanning multiple sessions. Do NOT propose anything "
        f"already covered by these existing skills/commands: {inventory}.\n\n"
        "Answer with STRICT JSON only - no prose, no code fences - matching:\n"
        '{"workloads": [{"name": "<kebab-case-skill-name>", '
        '"purpose": "<one line>", "evidence_cluster_ids": [1, 2]}], '
        '"corrections": [{"name": "<kebab-case-topic>", '
        '"purpose": "<one line, naming the doc/rule remedy>", '
        '"evidence_cluster_ids": [3]}]}\n\n'
        f"CLUSTERS:\n{digest}\n"
    )
