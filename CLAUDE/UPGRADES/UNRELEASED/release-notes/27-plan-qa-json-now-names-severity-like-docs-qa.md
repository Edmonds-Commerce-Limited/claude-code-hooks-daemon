# Callout: `plan-qa --json` now names severity `severity`, like `docs-qa` always did

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

`plan-qa --json` now emits **both** keys with the same value. `severity` is the
surviving name; `"level"` is deprecated and will be removed in a later release,
recorded here so a consumer parsing it has a window to move. Nothing breaks
today: a script reading `level` keeps working unchanged, and one reading
`severity` now works against both verbs.

`docs-qa --json` is unchanged.
