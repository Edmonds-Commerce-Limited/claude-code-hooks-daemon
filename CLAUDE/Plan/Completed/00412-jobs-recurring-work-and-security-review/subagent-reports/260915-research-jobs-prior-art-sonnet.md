# Prior art: modelling recurring operational work as documents-plus-automation

Research for Plan 00412. Online sources only; every claim below is attributed, and
the closing section lists what could not be verified against a primary source.

## The short version

Five patterns are worth stealing outright. Each is expanded below.

1. **Template vs instance.** The recurring-work *definition* and the *record of one
   execution* are different documents with different lifecycles. Release-checklist
   practice is unambiguous about this: the template is never ticked, a copy is.
2. **Coverage-as-interval, not a pointer.** `cargo-vet` records `delta = "X -> Y"` on
   the audit record itself rather than keeping a mutable "last audited" pointer.
   Intervals compose, so a gap is *detectable*; a pointer that gets bumped wrongly is
   silent forever. This is the single most important idea in this report.
3. **A delta run is structurally blind, so the periodic full run is a compensating
   control, not a nicety.** CodeQL states the limitation explicitly. Declare which
   checks are delta-able and which are full-only, and make a delta run record say
   which checks it did *not* run.
4. **Catch-up should widen the next run's interval, not replay missed runs.** systemd
   `Persistent=` catches up with a *single* activation. Airflow ships `catchup=False`
   as the default precisely because replaying is usually the wrong answer.
5. **Absence of a run is not observable from the run records.** Something outside the
   job must assert "a run is overdue" — the dead-man's-switch pattern. This project
   already has the machinery (`persistent_cron_assertor`, the SessionStart sweeps).

And one naming conclusion: **"Job" has a concrete, local collision** — this repo's own
`.github/workflows` uses `jobs:`, and 00412 plans to drive the concept *from* the
persistent-cron system, so "the cron job that runs the job" is a sentence the docs
would have to write. Recommendation and reasoning in section 5.

---

## 1. Runbooks and operational playbooks

### 1.1 What a runbook contains

Google's SRE Workbook defines the artefact narrowly:

> "Playbooks contain high-level instructions on how to respond to automated alerts.
> They explain the severity and impact of the alert, and include debugging suggestions
> and possible actions to take to mitigate impact and fully resolve the alert."

— <https://sre.google/workbook/on-call/>

The ITIL lineage uses a two-tier split that is directly relevant to 00412's structure:
a **procedure/SOP** gives the higher-level steps, a **work instruction** gives the
detailed ones; ITIL calls the SOP manual a *run book*
(<https://en.wikipedia.org/wiki/Standard_operating_procedure>,
<https://wiki.en.it-processmaps.com/index.php/IT_Operations_Control>).

Industry runbook templates converge on a consistent section list: overview and severity,
prerequisites stated up-front, verification at each step, an explicit **rollback**
section, and contacts/related docs at the end
(<https://docs.firehydrant.com/docs/runbook-best-practices>,
<https://www.pagerduty.com/resources/automation/learn/what-is-a-runbook/>).
The recurring advice is that the *structure* being identical across runbooks is what
stops a team forgetting a section like rollback or escalation criteria.

### 1.2 How a RUN is recorded separately from the runbook

This is where the general runbook literature is weakest and the compliance and
release-engineering literature is strongest — see sections 2.1 and 2.2. Runbook practice
mostly assumes an incident ticket already exists to hold the per-execution record, so it
never has to solve the problem. **00412 has no such ambient ticket**, which is exactly
why the run record has to be a first-class designed artefact rather than an afterthought.

The one runbook-side practice that does record runs is **drill reporting**: a DR drill
report records the scenario, the initiation and completion times, the actions, the
results, the issues, and the lessons learned — and the whole point is that this is
per-drill, retained, and used as audit evidence
(<https://oneuptime.com/blog/post/2026-09-02-disaster-recovery-testing-cadence/view>,
<https://cutover.com/blog/disaster-recovery-exercises-must-try-examples>).
CISA publishes an after-action report / improvement plan template for exactly this shape.
The **after-action report** is the closest existing name for what 00412 calls a run record.

### 1.3 How people stop runbooks rotting

The honest statement of the problem, from Google:

> "Details in playbooks go out of date at the same rate as production environment
> changes." — <https://sre.google/workbook/on-call/>

The same page names an unresolved tension that 00412 will have to take a position on:

> Some SREs advocate "keeping playbook entries general so they change slowly"; others
> prefer "step-by-step playbooks to reduce human variability and drive down MTTR."
> "If your team has conflicting views about playbook content, the playbooks might get
> pulled in many directions."

**The trade-off, stated plainly:** generality buys slow rot at the cost of requiring a
trained operator; specificity buys low variance at the cost of fast rot. The way out that
the runbook-as-code literature proposes is to *split the document along that seam* —
slow-changing WHY/scope/criteria stay prose, fast-changing exact commands become
executable and therefore testable, so rot surfaces as a failing run rather than a
silently wrong instruction. `Runbook.md` (<https://github.com/kjkuan/Runbook.md>) makes
Markdown code blocks directly bash-executable; the broader argument is at
<https://www.tines.com/blog/what-are-runbooks-and-how-to-automate-them/> and
<https://adhdecode.com/reliability-engineering/runbooks-and-playbooks/executable-runbooks/>.

Four anti-rot mechanisms recur across sources
(<https://oneuptime.com/blog/post/2026-09-02-keep-disaster-recovery-runbooks-current/view>,
<https://opspilot.com/blog/ai-sre-runbook-automation-why-runbooks-go-stale/>):

| Mechanism                                                         | Guards against                              | Cost                                 |
| ----------------------------------------------------------------- | ------------------------------------------- | ------------------------------------ |
| Named individual owner per runbook                                | Diffuse ownership → nobody updates it       | Owner churn leaves it orphaned       |
| Scheduled execution against staging                               | Instructions that no longer work            | Needs a safe place to execute        |
| Change-triggered review (deploy pipeline flags affected runbooks) | Environment drifting out from under the doc | Needs a doc↔component mapping        |
| Post-incident update as part of the incident                      | Known-wrong steps surviving                 | Only fires when there is an incident |

**The strongest single mechanism for 00412 is the second one, inverted**: because a Job
*is* executed on a cadence, every run is already an execution test of its own document.
Make the run record carry "the document was wrong here" as a first-class outcome field
and rot becomes self-reporting. That is a property Plans do not have and Jobs get free.

### 1.4 Google g3doc freshness metadata

Google's internal doc system carries a machine-readable freshness stamp, visible in
open-sourced g3doc trees:

```
<!--* freshness: {owner: '<user name>' reviewed: '<last review date in format yyyy-mm-dd>' *-->
```

placed "immediately after page title"
(<https://webrtc.googlesource.com/src/+/main/g3doc/how_to_write_documentation.md>).

**Worth stealing, with a caveat.** It cleanly separates "reviewed and still correct"
from "nobody has looked at this since 2019" — two states that are otherwise
indistinguishable and that a linter can check. The caveat is that the date is
self-asserted and can be bumped without reading. For 00412 the fix is available and
cheap: **derive the freshness date from the last run record rather than letting a human
type it**, so the claim "this doc is current" is backed by an execution rather than an
assertion.

### 1.5 Checklist design (Gawande)

Two checklist types, and the distinction matters for how a Job document is written
(<https://sketchplanations.com/read-do-do-confirm-checklists>,
<https://grahammann.net/book-notes/the-checklist-manifesto-atul-gawande>):

- **READ-DO** — read each step, then do it. Best for complex, infrequent, high-stakes
  work where order matters. → the **monthly full sweep**.
- **DO-CONFIRM** — do the work from memory, then pause and confirm nothing was missed.
  Best for experienced operators on familiar routine work. → the **per-release delta**.

Design rules that transfer directly: 5–9 items, "killer items" only (the critical steps
most often missed, not every step); a defined pause point; fits on one page; under ~60
seconds to run. The stated failure mode is precise — past roughly 60–90 seconds at a
pause point, "the checklist often becomes a distraction… People start shortcutting.
Steps get missed." **A 40-item security checklist is worse than a 7-item one**, because
it will be skimmed and the skimming will not be recorded.

---

## 2. Recording that a recurring check ran, on date X, and found Y

### 2.1 Release checklists: template vs instance

The practice is consistent and explicit across projects:

> The template is copied into a new issue titled `Release checklist: vX.Y.Z` each time a
> release is actually cut; **the copy is filled in, not the template itself**.

— synthesised from <https://usethis.r-lib.org/reference/use_release_issue.html>,
<https://github.com/nebari-dev/nebari/blob/main/.github/ISSUE_TEMPLATE/release-checklist.md>,
<https://github.com/scikit-hep/pyhf/issues/2768>

GitHub documents the automation of exactly this
(<https://docs.github.com/en/actions/tutorials/manage-your-work/schedule-issue-creation>),
and `JasonEtco/create-an-issue` is the common action for template→instance on a cron.

**Failure mode this guards against:** ticking the template destroys it as a template
*and* loses the per-run record, so after two cycles you can answer neither "what are the
steps?" nor "did we do them in August?". The two questions need two documents.

**Note the direction of travel worth copying**: one project explicitly moved its
checklist *out of* GitHub issue-body text and into "a durable, grep-able file", keeping
the per-instance issue for the ticking
(<https://github.com/Performant-Labs/holler/pull/332>). That is 00412's shape already —
definition in-repo, run record in-repo.

**Schedule reliability caveat, verbatim from GitHub:** "The `schedule` event can be
delayed during periods of high loads of GitHub Actions workflow runs", worst at the top
of the hour. A cadence-driven job must therefore treat its trigger as *approximate* and
must not infer "it is not late" from "no trigger fired".

### 2.2 Compliance evidence — the most directly transferable model

A SOC 2 **control** is a recurring obligation, and a run of it is an evidence artefact.
The shape of acceptable evidence is stated as: **dated, attributable artifacts showing
the control operated** — task timestamps, decision records, notification logs, and
after-action reports
(<https://oneuptime.com/blog/post/2026-08-03-what-counts-as-soc-2-evidence/view>,
<https://www.konfirmity.com/blog/soc-2-evidence-requirements>). A *periodic* control is
defined as one that "operates on a schedule selected by management", and the evidence
standard is that it must show **more than that a meeting occurred**
(<https://www.konfirmity.com/blog/soc-2-evidence-review-cadence>).

`dated + attributable + shows it operated` is a good minimum schema for a run record:
**when, who, and what was actually examined.**

The sharpest finding in this whole report comes from PCI DSS. Scanning every three
months is **not** sufficient; an entity must demonstrate

> "'clean' or 'passing' scans performed at least once every three months for the
> previous four quarters"

— <https://www.pcisecuritystandards.org/faq/articles/Frequently_Asked_Question/can-entities-be-pci-dss-compliant-if-they-have-performed-vulnerability-scans-at-least-once-every-three-months-but-do-not-have-four-passing-scans/>

The same FAQ requires "no pattern of *repeated failing scans* from poor remediation
practices", and allows compliance to be shown by "a collection of scan results which
together show that all required scans are being performed" where no single scan covers
everything.

**Three design consequences for 00412, each from that one FAQ:**

1. A run record needs an **outcome**, and "is this job in good standing?" must be a query
   over *outcomes*, not over run *existence*. A run that ran and failed does not
   discharge the obligation.
2. **A pattern across runs is itself a finding.** Three consecutive runs raising the same
   unremediated finding is a different (worse) state than three clean runs, and the
   design should be able to see it. This argues for run records being machine-readable,
   not just prose.
3. **Coverage can be assembled from several partial runs.** A run does not have to cover
   everything to count, as long as the union does — which is precisely the interval
   composition of section 3.1.

PCI also uses exactly 00412's dual trigger — cadence **and** event. Scanning is required
every three months **and** after significant changes to the environment, "since changes
can introduce new vulnerabilities" (secondary sources; see section 6). OWASP SAMM applies
the same idea to threat models: "regularly (e.g. yearly) review the existing threat models
to verify that no new threats are relevant"
(<https://owaspsamm.org/model/design/threat-assessment/stream-b/>).

### 2.3 ADRs — what to borrow and what not to

ADR practice contributes two things and explicitly disclaims a third.

Borrow: **stable IDs, append-only, links between related records, one log per system**
(<https://adr.github.io/>, <https://cloud.google.com/architecture/architecture-decision-records>).
An architecture *decision log* (ADL) is the collection of all ADRs.

Do not borrow the framing: the ADR community is emphatic that ADRs are "not a glorified
change log" and are for decisions that are "hard or expensive to reverse"
(<https://learn.microsoft.com/en-us/azure/well-architected/architect-role/architecture-decision-record>,
<https://www.redhat.com/en/blog/architecture-decision-records>). A job run is a *routine
operational activity*, not a decision — the sources draw that line themselves. ADRs are
prior art for the *log mechanics*, not for the record semantics. For semantics, use the
control-evidence model in 2.2.

---

## 3. Carrying state between runs — the high-water mark problem

This is the design-critical section, as the brief anticipated.

### 3.1 `cargo-vet`: put the interval on the record, not in a pointer

`cargo-vet` records supply-chain audits in `audits.toml` in two forms
(<https://mozilla.github.io/cargo-vet/recording-audits.html>):

> "Specifying a `version` means that the owner has audited that version in its entirety.
> Specifying a `delta` means that the owner has audited the diff between the two
> versions, and determined that the changes preserve the relevant properties."

Deltas are written `delta = "X.Y.Z -> A.B.C"`. Each entry also carries **who** (name and
email) and **criteria** (which property was verified, e.g. `safe-to-deploy`), plus a
`violation` form for recording that a version range is known-bad.

**Why this is the right model and a "last reviewed commit" pointer is not:**

|                                               | Mutable pointer                           | Interval on each record                |
| --------------------------------------------- | ----------------------------------------- | -------------------------------------- |
| Silent skip (pointer jumped too far)          | Undetectable — the pointer looks fine     | Shows as a **gap** between intervals   |
| Silent re-review                              | Undetectable                              | Shows as an overlap; harmless          |
| Two runs racing                               | Last writer wins, one run's coverage lost | Both records survive; union is correct |
| "Was commit `abc` ever covered, and by whom?" | Unanswerable                              | Answerable by interval lookup          |
| Partial coverage (one subsystem)              | Not representable                         | Representable — union must cover       |

The pointer's failure mode is the dangerous one: it produces **no error, no gap, no
signal** — just an assertion of coverage that was never performed. Composition turns the
same mistake into a visible hole.

The Mozilla pool also applies a **size-based escalation rule**: delta audits under
roughly 500 lines of change, full audits otherwise (secondary source; see section 6).
The principle transfers even if the number does not — **when the delta since the last
covered point is too large to review honestly, escalate to a full run rather than
pretend the delta was reviewed.**

### 3.2 Semgrep: the baseline ref must be validated, not assumed

> "Set `SEMGREP_BASELINE_COMMIT` to a commit hash to use that hash as a baseline for the
> scan. This means the scan will only show findings that were **not** already present at
> that hash."

Recommended value is `git merge-base main feature-branch`. It **does not work** when:
you are not in a git directory; there are unstaged changes; or the given baseline hash
does not exist or is unavailable in the CI environment
(<https://docs.semgrep.dev/semgrep-ci/ci-environment-variables>,
<https://docs.semgrep.dev/semgrep-ci/findings-ci>).

**The failure mode is silence-shaped and therefore serious.** An unresolvable baseline
does not produce "error, baseline missing" so much as an empty or wrong delta — a run
that reports nothing and looks clean. A run must therefore *resolve and record* its
baseline ref, and on failure escalate to a full run and say so in the record, never
emit an empty delta.

This project is structurally well placed here: `R-GIT-MERGE-SQUASH` and
`R-GH-PR-MERGE-SQUASH` already forbid squash merges on the stated grounds that they sever
ancestry. A stored baseline ref stays resolvable precisely because of that existing rule —
worth noting in the plan, because relaxing that rule later would break Job coverage
retroactively and non-obviously.

Semgrep documents a second subtlety worth knowing: findings introduced in a diff-aware
scan "are not automatically triaged at scan time, even if there are other instances of
that finding on branches that have been triaged" — i.e. **triage state does not
automatically travel with the delta**, so re-surfacing of already-accepted findings is a
predictable annoyance that needs its own answer.

### 3.3 CodeQL: what a delta run is structurally unable to see

CodeQL's overlay analysis carries an **overlay-base database** plus the **git object IDs
of all tracked files** between runs; the diff is computed by comparing OIDs, and the diff
ranges are expressed against the *new* file's line numbers
(<https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/scan-from-the-command-line/incremental-analysis>).

The limitations are the interesting part:

- **"You will only see an alert in a pull request if all the lines of code identified by
  the alert exist in the pull request diff."** A data-flow finding whose source is in
  unchanged code and whose sink is in changed code is *invisible* to the delta run.
- Queries tagged **`exclude-from-incremental`** must be excluded from diff-informed
  analysis — some checks simply cannot be run incrementally.
- A full analysis is required when "no compatible overlay-base database is available in
  the cache (for example, on the first run or after a CodeQL CLI version upgrade)", and
  when patch information is truncated or unavailable.
- Only `build-mode: none` is supported; git ≥ 2.38.0; all files of interest must be
  tracked (not gitignored).

**This is the argument that makes 00412's "delta per release plus full at least monthly"
correct rather than merely prudent.** The periodic full run is not redundancy — it is the
*compensating control* for a blindness the delta run has by construction. Three rules
follow:

1. **Classify every check in the Job as delta-able or full-only.** CodeQL's
   `exclude-from-incremental` tag is the precedent. Anything whole-program — data flow,
   dependency graph, "is there an unreachable handler anywhere" — is full-only.
2. **A delta run record must list the full-only checks it did not run**, so nobody reads
   it as coverage it does not have.
3. **Enumerate the conditions that force escalation to a full run**: first run ever, the
   tool/ruleset/criteria changed, the baseline ref will not resolve, the delta exceeds
   the size threshold, or a full run is overdue. Both CodeQL ("after a CodeQL CLI version
   upgrade") and `cargo-vet` (criteria are part of the audit record) treat *the analyser
   itself changing* as invalidating prior coverage. That is easy to forget and expensive
   to get wrong — **the coverage record is only valid for the criteria it was recorded
   under.**

### 3.4 Scorecard, Dependabot, Renovate — weaker prior art

OpenSSF Scorecard runs a **weekly** scan of public repositories to track ecosystem
security health and publishes results to a public BigQuery dataset; individual repos
typically run the action weekly plus on pushes to the default branch and on
branch-protection changes, uploading SARIF to the Security tab
(<https://github.com/ossf/scorecard>, <https://github.com/ossf/scorecard-action>).
Note the shape: **cadence trigger plus event triggers**, same as PCI, same as 00412.
Also note the failure mode found in the wild — a weekly scheduled Scorecard scan with no
failure alert means "the score can silently go stale"
(<https://github.com/kubestellar/docs/issues/6724>). That is the section 4.4 problem
arriving in practice.

Renovate's state model is the weakest match and should not be over-read. State lives in
the repository itself — the Dependency Dashboard issue, branches and PRs — rather than an
external database (<https://docs.renovatebot.com/key-concepts/dashboard/>). The useful
transferable idea is only the general one: **state that lives in the repo is reviewable,
diffable and survives tooling changes.** I could not find documentation of a high-water
mark in Renovate comparable to a baseline commit, and a known issue shows the model's
fragility — deleting the dashboard issue "leaves Renovate in a broken state"
(<https://github.com/renovatebot/renovate/issues/19563>). Treat as a cautionary note:
**if the state lives in one deletable artefact, deleting it is a silent regression.**
Interval composition across many append-only records (3.1) does not have this problem.

---

## 4. Scheduling and idempotency

Each mechanism below is listed with the specific failure mode it guards against.

### 4.1 systemd timers — catch-up is one activation, not a replay

> "`Persistent=` — Takes a boolean argument. If true, the time when the service unit was
> last triggered is stored on disk."
>
> "When the timer is activated, the service unit is triggered immediately if it would
> have been triggered at least once during the time when the timer was inactive."

— <https://man7.org/linux/man-pages/man5/systemd.timer.5.html>

Also available: `AccuracySec=` (defaults to 1min) and `RandomizedDelaySec=` (delay by a
random amount in `[0, value]`) — the latter guards against **many jobs firing
simultaneously on the same tick**, a thundering-herd concern that applies to any
"everything runs at month start" cadence.

**Guards against:** a machine that was off at the scheduled moment never running the job
at all. **Trade-off it accepts:** three missed months produce *one* run, not three — you
lose per-interval granularity in exchange for not stampeding. For an audit-style job
this is the *right* trade, but only if the single catch-up run **widens its interval** to
cover the whole gap. Otherwise you get one run that covers one month and a two-month hole
that nothing records.

### 4.2 Airflow — catch-up is off by default, and why

> "If you set `catchup=True` in the Dag, the scheduler will kick off a Dag Run for any
> data interval that has not been run since the last data interval."
>
> "By default, Dag runs that have not been run since the last data interval are not
> created by the scheduler upon activation of a Dag (Airflow config
> `scheduler.catchup_by_default=False`)."

— <https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dag-run.html>

The **logical date** "denotes the start of the data interval, not when the Dag is
actually executed" — a daily run for the 24th executes at the *end* of that interval, on
the 25th. Airflow separates this from **backfill**, which explicitly names a start and
end and may cover periods before the DAG's `start_date`, bounded by `max_active_runs`
(<https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/backfill.html>).

**Guards against:** the "catchup storm" — enabling a DAG with a distant `start_date` and
immediately spawning months of runs
(<https://thecodeforge.io/devops/airflow-backfill-catchup/>).

**Two things to steal.** First, **a run is identified by the interval it covers, not by
when it was executed** — the same insight as 3.1, arrived at independently, and the
reason Airflow can tell "never ran" from "ran late". Second, Airflow's backfill
reprocessing modes are a ready-made vocabulary for the "what do we re-run?" question:
**Missing Runs** (only intervals with no run), **Missing and Errored Runs** (also re-run
previously failed ones), **All Runs** (clear and re-run everything in range)
(<https://www.astronomer.io/docs/learn/rerunning-dags>). That distinction is only
expressible because *errored* and *missing* are stored as different states — exactly the
distinction the brief asked about.

### 4.3 Kubernetes CronJob — honest about non-determinism

`concurrencyPolicy` (<https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/>):

- **`Allow`** (default) — concurrent runs permitted. A slow job overlaps itself.
- **`Forbid`** — "if it is time for a new Job run and the previous Job run hasn't finished
  yet, the CronJob skips the new Job run."
- **`Replace`** — the running job is replaced by the new one.

`startingDeadlineSeconds` "defines a deadline (in whole seconds) for starting the Job, if
that Job misses its scheduled time for any reason… After missing the deadline, the CronJob
skips that instance of the Job (future occurrences are still scheduled)." It also bounds
the missed-run accounting window: the controller counts missed schedules from
`startingDeadlineSeconds` ago rather than from the last scheduled time.

The failure that this bounding exists to prevent is worth quoting because it is the worst
possible behaviour for a compliance-shaped job:

> "Cannot determine if job needs to be started. Too many missed start time (> 100).
> Set or decrease `.spec.startingDeadlineSeconds` or check clock skew."

Past 100 missed schedules with `startingDeadlineSeconds` unset, **the controller stops
scheduling entirely** — the recurring job silently stops recurring, permanently, and the
only signal is a log line. **Guards against:** unbounded catch-up computation.
**Introduces:** a silent permanent stall. Any 00412 design that has a "too far behind to
reason about" branch must make that branch *loud*, not quiet.

And the caveat the Kubernetes docs state outright:

> "A cron job creates a job object *about* once per execution time of its schedule…
> In certain circumstances two jobs might be created, or no job might be created."

with the conclusion that "jobs should be **idempotent**". A schedule is not a guarantee
in either direction. A Job in 00412 must tolerate being run twice for the same interval
(the second should be a recorded no-op, not a duplicate record) and must tolerate not
being run at all (detected by 4.4).

### 4.4 Detecting a run that never happened

> "Your monitoring stack doesn't know if a job didn't run. It only sees what you
> explicitly tell it about. This is the dead-man-switch problem. Not 'something went
> wrong' — but 'something didn't happen at all'."

— <https://blogs.snehangshu.dev/dead-mans-switch-style-application-monitoring-with-healthchecksio>

Healthchecks.io's model: each check has a **period** and a **grace time**. A ping is
expected at the scheduled time; no alert fires yet. If no ping arrives by the grace
deadline, the job is declared failed
(<https://healthchecks.io/docs/monitoring_cron_jobs/>).

**The two-parameter design is the bit to steal.** Period alone produces an alert every
time a job runs slightly late; period + grace separates "late" from "missing", which for
a monthly cadence with fuzzy release timing is essential. **Guards against:** the single
most common failure of recurring work — it quietly stops happening, and because nothing
is failing, nothing complains.

For 00412 this is an *external observer* requirement: no amount of run-record design
detects the absence of a run. Something must read the records, compare to the cadence,
and speak up. This project already has that shape — `plan_qa_sweep` and `docs_qa_sweep`
report at SessionStart, `persistent_cron_assertor` re-establishes declared crons — so the
natural implementation is a SessionStart sweep that reports overdue Jobs, with the
grace-period concept preventing it from nagging on day 31 of a monthly cadence.

### 4.5 Run keys and leases (double-run prevention)

The distributed-systems answer, which translates surprisingly cleanly to a file-based
design (<https://dev.to/techamit95ch/idempotency-as-a-product-feature-run-keys-leases-and-scheduling-3hmc>,
<https://oneuptime.com/blog/post/2026-09-14-cron-stable-business-key-side-effects/view>):

- **True exactly-once is impossible; aim for at-least-once delivery plus idempotent
  execution.**
- A **run key** uniquely identifies the *intent* of an action, not the action.
- A **lease** is a time-bound lock on that run key, with a TTL so a crashed worker does
  not deadlock it forever.
- A worker **claims** a run with a conditional write (compare-and-set `pending`→`running`);
  a failed claim means someone else has it.
- "A lock can reduce overlap, but a durable uniqueness rule must survive the lock, process,
  and scheduler."

**The document-native translation:** the run key is `<job>/<interval>`, the run record's
*filename* encodes it, and creating that file **is** the claim. Two agents running the
same interval concurrently then produce a git-level collision rather than a silent
double-run — the durable uniqueness rule survives the process, which is exactly the
property the last bullet asks for. This is a real advantage of keeping run records in git
rather than in a single mutable state file.

### 4.6 The run-outcome vocabulary

Pulling sections 2.2, 4.2 and 4.3 together, the states a run record must be able to
express — and which must never be conflated:

| State         | Meaning                             | Source of the requirement                          |
| ------------- | ----------------------------------- | -------------------------------------------------- |
| *(no record)* | Never ran                           | Airflow "Missing Runs"; dead-man's-switch          |
| `clean`       | Ran, nothing found                  | PCI "passing scan"                                 |
| `findings`    | Ran, found things (linked)          | PCI scan-remediate-rescan                          |
| `failed`      | Attempted, could not complete       | Airflow "Errored Runs" ≠ missing                   |
| `skipped`     | Deliberately not run, with a reason | k8s `Forbid`/deadline skip is recorded, not silent |

`clean` and *no record* being different is the whole point, and the brief was right to
call it out: a job that has never run and a job that ran and found nothing look identical
in every design that only records findings.

---

## 5. Naming

### 5.1 What the terms actually mean in the wild

| Term                       | Established meaning                                                                                                                                                | Fit for 00412                                                                             |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| **Runbook**                | ITIL/SRE: tactical, narrow, one operational outcome; conventionally *triggered* (by an alert or a task), not scheduled; its run is recorded in the incident ticket | Good for the *document*, wrong connotation (reactive) and carries no run-record tradition |
| **Playbook**               | Google SRE: alert-response instructions                                                                                                                            | Too tied to alerting                                                                      |
| **SOP / work instruction** | ITIL tiering: SOP broad, work instruction detailed                                                                                                                 | Accurate but heavy, bureaucratic register                                                 |
| **Control**                | Compliance: a recurring obligation that must produce evidence of execution                                                                                         | **Semantically the closest match**, but audit-jargon to a developer audience              |
| **Job**                    | Compute: a unit of scheduled execution (GitHub Actions `jobs:`, Airflow, k8s CronJob)                                                                              | Pairs idiomatically with "run"; collides locally — see below                              |
| **Routine**                | Plain English: something done repeatedly as a matter of course                                                                                                     | No compute collision; pairs with "run"; parallel grammar with "Plan"                      |
| **Ritual**                 | Team-practice slang (standups, retros); no documentation tradition                                                                                                 | No                                                                                        |
| **Cadence**                | A *property* of a schedule, not a thing — sources use it as "review cadence"                                                                                       | No; naming a thing after its schedule is a category error                                 |

Sources: <https://playcode.io/blog/runbook-vs-playbook>,
<https://en.wikipedia.org/wiki/Standard_operating_procedure>,
<https://wiki.en.it-processmaps.com/index.php/IT_Operations_Control>,
plus the SAMM/SOC 2/PCI sources above for "control". The runbook literature itself says
terminology varies and advises defining the hierarchy locally.

### 5.2 The local collision is the deciding fact

This is not an abstract preference. Checked in this repository:

- `.github/workflows/` already uses `jobs:` in the GitHub Actions sense (8 occurrences in
  one workflow file).
- The daemon already owns a scheduling vocabulary: `src/claude_code_hooks_daemon/utils/cron_cadence.py`,
  `persistent_cron_assertor`, `failsafe-cron`, the `issue-sdlc` hourly cron,
  `background_process_tracker`.
- 00412's own README entry says the concept is "driven by the persistent-cron system".

So the two senses will not merely coexist in the repo — they will appear **in the same
sentence, constantly**: "the cron job that runs the job", "the Job's cron job failed".
Prose that has to disambiguate its own central noun every time it is used is a tax paid
on every future document, and the ambiguity lands hardest in exactly the place clarity
matters most, the CLAUDE.md guidance blocks that instruct future agents.

### 5.3 Recommendation

**Use "Routine" for the definition, "Run" for the record.** `CLAUDE/Routine/NNNNN-name/`
sits beside `CLAUDE/Plan/NNNNN-name/` with parallel grammar and an honest semantic
contrast: *a Plan is finished; a Routine recurs*. "Routine" has no compute collision in
this codebase, needs no gloss for a developer reader, and still pairs naturally with
"Run" ("a Routine has Runs", "this Routine's last Run was clean").

Second choice is **"Job"**, and it is defensible — its merit is the idiomatic
Job→Run pairing that Airflow, k8s and GitHub Actions have already taught everyone. If the
owner prefers it, the mitigation is to ban bare "job" for CI jobs in prose (always
"workflow job"), which is a discipline that will erode.

**"Control"** is the most *accurate* word — it is precisely what this is — but it reads as
compliance theatre in a developer-facing tool, and the compliance model's value transfers
through the *design* (section 2.2) whether or not the word does.

Not recommended: Playbook, Ritual, Cadence.

The half of the vocabulary that matters more and is uncontroversial either way is **Run**.
Whatever the parent noun, the per-execution record should be called a Run, its records
should live in a `RUNS/` directory, and a Run should be named by the **interval it
covers**, not by the date it was executed (section 4.2). Worth settling the parent noun
now: it becomes a directory name, a set of QA rule IDs and a handler name, and is
awkward to change afterwards.

---

## 6. What could not be verified

- **`/var/lib/systemd/timers` as the stamp-file location.** Reported by multiple secondary
  sources; the man page at man7.org says only "stored on disk" without naming a path. The
  *behaviour* is verified verbatim, only the path is second-hand.
- **PCI DSS "after significant change" scanning requirement** (Req. 11.3.1.3 / 11.3.2.1).
  Consistently stated by several secondary sources
  (<https://www.breachlock.com/resources/blog/penetration-testing-and-vulnerability-scanning-for-pci-dss/>,
  <https://www.securecodinghub.com/blog/pci-dss-vulnerability-scanning-asv-and-internal-scans>)
  but the official PCI FAQ I read covers only the four-passing-scans question. The
  four-passing-scans requirement itself **is** verified against the PCI SSC page.
- **The `cargo-vet` 500-LOC delta/full threshold.** Attributed to "the convention in the
  Mozilla pool" by <https://safeguard.sh/resources/blog/rust-supply-chain-cargo-vet-expansion-2025>.
  The official cargo-vet docs I read state no numeric threshold. Treat the number as
  illustrative; the *principle* (escalate to full when the delta is too big to review
  honestly) is sound independent of the figure.
- **"Airbnb runs quarterly runbook-testing exercises against staging."** Asserted by a
  single vendor blog with no primary citation. Do not cite this; the underlying practice
  (scheduled execution against a safe environment) is well attested elsewhere.
- **Whether g3doc freshness metadata is automatically enforced inside Google** (e.g. a bot
  that nags a stale owner). The syntax and intent are verified from the open-sourced
  WebRTC g3doc guide; the enforcement mechanism is not documented publicly.
- **GitHub Actions disabling scheduled workflows after 60 days of repository inactivity.**
  Widely repeated and believed current, but not present on the GitHub page I fetched.
  Verify before relying on it. (The schedule *delay* warning **is** verified.)
- **Renovate high-water-mark state.** I found no documentation of a baseline-commit
  equivalent. Absence of evidence — I would not assert Renovate lacks one, only that the
  accessible docs do not describe one.
- **Semgrep's two-scan implementation** ("Semgrep performs two scans: one on the PR and
  another on the existing codebase before the PR"). From a search-result snippet; the
  Semgrep docs pages I fetched directly did not contain that sentence. The
  `SEMGREP_BASELINE_COMMIT` semantics and limitations **are** verified verbatim.

## Sources

Primary, fetched and quoted directly:

- <https://sre.google/workbook/on-call/>
- <https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/>
- <https://man7.org/linux/man-pages/man5/systemd.timer.5.html>
- <https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dag-run.html>
- <https://mozilla.github.io/cargo-vet/recording-audits.html>
- <https://docs.semgrep.dev/semgrep-ci/ci-environment-variables>
- <https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/scan-from-the-command-line/incremental-analysis>
- <https://docs.github.com/en/actions/tutorials/manage-your-work/schedule-issue-creation>
- <https://webrtc.googlesource.com/src/+/main/g3doc/how_to_write_documentation.md>
- <https://www.pcisecuritystandards.org/faq/articles/Frequently_Asked_Question/can-entities-be-pci-dss-compliant-if-they-have-performed-vulnerability-scans-at-least-once-every-three-months-but-do-not-have-four-passing-scans/>

Secondary, used for corroboration or context:

- <https://docs.firehydrant.com/docs/runbook-best-practices>
- <https://www.pagerduty.com/resources/automation/learn/what-is-a-runbook/>
- <https://www.tines.com/blog/what-are-runbooks-and-how-to-automate-them/>
- <https://github.com/kjkuan/Runbook.md>
- <https://oneuptime.com/blog/post/2026-09-02-keep-disaster-recovery-runbooks-current/view>
- <https://oneuptime.com/blog/post/2026-09-02-disaster-recovery-testing-cadence/view>
- <https://oneuptime.com/blog/post/2026-08-03-what-counts-as-soc-2-evidence/view>
- <https://www.konfirmity.com/blog/soc-2-evidence-requirements>
- <https://www.konfirmity.com/blog/soc-2-evidence-review-cadence>
- <https://owaspsamm.org/model/design/threat-assessment/stream-b/>
- <https://adr.github.io/>
- <https://cloud.google.com/architecture/architecture-decision-records>
- <https://learn.microsoft.com/en-us/azure/well-architected/architect-role/architecture-decision-record>
- <https://usethis.r-lib.org/reference/use_release_issue.html>
- <https://github.com/nebari-dev/nebari/blob/main/.github/ISSUE_TEMPLATE/release-checklist.md>
- <https://github.com/Performant-Labs/holler/pull/332>
- <https://github.com/ossf/scorecard> and <https://github.com/ossf/scorecard-action>
- <https://github.com/kubestellar/docs/issues/6724>
- <https://docs.renovatebot.com/key-concepts/dashboard/> and <https://github.com/renovatebot/renovate/issues/19563>
- <https://healthchecks.io/docs/monitoring_cron_jobs/>
- <https://blogs.snehangshu.dev/dead-mans-switch-style-application-monitoring-with-healthchecksio>
- <https://dev.to/techamit95ch/idempotency-as-a-product-feature-run-keys-leases-and-scheduling-3hmc>
- <https://oneuptime.com/blog/post/2026-09-14-cron-stable-business-key-side-effects/view>
- <https://www.astronomer.io/docs/learn/rerunning-dags>
- <https://thecodeforge.io/devops/airflow-backfill-catchup/>
- <https://sketchplanations.com/read-do-do-confirm-checklists>
- <https://grahammann.net/book-notes/the-checklist-manifesto-atul-gawande>
- <https://en.wikipedia.org/wiki/Standard_operating_procedure>
- <https://wiki.en.it-processmaps.com/index.php/IT_Operations_Control>
- <https://playcode.io/blog/runbook-vs-playbook>
