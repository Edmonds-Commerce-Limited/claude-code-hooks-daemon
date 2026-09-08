# Refreshing the vendored Claude Code hooks contract

The JSON files in `contracts/claude-code-hooks/` are a tracked, vendored
statement of the Claude Code hooks OUTPUT contract, one file per documented
event, plus `META.json` (provenance) and `ALLOWLIST.yaml` (recorded, reasoned
capability gaps). The QA check `scripts/qa/check_hook_contract.py` diffs the
daemon's sources of truth against these files on every QA run — network-free.

(This procedure lives under `docs/guides/` rather than beside the JSON because
the repository's markdown-organisation policy confines `.md` files to the
documentation trees; `META.json.refresh_procedure` points here.)

Refresh the vendored copy when the `contract_staleness` SessionStart advisory
fires (installed Claude Code version newer than
`META.json.last_audited_claude_code_version`), or whenever hook behaviour is
suspected to have changed.

**This procedure belongs to the daemon repository only.** In a client install
the vendored contract sits under `.claude/hooks-daemon/`, which every upgrade
overwrites, so a refresh performed there is discarded and never reaches
anyone. A client whose advisory fires should upgrade the daemon, or report it
upstream if already current — which is what the client-mode advisory says.

## The one non-negotiable rule: RAW fetch only

**Fetch the docs as raw markdown and read the raw text. Never trust a
summarising fetch layer.** During the Plan 00271 audit, a summarised fetch of
the same URL FABRICATED contract detail — it invented a
`permissionDecision: "escalate"` value that appears nowhere in the raw text.
A fabricated enum value vendored here would be enforced against the daemon as
if documented. Every claim written into a contract JSON must be found
VERBATIM in the raw markdown before it is recorded.

## Step 0: ask whether anything changed

```bash
bin/hooks-daemon contract-status --save untracked/hooks-raw.md
```

That is the mechanised half of this procedure (Plan 00327): a plain https
GET of `META.json.docs_url` — the exact bytes, no summarising layer — hashed
and compared with `META.json.docs_sha256`. The verdict is the exit code:

| Exit | Verdict     | What to do                                                                                                                   |
| ---- | ----------- | ---------------------------------------------------------------------------------------------------------------------------- |
| 0    | `unchanged` | Upstream matches the last audit. Bump only `last_audited_claude_code_version` and `fetch_date` in `META.json`; done.         |
| 1    | `CHANGED`   | Upstream moved. `--save` has left the RAW body on disk (keep it untracked); continue with the manual steps below.            |
| 2    | error       | `META.json` unreadable/incomplete, or the fetch failed. Nothing has been compared — fix the cause, do not guess the verdict. |

Everything after this point is judgement, and stays manual by design.

## Manual steps for a CHANGED verdict

1. Diff the saved RAW text against the previously audited text and read the
   changed sections (the "#### Decision control" table and each event's
   "decision control" / "output" section). Update the affected per-event JSON
   files. For every changed claim, locate the exact supporting sentence in
   the raw markdown and record it in the plan's audit document. Extraction is
   a verified manual/agent step by design — never an automated summarisation
   (Plan 00271 Decision 3).
2. A newly documented event gets a new `<Event>.json` file (the checker treats
   a documented event missing from the daemon's catalogue as a finding, which
   is the intended pressure).
3. Update `META.json`: `fetch_date`, `docs_bytes`, `docs_sha256` (the values
   `contract-status` printed for the upstream body),
   `last_audited_claude_code_version` (the installed Claude Code version
   audited against), `event_count`. `TestMetaProvenance` in
   `tests/unit/qa/test_check_hook_contract.py` pins the same three values;
   move them together. Re-run `contract-status` and expect exit 0.
4. Re-run the guard: `./scripts/qa/llm_qa.py hook_contract`. Triage every new
   finding into either a fix task (preferred) or an `ALLOWLIST.yaml` entry
   carrying a reason and a linked plan/task. Stale allowlist entries FAIL the
   check — delete entries whose drift no longer exists.
5. Re-triage the INPUT side (Plan 00273): run
   `./scripts/qa/llm_qa.py input_contract`, and diff the refreshed
   `input_example`s against the daemon's current read surface
   (`scripts/qa/check_input_contract.py --inventory`). Triage every new
   finding into a fix task (preferred) or an `INPUT-ALLOWLIST.yaml` entry with
   a reason and linked plan/task, and triage any NEWLY documented input field
   into consumed vs recorded-gap (append the verdict to
   `CLAUDE/Plan/00273-hook-input-payload-validation/INVENTORY.md` or its
   successor). Note the superset rule cannot see a rename where BOTH the old
   and new names appear across examples — this manual diff is the guard for
   that case. Without this step the input half rots exactly as the output
   half did.

## Contract JSON shape

Each `<Event>.json` records: `block_mechanism` (named token or null),
`can_block`, `ask_capable`, `top_level_output_fields` (the five universal
fields plus any documented top-level decision fields),
`top_level_decision_enum`, `hook_specific_output_fields` (with `enum` where
the docs enumerate values), `discarded_fields` (fields the docs say Claude
Code discards for this event), `notes`, and a VERBATIM `input_example` lifted
from the docs. `hookEventName` is implied for every event with
`hook_specific_output_fields` and is not listed per file.
