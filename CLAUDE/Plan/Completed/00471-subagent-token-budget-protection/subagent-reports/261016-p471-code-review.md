# Plan 00471 code review: branch `worktree-p471-spend-levers` (head 83d0b509a)

Reviewer: code-reviewer (Opus 5.5), 2026-10-16. Scope: `git diff main...worktree-p471-spend-levers`
(59 files, +6,794/-85). Read first: PLAN.md, RULINGS-fable.md, the implementer report
`261015-p471-build-implementer.md`.

**Evidence.** Probe script `untracked/scratch/p471-review/probe_p471.py`, output in
`untracked/scratch/p471-review/probe_output.txt`. Run it with
`/workspace/.venv/bin/python -I untracked/scratch/p471-review/probe_p471.py` (it inserts the worktree `src/`
itself). Targeted pytest of the six new suites, run with `PYTHONPATH` on the worktree src: 109 passed.

**Counts.** 2 blockers, 6 should-fix, 7 nits.

## Checks that passed

- **Hard mode ships off everywhere.** `hard_tokens: null` is set in `.claude/hooks-daemon.yaml:688`,
  `.claude/hooks-daemon.yaml.example:349` and `daemon/init_config.py:297`.
- **Client defaults match the rulings.** Soft 300k; resume guard `advise` at 250k; concurrency cap off;
  five-hour 80; review advisor off. This repo: soft 150k, resume `deny` at 150k, cap 4, five-hour 70,
  review on.
- **Missing or unreadable transcripts fail open with one record.** Both cases allow and write one
  `unmeasured` record per `(agent_id, reason)`, using an `O_EXCL` marker
  (`utils/spend_ledger.py:163-201`). Tests assert one record for four calls.
- **No double registration remains.** The only cross-handler class imports are the pre-existing
  re-exports in `handlers/status_line/__init__.py`. `TestEachHandlerOnce` passes.
- **No new handler is SAFETY-tagged**, so an exception fails open in non-strict mode (see S5 for strict
  mode).
- **Rule IDs and docs are complete.** Each rule ID is unique; CLAUDE.md table rows and markers are
  present; every new handler has acceptance tests (harness-undrivable ones are declared so); the
  `v3.70.0` config manifest lists all seven handlers.
- **Hook-time cost is bounded on the normal path.** It is a 64 KB tail with doubling, and the offset
  cache is used only at SubagentStop and by the CLI. The exception is B2.
- **Measurement is correct.**
  - Context is `input + cache_read + cache_creation` (`utils/transcript_tail.py:78-84`).
  - The resolver accepts both path shapes the Q5 ruling names (`transcript_tail.py:263-280`).
  - Dedup works by `requestId` with output-delta folding.

## Blockers

### B1. resume_guard denies structured protocol messages and names an override they cannot carry

**Location.** `handlers/pre_tool_use/resume_guard.py:197-219`. The behaviour is enshrined by
`tests/unit/handlers/pre_tool_use/test_resume_guard.py:161-166`. This repo runs `mode: deny` at 150k
(`.claude/hooks-daemon.yaml:698-699`).

**Problem.** `SendMessage.message` may be an object (`plan_approval_response`, `shutdown_request`,
`shutdown_response`). For an object, `first_line` is `""`, so the `RESUME-LARGE:` override can never
match. The deny reason still tells the caller to "start the message with `RESUME-LARGE: <reason>`",
which is impossible.

**Failure scenario (probe 5).**
1. A teammate at 300k context finishes its plan and sends `plan_approval_request`. Its turn ends with
   `end_turn`.
2. The coordinator takes more than 5 minutes to review the plan.
3. The coordinator's `{"type": "plan_approval_response", "approve": true}` is DENIED.
4. No message shape gets the approval through. The agent stays in plan mode with its work unapproved,
   and the coordinator's only route is a fresh spawn, which discards the plan the agent built. This is
   a lost-work lockout of a protocol flow.

A `shutdown_request` to a finished large teammate is denied the same way. TaskStop is a workaround
for that case only.

**Fix.**
- Never gate a non-string `message`: return ALLOW, optionally with advisory context.
- Replace the test at `test_resume_guard.py:161` with one asserting that `plan_approval_response` and
  `shutdown_request` are allowed under `mode: deny`.

### B2. A transcript with no recognisable usage is read whole on every call, silently

**Location.**
- `utils/transcript_tail.py:178-204`: the window doubles with no cap until `start == 0`.
- `handlers/pre_tool_use/subagent_context_budget.py:311-312`: `reading is None` returns ALLOW with no
  record.
- The behaviour is enshrined by `tests/unit/handlers/pre_tool_use/test_subagent_context_budget.py:154-160`,
  which asserts `unmeasured_count == 0`.

**Problem.**
- `read_tail` reports "no usage found" by doubling the window until it has read the whole file. The
  doublings re-read the same bytes, so one call reads about 3x the file.
- The budget gate treats `None` as "a fresh agent". So when Claude Code renames or moves `usage`, every
  subagent tool call pays a whole-file read and the gate is off with zero `unmeasured` records.
- That is exactly the silent fail-open RULINGS Q2 rejects ("Failing open silently would hide the same
  format change"). It is also the per-call cost that grows with transcript size, which focus item 2
  forbids.

**Failure scenario (probes 1 and 2).**

| Transcript with no usage | Bytes read per tool call | Time per call |
| ------------------------ | ------------------------ | ------------- |
| 1 MB                     | 3.1 MB                   | 10.6 ms       |
| 8 MB                     | 25 MB                    | 100.7 ms      |
| 32 MB                    | 100 MB                   | 353 ms        |

- The measured giant transcript was 48.9 MB, so the day the format changes, each such agent costs about
  0.5 s of hook time on every tool call.
- Probe 2 ran three calls against a 400k-context transcript with `usage` renamed: all three were
  `allow`, and `unmeasured_count` was 0.
- `resume_guard` (`:169`), `spawn_rate_advisor._cold_resume` (`:164`) and `session_load.live_agents`
  (`:126`) share the uncapped miss path.

**Fix.**
- Cap the window (for example a `MAX_WINDOW_BYTES` of 4 MB, well above the 264 KB largest line) and
  return a distinct result when the cap is hit without usage.
- Make the budget gate record `unmeasured` with reason `no-usage-in-tail` when the cap is hit, or when
  the file is larger than a fresh-agent bound (for example 256 KB) and holds no usage.
- Keep `None` (allow, no record) only for a genuinely small fresh transcript.
- Add a read-count test for the miss path (1 MB and 8 MB with no usage: bounded reads), and change
  `test_fresh_agent_with_no_usage_is_silent_and_measured` to cover both the small and the large case.

## Should-fix

### S1. The handoff path, with a CLAUDE/Plan glob, is computed on every subagent tool call

**Location.** `handlers/pre_tool_use/subagent_context_budget.py:318`; it calls `handoff_path` at
`:152-174`.

**Problem.** `target = self._handoff_target(hook_input)` runs before any band check. When the agent's
name or cwd carries a plan key, that means an `is_dir` check plus a `glob` over `CLAUDE/Plan/` (about
500 entries) for the cwd and the project root, on every tool call of every subagent.

**Scenario (probe 3).** Five calls at 10k context (soft is 150k) ran `handoff_path` five times. It is
needed only in the soft-crossing and hard branches.

**Fix.** Compute `target` lazily inside the two band branches.

### S2. The hard-band Bash allowlist splits inside quotes and rejects ordinary commit idioms

**Location.** `handlers/pre_tool_use/subagent_context_budget.py:108-112` and `:440-453`.

**Problem.**
- `_SEGMENT_SPLIT` splits on `;`, `|` and newline with no quote awareness.
- `_HIDDEN_EXECUTION` rejects `$(`, which this repo's standard commit form uses:
  `git commit -m "$(cat <<'EOF' … EOF)"`.
- The deny reason does not name the shape that works, `git commit -F <file under a handoff glob>`.

**Scenario (probe 4).**
- `git commit -m 'WIP: parser done; tests left'` is denied.
- The heredoc commit idiom is denied.
- `cd '/path with space' && git status` is denied.
- A WIP commit with a co-author trailer cannot be made the usual way. The agent burns its three
  escalation strikes on retries at more than `hard_tokens`, and every retry re-reads the whole context.

This does not block shipping, since hard mode is off, but it must be fixed before the owner sets
`hard_tokens`.

**Fix.**
- Split with `shlex` (punctuation_chars) so that quoted separators survive.
- Allow `git commit -F <path>` when the path matches the handoff globs.
- Make the deny reason say: "write the message to `untracked/scratch/<x>` and `git commit -F` it".
- Add the probe's commands to the allowlist matrix.

### S3. The handoff gate demands a file from agents that cannot write one

**Location.** `handlers/subagent_stop/subagent_handoff_gate.py:95-120`, and the deny text at
`subagent_context_budget.py:401-423`.

**Problem.** Some agent definitions have no Write tool: this `code-reviewer`, Explore-type scouts.
Under the hard band such an agent can only use Bash `git …` and SendMessage. Yet the gate blocks its
stop three times, demanding a file, and each blocked stop is a full turn at more than `hard_tokens`.

**Fix.**
- Record a SendMessage made while hard-engaged as `handoff_sent` in the state document, and let the gate
  accept it.
- Make the deny reason say "if you cannot Write, SendMessage the lead your handoff and stop".

### S4. `strict_mode: true` in this repo turns any exception in these handlers into a deny of every call

**Location.**
- `.claude/hooks-daemon.yaml:8` (`daemon.strict_mode: true`, wired since Plan 00466 N24, see
  `daemon/controller.py:310`).
- `core/chain.py:1185-1199`: in strict mode, a handler crash denies.
- `handlers/pre_tool_use/subagent_context_budget.py:302-306`: `resolve_agent_transcript` runs outside
  the `try`.

**Problem.**
- The "fails open" guarantee holds only for the exceptions each call site catches. Under strict mode,
  anything else denies the call with "SYSTEM ERROR … blocking for safety" and ends the chain. For
  `subagent_context_budget`, which runs on every subagent tool call, that is a whole-session subagent
  lockout, handoff steps included.
- On this interpreter (Python 3.11), `Path.is_file()` propagates `PermissionError` (EACCES). The raw
  `is_file()` calls in `resolve_agent_transcript` (`transcript_tail.py:275, 280`) are reached unguarded
  from `handle()`.
- The eacces_safe QA check flagged the handler-level calls but not these utils.

**Scenario.** A daemon user without search permission on the `<session>/subagents` directory gets
every subagent tool call denied.

**Fix.**
- Move the resolve step inside the `try`, catching `OSError` and recording `transcript-unreadable`.
- Switch `transcript_tail.py:248, 250, 275, 280` to `utils.path_predicates`.
- Consider a top-level `except Exception` in each of the three cost gates that records `unmeasured`
  (reason `handler-error`) and allows, since a cost control must not fall under the strict-mode deny.

### S5. The five-hour advisory reads a sidecar that ships off for clients, duplicating an existing source

**Location.**
- `handlers/pre_tool_use/spawn_rate_advisor.py:134-151` and `utils/session_load.py:237-253` read
  `untracked/context-sidecar/<session>.json`.
- `handlers/status_line/context_sidecar.py` gains `_read_five_hour`.

**Problem.**
- `context_sidecar` is `enabled: false` in `.claude/hooks-daemon.yaml.example:968-970` and in the init
  template, so the client default `advise_pct: 80` (`init_config.py:299`) can never fire. The example
  even says "needs status_line.context_sidecar".
- The daemon already holds this exact figure: `core.data_layer.latest_usage`, which the controller
  fills from `rate_limits` on every Status event. `usage_indicator` uses it (see its docstring, lines
  9-15).
- This is a second, weaker source of the same fact (a DRY violation). It also misses the
  "past `resets_at` means absent" rule the shared snapshot applies.

**Fix.** Read `latest_usage()` in `spawn_rate_advisor` and drop `five_hour_pct`/`resets_at` from the
context sidecar, unless ccy needs them. Record the deviation from the ruling's wording ("context_sidecar
gains…") in the journal: the ruling predates the shared snapshot.

### S6. The offset cache keeps every request id in memory forever and rewrites it whole on each save

**Location.** `utils/transcript_spend.py:132-153` (`seen_ids` serialised whole), `:251-254` (the
`_entries` dict is never evicted), and `utils/spend_ledger.py:49` (the process-wide `_caches`).

**Problem.**
- Each transcript's `_Entry` holds every `requestId` it has ever seen. It stays in a daemon-lifetime
  dict and is re-serialised in full on every save.
- Probe 6: 1,000 requests give a 34 KB sidecar; 5,000 requests give 166 KB.
- At the measured 584 agents per session, the daemon keeps every request id of the session resident
  until restart.
- `spend-ledger/offsets/` gains one file per transcript, and nothing prunes it.

**Fix.**
- Evict an entry from `_entries` after its SubagentStop write; it reloads from the sidecar.
- Bound `seen_ids`. It only needs to cover replayed history; for example, keep ids from the last N MB,
  or store a compact digest set.
- Prune the offsets and per-session ledger directories under the existing `stale_file_days` cleanup.

## Nits

- **N1.** `utils/transcript_spend.py:211`: `totals.ite += 5.0 * delta` hard-codes the output weight that
  `transcript_tail._WEIGHT_OUTPUT` defines. Export the constant and use it.
- **N2.** `daemon/cli.py:4955`: the fallback `transcript.parent / session_id` is unreachable, because
  `subagents_dir` never returns None for a non-empty stem. It would also name the wrong directory
  (missing `/subagents`). Delete the fallback.
- **N3.** Every SendMessage resolves and tail-reads the same target twice: in `resume_guard` (`:166-170`)
  and again in `spawn_rate_advisor._cold_resume` (`:157-168`). That is two scandirs of a directory with
  about 584 entries. The advisor also uses `DEFAULT_WARM_SECONDS` rather than the configured
  `resume_guard.warm_seconds`. Share one resolved reading per event, or read the option.
- **N4.** `utils/session_load.py:149-171`: `record_background_tasks` replaces the `finished` set
  wholesale, and both Stop (`background_task_recorder`) and every SubagentStop (the aggregator) write it.
  The last writer wins. If a SubagentStop's `background_tasks` is scoped to that subagent, it erases the
  coordinator's reconciliation. Merge per source, or record the source, before using this as deny-mode
  evidence.
- **N5.** `utils/session_load.py:118`: an agent inside a long tool call writes nothing for more than
  `liveness_seconds` (120); a 10-minute pytest is the common case. Such an agent is not counted live.
  This is fine for an advisory, but the ledger evidence for a deny mode will undercount. Note it in the
  deferred L4 item.
- **N6.** `subagent_context_budget.py:425-438`: the hard-band allowlist lacks `ToolSearch` (and
  `TaskStop`). The repo's own usage-pause tool gate allowlists ToolSearch so that a deferred SendMessage
  can still be loaded. Add it.
- **N7.** `handlers/pre_tool_use/review_round_advisor.py:119-123` appends the `review-round-advisory`
  ledger event in `handle()`, before the chain decides. HANDLER_DEVELOPMENT.md ("Side effects run before
  the decision — commit them after it") puts it in `commit_side_effects`, where the counter already is.
  As written, a denied dispatch still logs an advisory event, which pollutes the evidence the rulings
  want.

## Positive observations

- The double-registration fix is real, and `TestEachHandlerOnce` guards the whole registry, not just
  this handler.
- The offset cache is careful:
  - inode and shrink reset;
  - torn final lines are left for the next read;
  - per-request dedup folds streaming output deltas;
  - each of these has a test.
- Fail-open on missing or unreadable transcripts is tested to cost exactly one record.
- The hard band is never a kill:
  - escalation after three denials;
  - the stop gate gives way after three blocks;
  - SendMessage is always allowed.
- Red-first evidence is recorded per lever.

## Verdict

REQUEST CHANGES.
- **Before merge:** B1 and B2. B1 traps a protocol flow under this repo's shipped deny config. B2
  breaks the ruling's Q2 guarantee and the hook-time cost bound in the exact scenario Q2 exists for.
- **Before the owner enables `hard_tokens`:** S2, S3 and S4.
- **The rest:** file as plan follow-ups.
