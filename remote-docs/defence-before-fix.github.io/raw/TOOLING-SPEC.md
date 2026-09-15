---
source_url: https://defence-before-fix.github.io/raw/TOOLING-SPEC.md
fetched_at: 2026-09-15T11:36:54.202186+00:00
fidelity: converted
source_sha256: 64d5dc76473f5f50bb2522ab61924181473fbf5c7f469dd502945e424bb98bd3
licence: CC-BY-4.0
stale_after: 2026-12-14
fetch_method: agent-browser-lite-headless (accept-markdown)
---

# Defence Before Fix: Toolchain Specification

**Version**: 0.2.0, published 2026-09-08
**Companion to**: [the method specification](SPEC.md), version 1.0.1, and [the detector specification](DETECTOR-SPEC.md), version 1.0.0
**Author**: [Joseph Edmonds](https://ltscommerce.dev), [Edmonds Commerce](https://edmondscommerce.co.uk)
**Coined**: 22 February 2026, in [the original article](https://ltscommerce.dev/articles/defence-before-fix-static-analysis)

## 1. What this document is for

The key words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT and MAY are to be interpreted as
described in RFC 2119.

[The method specification](SPEC.md) states what a [Practitioner] does when a [Defect] is found.
[The detector specification](DETECTOR-SPEC.md) states what each [Detector] must offer so that they
can write, prove, run and resolve a [Rule] in it. This document states what a project's
[Toolchain] must offer beyond that, so that the [Rules] become [Defences]
the project governs.

**A [Toolchain] is measured at the project level.** It is whatever the project assembles to
run its checks through: the [Detectors] and [Runners], and the parts around them
that route, list, record and resolve. Those parts may be third-party, first-party or project-level,
in any combination. A third-party [Toolchain] such as `php-qa-ci` can supply all of it. A project
can also meet this document with its own scripts around a bare [Detector]. [Conformance]
is a property of the assembled whole, because that is where it counts: a [Practitioner]
arriving at the project cannot tell which package a mechanism came from, and does not need to.

The three documents are separable because they fail separately, and all three failures have been
observed. A project can follow the method faithfully on a [Toolchain] that gives it nowhere to
record what it decided. A [Toolchain] can offer every mechanism the method needs whilst the
project using it writes no [Rules] at all. A [Detector] can be the best host for
a [Rule] in its language whilst shipping an inline ignore that the project has never decided
whether to allow. Conflating them produces a specification that blames a project for a gap in its
[Toolchain], credits a [Toolchain] for discipline the project supplied itself, or
fails a [Detector] for governance that was never its to decide.

**The governing principle**: where the method specification requires a [Practitioner] to do
something, a [Conforming] [Toolchain] MUST make that possible without the project
building the mechanism first. A [Toolchain] that leaves the project to construct the means has
moved the obligation rather than met it. Where the project builds the means itself, those scripts are
part of its [Toolchain] and are judged as such.

**How to read this document.** It is self-contained for grading a [Toolchain]. The
table in section 2 glosses every term it borrows. Each clause states its obligation in its heading
and first sentence, and the **Why** paragraph beneath is reasoning, not a further requirement. A
link is there for depth and is not a prerequisite for the sentence that carries it.

## 2. Terminology

Terms from the method specification and the [detector specification](DETECTOR-SPEC.md) carry over unchanged. Every
capitalised term links to its definition; the ones this document leans on most are, in short:

| Term           | In one line                                                                         |
| -------------- | ----------------------------------------------------------------------------------- |
| [Detector]     | A tool that reads code without executing it and reports what it finds               |
| [Runner]       | A tool that executes code, a test suite or a compilation, and reports what happened |
| [Rule]         | One check a [Detector] evaluates                                                    |
| [Defence]      | A [Rule] with its documentation, in force and [Blocking]                            |
| [Identifier]   | The stable name printed with a finding that leads to its documentation              |
| [Blocking]     | Fails the run rather than issuing a [Warning]                                       |
| [Exception]    | A recorded, justified decision to leave an [Instance] unfixed or a [Rule] unapplied |
| [Practitioner] | Whoever is doing the work, a person or an [Agent]                                   |
| [Owner]        | The human who decides what the codebase may keep                                    |
| [Bundled rule] | A [Rule] a [Detector] ships rather than one the project wrote                       |
| [Harness]      | The route by which one [Rule] is run against supplied code on its own               |

These are additional.

#### Consuming project

A codebase that installs a [Detector] or a [Toolchain] shipped by somebody else. The maintainer of what is installed does not control it and cannot inspect it.

#### Bundled defence

A [Defence] a shipped [Toolchain] carries and enables by default in every [Consuming project]. A [Bundled rule] is the [Detector]-level counterpart; a [Bundled defence] is one with its documentation, [Blocking], and routed through the [Toolchain]'s own entry point.

#### Project record

The place a project writes down the judgements the method specification delegates to it: [Calibrations], [Exceptions] and conventions.

The distinction between a [Bundled defence] and a project's own is significant throughout. A bundled
[Defence] is authored once and runs in codebases its author will never see, so everything a
[Practitioner] needs in order to act on it has to travel with it.

## 3. The division of responsibility

Almost every requirement in section 8 of the method specification has two halves. Stating only one
of them is what produces a [Toolchain] that is *nearly* usable. The middle column says which
document states the mechanism half; the assembled [Toolchain] MUST provide every row, whichever
part of it does so.

| Requirement             | The mechanism, and where it is stated                                                                       | The project supplies                 |
| ----------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| Bespoke [Defences]      | The authoring and registration route, [detector specification](DETECTOR-SPEC.md) 4.1                        | The [Rules]                          |
| The red proof           | A [Harness], [detector specification](DETECTOR-SPEC.md) 4.2                                                 | The [Fixture] and the red run        |
| Running the [Defence]   | A local invocation, including subsets, [detector specification](DETECTOR-SPEC.md) 5                         | Running it                           |
| [Identifier] resolution | The lookup, [detector specification](DETECTOR-SPEC.md) 6 for [Bundled rules], clause 4.2 here for the rest  | The documentation content            |
| Correct construction    | A place for it to live, clause 4.2 here                                                                     | The remediation text                 |
| Enumeration             | The listing, section 5 here                                                                                 | The [Defences] listed                |
| [Agent]-context summary | Generation and delivery, section 7 here                                                                     | The terse lines                      |
| Recorded decisions      | A location it reads itself, section 6 here                                                                  | The decisions                        |
| [Suppression]           | A route that can be forbidden, [detector specification](DETECTOR-SPEC.md) 7; forbidding it, clause 4.3 here | The decision, under method section 4 |

Read down the middle column and the shape of a [Conforming] [Toolchain] is already visible. Read across
any row and the failure mode is visible too: either half alone leaves the [Practitioner] stuck.

## 4. The detectors a toolchain routes defences through

### 4.1 Every detector the toolchain routes a defence through MUST conform to the [detector specification](DETECTOR-SPEC.md)

A [Toolchain] MUST NOT route a [Defence] through a [Detector] that does not
[Conform] to [the detector specification](DETECTOR-SPEC.md). That document's MUSTs, in brief,
are six. The [Detector] hosts bespoke [Rules]. It runs one [Rule] on its own against supplied
code. It prints a stable [Identifier] with every finding. It runs locally, down to one file, with
the result in the command's own output and nothing reportable only through a hosted service. It
resolves every [Identifier] a [Bundled rule] can print to documentation shipped with it, offline.
It makes any inline [Suppression] route detectable or disableable. A [Detector] that fails any
one of those, after wrapping, fails this clause. Three points govern how that is met.

1. **Wrapping is permitted.** The [Toolchain] MAY supply a mechanism the
   [Detector] lacks by wrapping it, with a [Harness] script or a
   resolver of its own. The [Detector] together with that wrapping is then what the
   [Practitioner] uses and what is judged.

2. **How the wrapped pair is judged.** Start from the gap, not from what the [Detector] does
   well:

   | The [Detector]'s gap                       | What the [Toolchain] adds                                     | This clause |
   | ------------------------------------------ | ------------------------------------------------------------- | ----------- |
   | Resolves none of its [Identifiers] offline | A resolver keyed on the [Identifier], covering all of them    | Holds       |
   | Two [Bundled rules] have no documentation  | Nothing for those two                                         | Fails       |
   | Two [Bundled rules] have no documentation  | Its own documentation for those two, resolved by [Identifier] | Holds       |

   Behind the table is one question. With the wrapping in place, does the [Detector]
   meet every MUST of sections 4 to 7 of the [detector specification](DETECTOR-SPEC.md),
   exercised as its clause 8.1 describes? If yes, this clause holds. If no, it fails, however
   much else the [Detector] does well, and whether or not a clause below names the same gap
   again. Wrapping can add a mechanism; it cannot excuse a gap. The [Detector]'s own verdict
   under that document is unchanged by the wrapping. Satisfying most of that document is not
   [Conformance] to it, any more than satisfying most of this one is.

3. **What cannot be wrapped.** A [Detector] that cannot host a bespoke [Rule] at all
   cannot be wrapped into [Conformance], and no [Defence] is routed through it.
   It MAY still run as one of the [Toolchain]'s checks, as a formatter or a
   [Runner] does.

**Why**: the six clauses of the method are carried out in a [Detector], and everything this
document adds presumes those clauses can be followed there. A [Toolchain] that lists, records
and resolves beautifully around a [Detector] in which no [Rule] can be written or proven
has governed nothing. The wrapping is permitted because a [Practitioner] cannot tell where a
mechanism lives, and the method does not care. It is bounded because a mechanism the [Detector]
does not offer and the [Toolchain] does not add is a gap the project writes down under method
clause 3.2. A gap recorded is not a gap closed.

### 4.2 The toolchain MUST resolve every identifier a defence it routes can print, from the installed copy, without network access

This clause widens the [detector specification](DETECTOR-SPEC.md)'s reach: that document resolves
[Bundled rules] only, and this one covers every [Identifier] the project can see, the project's
own [Rules] included. The [Toolchain] MUST resolve every [Identifier] its [Defences]
print to [Remediation docs] on disk. The mechanism is keyed on the
[Identifier] exactly as printed, and it covers the project's own [Rules] and
every [Bundled defence]. Those [Remediation docs] MUST ship
with the project or with the [Toolchain], at a version tracked together. The
[Toolchain] MUST also give that documentation a place to live, so that a
[Rule author] adding a [Rule] knows where its documentation goes.
The documentation an [Identifier] resolves to MUST state the correct construction, not
only the prohibition, specifically enough to act on, as method clause 8.4 requires. The
[Toolchain] supplies the place and the [Rule author] the text.

This clause closes what the [detector specification](DETECTOR-SPEC.md) leaves open. That document holds a
[Detector] to on-disk resolution of its own [Bundled rules] and
no further, because it cannot know a project's documentation. A third-party [Detector]'s
native catalogue, which the [Toolchain] orchestrates without claiming as its own, is
resolved under that document's clause 6 and is not re-shipped here.

**Why**: method specification clauses 3.6 and 8.3. The [Identifier] has to resolve for the
reader, which for an [Agent] means mechanically and on disk, and the project's own
[Rules] are the ones that carry its knowledge. A [Detector] that prints the
[Identifier] faithfully has done its half; a project in which that string then leads nowhere
has a [Message] that names a pattern without leading anywhere, which method clause 3.6 says
does not [Conform].

### 4.3 The toolchain MUST forbid, through a defence of its own, every suppression route that bypasses the project record

A [Conforming] [Toolchain] MUST disable every [Suppression]
route that bypasses the [Project record], or MUST run a [Blocking]
[Defence] that fails on its use. A route bypasses the [Project record] when a finding can be
silenced through it without an entry appearing in the [Project record]: an inline
[Suppression] comment, a per-line ignore and a silently generated [Baseline] all do. The
obligation covers every such route in every [Detector] the [Toolchain] routes a
[Defence] through. Irreducible cases MUST be directed to the [Project record],
where clause 6.2 requires a justification.

The [detector specification](DETECTOR-SPEC.md) permits a [Detector] to ship such a route provided
it can be detected or disabled. This clause is where the project's decision is made and enforced,
and the decision is no. A [Baseline] an [Owner] has adopted under method section
4 is therefore kept in the [Project record], or read from a file the record names. It is
never a file the [Detector] generates unseen.

**Why**: a governance mechanism whose escape hatch is an unreviewed comment is not a governance
mechanism. This is the one place this document is stricter than the [Detectors] it assembles
are by default, and it is deliberate. The method specification's position is that
[Suppression] is an [Owner] decision, and an [Owner] cannot decide something
they are never shown. The [Detector] is not asked to forbid the route because the
[Detector] is not the project; the [Toolchain] is the project's, so it is.

The reference implementations both do this. `ts-qa-ci` bans every `eslint-disable` and
`@ts-expect-error` form outright; `php-qa-ci`'s `ForbidInlinePhpstanIgnoreRule` bans inline
`@phpstan-ignore` and directs irreducible cases to the configuration file, where they are visible.

### 4.4 The toolchain's own invocation MUST satisfy the detector specification's reporting clauses for every defence it routes

The [Toolchain]'s own entry point MUST meet clauses 5.1 to 5.4 of the
[detector specification](DETECTOR-SPEC.md) for every [Defence] it routes. That means invocable
locally with no infrastructure, over a subset down to one file, and with the result in the output of
the command the [Practitioner] ran. No [Defence] may be reportable only
through a mode they cannot run. The entry point MUST also print every [Identifier] its
[Detectors] print, unaltered, so that clause 4.3 of the
[detector specification](DETECTOR-SPEC.md) holds through the wrapping. The [Detector]'s verdict
under that clause is on its own output. The [Toolchain]'s is on what reaches the
[Practitioner].

**Why**: method clause 3.5 asks the [Practitioner] to demonstrate enforcement through the
project's own entry point, not through the [Detector] directly. A [Detector] that
[Conforms] on its own, wrapped in a command that runs only the whole codebase or only
elsewhere, has had its reporting clauses undone by the wrapping. The [Practitioner]
is then back to a loop that does not close.

### 4.5 The toolchain's entry point MUST run detectors before runners, and MUST stop on a detector failure

The invocation the project uses to accept changes MUST evaluate its [Detectors] before its
[Runners]. A [Blocking] failure at the [Detector] level MUST stop the
levels below it from being treated as meaningful, in the order method section 5 states. How the
project expresses that sequence, and where it runs, remain out of scope under method section 8.

**Why**: method section 5. A [Detector] is preventive and a test is diagnostic, and a failure
at the [Detector] level produces confusing results at every level above it. The method makes
the ordering a property of the project rather than of any one remediation, which is exactly the
kind of property that lives in the [Toolchain] and nowhere else.

## 5. Enumeration

### 5.1 The toolchain MUST be able to list the defences active in a project, without triggering them

The [Toolchain] MUST list every [Defence] active in the project without
running it. The listing MUST include each [Defence]'s [Identifier] and a terse
statement of what it forbids or requires. It MUST provide the route to each one's full documentation.

**Why**: method specification clause 8.5. An [Agent] arriving at a codebase has no colleague to ask.
Without a listing, a project's standards can only be learned by violating them one at a time.

### 5.2 The listing MUST be derived from the active configuration

The listing MUST be generated from the configuration the [Toolchain] actually loads. It
MUST NOT be a hand-maintained document that happens to describe the configuration. The test is
what happens when a [Rule] is added to the configuration and nobody edits anything else: a
derived listing shows it on the next run, and a hand-maintained one does not.

**Why**: a hand-maintained list drifts, and it drifts silently and in the dangerous direction. The
observed failure is a [Rule] that is registered, active, [Blocking], and absent from
the list of [Rules], whilst the list states its own count with confidence. A derived listing cannot
diverge from what is enforced, because the thing enforced is what produced it.

### 5.3 A project's own defences MUST appear in the listing alongside bundled ones

Every [Defence] the project has written itself MUST appear in the listing clause 5.1
requires, meeting its content requirements in full, alongside every [Bundled defence].

For a shipped [Toolchain], the case is the same and worth spelling out. Its
[Defences] against its own source, the ones only its contributors can trigger, are that
project's own [Defences] for this purpose. They MUST appear in the same listing clause 5.1
requires, meeting its content requirements in full, when the [Toolchain] is run on itself,
however they are enabled. Where such a [Defence] is not expressible in the [Toolchain]'s own
[Detectors], its entry MAY be sourced from wherever it is enabled, provided the listing stays derived
under clause 5.2 rather than hand-maintained.

**Why**: the [Practitioner] does not care which package a [Rule] came from. They care what defends the
code in front of them, and a listing that covers only what a shipped [Toolchain] carries describes somebody
else's project.

## 6. The project record

This section exists because of a gap found by cold readers of the method specification, repeatedly
and independently. The method delegates several judgements to project level, and a [Practitioner]
arriving at a project that has recorded none of them has no legal move. That is a [Toolchain]
obligation. The method specification cannot fix it, because the method specification does not own a
file in the project.

### 6.1 The toolchain MUST define a location for the project record, and MUST read it itself

The [Toolchain] MUST define where the [Project record] lives and MUST load it.
Not a documentation convention. A path the [Toolchain] loads.

**Why**: a [Project record] the [Toolchain] does not read can be wrong without anything noticing.
When the [Toolchain] reads it, the written decision and the enforced decision are the same object, and
neither can drift from the other.

### 6.2 Every exception in the project record MUST carry a written justification that names the hazard and the scope, and the toolchain MUST reject a generic one

The [Toolchain] MUST require a written justification on every [Exception].
It MUST NOT supply a default, and MUST reject an [Exception] that omits one. A field that is
merely present and non-empty does not satisfy this clause.

**Why**: an [Exception] without a reason is indistinguishable from an [Exception] nobody would defend,
and the person who could tell them apart is usually gone. Requiring the sentence is the whole
mechanism: it costs the author a minute at the moment they have the reason in mind, and it is the
only thing that makes an [Exception] reviewable later.

`ts-qa-ci`'s `tier-a-exemptions.json` is the reference implementation, and its own two entries
demonstrate the standard: both explain the scope limit as well as the reason.

The justification MUST name the [Hazard] being accepted and the scope of the [Exception].
The [Toolchain] MUST reject a justification that could be pasted onto any [Exception]
unchanged, by a check it documents: "needed for now", "legacy", "TODO" and their like. That check
cannot verify truth, and a [Toolchain]'s [Conformance] MUST NOT be read as having verified
it. Whether the sentence is true is the [Owner]'s judgement under section 4 of the method
specification. That is why clause 6.3 puts every justification in one listing, where a vacuous
one is seen next to its neighbours.

### 6.3 The project record MUST be enumerable by the same means as the defences

Listing the [Defences] and listing the [Project record] MUST be the same kind of operation.

**Why**: method specification clause 8.7. A decision nobody can find will be re-opened by every
[Practitioner] who arrives after it, which converts a settled question into a recurring one.

### 6.4 The toolchain SHOULD state its own defaults for anything the method leaves to the project

Where the method specification delegates a judgement and the project has recorded nothing, a
documented [Toolchain] default is what the [Practitioner] falls back to.

**Why**: this is the deadlock this section exists to break. "The project decides" combined with "the
project has decided nothing" leaves an [Agent] choosing between guessing and stopping. A default
turns the first project-level decision from a prerequisite into a refinement, and the project's
first day is exactly when it has recorded least and can afford the interruption least.

## 7. Agent context

### 7.1 The toolchain SHOULD generate a summary of the active defences suitable for an agent's context

One terse line per [Defence], phrased as a standing instruction rather than as a failure report, each
carrying its [Identifier] and the route to its documentation. Generated from the active configuration,
per clause 5.2.

### 7.2 The toolchain SHOULD deliver that summary into the project automatically

Into the file the project's [Agents] already load, refreshed on install and update, in a delimited
region marked as generated.

**Why**: 7.1 and 7.2 are separate clauses because they are separately missed, and the two reference
implementations miss opposite halves. `php-qa-ci` writes an auto-generated, auto-refreshed block
into every [Consuming project]'s [Agent] instructions and does not put a [Rule] table in it; `ts-qa-ci`
maintains an excellent [Rule] catalogue and has no mechanism to deliver it. Each has built the half
the other lacks. A summary that exists but is never loaded and a delivery channel carrying
everything except the [Rules] are the same outcome from opposite directions.

Together these are the only clauses in any of the three specifications that operate **before** the
mistake rather than after it, which is why they are worth stating even as SHOULDs.

## 8. Self-audit

### 8.1 A shipped toolchain MUST fail its own release if a bundled defence lacks resolvable documentation

The [Toolchain] MUST run an automated check that blocks its own release. The check covers
every [Identifier] printed by a [Rule] the [Toolchain] authors or bundles
as its own [Defence], whatever kind of [Detector] carries it. Where a documentation
page covers a family of [Identifiers] by a pattern, as clause 6.5 of the
[detector specification](DETECTOR-SPEC.md) allows, this audit MUST apply the pattern to every
[Identifier] printed and confirm it lands on that page. A member added to the
[Rule] and not to the page then fails the release. A third-party [Detector]'s
native catalogue, which the [Toolchain] orchestrates without claiming as its own, is outside
this audit; whether that catalogue resolves is judged under the
[detector specification](DETECTOR-SPEC.md)'s clause 6, as clause 4.2 says. The [detector specification](DETECTOR-SPEC.md)'s
clause 6.3 names the dangling reference as the failure to guard against above all others. This is the
guard, and a [Toolchain] is not held to less than it holds its
[Practitioners] to.

**Why**: clause 4.2 is the clause most easily believed to be satisfied whilst being broken, because
the documentation is written by the same person who wrote the [Rule] and its absence is invisible from
the inside. A check that blocks the release is the difference between honouring the clause and asserting it.
It is also the method applied to the [Toolchain]: the [Class] of [Defect] is "a [Rule] that blocks without
explaining", and it is detectable mechanically.

### 8.2 A shipped toolchain MUST run its own bundled defences on its own source

Every [Rule] the [Toolchain] ships to [Consuming projects] MUST also be
active when the [Toolchain] analyses itself, and a [Toolchain] release MUST fail when
they are not.

**Why**: a mechanism that delivers [Rules] to installed packages and not to the root package
leaves the [Toolchain] as the one project in which its own [Defences] never run. A
[Defect] in a [Rule]'s own code then goes unseen by every [Rule] built to see it. A
self-check that reports clean is believed, by the [Rule author] and by anyone checking their
work, because nobody expects a clean run to have run nothing. This clause was found by an execution
test in which both the [Practitioner] and the reviewer cited exactly such a run as evidence.

A project that assembles its [Toolchain] without shipping it has no release and no
[Consuming project], so this section does not bear on its [Conformance]. Its
own [Defences] already run on its own source, because that is the only source there is.

## 9. Conformance

**A project's [Toolchain] [Conforms]** if every MUST in sections 4 to 6 holds across the
assembled parts, wherever each part came from, and, where the [Toolchain] is one the project
ships, every MUST in section 8 as well. The project-level verdict is a single grade; which part of the
[Toolchain] satisfied each clause is evidence for that grade, not a second grade.

**A [Toolchain] [Conforms] with [Agent] support** if it additionally satisfies section 7.

Partial [Conformance] MUST NOT be described as [Conformance]. A [Toolchain] that satisfies most of this
document is in a normal and respectable condition; it is not [Conforming], and describing it as such
removes the only value the word has.

### 9.1 A project that ships a detector or a toolchain has two levels of conformance, graded separately

As a project, it follows the method with its own assembled [Toolchain], like any other
project, and is graded against this document and section 7 of the method specification on that
basis. As an artefact, what it ships is graded for its consumers: a [Detector] against
[the detector specification](DETECTOR-SPEC.md), a [Toolchain] against this document as it stands
when installed into a [Consuming project] with nothing else built around it. The two
verdicts MUST be graded and declared separately, and neither implies the other. Section 8 bears on
the artefact grade only; clause 5.3 is its project-level counterpart.

**Why**: the two questions have different readers. A contributor to the artefact wants to know
whether the project practises what it ships; a [Consuming project] wants to know what it
will get. A single grade answers neither, and the observed failure is a [Toolchain] whose own
source was the one place its [Bundled defences] never ran, which a consumer-facing grade
alone would never have shown.

### 9.2 The declaration is the claim and the known-gap record, not a condition of conformance

A project or a shipped artefact MAY declare, machine-readably in whatever form its ecosystem uses to
record dependencies, the version of the method specification it follows and the version of this
document or the [detector specification](DETECTOR-SPEC.md) it [Conforms] to. A project that ships an artefact
carries both levels of clause 9.1 in that declaration, each named separately.

The same declaration is where a gap is recorded once it is known. A project or artefact that has
learnt that it fails a MUST of the document it declares against MUST record that gap alongside the
version, in the same file or one it names. It may learn that from its own self-audit under section 8
or from a [Practitioner]'s report under the method's clause 3.2. A declaration with a non-empty gap record is
a statement of where the project stands and is not a claim of [Conformance]. A mechanism gap
is by its nature one the [Toolchain] could not detect for itself, so the record is the only
place its [Owner] and its consumers can learn of it.

The declaration is optional. A [Toolchain] assembled before this document existed, or by a
project that has never read it, MAY be graded [Conforming] on evidence by anyone who exercises
the clauses above against it. A verdict on any [Toolchain], declared or not, rests on that
exercise and not on the claim.

**Why**: a [Conformance] claim in a README is a sentence; a [Conformance] claim in a manifest is a fact
about a specific installed artefact, checkable by anyone, including mechanically. It also fixes what
"[Conforming]" meant at the point the claim was made, which a claim against a moving document cannot.
Making the claim a condition, though, would grade the maintainer's reading rather than the
[Toolchain], and would leave every project that met the method before hearing of it unable
to say so.

## 10. Relationship to the method and detector specifications

This document adds no obligations to a [Practitioner] and relaxes none. Every clause here exists to
make a clause of the method specification achievable.

Where this document and the method specification disagree, the method specification governs. It
describes the method, which is the thing being specified; this describes the equipment. Where this
document and the [detector specification](DETECTOR-SPEC.md) disagree about a [Detector], the [detector specification](DETECTOR-SPEC.md)
governs, because it is the document a [Detector]'s maintainer works from; what this document
asks of a [Detector] is that it [Conform] there.

Nothing here requires a project to use a [Conforming] [Toolchain] shipped by anyone. A project can [Conform] to the method
specification on a [Toolchain] that [Conforms] to none of this, at the cost of building the missing
mechanisms itself, and once built they are its [Toolchain] and are graded here. This document exists so that it
does not have to build them alone.

<!-- Term link definitions -->

[agent]: SPEC.md#agent
[agents]: SPEC.md#agent
[baseline]: SPEC.md#baseline
[blocking]: SPEC.md#blocking
[bundled defence]: #bundled-defence
[bundled defences]: #bundled-defence
[bundled rule]: DETECTOR-SPEC.md#bundled-rule
[bundled rules]: DETECTOR-SPEC.md#bundled-rule
[calibrations]: SPEC.md#calibration
[class]: SPEC.md#class
[conform]: SPEC.md#conform
[conformance]: SPEC.md#conform
[conforming]: SPEC.md#conform
[conforms]: SPEC.md#conform
[consuming project]: #consuming-project
[consuming projects]: #consuming-project
[defect]: SPEC.md#defect
[defence]: SPEC.md#defence
[defences]: SPEC.md#defence
[detector]: SPEC.md#detector
[detectors]: SPEC.md#detector
[exception]: SPEC.md#exception
[exceptions]: SPEC.md#exception
[fixture]: SPEC.md#fixture
[harness]: DETECTOR-SPEC.md#harness
[hazard]: SPEC.md#hazard
[identifier]: SPEC.md#identifier
[identifiers]: SPEC.md#identifier
[instance]: SPEC.md#instance
[message]: SPEC.md#message
[owner]: SPEC.md#owner
[practitioner]: SPEC.md#practitioner
[practitioners]: SPEC.md#practitioner
[project record]: #project-record
[remediation docs]: SPEC.md#remediation-docs
[rule]: SPEC.md#rule
[rule author]: DETECTOR-SPEC.md#rule-author
[rules]: SPEC.md#rule
[runner]: SPEC.md#runner
[runners]: SPEC.md#runner
[suppression]: SPEC.md#suppression
[toolchain]: SPEC.md#toolchain
[warning]: SPEC.md#warning
