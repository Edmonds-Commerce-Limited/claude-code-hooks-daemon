---
source_url: https://defence-before-fix.github.io/defence-before-fix-project-prompt.md
fetched_at: 2026-09-10T07:45:19.825911+00:00
fidelity: converted
source_sha256: 7a0f97d40eea12a518cf77d6cfff143683ca2d5c3843854a2c7a32cc43938441
licence: unreviewed
stale_after: 2026-12-09
fetch_method: agent-browser-lite-headless (accept-markdown)
---

# Defence Before Fix (DBF): project prompt for agents

You are working in a project that follows Defence Before Fix (DBF), method specification 1.0.1.
This file is generated from that specification and is the short form; the specification governs
where they differ. Read it once at the start of a task that involves fixing a defect.

## The method, when you find a defect

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
keep that Fixture as the Rule's test.

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

Make the Rule a permanent part of the project's quality checks, failing rather than Warning. Write
its failure Message terse, carrying a stable Identifier that resolves to documentation shipped
with the project saying what the Rule is about, why it exists and how to fix a violation
correctly. Check you can run the Rule yourself and read its output, because if you cannot, nor can
the next Agent.

Only then fix the original Defect in the normal way, with a test that reproduces it.

## Where the full documents are, as raw markdown

- Method specification 1.0.1: https://defence-before-fix.github.io/raw/SPEC.md
- Detector specification 1.0.0: https://defence-before-fix.github.io/raw/DETECTOR-SPEC.md
- Toolchain specification 0.2.0: https://defence-before-fix.github.io/raw/TOOLING-SPEC.md
- Primer: https://defence-before-fix.github.io/raw/PRIMER.md
- Provenance: https://defence-before-fix.github.io/raw/PROVENANCE.md
- Changelog: https://defence-before-fix.github.io/raw/CHANGELOG.md
- Index of everything: https://defence-before-fix.github.io/llms.txt (and https://defence-before-fix.github.io/llms-full.txt for all of it in one file)

The rendered site is https://defence-before-fix.github.io/. The US spelling, Defense Before Fix, is the same method; DBF is the short form of both.

## What to expect from the toolchain

A detector that conforms to the detector specification gives you: a way to write a bespoke rule
in the project; a harness that runs one rule against one file; a stable identifier printed with
every finding; and resolution of a printed identifier to its documentation. A project's toolchain
that conforms to the toolchain specification adds: resolution of the project's own identifiers
without network access; a listing of every defence active in the project, derived from the live
configuration, with the project's recorded exceptions in the same listing; the inline suppression
routes forbidden; and, where the owner has chosen to declare it, a manifest entry naming the
specification versions it conforms to. Use those commands rather than guessing. The two reference
toolchains and their commands are listed at https://defence-before-fix.github.io/tools/. If the project's toolchain lacks one of
these, say so in your report; that gap belongs to the toolchain's owner under clause 3.2 of the
method specification. If the detector itself lacks one of the four things a detector gives you, say
so in your report as a gap in the detector under the detector specification; use the toolchain's
wrapping where it closes the gap, and otherwise fix the defect conventionally as the method's
Appendix A allows and say why.

## How the project declares it

The project's manifest names the method specification version it follows and, for a toolchain, the
toolchain specification version, in the form its ecosystem uses for dependencies (for example
`extra.defence-before-fix` in composer.json or `defenceBeforeFix` in package.json), together with a
known-gap record that must be empty for conformance to be claimed. Do not add or change that
declaration yourself; report what you found.

## Citation

Edmonds, Joseph. *Defence Before Fix*, version 1.0.1. First published 22 February 2026.
https://defence-before-fix.github.io/
