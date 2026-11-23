# Plan 00634 independent review: human_approval_check (PR #225)

Reviewed in worktree `/workspace/.claude/worktrees/agent-a6328547e60968275-2a1ab764`
(branch `plan-00634-human-approval-check`, HEAD 24a96865b), read-only.
Light verification only: one probe script over `classify_acts` / `cite_from_command`
(cwd = the linked worktree and the `/workspace` main checkout), plus the targeted unit
tests for the changed modules (534 passed, nice -n 19, PYTHONPATH=src).

## Verdict

**Safe to merge as shipped. It cannot pass a forged cite today, and the refactors change
no behaviour.** The production verifier is `contract_unconfirmed_verifier`
(`utils/human_approval.py:211-223`). `TeamchatVerifyCli` is not wired anywhere in `src/`,
so no cite can pass. The shipped mode is `advise` (`human_approval_check.py:195`,
`.claude/hooks-daemon.yaml` +449), which never denies.

**The guard is NOT fit to be switched to the live verifier, or to `block`, as designed.**
Findings 1-3 mean that a verified pass would prove only that "some declared human
once said something in the questions room". It would not prove that a human approved this
act. Fix these before Task 2.3, the swap to `TeamchatVerifyCli`.

## Findings, ranked

### 1. HIGH (latent until Task 2.3): the approval is not bound to the act, its content or its age, so replay is unbounded

- `check_approval` (`utils/human_approval.py:380-392`) checks four things only: the line
  is the cited id, in team T's `questions` room, and its sender kind is `human`.
- Nothing reads what the line says. Invariant 4 forbids it, so a human writing
  "NO, do not push" in the questions room is an approval.
- `VerifiedLine.question` is parsed (`:207`) and then never used.
- The cite comes entirely from the agent's command text (`human_approval_check.py:165-185`).
  A coordinator agent can read the room and cite ANY human line id, including one from
  weeks ago or one about something unrelated.
- The plan's "Gap, replay" note (PLAN.md:76-78) understates this. It says the line
  authorises acts "until its in-memory approval record lapses (TTL 300s)". The TTL
  (`ApprovalRecords`, `:269-299`) only skips re-verification. After it lapses, the same
  line verifies again and passes again, indefinitely.
- There is no single-use rule, no maximum line age, no binding to an act class, branch
  or repo, and no requirement that the line answers a question the coordinator asked.
- Fix: before switching verifiers, require at least two things:
  - a bounded line age (verify must return a timestamp);
  - a binding, e.g. the line must answer a `Q<n>` the coordinator posted that names the
    act, or a per-cite single-use ledger.

### 2. HIGH (documented, but it defeats the guard): sub-agents and in-process teammates are never armed

- `is_armed` returns False for anything that is not the main thread
  (`utils/human_approval.py:319`, via `acts_as_main_thread`). An in-process teammate also
  carries `agent_id` (`core/handler_scope.py:148-155`).
- As a result, `matches()` (`human_approval_check.py:251`) is silent for those threads, and
  `Refusal.SUBAGENT` (`:363-364`) can never be reached from the handler.
- A coordinator can bypass the whole check by dispatching a sub-agent or teammate to run
  `git push` / `gh pr merge` / `git branch -D`.
- This is acknowledged in PLAN.md:73-75 as "Gap, sub-agents". It is the single largest
  bypass and should be fixed before `block` is meaningful. One option: arm sub-agents of
  an armed coordinator session, and deny them under block, accepting the cost that
  sub-agents cannot do these acts.

### 3. MEDIUM: gaps in the act detectors, verified by probe

These are all `[]` (no act) from `classify_acts`:

- **Merge to main:**
  - `gh -R o/r pr merge 5`: `_GH_PR_MERGE_RE` requires adjacent `gh pr`
    (`merge_to_main_approval.py:69-72`). This gap already exists in merge_to_main_approval.
  - `gh api -X PUT repos/o/r/pulls/5/merge`
  - `gh api repos/o/r/merges ...`
  - On `main` in `/workspace`: `git fetch . feature:main`, `git update-ref refs/heads/main <sha>`,
    `git reset --hard feature`, `git rebase feature`, `git cherry-pick <sha>`.
  - Command-order blindness: `git checkout main && git merge feature`, issued from another
    branch, is judged against the branch checked out BEFORE the command runs
    (`merge_lands_on_main`, `merge_to_main_approval.py:321-337`). This already exists too.
  - `git -C <other> merge x` is judged against the hook cwd, not `-C`.
- **Delete:**
  - `git branch -d` (documented gap)
  - `git tag -d v1`
  - `gh api -X DELETE .../git/refs/heads/foo`
  - `rm -rf .git/refs/heads/foo`
- **Permission:** shared with dangerous_permissions, so these all exist on main as well:
  - `chmod a=rwx f`, `chmod o=rwx f`, `chmod ugo+w f`. The symbolic pattern only
    accepts `[ao]\+` (`dangerous_permissions.py:51`).
  - `chmod 00777 f` (an octal mode with two leading zeros)
  - `install -m 777`, `setfacl -m o::rwx`, `umask 000`
- **Push:** `git send-pack origin x`.

What holds up, on the same probe: the wrapper and quoting bypasses I tried are all caught.
That covers `env`, `sudo`, `command`, `bash -c`/`sh -c`, `eval`, `xargs`,
`timeout`/`nice`, `\git`, `g''it`, `/usr/bin/git`, `git -C/-c`, subshells, `$( )`, and
`GIT_DIR=` prefixes. `HEAD:main`, `+ref` and `--force-with-lease` all classify as push.
`--force-with-lease` also counts as delete, which fails closed. `:ref`, `--delete`/`-d`,
`update-ref -d` and `worktree remove` count as delete.

### 4. MEDIUM-LOW: fail-open before arming covers exceptions in `classify_acts`

- `matches()` (`human_approval_check.py:244-262`) turns any exception into a silent False.
  That is the right call for a seatless session, but `classify_acts` runs BEFORE the seat
  probe.
- So for an armed coordinator, an exception there silently drops EVERY act in the
  command, not just the act that raised. Examples: git subprocess trouble in
  `merge_lands_on_main` / `GitRepo.resolve_for`, or a parser edge in `git_invocations`.
  Example command: `git push x && git merge y`.
- `names_a_deletion` catches only `_Unverifiable` (`destructive_git.py:877-886`).
- Suggested fix: resolve the seat first when the runtime is set, then classify, and
  treat an exception after a seat is known as armed.
- Unknown role and an UNRESOLVED seat correctly stay armed (`utils/human_approval.py:321-327`).
  A missing kit or a bad path also leads to UNRESOLVED, which is armed. Good.

### 5. LOW: `advise` (the shipped default) permits everything

- `_refuse` returns ALLOW with context in any mode other than `block`
  (`human_approval_check.py:304-307`). So under `advise`, all of these run:
  - uncited acts
  - forged acts
  - wrong-team acts
  - acts from a non-coordinator seat
  - acts where verify is unavailable
  - acts after a handler exception
- This is documented and intended. Combined with the refuse-all verifier, the handler is
  currently a pure annotation. Reviewers should not read it as protection.
- Under `block`, every armed act is denied until issue 369 lands (also documented).

### 6. LOW: the event-id grammar accepts path-ish ids

- `_EVENT_ID` (`utils/human_approval.py:59`) allows `/`, `.`, `+`, `=`, and the probe
  accepted `$abc/../../x`.
- This is not argv injection: the argv is a tuple with no shell, the leading `$` prevents
  it being read as an option, and the team passes `normalise_name`, which rejects
  `-rf` and `../x`.
- But it relies on teamchat not treating the id as a path. Consider tightening it to the
  real id alphabet once issue 369 confirms it.

### 7. LOW / informational

- **Approval records** live in daemon memory only (`ApprovalRecords`). There is no file,
  so there is no file race or permission issue.
  - Records are keyed on `(SessionSignals(runtime, kit), cite, act)`, not on the session
    id. Two sessions sharing one runtime share a record.
  - The record lookup comes after the role gate (`:373-379`), so the impact is bounded by
    Finding 1.
  - `_RECORDS` is a module-global singleton (`human_approval_check.py:189`).
- **Seat password / store / run directory: no reads.** Neither new module calls `open`
  or `read_text`. The only route out is `run_kit_command` (`teamchat_seat.py`, the new
  public seam), which:
  - runs `$KIT/bin/teamchat` through `default_command_runner`, after `_binary_trust`;
  - passes only `TEAMCHAT_RUNTIME` in the overlay;
  - uses the same path as the existing whoami probe.
- **The GO grant path is dead code in the handler**: `go` is never passed. It is harmless.
- **Chain semantics:** priority 21 runs after destructive_git (10), dangerous_permissions
  (15) and merge_to_main_approval (20). A terminal ALLOW never ends a PreToolUse chain
  (`core/chain.py:8-16`, `:581`), so a pass or an advise ALLOW does not relax later
  guards. Invariant 1 holds.
- **Wiring:** `team_seat` is threaded through cli → controller → registry
  (`cli.py:4592`, `controller.py:262/388`, `registry.py:906-909`). Other construction
  paths fall back to `TeamSeatConfig()` (`human_approval_check.py:231`).

## Refactor parity versus main

The refactored handlers behave the same as on main:

- **dangerous_permissions:** `sets_world_writable` is the old inline body moved verbatim.
- **merge_to_main_approval:** `merge_lands_on_main` keeps the same logic. Its only
  difference is that an unreadable branch returns None, and the old handler maps it back
  with `is True`, so None is still False there. The new handler maps None the other way:
  it counts as a merge into main (fail closed).
- **destructive_git:** the change only adds `names_a_deletion`.
- **teamchat_seat:** `decode_json_document`, `kit_argv` and `run_kit_command` are pure
  extractions. `parse_whoami` and `_probe` return the same ProbeReasons as before.
- The targeted tests pass (534).
