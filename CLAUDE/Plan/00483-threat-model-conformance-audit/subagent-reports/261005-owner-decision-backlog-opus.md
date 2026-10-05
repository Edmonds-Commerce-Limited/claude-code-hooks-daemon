# Owner decision backlog (Opus, read-only)

Plans covered: 00470, 00474, 00475, 00479, 00480, 00483, 00484, 00486, 00487, 00490. Answered items are left out, and
so are items that only need a human's hands, which are listed in their own section. Line numbers are against the tree
at `e0f882e97`.

**Counts: 46 open decisions. 23 are clear winners and 23 are real decisions. 5 items need the human's hands.**

`clear_winner: true` means one option is plainly better, a wrong choice is cheap to reverse, and nothing outward-facing,
security-weakening or costly depends on it. In every other case, or where in doubt, it is `false`.

---

## Part 1: by plan

### Plan 00470: persistent session optimisation

**00470 T2.3-Q1: quiet threshold for the cron watchdog**

- question: The supervisor will re-arm crons when the session has been silent and every recorded cron has expired. How long a silence should it wait for?
- options: any number of hours.
- recommendation: none in the plan. Mine: 2 h. The declared jobs tick at least hourly, so two missed ticks is a clear signal. The other condition (every record past the 7-day expiry) already rules out false alarms.
- clear_winner: true
- risk_if_wrong: a re-arm prompt a little early or late. It is one constant.
- source: `00470-persistent-session-optimisation/PLAN.md:54-59`

**00470 T2.3-Q2: what counts as "silent"**

- question: Should the supervisor judge silence from the terminal going quiet, or should the daemon write a "last hook event" timestamp for it to read?
- options: (a) terminal quiet as a proxy, with no daemon change; (b) the daemon stamps a marker on every hook event, at one file write per event.
- recommendation: none in the plan. Mine: (a). The expiry precondition already makes the trigger rare, so a rough signal is enough and the hot path stays untouched.
- clear_winner: false (a real accuracy-against-cost trade-off)
- risk_if_wrong: (a) could fire while hooks run with no output; (b) adds a write to every hook call.
- source: `00470-persistent-session-optimisation/PLAN.md:57`

**00470 T2.3-Q3: wording of the re-arm prompt**

- question: When the watchdog fires, should it use new text, or reuse the existing "CronList and reconcile" wording?
- options: new fixed text; reuse the `persistent_cron_assertor` wording.
- recommendation: none in the plan. Mine: reuse it, so there is one text to maintain, pinned by a test.
- clear_winner: true
- risk_if_wrong: wording only.
- source: `00470-persistent-session-optimisation/PLAN.md:58`

**00470 T3.3-Q1: automatic re-dispatch from the work queue**

- question: After a restart or a usage limit, should the session start the queued agents again by itself, or only list them as it does now?
- options: auto-respawn; list only.
- recommendation: none in the plan. Mine: list only for now, and auto-respawn once the queue has proved reliable. The plan's success criterion does ask for re-dispatch from the queue alone.
- clear_winner: false (auto-respawn spends usage with no human present)
- risk_if_wrong: auto-respawn may re-run stale or duplicate agents and burn usage. List-only keeps the hand re-brief.
- source: `00470-persistent-session-optimisation/PLAN.md:85-86`

**00470 T3.3-Q2: keeping finished queue records**

- question: Finished and abandoned queue records are kept but hidden. Should they be pruned, and when?
- options: keep forever; prune after N days; prune on demand.
- recommendation: none in the plan. Mine: prune after 14 days, as the 7-day cron records already are pruned.
- clear_winner: true
- risk_if_wrong: losing an old record nobody reads, or a file that slowly grows.
- source: `00470-persistent-session-optimisation/PLAN.md:87`

**00470 T3.3-Q3: stale "running" records**

- question: Should the re-brief age out "running" records whose coordinator is gone?
- options: age them out; leave them.
- recommendation: none in the plan. Mine: mark them stale and list them apart from live work, but never delete them silently.
- clear_winner: true
- risk_if_wrong: a stale list that misleads the re-brief.
- source: `00470-persistent-session-optimisation/PLAN.md:88`

**00470 T3.3-Q4: record which session dispatched each agent**

- question: Several coordinators share one queue. Should each record say which session dispatched it?
- options: yes; no.
- recommendation: none in the plan. Mine: yes. It is an additive field, and it is what Q1 and Q3 need to tell records apart.
- clear_winner: true
- risk_if_wrong: negligible.
- source: `00470-persistent-session-optimisation/PLAN.md:89`

**00470 T5.2: how the stand-in's one-off cron is guaranteed**

- question: When a stop says it is waiting on the owner, a cron about three hours out should wake a stand-in decider. How should the stop hook make sure that cron really gets created?
- options: block the stop until `session_crons` shows it, as `cron_stop_enforcer` already does for declared jobs; advise only.
- recommendation: the plan says "decide with the owner". Mine: block and verify through `session_crons`, which is the proven pattern.
- clear_winner: true (the stand-in concept itself was the owner's request; this is only the mechanism)
- risk_if_wrong: an awaiting-human stop with no stand-in, which is today's behaviour.
- source: `00470-persistent-session-optimisation/PLAN.md:126-136`

### Plan 00474: niggles ledger seventeen

**00474 N309: vendoring documentation pages that contain an example session id**

- question: Two Claude Code docs pages (statusline and changelog) cannot be saved locally, because an example id in them looks like a real session id to the sensitive-content check. What should happen?
- options: (a) store a documented placeholder and record the substitution in the page's provenance; (b) exempt the vendored-docs tree from that one pattern; (c) leave such pages unvendored.
- recommendation: none in the ledger. Mine: (a). The check stays whole, and the fidelity breach is recorded where a reader sees it.
- clear_winner: false (it amends either the fidelity rule or a content guard)
- risk_if_wrong: (b) could let a real session id into git; (c) leaves 00479 Task 1.1 and 00486 Task 1.3 blocked.
- source: `00474-niggles-ledger-seventeen/NIGGLES.md:2014-2030` (duplicates: 00479 PLAN.md:71-75, 00486 PLAN.md:45)

**00474 N296: what an acceptable "log and carry on" looks like to the error-hiding audit**

- question: The error-hiding audit only recognises a log call written inline, so code that logs through a helper slips past it. What form should a justified "log and carry on" take?
- options: one recognised, reviewable marker; a named helper that the audit allowlists.
- recommendation: none in the ledger. Mine: a single helper that takes a required reason argument, so every use is searchable and shows its reason, plus the audit widened to catch log-then-continue bodies.
- clear_winner: false (it allowlists an error-hiding exception, which the repository reserves for a human)
- risk_if_wrong: either real failures stay hidden behind helpers, or justified cases keep getting reworked to dodge the audit.
- source: `00474-niggles-ledger-seventeen/NIGGLES.md:1221-1245`

**00474 N314: the exception list for a module-size gate**

- question: The module-length report finds 26 modules over 1,000 lines. Should it become a gate, and with which exception list?
- options: stay report-only; gate with a frozen exception list that may only shrink; gate with no exceptions, which would mean splitting now.
- recommendation: none in the ledger. Mine: gate with a shrink-only list of today's 26 modules. 00483 R5 asks for the same thing for three of them.
- clear_winner: false (an allowlist needs owner approval)
- risk_if_wrong: more modules grow unnoticed, or a gate that blocks unrelated work.
- source: `00474-niggles-ledger-seventeen/NIGGLES.md:1902-1917`

**00474 N289: delete 13 GB of old probe copies under `untracked/scratch`**

- question: Most of the remaining session-start sweep cost is about 13 GB of whole-repository probe copies from earlier review runs. Should they be deleted?
- options: delete; keep; move them out of the repository.
- recommendation: the ledger says "the owner's call". Mine: delete, after checking that no live worktree or open report points into them. The conclusions are already in the reports.
- clear_winner: false (a bulk deletion that cannot be undone)
- risk_if_wrong: losing evidence a later dispute might want, or a slow sweep from keeping them.
- source: `00474-niggles-ledger-seventeen/NIGGLES.md:1012-1014`

N350 (`NIGGLES.md:1463-1471`) and N352 (`:1427-1429`) are parked on 00483 R3 and R4. They are not separate decisions.

### Plan 00475: targeted QA and small batches

**00475 T4.1: should the branch-count check ever block?**

- question: A start-of-session notice warns when more than 3 work branches are open. Should it stay a warning, or start blocking?
- options: advisory; blocking.
- recommendation: none in the plan. Mine: stay advisory. A block would stall the coordinator mid-batch, and the warning already fires.
- clear_winner: true
- risk_if_wrong: branch build-up continues, which is visible and reversible.
- source: `00475-targeted-qa-and-small-batches/PLAN.md:167-171`

**00475 T4.2: should merging without a recorded green QA run be blocked?**

- question: Merging a branch with no recorded passing targeted-QA run now draws a warning. Should it be blocked instead?
- options: advisory; blocking.
- recommendation: none in the plan. Mine: block for work branches. N278, N297 and N310 (six instances) show the warning alone has not kept `main` green.
- clear_winner: false (it adds merge friction, and a block can stall work when QA is slow or the lock is held)
- risk_if_wrong: either `main` keeps going red, or the coordinator is blocked on QA runs.
- source: `00475-targeted-qa-and-small-batches/PLAN.md:172-185`

### Plan 00479: subscription usage monitor and ceiling

**00479 Q2: several matching host entries**

- question: If more than one host entry matches, which usage ceiling wins?
- options: the lowest ceiling; the first match in file order.
- recommendation (plan): the lowest ceiling, as the safer choice. It is already built that way.
- clear_winner: true
- risk_if_wrong: a session pauses a little earlier than intended.
- source: `00479-subscription-usage-monitor-and-ceiling/PLAN.md:197-199`

**00479 Q3: one threshold or one per window**

- question: Should the ceiling be one number for both the 5-hour and the weekly windows, or one per window?
- options: one number; one per window; one number with optional per-window overrides.
- recommendation (plan): one number with optional overrides. It is already built that way.
- clear_winner: true
- risk_if_wrong: config ergonomics only.
- source: `00479-subscription-usage-monitor-and-ceiling/PLAN.md:200-202`

**00479 Q4: move cron host selection into the new `hosts:` block**

- question: Should the per-cron `hosts:` lists later move into the new top-level `hosts:` block, so all host settings live in one place?
- options: fold them in later; keep both.
- recommendation: none in the plan. Mine: fold them in at the next major, with a config-changes entry, and keep the old form working until then.
- clear_winner: false (a config schema change that client projects see)
- risk_if_wrong: two ways to say the same thing, or a breaking config migration.
- source: `00479-subscription-usage-monitor-and-ceiling/PLAN.md:203`

### Plan 00480: plan fact checker and debounce

**00480 Q1: who runs the fact check**

- question: When a plan is edited, who should run the fact-checker: the session itself, prompted through the supervisor, or a separate headless Claude process that the daemon starts?
- options: (a) the session, through the supervisor turn channel; (b) a headless `claude -p` subprocess.
- recommendation (plan): (a) when a supervisor is present, otherwise an advisory on the next hook event.
- clear_winner: true ((a) spends nothing outside the session and needs no credentials in the daemon; (b) is the costly option)
- risk_if_wrong: checks are delivered less reliably in sessions without a supervisor.
- source: `00480-plan-fact-checker-and-debounce/PLAN.md:130-140`

**00480 Q2: should a refuted claim block the plan commit?**

- question: Should an unresolved refuted claim block the plan's next commit, or only be reported?
- options: block; report.
- recommendation (plan): report first, and decide on blocking once the false-refutation rate is known.
- clear_winner: true
- risk_if_wrong: a false claim lands with a warning attached.
- source: `00480-plan-fact-checker-and-debounce/PLAN.md:142-143`

### Plan 00483: threat model conformance audit

The guard-effort review (`subagent-reports/261004-guard-effort-pragmatism-review-opus.md`) is the main input for Q4.
Q2, Q3 and several ledger items depend on R3 and R4.

**00483 Q4-R1: confirm the freeze on new tightening in the secret-guard area**

- question: The coordinator froze new tightening in the secret-guard area, so only fixes for false denials go ahead. Do you confirm the freeze?
- options: confirm; lift.
- recommendation (review): confirm, until the R2 gate exists.
- clear_winner: true (it is already in effect, it is cheap to lift, and it only pauses new work)
- risk_if_wrong: an ordinary-route bypass waits longer for its fix.
- source: `00483-threat-model-conformance-audit/PLAN.md:199-200`; review `:262-266`

**00483 Q4-R2: a regression gate built from ordinary commands**

- question: Should a corpus of real everyday commands become a merge gate, so that any guard change turning one of them from allowed to denied fails?
- options: approve as a merge gate; build it as a report only; skip it.
- recommendation (review): approve as a merge gate, seeded from N79's 171 commands, over a realistic fixture tree.
- clear_winner: true (it weakens nothing: a new deny still lands once you add a row for it)
- risk_if_wrong: build effort, and occasional friction when a deny is wanted.
- source: `00483-threat-model-conformance-audit/PLAN.md:202`; review `:268-277`

**00483 Q4-R2b: block releases on open false-positive reports**

- question: Should any client-filed false-positive issue in this area block the next minor release until it is fixed or accepted?
- options: yes; no.
- recommendation (review): yes.
- clear_winner: false (it changes release policy, and the release is human-gated)
- risk_if_wrong: a delayed release, or false positives shipping to clients.
- source: review `:278-279` (not repeated in PLAN.md)

**00483 Q4-R3: amend the fail-closed rule**

- question: Today a guard denies whenever a size cap or time limit runs out, even on harmless commands. Should it deny only on a literal protected name or a command it cannot parse at all, and otherwise allow with a warning?
- options: amend as proposed; keep fail-closed; a middle ground, such as a raised cap with fail-closed kept.
- recommendation (review): amend.
- clear_winner: false (it amends ARCHITECTURE.md's "what this ruling does not change", and a command built to exhaust a cap would pass)
- risk_if_wrong: amending lets a crafted, limb-2 command through; keeping it means load- and size-dependent denials of ordinary commands continue (N348, N352, #64, #66, #68).
- source: `00483-threat-model-conformance-audit/PLAN.md:203-204`; review `:281-296`. It also absorbs the INVENTORY fail-closed owner calls (`INVENTORY.md:303`, `:367`, `:379`, `:587`, `:841`, `:976`: `git am`, `cd "$(git rev-parse …)"`, a loop variable in `git branch -D`, and containment's unresolved-variable deny) and N352.

**00483 Q4-R4 (with Q2): remove out-of-scope and per-call filesystem code**

- question: Should we remove the code that walks the filesystem on every command (bare-glob expansion, the 250,000-entry tree scan) and use a cached index instead? Should we also delete about 2,000 to 3,500 lines that only catch deliberately obfuscated shapes?
- options: per item: remove, narrow, or keep (the R4 table and the INVENTORY list).
- recommendation (review): remove all of the R4 table. That is roughly 2,000 to 2,500 lines, and the review finds no loss on any ordinary route.
- clear_winner: false (removal is explicitly the owner's decision, and it changes protection)
- risk_if_wrong: removal could drop a route that turns out to matter; keeping it means the false positives and maintenance cost continue (N348, N350, #68, FP-1 to FP-4).
- source: `00483-threat-model-conformance-audit/PLAN.md:181-182, 205`; review `:298-310`; `INVENTORY.md:1259-1293`. Absorbs N350 and Task 3.3.

**00483 Q4-R5: an effort budget for the area**

- question: Should work in this area be capped: one open branch, at most two review rounds, no net growth in lines, a latency limit per command, and the size gate on the three biggest modules?
- options: adopt; adopt in part; no budget.
- recommendation (review): adopt.
- clear_winner: true (a process limit that weakens no guard and is easy to lift)
- risk_if_wrong: a legitimate fix needs a third round or extra lines and has to ask for an exception.
- source: `00483-threat-model-conformance-audit/PLAN.md:206-207`; review `:312-323`

**00483 Q4-R6: return strict mode to only commands that change something**

- question: Strict mode for chained shell commands now blocks read-only sequences too. Should it go back to applying only when a command modifies something?
- options: (a) `only_with_mutator: true`; (b) keep block mode with a compound-aware splitter; (c) drop it to a warning.
- recommendation (review): (a).
- clear_winner: false (it reverses the owner's N308 ruling, "on by default … harmless")
- risk_if_wrong: (a) lets an unguarded read-only chain run blind, which is low harm; keeping it means more false denials (N312, N321, N339, N320).
- source: `00483-threat-model-conformance-audit/PLAN.md:207` (bundled into R5 there); review `:325-341`; ruling at `00474-niggles-ledger-seventeen/NIGGLES.md:2032-2046`

**00483 Q4-R7: the keep / narrow / drop list for in-flight items**

- question: For the remaining guard items, do you accept the review's verdict on each?
- options: per item, as below.
- recommendation (review): keep N23, N35, N53, N86, N91, N95, N98, N260, N197 (low), and N222 (test half); keep N350 only if R4 is not approved; narrow N229 (about 20 lines, otherwise drop) and N75 (file extensions only); drop N76; defer N28; promote N79 into R2; resolve N74 with R4's cached index.
- clear_winner: false (the drops and narrowings dismiss in-scope defects)
- risk_if_wrong: a dropped ordinary leak route stays open (N76, N229), or effort is spent on low-value parsing.
- source: `00483-threat-model-conformance-audit/PLAN.md:208`; review `:343-367`

**00483 Q3: the capped tree walk defaults (O1–O5)**

- question: The coordinator built the N130 tree walk with five defaults: fixed caps; the Grep tool treated as reading every file; deny past the cap; quarantine fails closed; the index deferred. Do you overturn any of them?
- options: keep each default, or overturn it.
- recommendation: the coordinator's defaults stand. The review says they are superseded if R3 and R4 are approved.
- clear_winner: false (O2 and O3 decide what a protected-file search denies)
- risk_if_wrong: either size-dependent denials, or a root Grep of an ignored protected file is allowed.
- source: `00483-threat-model-conformance-audit/PLAN.md:183-194`; review `:364`

**00483 Q5: N98, the fallback socket path is shared across hostnames**

- question: When several machines share a home directory, their daemons can collide on one fallback socket path. A fix exists, but it changes paths on upgrade, and generated forwarders would need regenerating. Take the fix, or leave it?
- options: take it, with a forwarder-regeneration step on upgrade; leave it.
- recommendation: none in the plan (the coordinator parked it as rare); the review says keep. Mine: take it at the next minor, with the regeneration step and a release note.
- clear_winner: false (an upgrade-time path change for clients)
- risk_if_wrong: a broken forwarder after upgrade, or a rare cross-host collision left in place.
- source: `00483-threat-model-conformance-audit/PLAN.md:209-214`

**00483 T2.2: nine uncovered dangerous commands**

- question: Nine ordinary but dangerous commands are not blocked by anything today: `git reset --keep`, `rm -rf`, `truncate -s 0`, `git push --delete`, `git tag -d`, `pip install --index-url`, `gh auth token`, `crontab -r`, and `docker run -v /:/host`. Each new block needs your approval. Which, if any, should be blocked?
- options: per row: block, warn, or accept as uncovered.
- recommendation: none in the plan. Mine: warn first for `rm -rf`, `git push --delete`, `git tag -d` and `crontab -r`, and decide the rest after R2 exists so the false-positive cost can be measured.
- clear_winner: false (new denies change the security posture and can break ordinary work)
- risk_if_wrong: an unguarded destructive command, or a wave of new false denials.
- source: `00483-threat-model-conformance-audit/PLAN.md:98-107`

**00483 RULINGS-ext: confirm the four coordinator-extended Fable rulings**

- question: The Fable delegation you gave covered N154, N230 and N240. The coordinator extended it to N55 (fix), N62 (no change), N74 (no change, accepted residual) and N96 (refactor plan). Do you confirm those four?
- options: confirm each, or overrule it.
- recommendation: confirm. N55 has already shipped (ae62d27d1, release note 216). Note that the review's R7 proposes resolving N74 differently, through R4's index.
- clear_winner: false (N74 accepts a protected-file read route as a residual)
- risk_if_wrong: `grep -r` above a protected path stays allowed.
- source: `00483-threat-model-conformance-audit/RULINGS-owner-delegated-fable.md:12-24`; `TRIAGE-ledger-466.md:97-111`

### Plan 00484: DBF adoption and toolchain conformance

The owner batch is in `REVIEW-fable.md:138-163`, and the gap table in `CONFORMANCE.md:369-389`. G5–G9, G12, G13 and G15
need no ruling.

**00484 DEFSET: which guards are "DBF Defences"**

- question: For the public conformance claim, are the action guards (destructive git, stash, squash, pipe, sed, strict mode, root scan) DBF Defences, or guardrails outside that set?
- options: inside the Defence set; outside it, with the content and commit gates declared as the Defence set.
- recommendation (Fable): outside.
- clear_winner: false (it shapes a published conformance claim)
- risk_if_wrong: a public claim that overstates or understates what the daemon defends.
- source: `00484-dbf-adoption-and-toolchain-conformance/REVIEW-fable.md:143-145`

**00484 G1: inline QA suppressions**

- question: About 62 live `# nosec` markers and others are honoured inline. Should they move into one reasoned exceptions file, with about 173 inert markers deleted and any new inline suppression failing QA?
- options: close as described; accept as a known gap.
- recommendation (Fable): yes, close.
- clear_winner: false (it sets up a standing exceptions list, which needs owner approval)
- risk_if_wrong: churn across many files, or a published known gap.
- source: `REVIEW-fable.md:146-147`; `CONFORMANCE.md:376`

**00484 G2: the four agent-typable escape hatches (`MUST_*_BECAUSE`)**

- question: `MUST_SQUASH_BECAUSE`, `MUST_STASH_BECAUSE`, `MUST_SCAN_ROOT_BECAUSE` and `MUST_SKIP_SAFE_MODE_BECAUSE` let an agent bypass a guard by typing a reason. They predate the "no agent-typable escape hatch" rule. Keep them, with the hygiene fixes, or remove them?
- options: keep and fix (outside the Defence set); remove; keep and declare a known gap.
- recommendation (Fable): keep, fix (the no-reason hatch, the `-->` closer bug, the generic-reason check), and place them outside the set.
- clear_winner: false (it decides whether an agent-typable bypass stays)
- risk_if_wrong: an agent keeps a bypass contrary to Plan 00259, or ordinary needs lose their documented route.
- source: `REVIEW-fable.md:148-150`; `CONFORMANCE.md:377`. Duplicate: `00483 INVENTORY.md:1295-1297`.

**00484 G3: the in-file `MUST_EXCEED_*_BECAUSE` tokens**

- question: Should the in-file size-limit override tokens be listed and reason-checked, or accepted as a known gap?
- options: close; accept.
- recommendation (Fable): close; it is cheaper than writing the gap line.
- clear_winner: true
- risk_if_wrong: a small listing tool that is not needed.
- source: `REVIEW-fable.md:151-152`

**00484 G4: reasons on config exceptions**

- question: Should config exceptions (`exclude_paths`, `extra_whitelist`) accept a reason now, require one under strict mode, and require one for everyone at the next major?
- options: as described; reasons optional for ever.
- recommendation (Fable): yes.
- clear_winner: false (a breaking config change for clients at the next major)
- risk_if_wrong: client configs break on upgrade, or exceptions stay unexplained.
- source: `REVIEW-fable.md:153-154`; `CONFORMANCE.md:379`; `00484 PLAN.md:111-112` (§6.1 question)

**00484 G10: confirm the linters are not Defences**

- question: Confirm the statement "no DBF Defence is routed through ruff, mypy, pyright, bandit or shellcheck; they run as checks".
- options: confirm; amend.
- recommendation (Fable): confirm; it is not a gap.
- clear_winner: true
- risk_if_wrong: wording in the declaration.
- source: `REVIEW-fable.md:155-156`

**00484 G11: the batch "scan" mode**

- question: Build a `scan <handler> <paths>` sweep mode in this plan, or file it as a follow-up?
- options: build here; follow-up plan.
- recommendation (Fable): follow-up; `probe --only` stays in this plan.
- clear_winner: true
- risk_if_wrong: DBF tools wait longer for sweeps.
- source: `REVIEW-fable.md:157-158`

**00484 G14: what the declaration says about failure behaviour**

- question: What should the public declaration say about what happens when the daemon is down?
- options: Fable's text (defences "fail open"); the coordinator's correction (they fail closed except in named setup states: not installed, venv missing, version mismatch, repository unconfigured, CI).
- recommendation: the coordinator's corrected wording. Fable's text contradicts the code (`.claude/init.sh` around 612–637).
- clear_winner: false (published externally)
- risk_if_wrong: a public statement that misdescribes the product.
- source: `REVIEW-fable.md:159-160`; correction at `00484 PLAN.md:99-106`

**00484 G16: grade the method and detector levels before publishing**

- question: Before publishing, grade SPEC §7 and declare the detector level, or publish the toolchain level only, with those two listed as not assessed?
- options: grade both; publish the toolchain level only.
- recommendation (Fable): grade both, since it is a short job.
- clear_winner: true
- risk_if_wrong: a small delay to Task 3.3.
- source: `REVIEW-fable.md:161-163`

**00484 T1.4: post the adoption comments on #65 and #67**

- question: You ruled that DBF is adopted and linked. May the agent post that ruling as comments on GitHub #65 and #67 ("Addresses", no closing keyword) and remove the `agent-needs-human` label?
- options: post; hold.
- recommendation: post. The content is your own ruling.
- clear_winner: false (it publishes to GitHub)
- risk_if_wrong: a public comment that cannot be retracted.
- source: `00484-dbf-adoption-and-toolchain-conformance/PLAN.md:84-85`

### Plan 00486: Claude Code version tracking

**00486 T2.2: review Claude Code changes between releases, or only at release time**

- question: Should the Claude Code changelog be reviewed each time a new Claude Code version is first seen, as a routine, or only at each daemon release?
- options: a routine on each new version; release-only.
- recommendation: none in the plan. Mine: release-only for now. The drift advisory (Task 2.1) already tells a session it is on an unreviewed version, and a per-version routine spends a review every few days.
- clear_winner: true
- risk_if_wrong: a conflicting Claude Code change is noticed later, at the release.
- source: `00486-claude-code-version-tracking/PLAN.md:52`

**00486 D1–D3: confirm the coordinator's rulings**

- question: The coordinator chose a YAML file for the per-release record (D1), a release sub-step 1c for the review (D2), and a backfill from 2.1.272 (D3). Confirm them?
- options: confirm; overturn any.
- recommendation: confirm. They are internal, already built, and reversible.
- clear_winner: true
- risk_if_wrong: a file-format change later.
- source: `00486-claude-code-version-tracking/DECISIONS.md:6-29`

### Plan 00487: supervisor plugin API and ccy restart plugin

There are no open decisions. D1–D7 in `OWNER-DECISIONS.md` are all answered. The remaining work needs the human's
hands (below).

### Plan 00490: GitHub issue assignment guard

**00490 Q1: should the handler assign issues itself?**

- question: When work is tied to an unassigned issue, should the handler assign it to you itself, or tell the agent the exact command to run?
- options: claim automatically; tell the agent.
- recommendation (plan): tell the agent, because assignment publishes to GitHub and the command then shows in the transcript.
- clear_winner: true
- risk_if_wrong: one extra step per issue.
- source: `00490-github-issue-assignment-guard/PLAN.md:116-117`

**00490 Q2: on by default for client projects?**

- question: Should the guard be on by default for other projects, or only here at first?
- options: on; off in the client template.
- recommendation (plan): off for clients and on here, until it has run here for a while.
- clear_winner: true
- risk_if_wrong: clients get the feature one release later.
- source: `00490-github-issue-assignment-guard/PLAN.md:118`

**00490 Q3: what to do when `gh` cannot answer**

- question: When GitHub cannot be asked (offline, not signed in, several accounts), should the guard warn and allow, or deny?
- options: advise; deny.
- recommendation (plan): advise.
- clear_winner: true (denying would block every offline session working on an issue-tied plan; this is a workflow guard, not secret protection)
- risk_if_wrong: someone else's issue is worked on while offline.
- source: `00490-github-issue-assignment-guard/PLAN.md:119-120`

---

## Part 2: clear winners (23)

Each can be approved as recommended in one go:

| id            | approve                                                          |
| ------------- | ---------------------------------------------------------------- |
| 00470 T2.3-Q1 | 2 h quiet threshold                                              |
| 00470 T2.3-Q3 | reuse the "CronList and reconcile" wording                       |
| 00470 T3.3-Q2 | prune finished queue records after 14 days                       |
| 00470 T3.3-Q3 | mark stale "running" records, never silently delete              |
| 00470 T3.3-Q4 | records carry their dispatching session                          |
| 00470 T5.2    | block the stop until the one-off cron is seen in `session_crons` |
| 00475 T4.1    | branch-count check stays advisory                                |
| 00479 Q2      | lowest ceiling wins (as built)                                   |
| 00479 Q3      | one threshold with per-window overrides (as built)               |
| 00480 Q1      | (a) the session runs the check via the supervisor                |
| 00480 Q2      | report refuted claims, do not block yet                          |
| 00483 Q4-R1   | confirm the tightening freeze                                    |
| 00483 Q4-R2   | ordinary-command regression corpus becomes a merge gate          |
| 00483 Q4-R5   | adopt the effort budget                                          |
| 00484 G3      | close the in-file token gap                                      |
| 00484 G10     | confirm the linters are not Defences                             |
| 00484 G11     | scan mode as a follow-up plan                                    |
| 00484 G16     | grade method and detector levels before publishing               |
| 00486 T2.2    | release-only changelog review for now                            |
| 00486 D1–D3   | confirm the coordinator's three rulings                          |
| 00490 Q1      | tell the agent; do not auto-claim                                |
| 00490 Q2      | off for clients, on here                                         |
| 00490 Q3      | advise when `gh` cannot answer                                   |

## Part 3: real decisions (23)

| id                | why it is not a clear winner                                    |
| ----------------- | --------------------------------------------------------------- |
| 00470 T2.3-Q2     | accuracy against a write on every hook call                     |
| 00470 T3.3-Q1     | auto-respawn spends usage unattended                            |
| 00474 N309        | amends the fidelity rule or a content guard                     |
| 00474 N296        | an error-hiding allowlist is reserved for a human               |
| 00474 N314        | an allowlist for a new gate                                     |
| 00474 N289        | irreversible 13 GB deletion                                     |
| 00475 T4.2        | merge friction against `main` staying red                       |
| 00479 Q4          | client-visible config schema change                             |
| 00483 Q4-R2b      | changes release policy                                          |
| 00483 Q4-R3       | amends the fail-closed rule in ARCHITECTURE.md                  |
| 00483 Q4-R4 (+Q2) | removes guard code; removal is the owner's decision             |
| 00483 Q4-R6       | reverses the owner's N308 ruling                                |
| 00483 Q4-R7       | drops and narrows in-scope defects                              |
| 00483 Q3 (O1–O5)  | decides what a protected-file search denies (moot if R3 and R4) |
| 00483 Q5 (N98)    | client path change on upgrade                                   |
| 00483 T2.2        | nine new denies, posture change                                 |
| 00483 RULINGS-ext | N74 accepts a read-route residual                               |
| 00484 DEFSET      | shapes a published claim                                        |
| 00484 G1          | creates a standing exceptions list                              |
| 00484 G2          | keeps agent-typable bypasses                                    |
| 00484 G4          | breaking config change at the next major                        |
| 00484 G14         | published wording                                               |
| 00484 T1.4        | posts to GitHub                                                 |

Suggested order: 00483 R3 and R4 first. They settle 00483 Q2, Q3, Task 3.3, R7's N350 and N74 rows, N350 and N352,
and they set the frame for 00490 Q3.

---

## Needs the human's hands, not a decision (5)

1. **00470 T3.5:** install the host restart unit (systemd `Restart=always` or a shell loop) around ccy on the server,
   with `--continue`, back-off, and `HOOKS_DAEMON_HOSTNAME=cchd-sdlc-runner` for the SDLC runner, then record it in
   `RUNBOOK.md` §3. Source: `00470 PLAN.md:95-98`, `RUNBOOK.md:49-61`.
2. **00470 T6.3:** dogfood probe of extra agent threads in one Claude Code session (left arrow, then a new thread), to
   see their `session_id`, transcript and `session_crons`. It needs someone at the UI. Source: `00470 PLAN.md:151-154`.
3. **00479 live ceiling:** put a `hosts:` usage ceiling in the config of a host you choose (never this repository's
   tracked config), so that a real pause with real `CronDelete`/`CronCreate` calls is observed. Source:
   `00479 PLAN.md:219-223`.
4. **00487 T3.1:** merge fedora-desktop PR 66 into F44, run the claude-yolo play, `ccy --rebuild`, and run `qa-all.bash`
   on the host. The host agent then drives `OWNER-LIVE-TEST.md`. Task 3.2 (comments on #71 and fedora-desktop#61)
   follows. Source: `00487 PLAN.md:119-120`, `OWNER-DECISIONS.md` D1 and D5.
5. **00487 D4 / release:** type `/release` for a hooks-daemon release carrying the supervisor plugin API. Until then,
   other projects cannot use `--max-age`. Source: `OWNER-DECISIONS.md:36-41`, `OWNER-LIVE-TEST.md:8`.

Not yet ripe (no data to decide from): **00470 T4.3**, choosing the orchestrator model from an A/B record that has not
been measured yet (`00470 PLAN.md:113`).

---

## Duplicates across plans

- **N309** is the same decision as **00479 Task 1.1** and **00486 Task 1.3**. One answer unblocks all three.
- **00483 Q2** (out-of-scope-only code) is the INVENTORY list that **R4** proposes acting on. Answer them together.
- **00483 INVENTORY escape hatches** (`INVENTORY.md:1295-1297`) are the same four hatches as **00484 G2**.
  `MUST_SKIP_SAFE_MODE_BECAUSE` also touches **R6**.
- **N352** is evidence for **R3**, and **N350** is resolved by **R4** (or kept per R7). Neither is a separate question.
- **N314** (module-size gate exceptions) overlaps **R5**'s "make the size check a gate for the three area modules".
- **N98** appears as **00483 Q5** and as a "keep" row in **R7**.
- **N74** has two answers on disk: the Fable ruling says no change, accepted residual (`RULINGS…:19`), while R7 says
  resolve it with R4's cached index. Settle it with R4.
- **00470 T3.3 Q1–Q4** are repeated in `00470 JOURNAL/00470-Journal-26-10-04.md:52`. It is the same set.
- **00490 Q3** follows the R3 direction ("advise, not deny, when a check cannot finish"), but stands on its own.
- **R6** would reverse the owner ruling recorded at **00474 N308**.

## Moot, stale or already answered

- **00483 Q3 (O1–O5)** is largely moot if R3 and R4 are approved (review `:364`).
- **00486 non-goal, filing a ccy issue about restarting on Claude Code updates** (`00486 PLAN.md:29`): 00487's max-age
  plugin now restarts ccy sessions onto the current Claude Code version, so this is likely moot. It is not counted.
- **00487 HANDOVER.md:12** still says the owner decides where Tasks 1.4 and 1.5 go. D2 answered that (moved to Plan
  00489). **OWNER-LIVE-TEST.md:6** still says "no PR", but PR 66 exists (D1, D6). Both are stale text.
- **00474 CARRIED-REFIX-BRANCHES.md:23-29** still counts 3 "Needs owner". All three are settled (N154 and N230 fixed,
  N240 ruled no change), so the column is stale.
- **00474 N271** (uv locations) was answered by owner ruling (`NIGGLES.md:540-550`). **00474 N327** has its decision
  recorded (`:1732`).
- **00479 Q1** and **00483 Q1** are marked resolved by the owner.
- **00487 D1–D7** are all answered.
- **00483 JOURNAL 26-10-03:52** refers to "the 19-item decision list from the coordinator session", which is still
  unanswered. That list is not on disk in any of these plans, so this backlog may not cover all of it. If the owner
  still has it, compare it with this list.
