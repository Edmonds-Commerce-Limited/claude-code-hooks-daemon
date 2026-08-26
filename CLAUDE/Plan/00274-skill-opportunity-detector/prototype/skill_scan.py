"""Plan 00274 PROTOTYPE: skill-opportunity detector pipeline.

Throwaway research code — NOT daemon integration. Runs the three-stage
pipeline from BRAINSTORM.md: deterministic extraction of genuine human prompts
from Claude Code jsonl transcripts, deterministic normalise/cluster/redact
aggregation, then one bounded headless Haiku call proposing skill candidates.
Writes a report under untracked/reports/.

Run with the daemon venv python (needs claude_code_hooks_daemon importable):
    PYTHONPATH=/workspace/src <venv-python> skill_scan.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re

# SECURITY: subprocess is used only to invoke the trusted local `claude` CLI
# with a list argv and no shell.
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

DEFAULT_TRANSCRIPT_DIR: Final[str] = str(Path.home() / ".claude" / "projects" / "-workspace")
PROJECT_ROOT: Final[Path] = Path("/workspace")
SECRET_WORD_LIST: Final[Path] = PROJECT_ROOT / ".claude" / "block-words.secret"
REPORT_PATH: Final[Path] = PROJECT_ROOT / "untracked" / "reports" / (
    "skill-opportunities-2026-08-26.md"
)
SKILLS_DIR: Final[Path] = PROJECT_ROOT / ".claude" / "skills"
COMMANDS_DIR: Final[Path] = PROJECT_ROOT / ".claude" / "commands"

USER_RECORD_TYPE: Final[str] = "user"
EXCLUDE_FLAGS: Final[tuple[str, ...]] = (
    "isMeta",
    "isSidechain",
    "isCompactSummary",
    "isVisibleInTranscriptOnly",
)
# Content-level markers (BRAINSTORM.md section 2): a prompt containing one of
# these is machine traffic, not a human.
EXCLUDE_CONTENT_MARKERS: Final[tuple[str, ...]] = (
    "<teammate-message",
    "Another Claude session sent a message",
    "<task-notification",
    "[Request interrupted by user",
    "FAILSAFE RECOVERY CHECK",
    "🤖 [ccy-supervisor",
    "<command-name>",
    "<local-command-stdout>",
    "<system-reminder>",
    "<command-message>",
)

PATH_PLACEHOLDER: Final[str] = "<path>"
SHA_PLACEHOLDER: Final[str] = "<sha>"
NUM_PLACEHOLDER: Final[str] = "<num>"

_PATH_RE: Final[re.Pattern[str]] = re.compile(r"(?:~?/?[\w.\-]+/)+[\w.\-]*")
_SHA_RE: Final[re.Pattern[str]] = re.compile(r"\b[0-9a-f]{7,40}\b")
_NUM_RE: Final[re.Pattern[str]] = re.compile(r"\b\d+\b")
_WS_RE: Final[re.Pattern[str]] = re.compile(r"\s+")

JACCARD_THRESHOLD: Final[float] = 0.5
REPRESENTATIVE_MAX_CHARS: Final[int] = 200
MAX_CLUSTERS_IN_DIGEST: Final[int] = 100
MAX_PAYLOAD_CHARS: Final[int] = 50_000
SECONDS_PER_DAY: Final[int] = 86_400
CLAUDE_TIMEOUT_SECONDS: Final[int] = 300

REPORT_HEADER: Final[str] = (
    "> **PRIVACY**: derived from private session transcripts — review before\n"
    "> sharing outside the project. Representatives are normalised, truncated\n"
    "> and secret-redacted, but redaction is list-based and cannot catch\n"
    "> unlisted secrets.\n"
)


@dataclass(frozen=True)
class Prompt:
    """One genuine human prompt extracted from a transcript."""

    text: str
    session_id: str
    mtime: float


@dataclass
class Cluster:
    """A group of near-identical normalised prompts."""

    key_tokens: frozenset[str]
    prompts: list[Prompt] = field(default_factory=list)

    @property
    def distinct_sessions(self) -> int:
        return len({p.session_id for p in self.prompts})

    @property
    def representative(self) -> str:
        return max(self.prompts, key=lambda p: len(p.text)).text[:REPRESENTATIVE_MAX_CHARS]


@dataclass
class ScanStats:
    """Counters for the schema-drift canary."""

    files: int = 0
    lines: int = 0
    user_records: int = 0
    unparseable: int = 0
    excluded_flags: int = 0
    excluded_blocks: int = 0
    excluded_markers: int = 0
    genuine: int = 0


def _is_genuine_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return all(marker not in stripped for marker in EXCLUDE_CONTENT_MARKERS)


def extract_prompts(
    transcript_dir: Path,
    window_days: int | None,
    stats: ScanStats | None = None,
) -> list[Prompt]:
    """Stage 1: extract genuine human prompts from every jsonl in the window."""
    stats = stats if stats is not None else ScanStats()
    cutoff = time.time() - window_days * SECONDS_PER_DAY if window_days else None
    prompts: list[Prompt] = []
    for path in sorted(transcript_dir.glob("*.jsonl")):
        mtime = path.stat().st_mtime
        if cutoff is not None and mtime < cutoff:
            continue
        stats.files += 1
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stats.lines += 1
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    stats.unparseable += 1
                    continue
                if not isinstance(record, dict) or record.get("type") != USER_RECORD_TYPE:
                    continue
                stats.user_records += 1
                if any(record.get(flag) for flag in EXCLUDE_FLAGS):
                    stats.excluded_flags += 1
                    continue
                message = record.get("message")
                content = message.get("content") if isinstance(message, dict) else None
                if not isinstance(content, str):
                    stats.excluded_blocks += 1
                    continue
                if not _is_genuine_text(content):
                    stats.excluded_markers += 1
                    continue
                stats.genuine += 1
                prompts.append(
                    Prompt(
                        text=content.strip(),
                        session_id=str(record.get("sessionId", path.stem)),
                        mtime=mtime,
                    )
                )
    return prompts


def normalise(text: str) -> str:
    """Stage 2a: lowercase and replace paths/shas/numbers with placeholders."""
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
    """Stage 2b: greedy token-set Jaccard clustering over normalised prompts."""
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
    clusters.sort(key=lambda c: (c.distinct_sessions, len(c.prompts)), reverse=True)
    return clusters


def _load_redaction_terms() -> tuple[str, ...]:
    try:
        from claude_code_hooks_daemon.utils import secret_redaction
    except ImportError:
        print("WARN: daemon utils not importable; secret-list redaction skipped")
        return ()
    if not SECRET_WORD_LIST.exists():
        return ()
    return secret_redaction.load_secret_terms(SECRET_WORD_LIST)


def _redact(text: str, terms: tuple[str, ...]) -> str:
    if not terms:
        return text
    from claude_code_hooks_daemon.utils import secret_redaction

    return secret_redaction.redact_text(text, terms)


def _existing_skill_names() -> list[str]:
    names: list[str] = []
    for directory in (SKILLS_DIR, COMMANDS_DIR):
        if directory.is_dir():
            names.extend(
                sorted(p.name for p in directory.iterdir() if not p.name.endswith(".md"))
            )
    return names


def build_digest(clusters: list[Cluster], terms: tuple[str, ...]) -> str:
    """Stage 2c: the bounded, redacted digest that is all Haiku ever sees."""
    lines: list[str] = []
    for idx, cluster in enumerate(clusters[:MAX_CLUSTERS_IN_DIGEST], start=1):
        rep = _redact(cluster.representative.replace("\n", " "), terms)
        lines.append(
            f"[{idx}] count={len(cluster.prompts)} sessions={cluster.distinct_sessions} "
            f"rep={rep!r}"
        )
    digest = "\n".join(lines)
    if len(digest) > MAX_PAYLOAD_CHARS:
        digest = digest[:MAX_PAYLOAD_CHARS]
    return digest


def build_haiku_prompt(digest: str, existing: list[str]) -> str:
    return (
        "You are analysing clustered human prompts from a software project's "
        "Claude Code session transcripts. Each line is one cluster: an id, how "
        "many times a near-identical prompt occurred, across how many distinct "
        "sessions, and a truncated redacted representative.\n\n"
        "Identify (a) repeated workloads and (b) recurring points of confusion "
        "or re-explanation, and propose concrete Claude Code SKILL candidates. "
        "For each: a kebab-case name, a one-line purpose, and the cluster ids "
        "that are the evidence. Prefer clusters spanning multiple sessions. "
        "Do NOT propose anything already covered by these existing "
        f"skills/commands: {', '.join(existing) or '(none)'}.\n"
        "Also flag clusters that want a doc/CLAUDE.md line rather than a "
        "skill. Answer in concise markdown.\n\n"
        f"CLUSTERS:\n{digest}\n"
    )


def call_haiku(prompt: str) -> tuple[str | None, str | None]:
    """Stage 3: one bounded headless Haiku call. Returns (output, error)."""
    argv = ["claude", "-p", prompt, "--model", "haiku"]
    try:
        # SECURITY: list argv, trusted local CLI, no shell interpretation.
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT_SECONDS,
            check=False,
            cwd=str(PROJECT_ROOT),
        )
    except FileNotFoundError:
        return None, "claude CLI not found on PATH"
    except subprocess.TimeoutExpired:
        return None, f"claude CLI timed out after {CLAUDE_TIMEOUT_SECONDS}s"
    if result.returncode != 0:
        detail = (result.stderr.strip() or result.stdout.strip())[:500]
        return None, f"claude CLI exited {result.returncode}: {detail}"
    return result.stdout.strip(), None


def write_report(
    clusters: list[Cluster],
    stats: ScanStats,
    terms: tuple[str, ...],
    haiku_output: str | None,
    haiku_error: str | None,
    existing: list[str],
) -> Path:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    multi = [c for c in clusters if len(c.prompts) > 1]
    lines: list[str] = [
        "# Skill Opportunity Report — 2026-08-26 (Plan 00274 prototype)",
        "",
        REPORT_HEADER,
        "## Scan statistics",
        "",
        f"- Transcript files scanned: {stats.files} ({stats.lines} lines)",
        f"- `type: user` records: {stats.user_records}",
        f"- Excluded by field flags (meta/sidechain/compaction): {stats.excluded_flags}",
        f"- Excluded block-content (tool results etc.): {stats.excluded_blocks}",
        f"- Excluded by content markers (machine traffic): {stats.excluded_markers}",
        f"- Genuine human prompts: {stats.genuine}",
        f"- Unparseable lines (schema-drift canary): {stats.unparseable}",
        f"- Clusters: {len(clusters)} total, {len(multi)} with repetition",
        f"- Existing skills/commands suppressed: {', '.join(existing) or '(none)'}",
        "",
        "## Top repeated clusters (deterministic)",
        "",
    ]
    for idx, cluster in enumerate(multi[:25], start=1):
        rep = _redact(cluster.representative.replace("\n", " "), terms)
        lines.append(
            f"{idx}. **{len(cluster.prompts)}x / {cluster.distinct_sessions} session(s)** — "
            f"`{rep}`"
        )
    lines.append("")
    lines.append("## Haiku skill suggestions")
    lines.append("")
    if haiku_output:
        lines.append(_redact(haiku_output, terms))
    else:
        lines.append(f"_Model stage skipped: {haiku_error or 'dry run'}_")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return REPORT_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript-dir", default=DEFAULT_TRANSCRIPT_DIR)
    parser.add_argument("--window-days", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    stats = ScanStats()
    prompts = extract_prompts(Path(args.transcript_dir), args.window_days, stats)
    clusters = cluster_prompts(prompts)
    terms = _load_redaction_terms()
    existing = _existing_skill_names()
    digest = build_digest(clusters, terms)
    haiku_prompt = build_haiku_prompt(digest, existing)

    print(
        f"files={stats.files} lines={stats.lines} user_records={stats.user_records} "
        f"genuine={stats.genuine} clusters={len(clusters)} "
        f"payload_chars={len(haiku_prompt)}"
    )
    if args.dry_run:
        print("--- DRY RUN: prompt that would be sent to Haiku ---")
        print(haiku_prompt)
        return 0

    haiku_output, haiku_error = call_haiku(haiku_prompt)
    if haiku_error:
        print(f"WARN: {haiku_error}")
    report = write_report(clusters, stats, terms, haiku_output, haiku_error, existing)
    print(f"Report written: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
