# Category: authored path resolution

**Defence**: `scripts/qa/check_authored_path_stat.py` — a stat predicate **or a
consuming call** applied to a joined path, anywhere in the trees that resolve
paths an author wrote, whether the join is at the call site or bound to a local
one statement earlier.

Index: [README.md](README.md). Found by
[Routine 00001](../Routine/00001-security-review-full/ROUTINE.md)'s check
`D-PATH`.

## The class

A path that an AUTHOR wrote — a markdown link target, a path quoted in a plan,
an `ssot-quote` marker's source — resolved by stat-ing or reading the joined
path.

Two distinct harms, and they need different fixes:

| Harm           | Cause                      | Fix                       |
| -------------- | -------------------------- | ------------------------- |
| Wrong answer   | `..` walked through the FS | normalise lexically       |
| Content oracle | target read with no bound  | establish **containment** |

The second is the worse of the two and was found second. A stat answers a
question wrongly; a read makes the daemon an oracle over whatever the path
resolved to. **Normalising does not fix the read** — it makes
`src/../../etc/passwd` resolve *faithfully* to a real file, which is not the
same as it being a file the daemon may open.

`Path.exists()` stats the path exactly as written, which makes `..` a
**filesystem** operation: every directory along the way has to exist for the
answer to be about the target at all.

```python
(Path("CLAUDE/Security") / "../Routine/x.md").exists()   # False
```

False whenever `CLAUDE/Security/` does not exist — even though
`CLAUDE/Routine/x.md` is sitting right there.

A defect belongs here when a path check answers a question about the *route* to
the target rather than about the target. The boundary is mechanical: if the
value being joined can carry a `..`, the site is in the class. Deciding whether
a particular value *actually* can needs data flow, so the rule does not try —
it applies to the whole of `docs_qa/` and `plan_qa/` and has no exemption
marker.

## Why a review finds it and the test suite does not

Every test for the affected check passed, because every one of them created the
file's directory first. That is the natural way to write a fixture, and it
makes the bug invisible: the hazard only appears when the containing directory
does **not** exist, which is a state a test has to construct deliberately.

The suite was not weak here. It was testing the shape it had been given, and
nothing in that shape suggested that the absence of a directory was a variable
worth varying.

The second instance failed the same way for a different variable. Every
quote-drift test pointed its `ssot-quote` marker at a source file inside the
fixture repository, because that is what a quote *is*. Nothing in the check's
own contract suggested that "where the source path lands" was a question at
all — the check was written to answer "does this quote still match", and the
read was infrastructure on the way to that answer. A test suite built from a
check's stated purpose will not probe the capabilities it acquired
incidentally, and reading any file on disk was such a capability.

**This is the generalisable lesson of the category**: both instances were
invisible because the fixture embodied the assumption that the defect
violates. Neither was a missing test. Both were missing *variables*.

## Instances

**The docs QA link resolver** — `docs_qa/checks/pointer_resolves.py`, plus four
sibling sites in `plan_qa/` converted with it.

What it allowed: a link to a file that exists was reported as dead. Because a
*new* dead link is graded BLOCK at the edit stage, the write was denied — and
no retry could succeed, since the directory only comes into being by the write
being allowed. Creating the first document in a new documentation directory was
impossible if it linked to a sibling with `../`. The denial named a dead link,
so a reader would go hunting for a typo in a path that was correct.

Found by hitting it: the first write of `CLAUDE/Security/README.md` — this
register — was refused.

- Defence: `20f5fe82`, committed deliberately red over 7 instances.
- Fix: `344ebf16`.

The sweep found 7 where the first estimate was 4. `README_FILENAME` and two
config-derived directory names are `Name` nodes rather than string literals, so
the syntax does not reveal whether a value can carry a `..`. That miss is why
the rule became a chokepoint instead of a judgement.

**The quote-drift source path** — `docs_qa/checks/quote_drift.py:78-89`. The
only site in either tree whose joined value is genuinely author-written: an
`ssot-quote` marker names its own source document, and the check stat-ed and
then **read** that path with no containment test.

What it allowed: the check was a content oracle. A `..` hop, an absolute path
and an in-repo symlink pointing out all resolved and were read. `secret_file_guard`
does not cover it — that guard judges the path an **agent** names in a tool
call, and nothing an agent typed names the file when the daemon follows a
marker inside a document it is checking.

Found twice independently in run 2026-001, by `D-PATH` (as a path defect) and
`D-SEC` (as a route past the secret guard). That agreement is what separated it
from the 29 other sites the widened Detector reported, all of which are
daemon-enumerated or config-derived.

The same fix closed a second instance of the ORIGINAL bug hiding in the same
function: `docs/../CLAUDE/Source.md` was reported as a missing source file,
because the un-normalised stat walked a `docs/` that need not exist.

- Defence: `e040e89b`, committed deliberately red over 30 instances.
- Fix: `73c90244` (this defect), `65161ce5` (the other 29, gate green).

## What the Defence does not catch

- **Only two trees.** `docs_qa/` and `plan_qa/`. The same shape elsewhere in
  `src/` is not reported, and the scoping is what makes the rule usable: run
  the widened rule over the whole package and it finds **153 sites outside
  those two trees, against 0 remaining inside them**. Nearly all 153 are
  daemon-chosen paths where `..` cannot arise, and a rule that opens with 153
  findings gets switched off rather than obeyed.

  A third tree that starts resolving authored paths must be added to
  `_SCOPED_TREES`; nothing will notice on its own. That is the live risk in
  this design — the scoping that makes the rule credible is also the thing
  that will silently stop covering new code.

- **Inline string literals are excluded.** `root / "README.md"` is never
  reported. Correct today, and it would stop being correct if someone wrote a
  literal containing `..`.

- **A fixed name list.** Stat predicates `exists`, `is_file`, `is_dir`;
  consuming calls `read_text`, `read_bytes`, `open`, `iterdir`, `glob`,
  `rglob`. A different way of asking — `os.stat`, `os.path.exists`, a builtin
  `open(p)` — is not seen, and neither is a path assembled with `joinpath()` or
  `os.path.join`.

- **One statement, not two.** The rule tracks a name bound to a join in the
  same function. A value that travels through a second assignment, a container,
  or a function boundary is invisible.

  This bullet used to read "the receiver must be a join AT the call site", and
  that blind spot turned out to be the **majority of the surface**: widening it
  took the count from 7 to 30, and the 23rd-to-30th sites included the live
  `quote_drift` defect above. The lesson generalises past this rule — the
  widening was built only because a reviewer was asked to MEASURE the Defence's
  coverage rather than confirm it, and the measurement disagreed with the
  docstring's confident "always".

  Scope stops at a nested function, so a closure over a joined local is missed.
  That under-report is deliberate: the first attempt used module scope, leaked
  a binding between sibling functions, and reported 2 where 1 was right. A rule
  that cries wolf gets suppressed, and a suppressed rule protects nothing.

- **The rule forces the chokepoint; it does not choose the helper.** Reaching
  `authored_path` satisfies it, and that only normalises. Only
  `contained_authored_path` establishes containment, and which one a site needs
  is still a human judgement the Detector cannot grade. Two sites currently
  take normalisation where containment was arguable:

  - `plan_qa/context.py`'s plan dir — config-derived, but it has no "not
    there" branch to refuse into, so containment would mean inventing a
    failure behaviour for a misconfigured tree. That belongs with the wider
    config-validation-fails-open question, which is owner-gated.
  - `docs_qa/corpus.py`'s revalidation — its keys arrive through a cache file,
    so they are only as trustworthy as that file, but it runs inside a
    PreToolUse budget that already rejected a ~2000x costlier pass.

- **Containment ends at the root it checks.** `contained_authored_path` proves
  the joined path lands inside `base`. It says nothing about what an `rglob`
  under that root then yields — a symlink inside a contained tree can still
  point out, and the corpus walkers do not re-check each child.

- **TOCTOU.** Containment is checked, then the file is opened. The realistic
  attack here is a committed document plus a committed symlink, which is caught;
  a swap between the check and the open is not.
