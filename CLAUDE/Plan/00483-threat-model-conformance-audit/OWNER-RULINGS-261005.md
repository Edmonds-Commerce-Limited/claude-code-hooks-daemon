# Owner rulings, 2026-10-05

The project owner answered owner-question chunks A to D on 2026-10-05. These ARE owner rulings. The owner's words are
paraphrased from speech-to-text. The questions are in
[subagent-reports/261005-owner-decision-backlog-opus.md](subagent-reports/261005-owner-decision-backlog-opus.md), Part 3.

Where a ruling carries a "Coordinator's recorded reading", that reading is the coordinator's interpretation, flagged for
the owner to correct. It is not the owner's wording.

## A1: 00483 Q4-R3, the fail-closed rule

**Owner ruling:** "Fail-closed is too problematic. Deliberate evasion is out of scope. I'm not sure any kind of
fail-closed is really sensible."

**Coordinator's recorded reading (flagged for the owner to correct):** guards deny only on a positive finding, meaning a
literal protected path or a named dangerous command. A cap, a deadline, an unreadable command or an unparseable command
allows, with a loud advisory. The fail-closed rule in `CLAUDE/ARCHITECTURE.md` is to be amended accordingly.

**Settles:** 00483 Q4-R3 (PLAN.md open question 4), the INVENTORY fail-closed owner calls, and N352 (via this ruling).
00490 Q3 follows the same direction.

## A2: 00483 Q4-R4 (with Q2), remove the expensive code

**Owner ruling:** "Rip out the expensive code. Make this much more simple, optimised, and fitted to the threat model we
are talking about."

The whole R4 table goes: the bare-glob filesystem expansion, the per-call tree walk, and the out-of-scope-only branches
listed in `INVENTORY.md` ("Out-of-scope-only code").

**Settles:** R4, Q2 (open question 2), Q3 O1 to O5 (superseded), N74 (via the cached index), N350 (removed with the
bare-glob expansion), N352 (via A1), and Task 3.3.

## A3: 00483 Q4-R6, strict mode

**Owner ruling:** yes, `bash_safe_mode` goes back to `only_with_mutator: true`. This reverses the owner's own N308
ruling.

**Settles:** R6; the N308 ruling at `00474 NIGGLES.md` (N308 entry).

## A4: 00483 Q4-R7, the keep/narrow/drop list

**Owner ruling:** yes, accept the review's R7 keep/narrow/drop list
([261004-guard-effort-pragmatism-review-opus.md](subagent-reports/261004-guard-effort-pragmatism-review-opus.md)).

**Settles:** R7.

## A5: 00483 Q4-R2b, releases and false-positive reports

**Owner ruling:** yes. An open client-filed false-positive issue in this area blocks the next minor release until it is
fixed or accepted.

**Settles:** R2b.

## A6: 00483 T2.2, nine uncovered dangerous commands

**Owner ruling: NOT agreed; to be revisited.** The owner's notes:

- `docker run -v /:/host` sounds dangerous and should be blocked.
- `rm -rf` must NOT be blocked, because it is often the right thing.
- Destructive deletes on the REMOTE git repository need a human.
- `gh auth token` is "probably not something that should be done".
- The owner did not know what `pip install --index-url` and `git push --delete` do, and wants them explained.

**Status:** awaiting the coordinator's revised proposal. Task 2.2 stays open on this point.

## B1: 00484 G2 and the 00483 INVENTORY escape hatches

**Owner ruling:** keep the `MUST_*_BECAUSE` hatches (`MUST_SQUASH_BECAUSE`, `MUST_STASH_BECAUSE`,
`MUST_SCAN_ROOT_BECAUSE`, `MUST_SKIP_SAFE_MODE_BECAUSE`). "They force the agent to say I really do mean to do this,
which is what we want." Keep the review's hygiene fixes (the no-reason hatch, the `-->` closer bug, the generic-reason
check).

**Settles:** 00484 G2; `INVENTORY.md` (escape-hatch note after the out-of-scope table).

## B2: 00484 G1, inline QA suppressions

**Owner ruling:** NO central exceptions file or baseline. "Baselines become huge blobs of unmaintained" mess. Keep
suppressions inline and co-located, but each MUST carry its reasoning. Delete as many as possible, and review every one
that is kept to see whether it is needed and why it exists.

**Settles:** G1, in the opposite direction to the Fable recommendation (which proposed a record file).

## B3: 00484 G4, reasons on config exceptions

**Owner ruling:** yes, as recommended. Reasons are accepted on config exceptions now (`exclude_paths`,
`extra_whitelist`), required under strict mode, and required for everyone at the next major.

**Settles:** G4.

## B4: 00474 N296, error-hiding audit

**Owner ruling:** yes, as recommended. One named helper with a required reason argument, and the audit widened to catch
log-then-continue bodies.

**Settles:** N296.

## B5: 00474 N314, module-size gate

**Owner ruling:** not just a size gate. The owner asks for a NEW PLAN: a general code-quality and architecture review
covering module size, DRY, architecture overview and code quality, perhaps followed by a refactoring effort.

**Settles:** N314 folds into the new plan `code-quality-and-architecture-review` (see the plan index).

## C1: 00484 DEFSET

**Owner ruling:** yes. The action guards are outside the DBF Defence set. The content and commit gates are the Defence
set.

**Settles:** DEFSET.

## C2: 00484 Task 1.4

**Owner ruling:** yes. The agent may post the "DBF adopted" ruling as comments on #65 and #67, using "Addresses" and no
closing keyword, and remove the `agent-needs-human` label.

**Settles:** Task 1.4 is unblocked.

## D1: 00474 N309, duplicated by 00479 Task 1.1 and 00486 Task 1.3

**Owner ruling:** a broader design than asked. There is to be a single source of truth listing the FAKE values used in
docs (session ids, tokens, hostnames and so on). Docs may freely use any listed fake. Anything fake-looking that is not
on the list must be replaced by a listed fake, or the list extended for a genuinely new kind of fake.

**Settles:** N309, 00479 Task 1.1 and 00486 Task 1.3, by this route. The work is the new plan
`docs-fake-values-registry`.

## D2: 00483 Q5 (N98)

**Owner ruling:** yes. Take the N98 fix at the next minor, with the forwarder-regeneration step on upgrade.

**Settles:** Q5.

## D3: 00474 N289, the 13 GB under `untracked/scratch`

**Owner ruling:** yes, clean up. And add a standing "housekeeping" task list to the RELEASE process. It covers cleaning
`untracked/` and may include tracked housekeeping too.

Cleanup keeps anything a live worktree or an open report points at.

**Settles:** N289. The housekeeping list is in `CLAUDE/development/RELEASING.md`.
