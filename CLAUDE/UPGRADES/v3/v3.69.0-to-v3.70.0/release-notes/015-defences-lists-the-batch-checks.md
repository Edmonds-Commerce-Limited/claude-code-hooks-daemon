# Callout: defences lists three batch checkers beside the handlers

**Plan**: 00484
**Audience**: operators

`hooks-daemon defences` now also lists the `scripts/qa` checkers that are the whole-tree form of a Defence handler: `audit_error_hiding.py`, `check_sensitive_content.py` and `check_inline_suppressions.py`. There is one row per rule ID the checker prints, leaving out the rules that report on the checker itself (its configuration, an unreadable file, a stale exclusion). Each row has the defect class of its handler counterpart, that checker rule ID, a docs route (`./scripts/qa/llm_qa.py --explain <ID>`) and an entry point (the `llm_qa.py` step).

A new field, `kind`, tells the rows apart: `handler` for a write-time handler rule, `batch-check` for a checker row. `defences --json` carries it on every record, and the text output ends each line with it. Filter on `kind` if you read the listing; a batch row's `handler` is the `llm_qa.py` step, its `handler_class` the script, its `event` is `qa` and its `priority` is 0.

The rows come from `scripts/qa/qa-rules.json` in the project, so a project without that file lists handler rows only. A batch row is listed only while its handler is enabled, and an unusable registry (unparseable, or not a JSON object) makes `defences` print one line to stderr and exit 1, with the handler rows still listed. The British-English check is not listed: a spelling convention is not a defect class, and its handler is not a Defence.

`defences` also discovers a project's handlers once per run instead of twice. Nothing to do on upgrade.
