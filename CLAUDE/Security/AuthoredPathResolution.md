# Category: authored path resolution

**Defence**: `scripts/qa/check_authored_path_stat.py` — a stat predicate
applied to a joined path, anywhere in the trees that resolve paths an author
wrote.

Index: [README.md](README.md). Found by
[Routine 00001](../Routine/00001-security-review-full/ROUTINE.md)'s check
`D-PATH`.

## The class

A path that an AUTHOR wrote — a markdown link target, a path quoted in a plan —
resolved by calling `.exists()`, `.is_file()` or `.is_dir()` on the joined
path.

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

## What the Defence does not catch

- **Only two trees.** `docs_qa/` and `plan_qa/`. The same shape elsewhere in
  `src/` is not reported — 17 sites, nearly all daemon-chosen paths where `..`
  cannot arise, and a rule with that ratio gets suppressed rather than obeyed.
  A third tree that starts resolving authored paths must be added to
  `_SCOPED_TREES`; nothing will notice on its own.

- **Inline string literals are excluded.** `root / "README.md"` is never
  reported. Correct today, and it would stop being correct if someone wrote a
  literal containing `..`.

- **Only three predicates.** `exists`, `is_file`, `is_dir`. A different way of
  asking — `os.stat`, `os.path.exists`, `glob`, an `open()` in a `try` — is not
  seen.

- **It is a syntax rule, and this blind spot is the MAJORITY of the surface —
  measured, not estimated.** The receiver must be a join at the call site, so
  `p = base / target` on its own line and `p.exists()` on the next is invisible.
  Asking the same question one statement away, in the same two directories,
  finds **28 more sites** (12 stat, 16 read) against the 7 the Defence reports.

  Two of them — `docs_qa/checks/quote_drift.py:79` and `:89` — are a live
  instance of the exact hazard this category exists for: an authored
  `ssot-quote` source path, stat-ed and then READ, with no containment test.
  So the Defence's own scoped trees contain an uncaught member of its class,
  invisible for a purely syntactic reason.

  Most of the other 26 are safe by construction (corpus walkers over
  daemon-enumerated keys; plan-tree joins over config-derived directory names),
  so a naive widening carries roughly a 1-in-3 signal ratio. The remedy is the
  same chokepoint argument that shaped the original rule — route them through
  the helper rather than judge them — but the widening is **not yet built**.

  Until it is, read this Defence's coverage as "direct joins only", not as the
  "always" its own docstring claims. A green check plus a confident docstring
  is exactly what makes a blind spot read as coverage.

- A path assembled with `joinpath()` or `os.path.join` does not match either.

- **Containment is a different question.** Normalising makes `..` resolve
  faithfully; it does not stop a target escaping the repository. A link reading
  `src/../../etc/passwd` resolves to a real file, and this Defence says nothing
  about that.
