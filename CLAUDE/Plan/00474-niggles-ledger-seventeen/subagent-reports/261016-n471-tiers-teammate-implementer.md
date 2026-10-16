# N471 implementer report: tiers joins a teammate on agent_id

## Assumptions

- The `unjoined` header counts, besides unclaimed dispatch rows, every agent with no `toolUseId` in its meta and no
  `agent_id` row. An agent that has a `toolUseId` but no row (a Workflow agent, or one spawned before the ledger) is
  deliberately not counted: that is the legitimate `unrecorded` case and counting it would make the header cry wolf.
- The header wording ("unjoined dispatch rows") is unchanged, so the golden output stays stable.
- `toolUseId` wins when present; `agent_id` is only the fallback, so a plain subagent can never be stolen by another
  row.

## Red

Two new tests failed before the change in `tests/unit/daemon/test_tier_report.py`:

- `test_a_teammate_without_a_tool_use_id_joins_on_agent_id`: `assert ('unrecorded', 'other') == ('explicit', 'implement')`
- `test_an_agent_with_no_tool_use_id_and_no_row_counts_as_unjoined`: `assert 0 == 1`

The third new test (`toolUseId` wins over an `agent_id` match) passed before and after, as a guard.

## Change

`collect_tiers` in `src/claude_code_hooks_daemon/daemon/tier_report.py`: builds a second index of rows by `agent_id`,
looks up by `toolUseId` when the meta has one, falls back to `agent_id`, and adds one to `unjoined` for an agent with
no `toolUseId` and no `agent_id` match.

## Other readers of `toolUseId`

- `hooks-daemon spend` (`daemon/spend_report.py`) never joins on it; it reads `agent_id` from the transcript name.
- `subagent_cache_aggregator` only copies `meta.tool_use_id` into the per-agent ledger sidecar and sets `downgraded`
  from the transcript tail; there is no join, so nothing to fix.
- `read_dispatch_rows` only orders rows by `tool_use_id`; no other consumer joins agents to rows.

## Release note

079 (Plan 00472) does not claim teammates are covered, so it is not amended.

## QA

`./scripts/qa/llm_qa.py changed`: 39/40, the one failure being `tier_report.py` reported `[too-broad]` unmapped. With
`--allow-unmapped`: all checks pass, exit 0. `tests/unit/daemon/test_tier_report.py`: 13 passed.

## Ledger

N471 marked fixed in NIGGLES.md and STATUS-INDEX.md; PLAN.md open 12 to 11, checkmarked 146 to 147 (143 of the 172 N
rows). Code commit: e5d85dbaf.
