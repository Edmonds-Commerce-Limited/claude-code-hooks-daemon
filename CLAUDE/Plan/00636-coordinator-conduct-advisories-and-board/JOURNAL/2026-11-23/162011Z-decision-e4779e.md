## 16:20 · decision · — — PR 226 delta review: N1-N3 fixed, N4-N6 open

Delta review of PR 226 (subagent-reports/261123-opus-delta-review-pr226.md) filed and N1-N3 fixed test-first, one commit each.

- N2: the widened F2 detector read any capitalised word as a person and reply/response/decision/input alone as a human's answer. A target is now an owner/human/user/operator noun, an @handle, or a name in the new options.owner_names (default empty; config-changes v3.77.0, HANDLER_REFERENCE and release note 026 updated). Only "answers" stands alone, "pick up" is not an act, and the bare "X to <act>" shape is gone. Trade-off: "waiting on Joseph" now needs owner_names: [Joseph]; no roster exists on the bus snapshot or seat context to name team humans otherwise. All 11 probe rows from the review are negative tests, run with Joseph configured.
- N1: the fault deny now carries the stand-in (a fault computing it leaves the deny intact). auto_continue_stop treats a stop_hook_active re-stop whose LATEST block marker carries R-STOP-OWNER-WAIT-UNBUMPED as fresh, so its own refusals surface; its own deny is then the latest marker, so the chain holds at most two refusals (chain test proves no third).
- N3: a raising flags_readable() under auto now refuses (fails closed).
- N4, N5, N6 recorded in PLAN.md as open follow-ups (Task 2.1d), not fixed.

Light runs: stop and subagent_stop suites, stop-chain shadowing, both response-validation suites, owner_wait_bus, fail-closed tagging (1410 passed); tests/unit/config (686 passed); ruff, black, mypy clean on touched files.
