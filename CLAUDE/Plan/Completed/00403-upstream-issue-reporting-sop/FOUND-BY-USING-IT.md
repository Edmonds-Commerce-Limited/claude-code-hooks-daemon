# Plan 00403: what only running the thing found

Three defects, none of which a passing test suite would have surfaced. Each has
a regression test now. Kept as a named document because the shared cause is
reusable and the individual findings are not obvious from the code.

## The shared cause

**The generator is correct in the environment it is DEVELOPED in and wrong in
the one it SHIPS to — and every test runs in the developing one.** That is why
all three were invisible to a green suite, and why running the finished thing
was the only thing that showed them.

## 1. The printed filing command had no `--repo`

The generator printed `gh issue create --body-file <report>`. In a self-install
that is correct and invisible. In a CLIENT project — the only place the
generator matters — `gh` takes the target from the working directory, so the
printed remedy files a hooks-daemon defect on the CLIENT'S OWN tracker.

Both halves failed in the same direction: the filing gate never engages either,
because it judges the repository a command TARGETS. `issue_report/upstream.py`
now holds the slug and builds the command, so the printed remedy and the gate's
comparison cannot drift apart.

## 2. The block-word list never reached `assemble_report`

`assemble_report` called `scrub_report` without the term list, so the free text
a reporter TYPES was the one surface with no backstop — and it is the only
surface the "collect nothing sensitive" design cannot reach, because those words
are not collected from the environment, they are written by a person.

## 3. `bin/hooks-daemon --version` does not exist

Three documents made it a verification step. Recorded as Plan 00405 N4 and
fixed there; all three now name `release-notes`, whose first heading carries
the installed version.

## A fourth, found the same way after the criteria were ticked

The `--web` fallback was justified in six places with "the form cannot be
submitted without ticking two acknowledgements". `--web` opens the CHOOSER, and
the free-text form deliberately has none — so the claim was true of the form a
defect reporter picks and false of the other. Corrected everywhere, and two
tests now pin the acknowledgement count to the forms themselves, which nothing
did before. See [DECISIONS.md](DECISIONS.md) for why the hole exists at all.
