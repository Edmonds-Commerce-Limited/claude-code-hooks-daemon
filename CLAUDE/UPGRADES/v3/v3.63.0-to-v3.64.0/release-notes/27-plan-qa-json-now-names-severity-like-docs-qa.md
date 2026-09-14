# Callout: BREAKING — `plan-qa --json` renames `level` to `severity`

**Plan**: 00375
**Audience**: operators

Two sibling verbs emitted the same concept under two names: `docs-qa --json`
gave each finding a `"severity"`, `plan-qa --json` gave it a `"level"`. Same
finding shape, same two values (`block` / `advise`), same purpose.

That is not cosmetic — it produced a defect within an hour of first being met.
A reader that knows only one name drops every finding from the other verb while
still counting it toward the total, and one did: a QA wrapper counted
`severity`, so every plan finding fell out of the severity split and it printed
`3 findings (0 block, 0 advise)` — a summary contradicting itself.

`plan-qa --json` now emits `"severity"` and nothing else. `docs-qa --json` is
unchanged.

**What to change**: anything parsing `plan-qa --json` should read `severity`
where it read `level`. The values are identical, so this is a key rename and
nothing more.

**Why there is no deprecation window.** Emitting both spellings for a release
would make the defect itself — two live names for one concept — correct by
policy for that release, and invite a new reader to key on the one about to
disappear. It would not avoid the break either: removing the key later is the
same breaking change, merely deferred. So the break is taken once, declared
honestly under semver, and carried by an upgrade-time migration rather than by
a delay.
