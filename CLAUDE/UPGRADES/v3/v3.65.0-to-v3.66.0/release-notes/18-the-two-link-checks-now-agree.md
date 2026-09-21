# Callout: the two link checks now agree, and one stops crying "archived"

**Plan**: 00441
**Audience**: everyone

Docs QA's `pointer-resolves` and plan QA's `plan-link-resolves` both answer
"does this markdown link point at a file that exists". They were written months
apart and disagreed three ways.

**A live plan is no longer called archived.** `PlanLinkResolver` searches the
active plan root before any archive and takes the first match — deliberately,
because the live plan is the better answer to "where is plan N". But the
finding built from it said, unconditionally, that the target "has been
archived". So an author who mistyped a `../` depth for a plan that is very much
alive was sent to look in `Completed/`, where it is not. There are now two
messages, chosen by where the target actually sits.

**One finding per link, not one per occurrence.** A document naming the same
dead link three times produced three identical findings. It now produces one,
at all three stages — including EDIT, where those duplicates were repeated
lines in the report denying your write.

**A repo-root-relative link resolves in plan documents too.** `pointer-resolves`
has always accepted `CLAUDE/Plan/README.md` written from anywhere, because this
project's docs use that convention constantly; `plan-link-resolves` accepted
only paths relative to the file, and reported the rest as needing a repoint.
Both now use one shared rule in `utils/link_resolution.py`, and docs QA's copy
was deleted rather than left beside it — a second copy is what let them drift.

Nothing here changes which links are legal. It changes which findings you see,
and all three changes remove noise rather than adding it.
