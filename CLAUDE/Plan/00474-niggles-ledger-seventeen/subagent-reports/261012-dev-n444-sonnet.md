# N444 (GitHub #96): ship the plan fact-checker agent

Branch `worktree-issue-96-ship-fact-checker`.

## Commits

- f6fb96d0c: template, registry entry, name and instruction change, dogfood copy removed, docs, release note 045.
- 41a669457: release note `**Audience**` changed to `client projects` (the holding-area test only accepts a fixed set of values).

## Red first

- `tests/unit/utils/test_plan_fact_check.py` and `tests/unit/handlers/post_tool_use/test_plan_fact_check_feed.py`: 4 failed, 80 passed.
- `tests/unit/install/test_agent_assets.py`: collection error (`FACT_CHECKER_AGENT_NAME` missing), so its 3 new tests were red by import failure.

## Tests changed

New, in `tests/unit/install/test_agent_assets.py`:

- `test_fact_checker_registered_with_declared_md5`
- `test_fact_checker_gated_on_the_feed_flag` (on / off / absent entry)
- `test_fact_checker_deployed_only_when_the_feed_is_on`

Updated, not deleted:

- `tests/unit/install/test_agent_assets.py::_enabled_config` now also enables the feed, because `TestSync` expects every shipped agent to deploy.
- `tests/unit/utils/test_plan_fact_check.py::test_delivery_returns_instruction_naming_agent_plan_and_diff_file` now asserts the new name, the `agents install` command and "later session".
- `tests/unit/handlers/post_tool_use/test_plan_fact_check_feed.py`: the delivered-text assertion, plus the two `subagent_type` values used for dispatch confirmation (parametrised tool names and the subagent-dispatch test), now use the new name.

## Implementation

- Template `hooks-daemon-plan-fact-checker.md` v1.0.0, md5 `67f6a215896282d743f7bc1c937ee5a5`, project-neutral, same header and version marker as the dedupe scout.
- `agent_assets.py`: `FACT_CHECKER_AGENT_NAME`, `_fact_check_feed_enabled`, declared md5 and spec. The gate requires the `plan_fact_check_feed` entry to be PRESENT and enabled. `HandlerConfig.enabled` defaults to True, so reading it for an absent entry would have deployed the agent for everyone.
- `plan_fact_check.py`: `FACT_CHECKER_AGENT` is imported from `agent_assets` (single source). The instruction gains: "If `hooks-daemon-plan-fact-checker` is not an available agent type here, deploy it with `hooks-daemon agents install hooks-daemon-plan-fact-checker`; it becomes dispatchable only from a later session." Dispatch confirmation keys on the diff path in the prompt, so it only needed the test fixtures renamed.
- Docstring, message and pattern mentions in the handler, `init_config.py` and `.claude/hooks-daemon.yaml.example`; `docs/guides/AGENT_ASSETS.md` table row.
- `git rm .claude/agents/plan-fact-checker.md`.

## QA

- Targeted pytest (agent assets, fact-check util and feed, cli agents, ledger completeness, deployed-artefact drift): 164 passed after the commit. The ledger integration test needs git history for the new template, so it only passes once committed.
- `./scripts/qa/llm_qa.py changed`: 39 of 40 passed. The one failure was `changed_tests`, which reported:
  - release note 045 audience value (fixed in the second commit; holding-area test now passes);
  - `init_config.py` and `agent_assets.py` as "unmapped [too-broad]". This is the runner's mapping rule for those two files, not a test failure. I ran `tests/daemon/test_init_config.py` and `tests/unit/daemon/test_init_config.py` with the holding-area test directly: 92 passed. I did not re-run the whole `changed` pass after the second commit.

## Post-merge deploy step for this repository

After merge and daemon restart, run from the main checkout: `bin/hooks-daemon agents install hooks-daemon-plan-fact-checker`. It deploys only if `plan_fact_check_feed` is enabled in `.claude/hooks-daemon.yaml`; the daemon's start-time sync also does this. `.claude/agents/plan-fact-checker.md` is removed by the merge. The agent is dispatchable from the next session.

## Deviations

- Release note audience is `client projects` (brief said to follow 044, whose value is `handler authors`; that value does not fit and the test restricts the set).
- The `agents list` output and docs listing needed no code change: both iterate `SHIPPED_AGENTS`. The docs table already lacked a docs-qa row; I left that alone.
