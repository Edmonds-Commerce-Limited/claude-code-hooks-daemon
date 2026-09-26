# Callout: `secret_file_guard` fails closed on a slow scan instead of timing out open

**Plan**: 00466
**Audience**: client projects

A crafted or merely pathological command token — long runs of `*`, many
bracket-and-star tokens in one command, or high volume of ordinary
glob-shaped text — could make `secret_file_guard`'s mention scan run past the
client's PreToolUse socket budget; a timed-out PreToolUse call is an ALLOW
for the whole chain, so a slow scan was a bypass, not just a nuisance. The
interior-wildcard intersection check now collapses repeated `*` runs
(language-preserving), caps its own per-token cost, and the whole scan now
carries a deadline: exceeding it raises rather than silently truncating, so
the existing fail-closed wrapper denies instead of skipping whatever sat
past the cutoff. A 60 KB single-token bypass shape and a 1 MB
ordinary-content scan both now stay comfortably under a one-second budget.
