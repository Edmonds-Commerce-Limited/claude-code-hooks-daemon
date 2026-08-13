"""Verdict log reporting (Plan 00209 Task 2.5): ``hooks-daemon verdicts``.

Pure aggregation over parsed ``verdicts.jsonl`` records (see
``daemon/verdict_log.py`` for the writer). Answers the field report's
concrete questions:

- Which handlers actually earn their keep, and which have never fired?
- What is the verdict mix (allow/deny/ask/override) per handler?
- What is the override rate — the strongest available signal that a rule is
  mis-tuned?

Plan 00206 lesson, restated here deliberately (Task 2.4): ``verdicts.jsonl``
is a bounded ROLLING SAMPLE (the same ``cap_log_file`` retention primitive
as every other daemon JSONL log), NOT a durable lifetime counter. Every
number this module produces describes the RETAINED WINDOW only. Presenting
them as lifetime totals would repeat exactly the mistake Plan 00206 found —
so ``format_report`` always says so, not just the module docstring.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_WINDOW_CAVEAT = (
    "NOTE: these figures describe the RETAINED WINDOW of verdicts.jsonl "
    "(a bounded rolling sample, capped like every other daemon JSONL log) — "
    "they are NOT lifetime totals. A handler that fired long ago and was "
    "since trimmed from the log will not appear here.\n"
    "Status-line renders are not recorded and status handlers are omitted "
    "from the roster below: a renderer can only ever return 'allow', so its "
    "records carry no information while arriving at the refresh rate.\n"
    "'Never fired' is NOT evidence a handler is pointless. A guard on a rare, "
    "catastrophic operation is SUPPOSED to sit silent — rarity is what success "
    "looks like for it. Read this list as 'not exercised in this window', and "
    "establish 'cannot fire' from the code before concluding anything."
)


def read_verdict_records(path: Path) -> list[dict[str, Any]]:
    """Parse ``verdicts.jsonl`` into a list of dicts.

    Best-effort: a missing file is an empty report (not an error — the log
    may simply not have accumulated anything yet, or verdict logging may be
    disabled). Malformed lines are skipped rather than aborting the whole
    report — one corrupted append (e.g. a crash mid-write) should not hide
    every other decision recorded around it.
    """
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def aggregate_verdicts(
    records: list[dict[str, Any]],
    all_handlers: list[str] | None = None,
) -> dict[str, Any]:
    """Aggregate parsed verdict records into report-ready statistics.

    Args:
        records: Parsed ``verdicts.jsonl`` lines (see ``read_verdict_records``).
        all_handlers: The full set of currently-registered handler names, if
            known (e.g. from a running daemon's ``handlers`` listing). When
            provided, ``never_fired`` lists handlers absent from ``records``.
            ``None`` when the caller could not determine the full handler
            set (e.g. daemon not running) — ``never_fired`` is then ``None``
            rather than a misleadingly empty list.

    Returns:
        Dict with ``total_records``, ``handler_counts`` (excludes the
        synthetic escape-hatch-override entries, which carry
        ``handler: None``), ``handler_verdict_mix`` (per-handler breakdown),
        ``verdict_mix`` (overall, includes ``"override"``),
        ``override_count``, ``override_rate``, and ``never_fired``.
    """
    handler_counts: dict[str, int] = {}
    handler_verdict_mix: dict[str, dict[str, int]] = {}
    verdict_mix: dict[str, int] = {}
    override_count = 0

    for record in records:
        verdict = str(record.get("verdict", "unknown"))
        verdict_mix[verdict] = verdict_mix.get(verdict, 0) + 1

        if record.get("overridden"):
            override_count += 1

        handler = record.get("handler")
        if not handler:
            # Synthetic escape-hatch-override line — no specific handler to
            # attribute a fire count to (see verdict_log.py's docstring).
            continue
        handler_counts[handler] = handler_counts.get(handler, 0) + 1
        per_handler = handler_verdict_mix.setdefault(handler, {})
        per_handler[verdict] = per_handler.get(verdict, 0) + 1

    total_records = len(records)
    override_rate = (override_count / total_records) if total_records else 0.0

    never_fired: list[str] | None = None
    if all_handlers is not None:
        never_fired = sorted(set(all_handlers) - set(handler_counts))

    return {
        "total_records": total_records,
        "handler_counts": handler_counts,
        "handler_verdict_mix": handler_verdict_mix,
        "verdict_mix": verdict_mix,
        "override_count": override_count,
        "override_rate": override_rate,
        "never_fired": never_fired,
    }


def format_report(aggregate: dict[str, Any]) -> str:
    """Render an aggregate dict as a human-readable text report."""
    lines: list[str] = [_WINDOW_CAVEAT, ""]

    total = aggregate["total_records"]
    lines.append(f"Total recorded decisions: {total}")
    lines.append(
        f"Overrides (MUST_..._BECAUSE used): {aggregate['override_count']} "
        f"({aggregate['override_rate']:.1%})"
    )
    lines.append("")

    handler_counts: dict[str, int] = aggregate["handler_counts"]
    if handler_counts:
        lines.append("Per-handler fire counts:")
        for handler, count in sorted(handler_counts.items(), key=lambda kv: -kv[1]):
            mix = aggregate["handler_verdict_mix"].get(handler, {})
            mix_text = ", ".join(f"{v}={c}" for v, c in sorted(mix.items()))
            lines.append(f"  {handler}: {count} ({mix_text})")
    else:
        lines.append("Per-handler fire counts: (none recorded)")
    lines.append("")

    verdict_mix: dict[str, int] = aggregate["verdict_mix"]
    if verdict_mix:
        lines.append("Verdict mix (all handlers, includes overrides):")
        for verdict, count in sorted(verdict_mix.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {verdict}: {count}")
    lines.append("")

    never_fired = aggregate["never_fired"]
    if never_fired is None:
        lines.append("Never-fired handlers: unavailable (daemon not running)")
    elif never_fired:
        lines.append(f"Never-fired handlers ({len(never_fired)}):")
        for handler in never_fired:
            lines.append(f"  {handler}")
    else:
        lines.append("Never-fired handlers: none — every registered handler fired")

    return "\n".join(lines)
