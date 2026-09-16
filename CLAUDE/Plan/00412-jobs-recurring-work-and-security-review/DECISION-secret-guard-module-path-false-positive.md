# Decision needed: `secret_file_guard` matches dotted MODULE paths

**Status**: open, owner decision. Blocks Plan 00412 worklist row **F-PRIV-4**.

**Found by**: dogfooding, 2026-09-16, while writing the F-PRIV-4 regression
test.

## What happens

`secret_file_guard` denies any `Write`/`Edit` whose content references a
protected path. One shipped protected glob is `*.secret*`.

A Python import of the daemon's own redaction utility — the module living at
`src/claude_code_hooks_daemon/utils/secret_redaction.py` — is written in
DOTTED form. That dotted form contains a dot immediately followed by `secret`,
so it glob-matches `*.secret*` and the write is denied:

```
Matched protected glob: `*.secret*`
Matched on this token from your input: <the dotted module path>
```

The FILE path form does not match — `…/utils/secret_redaction.py` has a
SLASH before `secret`, not a dot. Only the import spelling trips it.

## Why it matters

That module is ordinary daemon source, imported normally across this
repository. `scripts/qa/check_sensitive_content.py` already imports it (lazily,
inside two functions). Any edit that re-authors one of those import lines is
therefore denied — which is precisely what F-PRIV-4's fix requires, since the
defect IS in how those two lazy imports degrade.

So the guard currently makes one daemon module un-editable-by-import, in a
repository that dogfoods itself. A client project would hit the same wall for
any module of its own whose dotted path happens to contain `.secret`.

## Why I did not fix it myself

Every narrowing I could construct loses real protection, and the guard is
deliberate about having no escape hatch:

- **"Skip tokens with no path separator."** `.vault-pass` and `id_rsa` are
  protected names mentioned exactly that way, with no separator. This would
  stop catching them.
- **"Skip tokens that are valid dotted Python identifiers."** `foo.secret` is
  both a valid dotted path and a plausible protected FILENAME. A mention of a
  real file called `foo.secret` would stop being caught.
- **"Require the character after `.secret` not to be an identifier char."**
  This excludes `.secret_redaction`, but it also excludes `.secrets`, which is
  a name the guard exists to catch.

This is the shape already recorded in
[AsymmetricSiblingProtection.md](../../Security/AsymmetricSiblingProtection.md)'s
Rejected rows section: an exclusion that looks like consistency and actually
removes protection. It needs a human to choose, not an agent mid-task.

The guard's own deny message says the same thing: *"Only a human may lift
this."* Routing around a security guard to make my own task easier is the move
it exists to stop, so I did not construct the string in pieces either.

## Options

**A — context-aware matching (recommended).** Match the token as a path only
when it is used in a path-like position, and treat a token that is the target
of an `import` / `from … import` statement as a module reference rather than a
filename. Keeps every filename case above. Costs: the guard gains a notion of
Python syntax, which is a real complexity increase and needs its own tests for
the cases listed under "Why I did not fix it myself".

**B — per-project exemption.** Add the dotted module path to a new
`allowed_module_paths` option. Narrow and cheap, but it is a list that has to
be maintained, and a client project would need to discover the failure before
knowing to add its own entry.

**C — rename the module.** `secret_redaction` → e.g. `redaction`. Removes the
collision entirely and costs one mechanical rename across the tree. Cheapest
technically; the objection is that renaming source to appease a guard's
matcher is the tail wagging the dog, and the next module with `.secret` in its
path hits the same wall.

**D — accept it.** Record the limitation and route F-PRIV-4 around it. Not
viable as written: F-PRIV-4's fix cannot be authored at all.

## What is blocked until this is decided

- **F-PRIV-4** — `scripts/qa/check_sensitive_content.py`'s two adjacent lazy
  imports degrade in OPPOSITE directions on the same `ImportError`. The
  exclusion route degrades toward scanning MORE files (safe). The secret-term
  route degrades toward an EMPTY term list, so the checker reports zero
  violations having never loaded a single term. The design and tests are
  written up in the journal entry for this date; only the authoring is blocked.

Nothing else on the 00412 worklist depends on this.
