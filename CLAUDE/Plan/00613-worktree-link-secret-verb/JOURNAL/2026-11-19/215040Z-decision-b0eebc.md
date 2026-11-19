## 21:50 · decision · —

Rulings on Q0 to Q5, settled by a fable sub-agent under the owner's delegation, 2026-11-19. NOT the owner's own words; a later owner message overturns any of them. The delegation reached the sub-agent through the coordinating session, so each ruling is shaped to need no owner authority: none loosens the secret guard and none creates a route an agent can invoke. Full text: DESIGN.md, section Rulings.

- Q0 (did the owner type that agents may link protected files): not verified, treated as no. No human line is cited in this plan and a sub-agent cannot answer for the owner. Nothing below relies on it.
- Q1 (is a link acceptable at all): yes, only by a route a human owns (project config, or a human-typed command); never by a route an agent can invoke.
- Q2 (mechanism): B + D. Config seed list in link mode for harness-created worktrees, a human-run step for hand-made ones. The verb (A) is not built; it is reopened only by the owner's own typed yes to Q0 and Q1.
- Q3 (copy mode for a protected source): forbid.
- Q4 (config switch for A): moot while A is not built; if reopened, yes, default off.
- Q5 (gate): yes, and wider than written. The Plan 00614 fix lands through Plan 00623. Until both are on main and the three link routes are verified denied through a live daemon socket, no text advises seeding or hand-linking a protected path. Gap 1 is live on main today, so the gate covers the human-run step as well.

Plan changes: Task 1.3 ticked as a delegated ruling. Phase 2 rewritten from the verb to tightening the seeding executor (copy refusal, audit line, a pin that hand-typed link and copy commands stay denied, release note); it only tightens, so it may start now. Phase 3 (advise the link, group C end to end) waits for the gate. Nothing was built.

Still needs the human: only Q0, and only if the owner wants the verb. Safe default: no verb.

First build slice: Task 2.1, failing tests that `utils/worktree_seeding.py` refuses `mode: copy` for a protected source.
