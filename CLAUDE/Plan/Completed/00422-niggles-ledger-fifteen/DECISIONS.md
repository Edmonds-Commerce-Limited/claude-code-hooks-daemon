# Ledger fifteen: decisions on the six owner questions

The owner set this session to run unattended on 2026-09-24. Their
instructions: "your goal is to get everything working", "no known defects",
and "we have to support plugins properly". An unattended session cannot ask,
so each question below takes the option the ledger's own analysis
recommended. Each decision states its assumption so the owner can reverse it
with one message. The questions themselves are in
[PLAN.md](PLAN.md#questions-waiting-on-the-owner).

| #   | Entry | Decision                                                                                                                                                                                                                                                                                                                                                       | Assumption                                                                                                                                                             |
| --- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | N1    | The consistency test covers the **whole** `init_config.py` template against `priority.py`. Every divergence it finds is fixed in the same change, never allow-listed.                                                                                                                                                                                          | "No known defects" rules out a test that stops at the one block already known to be wrong.                                                                             |
| 2   | N4    | A **session-scoped cron pause** exists. It is recorded through an expiring marker, the same mechanism as the "blocked only on human input" marker. It is set only by a CLI verb that names the job and a reason, it expires within 24 hours, and it is visible in the Stop enforcer's output. Config (`persistent_crons`) stays the only permanent off switch. | A pause that expires and is visible gives up less than a legal move that has no spelling, which leaves every session to re-derive the contradiction from two failures. |
| 3   | N7    | An effort drop that the supervisor did not inject **is trusted as manual and latched**. The asymmetry with the model-downgrade logic is accepted and documented next to both.                                                                                                                                                                                  | Only a human uses the selector. A supervisor that silently reverts a human's choice is the worse failure.                                                              |
| 4   | N11   | The acceptance fixtures **move** to a dedicated `untracked/acceptance/` root. Every strategy, the playbook harness and the client-facing docs are updated, and the N2 depth-scoped exclusion is revisited.                                                                                                                                                     | The coupling will keep producing exclusions until the two uses of the directory are separated.                                                                         |
| 5   | N3    | A **`correction`** category is added to the journal grammar in `_JOURNAL_TEMPLATE_.md` and the journal tooling (`mkplan.bash --journal`, the journal QA rules).                                                                                                                                                                                                | A correction that reads as a correction is worth one template change that ships to clients.                                                                            |
| 6   | N5    | Review dispatches **default to a tracked report destination**: the dispatching plan's `subagent-reports/` folder, which this project already uses. The gitignored `untracked/agent-reports/` path stays only as the fallback when there is no plan.                                                                                                            | Evidence that survives only until the container restarts is not evidence.                                                                                              |

**All six are now built**, not just decided: N1 (`c1822548`, merged
`d28b25fa`), N4 (`8b388a2a`, merged `63dea9f08`), N7 (`8ffe9ffe`, merged
`63dea9f08`), N11 (moved with B1), N3 (`14bdb525`, merged `d28b25fa`), N5
(`f013ac65`, merged `d28b25fa`). See NIGGLES.md for each entry's delivery
detail.

## The original questions, as put

Kept verbatim for the record: each was ONE question, with what leaving it
unanswered would cost.

1. **N1 — how loud may a template-versus-constants test be?** `priority.py`
   and the `init_config.py` template disagree across the whole `status_line`
   block and have for longer than the handler that surfaced it has existed;
   relative order is preserved, so nothing misbehaves and no check can see
   it. A consistency test would fix that permanently. **Does it get to fail
   across the WHOLE template, or only across the `status_line` block?**
   Whole-template may surface more than the divergence found, which is a
   scope call, not a bug fix. Unanswered: the constants keep documenting a
   relationship a fresh install cannot have.

2. **N4 — may a session suppress a cron the project declared?** Obeying an
   instruction to cancel `issue-sdlc` makes the next Stop block, because the
   enforcer refuses a session missing a declared job — correctly. The only
   existing knob (edit `persistent_crons`) stops the job for every session on
   every branch. **Is there to be a session-scoped pause, recorded through an
   expiring marker like the "blocked only on human input" one, or does
   "cancelled for now" remain unspellable?** A pause hands a session the
   ability to switch off a guard the project declared. Unanswered: the two
   moves stay mutually exclusive and whoever hits it re-derives that from two
   failures.

3. **N7 — is an unattributed effort drop a human choice?** A bare `/effort`
   opens Claude Code's own selector, which names nothing the supervisor can
   read, so the manual-effort latch never sets and the floor puts it back.
   **Should an effort drop the supervisor did not itself inject be trusted as
   manual and latched?** The downgrade logic deliberately answers the
   mirror-image question NO — an unattributed model change gets no restore —
   so answering YES here is a real asymmetry to accept, not an oversight to
   correct. Unanswered: setting effort from the selector keeps getting
   undone.

4. **N11 — may the acceptance fixtures leave the human scratch directory?**
   The lint strategies write their probe fixtures under `untracked/scratch/`,
   the same directory agents are told to use for working notes, which is what
   forced the depth-scoped exclusion N2 shipped. A dedicated
   `untracked/acceptance/` root separates them properly. **Is that move worth
   making?** It renames a path ten strategies, the playbook harness and
   client-facing docs all name. Unanswered: the coupling stays, and the next
   exclusion has to rediscover it.

5. **N3 — may a `correction` category be added to the journal grammar?** It
   is the only implementable remedy for the three-rule contradiction, and the
   grammar lives in `_JOURNAL_TEMPLATE_.md`, which ships to every client.
   **Is that a template change worth making?** Unanswered: nothing breaks —
   the contradiction is self-limiting, since the ordering sweep only reads
   live plans — but a correction stays illegible as a correction.

6. **N5 — should a review dispatch default to a TRACKED report destination?**
   `dispatch_declaration` currently recommends `untracked/agent-reports/`,
   which is gitignored; that is how twenty release-review non-defects came
   within one container restart of being lost. **Should the default move
   somewhere git can see?** It changes what every client project is told,
   not just this one. Unanswered: the next reviewer's evidence lands
   somewhere nothing durable reads.
