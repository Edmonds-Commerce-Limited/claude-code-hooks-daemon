# Plan 00377: niggles ledger

**Status**: Complete
**Created**: 2026-09-11
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Main Thread

## Overview

**This is the open niggles ledger. A small defect found in passing is recorded
here, in the same turn it is found — never reported only in chat.**

A defect mentioned in conversation and nowhere else is lost the moment the
context window rolls. It reads as diligence ("worth knowing about…") while
producing exactly the same outcome as saying nothing: nobody can act on it, no
one can find it later, and the next agent rediscovers it from scratch. Several
real defects in this repository were surfaced that way and survived only
because someone happened to re-notice them.

A niggle is a defect too small to deserve its own plan: a missing check, an
invariant nothing enforces, a message that misleads, a tool with a blind spot.
It is still a defect. The ledger is the standing home for them, so recording
one costs an append rather than a whole plan.

**Lifecycle** — see `CLAUDE/PlanWorkflow.md` ("The niggles ledger") for the
authoritative rule:

- Exactly one niggles ledger is open at a time.
- When every entry is resolved, the ledger closes and is archived like any
  other plan.
- The next niggle found opens a NEW ledger. Do not reopen a closed one.

## Goals

- Every small defect found in passing is recorded the moment it is found.
- No defect exists only as chat output.

## Non-Goals

- Absorbing work that deserves its own plan. A niggle that turns out to be
  systemic graduates to its own plan and is struck from here with a pointer.
- Being a wish-list. This is defects, not ideas or preferences.

## Tasks

### Phase 1: Open niggles

- [x] ✅ **N1: `plan-qa --sweep` does not check journal entry ordering.** The
  journal preamble states the grammar "times increase down the file", and
  nothing enforced it. Measured: a `00376` day-file whose entries ran
  12:49 → 12:58 → 13:00 → 12:50 passed `plan-qa --sweep` with `0 findings`.
  The `journal-append-only` check correctly caught the EDIT that caused it, so
  the gap was specifically in the sweep. **Fixed**: new check
  `journal-entry-ordering`, registered at EDIT and SWEEP, advise, honouring
  `journal.mode: block`. Fenced blocks and the blockquoted grammar example are
  not entries; equal times pass.

  Two deliberate blind spots, each guarded by a test: archived plans are
  skipped (`archive-immutability` forbids the edit that would fix them), and
  day-files named before the rule shipped are grandfathered, mirroring Plan
  00163 Decision 7's no-backfill. The second was not a convenience — running
  the check over this repo showed the pre-existing journals have the narrative
  order RIGHT and the clock readings wrong, so the only available "fix" was
  inventing timestamps in an append-only record. A permanently unfixable
  finding trains readers to ignore the check.

- [x] ✅ **N2: the plan-dedupe scout cannot see completed plans.** It read
  only plans in the plan root and reported "Checked N live plans". For the
  question it is most often asked — "does this machinery already exist?" — a
  COMPLETED plan is the likelier home, because the machinery exists precisely
  because a plan finished. Measured: it reported "No existing plan covers this"
  for Plan 00376's pre-upgrade work while Plan 00062 (Complete) had already
  built a pre-upgrade validation phase and the very confirmation gate 00376 is
  about. **Fixed**: the template gained step 3b — a cheap
  `grep -ril` over `Completed/*/PLAN.md`, reported under a mandatory
  `## Prior art (completed plans)` heading kept separate from duplicate
  candidates, because prior art means "read this first", not "do not file".

- [x] ✅ **N4: `agents install` cannot restore a drifted agent — it recommends
  itself.** When a deployed agent no longer matched a shipped revision, the
  daemon refused to touch it and advised running
  `hooks-daemon agents install <name>` — the command that just refused, so it
  failed again (exit 1). Reproduced on `hooks-daemon-plan-dedupe-scout`.
  **Fixed**: `agents install <name> --force` discards a customised copy and
  restores the shipped revision, saying that it did. The refusal itself is
  kept and is correct — a bulk refresh must never clobber local edits — so
  `force` defaults to False and only an explicitly named, explicitly forced
  install overwrites. The warning now names that escape instead of itself.

- [x] ✅ **N5: no dev-loop command redeploys the core docs.**
  `deploy_core_docs_if_enabled` is invoked only from `scripts/install_version.sh:684`
  and `scripts/upgrade_version.sh:423,1103`. Editing
  `install/templates/core/*.core.md` therefore leaves the deployed
  `CLAUDE/core/*.core.md` stale until the next install or upgrade, with nothing
  reporting the drift — `deploy-plan-workflow` does not cover core docs and a
  daemon restart does not either. Agents have `agents install`; core docs had
  no equivalent. **Fixed**: new `hooks-daemon deploy-core-docs` verb — the
  dev-loop refresh for `CLAUDE/core/*.core.md`. Client-owned overrides are
  untouched; only daemon-owned files are rewritten.

- [x] ✅ **N6: nothing reports that a deployed artefact has drifted from its
  template.** N5's verb makes the drift FIXABLE; it does not make it visible,
  so a stale deployed file still goes unnoticed until someone happens to
  redeploy. Measured while fixing N5: the same stale header sentence was
  sitting in `CLAUDE/Plan/mkplan.bash` AND in the deployed dedupe-scout agent,
  unreported. The agent surface is the only one that notices at all — it
  classifies as `CUSTOMISED` — and it cannot distinguish "the user edited this"
  from "the template moved on", which is why its warning accused the daemon's
  own deployed file of being hand-hacked. A drift check would most naturally
  live where the other whole-tree checks already run.

  **Fixed**: `deployed_artefact_drift`, a SessionStart advisory sitting in the
  same priority band as `plan_workflow_asset_checker` — that one reports an
  artefact that is ABSENT, this one an artefact that is PRESENT but no longer
  matches its template. Each entry names the repair for its own surface.

  **Presence is the signal**, which is what makes it quiet in the right places:
  only artefacts on disk are compared, so a core document whose gate is off is
  absent by design rather than drifted (the trap the N5 fixture fell into), and
  an absent `mkplan.bash` stays the other handler's report so a project never
  gets two messages about one problem.

  The ownership split drives the remediation. Core docs and plan tooling are
  rewritten unconditionally, so any difference is drift and no ledger is needed
  — the part of this entry that looked hardest dissolved once the deploy
  functions were read rather than assumed. Agents are the opposite: a
  customised copy is never clobbered, so `classify_agent` decides which of the
  two cases it is, and a `CUSTOMISED` one is named with the `--force` escape
  rather than the plain command that would refuse it.

  The "cannot distinguish" complaint above is now answered rather than merely
  worked around: Plan 00378 completed the revision ledger, so `OUTDATED` and
  `CUSTOMISED` mean what they say.

- [x] ✅ **N7: `destructive_git` reads PROSE as the command.** A
  `git commit -F - <<'EOF' … EOF && git push origin main` whose message
  described the new `agents install --force` flag was denied as
  `R-GIT-PUSH-FORCE`, though the `--force` was prose inside a quoted heredoc
  the shell expands nothing in.

  **Mechanism (measured, and not what this entry first claimed).** The original
  text said the guard "saw `git push` and `--force` in one command string and
  joined them". That is wrong, and the real cause is more specific — the
  opener line was `git commit -F - <<'EOF' && git push origin main`, so the
  heredoc BODY physically follows `git push` in the command string, and
  `_GIT_PUSH_FORCE_PATTERN`'s `[^;&|]*?` excludes the three separators but NOT
  newlines. The scan therefore ran from `git push` straight down into the body
  and found `--force` there.

  That makes the defect wider than one pattern. Probed against the live
  handler (`untracked/scratch/n7_probe.py`), three shapes are falsely denied
  today and the real commands are unaffected:

  | command                                     | today | correct |
  | ------------------------------------------- | ----- | ------- |
  | the field report above                      | DENY  | allow   |
  | `python3 - <<'PY'` whose body names a reset | DENY  | allow   |
  | `git commit -m 'document --amend'`          | DENY  | allow   |
  | `git commit --amend -m 'fix typo'`          | DENY  | DENY    |
  | `git push --force origin main`              | DENY  | DENY    |

  The second row is not hypothetical: it blocked the probe written to
  investigate this entry. The third comes from a different route — the
  single-line patterns use `.*`, which stays on one line but still matches
  inside a `-m` value.

  **Fixed**: both verbs now judge `strip_inert_spans(command)`, so a
  quoted-delimiter heredoc body and an inert `-m`/`-F` value are blanked before
  any pattern runs. This covers every rule the handler enforces, not just
  force-push. Both halves were needed — blanking only the heredoc left the two
  `-m` rows above still denied, which is why the table was measured rather than
  assumed.

  The message-blanking half moved from `pipe_blocker` into
  `utils/shell_segmentation`, beside the heredoc half already shared there;
  `pipe_blocker` now calls the shared function instead of keeping its own copy.
  That is the stated purpose of that module ("One scanner, one set of rules,
  one place to fix"), and the same move Plan 00234 made for the heredoc half.

  Nothing bash would actually RUN was exempted, and both boundaries have a test
  and an acceptance test: a substituting message value (`-m "$(...)"`) and an
  unquoted `<<EOF` body are still judged.

  Blast radius was wider than the inconvenience suggested: the deny message
  asserts the command "PERMANENTLY DESTROYS data", which is flatly untrue of
  the command that ran, and a guard that cries wolf on prose is one an agent
  learns to route around.

- [x] ✅ **N8: the plan-asset advisory describes the repair as "fills gaps
  only".** `plan_workflow_asset_checker`'s `get_claude_md()` told agents the
  deploy is "idempotent (fills gaps only, never overwrites client-owned
  files)". The second clause is right; the first was wrong for exactly the
  files that matter. `_deploy_mkplan` and `_deploy_planlib` overwrite
  unconditionally — their own docstrings say "overwritten on every upgrade …
  to guarantee audit fixes reach the field". So an agent that read the advisory
  and then found a DRIFTED `mkplan.bash` concluded the offered command could
  not help, when it is precisely the repair. Found while scoping N6, whose
  remediation this sentence undercuts. **Fixed**: both the resident guidance
  and the runtime advisory now state the ownership split — client-owned files
  filled in only when absent, daemon-owned tooling rewritten — so the command
  reads as a repair. Swept for other copies of the wording: none live.

- [x] ✅ **N9: nothing notices when journal timestamps drift from the clock.**
  `journal-entry-ordering` (N1) enforces that times increase down the file, and
  `journal-append-only` forbids rewriting an entry — but neither can see a run
  of entries that is internally monotonic and uniformly WRONG. Measured in this
  plan's own day-file: entries from `14:05` onward are ~70 minutes ahead of
  real time (the `14:05`–`14:14` entries accompany commit `12119d14`, authored
  `13:15`), because I estimated the clock instead of reading it. Nothing
  reported it; it was caught only by chance when a later entry had to be
  placed.

  This is not cosmetic — the journal is the record used to reconstruct what
  happened, and a timestamp an hour out silently breaks correlation with git
  history, which is the one external clock available to check it against. That
  also suggests the fix: compare the newest entry's `HH:MM` against the
  day-file's last commit time and advise past a generous threshold. Not
  backfilled, per N1's precedent — the readings are wrong but the order is
  right, and the file is append-only.

  **Fixed**: `journal-entry-future-dated` compares the newest entry against the
  wall clock and advises past 30 minutes. Only the FUTURE direction is judged —
  writing up something that already happened is ordinary journalling, while a
  time that has not arrived cannot be anything but a mistake.

  **EDIT stage only, deliberately departing from N1's dual registration.** An
  out-of-order entry can in principle be moved, so a sweep for it is
  actionable; a wrong READING cannot be corrected once committed, so a sweep
  here could only raise findings nobody is permitted to act on. The framework
  enforces that reasoning rather than trusting it: the suite failed until the
  rule was recorded in `WRITE_ACT_ONLY_RULES` with its justification.

  Verified against the file that motivated it — this plan's own day-file — where
  it reports the newest entry as `141 minutes ahead of the clock (14:30)`, while
  `plan-qa --sweep` stays at 0 findings. That split is the design working: the
  defect is surfaced to whoever is writing, without parking a permanent
  unfixable finding in the tree.

- [x] ✅ **N10: the agent-ledger "DBF guard" asserts a tautology, and four
  shipped revisions went unledgered as a result.** Found while N6's drift
  question surfaced a live CUSTOMISED warning against
  `.claude/agents/hooks-daemon-docs-qa.md` — a file nobody had edited.

  `ledger()` computes the CURRENT version's md5 from the bundled file:
  `entries = {spec.version: content_md5(spec_source_path(spec).read_text())}`.
  So `test_current_ledger_entry_matches_bundled_file` compares
  `content_md5(file)` with `content_md5(file)` and cannot fail — while its
  docstring claims "editing a bundled agent without bumping its version and
  re-recording its md5 must fail loudly here, never ship silently". A test that
  reads as a safety net and is a no-op is worse than an absent one, because it
  is cited as coverage.

  Consequence, measured across every shipped agent's git history
  (`untracked/scratch/n10_ledger_audit.py`):

  | template      | revision    | digest        | state        |
  | ------------- | ----------- | ------------- | ------------ |
  | docs-qa       | `129aee179` | `5185213319…` | NOT ledgered |
  | opus-security | `86e4ab319` | `c300a7ed8e…` | NOT ledgered |
  | dedupe-scout  | `06077503`  | `19551a26c2…` | NOT ledgered |
  | dedupe-scout  | `daa73a3c`  | `0bff2001a0…` | NOT ledgered |

  A deployment made from any of those is classified `CUSTOMISED`, which freezes
  it: upgrades refuse to touch it for ever, and the refusal tells the reader
  they hand-edited a file they never opened. This workspace is in exactly that
  state — its docs-qa agent is the `129aee179` blob, deployed 2026-08-31, and
  the accusation is false.

  The fourth row is mine: commit `4ef11224` (N2) edited the dedupe-scout
  template and never touched `agent_assets.py`, because nothing objected.

  Not a count check either — `test_dedupe_agent_carries_historic_versions`
  asserts `len(spec.historic_md5s) >= 5`, which stays true while revisions go
  missing. Nothing asks the real question: is every revision this template has
  ever had either current or ledgered?

  **Graduated to [Plan 00378](../Completed/00378-agent-asset-ledger-guard-and-backfill/PLAN.md)
  (now Complete)**
  — three distinct defects (a tautological guard, four unrepaired field states,
  no completeness check), a design decision about where the current md5 is
  pinned, and a change to a public dataclass. Too large for the ledger, so it
  is struck from here per the Non-Goals above; the discovery evidence and audit
  output stay in this plan's journal. Dedupe scout confirmed no existing plan
  covers it (Plan 00279 built the subsystem and is prior art, not a duplicate).

  One part was repairable immediately and is done: this workspace's own
  deployed docs-qa agent was restored (`9a4bb0c9`), since it was provably a
  stale shipped blob rather than a local edit.

- [x] ✅ **N11: the post-upgrade task index listed a file that did not exist.**
  `UNRELEASED/post-upgrade-tasks/README.md` carried an index row for
  `01-drop-hooks-daemon-python-workaround.md` while the directory held only
  `README.md` — the task had been consumed by a release and the index was never
  regenerated. The README asks for this by hand ("regenerate when
  adding/removing tasks"), and nothing enforces it.

  Found while filing Plan 00375's migration task into that directory. The
  stale row is gone now, replaced by the real one, but the gap that produced it
  is untouched: an index maintained by instruction drifts at exactly the moment
  it matters, and this one describes work an upgrading agent is supposed to
  perform. An agent reading it would have gone looking for a task file that is
  not there.

  Cheap to enforce — the index rows and the directory listing are both right
  there, so a check can compare them the way the plan README's own index checks
  already do.

  **Fixed**: `post-upgrade-index-drift`, a new rule in
  `scripts/qa/check_repo_hygiene.py` — which already owns rules over the
  holding area, so no new surface was invented. It reports BOTH directions: a
  row naming a file that is gone (the case observed), and a task on disk with
  no row. The second is the worse half — work nobody is told to do — and a
  check that only looked for dead rows would have missed it entirely.

  Verified against a throwaway root carrying both shapes, so the rule was seen
  reporting before being trusted. No release-bound consequence: the check
  guards this repository's own release staging and ships nothing to a client.

- [x] ✅ **N3: `upgrade.md` never mentions post-upgrade tasks.** The
  agent-facing upgrade procedure omits the step entirely, so the tasks are not
  read even by an agent following the procedure exactly.

  **Struck to [Plan 00376](../00376-pre-upgrade-phase-with-migration-and-confirm-gate/PLAN.md)
  Task 4.3**, which owns the upgrade rework this belongs to — the same
  treatment N10 got. Not fixed here, and deliberately not left open here
  either: a ledger holding one entry that another plan is committed to
  delivering is the "sits In Progress with nothing left to do" state the Plan
  Completion Checklist warns about, and it makes "is the slate clean?"
  unanswerable.

  This gained weight while the ledger was open, which is worth saying rather
  than losing: Plan 00375 filed the first real post-upgrade task
  (`01-rewrite-plan-qa-json-level-to-severity.md`, severity `critical`), so the
  directory `upgrade.md` fails to mention is no longer hypothetical — an agent
  following the procedure exactly would now miss a migration whose failure mode
  is silence.

## Success Criteria

- [x] Every entry above is either fixed or graduated to its own plan. Nine
  fixed here (N1, N2, N4, N5, N6, N7, N8, N9, N11); two struck with pointers —
  N10 to Plan 00378, N3 to Plan 00376 Task 4.3.
- [x] No niggle in this repository exists only as chat output.
- [x] Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/28-repairing-a-drifted-deployed-artefact.md` (N4,
  N5), `29-prose-describing-a-destructive-command.md` (N7) and
  `31-a-drifted-deployed-file-now-tells-you.md` (N6). N8, N9 and N11 have none
  — N8 corrects resident guidance the daemon regenerates, and N9 and N11 are
  QA checks over this repository's own tree.

## Delivery & Milestones

- Opened on the owner's ruling: "record ALL defects, never just casually tell
  me about them without recording them… we should always have an active plan
  that is collecting small niggles".
