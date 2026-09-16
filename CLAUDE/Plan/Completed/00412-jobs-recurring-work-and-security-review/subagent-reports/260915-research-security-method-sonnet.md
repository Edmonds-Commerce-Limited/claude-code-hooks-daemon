# Research: Defence Before Fix, and recurring security review as a process

Research report for Plan 00412. Two parts, as dispatched. Part 1 establishes what
"defence-before-fix.github.io" actually is. Part 2 surveys how serious open-source projects run
recurring security review.

All claims below carry a URL. A closing section lists what could not be verified.

---

## Part 1: Defence Before Fix

### Verdict: the site exists, and it is a formal specification

`https://defence-before-fix.github.io` **resolves and is real**. So does the US-spelling
`https://defense-before-fix.github.io`, which is a deliberate signpost/redirect site carrying no
original content of its own. Both are backed by GitHub organisations:

- <https://defence-before-fix.github.io> — canonical site
- <https://defense-before-fix.github.io> — US spelling signpost
- <https://github.com/Defence-Before-Fix/defence-before-fix.github.io> — source repository
- <https://github.com/Defense-Before-Fix/defense-before-fix.github.io> — US spelling repository

This is not a blog post or a slogan. It is a **normative specification set** using RFC 2119
MUST/SHOULD/MAY language, with three versioned documents, a conformance model, a provenance
record, a changelog, an acceptance process, and two reference toolchain implementations.

**Authorship:** Joseph Edmonds of Edmonds Commerce (<https://ltscommerce.dev>,
<https://edmondscommerce.co.uk>). Coined and first published 22 February 2026 in the article
<https://ltscommerce.dev/articles/defence-before-fix-static-analysis>. Licensed CC BY 4.0.

> **Note for the plan owner.** This repository's git user is `joseph`, and the specification's
> author is Joseph Edmonds of Edmonds Commerce. If this project is Edmonds Commerce's, then the
> user is asking us to adopt a methodology they themselves authored, which changes the framing of
> "engage with this" from *evaluate an external standard* to *conform this project to our own
> published standard*. Worth confirming rather than assuming.

### It is already vendored in this repository

The daemon's `remote_docs_routing` handler intercepted my fetch of the spec and pointed at local
copies. The corpus already holds:

| Path                                                                                       | Document                                 |
| ------------------------------------------------------------------------------------------ | ---------------------------------------- |
| `/workspace/remote-docs/defence-before-fix.github.io/SPEC.md`                              | Method specification 1.0.1 (1,207 lines) |
| `/workspace/remote-docs/defence-before-fix.github.io/DETECTOR-SPEC.md`                     | Detector specification 1.0.0             |
| `/workspace/remote-docs/defence-before-fix.github.io/defence-before-fix-project-prompt.md` | Short agent-facing form of the method    |
| `/workspace/remote-docs/defence-before-fix.github.io/index.md`                             | Site index                               |

Captured 2026-09-10, fresh until 2026-12-09. **The toolchain specification (`TOOLING-SPEC.md`) is
NOT vendored** — I fetched it live for this report. If the plan proceeds, capture it:

```
bin/hooks-daemon remote-docs add https://defence-before-fix.github.io/TOOLING-SPEC.html
```

Caveat: every vendored file carries `licence: unreviewed` in its frontmatter. The site itself
states CC BY 4.0 in its footer and in the spec's own closing line, so quoting with attribution is
fine, but the frontmatter should be corrected so the next reader does not have to re-derive that.

### The core definition, verbatim

From the method specification's opening (SPEC.md:36-45):

> "Defence Before Fix (DBF) is a phase that runs before a Defect is fixed. Rather than dropping
> straight into remediating the specific Instance in front of you, you first treat that Instance
> as evidence of a Class, and you build the automated Defence that detects every occurrence of
> that Class across the whole codebase. The Defence is only trusted once it has been seen to
> fire."
>
> "The Defect is what makes this possible. It is a real, confirmed, impactful example of a harmful
> pattern, which is precisely the raw material a good custom Rule needs and which speculative
> Rules never have. Every Defect is therefore an opportunity to extend the codebase's permanent
> defensive Coverage, and that opportunity exists only in the window before the fix."

And the explicit disambiguation the user's phrasing might otherwise invite (SPEC.md:51-52):

> "Not to be confused with Defence in depth, which is a security term meaning something else
> entirely. The Defence here comes before the fix in time, not in layers."

The primer states the ordering rationale bluntly
(<https://defence-before-fix.github.io/PRIMER.html>): defensive patterns must be established
before fixes are applied, "since the fix destroys the evidence needed for rule construction."

### Key terminology (all normative, SPEC.md §1)

The spec is precise about vocabulary, and the precision is load-bearing. Abbreviated:

| Term             | Definition                                                                                                                                                          |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Defect**       | "Any observed problem worth acting on: a bug, a code review finding, a performance observation, an incident, an inconsistency." Explicitly *not* security-specific. |
| **Class**        | "The pattern, style, idiom or configuration that permitted the Defect, expressed generally enough that other occurrences of it are also Defects or latent Defects." |
| **Instance**     | One occurrence of a Class.                                                                                                                                          |
| **Hazard**       | "The harm a Class causes, which is not necessarily a failure. It may be a failure, but it may equally be error hiding, or something merely sloppy."                 |
| **Detector**     | "A tool that reads code without executing it and reports occurrences of a pattern. A Detector is not a Runner."                                                     |
| **Runner**       | A tool that executes code (test runner, compiler, benchmark).                                                                                                       |
| **Rule**         | One pattern definition within a Detector.                                                                                                                           |
| **Defence**      | "A Blocking Rule together with the supporting documentation… A Rule without its documentation is not a Defence, and neither is a Rule that only warns."             |
| **Coverage**     | "The accumulated set of Defences a project has built."                                                                                                              |
| **Blocking**     | Firing prevents a change being accepted. Non-blocking is a Warning, and "a Rule that only warns is not a Defence."                                                  |
| **Suppression**  | Any means of preventing a Rule reporting an Instance that carries the Hazard — ignore comment, ignore entry, Baseline, or a Narrowing that excludes it.             |
| **Narrowing**    | Reducing scope so the Rule stops reporting code that does *not* carry the Hazard. Legitimate.                                                                       |
| **Exception**    | "A recorded Owner decision… The only legitimate form of Suppression."                                                                                               |
| **Practitioner** | Whoever does the work, human or Agent. Decides *how* the Defence is built.                                                                                          |
| **Owner**        | Always a human. Holds authority over Exceptions and Calibrations.                                                                                                   |

### The six clauses of the method (SPEC.md §3)

The spec's own summary table, restated:

| Clause                       | The Practitioner MUST                                                                | Goes to the Owner                                                                            |
| ---------------------------- | ------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| **3.1** Attribute to a class | Name the Class the Defect belongs to, bounded both ways, after an independent search | Whether the next wider Rule is built; whether the Rule stays narrower than the search showed |
| **3.2** Build the net        | Express the Class as a Rule in a **Detector**, never a test                          | Whether a defensible Class is left undefended                                                |
| **3.3** Prove the net        | Make the Rule fire, on the Instance or a Fixture, **in a commit of its own**         | Any exclusion whose justifying sentence cannot be written                                    |
| **3.4** Sweep and fix        | Sweep the whole codebase, record the count, then fix **every** Instance              | Any Instance left unfixed; any Baseline                                                      |
| **3.5** Enforce              | Make the Rule permanent and **Blocking** in the project's own checks                 | Removing/disabling the Rule; any Suppression                                                 |
| **3.6** Message and docs     | Terse Message with a stable Identifier resolving to versioned documentation          | Nothing                                                                                      |

The clauses that matter most in practice, with their sharp edges:

**3.1 — the two bounds.** Lower bound: "If the Rule catches only the originating Instance, the
Class is probably drawn too narrowly and MUST be widened… A Rule that matches exactly one thing is
an Instance wearing a Rule's clothes." Upper bound: "If the Rule matches code that does not carry
the Hazard, the Class is drawn too broadly and MUST be narrowed. False positives destroy a
Defence's credibility faster than a missing Rule does. One report on code that does not carry the
Hazard is enough; there is no tolerated rate."

The **independent search** requirement is the clause's teeth. At least two *independent*
techniques (they are independent "when they would miss different things"), chosen and run *before*
the Rule is run against the codebase, stopping on saturation rather than effort: "the search is
complete when the last technique added found nothing the earlier ones had missed." Critically,
"The Rule itself is never one of the techniques, because the search exists to check the Rule." And
where the search and the Rule disagree, **the search wins**: "the Rule was drawn too narrowly and
MUST be widened until it catches them."

**3.2 — a test is not a Detector.** "A test MUST NOT serve as the Detector. A test proves that one
input produces one wrong output; a Rule finds the pattern wherever it occurs, including in code
nobody thought to test." Where no extensible detector exists, a bespoke one is permitted as a last
resort; where even that is impractical, that is a recorded **Toolchain gap**, not the defect being
out of scope — "the first is a decision somebody can revisit and the second quietly disappears."

**3.3 — the red commit.** "The proof MUST survive as a commit of its own. The Defence is committed
with the originating Instance still present, and the fix is committed after it." A merge that
squashes the two destroys the proof, and the spec says so explicitly: a project whose merge policy
flattens them "MUST keep the Defence commit reachable by another recorded reference, a tag or the
retained branch, or MUST NOT claim the remediation Conforms."

Also 3.3: "A green run proves nothing unless the Rule was loaded." Before treating a clean run as
evidence, confirm the Rule was actually active in it — a toolchain analysing its own source with a
config that omits its own bundled rules "reports clean on every one of them, and both the
Practitioner and a reviewer have taken that for a pass."

**3.4 — fix every instance, and the Baseline verdict.** "There is no count at which a Practitioner
stops fixing." A Baseline MAY be adopted where fixing every Instance is "genuinely unfeasible, and
the scale at which that becomes true is tremendous." The AI-era argument is stated directly:

> "Under AI-assisted development a Baseline is almost never the right answer. The historical case
> for baselining was the cost of human hours, and that cost has largely collapsed… This
> specification stops short of forbidding Baselines outright, and only just."

The published worked example: "the reported Defect was one of twenty-three… A project that knows
about twenty-three Instances and fixes one has produced a documented list of Defects it has chosen
to keep."

**3.5 — block, do not warn.** "the purpose is that the mistakes of the past become structurally
impossible to repeat, and a Warning is not structure. A Warning is a suggestion, and suggestions
decay under deadline pressure, which is the condition under which the original Defect was
written." Enforcement must be demonstrated **through the project's own entry point**, not by
invoking the detector directly: "A Practitioner who bypasses it has proven the Rule and not the
Defence."

**3.6 — message versus documentation.** Terse message carrying a stable Identifier; documentation
stating three things — what the Rule is about, why it exists, and how to fix a violation
correctly. Rule and documentation "are one artefact and MUST be versioned as one." The closing
line of the clause is the thesis: *"The best custom Rules are opinionated documentation encoded as
automation."*

### The authority model (SPEC.md §4) — the part built for agents

This section exists because two failure modes were observed in cold readings of an earlier draft:
an agent that "either stalls at the first judgement call it cannot authorise or takes the decision
unilaterally, and the second failure is much harder to notice than the first."

**The Practitioner decides alone:** the Class and its bounds; which Detector and how to express
the Rule; how to prove it and what Fixture to use; what the correct behaviour is at each Instance;
the wording of the Message and docs.

**Must go to the Owner:** adopting a Baseline; suppressing an Instance or removing/disabling a
Rule; accepting a known Instance as unfixed; deciding a Class will not be defended at all;
leaving the named next-wider Rule unbuilt; leaving a Rule narrower than the search showed.

The dividing line, stated cleanly: **"the Practitioner decides how the Defence is built and the
Owner decides what the codebase is permitted to keep."**

Two rules that matter for agent operation:

- **Doubt routes upwards.** "Where the Practitioner is not confident that code they are about to
  exclude is free of the Hazard, that exclusion is a Suppression and belongs to the Owner,
  whatever it is called… Narrowing is the Practitioner's decision only whilst they are sure."
- **Count never triggers escalation.** "A large Sweep is work, not a blocked decision… Five
  hundred Instances with no Exception needed is five hundred Instances to fix."

And the standing answer on exceptions: "Suppressions, Baselines and every other means of evading a
Defence are not techniques with a threshold governing their use; they are Exceptions to the
method, and the standing answer is no… Nothing an Agent concludes on its own creates one."

Blocked work does not stall everything: "A decision awaiting the Owner MUST NOT stall the rest of
the work," and the Rule is left **unmerged rather than merged in a weakened form**.

### Check ordering (SPEC.md §5)

Enforcing, not advisory:

1. Detectors — type checking, linting, custom Rules
2. Automated tests — unit, integration, functional
3. Build verification — services start, dependencies resolve
4. Human acceptance testing

"Detectors MUST run first, and a failure at that level MUST stop the levels below it from being
treated as meaningful." Rationale: "a Detector is preventive and a test is diagnostic. A Detector
reads every file, every time it runs, so it cannot miss a file merely because nobody thought to
write a test for it."

### Relationship to TDD (SPEC.md §6)

Not a replacement — a different level. The spec's own table:

| Concern            | TDD                                | Defence Before Fix                           |
| ------------------ | ---------------------------------- | -------------------------------------------- |
| Operates on        | The specific Defect                | The Class the Defect belongs to              |
| Artefact           | A test                             | A Rule in a Detector                         |
| Proves correctness | For one behaviour, by executing it | For a pattern, by reading the code           |
| Answers            | "Is this bug fixed?"               | "Can this kind of bug still exist anywhere?" |

"The name records the ordering. The Defence comes first, because once the fix has landed the
evidence is gone and the opportunity closes with it."

### Conformance (SPEC.md §7) — four separately-graded levels

A **remediation** conforms if all six clauses were followed for that Defect. A **Defence** conforms
on clauses 3.1, 3.2, 3.3, 3.5, 3.6 (Sweep excluded — a Defence can conform while the Sweep is
incomplete). A **Toolchain** conforms if it permits bespoke rules, supports the §5 ordering, and
satisfies clauses 8.1–8.5 and 8.7. A **project** conforms if its Defences, Remediation docs and
recorded decisions are discoverable.

"Partial Conformance MUST NOT be described as Conformance."

The verification standard is worth stealing on its own: **"A verdict on a remediation or a Defence
MUST rest on reproduction, not on the report"** — the reviewer reruns the Defence red at the
introducing commit and green at the final commit, through the project's own entry point. "A report
that reads as Conforming has not been shown to be."

### Section 8 — operating under AI-assisted development

This is the section most directly relevant to this repository. The argument:

> "For an Agent, the failure Message is the entire remediation loop. It is consumed as instruction,
> in the same turn, every time, with no fatigue and no seniority gradient. A Message that resolves
> to documentation explaining the correct approach does not simply block the Agent, it redirects
> it, and it does so identically on the thousandth occurrence as on the first."
>
> "That reframes the usual complaint about AI-written code. The difficulty was never that Agents
> make mistakes, since people do too. The difficulty is that nobody built the channel to correct
> them at the level of the Class rather than the Instance."

The clauses:

| Clause | Requirement                                                                                                                          |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| 8.1    | The Practitioner MUST be able to run the Defence themselves                                                                          |
| 8.2    | The result MUST reach them in the output they are already reading — not only a dashboard                                             |
| 8.3    | The Identifier MUST resolve without a human — a command, a file, or a URL                                                            |
| 8.4    | Documentation MUST state the correct construction, not only the prohibition                                                          |
| 8.5    | A project's Defences MUST be enumerable **without triggering them first**                                                            |
| 8.6    | A project SHOULD publish a summary of its Defences suitable for an agent's context (SHOULD, deliberately not bearing on Conformance) |
| 8.7    | Recorded project decisions MUST be discoverable by the same means                                                                    |

8.5's rationale: "an Agent arriving at a codebase has no colleague to ask and no memory of last
time. Without this, a project's standards can only be learned by violating them one at a time."

8.6's rationale: "everything else in this method operates after the mistake. This operates before
it… it costs one table."

### The companion specifications

**Detector specification 1.0.0** (<https://defence-before-fix.github.io/DETECTOR-SPEC.html>) —
addressed to detector *maintainers*. Governing principle: "where the method specification requires
a Practitioner to do something with a Rule, a Conforming Detector MUST make that possible without
the project building the mechanism first. A Detector that leaves the project to construct the
means has moved the obligation rather than met it." Its §3 table splits each mechanism into what
the Detector provides versus what the Rule author supplies (bespoke rules, a Harness for the red
proof, local invocation, Identifier carriage and printing, documentation resolution, a detectable
or disableable inline-suppression route).

**Toolchain specification 0.2.0** (<https://defence-before-fix.github.io/TOOLING-SPEC.html>) —
addressed to toolchain authors. Clauses verified live:

- **4.1** every detector routed MUST conform to the detector specification
- **4.2** MUST resolve every identifier from the installed copy, **without network access**
- **4.3** MUST forbid, through a defence of its own, every suppression route that bypasses the project record
- **4.4** the toolchain's own invocation MUST satisfy the detector spec's reporting clauses
- **4.5** the entry point MUST run detectors before runners and stop on detector failure
- **5.1–5.3** MUST list active defences without triggering them; the listing MUST be derived from live configuration, not hand-maintained; project rules appear alongside bundled ones
- **6.1–6.4** MUST define and read a project record; every exception MUST carry a justification naming hazard and scope, and generic ones MUST be rejected; the record MUST be enumerable the same way as the defences
- **7.1–7.2** SHOULD generate an agent-context summary and SHOULD deliver it into the project automatically
- **8.1–8.2** a shipped toolchain MUST fail its own release if a bundled defence lacks resolvable documentation, and MUST run its own bundled defences on its own source
- **9.1–9.2** project-level and shipped-artefact conformance are graded separately

Reference implementations: `php-qa-ci` (<https://github.com/LongTermSupport/php-qa-ci>) and
`ts-qa-ci` (<https://github.com/LongTermSupport/ts-qa-ci>).

### How close this project already is

This is the striking finding. Measured against the toolchain specification, the hooks daemon
already satisfies most of it, apparently by convergent design rather than by conformance:

| DBF clause                                                                                    | This project                                                                                                                                   | Status                      |
| --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------- |
| 8.5 / 5.1 enumerable defences                                                                 | `bin/hooks-daemon handlers`                                                                                                                    | Present                     |
| 8.3 / 4.2 identifier resolves mechanically, offline                                           | `bin/hooks-daemon explain-rule <ID>`, `explain-handler <name>`                                                                                 | Present                     |
| 3.6 stable identifier printed with finding                                                    | `R-PIPE-TO-HEAD`, `R-GIT-RESET-HARD` etc., printed in every deny message                                                                       | Present                     |
| 8.4 docs state correct construction                                                           | Deny messages carry a "Fix" column and worked alternatives                                                                                     | Present, and unusually good |
| 3.5 blocking not warning                                                                      | PreToolUse handlers deny                                                                                                                       | Present                     |
| 8.6 / 7.1–7.2 agent-context summary delivered automatically                                   | The `<hooksdaemon>` block in `CLAUDE.md`, auto-generated by `generate-docs` / `regenerate-docs` on daemon restart                              | Present                     |
| 5.2 listing derived from live configuration                                                   | The block is regenerated from live config and handler metadata                                                                                 | Present                     |
| 3.2 bespoke rules                                                                             | Project handlers: `init-project-handlers`, `validate-project-handlers`                                                                         | Present                     |
| 4.5 detectors before runners                                                                  | Not established — worth checking                                                                                                               | **Unverified**              |
| 4.3 suppression routes forbidden by a defence                                                 | Partially: `qa_suppression` blocks noqa/eslint-disable/etc. in source                                                                          | Partial                     |
| 6.1–6.3 a project record of exceptions, with rejected-generic justifications, enumerable      | `exclude_paths` config exists, but there is no exception *record* with mandatory hazard-naming justification enumerable alongside the defences | **Gap**                     |
| 8.1–8.2 release fails if a bundled defence lacks resolvable docs / does not run on own source | `release-slate-check` exists; whether it asserts these two is unverified                                                                       | **Unverified**              |
| 3.3 red proof as its own commit                                                               | Not a project convention                                                                                                                       | **Gap**                     |

The two real gaps are **the project record (§6)** and **the red-commit discipline (3.3)**. Both are
cheap to add and are exactly the shape of work Plan 00412 is scoped for.

### Honest flags on Part 1

- The site is real, current (specs published 2026-09-08), and substantive. Nothing in Part 1 is
  inferred or reconstructed.
- I could not retrieve `llms.txt` — the fetch tool declined to reproduce it verbatim on copyright
  grounds despite the CC BY 4.0 licence. Not material; its content is an index of documents I
  retrieved individually.
- I did not retrieve `PROVENANCE.md`, `CHANGELOG.md`, `SCOPE.md`, `DECLINED.md` or `ACCEPTANCE.md`
  in full. `DECLINED.md` and `SCOPE.md` would be worth reading before adopting, since they record
  what the method deliberately does *not* claim.
- The method is **not security-specific**. "Defect" is explicitly any observed problem worth acting
  on. Applying it to security review is a legitimate specialisation, not the spec's own framing.

---

## Part 2: Recurring security review as a process

### 2.1 Cadence — what serious projects actually commit to

The honest headline: **very few open-source projects publish a recurring security-review cadence
at all.** What exists splits into three tiers.

**Tier 1 — calendar cadence, rare and long.** The OpenSSF Best Practices Badge is the clearest
citable calendar commitment, and it is at Gold level only:

> `security_review`: "The project MUST have performed a security review within the last 5 years.
> This review MUST consider the security requirements and security boundary."

— <https://www.bestpractices.dev/en/criteria/2>

Five years. That is the bar the industry's own badge programme sets for a *full* review, which
tells you how much of the real work happens elsewhere. The badge's criteria are graded MUST /
SHOULD / SUGGESTED, with SHOULD requiring documented rationale if unmet
(<https://www.bestpractices.dev/en/criteria/0>, <https://openssf.org/projects/best-practices-badge/>).

The badge also has a per-release rather than per-calendar hook:

> Dynamic analysis is SUGGESTED to be applied "to any proposed major production release of the
> software before its release", and for memory-unsafe languages, a fuzzer or similar SHOULD be
> "routinely used".

**Tier 2 — third-party audits at irregular intervals, tied to releases.** CNCF has run and
open-sourced third-party audits since 2018 across Argo, Backstage, CoreDNS, CRI-O, Envoy, etcd,
Flux, KubeEdge, Linkerd, Prometheus, SPIFFE/SPIRE and others. Kubernetes itself was audited by
Trail of Bits and Atredis against v1.13 (2019,
<https://www.cncf.io/blog/2019/08/06/open-sourcing-the-kubernetes-security-audit/>) and by NCC
Group against v1.24 (2022, published 2023,
<https://www.cncf.io/blog/2023/04/19/new-kubernetes-security-audit-complete-and-open-sourced/>);
findings are tracked as public issues
(<https://github.com/kubernetes/kubernetes/issues/118980>).

Note the anchoring: audits are scoped **to a named release version**, not to a date. That is the
single most transferable idea in this tier — it makes "what has changed since the last reviewed
point" a mechanically answerable question.

**Caveat, flagged:** I could not verify a formal *annual* audit commitment for Kubernetes or CNCF.
The observed intervals (2019, 2022) are roughly triennial and appear opportunistic rather than
scheduled. Do not cite CNCF as an annual cadence.

**Tier 3 — continuous automated evaluation, which is where the real cadence lives.** OpenSSF
Scorecard runs 24 checks and offers three cadences simultaneously
(<https://github.com/ossf/scorecard>):

- a GitHub Action that runs "on any repository change" — per-commit
- "a weekly Scorecard scan of the 1 million most critical open source projects" — weekly calendar sweep
- CLI and REST API for on-demand evaluation

Relevant checks: `SAST` ("Does the project use static code analysis tools"), `Fuzzing`,
`Code-Review`, `Dangerous-Workflow`, `Security-Policy`.

The OSPS Baseline (<https://baseline.openssf.org/>, <https://openssf.org/projects/osps-baseline/>)
defines 41 requirements across three maturity levels and six lifecycle stages, versioned
continuously (current version v2026.08.28) — the *standard itself* is on a rolling cadence even
where individual projects are not.

**The pattern to take from Tier 3:** the cadence that actually works is *per-change automated +
periodic automated sweep*, with human review reserved for what automation cannot see. The
calendar-driven human review is the exception layer, not the primary mechanism.

### 2.2 Delta review — scoping to what changed, and why it is not enough

**The case for delta review.** It is the only way to keep review proportionate to change volume.
The agile-security literature is consistent that end-of-cycle full reviews are structurally
incompatible with incremental delivery, and that the fix is to evaluate *deltas* continuously
rather than reset each cycle
(<https://lumenalta.com/insights/implementing-threat-modeling-in-agile-sdlc>,
<https://www.securitycompass.com/blog/threat-modeling-in-agile-development/>). The practical
advice from that literature that is worth keeping: **version the threat model alongside the code
in git**, and model a few threats per increment rather than aiming for total coverage immediately.

**What goes wrong with delta-only review.** Three distinct failure modes, and they are worth
separating because they have different remedies:

1. **Global invariants are invisible in a local diff.** Diff-only reviewers "catch many local
   issues… but may miss violations of global invariants, API misuse, or architectural consistency
   problems" (<https://graphite.com/guides/ai-code-review-context-full-repo-vs-diff>). A change
   can be individually correct and collectively wrong.

2. **Architectural drift is a property of the whole, not of any change.** The sharpest statement
   found: "Code review checks the diff. Drift is a property of the whole system, and it is nearly
   impossible to see a hundred-line diff and notice it has quietly created the fourth path into
   the database" (<https://graphlit.co/blog/architecture-drift>). And the security consequence:
   "security properties depend on structure as much as they depend on individual controls. When
   drift occurs, when boundaries blur, threat modelling becomes less reliable, audits become
   harder to evidence, and defensive assumptions stop matching reality"
   (<https://nhimg.org/articles/architectural-drift-is-the-maintainability-gap-ai-code-can-widen/>).

3. **The review baseline itself goes stale.** A delta review is only as good as its reference
   point. If the rules, the threat model, or the assumptions changed since the last reviewed
   commit, a review of "code changed since then" silently misses "code that did not change but is
   now wrong". **This is why a delta review must be scoped to changed code *plus changed rules* —
   a new rule makes unchanged code newly reviewable.** The dispatch brief already identified this;
   the research supports it, and it is the part most often missed.

**What forces a periodic full sweep.** The literature's conclusion is not "do periodic manual
reviews" — it is that periodic manual review is the *inferior* fallback: "The manual alternative
(periodic architecture reviews) finds drift months after it happened, which is better than nothing
and much worse than a check." The recommended shape is "a machine-readable description of the
intended architecture, plus something that compares it to reality automatically"
(<https://graphlit.co/blog/architecture-drift>).

Translated into a rule for this project: **a full sweep is owed whenever the rule set changes, and
that sweep should be mechanical.** Calendar-driven full sweeps are a crutch for the case where you
have no mechanical detector. Where you do have one, "changed code since last review" and "all code,
against new rules" are both cheap, and the second is what catches what the first cannot.

### 2.3 Living security documentation — the strongest examples

**GitLab Secure Coding Guidelines — the single best model found.**
<https://docs.gitlab.com/development/secure_coding_guidelines>

Purpose, verbatim: "This document contains descriptions and guidelines for addressing security
vulnerabilities commonly identified in the GitLab codebase," with the goal of "reducing the number
of vulnerabilities released over time."

Two properties make it the closest published analogue to Defence Before Fix:

1. **New guidelines are added by MR, and must cite the vulnerability that motivated them** —
   guidelines must include "links to examples of the vulnerability found, and link to any resources
   used in defined mitigations." The registry grows from real findings, not from theory.
2. **Every guideline is expected to have an automated detector.** Verbatim: *"For each of the
   vulnerabilities listed in this document, AppSec aims to have a SAST rule either in the form of a
   semgrep rule (or a RuboCop rule) that runs in the CI pipeline."* And: *"All guidelines should
   have supporting semgrep rules or RuboCop rules."*

That is clause 3.2 and clause 3.6 of DBF, independently arrived at, in production, at scale.
Classes covered: ReDoS, JWT, SSRF, XSS, XXE, path traversal, OS command injection, insecure TLS
ciphers, archive operations, URL spoofing, request parameter typing.

**Chromium security rules — a rule index with enforcement behind each entry.**
<https://chromium.googlesource.com/chromium/src/+/refs/heads/main/docs/security/rules.md>

A dozen named, durable rules, each its own document: the Rule of Two ("don't handle untrustworthy
data in the browser process in an unsafe language"), "the browser process should not handle
messages from web content", "always assume a compromised renderer", "use origin not URL for
security decisions", "avoid adding cross-origin full-page overlays", plus a recent addition for
LLMs in Chrome. The Rule of Two is the canonical example of a *class-level* rather than
instance-level defence: at most two of {untrusted input, unsafe language, no sandbox}
(<https://chromium.googlesource.com/chromium/src/+/refs/tags/128.0.6613.5/docs/security/web-platform-security-guidelines.md>).

Chromium's review process itself is launch-triggered, not calendar-triggered: "All launches and
major changes to Chrome undergo a security review"
(<https://www.chromium.org/Home/chromium-security/security-reviews/>). Worth quoting to anyone who
thinks a review is a sign-off: *"Security reviews don't mean that you can stop caring about
security. Your team is still accountable and responsible for ensuring that your code is free of
security bugs."*

**OWASP ASVS — the taxonomy-as-checklist model.** ASVS 5.0.0 restructured to 17 chapters and 345
requirements, with stable hierarchical identifiers of the form
`v<version>-<chapter>.<section>.<requirement>` (e.g. `v5.0.0-1.2.5`), and three verification levels
L1–L3 (<https://owasp.github.io/www-project-application-security-verification-standard/>). The
transferable properties are the **stable citable identifier per requirement** and the
**modularity** — a project includes only the chapters that apply and says so.

**CWE — the class taxonomy, recalibrated annually.** <https://cwe.mitre.org/top25/> — the CWE Top
25 is recomputed each year from real NVD/CVE data (the 2025 list drew on the CWEs behind 39,080
CVEs: <https://cwe.mitre.org/top25/archive/2025/2025_cwe_top25.html>,
<https://www.cisa.gov/news-events/alerts/2025/12/11/2025-cwe-top-25-most-dangerous-software-weaknesses>).
This is the best available example of a **defect-class registry on a recurring recalibration
cadence**: the taxonomy is stable, the *ranking* is annual and evidence-driven.

curl assigns a CWE to every flaw as a documented step of its disclosure process ("Figure out the
CWE (Common Weakness Enumeration) number for the flaw" —
<https://curl.se/dev/vuln-disclosure.html>), which is how an individual project connects its own
findings to the shared taxonomy.

**CNCF TAG Security self-assessment / joint assessment.**
<https://tag-security.cncf.io/community/assessments/guide/self-assessment/> and
<https://tag-security.cncf.io/community/assessments/guide/joint-assessment/> — a project writes a
self-assessment, which becomes the basis of a joint assessment with reviewers, which in turn is
"a cornerstone for if and when a project seeks graduation and is preparing for a security audit."
These are explicitly living documents that evolve with project maturity, and the threat model draws
its scope from the self-assessment's list of security-relevant functions. Example threat model:
<https://tag-security.cncf.io/community/assessments/projects/longhorn/threat-model/>.

### 2.4 "Build the defence before the fix" in the wild

This discipline exists in industry under a different name and without the ordering constraint.

**Variant analysis — the closest named practice.** "Variant analysis is the process of using a
known security vulnerability as a seed to find similar problems in your code." GitHub Security Lab
uses CodeQL for exactly this, with multi-repository variant analysis to find the same class across
many codebases; over 400 CVEs have been identified this way, including Android advisories affecting
more than 10 million applications
(<https://github.blog/security/vulnerability-research/multi-repository-variant-analysis-a-powerful-new-way-to-perform-security-research-across-github/>,
<https://codeql.github.com/docs/codeql-overview/about-codeql/>,
<https://securitylab.github.com/research/one-year-of-security-lab/>).

**This is DBF's clause 3.4 Sweep, with the crucial difference that variant analysis is normally
performed *after* the fix, by a research team, on other people's code.** DBF's contribution is the
ordering (before the fix, while the evidence exists) and the permanence (the query becomes a
blocking gate in the project, not a one-off research artefact).

**Trail of Bits — audit findings codified into public rules.** ToB publish their Semgrep rules
(<https://github.com/trailofbits/semgrep-rules>) and CodeQL queries
(<https://blog.trailofbits.com/2023/12/06/publishing-trail-of-bits-codeql-queries/>), and state
that rules are written *during* engagements — many of their Ruby rules "were written during their
recent Ruby Central (rubygems.org) audit"
(<https://blog.trailofbits.com/2024/12/09/35-more-semgrep-rules-infrastructure-supply-chain-and-ruby/>).
Their custom CodeQL queries "have been used to find critical issues that standard CodeQL queries
would have missed."

**Google Safe Coding — the same idea at platform scale.** "the most effective way to eliminate
entire classes of vulnerabilities is to stop treating security as a matter of developer discipline
and instead build it into the development platform." Safe Coding "enforces security invariants
directly into the development platform through language features, static analysis, and API design"
and "disallows unsafe constructs by default… with carefully reviewed exceptions." Measured result:
memory-safety vulnerabilities in Android fell from 76% to 24% of the total over six years
(<https://security.googleblog.com/2024/09/eliminating-memory-safety-vulnerabilities-Android.html>,
<https://security.googleblog.com/2024/11/retrofitting-spatial-safety-to-hundreds.html>,
<https://queue.acm.org/detail.cfm?id=3773096>).

Note the phrase "with carefully reviewed exceptions" — that is DBF's Owner-held Exception, at
Google scale.

**ClusterFuzz / OSS-Fuzz — the permanent detector, automated.** When a fuzzer finds a bug it saves
a reproducer test case, which "gets re-run periodically until it no longer produces an exceptional
condition"; ClusterFuzz then verifies the fix and records the commit range
(<https://google.github.io/oss-fuzz/further-reading/clusterfuzz/>). OSS-Fuzz's integration guidance
asks that fuzz targets be "regularly tested (not necessarily fuzzed!) as a part of the project's
regression testing process"
(<https://google.github.io/oss-fuzz/advanced-topics/ideal-integration/>).

This is the *instance*-level permanent detector (DBF would call it a Runner check), automated end
to end. It is the best existing proof that "a found defect produces a permanent detector" works
mechanically when the infrastructure exists.

**Where the discipline is weaker than one might hope.** curl's documented vulnerability disclosure
process — a 13-step, unusually rigorous process covering CVE assignment, CWE assignment, advisory
drafting, distros@openwall notification and merge timing — **does not mention writing a test case
or regression test at all** (<https://curl.se/dev/vuln-disclosure.html>). Nor does it describe any
recurring or scheduled review. That is a genuine finding, not an omission in my search: even a
best-in-class project's *written* security process may stop at disclosure and not extend to
permanent detection.

### 2.5 What this project should steal, with the trade-off stated

Ordered by value-to-cost. Each carries its cost honestly.

**1. Adopt the delta-review scope rule: changed code PLUS changed rules.**
Define the reviewed point as a commit SHA, recorded. A review covers the diff since that SHA, *and*
a full sweep of all code against any rule added or modified since that SHA.
*Trade-off:* requires recording a reviewed-point marker and keeping rule-change history queryable.
Cheap here — the daemon already versions handlers and the git history is clean.
*Why it matters:* this is the one failure mode a naive delta review cannot self-detect.

**2. Anchor reviews to releases, not to the calendar.**
Following CNCF's audit-per-release-version model, make the reviewed point a release tag. "Reviewed
as of v3.64.0" is checkable; "reviewed in September" is not.
*Trade-off:* releases may be irregular, so add a calendar backstop (the OpenSSF Gold five-year bar
is far too slack for a project of this change rate — something like per-minor-release plus a
quarterly floor is defensible, but that number is a project Calibration, not a research finding).

**3. Build the project record that DBF clause 6 requires and this project lacks.**
Today `exclude_paths` entries are exceptions in effect but carry no recorded hazard-naming
justification and are not enumerable alongside the defences. TOOLING-SPEC 6.2 requires that every
exception "carry a written justification that names the hazard and the scope, and the toolchain
MUST reject a generic one."
*Trade-off:* real work — a record format, a validator that rejects "TODO"/"needed for now", and a
listing command. But it closes the largest conformance gap and is directly useful independently of
DBF: right now an exclusion is indistinguishable from an oversight.

**4. Adopt the GitLab rule: every entry in the defect-class registry has a detector.**
Maintain a registry of "classes of defect we have seen", each entry naming the originating incident
and either its handler ID or an explicit recorded gap. GitLab's formulation — "AppSec aims to have
a SAST rule… for each of the vulnerabilities listed" — is the right ambition level, because it
admits gaps rather than pretending at completeness.
*Trade-off:* a registry that is not maintained is worse than none. Mitigate by generating it from
handler metadata (as `generate-docs` already does for the CLAUDE.md block) rather than
hand-maintaining it — which is also TOOLING-SPEC 5.2's requirement.

**5. Adopt the red-commit discipline for new handlers.**
DBF clause 3.3: commit the failing detector with the offending code still present, then commit the
fix. This project's TDD enforcement already gets you most of the way (test-before-source), but the
*handler* proving it fires on real repository code, as a separately reachable commit, is the part
missing.
*Trade-off:* two commits where one would do, and it constrains merge strategy. Note this project
already blocks `git merge --squash` and `gh pr merge --squash` (R-GIT-MERGE-SQUASH,
R-GH-PR-MERGE-SQUASH), so the ancestry requirement is already satisfied — the cost is genuinely
just the extra commit.

**6. Adopt the "verify by reproduction, not by report" review standard.**
SPEC §7: "A verdict on a remediation or a Defence MUST rest on reproduction, not on the report."
For an agent-heavy workflow this is the highest-leverage single sentence in the specification,
because an agent's report of having done the work is exactly the artefact most likely to read as
conforming without being so.
*Trade-off:* reviews get slower. That is the point.

**7. Assign a CWE (or a local class ID) to each finding, following curl.**
Connects local findings to the shared taxonomy and makes "have we seen this class before"
answerable.
*Trade-off:* CWE mapping is often ambiguous and can become box-ticking. Mitigate by treating CWE as
a secondary tag on a primary *local* class identifier, which is what actually needs to be stable.

**8. Check the two self-audit clauses (TOOLING-SPEC 8.1, 8.2) against `release-slate-check`.**
Does the release gate fail if a handler's rule ID does not resolve via `explain-rule`? Does the
daemon run its own handlers over its own source? Clause 3.3's warning is precisely on point: "A
toolchain analysing its own source with a configuration that omits its own bundled Rules reports
clean on every one of them, and both the Practitioner and a reviewer have taken that for a pass."
*Trade-off:* none. This is a verification task, not a design change, and if both already hold it
costs only the checking.

**What NOT to steal.** The calendar-driven full manual sweep as a primary mechanism. The research
is consistent that it finds drift months late and is strictly worse than a mechanical check
(<https://graphlit.co/blog/architecture-drift>). Where a detector can be written, write it;
reserve human sweeps for what no detector can read — which for this project is mainly the
architectural and trust-boundary questions, not pattern-level defects.

### 2.6 What I could not verify

Stated plainly, because a confident-sounding gap is worse than an acknowledged one.

- **No formal annual security-review cadence for Kubernetes/CNCF.** Audits observed at ~2019 and
  ~2022. Do not cite as annual.
- **No documented Django policy requiring a regression test with every security fix.** I searched
  specifically and found only the general disclosure and backport policy
  (<https://docs.djangoproject.com/en/dev/internals/security/>). The widely-repeated claim that
  mature projects mandate this appears to be folklore rather than written policy; one source
  characterises the regression check as typically "optional" even at large technology companies.
- **curl's process does not mention regression tests or recurring review** — verified by reading
  the policy, so this is a positive finding about the document's scope, but it means curl cannot be
  cited as an example of the defence-before-fix discipline.
- **Chromium's enforcement mechanisms per rule** — `rules.md` indexes the rules but does not state
  which are enforced by presubmit, compiler, or review. Determining that needs the individual rule
  documents.
- **OpenSSF Baseline's own review cadence** — the standard is versioned continuously but I found no
  statement of a required *project-side* periodic review interval within it.
- **This project's `release-slate-check` behaviour** against TOOLING-SPEC 8.1/8.2, and whether the
  daemon's entry point orders detectors before runners (clause 4.5). Both flagged as unverified in
  the gap table above; both are answerable by reading the code and were out of scope for this
  online-research brief.
- **DBF's `PROVENANCE.md`, `SCOPE.md`, `DECLINED.md`, `ACCEPTANCE.md`** not retrieved. `SCOPE.md`
  and `DECLINED.md` in particular would say what the method deliberately excludes, which is
  relevant before adopting.

---

## Source list

**Defence Before Fix**

- <https://defence-before-fix.github.io>
- <https://defense-before-fix.github.io>
- <https://defence-before-fix.github.io/SPEC.html> (vendored: `/workspace/remote-docs/defence-before-fix.github.io/SPEC.md`)
- <https://defence-before-fix.github.io/DETECTOR-SPEC.html> (vendored: `.../DETECTOR-SPEC.md`)
- <https://defence-before-fix.github.io/TOOLING-SPEC.html> (not vendored)
- <https://defence-before-fix.github.io/PRIMER.html>
- <https://defence-before-fix.github.io/defence-before-fix-project-prompt.md> (vendored)
- <https://github.com/Defence-Before-Fix/defence-before-fix.github.io>
- <https://github.com/Defense-Before-Fix/defense-before-fix.github.io>
- <https://ltscommerce.dev/articles/defence-before-fix-static-analysis>
- <https://github.com/LongTermSupport/php-qa-ci>
- <https://github.com/LongTermSupport/ts-qa-ci>

**Standards and cadence**

- <https://www.bestpractices.dev/en/criteria/2>
- <https://www.bestpractices.dev/en/criteria/0>
- <https://openssf.org/projects/best-practices-badge/>
- <https://github.com/ossf/scorecard>
- <https://baseline.openssf.org/>
- <https://openssf.org/projects/osps-baseline/>
- <https://owasp.github.io/www-project-application-security-verification-standard/>
- <https://cwe.mitre.org/top25/>
- <https://cwe.mitre.org/top25/archive/2025/2025_cwe_top25.html>
- <https://www.cisa.gov/news-events/alerts/2025/12/11/2025-cwe-top-25-most-dangerous-software-weaknesses>

**Project security process**

- <https://curl.se/dev/vuln-disclosure.html>
- <https://curl.se/dev/advisory.html>
- <https://docs.djangoproject.com/en/dev/internals/security/>
- <https://www.chromium.org/Home/chromium-security/security-reviews/>
- <https://chromium.googlesource.com/chromium/src/+/refs/heads/main/docs/security/rules.md>
- <https://chromium.googlesource.com/chromium/src/+/refs/tags/128.0.6613.5/docs/security/web-platform-security-guidelines.md>
- <https://docs.gitlab.com/development/secure_coding_guidelines>
- <https://tag-security.cncf.io/community/assessments/guide/self-assessment/>
- <https://tag-security.cncf.io/community/assessments/guide/joint-assessment/>
- <https://tag-security.cncf.io/community/assessments/projects/longhorn/threat-model/>
- <https://www.cncf.io/blog/2019/08/06/open-sourcing-the-kubernetes-security-audit/>
- <https://www.cncf.io/blog/2023/04/19/new-kubernetes-security-audit-complete-and-open-sourced/>
- <https://github.com/kubernetes/kubernetes/issues/118980>

**Defence-before-fix-like practice**

- <https://github.blog/security/vulnerability-research/multi-repository-variant-analysis-a-powerful-new-way-to-perform-security-research-across-github/>
- <https://codeql.github.com/docs/codeql-overview/about-codeql/>
- <https://securitylab.github.com/research/one-year-of-security-lab/>
- <https://github.com/trailofbits/semgrep-rules>
- <https://blog.trailofbits.com/2023/12/06/publishing-trail-of-bits-codeql-queries/>
- <https://blog.trailofbits.com/2024/12/09/35-more-semgrep-rules-infrastructure-supply-chain-and-ruby/>
- <https://security.googleblog.com/2024/09/eliminating-memory-safety-vulnerabilities-Android.html>
- <https://security.googleblog.com/2024/11/retrofitting-spatial-safety-to-hundreds.html>
- <https://queue.acm.org/detail.cfm?id=3773096>
- <https://google.github.io/oss-fuzz/further-reading/clusterfuzz/>
- <https://google.github.io/oss-fuzz/advanced-topics/ideal-integration/>

**Delta review and drift**

- <https://graphite.com/guides/ai-code-review-context-full-repo-vs-diff>
- <https://graphlit.co/blog/architecture-drift>
- <https://nhimg.org/articles/architectural-drift-is-the-maintainability-gap-ai-code-can-widen/>
- <https://lumenalta.com/insights/implementing-threat-modeling-in-agile-sdlc>
- <https://www.securitycompass.com/blog/threat-modeling-in-agile-development/>
