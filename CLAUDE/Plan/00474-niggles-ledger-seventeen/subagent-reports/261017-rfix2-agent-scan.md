# rfix2-agent-scan: stale_derived_agents crash and two Plan 00531 minors

## Assumptions

- The "one warning" rule is applied to every bad `tuned_agent` value (non-string, unsafe name, undeployed), keyed on (value, project root), not only to the non-string case. The same per-event spam existed for the others.
- `_tuned_agent` on the feed handler is now typed `object`, since it is injected from YAML.

## Red (before the fix)

11 failed in the targeted run, including `test_a_directory_named_like_an_agent_is_skipped`,
`test_a_dangling_symlink_costs_only_that_entry`, `test_an_unreadable_file_is_logged_and_skipped`,
`test_the_header_does_not_call_a_tuned_copy_daemon_owned`, the non-string `tuned_agent` rows and the warn-once row.

## Fix

- `install/agent_assets.py` `stale_derived_agents`: skip non-files; an `OSError` on read goes through `log_and_continue` with a specific reason, so one bad entry costs only that entry.
- `utils/plan_fact_check.py` `resolve_checker_agent`: takes `object`, falls back to the generic agent for anything that is not a deployed safe name, warns once per (value, project).
- `handlers/session_start/deployed_artefact_drift.py`: header no longer says tuned copies are daemon-owned; it says a tuned copy is the project's and never touched.

## Sibling code checked

- `classify_agent` reads only after `is_file()` (agent_assets.py): fine for a directory, but a dangling symlink returns False from `is_file`, so ABSENT; a permission error would still raise. Not part of the reported defect; left alone, noted for the coordinator.
- Other `glob("*.md")` readers in the drift handler (core docs, plan tooling) use fixed filenames, not a scan of project-owned directories.

## QA

`./scripts/qa/llm_qa.py changed` did NOT run: the host-wide QA lock was held by pid 1644783 in /workspace for both a 600s and a 1500s wait ("this run did not start", exit non-zero). Substitute run directly on the 7 changed files: ruff check, black --check and mypy all pass. Pytest on the four touched test files (agent_assets, plan_fact_check, deployed_artefact_drift, plan_fact_check_feed): 181 passed. The coordinator should run `changed` once the lock is free.

## Existing callouts

None edited (per brief). Not checked for untruth: callout text claiming the header says "daemon-owned" for tuned copies; the coordinator may grep UNRELEASED/moved callouts for "tuned_agent" and the drift header.
