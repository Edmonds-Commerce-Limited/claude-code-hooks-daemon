# Design: Data-Driven Promotion (the "cake and eat it" hybrid)

Maintainer direction (2026-08-31, verbatim intent): *count real blocks from
transcripts, and DO include full up-front guidance for commonly triggered
handlers — real-data-driven promotion for relevant handlers; dormant-but-active
handlers stay fully active but progressively disclose their docs.*

This amends the original all-or-nothing Phase 5 ("injector emits the rule table
only") into a **two-tier injected block**:

## The two tiers

| Tier            | Which handlers                                                     | Always-on content                                                | Block-time behaviour                                                       |
| --------------- | ------------------------------------------------------------------ | ---------------------------------------------------------------- | -------------------------------------------------------------------------- |
| **PROMOTED**    | Blocking handlers that REALLY fire often in this project's history | Full `get_claude_md()` guidance stays resident, exactly as today | Unchanged (rules/IDs still declared for explain-rule parity)               |
| **PROGRESSIVE** | Blocking handlers that rarely/never fire ("dormant but active")    | One rule-table row per rule (ID, blocked, why, one-line fix)     | Verbose on FIRST fire per agent, terse after, reset on compact/new session |
| **ADVISORY**    | Non-blocking handlers (Decision C, unchanged)                      | Lighter entry                                                    | n/a                                                                        |

Enforcement is IDENTICAL across tiers — promotion affects only where the
documentation lives. A progressive handler blocks exactly as it always did;
the first block teaches verbosely, precisely because its docs are not resident.

## Why this is strictly better than either extreme

- Table-only (original Phase 5): cheapest, but an agent repeatedly tripping
  `pipe_blocker` pays a verbose block once per compact cycle and the guidance
  that PREVENTS the trip was never resident — for hot handlers, prevention
  beats teaching-after-the-fact.
- Everything-resident (status quo): 28.6k tokens every turn, mostly for
  handlers that have never fired once in months of transcripts.
- Hybrid: resident budget is spent where measured reality says blocks actually
  happen; everything else pays ~1 table row.

## Measurement: `bin/hooks-daemon block-report`

A re-runnable analyser producing per-handler (and, once rule IDs are live,
per-rule) REAL block counts:

1. **Data source — transcripts** (primary): stream every
   `~/.claude/projects/<slug>/*.jsonl` (same streaming pattern as Plan 00293's
   `tool_report/analyser.py`; same privacy contract — names + counts only,
   never content in the report). A hook deny surfaces in the transcript as
   hook feedback / `tool_use_error` text containing the handler's deny
   message. Attribution is by **handler fingerprint**: each handler's deny
   messages contain distinctive literal phrases; the analyser ships a
   fingerprint table (derived from the handlers' own message constants, so it
   cannot drift silently — a parity test asserts every blocking handler has at
   least one fingerprint that matches its own deny output). Once Phase 3
   lands, block messages lead with `[R-…]` rule IDs and attribution becomes
   exact; the fingerprint table remains for pre-rule-ID history.
2. **Data source — HandlerHistory** (secondary, live-daemon view):
   `core/handler_history.py` counts deny/ask per handler in memory —
   daemon-lifetime only, so it validates the transcript numbers but cannot
   replace them.

Output: a ranked table (handler, block count, sessions-with-a-block, last-seen
date) + a recommended PROMOTED set given the configured threshold.

## Promotion policy — config-recorded, human-visible

```yaml
claude_md:
  promotion:
    # Handlers whose guidance stays fully resident in the injected block.
    # Regenerate the recommendation with: bin/hooks-daemon block-report
    promoted_handlers: []        # e.g. [pipe_blocker, sed_blocker, lsp_enforcement]
    # Advisory threshold used by block-report's recommendation
    min_blocks: 5
    min_sessions: 2
```

- The injector reads `promoted_handlers` at inject time; the LIST is the
  contract (deterministic, reviewable, committed), the analyser is the
  evidence that keeps it honest. `block-report` prints drift ("promoted but
  0 blocks in 90 days" / "not promoted but 40 blocks") so re-running it
  periodically re-tunes the set.
- Empty list ⇒ pure progressive disclosure (the original design) — safe
  default for fresh installs with no history yet.
- This repo's own initial set comes from a real transcript scan (Phase 2b
  task), not guesswork.

## Injected block layout (amended Phase 5)

```
<hooksdaemon>
  [shared meta-rule: blocked ⇒ adapt & continue — stated ONCE]
  [pointer: full detail via /hooks-daemon rule-explain <ID> / CLI explain-rule]

  ## Frequently-triggered handler guidance   (PROMOTED tier — full prose)
  ...today's per-handler sections, only for promoted handlers...

  ## All other enforced rules                (PROGRESSIVE tier — table)
  | ID | Blocked | Why | Fix |
  ...one row per blocking rule of every non-promoted handler...

  ## Advisories                              (lighter entries, Decision C)
</hooksdaemon>
```

## Success measure (amends G1)

Baseline re-measured 2026-08-30: the injected block is now **121,932 B ≈
28,630 cl100k tokens** (the plan's 22,041 B figure was the 2026-05-29
baseline; the block grew 5.5×). Target: with the data-derived promoted set,
the injected block shrinks **≥70%** vs the 2026-08-30 baseline while every
promoted handler keeps full guidance. Pure-progressive floor and
everything-resident ceiling are both reported by the Phase 9 re-measure so the
hybrid's position between them is visible.
