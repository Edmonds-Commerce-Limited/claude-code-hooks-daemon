## 02:53 · decision · —

This is the STAND-IN's ruling (automated, 5 November 2026), not the owner's; a later owner message overturns it.

**Q5 rollout mode (RESERVED, declined again).** The question is whether the scratch deny and the SessionStart sweep ship to clients as `advise` for one release and then `block`, or as `block` at once. Either answer sets the model default the next release ships to every client, which is a release and shipped-client-default decision, and the stand-in's remit is engineering choices only. Nothing has changed since the 223017Z ruling that would make it pure engineering: the deny and the sweep are not yet built, so there is no field evidence of false positives to argue from, and this repository already runs `block` from day one regardless of the answer (DESIGN.md section 9), so the only thing the choice decides is what clients receive.

The plan's recommendation stands as the recommendation: `advise` for one release, then `block`, mirroring Plan 00558's rollout. The owner can answer with one word. Task 1.4 stays blocked on this; Phase 1 engineering is not held up by it. Nothing is implemented by this ruling and PLAN.md is untouched.
