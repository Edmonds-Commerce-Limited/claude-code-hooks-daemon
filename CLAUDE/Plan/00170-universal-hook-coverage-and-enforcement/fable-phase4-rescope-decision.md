# Plan 00170 — Phase 4 re-scope ruling

Decision document only. The plan's Blocker line says "resuming needs that
re-scope confirmed first" (`PLAN.md:4-6`). This document confirms the
reasoning of commit `6f6dffd4`, revises its task list against what has been
built since, and records a regression the plan must own. It does not change
the status header.

## Decision

The re-scope's reasoning is sound and is confirmed; its task list is stale and
is revised. Phase 4 becomes: drop Task 4.1; record Task 4.2 as delivered by
Plans 00271 and 00327; keep a narrowly scoped forwarder-presence check; build
the Task 4.3 scaffolder and prove it by wiring the three events that are
currently unwired. Phase 5.1 is collapsed to one triage table. The plan should
resume.

## Reasoning

### What the re-scope said, and whether it holds

Commit `6f6dffd4` appended one finding to the journal
(`JOURNAL/00170-Journal-26-07-16.md:318-344`): Claude Code invokes only a
forwarder registered in `settings.json`, so "the daemon can NEVER observe a
truly-new upstream event at runtime". Task 4.1's runtime unknown-event logger
therefore fires only during a self-inflicted discovery-to-wire gap. The real
detectors are (1) a spec audit against the authoritative docs, (2) a
coverage-degraded alert asserting each wired forwarder exists and is
executable, and (3) the `add-hook-event` scaffolder.

**Point (1) on 4.1 is correct, and the architecture map in the same journal
proves it.** An unknown `hook_event_name` is already fail-open: `EventType.from_string`
raises, `HookEvent` rejects, and the router returns allow-plus-warning
(`JOURNAL:80-89`, `:106-114`). No forwarder means no socket call at all.
Dropping 4.1 stands.

**Point (2) has been overtaken — the spec audit exists.** Since the re-scope,
Plan 00271 vendored the hooks contract (`contracts/claude-code-hooks/`, one
JSON per event, `META.json` recording docs URL, sha256, and
`last_audited_claude_code_version: 2.1.272`, `event_count: 33`), wired
`scripts/qa/check_hook_contract.py` into QA with an `event-missing-from-catalogue`
rule (`:127`), and shipped the `contract_staleness` SessionStart advisory
(`handlers/session_start/contract_staleness.py:1-9`). Plan 00327 then
mechanised the fetch-and-compare half as `bin/hooks-daemon contract-status`
(`daemon/contract_status.py:1-14`). The plan's own Dependencies section
already says this ("Phase 4's drift detection should build ON it, not beside
it", `PLAN.md:278-293`). Run today, the tool reports **CHANGED** — upstream
sha `e19530eb…` (327,672 bytes) against recorded `0dc5622c…` (322,902 bytes)
— so the detector is not only built, it is currently firing. What Task 4.2
imagined (a version-pinned static assertion plus an advisory that fetches the
live doc and diffs) is exactly `test_hook_coverage_completeness.py` plus
`contract-status`. Nothing is left to build for 4.2; it should be ticked with
the delivering commits cited, not re-done.

**Point (2)'s second half, the forwarder-presence alert, is partly covered and
a small gap remains.** `init.sh`'s `_exec_bit_selfheal` (`init.sh:501-596`)
restores `+x` on sibling hook scripts on every invocation, and the
`bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/<key>` invocation form makes the
exec bit irrelevant — the validator asserts that form
(`utils/hook_registration.py:295-308`). A DELETED forwarder is not checked
anywhere in a client: `hook_registration_checker`'s only `exists()` is on
`settings.json` itself (`handlers/session_start/hook_registration_checker.py:119`),
and the completeness test that asserts forwarders on disk runs only in this
repository. The gap is narrow (the installer writes the forwarders; deletion is
rare) and the fix is small: at SessionStart, assert each wired event's
forwarder is present and regenerate it via `install.py`'s
`create_forwarder_script`, the reconciler pattern already used for missing
settings entries. Keep as a scoped task; it is not the plan's centre.

**Point (3) is confirmed, and the evidence for it is a regression the plan
must own.** Coverage reached 100% at `367234d2` ("EXPECTED_UNWIRED empty").
Today `EXPECTED_UNWIRED = {"DirectoryAdded", "PreModelSwitch", "PostModelSwitch"}`
(`tests/integration/test_hook_coverage_completeness.py:103-105`) with
`wired=False` in the catalogue (`constants/events.py:454-460`, `:524-544`).
Each is annotated "wiring it end-to-end ... is a follow-up" (`:93-102`), and
no live plan mentions any of them — the only plan that does is
`Completed/00271-hook-contract-alignment`. The drift detector did its job
(three new upstream events were catalogued), and then the wire step that the
plan's founding invariant makes non-negotiable ("Wire every hook event,
unconditionally", `PLAN.md:29-33`; owner mandate "we wire it for sure",
`JOURNAL:310-311`) did not happen. The per-event recipe is about four edits
after the DRY foundation (`JOURNAL:203-208`) and still nobody ran it in the
weeks since. That is the strongest possible argument for the scaffolder: a
one-command wire is the difference between a tracked gap and a wired event.

### The revised Phase 4 and 5

- **Task 3.4 (new, Phase 3 regression)**: wire `DirectoryAdded`,
  `PreModelSwitch`, `PostModelSwitch` end-to-end with fail-open passthrough,
  emptying `EXPECTED_UNWIRED` again. `PreModelSwitch` can block, so the
  `ALLOWLIST.yaml` entry `missing-refusal-claim:PreModelSwitch:deny`
  (`contracts/claude-code-hooks/ALLOWLIST.yaml:7-9`) is deleted in the same
  change, as it instructs. Do this THROUGH Task 4.3's scaffolder if 4.3 is
  built first; otherwise by hand and 4.3 is dropped as unproven.
- **Task 4.1**: dropped, with the fail-open reject path recorded as the
  reason.
- **Task 4.2**: delivered by Plan 00271 (`contracts/`, `check_hook_contract.py`,
  `contract_staleness`) and Plan 00327 (`contract-status`). Tick with those
  citations; the coordination note at `PLAN.md:278-293` becomes the task's
  record.
- **Task 4.2b (new, narrow)**: client-side forwarder-presence check with
  regeneration, as above.
- **Task 4.3**: build the `add-hook-event` scaffolder; its acceptance test is
  Task 3.4.
- **Task 5.1**: replace "a backlog/triage entry (own follow-up plan)" per event
  — twenty plans of one sentence each — with a single triage table in a
  supporting document, seeded from the Coverage Gap table (`PLAN.md:100-121`)
  and the 00169 backlog it already cites. A per-event plan is filed when
  someone decides to build a handler, not before.
- **Task 5.2**: verify `CLAUDE/PROJECT_HANDLERS.md` states that a project
  handler can attach to ANY wired event (it says "Every wired event has one"
  base class at `:245` — confirm the attach path is documented, not only the
  base classes), regenerate docs, restart, and add the client-rollout note.

### Confirming versus revising

Confirming the re-scope means accepting that Phase 4 is about spec-audit,
presence check and scaffolder rather than a runtime logger. That is confirmed.
Revising it means recognising that two-thirds of it has been built under other
plan numbers and that the plan's own coverage invariant is broken while it
sits Dormant. A Dormant plan whose invariant is being violated with no owner is
not parked; it is abandoned in the wrong status. The Blocker line's condition
is met by this document, and the status should be flipped to `In Progress`
when work resumes — by whoever picks it up, in the same edit that revises the
tasks (the status flip is outside this document's remit).

## Cost, and who bears it

Wiring three events adds three forwarders and three `settings.json` entries to
every client on upgrade; the settings reconciler is additive per event
(`utils/hook_registration.py:314-323`) so nothing a client added is touched.
`PreModelSwitch` is a blocking-capable event and ships as `{}` passthrough,
the same shape every Phase 3 event shipped in. The scaffolder is maintainer
work with one proving use. Clients bear three more forwarder invocations on
rare events; maintainers bear the build.

## Strongest argument against

"Three unwired events on rare triggers (`/add-dir`, a model switch) harm
nobody, and the scaffolder is tooling for a task that happens a few times a
year." Both true as stated. The plan's answer is its Overview: coverage is the
daemon's reason to exist, and "a newly-discovered upstream event is wired
FIRST; what to do with it is a separate decision" (`PLAN.md:29-33`). A
client wanting a `PreModelSwitch` handler today cannot attach one, and cannot
tell from the daemon that this is why. If the owner no longer holds the
invariant unconditionally, the right move is to strike it from the plan, not
to leave it stated and unmet.

## Does a human gate remain?

No. The only owner-shaped question — "is the unconditional-coverage invariant
still the policy?" — was answered by the owner in this plan's own journal
("we wire it for sure") and has not been withdrawn. Everything else is
technical with a defensible answer.
