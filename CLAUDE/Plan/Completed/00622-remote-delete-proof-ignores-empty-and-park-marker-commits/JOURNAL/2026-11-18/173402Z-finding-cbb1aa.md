## 17:34 · finding · —

Residuals measured by the round 2 corpus. They are older than Plan 00622 and are not widened by it.

Patch-equivalence passes a whitespace-only difference, and the corpus shows it on the local and local-hook paths, before and after this plan:

- `r2-ws-pick-bare`: a pick that main took reformatted.
- `r2-orphan-ws-bare`: an orphan whitespace twin with no merge base.
- `r2-ws-pick-writer-park`: the park writer's own marker over a whitespace pick. The park-marker drop in `patch_equivalent` is from Plan 00617.

The remote proofs refuse all three, because they require the net change. Closing them means changing the patch-equivalent tier itself, for example by requiring the net change or by refusing when there is no merge base. That is a behaviour change to a tier this plan does not own, so it is ledgered as N660 in Plan 00474's NIGGLES.md rather than fixed here.
