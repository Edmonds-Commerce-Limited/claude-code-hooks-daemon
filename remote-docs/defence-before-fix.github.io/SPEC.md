---
source_url: https://defence-before-fix.github.io/SPEC.html
fetched_at: 2026-09-10T07:45:17.574717+00:00
fidelity: converted
source_sha256: 4f039f5c4e1cf7e29b12885a2572cae259128f1ca1468c8a8863af1bf30af09a
licence: unreviewed
stale_after: 2026-12-09
fetch_method: agent-browser-lite-headless (llms-link)
---

Defence Before Fix (DBF)

Method specification
Detector specification
Toolchain specification
Primer
Tools
Provenance
Changelog
Agents

Agents: read the project prompt
(raw markdown), or start from llms.txt.
This page as raw markdown.

By Joseph Edmonds of
Edmonds Commerce. First published 22 February 2026.

# Defence Before Fix: Method Specification

Version: 1.0.1, published 2026-09-08
Companion to: the detector specification, version 1.0.0, and the toolchain specification, version 0.2.0
Author: Joseph Edmonds, Edmonds Commerce
Coined: 22 February 2026, in the original article

Defence Before Fix (DBF) is a phase that runs before a Defect is fixed. Rather than dropping
straight into remediating the specific Instance in front of you, you first treat that Instance
as evidence of a Class, and you build the automated Defence that detects every occurrence of
that Class across the whole codebase. The Defence is only trusted once it has been seen to
fire.

The Defect is what makes this possible. It is a real, confirmed, impactful example of a harmful
pattern, which is precisely the raw material a good custom Rule needs and which speculative
Rules never have. Every Defect is therefore an opportunity to extend the codebase’s permanent
defensive Coverage, and that opportunity exists only in the window before the fix.

Defence Before Fix does not replace test-driven development. The specific Defect is still
reproduced with a test and proven fixed, exactly as normal. The two operate at different levels:
TDD addresses the Instance, Defence Before Fix addresses the Class.

Not to be confused with Defence in depth, which is a security term meaning something else
entirely. The Defence here comes before the fix in time, not in layers.

US spelling: Defense Before Fix. Abbreviated DBF throughout.

## Status of this document

This is version 1.0.1 of the specification. It is normative: section 3 defines the method,
section 4 states who decides what, and section 7 defines what Conformance means and who may claim
it.

This document is the source of truth for what the method is. Where anything else describing
Defence Before Fix disagrees with it, including the article in which the term was first published,
this document is correct.

Who coined the term, when it was first published, and what is and is not being claimed are recorded
separately in provenance, which is meta information about this specification
rather than part of it. A short introduction to the method is in the primer.

Changes are recorded in the changelog at the end.

## 1. Terminology

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are to be interpreted as described in
RFC 2119.

#### DBF

The acronym for Defence Before Fix, used as shorthand for this method and for anything built under it. A DBF is a Rule as this specification defines it; a DBF is one that Conforms to the Toolchain specification; a DBF project is one that Conforms to section 7.

#### Defect

Any observed problem worth acting on: a bug, a code review finding, a performance observation, an incident, an inconsistency. The method does not care which.

#### Class

The pattern, style, idiom or configuration that permitted the Defect, expressed generally enough that other occurrences of it are also Defects or latent Defects.

#### Instance

One occurrence of a Class. The reported Defect is one Instance; there are usually others.

#### Hazard

The harm a Class causes, which is not necessarily a failure. It may be a failure, but it may equally be error hiding, or something merely sloppy that makes the code harder to reason about or to change safely.

#### Detector

A tool that reads code without executing it and reports occurrences of a pattern. A Detector is not a Runner. What a Detector must offer so that a Practitioner can write, prove, run and resolve a Rule in it is specified in the detector specification.

#### Runner

A tool that executes code and reports what happened: a test Runner, a compilation, a benchmark, a smoke check. A Runner answers questions about behaviour at one moment, on the paths it happened to exercise; a Detector answers questions about the text of the code, everywhere it exists. Detection under this method MUST come from a Detector, for that reason.

#### Rule

One pattern definition within a Detector.

#### Defence

A Blocking Rule together with the supporting documentation that clarifies it and clearly signposts best practice. A Rule without its documentation is not a Defence, and neither is a Rule that only warns.

#### Coverage

The accumulated set of Defences a project has built. Every Defect handled under this method extends it.

#### Remediation docs

The fuller documentation a failure Message points to, explaining what a Rule is about, why it exists and how to fix a violation correctly.

#### Blocking

A Rule is Blocking when its firing prevents a change from being accepted by whatever the project uses to accept changes. A report that does not block is a Warning, and a Rule that only warns is not a Defence.

#### Warning

A report that does not block. A Rule that only warns is not a Defence.

#### Message

The text a Rule prints when it fires. Terse, and carries the Rule’s Identifier.

#### Identifier

The stable string a Rule reports with, by which its Remediation docs are found. Survives renames of the Rule.

#### False positive

A report on code that does not carry the Hazard.

#### Narrowing

Reducing a Rule’s scope so it stops reporting code that does not carry the Hazard. Narrowing that excludes code which does carry the Hazard is a Suppression.

#### Suppression

Any means of preventing a Rule from reporting an Instance that carries the Hazard: an ignore comment, an ignore entry, a Baseline, or a Narrowing that excludes it.

#### Baseline

A recorded set of pre-existing Instances a Rule is configured not to report. A Suppression in bulk.

#### Exception

A recorded Owner decision that a specific Instance or scope is excluded from a Defence. The only legitimate form of Suppression. This document never uses the word in its programming-language sense.

#### Sweep

Running a Rule across the whole codebase to enumerate every Instance.

#### Fixture

Code written to carry the Hazard deliberately, so a Rule can be proven to fire when the codebase has no Instance to prove it on.

#### Calibration

A project-level ruling on a threshold or parameter this document leaves open.

#### Practitioner

Whoever is doing the work of this method on a given Defect, human or Agent. Decides how the Defence is built. Has no authority over Exceptions.

#### Agent

A Practitioner that is an automated system. Everything said of a Practitioner applies to an Agent; section 8 exists because of what is additionally true of one.

#### Owner

Whoever holds authority over a project’s Exceptions and Calibrations. Always a human. The project decides who, and clause 8.7 requires the answer to be findable. Where the project has recorded nobody, the Owner is whoever instructed the Practitioner, and Escalation goes there. One limit applies to that default. The default Owner is usually the person under the same deadline as the Practitioner, so a decision they take under section 4 to keep an Instance unfixed, Suppress, Baseline or remove a Rule MUST be recorded in the project record with its justification. That record MUST mark the decision as taken by a default Owner and state why nobody better placed was reachable, where the next reader can see who decided and why. Such a decision SHOULD be revisited by someone not under that deadline before the next release. A project that wants the separation section 4 describes names an Owner; the default exists so work is not blocked, not to certify that a second judgement was applied.

#### Escalation

Referring a decision to the Owner, whilst continuing with everything that does not depend on it.

#### Toolchain

Whatever a project assembles to run its checks through: its Detectors and Runners, and the parts around them that route, list, record and resolve, from third-party, first-party and project-level parts in any combination. It is measured at the project level. What a Toolchain must offer beyond what each Detector in it offers is specified in the toolchain specification.

#### Conform

To satisfy every MUST of the relevant section 7 level, or of the companion specification being claimed. Partial satisfaction is not Conformance.

## 2. When the method applies

Defence Before Fix applies to a Defect when that Defect can be attributed to a pattern, style,
idiom or configuration that a Detector can be made to recognise.

When it can, building the Defence is not optional and MUST be attempted before the Defect is
fixed. This is the substance of the method rather than a preliminary to it.

When it cannot, the Defect is outside the method’s scope and is fixed conventionally. Not every
Defect is an Instance of a detectable pattern, and forcing a Rule where no pattern exists
produces Detectors that fire on innocent code, which is worse than having no Detector.

Attempt rather than pre-judge. The Practitioner MUST attempt to express the Class as a Rule
rather than deciding in advance whether it is expressible. Failing to write a Rule that satisfies
clause 3.1’s bounds is itself the evidence that the Defect is out of scope, and it is cheaper and
more reliable than a judgement made before trying. The conclusion that no pattern exists MUST be
stated in one sentence, naming at least two independent techniques tried at expressing the
Rule, in the vocabulary clause 3.1 uses for a search, and recorded where the project’s
other decisions are enumerable under clause 8.7, not only with the fix. It is the cheapest way
out of the method and the only one that would otherwise leave no trace; enumerating it is how an
Owner sees an Agent routing around the method, and naming the techniques is what lets
them judge whether the attempt was one.

There are three ways out of the method and they are recorded differently. No pattern exists: the
Defect is out of scope under this section, and only the sentence above is recorded. A pattern exists but the
language has no extensible Detector and a bespoke one is not practical: a Toolchain gap
under clause 3.2. A pattern exists, a
Detector exists, but the Toolchain lacks a mechanism the toolchain specification requires: a
mechanism gap under clause 3.2, and the Rule is still built. The attempt that separates the first
from the second is complete when the Practitioner has checked the Detectors the project already
runs and the language’s own Detector ecosystem for an extension point, and found none.

## 3. The method

Six clauses, in order. In brief, before the detail:

Clause
The Practitioner MUST
The record shows
Goes to the Owner under section 4

3.1
Name the Class the Defect belongs to, bounded both ways, after an independent search
The Class, the Hazard sentence, the two search techniques, the next wider Rule not built, whether a Runner check pins the reported behaviour
Whether the next wider Rule is built, and whether the Rule stays narrower than the search showed

3.2
Express the Class as a Rule in a Detector, never a test
The Rule, and any Toolchain gap that stopped a bespoke one
Whether a Class that could be defended is left undefended

3.3
Make the Rule fire, on the Instance or a Fixture, in a commit of its own
The red run, and the sentence behind every Narrowing
Any exclusion whose sentence cannot be written: that is Suppression

3.4
Sweep the whole codebase, record the count, then fix every Instance
The count, corroborated, and what was fixed by hand or by pattern
Any Instance left unfixed, and any Baseline

3.5
Make the Rule permanent and Blocking in the project’s own checks
The green run through the project’s entry point, and the recorded decision behind any Suppression
Removing or disabling the Rule, and any Suppression added to it

3.6
Print a terse Message with a stable Identifier that resolves to documentation versioned with the Rule
The Remediation docs
Nothing

The fourth column is what an Agent or other Practitioner MUST NOT decide alone, clause by
clause; section 4 states the full list and governs where the two differ.

Three of them turn on a judgement this specification deliberately does not close: whether code
carries the Hazard (3.1, 3.3), whether a search was comprehensive (3.1, 3.4), and how broadly to
draw the Class (3.1). Any threshold given here would be calibrated to one codebase, one team and
one generation of Toolchain, and would be wrong everywhere else.

Those judgements are settled at project level, not in this document. A project fixes its own
thresholds and parameters, in its configuration or in its Toolchain’s defaults, and where a case is
genuinely ambiguous it is raised, discussed and written down so the next person inherits the answer
rather than the argument. A project’s accumulated decisions become part of its Coverage in the same
way its Rules do.

A project MUST make those decisions discoverable, by the same means as its Defences, so that a
Practitioner arriving cold can find what has already been settled instead of guessing at it or
re-opening it. The burden is the project’s, not the reader’s: a decision that cannot be found by the
means clause 8.7 requires is, for the Practitioner’s purposes, a decision the project has not
recorded, and the paragraph below applies. The search is therefore bounded: enumerate the project’s
Defences as clause 8.5 requires them to be enumerable, and whatever is reachable from there is the
record. Nothing further is owed before concluding that nothing is recorded.

Where the project has recorded nothing, the Practitioner is not blocked. Proceed on the
examples below, state the Calibration assumed, and record it with the Remediation docs
for the Defence being built, which clause 3.6 already requires to exist, to ship with the project
and to be reachable by a stable Identifier. That statement becomes the project’s first recorded
decision on the point, and the next Practitioner inherits it.

A project MAY of course keep these decisions somewhere else and say so. The default above exists
so that a Practitioner who finds no project convention still has one, because “the project
decides” and “the project has decided nothing” would otherwise combine into a deadlock. What is
never acceptable is assuming silently, since a Calibration nobody knows was chosen cannot be
corrected.

Worked examples of the three, to calibrate against:

Judgement
Too little
Too much

Hazard
Only counting things that crash. Error hiding and code nobody can safely change are Hazards too.
Counting every stylistic preference, so the Rule defends taste rather than the codebase.

Comprehensive
One text search for the exact token from the reported Defect, then stopping.
Auditing the whole system by hand before writing a Rule at all.

Class
A Rule matching the variable name in the original bug report.
A Rule matching every use of the language feature the bug happened to involve.

### 3.1 Attribute the defect to a class

The Practitioner MUST first establish what Class the Defect belongs to. The question is not
“what went wrong here” but “what kind of thing is this an Instance of”.

In order, this clause is five steps, each detailed below:

- Name the Class as a pattern, and write the one sentence that says what Hazard it carries.

- Search the codebase for other Instances by at least two independent techniques, chosen and
run before the Rule is run against the codebase, until the last technique adds nothing.

- Widen the Class if the search found Instances the Rule would miss; narrow it if the
Rule would match code that does not carry the Hazard.

- Where the Class stays at the reported Instance, name the next wider Rule and why it
was not built.

- Record all of that, the five things listed at the end of this clause, before clause 3.2.

A worked example. The Defect: a currency conversion’s error was caught and its empty result
used as a total. Step 1 names the Class “a caught error whose call’s result is then used as if
the call had succeeded”, with the Hazard “silent wrong output”. Step 2 searches twice: a text
search for every catch in the codebase, read for whether the result is used afterwards, and a
reading of every caller of the fallible conversion and payment functions; the second finds two
Instances the first missed, so a third technique, asking the team which other calls fail
quietly, is run and finds nothing new. Step 3 keeps the Class as named because the Rule
would catch all four. Step 4 names the wider Rule, “any caught error that is not rethrown or
reported”, and records that it was not built because most of the codebase’s catches are
legitimate and the Owner has not decided whether that is a Hazard. Step 5 writes the four
things down.

A Defect usually belongs to several overlapping Classes at different levels of abstraction, and
choosing between them determines the Rule, the Instance count and the scope of the remediation.
Two bounds apply, and both are checkable during the work rather than matters of taste:

- Lower bound. If the Rule catches only the originating Instance, the Class is probably drawn
too narrowly and MUST be widened, unless the independent search below has found no other
Instance and the Practitioner records that the Class is genuinely singular today. A
Rule that matches exactly one thing is an Instance wearing a Rule’s clothes.
A Rule drawn to the exact value or name found in the Defect is the same Narrowing however
it is spelt, and where it stays because the search found nothing wider, the record MUST also name the next
wider Rule, the one with the Instance’s distinguishing detail dropped, and state why it was
rejected. That rejection is tested as a Narrowing is under clause 3.3: a sentence stating why the
Hazard cannot arise in the code the wider Rule would add, confirmed by search, with uncertainty
routed upwards under section 4.

- Upper bound. If the Rule matches code that does not carry the Hazard, the Class is drawn
too broadly and MUST be narrowed. False positives destroy a Defence’s credibility faster than a
missing Rule does. One report on code that does not carry the Hazard is enough; there is no
tolerated rate.

Both bounds measure breadth within one level; the level itself is a separate question, answered
against the report.
Where the Defect was reported as a behaviour, a check that reported clean having run nothing, a
process that stopped before its work, the Class a Detector can read usually sits one level
below that Hazard: the mechanism of this Instance, not the failure the report opens with.
That Class is the right one to build, because no Detector reads “this check still produces
its signal”. It is not the whole answer. The record MUST state whether the reported behaviour is also
pinned by a check a Runner executes, under section 6, either one added with this remediation or
an existing one named, and where neither is offered, why not. A Class drawn at the mechanism with
the behaviour left unpinned defends the Instance thoroughly and the report not at all.

Resolve the lower bound by searching independently, not by judgement. The Rule is not the only
way to find Instances, and it is the least trustworthy one whilst it is still unproven. Search for
other Instances by other means, whether that is a text search, reading the code, or asking someone
who knows the system, and, once the Rule exists under clause 3.2, confirm it catches what those
searches found. That confirmation is not one of the techniques.

That search MUST be a comprehensive one, carried out by a person, model or Agent competent to
carry it out. No fixed technique is prescribed, because what is comprehensive depends entirely on
the Class and the codebase. What is not acceptable is a cursory look that exists to discharge the
requirement, since this search is what the single-Instance conclusion and the Sweep count both
rest on, and a bad search validates a bad Rule silently.

The stopping criterion is saturation, not effort. Use at least two independent techniques, and
the search is complete when the last technique added found nothing the earlier ones had missed. A
second technique that turns up new Instances means a third is owed; a second that turns up nothing
new means the search is done. That is a test the Practitioner can apply and record without a
threshold, and it is the standard clause 3.4 refers back to.

Two techniques are independent when they would miss different things. A text search for the token
and a reading of the code paths that consume the value are independent; two text searches for two
spellings of the same token are one technique; asking someone who knows the system is a third. For a
Class defined by how code is spelt, writing the idiom the other ways it is commonly spelt and searching
the codebase for each of them is a technique, because a search for one spelling misses every other;
whether the Rule catches those spellings is the confirmation step, not the technique. The
Rule itself is never one of the techniques, because the search exists to check the Rule.
A clean run of the Rule is therefore not evidence of saturation either: “the Rule found nothing
the reading had missed” is one technique and a Rule run, not two techniques, and the stopping
criterion cannot be applied to it.
The record MUST name both techniques, chosen before the Rule is run against the codebase, and
MUST state what each found that the other could not have checked. A technique counts only if it does
not invoke the Detector under proof in any configuration and would exist unchanged had the
Rule never been written; a Sweep-shaped run of the Rule, however comprehensive it looks, is
never one of the two. Where a later technique shows that two earlier checks shared a blind spot, they
were one technique, and a third is owed.

That turns the single-Instance case into something checkable rather than a matter of taste. If an
independent search finds Instances the Rule missed, the Class was drawn too narrowly and the Rule
MUST be widened until it catches them. Fixing those Instances by hand does not discharge the
widening: they are still Instances the Rule missed, and where the Practitioner leaves the
Rule unwidened because the wider check is harder to build without False positives, that is
the Owner’s decision under section 4 and is recorded as one. If an independent search finds nothing
the Rule did not already have, then one Instance is a reasonable conclusion rather than an
assumption, and the Rule is correct as written.

What this clause leaves on the record, before clause 3.2 begins: the Class, spelt as a
pattern; the Hazard sentence; the two search techniques and what each found; the next wider
Rule that was not built, with the reason; and, where the Defect was reported as a behaviour,
whether a check a Runner executes pins that behaviour, or why not. A record missing any of the
five has not finished this clause.

Why: the Class is the unit of work. Everything downstream operates on it, so an error here
wastes all the effort that follows.

### 3.2 Build the net

The Practitioner MUST express the Class as a Rule in a Detector, and the Detector MUST read code
rather than execute it.

A test MUST NOT serve as the Detector. A test proves that one input produces one wrong output; a
Rule finds the pattern wherever it occurs, including in code nobody thought to test.

Where an off-the-shelf Rule or a tightening of existing configuration genuinely detects the
Class, using it Conforms. However, a Toolchain that supports only its own built-in Rules cannot
support the method in general, so a Conforming MUST allow bespoke custom Rules.
The Rules that matter most are tightly coupled to the project and carry project-specific
knowledge, both in the pattern they match and, importantly, in the Message they emit.

Any tool that reads code and reports pattern matches qualifies, whatever its category. Static
Detectors such as PHPStan, ESLint, mypy and Clippy are the usual instruments; so are custom AST
walkers, architectural fitness checks, and Detectors that inspect a change before it lands. These
are examples rather than a permitted list, and a Detector is not disqualified for being unfamiliar.

Where the affected language has no extensible Detector available, the Practitioner MAY build a
bespoke one: a program of the project’s own that reads code and reports matches of the Class, run
through the project’s own entry point like any other Detector. This is a last resort rather than
a default, because a Detector the ecosystem maintains is cheaper to keep and easier for the next
Practitioner to find, but a bespoke Detector is far better than none: the Class is defended,
and every clause of this method applies to the bespoke Detector unchanged, including the proof in
3.3, the enforcement in 3.5 and the Identifier and documentation in 3.6.

Only where a bespoke Detector is not practical either is the Class undefended. That is a
Toolchain gap and MUST be recorded as one, with the reason a bespoke Detector was not
practical, rather than treated as the Defect being out of scope. The distinction matters, because
the first is a decision somebody can revisit and the second quietly disappears.

A gap is recorded in the project record where the Toolchain defines one, as the
toolchain specification requires it to; only where it does not is the location the project’s choice, and
then the only requirement is that somebody deciding what to invest in the Toolchain would find
it. A gap recorded where nobody looks has been forgotten with extra steps.

There are two kinds of gap and they lead to different work. The language having no extensible
Detector and no practical bespoke one is the gap above, and the Class waits for one. The project’s Toolchain
lacking a mechanism the toolchain specification requires, such as a proving harness or an
Identifier resolver, is a mechanism gap, and it does not put the Class out of reach: the
Practitioner builds the Rule, uses the substitutes clauses 3.3 and 3.6 already allow, and records
the mechanism gap alongside it. A mechanism gap that is also a breach of the toolchain specification’s
own obligations, such as a Toolchain that cannot run its Defences on its own source, is recorded
against the Toolchain’s claim under section 7 as well, because that is the fact its Owner needs.
Where that record lives is the Toolchain’s own Conformance declaration, under the
toolchain specification’s clause 9.2, or the detector specification’s clause 8.1 for a Detector; a Practitioner who cannot write there reports it by the channel
section 4 names, as a blocked decision.

What happens next is not waiting. Once the gap is recorded, the Defect is fixed conventionally
under section 2, with its reproduction test, and the work moves on. What the record changes is the
Class, not the Defect: the Class is known to be undefended, and the next person to see an
Instance of it finds a decision to revisit rather than nothing.

Why: this clause is what distinguishes the method. Detection happens at the level of the
Class, using an artefact that can be pointed at the whole codebase, and it happens before
anything is fixed.

### 3.3 Prove the net by making the rule fire

A new Rule MUST be proven to fire before it is trusted. It is never the goal to write a Rule and
be instantly green.

This clause has three parts. Part A: the proof, a red run kept as a commit of its own. Part B:
Narrowing, which is the Practitioner’s to decide only when they can write down why the
Hazard cannot arise in what is excluded, and is Suppression for the Owner otherwise. Part C:
proving a Rule when the pattern is absent from the codebase, and what a Rule’s own code owes.

Part A: the proof.

Proving and sweeping are two questions, not necessarily two runs. Proving asks “does this Rule
work at all”, and the answer is pass or fail. Sweeping, in clause 3.4, asks “how much of this Class
is present”, and the answer is a count. A single execution of the Rule answers both, and no second
run is required. What matters is that the two answers are not confused with one another: a large
count does not make a Rule more proven, and a Rule that fired does not tell you the Sweep is
complete.

The proof MUST survive as a commit of its own. The Defence is committed with the originating
Instance still present, and the fix is committed after it. That first commit is the red run: it is
what a reviewer under section 7 checks out to reproduce the proof, and it is the only record that the
Rule fired on real code rather than on a Fixture alone. Where the Defence and the fix share a
commit, the red run can only be reconstructed by hand-reverting lines the reviewer has to guess at,
and the proof rests on that guess.
Surviving as a commit means a fresh checkout of that commit, followed by the project’s own declared
setup, reproduces the proof. Dependency installation and generation driven by files the commit does
carry, a manifest, a lockfile, are that setup. Anything else the proof depends on that version control
does not carry, an empty directory, an ignored file, an artefact placed by hand, is state the commit
does not contain, and a reviewer under section 7
reproduces from a fresh checkout rather than from the Practitioner’s working tree, so a
proof that passes only there does not survive.
Both commits MUST remain individually reachable in the history the reviewer inspects. A merge that
flattens them into one destroys the proof, so a project whose merge policy does that MUST keep the
Defence commit reachable by another recorded reference, a tag or the retained branch, or MUST NOT
claim the remediation Conforms. How the project merges is its own business under section 8;
what must survive the merge is not.

Part B: Narrowing.

The decision comes first, and it turns on one sentence. Can the Practitioner write down why
the Hazard cannot arise in the code being excluded? If they can, the exclusion is a Narrowing,
it is theirs to make, and they record that sentence. If they cannot, or are not sure, the exclusion
is a Suppression and belongs to the Owner under section 4. Doubt is Suppression. The test is
the Hazard, never the count. Two exclusions of the same Rule show the difference:

Excluded code
The sentence
Which it is
Who decides

A catch in test helpers that asserts on the caught error and returns it
“The result is the error itself, so it cannot be used as if the call had succeeded”
Narrowing
Practitioner

A catch in a nightly export, excluded because the export “hardly matters”
Cannot be written: the caught result is still used, so the Hazard is present
Suppression, referred under section 4
Owner

The sequence is: write the sentence; confirm it by search, the way clause 3.1’s search confirms
the Class, so that the excluded code is looked at and not assumed; record both. A sentence
that cannot be confirmed is a sentence that cannot be written, and the exclusion goes to the
Owner. Ask, for every exclusion, which row it sits in:

- If the excluded code carries the Hazard, the exclusion is Suppression and is forbidden to
the Practitioner, however many or few Instances it removes.

- If the excluded code does not carry the Hazard, the exclusion is precision and is required
by clause 3.1’s upper bound.

- If the Practitioner is not sure which, the exclusion is Suppression, and it goes to the
Owner with the doubt stated.

A Rule MUST NOT be narrowed because its Instance count is uncomfortably high. A high count is a
finding about the codebase, not a Defect in the Rule. Firing on more than the originating
Defect is success. A Rule that catches the reported Instance and forty-nine others has done
exactly what it was built to do, and the forty-nine are the reason the method exists.

Then the proof, which runs the other way round, and both ways. Where the change under proof is
that the Rule should stop firing on code that does not carry the Hazard, three things are shown:
the Rule firing on that code before the change, from a commit still reachable in history and to the
same standard as a new Rule’s red run; the Rule not firing on it afterwards; and a retained
Fixture on which it still fires afterwards, the case that motivated the Rule. Where the narrower
shape was chosen from the outset and no wider Rule was ever built, the before state is a Fixture
of the wider pattern the Rule does not catch, retained as the record of what was left out.

A Narrowing reduces the Practitioner’s own work, which is why it is not left to self-report
alone. The sentence is recorded with the Narrowing as part of the Rule’s Remediation docs;
the search confirms it. Code a Narrowing excludes MUST be searched to the standard of clause
3.1, and an Instance that search finds there disproves the sentence and reverses the
Narrowing. Every Narrowing MUST be enumerable by the
same means as the project’s Exceptions, so the Owner sees them in one place, and a
Narrowing that excludes more code than the Rule still covers MUST be reported to the Owner
as if it were a Suppression. The sentence remains the test of whether an exclusion is honest;
the search and the listing are what make a fluent dishonest one visible.
Where the Toolchain’s own listing shows the Narrowing with its sentence, that listing is
the record, and no separate prose is owed for it.

The sentence may turn out to be wrong. The method does not require the Practitioner to be
infallible; it requires the reasoning to be written down where the next reader, or the next
Defect, can test it. A Narrowing with a recorded reason is correctable. One without is
indistinguishable from a Suppression, which is why the sentence is the test and a percentage is
not.

Part C: proving when the pattern is absent, and the Rule’s own code.

Where the pattern is present, prove the Rule against it. At minimum the Rule MUST detect the
originating Defect. Where the Defect was found in code review rather than in production, the
pattern exists in the branch under review, so the Rule is written and proven there before the fix
lands.

Where the pattern is genuinely absent, prove the Rule another way. A Rule may legitimately be
green against the codebase: the branch that carried the pattern may have been rejected and
orphaned, the Instance may already have been fixed, or the Rule may be a purely proactive Defence
against a pattern that might occur but does not yet. In each of these cases the Rule MUST still be
proven, using Fixture code that demonstrates the pattern the Rule is meant to catch. That Fixture
SHOULD be kept as the Rule’s own test rather than deleted, so the proof re-runs whenever the Rule runs
instead of expiring the moment it succeeds.

A green run proves nothing unless the Rule was loaded. Before treating any run as evidence,
confirm the Rule was active in it, by enumerating the Defences that run was configured with or by
seeing it fire on a Fixture in the same run. A Toolchain analysing its own source with a
configuration that omits its own bundled Rules reports clean on every one of them, and both the
Practitioner and a reviewer have taken that for a pass.

A Rule about how code is written may match its own source. A Rule that forbids a construct in
Rule code will contain that construct, because it has to look for it. That match is not an
Instance: the construct there is the Rule’s subject, not its use, so the Hazard is absent and
clause 3.1’s upper bound requires the Narrowing. Exclude it as precisely as possible, write the
sentence, and keep a test that proves the exclusion reaches nothing else.

Rules are software, and SHOULD be built test-first like any other software. How practical
that is varies considerably between Detectors, some of which offer purpose-built Rule-testing harnesses
and some of which offer nothing, so this is a best-effort requirement rather than an absolute one.
Where a Detector makes Fixture-based testing impractical, an acceptance or smoke check that
demonstrates the Rule firing is an acceptable substitute.

Fixtures are part of the Rule and are versioned with it, under the co-location requirement in
clause 3.6. A Fixture is input to the Rule’s test, not part of the code the Defence enforces:
the Sweep excludes it under clause 3.4, and the enforced run does not report it, so there is no
circularity in a Fixture that deliberately fails the Rule it proves. Writing the Fixture is the Practitioner’s own decision under section 4, not something
to refer upwards.

Where they sit within the repository is the project’s business. Absent a convention, put them
where the project’s existing tests live, and where there are none, alongside the Rule - then say
which was chosen, as with any other Calibration under section 3.

Why: proving is the Rule’s own validation. A Rule that does not catch the Instance that
prompted it does not detect the Class it claims to, and shipping it would add a Defence that defends nothing
whilst defending nothing. This is the clause most easily skipped, because a green run feels like
success and looks like a clean codebase.

### 3.4 Sweep the codebase, then fix every instance

The Practitioner MUST run the Rule across the entire codebase and record the total Instance
count before fixing anything, and MUST then fix every Instance found rather than only the one
that was reported.

“Entire codebase” means everywhere the pattern can occur, and nowhere it cannot. For most
Classes that is a single language, because the pattern is a feature of that language, and sweeping
unrelated languages would be theatre. What the clause forbids is stopping at the package,
component or service that happened to report the Defect when the pattern plainly reaches further.
The question is where the pattern can exist, never where the bug was found.

Whether vendored dependencies, generated code and test Fixtures are in scope is the project’s
decision, and it SHOULD be a recorded one rather than an implicit one, because a Class that is
excluded silently is indistinguishable from a Class that was never swept. Where a project has
recorded no such decision, Sweep all first-party source in every language where the pattern can
occur, and exclude generated code and vendored dependencies, then record that as the decision.
First-party source is code the project maintains in its own repository; generated code is what a
build step produces from other source; vendored code is a dependency copied in rather than
installed. Modified vendored code is first-party, because the project now maintains it. The two
exclusions are not a judgement that such code carries no Hazard. Unmodified vendored code is
somebody else’s project, and an Instance found in it is reported upstream rather than fixed
in place; generated code carries an Instance only because its generator does, and the generator
is the first-party source the Sweep covers. An Instance the Practitioner notices in either
is recorded as a known Instance under section 4, not ignored.
A Rule’s own Fixtures under clause 3.3 are never Instances: they carry the pattern
deliberately, as the proof, and the Sweep count excludes them.

The count MUST be corroborated independently, to the standard set out in clause 3.1: a
comprehensive search by someone competent to make it. A Rule that is too narrow produces a small
count and a clean-looking Sweep, and nothing inside the Rule can reveal that.

Where the independent search finds Instances the Rule did not, clause 3.1 governs: the Rule was
drawn too narrowly and MUST be widened until it catches them. The two are not permitted to
disagree, and the search is the authority, not the Rule.

Each fix MUST address the Hazard rather than the Rule. Throw on the absent case, or propagate
the absence explicitly so the caller decides: whatever the correct behaviour turns out to be. What is
forbidden is a change that turns the Rule green whilst leaving the failure mode intact, and
suppressing the Rule at the call site, which is not a fix at all.

Supplying a default is usually the Hazard in another form, not a fix. A default makes the absent
case look present, and the failure moves downstream to where nobody expects it and nothing names it.
A default is a fix only where absence is a legitimate state whose meaning the code defines, and then
the default states that meaning rather than filling the gap with a placeholder. This is the same
test as clause 3.3’s Narrowing sentence and carries the same discipline: the Practitioner
MUST write down, with the fix, what the absence means and why the default is that meaning, and
where the sentence cannot be written the absence is an error and MUST be treated as one.

Repetition is not the problem. Where every Instance genuinely has the same correct answer,
applying that answer to all of them is right, and the fact that it looks mechanical is not an
objection. The requirement is that each Instance was actually examined and the same answer was
genuinely correct for it, rather than assumed correct because it was correct elsewhere. Where one
change is applied across many Instances, the Practitioner MUST record which were examined
individually and which received the change by pattern, and MUST examine a sample of the latter
large enough, given how much the surrounding code varies, that a wrong answer there would have
been seen. “All examined” with nothing behind it is a claim, not a record.

Fix them all. There is no count at which a Practitioner stops fixing. A Practitioner
stops only when the next Instance needs a decision they lack the authority to make, and section 4
says which decisions those are; a hundred Instances, or a thousand, is work rather than a
decision. A Baseline of the existing Instances, so that the Rule blocks only new ones, MAY
be adopted where fixing every Instance is genuinely unfeasible, and the scale at which that
becomes true is tremendous. No threshold is given here deliberately. Any figure would be
calibrated to the Toolchain of the moment rather than to anything durable, and the honest measure is
the size of the change rather than the hours it would take, since the hours depend entirely on what
is doing the work.

Under AI-assisted development a Baseline is almost never the right answer. The historical case
for baselining was the cost of human hours, and that cost has largely collapsed: an Agent can work
through hundreds of Instances at a price that made a Baseline unavoidable a few years ago. Reaching
for one now is usually a habit rather than a judgement. This specification stops short of
forbidding Baselines outright, and only just.

Adopting one is a decision for whoever owns the codebase, taken after fixing has genuinely been
attempted rather than on the strength of the Instance count alone. “Attempted” is the
Owner’s judgement on the Practitioner’s report, not a threshold the Practitioner applies:
the Practitioner fixes until stopped by a decision they cannot make, and reports what was fixed and
what remains. That report MUST state the count fixed, the count remaining, what stopped the fixing,
and what would have to be tried next, so the Owner judges a record and not an adjective. A
Practitioner executing this method does not have that authority - see section 4. A baselined project SHOULD reduce the
Baseline over time and MUST NOT allow it to grow.

Why: consistency across a codebase is fundamental, and the Sweep is where this method
delivers most of its value. In the published worked example the reported Defect was one of
twenty-three; the other twenty-two were bugs waiting to surface in different contexts, reported
by different customers, at different times. A project that knows about twenty-three Instances
and fixes one has produced a documented list of Defects it has chosen to keep.

### 3.5 Enforce permanently, and block

The Rule MUST become a permanent part of the project’s quality checks, and it MUST fail rather
than warn. Three things must hold for this clause to be met: the Rule is in the checks the
project runs to accept changes; it fails rather than warns; and every Suppression it carries is
covered by a recorded decision. A Rule that reports a violation without failing does not
Conform, and neither does a Rule whose green run depends on a Suppression that no recorded
decision covers, since the checks are then passing around the Instance rather than enforcing
against it.

Where those checks run, and what the project does when they fail, is out of scope. Continuous
integration, git hooks, branch policy and release process are the project’s own business; see
section 8. What this clause requires is that the Defence is permanent, applies to everyone rather
than to whoever remembers it, and produces a failure rather than a remark.

Removing a Rule, or adding a Suppression for an Instance, MUST be a recorded decision rather
than a silent edit, and belongs to the Owner under section 4, which governs. Where a Rule
carries a Suppression that no recorded decision covers, this clause is not followed until the
decision is recorded or the Suppression removed.

Enforcement is demonstrated through the project’s own entry point. Running the Detector
directly shows that the Rule can fire; it does not show that the project’s checks will run it.
The Practitioner MUST run the invocation the project uses to accept changes, over everything
that invocation covers, and see the Rule reported there. A Toolchain that wraps its
Detectors in its own command is asking for that command to be used, and a Practitioner
who bypasses it has proven the Rule and not the Defence.

For a Bundled defence, the project whose entry point demonstrates it is any project the
Toolchain is genuinely installed into, the Consuming project included, since that is
where the Rule will be enforced. A mechanism gap that stops the Toolchain running its own entry
point on its own source moves the demonstration to such a project; it does not weaken it. The
substitutes clause 3.2 allows, for proving under clause 3.3 and for resolution under clause 3.6, do
not extend to this clause: the demonstration here is through an entry point or it is not made. A
project created for the purpose, with the Toolchain installed into it from the source under
test, is such a project, so a Toolchain with no consumer yet is not excused.

Why: the purpose is that the mistakes of the past become structurally impossible to repeat, and
a Warning is not structure. A Warning is a suggestion, and suggestions decay under deadline
pressure, which is the condition under which the original Defect was written.

### 3.6 Make the failure message terse, and point it at real documentation

The failure Message MUST be terse, and it MUST carry a stable Identifier that resolves to
Remediation docs shipped with the project.

That documentation MUST state three things: what the Rule is about, why it exists, and how to
fix a violation correctly using the project’s preferred approach.

A Practitioner who finds that an existing Rule’s printed Identifier does not resolve records
it where clause 3.2’s gaps are recorded, naming the Rule and the Identifier, with no Rule build of
their own to attach it to. It does not block the remediation. Where the mechanism cannot resolve
Identifiers at all, it is a Toolchain gap and blocks the Toolchain’s claim under section 7
until fixed; where the mechanism resolves others and only this Rule’s documentation is missing, it is a
fault in that Rule’s Remediation docs, owned by whoever wrote the Rule, and bears on
the project’s claim rather than the Toolchain’s.

The split between the two is by job, not by length. The Message carries what was detected,
where, and the Identifier; it is read under interruption by somebody trying to get on with
something else. The documentation carries the reasoning and the remedy; it is read once, by
somebody who has decided to understand the Rule, and it is maintained as the project’s thinking
develops. Anything that would grow over time belongs in the documentation.

A Rule and its documentation are one artefact and MUST be versioned as one. They live in the
same repository and are committed together, or in a library the project depends on at a clearly
tracked version. A Rule carries knowledge specific to the project it defends, and its
documentation is where most of that knowledge actually sits, so anything that lets the two drift
apart destroys the value of both. The same applies to a Rule’s Fixtures under clause 3.3.

An external URL Conforms only where the project controls it and versions it alongside the Rule. A
link into a third-party wiki or a general article does not, because neither can be relied upon to
still describe this Rule.

Repository structure is left to the project. Where these artefacts sit, how they are foldered,
whether Rules are vendored or depended upon: none of that is this specification’s business. What
is required is that they move together.

The Identifier MAY be a Rule ID resolved by a command, an anchor in a documentation file, or a
URL. It MUST continue to resolve for as long as any released version can emit it, which is a
stronger requirement than surviving the current release. Where a Rule is redesigned such that its
meaning materially changes, a new Identifier SHOULD be issued and the old one SHOULD keep
resolving to an explanation of what became of it.

A Message that names a pattern without leading anywhere does not Conform. “Pattern X detected”
teaches nothing.

Why: the Message is read at the moment of failure, by someone who wants to get on with their
work, so it has to be short enough to read and specific enough to act on, whilst the reasoning
has to live somewhere it can be maintained and can grow. Splitting it this way keeps the Message
terse without losing the teaching, and the documentation becomes the project’s accumulated
engineering knowledge rather than a comment nobody revisits. The best custom Rules are
opinionated documentation encoded as automation.

## 4. Authority: which decisions belong to whom

The method is frequently executed by somebody who does not own the codebase, including an Agent
acting under instruction. This section states which decisions that person takes alone and which
they do not.

Decisions the Practitioner takes alone, without seeking approval:

- What Class the Defect belongs to, and where its bounds sit (clause 3.1).

- Which Detector to use and how to express the Rule in it (clause 3.2).

- How to prove the Rule, and what Fixture to prove it against (clause 3.3).

- What the correct behaviour is at each Instance, and therefore what each fix should be (clause
3.4).

- The wording of the failure Message and the Remediation docs (clause 3.6).

Decisions that MUST go to whoever owns the codebase:

- Adopting a Baseline, in whole or in part (clause 3.4).

- Suppressing an Instance, or removing or disabling an existing Rule (clauses 3.4 and 3.5).

- Accepting a known Instance as unfixed for any reason.

- Deciding that a Class will not be defended at all, where a Rule for it is achievable.

- Leaving unbuilt the next wider Rule that clause 3.1 required the Practitioner to name, where
it was rejected because no Instance of it exists today rather than because the Hazard cannot
arise there. The absence of an Instance is the Practitioner’s reason not to widen unasked; it
is not authority to exclude the extension, and recording it as a known gap does not change whose
decision it is. This does not reopen a Class whose bounds a Hazard sentence has settled, and
it reaches no further than the one wider Rule already on the record.

- Leaving a Rule narrower than an independent search under clause 3.1 showed it should be, where
the reason is that the wider check is harder to build without False positives rather
than that the Hazard is absent from what it would add. The Instances the search found are
fixed regardless; what stays with the Owner is the Class left partly undefended.

The dividing line is that the Practitioner decides how the Defence is built and the Owner
decides what the codebase is permitted to keep. An Agent MUST NOT Baseline, suppress or
knowingly leave an Instance unfixed on its own authority, whatever the Instance count turns out to
be.

The default position is that none of these are permitted at all. Suppressions, Baselines and
every other means of evading a Defence are not techniques with a threshold governing their use; they are
Exceptions to the method, and the standing answer is no. An Exception exists only where a human has
discussed it, agreed it and documented it for that project. Nothing an Agent concludes on its own
creates one.

Uncertainty is itself an Escalation trigger. Where the Practitioner is not confident that code
they are about to exclude is free of the Hazard, that exclusion is a Suppression and belongs to the
Owner, whatever it is called. This is deliberately asymmetric: Narrowing is the Practitioner’s
decision only whilst they are sure, and doubt routes it upwards. Without this, the Hazard judgement
in clause 3.3 would let a Practitioner suppress an Instance whilst never touching the clause that
would have escalated it.

Where the work is entirely Agent-driven, do the work. Fixing Instances is cheap now, and an
Agent that reaches for an Exception has almost always found a shortcut rather than a genuine
obstacle.

What to do whilst waiting. A decision awaiting the Owner MUST NOT stall the rest of the work.
The Practitioner completes everything within their own authority, reports the blocked decision
with the Instance count and what it would cost to fix, and leaves the Rule unmerged rather than
merged in a weakened form. Where the only thing pending is whether one matched case carries the
Hazard, the Rule MAY merge at full width with that case recorded as a known Instance
awaiting the Owner, enumerable under clause 8.7: the Rule is not weakened, the case is not
hidden, and the Practitioner is not pushed towards declaring that no pattern exists. Reporting a
Sweep of four hundred Instances and stopping is a useful outcome; quietly baselining them is not.

Report by whatever channel carries the rest of the Practitioner’s work: for an Agent, its
output to whoever instructed it. An Instance in code the Practitioner is not permitted to
change is reported the same way, as a blocked decision with its count, and is never a reason to
narrow the Rule so that it stops seeing it.

The Instance count alone never triggers Escalation. A large Sweep is work, not a blocked
decision. Stopping to report is what the Practitioner does when an Owner decision is genuinely
required, which means an Exception is being contemplated, or when they are uncertain whether an
exclusion carries the Hazard. It is not what they do because the number is uncomfortable. Five
hundred Instances with no Exception needed is five hundred Instances to fix.

A remediation MAY be delivered across several changes where the volume warrants it, provided the
Rule does not become Blocking until every Instance is fixed, since a Blocking merged over a
codebase that still violates it either fails continuously or has been weakened to avoid doing so.
No Instance may be knowingly left unfixed at the end without the Owner’s decision.

Why: without this, an executing Agent either stalls at the first judgement call it cannot
authorise or takes the decision unilaterally, and the second failure is much harder to notice than
the first. Both were observed in cold readings of an earlier draft of this specification.

## 5. Ordering the quality checks

Defence Before Fix presumes quality checks ordered as follows, and the ordering is enforcing rather
than advisory:

- Detectors - type checking, linting, custom Rules

- Automated tests - unit, integration, functional

- Build verification - services start, dependencies resolve

- Human acceptance testing - visual review, workflow validation

Detectors MUST run first, and a failure at that level MUST stop the levels below it from
being treated as meaningful.

This constrains the sequence of checks, not the infrastructure that runs them. How the project
expresses that sequence is out of scope, per section 8. It is a property of the project, not a step
in any one remediation: a Practitioner handling a Defect is not required to reorder the
project’s checks, and a project whose checks run in another order is a project that does not
Conform, which is a finding to record, not work to do on the way to a fix.

Why: a Detector is preventive and a test is diagnostic. A Detector reads every file, every
time it runs, so it cannot miss a file merely because nobody thought to write a test for it.
Failures at a lower level also produce confusing results at the levels above, so any other order
costs time diagnosing symptoms of a problem the first level would have named directly.

## 6. Relationship to test-driven development

Defence Before Fix neither replaces nor competes with TDD. They operate at different levels, and
a full remediation uses both: a test, executed by a Runner, pins the Instance; a Rule, evaluated by
a Detector, catches the Class.

Concern
TDD
Defence Before Fix

Operates on
The specific Defect
The Class the Defect belongs to

Artefact
A test
A Rule in a Detector

Proves correctness
For one behaviour, by executing it
For a pattern, by reading the code

Answers
“Is this bug fixed?”
“Can this kind of bug still exist anywhere?”

The specific Defect is still reproduced with a test and proven fixed, exactly as normal. What
this method adds is the phase before that work begins, in which the codebase’s permanent Defence is extended using the evidence the Defect has just supplied.

The name records the ordering. The Defence comes first, because once the fix has landed the
evidence is gone and the opportunity closes with it.

## 7. Conformance

Conformance is claimed at one of four levels. Partial Conformance MUST NOT be described as
Conformance.

A remediation Conforms if all six clauses of section 3 were followed for that Defect.

A Defence if it satisfies clauses 3.1, 3.2, 3.3, 3.5 and 3.6: it is drawn to a
Class within both bounds and not to the reported Instance, it is evaluated by reading code, it
was proven to fire against either the originating Instance or Fixture code, it fails rather
than warns, and its Message is terse and resolves to Remediation docs versioned alongside
it. A Defence can Conform whilst the Sweep is incomplete; what that describes is a
Conforming over a codebase with known Instances, which section 4 requires to be
recorded, not a Conforming remediation.

A Toolchain if it permits bespoke custom Rules, supports the ordering in section 5,
and satisfies clauses 8.1 to 8.5 and 8.7: the Practitioner can run it, the result reaches them in
the output they are reading, Identifiers resolve mechanically, documentation states the correct
construction, and both the Defences and the project’s recorded decisions can be enumerated. Clause
8.6 is a SHOULD and does not bear on Conformance, deliberately: it is the one clause that acts
before a mistake rather than after, so no failing run can prove it absent, and Conformance is
claimed only over what a run can prove. The toolchain specification names a
Toolchain that also satisfies it as Conforming with Agent support, which is the claim to
make when it is true. Those obligations fall in two documents: what each Detector the
Toolchain routes a Defence through must offer is stated in the
detector specification, and what the assembled Toolchain must add is stated
in the toolchain specification, which requires the first as its own opening clause,
carries the ordering in section 5 and the correct construction of clause 8.4 as clauses of its own,
and states the listing and the project record that clauses 8.5 and 8.7 require.

A project Conforms if its Defences and Remediation docs, and if its recorded
decisions under section 3 are discoverable. Nothing here constrains how the project runs its checks
or what it does when they fail.

Toolchain is stated in full in the detector specification
and the toolchain specification together, which give each of the obligations above as a
clause with its own reasoning, and add what a Detector and a Toolchain must provide so
that a project can meet its own. The summary here is normative and sufficient to judge a
Toolchain by; the companion documents are where a Detector maintainer and a
Toolchain author should work from.

A verdict on a remediation or a Defence MUST rest on reproduction, not on the report: the reviewer
reruns the Defence red at the commit that introduced it and green at the final commit, through the
project’s own entry point for accepting changes, and reruns the originating symptom against the fix.
Where the Rule was proven against a Fixture under clause 3.3, the red run is against the
retained Fixture. Where the originating symptom cannot be reproduced through the entry point,
an incident or an observation at production scale, the reviewer says so and verifies the red and green
runs alone. A verdict on a Toolchain or a project rests on the reviewer exercising the clauses
named above, not on the claimant’s report of having done so. A report that reads as Conforming
has not been shown to be.

A Toolchain MAY additionally audit its own Rules against clause 3.6, failing its own release if any
Rule fails something without resolving to Remediation docs. This is the strongest
available demonstration that the clause is honoured rather than asserted.

## 8. Operating a defence under AI-assisted development

This section is normative.

### The argument these clauses rest on

For a human developer, a failure Message that teaches is good practice. They may read it, may
internalise it, may ignore it, and which of those happens depends on their seniority, their
workload and how many times they have seen the Message before.

For an Agent, the failure Message is the entire remediation loop. It is consumed as instruction,
in the same turn, every time, with no fatigue and no seniority gradient. A Message that resolves
to documentation explaining the correct approach does not simply block the Agent, it redirects it,
and it does so identically on the thousandth occurrence as on the first.

That reframes the usual complaint about AI-written code. The difficulty was never that Agents make
mistakes, since people do too. The difficulty is that nobody built the channel to correct them at
the level of the Class rather than the Instance.

If the value of the method depends on that loop closing, then what closing it requires has to be
stated rather than assumed. The clauses below are what a Defence must do to be usable by an Agent
at all.

### Scope: this specifies a defence, not a pipeline

Continuous integration, git hooks, branch policy, review process and release management are out
of scope. How a project chooses to run its quality checks, and what it does when they fail, is
the project’s own business and no part of this specification.

What is in scope is the Defence itself: a Rule that reads code, the documentation that explains it,
and the requirement that the Practitioner can run it and act on the result. A specification that
told projects how to run their checks would be overreaching, and would be ignored for it.

### 8.1 The practitioner MUST be able to run the defence themselves

A Rule that only reports through infrastructure the Practitioner cannot invoke is not usable by
them, whatever it does for anyone else.

Why: an Agent that cannot check its own work against a Defence cannot iterate against it, so
the loop never closes in the turn where the mistake was made, which is the only moment it is cheap
to fix.

### 8.2 The result MUST reach the practitioner in the output they are already reading

The Detector’s own output, at the point of the work. Not exclusively a dashboard, a report artefact or
a summary elsewhere.

Why: a Message that teaches nobody, because nobody sees it, is the same as no Message.

### 8.3 The identifier MUST resolve without a human

By a command the Practitioner can run, a file they can read, or a URL they can fetch.

Why: clause 3.6 requires the Identifier to resolve. This requires it to resolve for the
reader, which for an Agent means mechanically. An explanation that lives in a colleague’s head
resolves for nobody at three in the morning either.

### 8.4 Documentation MUST state the correct construction, not only the prohibition

Explaining why the pattern is dangerous is not sufficient. The documentation has to show what to do
instead, specifically enough to act on.

Why: this is the difference between Blocking an Agent and redirecting it. A prohibition alone
leaves it to guess at the replacement, and it will guess.

### 8.5 A project’s defences MUST be enumerable

A Practitioner MUST be able to list what defends this codebase, and read each Defence’s
documentation, without triggering it first.

Why: an Agent arriving at a codebase has no colleague to ask and no memory of last time.
Without this, a project’s standards can only be learned by violating them one at a time.

### 8.6 A project SHOULD publish a summary of its defences suitable for an agent’s context

One terse line per Defence, stating the Rule as a standing instruction rather than as a failure
report, each linked to its full documentation. “Error hiding is forbidden” is the shape.

Why: everything else in this method operates after the mistake. This operates before it. A
summary small enough to sit in an Agent’s working context turns the accumulated Defences from a
series of ambushes into a description of how this project expects code to be written, and it costs
one table.

### 8.7 Recorded project decisions MUST be discoverable by the same means

The judgements section 3 delegates to project level, once agreed and written down, MUST be
reachable exactly as the Defences are.

Why: section 3 says a project’s accumulated decisions become part of its Coverage. Coverage
nobody can find is not Coverage, and every Practitioner who arrives after a decision will otherwise
re-open it.

## 9. Citation

Edmonds, Joseph. Defence Before Fix, version 1.0.1. First published 22 February 2026.
https://ltscommerce.dev

## Appendix A: Instructing an agent

Where an Agent is expected to follow this method, give it the clauses rather than the article.
This appendix restates sections 3 and 4; where the two differ, the sections govern.

When you find a Defect of any kind, do not fix it yet.

First work out what Class it belongs to: the pattern, style, idiom or configuration that allowed
it. Do not decide in advance whether that is possible, attempt it. If you cannot write a Rule
for it, say so and fix the Defect conventionally.

Write a custom Rule that detects the Class, in a tool that reads code rather than running it.
Draw it so that it catches more than the single Instance you started from, but never so broadly
that it matches code which does not carry the Hazard.

Do not trust the Rule as your only way of finding Instances. Search independently as well, by
text search and by reading the code, and check the Rule catches what you found by hand. Make that
search a thorough one rather than a gesture, because everything downstream rests on it. If your
own search turns up Instances the Rule missed, widen the Rule until it catches them; the search
wins, not the Rule. If it turns up nothing new, then one Instance is a supported conclusion rather
than a guess.

The Hazard is whatever harm the Class does, and it need not be a failure. Error hiding counts.
So does something merely sloppy that makes the code harder to reason about safely.

Prove the Rule fires before you trust it. It must catch the originating Defect. If the pattern
is not present in the codebase, because it was already fixed or because you are defending
against it pre-emptively, prove the Rule against Fixture code that demonstrates the pattern and
keep that Fixture as the Rule’s test.

Then run the Rule everywhere the pattern can occur, which usually means one language but never
just the component the bug was reported in, and report the Instance count. Catching far more
Instances than you expected is success, not evidence the Rule is too broad. Only ever narrow a
Rule to exclude code that does not carry the Hazard; never to make the number smaller.

Fix every Instance. Examine each one; where the same answer is genuinely right for all of them,
applying it to all of them is correct. Never satisfy the Rule whilst leaving the Hazard in place,
and never suppress the Rule at the call site.

You do not have the authority to Baseline, to suppress an Instance, or to leave a known Instance
unfixed, however large the count turns out to be. Those belong to whoever owns the codebase, and
the standing answer is no unless a human has already agreed and documented an Exception for this
project. If you hit one, finish everything else, then report the count and what fixing it would
take, and leave the Rule unmerged rather than merging it weakened.

If you are unsure whether code you want to exclude carries the Hazard, you are suppressing it, so
refer it upwards rather than deciding. Narrow only where you are confident.

Otherwise, just do the work. Fixing Instances is cheap for you, and reaching for an Exception is
almost always a shortcut rather than a real obstacle.

Make the Rule a permanent part of the project’s quality checks, failing rather than Warning. Write
its failure Message terse, carrying a stable Identifier that resolves to documentation shipped
with the project saying what the Rule is about, why it exists and how to fix a violation
correctly. Check you can run the Rule yourself and read its output, because if you cannot, nor can
the next Agent.

Only then fix the original Defect in the normal way, with a test that reproduces it.

## Changelog

Version
Date
Change

1.0.0
2026-09-08
Initial specification, formalising the method published on 22 February 2026. Revised before publication after three independent cold readers understood the method correctly and still could not execute its judgement calls.

1.0.1
2026-09-08
Clarity, no obligation changed: section 3 opens with a map of the six clauses; clause 3.1 opens with its five steps and closes with what it leaves on the record; clause 3.3 is in three named parts and its Narrowing part opens with the decision. The header and the terminology entries for Detector, Toolchain and Conform name the detector specification 1.0.0 alongside the toolchain specification 0.2.0, and Conform extends to the companion specification being claimed. Accepted under ACCEPTANCE.md.

Method specification 1.0.1, detector specification 1.0.0 and
toolchain specification 0.2.0, published 8 September 2026. Source and history at
github.com/Defence-Before-Fix.

Defence Before Fix (DBF) was coined by Joseph Edmonds of
Edmonds Commerce. US spelling:
Defense Before Fix.
Licensed under CC BY 4.0.