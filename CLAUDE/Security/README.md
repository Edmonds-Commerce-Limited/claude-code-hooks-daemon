# Security register

The classes of defect this project has found in itself, and for each one the
**Defence** that keeps finding it.

Written by the security-review routines
([00001 full](../Routine/00001-security-review-full/ROUTINE.md),
[00002 delta](../Routine/00002-security-review-delta/ROUTINE.md)) and read by
anyone about to change a guard.

## Categories

| Category                                                        | Defence                                        | Detects                                                                                                                                                                                                      |
| --------------------------------------------------------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [authored path resolution](AuthoredPathResolution.md)           | `scripts/qa/check_authored_path_stat.py`       | A stat predicate on a joined path in the trees that resolve what an author wrote — `..` walked through the filesystem, so a missing intermediate directory reads as a missing target                         |
| [asymmetric sibling protection](AsymmetricSiblingProtection.md) | `scripts/qa/check_declared_invariant_pairs.py` | A site that re-derives, shortens or omits behaviour this codebase already implements correctly at a sibling site — asserted as a declared relation between the two, because neither side is wrong on its own |

**A category whose Defence cell is empty is the most important row in this
table.** It says a class of defect is known and nothing is watching for it,
which is strictly worse than not having looked — the register would then be
recording that the work was done.

## What this is

A register of **classes**, not a log of incidents.

The unit is a category: a description of what makes a defect belong to it, and
one Detector that finds every member. A single finding is an instance recorded
under its category, never a row of its own. That ordering is not tidiness —
it is the whole method. **Defence Before Fix**: the Defence lands before the
fix, every time, because a regression test proves one instance was fixed while
a Detector finds the class and keeps finding it.

So the first question a finding raises is not "how do I fix this?" but "what is
the class, and what would find all of it?". This register holds the answers to
the second question, which is the one that survives.

## What this is not

- **Not an incident log.** When something was found and by which run is in the
  routine's `RUNS/` ledger and in git. Dates do not belong here: this document
  describes the defences as they stand now, and a dated entry turns it into a
  changelog that nobody prunes.
- **Not a threat model.** It records what has actually been found, not what
  might exist. The full sweep's [check
  inventory](../Routine/00001-security-review-full/CHECKS.md) is where "what
  should we look for" lives.
- **Not a findings dump.** A finding with no category and no Defence is not
  finished being understood, and filing it here would make it look finished.

## Adding a category

Create `<CategoryName>.md` in this directory, add its row above, and give it:

```markdown
# Category: <name>

**Defence**: `scripts/qa/<detector>.py` — <one line: what it detects>

## The class

<What makes a defect belong here, written so someone can decide a new case
 without asking. A boundary that needs a judgement call every time is a
 boundary that will drift.>

## Why a review finds it and the test suite does not

<The tests pass and the defect is present. Say why. If this section is hard to
 write, the class may already be covered and this may not be a new category.>

## Instances

<One entry each: where it was, what it allowed, the commit that added the
 Defence, and the commit that fixed it — in that order, because that is the
 order they must have landed in.>

## What the Defence does not catch

<Every Detector has a boundary. An unstated one gets rediscovered as a new
 finding, and the register will not show that it was already known.>
```

The last section is the one people skip and the one that pays. A Detector with
an unwritten blind spot reads, to the next person, as complete coverage — and
the register's whole value is that a reader can trust what it says is covered.

## The obligation this carries

Every category in the table must name a Defence, and every Defence must be a
Detector in `scripts/qa/` wired into `run_all.sh` like any other check — not a
regression test, not a note, not a convention.

Both categories honour it. `authored-path-stat` is check 25 in `run_all.sh` and
`declared-invariant-pairs` is check 26; each is a Detector, each is also a step
in `llm_qa.py`, and each fails rather than warns.

**Nothing yet enforces that the NEXT one will.** A third category could name a
regression test as its Defence, or name nothing, and no gate would object. That
is recorded here rather than left implicit because an unenforced invariant in a
security register decays in exactly the way this whole plan exists to make
visible — and the honest place to say so is beside the invariant, not in a
backlog.

The second category also shows the obligation is not sufficient on its own. Its
Defence is wired in and failing correctly, and it covers **five declared pairs
out of thirteen known instances** — so "has a Defence" and "the class is watched"
are different facts, and only the category page's own blind-spot section carries
the second one.

That category records a third instance its own Defence does not catch, found
while the Defence was being built. Keeping it listed is deliberate: a register
that only recorded what its Detectors cover would describe the detectors, not
the defects.
