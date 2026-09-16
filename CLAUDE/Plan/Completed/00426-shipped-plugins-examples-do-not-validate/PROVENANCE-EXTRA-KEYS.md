# Are extra provenance frontmatter keys a supported extension point?

The owner decision behind the second half of issue #44. This document records
what was **measured**, not what should happen. The decision is product intent
and is not taken here.

## What was measured

An `x-captured-because:` key was injected into a captured document's provenance
frontmatter, then the document was put through the normal commands.

| Step                        | Result                                            |
| --------------------------- | ------------------------------------------------- |
| `parse_provenance`          | accepts it — reads only the fields it requires    |
| `remote-docs check`         | exit `0`, "all vendored documents are fresh"      |
| `remote-docs refresh --all` | **key is gone**, and the run reported `unchanged` |
| `remote-docs add --force`   | **key is gone**                                   |

So the tolerance the issue describes is real: a project CAN add its own keys,
and every read path accepts them. Both write paths then discard them.

## Why the `unchanged` case is the sharp end

`docs/guides/REMOTE_DOCS.md` says a refresh that finds upstream unchanged "says
`unchanged` and rewrites nothing but the dates". That is what a reader relies on
when deciding a refresh is safe to run.

It is not what happens. A refresh that finds nothing new still rewrites the
frontmatter from scratch, so any key the daemon does not know is destroyed — and
the command reports that nothing changed. Silent data loss on a no-op is a
different severity from "refresh rewrites frontmatter", and it is the reason
this is worth deciding rather than documenting either way.

## The options, with what each costs

**(1) The tolerance is a contract.** Say so in `CLAUDE/RemoteDocs.md`, and make
the write paths preserve unknown keys across `refresh` and `add --force`.

- Projects can annotate captures — why a page was pinned, what derives from it —
  and that survives maintenance.
- Cost: unknown keys become a compatibility surface. A future schema field could
  collide with a key some project already uses. A reserved namespace (`x-`)
  bounds that, at the price of a rule to remember.
- Note: choosing this means `refresh` is currently VIOLATING the contract on
  every run, so it is a fix, not just a docs change.

**(2) The tolerance is an accident.** Say that in the docs, and reject unknown
keys at capture time.

- Honest, and closes the gap between what is accepted and what survives.
- Cost: a project wanting a note has nowhere to put it, and any project already
  relying on the tolerance breaks loudly on upgrade — which is better than
  breaking silently, but is still a break.

**(3) Document the current behaviour and change nothing.** Write down that
unknown keys are accepted on read and dropped on write.

- Cheapest, and removes the surprise.
- Cost: keeps a shape where the system accepts something it will later delete
  without saying so. It makes the trap documented rather than absent.

## What is not in question

The parser's tolerance is not itself a bug — reading only required fields is why
a capture from an older schema still parses. The question is only whether that
tolerance is *promised*, and what the write paths owe it if so.
