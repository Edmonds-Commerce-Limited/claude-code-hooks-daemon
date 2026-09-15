# Plan 00413: niggles ledger thirteen

**Status**: In Progress
**Created**: 2026-09-15
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The rolling ledger for defects found in passing. Ledger twelve (00407) is
archived, so this is the open one.

Both opening entries came from the same event: a collaborator was granted
access, cloned the repository fresh, and started an agent in it. Nothing about
that is unusual — it is the ordinary first-run path for anyone new — and it
produced a session with every safety handler inactive and an on-screen error
that named neither cause nor remedy.

That is worth stating plainly because this repository's own defences are the
product. A fresh clone is the one environment the project cannot dogfood, since
every checkout the maintainers work in has already been installed into.

## Goals

- Record each niggle with enough evidence that someone else can reproduce it.
- Resolve each entry to a terminal state: fixed, graduated to its own plan, or
  dismissed as not-a-defect with the reasoning kept.

## Non-Goals

- **Becoming a feature plan.** A niggle that needs design graduates to its own
  numbered plan and leaves a pointer here.

## Niggles

Seventeen entries. **Full bodies: [NIGGLES.md](NIGGLES.md)** — moved there when
`plan-doc-size` neared the hard block, because a plan nobody can edit is worse
than a long one. Deeper narrative is in
[JOURNAL/00413-Journal-26-09-15.md](JOURNAL/00413-Journal-26-09-15.md). Nothing
was deleted.

Listed in the order found, which is not numeric: N14-N17 were found while
fixing earlier entries, and that sequence is part of the record.

| #   | Verdict                                                                                    | Status                                                                               |
| --- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| N1  | `hookEventName: "Unknown"` fails a closed enum, so the whole response is discarded         | ✅ Fixed                                                                             |
| N2  | the self-install guard is RIGHT to ignore tracked config; its comment was not              | ✅ Not a defect                                                                      |
| N3  | a missing secret word list leaves a guard inert and says nothing                           | ⬜ Graduated to [00414](../00414-absent-protected-path-is-silent/PLAN.md)            |
| N4  | the printed remedy names an interpreter that is not installed                              | ✅ Fixed                                                                             |
| N5  | that remedy also DESTROYS this repository's tracked config                                 | ✅ Fixed                                                                             |
| N6  | the persistent-cron mechanism rests on output agents skim                                  | ⬜ Designed; implementation owner-gated                                              |
| N7  | no sanctioned way to FIND a plan, so the guard denies the only obvious one                 | ✅ Fixed                                                                             |
| N8  | a newly recorded licence never reaches already-vendored files                              | ✅ Fixed (Task 1.11 — drift is reported)                                             |
| N9  | the provenance deny message invites the corruption it should prevent                       | ✅ Fixed                                                                             |
| N10 | the question gate's escape hatch is fatal unattended                                       | ✅ Fixed                                                                             |
| N11 | host-identity tests read the real machine's `/etc/hosts`                                   | ✅ Fixed                                                                             |
| N12 | the contract cannot express a CONDITIONAL input field, and the gap produced a wrong answer | ✅ Fixed                                                                             |
| N13 | a scoped QA scan publishes its verdict as the repository's own                             | ✅ Fixed                                                                             |
| N14 | the acceptance playbook describes the DEFAULT handler, not the configured one              | ✅ Fixed                                                                             |
| N15 | the daemon CAN see the session's crons; two plans were built on it not being able to       | ✅ Fixed                                                                             |
| N16 | CLAUDE.md's own discovery route fails on the FIRST handler it lists                        | ✅ Fixed                                                                             |
| N17 | the freshness guard certifies a live dispatch it cannot vouch for                          | ⬜ Graduated to [00415](../00415-config-is-invisible-to-the-freshness-guard/PLAN.md) |

## Tasks

- [x] ✅ **Task 1.1**: N1 — detector first, RED on both tracked paths, then the
  fix: no event name at all, carried by the universal `systemMessage` field.

- [x] ✅ **Task 1.2**: N2 — resolved as not-a-defect; the misleading TODO-shaped
  comment that invited the wrong change was replaced with the rationale.

- [x] ✅ **Task 1.3**: N3 — established: the exclusion IS deliberate and
  documented. Re-scoped to visibility, which needs its own plan.

- [x] ✅ **Task 1.4**: N4 — corrected in `init.sh` and `daemon/cli.py`; the swept
  repository had no other bare `python install.py`.

- [x] ✅ **Task 1.5**: N5 — `scripts/bootstrap-self-install.sh`, and a message
  that warns against the destructive command rather than recommending it.

- [x] ✅ **Task 1.6**: Prove it the only way that counts — cloned fresh from
  GitHub, ran the real forwarder, followed the printed instruction verbatim.

- [x] ✅ **Task 1.7**: N3 graduated to Plan
  [00414](../00414-absent-protected-path-is-silent/PLAN.md).

- [x] ✅ **Task 1.8**: N6 — designed, and the design changed when N15 showed the
  premise was false: verification is a `Stop`-time comparison of `session_crons`
  against `persistent_crons`, the teeth are a Stop block, and the supervisor
  drops to backstop rather than being the mechanism. Duplication settled as
  `when_env:` activation (a lock arbitrates between machines nobody controls;
  here the owner controls them). The claim race settled as an atomic
  branch-ref push — git's `push` of a new ref is the compare-and-swap a label
  can never be. **Implementation is NOT started**: it adds a config key and
  changes the public issue loop, so it needs the owner's go.

- [x] ✅ **Task 1.18**: N15 — `session_crons` and `background_tasks` declared in
  `Stop`/`SubagentStop` `conditional_input_fields`, carrying the two traps that
  would each have produced a plausible broken check: the 1000-character
  `prompt` cap (exact-equality against this project's own long `issue-sdlc`
  prompt never matches) and absent-is-not-empty. N12's slot earning its keep
  within the hour. 00412's D7/D9 corrected in the same pass, since they rest on
  the same false premise.

- [x] ✅ **Task 1.19**: N16 — `discover_handler_rules` gained an opt-in
  `include_project_handlers`, wired into both `explain-handler` and
  `explain-rule`. RED first. All four project handlers now resolve; library
  lookups unchanged. Opt-in rather
  than default, because the block-report fingerprint index wants the library
  package alone — it maps a rule ID to a library handler's config key.
  Project-handler loading degrades to "none" on any failure, so a lookup that
  would have answered about library handlers still does.

- [x] ✅ **Task 1.9**: N7 — `bin/hooks-daemon find-plan <number|name|words>`,
  named in the deny message beside the number and in the injected guidance.
  Detector unchanged, as intended: it still denies, and now says what to do
  instead. Substrate question answered NO — the README index is complete today
  (404 rows against 404 folders) but a plan missing a row would be invisible to
  a reader told the search covers everything, which is the guard's own failure
  mode one layer up. The finder walks the filesystem, which cannot have that
  gap. Live-verified on the archived plan a folder scan misses.

- [x] ✅ **Task 1.10**: N7b — `plan_number_helper` now exempts a `git commit`
  message, RED first on the live reproduction. Anchored on the LAST mention,
  not the first as `sed_blocker` does: a first-match anchor would let
  `git commit -m '...<dir>...' && ls <dir>/*` launder a real scan, and the
  plan directory appears in exactly the messages this exemption allows. Both
  laundering shapes are pinned as still-denied.

- [x] ✅ **Task 1.11**: N8 — `remote-docs check` now reports licence drift
  against `known_sources` beside staleness, and names re-capture as the fix
  (`refresh` compares the source hash and reports `unchanged`). Reporting was
  chosen over a back-fill flag deliberately: re-stamping a licence is a legal
  assertion about someone else's work, so it should be a decision rather than
  a side effect. Folded into the existing verb rather than a new one — a
  second command nobody runs would leave the drift as invisible as it was.
  Proved end-to-end on a scratch project, since the real corpus is clean.

- [x] ✅ **Task 1.12**: N9 — an `Edit` in the tree is now refused outright,
  with a reason that names the real objection instead of a frontmatter
  complaint. RED first. The fix closed a HOLE the misdiagnosis had opened: a
  fragment that parsed as valid provenance previously PASSED, so the message
  invited pasting a `---` block into the document and then waved the corrupted
  write through. The new message also names the `remote-docs add` re-capture
  route, which N8 found was discoverable only by trial.

- [x] ✅ **Task 1.13**: N10 — both facts established, and neither removed the
  need: Claude Code's mechanisms are LAUNCHER flags and cannot reach a
  `CronCreate` job firing into a live interactive session. `mode: unattended`
  added RED-first and enabled here; live-verified through the real hook.

- [x] ✅ **Task 1.14**: N11 — 13 machine-dependent tests pinned to the
  `_FEDORA_STYLE_HOSTS` fixture via `hosts_path`; resolver untouched, no
  assertion dropped. A new guard makes "refused" distinguishable from "broken",
  which the class could not do before. 48 pass. Detail in JOURNAL.

- [x] ✅ **Task 1.15**: N12 — `conditional_input_fields` added to the contract
  shape (name → the CONDITION under which the field arrives), consumed by
  `check_input_contract.py`, surfaced in `--inventory`, and mandated by
  `HOOK-CONTRACT-REFRESH.md` at every refresh. A name with no condition is
  REJECTED; the slot is per-event, never global. `permission_mode` deliberately
  got NO entry, contrary to this task's original wording — upstream resolves it
  via each event's example, so the existing convention already answers it.
  Detail and the `Stop`/`SubagentStop` boundary in JOURNAL.

- [x] ✅ **Task 1.16**: N13 — a `--path` scan now reports BESIDE what it
  scanned and never overwrites the repository artefact. RED first, on both
  halves: the artefact is byte-identical after a scoped run, and the scoped
  verdict still lands. The 20 existing tests stop reading a file the whole QA
  suite also writes. 21 pass.

- [x] ✅ **Task 1.17**: N14 — the generator now applies configured `options`
  before asking a handler what it declares, mirroring the registry's
  `_`-prefixed mechanism; `ask_user_question_blocker` declares unattended
  probes to match. RED first on both. Option INHERITANCE
  (`shares_options_with`) is deliberately NOT reproduced — it needs the
  registry's two-pass collection, and no handler today both inherits options
  and varies its declared tests by one. 224/224 probes behave as declared;
  2,025 acceptance + daemon tests pass.

- [x] ✅ **Task 1.20**: N17 graduated to Plan
  [00415](../00415-config-is-invisible-to-the-freshness-guard/PLAN.md). It needs
  design, not a patch: what to hash (file bytes versus resolved model) and
  whether to extend the existing fingerprint or report a second one are genuine
  forks, and the wrong pick yields a guard that either flaps or leaves existing
  consumers no better off. Dedupe-checked first — 00371 put config-only
  staleness in its non-goals and 00395 recorded it as uncovered, so the gap was
  known and deferred twice rather than missed.

## Success Criteria

- [x] ✅ No `emit_hook_error` path can emit an event name Claude Code rejects,
  and a test fails if one is reintroduced — 15 tests, including a sweep of all
  32 forwarders and two vacuity guards so a dead regex cannot pass silently.

- [x] ✅ A fresh clone of this repository starts a session in which the daemon
  either runs, or explains in readable prose exactly why it does not.

- [x] ✅ The printed remedy is one a reader can follow without losing anything:
  run from a bare clone it reaches 31/31 listeners and leaves the tracked tree
  clean, with no `.bak` files.

- [x] ✅ Every entry above is terminal in the sense this plan's Goals define —
  seventeen niggles, twenty tasks, each fixed with a RED-first test, determined
  from the record, or graduated to its own numbered plan (N3 → 00414,
  N17 → 00415).

- [ ] ⬜ **Owner-gated, and the only thing left**: N6/N15's enforcement is
  DESIGNED, not built. It adds a `when_env:` config key and changes the public
  `issue-sdlc` claim from a label to a branch-ref push, so it is not a change
  to make unasked. Everything else in this ledger is complete.

## Delivery & Milestones

- Opened from a real first-run failure: a new collaborator's fresh clone, which
  is the one environment this project structurally cannot dogfood.
