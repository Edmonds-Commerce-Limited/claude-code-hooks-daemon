---
source_url: https://defence-before-fix.github.io/DETECTOR-SPEC.html
fetched_at: 2026-09-10T07:45:18.695477+00:00
fidelity: converted
source_sha256: 27de8f40380fa9448def102c05ae2d74d802ac3b0ec69aa6be25ba43556dffb9
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

# Defence Before Fix: Detector Specification

Version: 1.0.0, published 2026-09-08
Companion to: the method specification, version 1.0.1, and the toolchain specification, version 0.2.0
Author: Joseph Edmonds, Edmonds Commerce
Coined: 22 February 2026, in the original article

## 1. What this document is for

The key words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT and MAY are to be interpreted as
described in RFC 2119.

The method specification states what a Practitioner does when a
Defect is found. This document states what a Detector must offer so that they
can do it: write a Rule, prove it, run it and resolve what it prints. It is addressed to
whoever maintains a Detector, which the method specification defines as a tool that reads
code without executing it and reports occurrences of a pattern.

A Detector is one part of a project’s Toolchain, and this document judges it
on what it offers alone. What the assembled Toolchain of a project must add on top, the
Project record, the listing of active Defences and the
governance of Suppression, is stated in the toolchain specification.
The two are separable because they are built by different people: a Detector is authored once
and installed into projects its maintainer will never see, whilst governance is decided by each
project for itself. A document that asked a Detector to enforce a project’s governance would
fail every Detector in use and would not make any project better governed.

The governing principle: where the method specification requires a Practitioner to do
something with a Rule, a Conforming MUST make that possible
without the project building the mechanism first. A Detector that leaves the project to
construct the means has moved the obligation rather than met it.

## 2. Terminology

Terms from the method specification carry over unchanged. Every capitalised term links to its
definition; the ones this document leans on most are, in short:

Term
In one line

Detector
A tool that reads code without executing it and reports what it finds

Rule
One check a Detector evaluates

Identifier
The stable name printed with a finding that leads to its documentation

Practitioner
Whoever is doing the work, a person or an Agent

Toolchain
Everything a project assembles to run its checks through, Detectors included

Suppression
Making a finding go away without fixing it

Baseline
A recorded set of existing findings a Rule is told to ignore

These are additional.

#### Rule author

Whoever writes a Rule. May be the Detector’s maintainer, a Toolchain’s maintainer or the project that runs it.

#### Bundled rule

A Rule the Detector ships, or fetches on the Practitioner’s behalf from a source the Detector’s maintainer controls. Its Rule author will never see the codebases it runs in, so everything a Practitioner needs in order to act on it has to travel with it.

#### Harness

The route by which one Rule is run against supplied code and its findings observed, without the project’s own test suite and without every other Rule running alongside it.

The distinction between a Bundled rule and a project’s own Rule matters throughout.
The Detector owns the documentation of the first and can be held to shipping it; it cannot
know the documentation of the second, and what it owes there is the mechanism that lets the project
attach its own.

## 3. The division of responsibility

Each mechanism the method needs has two halves. Stating only one of them is what produces a
Detector that is nearly usable.

Requirement
The Detector MUST provide
The Rule author supplies

Bespoke Rules
The authoring and registration route
The Rules

The red proof
A Harness
The Fixture and the red run

Running the Rule
A local invocation, including subsets
Running it

The Identifier
A place to carry it, and printing it with every finding
Choosing it once

Resolution of a Bundled rule
The lookup, and the documentation, on disk
Nothing

Resolution of a project’s own Rule
The Identifier printed unaltered
The documentation and, with the Toolchain, the lookup

Inline Suppression
A route the project can detect or disable
The decision whether to forbid it

Read down the middle column and the shape of a Conforming is already
visible. Read across any row and the failure mode is visible too: either half alone leaves the
Practitioner stuck.

## 4. Authoring rules

### 4.1 The detector MUST support bespoke rules written by the project that runs it

Configuration of an existing Rule set is not sufficient. The project must be able to express a
pattern the Detector’s authors have never anticipated, and register it so that it runs with
the same standing as a Bundled rule.

Why: the method turns a specific Defect into a Class, and the
Classes that matter most to a project are the ones peculiar to it. A Detector offering
only a fixed catalogue can defend against the industry’s known Hazards and none of the
project’s own, which is the half that carries its institutional knowledge.

### 4.2 The detector MUST provide a harness that runs a single rule against supplied code

A Harness reports, for a given input, whether the Rule fired and what it printed, without
executing the project’s own test suite and without the other Rules obscuring the answer.
This applies to every Rule the Detector runs, bundled or bespoke; a
Detector failing 4.1 is graded here on its Bundled rules.

Why: clause 3.3 of the method specification requires the Rule to be proven by making it go
red. A Practitioner who can only observe a Rule’s behaviour by running every
Rule over the whole codebase cannot demonstrate that a Rule fires on the pattern rather
than on something incidental.

### 4.3 The detector MUST allow a rule to carry a stable identifier, and MUST print it with every finding

The Identifier MUST be stable across releases and MUST NOT be derived from the Rule’s
file path, Class name or position in a configuration file. The Rule author chooses it
once. The Detector MUST print it, unaltered, alongside every finding the Rule
reports, in its default output and in every machine-readable format it offers. A prefix the
Detector adds from the invoking directory or the Rule’s location is derived from
the file path. A namespace the Rule author assigns once in configuration is not.

Identifier
Where it comes from
Stable?

proj.no-raw-sql
Written once by the Rule author in configuration, printed as is
Yes

LM-0107
Assigned once by the Detector’s maintainer at the Rule’s first release
Yes

rules/no-raw-sql
Produced from where the Rule’s file sits; changes when the file moves
No

NoRawSqlRule
The Rule’s Class name; changes when the Rule is renamed
No

rule 7
The Rule’s position in a configuration file; changes when one is inserted
No

Why: the Identifier is the only string that reaches the Practitioner and the
only key their lookup can use. An Identifier that changes when a Rule is renamed
silently breaks every reference to it, including references written down by people who have left.
An Identifier the Detector carries but does not print is one the
Practitioner was never given.

### 4.4 The detector SHOULD enforce 4.3 with a rule of its own

A Rule over the Rules, failing any Rule that reports without a stable
Identifier.

Why: this is the method applied to the Detector itself, and it is cheap. The worked
example is php-qa-ci’s RequireRuleIdentifierConstantRule, a Rule hosted in PHPStan by a
Toolchain built on it: it rejects a magic-string Identifier and names the
constant to declare instead. Nothing about it needed to live outside the Detector.

## 5. Reporting

### 5.1 The detector MUST be invocable by the practitioner, locally, with no infrastructure

Why: method specification clause 8.1. An Agent that cannot check its own work cannot
iterate against a Defence, so the loop never closes in the turn where it is cheap to close.

### 5.2 The detector MUST support invocation over a subset, at minimum a single file

Why: 5.1 is satisfied in principle by a whole-codebase run and defeated in practice by one.
Checking a single edited file has to be fast enough to do on every edit, or it will not be done on
any.

### 5.3 The result MUST reach the practitioner in the output of the command they ran

Where the Detector writes fuller detail elsewhere, the invoked command’s own output MUST
carry both a usable summary and the location of the remainder.

Why: method specification clause 8.2. A report the Practitioner has to go and find is a
report that arrives after the decision it was meant to inform.

### 5.4 A finding MUST NOT be reportable only through a hosted service, licence tier or CI-only mode the practitioner cannot invoke locally

A finding that the Detector reports only through a hosted service, a licence tier or a
continuous-integration-only mode the Practitioner cannot invoke locally does not
Conform, whatever the same Rule reports there.

Why: a Rule that fires only in an environment the Practitioner has no access to
teaches nobody anything and blocks them anyway, which is the worst combination available.

## 6. Resolving an identifier

### 6.1 The detector MUST provide a mechanism that resolves a printed identifier to its documentation

Two cases, by who wrote the Rule:

The Rule
Who supplies the documentation
What this clause asks of the Detector

A Bundled rule
The Detector
Resolve the Identifier, presented alone, to that documentation

The project’s own
The project
Print the Identifier unaltered; the lookup is the Toolchain’s to give

In both, the mechanism is keyed on the Identifier exactly as printed. A command, an index
file or a URL are all acceptable forms. Each case in turn:

For a Bundled rule, the Detector supplies the documentation and the
lookup, and clauses 6.2 and 6.3 say where. The mechanism MUST resolve an Identifier
presented alone, because the reader who needs it most has the Identifier from a log, a
ticket or a colleague and not the Message. A Message that carries its own
documentation path resolves that Message, not the Identifier.

For a project’s own Rule, the Detector cannot know the documentation, so what
it owes is the half it can give: the Identifier printed unaltered under clause 4.3, and no
transformation of it. Where the Identifier is itself a URL, as method clause 3.6 allows,
the Detector prints that URL and has done what this clause asks. What this clause forbids is
a documentation path printed alongside a shorter Identifier that cannot be looked up on its
own. The lookup for such
a Rule is an obligation on the project’s assembled Toolchain, under clause 4.2
of the toolchain specification, and a Detector that offers it as well has
gone further than this clause asks.

Why: method specification clause 8.3 requires the Identifier to resolve without a human.
An index keyed on anything else does not resolve it. This is the most commonly failed clause in this
document and it fails in a specific way: documentation exists, is genuinely good, and is keyed on the
Rule’s Class or file name, which is a string the Practitioner was never
given. The lookup they can actually perform is the only one that counts.

### 6.2 Resolution of a bundled rule’s identifier MUST work from the installed copy, without network access

Why: an Agent working offline, behind a proxy, or against a URL that has since moved needs
the answer to be on disk. A dependency the project already installed is on disk by definition. A
catalogue on the Detector’s website, however complete, is the right documentation in the wrong
place.

### 6.3 A bundled rule’s documentation MUST ship with the rule, at a version tracked together

Every Identifier a Bundled rule can print MUST resolve, under clause 6.1,
to a page in that shipped documentation. One Identifier that does not resolve fails this
clause, however many others do. A page per Identifier satisfies this; a page per family of
Identifiers MAY be used instead, under clause 6.5.

Why: method specification clause 3.6. A Bundled rule travels into codebases its author
will never see. If its documentation lives only in the Detector’s repository or on its
website, then every project that installs it is one link rot away from a Rule that blocks
without explaining.

The failure to guard against is not the absent document but the dangling one: a reference to
documentation that was planned and never written is worse than no reference, because it consumes
the Practitioner’s attention before failing them.

### 6.4 The detector SHOULD fail its own release if a bundled rule lacks resolvable documentation

An automated check over every Identifier a Bundled rule can print, applying the
family list or pattern of clause 6.5 where one is used, that blocks the release when any of them
lands on no page.

Why: clause 6.1 is the clause most easily believed to be satisfied whilst being broken, because
the documentation is written by the same person who wrote the Rule and its absence is
invisible from the inside. Where the Detector is shipped inside a Toolchain,
the toolchain specification’s self-audit makes this check a MUST for the Toolchain; a
Detector released on its own is asked for it as a SHOULD because the same Class of
Defect, a Rule that blocks without explaining, is detectable mechanically there too.

### 6.5 One page MAY document a family of identifiers, and SHOULD name its members so a check can confirm them

Where several Bundled rules share a prefix, one page MAY document them all. Such a page
SHOULD let the check clause 6.4 asks for confirm that each member resolves to it. Two forms do
that and one does not:

The page
A check can confirm each member?

Lists every full Identifier in the family, LM-0100, LM-0101, and so on
Yes

Carries a regular expression the check can run, ^LM-01[0-9]{2}$, matching every member and nothing else
Yes

Says in prose that everything under LM-01 is documented here
No: a person can infer it, a check cannot

The list or the regular expression lives in the installed file, since clause 6.2 requires
resolution to work from the installed copy, not only in a rendered web page.

Why: a family page is a convenience for the author, and the cost of it must not fall on the
check. A page that a person can see covers LM-0107 but a check cannot leaves clause 6.4 with
nothing to run.

## 7. Suppression

### 7.1 A detector MAY offer an inline suppression route, but MUST make it detectable or disableable

An inline ignore comment, a per-line directive and a generated Baseline are all such
routes. The Detector MAY ship them. For each one it MUST do at least one of two things, and either
alone satisfies this clause: make the route disableable by configuration; or make the route
detectable, by a Rule the project can write in the Detector itself or by a mechanical check
the Detector documents. Either lets a project which decides to forbid the route enforce that
decision. A route that can be neither switched off nor seen does not Conform.

Why: the method specification’s position is that Suppression is an Owner
decision under its clause 3.4 and section 4, and an Owner cannot decide something they are
never shown. The Detector is not the Owner and does not know the project’s
governance, so it is not asked to enforce it; what it is asked is not to hide the route. Every
Detector in wide use ships an inline ignore, and a clause that forbade them would fail all of
them without governing any project better. Whether the route is forbidden is the project’s decision,
enforced through its Toolchain under clause 4.3 of the toolchain specification.

### 7.2 An inline suppression route SHOULD require a written reason

The Detector SHOULD reject, or be configurable to reject, an inline Suppression
that carries no reason, and SHOULD NOT supply a default one, including each entry of a generated
Baseline.

Why: a Suppression without a reason is indistinguishable from one nobody would defend,
and the person who could tell them apart is usually gone. Requiring the sentence costs the author a
minute at the moment they have the reason in mind, and it is the only thing that makes the
Suppression reviewable later. PHPStan’s reportIgnoresWithoutComments is the shape of it.

## 8. Conformance

A Detector if it satisfies every MUST in sections 4 to 7.

Partial Conformance MUST NOT be described as Conformance. A Detector
that satisfies most of this document is in a normal and respectable condition; it is not
Conforming, and describing it as such removes the only value the word has.

This document defines one level. The clauses of the method specification’s section 8 that reach
beyond what sections 4 to 7 here already secure, the listing of active Defences and the
summary for an Agent’s context, are obligations on a project’s assembled Toolchain
and are stated in the toolchain specification, so there is no separate Agent-support level
for a Detector.

### 8.1 A maintainer MAY declare the version of this document the detector conforms to, and the declaration records known gaps

The declaration is machine-readable, in whatever form the Detector’s ecosystem uses to
record dependencies. The same declaration is where a gap against this document is recorded once it is
known: a Detector that has learnt, from its own checks or from a Practitioner’s
report under the method’s clause 3.2, that it fails a MUST in sections 4 to 7 MUST record that gap
alongside the version it declares, in the same file or one it names. A declaration with a non-empty
gap record is a statement of where the Detector stands and is not a claim of
Conformance.

The declaration is optional. It is how a maintainer claims Conformance; it is not a
condition of it. A Detector that predates this document, or whose maintainer has never read
it, MAY be graded Conforming on evidence by anyone who exercises the clauses above against
it, and a verdict on any Detector, declared or not, rests on that exercise and not on the
claim. A declaration tells the reader what the maintainer believes and what they know to be missing;
the reader still runs the Harness.

The shape is illustrative rather than prescribed. In a Composer manifest:

```
"extra": {
  "defence-before-fix": {
    "method": "1.0.1",
    "detector": "1.0.0",
    "toolchain": null,
    "known-gaps": []
  }
}

```

In a package.json, the equivalent is a top-level defenceBeforeFix object with the same keys. A
Detector that is not also shipped as a Toolchain leaves toolchain empty;
a project that ships both declares both. Each entry in known-gaps names the clause and states the
gap in a sentence.

Why: a Conformance claim in a README is a sentence; a claim in a manifest is a fact about
a specific installed artefact, checkable by anyone, including mechanically, and it fixes what
“Conforming” meant at the point the claim was made. Making the claim a condition of
Conformance, though, would mean a Detector with every mechanism in place could
never Conform until its maintainer had heard of this document, which grades the
maintainer’s reading rather than the Detector.

## 9. Relationship to the other specifications

This document adds no obligations to a Practitioner and relaxes none. Every clause here
exists to make a clause of the method specification achievable with a Detector in hand.

Where this document and the method specification disagree, the method specification governs. It
describes the method, which is the thing being specified; this describes one piece of the equipment.

The toolchain specification states what a project’s assembled Toolchain must offer beyond
what each Detector in it offers, and it requires every Detector a Defence
is routed through to Conform to this one. A Detector shipped inside a
Toolchain is measured here as a Detector and there as part of the
Toolchain; the two verdicts are separate and neither implies the other.

Nothing here requires a project to use a Conforming. A project can
Conform to the method specification on a Detector that Conforms to
none of this, at the cost of building the missing mechanisms itself. This document exists so that it
does not have to.

Method specification 1.0.1, detector specification 1.0.0 and
toolchain specification 0.2.0, published 8 September 2026. Source and history at
github.com/Defence-Before-Fix.

Defence Before Fix (DBF) was coined by Joseph Edmonds of
Edmonds Commerce. US spelling:
Defense Before Fix.
Licensed under CC BY 4.0.