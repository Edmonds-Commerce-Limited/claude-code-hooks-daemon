---
source_url: https://defence-before-fix.github.io/
fetched_at: 2026-09-10T07:45:16.459448+00:00
fidelity: converted
source_sha256: 487f94c7996f15da009ac069e4db600e023497f69e241c6a634026b0582464bd
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

By Joseph Edmonds of
Edmonds Commerce. First published 22 February 2026.

# Defence Before Fix (DBF)

Defence Before Fix (DBF) is a phase that runs before a defect is fixed. Rather than dropping
straight into remediating the specific instance in front of you, you first treat that instance
as evidence of a class, and you build the automated defence that detects every occurrence of
that class across the whole codebase. The defence is only trusted once it has been seen to fire.

A bug you have just found is a confirmed, in-production example of a pattern that actually hurt
you, and that is exactly the evidence you need in order to write a good detection rule. The
moment you fix the line, the evidence is gone. This method asks you to hold on for a moment and
build the net first, then go red on the bug that sent you looking, then sweep the codebase and
find out how many more there are, and only then fix them all. The
primer tells that story at reading pace; the specification below is the precise
version.

## The method, in six clauses

- Attribute the defect to a class. Not “what went wrong here” but “what kind of thing is
this an instance of”, within a lower bound and an upper bound that are both checkable.

- Build the net. A rule that reads code, in whatever detector the toolchain offers, bespoke
where nothing off the shelf will take it.

- Prove the net by making the rule fire. Red before green, on the originating instance,
committed before the fix.

- Sweep the codebase, then fix every instance. The count is the finding; the fix addresses
the hazard, not the rule.

- Enforce permanently, and block. Through the project’s own entry point for accepting
changes, failing rather than warning.

- Make the failure message terse, and point it at real documentation. Versioned with the
rule, resolvable from the identifier as printed.

## The specifications

Document
What it is
Version

The method specification
Normative. What a practitioner does when a defect is found.
1.0.1

The detector specification
What a tool that reads code must offer so that a rule can be written, proven, run and resolved in it.
1.0.0

The toolchain specification
What a project’s assembled tooling must offer beyond its detectors, measured at the project level.
0.2.0

Primer
The short introduction.

Provenance
Who coined the term, when, and what is and is not claimed.

Changelog
Changes to each document, versioned independently.

The method specification is the source of truth for what the method is. Where anything else
describing DBF disagrees with it, including the article in which the term was first
published, the specification is correct. The three documents are versioned independently, so a
detector or toolchain clause can be added without reissuing the method.

If you maintain a linter or a static analyser, the detector specification is the one addressed to
you: what a tool that reads code has to offer so that a rule can be written, proven, run and
resolved in it. If you maintain a QA pipeline, or assemble one for your own project, the toolchain
specification is the one for you: what the assembled tooling adds beyond its detectors, listing,
the project record, resolution and self-audit, measured at the project level because that is where
it counts.

## Tools that implement it

- php-qa-ci, the PHP toolchain

- ts-qa-ci, the TypeScript toolchain

Each records the toolchain specification version it conforms to, in its own manifest, and each
was audited against every clause through its own commands before the claim was made. Both were
also the subjects of the execution tests that hardened the method specification before it was
published: real defects, found in the tools themselves, taken through all six clauses.

## The article

The term was first published on 22 February 2026 in
Defence Before Fix: Preventing Bug Classes with Static Analysis,
which walks through a worked example in which the reported defect turned out to be one of
twenty-three. The article’s date is what establishes priority on the coinage; the specification
here is what the method now is.

## If you are an agent

DBF is written to be followed by agents as much as by people. Read the project prompt, raw markdown generated from the
specification’s appendix on instructing an agent: the method in the form to follow when you find
a defect, where the raw documents are, what a conforming toolchain gives you, and how a project
declares the version it follows. llms.txt indexes everything on this site, and every
document is available as raw markdown under /raw/.

## Source and licence

The documents live at
github.com/Defence-Before-Fix,
with their full history, and are checked in CI by the repository’s own defence, spec-qa.py.
They are licensed under
Creative Commons Attribution 4.0 International.

Coined by Joseph Edmonds of
Edmonds Commerce. US spelling: Defense Before Fix.

Method specification 1.0.1, detector specification 1.0.0 and
toolchain specification 0.2.0, published 8 September 2026. Source and history at
github.com/Defence-Before-Fix.

Defence Before Fix (DBF) was coined by Joseph Edmonds of
Edmonds Commerce. US spelling:
Defense Before Fix.
Licensed under CC BY 4.0.