# Issue #125 implementer report (Plan 00537, Opus)

Plan work: this covers Plan 00537 Tasks 1.1–1.4, 2.1 (investigation only) and 3.1. Branch
`worktree-plan-00537`. Commits:

- `d3dab01d1` code and tests
- `249c9a341` docs, release note, journal and PLAN ticks
- this report's commit (hash in the reply to the lead)

## What changed

All code is in `.claude/ccy/claude-supervise.py`. Tests are in the new
`tests/unit/supervise/test_main_focus_hold.py` (47 tests).

- **Task 1.1: `MainFocusModel` and `FocusHold`.** A new class with its own small
  ANSI parser, fed by `InputActivity.record` alongside `HumanInputLine`.
  `HumanInputLine` and `_finish_csi` are unchanged; a test confirms an Up still
  counts as box content there.
  - It latches on a bare Up/Down. I extended this to SS3 `ESC O A/B`, the same
    key in application-cursor mode, because the ruling says to fail toward hold.
    Arrows with parameters, Left/Right, and anything inside a bracketed paste do
    not latch.
  - Enter while latched keeps the hold and rewords its reason. `since` stays at
    the navigation time.
  - Only a bare Esc clears the hold: an ESC followed by ESC or by a
    non-introducer, or an ESC that ends a read. In the last case the hold is
    restored if the next read shows a sequence after all.
  - Ctrl-C, Ctrl-U, Enter and child output never clear it.
- **Task 1.2.** `TickFacts` gains `main_focus_confirmed`, `focus_hold_reason`,
  `focus_held_since` and `focus_latch_bytes`, serialised both ways.
  - The host fills them from its long-lived model via `_with_focus_hold`. This
    covers both the worker path and the in-process `_poll_once`.
  - The field is ANDed into `can_inject`.
  - Judgement call: when the key is absent (an older host under a reloaded
    worker), it reads as confirmed. Defaulting to held would stop every send
    with no Esc able to end it. This is documented in `TickFacts` and in
    CcySupervisor.md.
- **Task 1.3: explicit gates.**
  - The model switch.
  - The abandoned-box flush, in `_evaluate_monitor` AHEAD of the one-shot
    `_abandoned_box_handled`, so a held flush is not spent.
  - The usage-pause compact. The gate is inside `_usage_pause_outcome`, which
    bypasses `can_inject` and applies its own copy of it (idle, work idle,
    empty box).
  - `RestartCoordinator.request(focus_hold=...)`. A held `/exit` returns False
    before `_perform_injection`. It creates no `_PendingRestart`, does not call
    `mark_own_line_typed`, adds no abandon count and starts no cooldown.
  - `_apply_decision(main_focus_confirmed=...)`, re-read from the host model at
    apply time. This catches a payload the worker decided before an Up arrived
    mid-tick. It is passed through `handle_plugin_outcome` and the host loop.
  - ESC and resubmit are covered by the `can_inject` AND, which is tested. The
    dry-run marker is held and its once-only fuse is not spent.
  - An AST test pins the `_perform_injection(` call sites to
    `{_apply_decision, RestartCoordinator.request}`.
- **Task 1.4: visibility.**
  - `CompactStateMachine.focus_hold_log` writes the `injection deferred: main-thread focus unconfirmed (<family> pending; latched by <reason>[; held N min][; latching bytes ...])` line. It is rate-limited to one line per family
    per 60 s, plus one at every escalation-level change. The rate-limit state
    round-trips through `export_state` and `import_state`.
  - `_note_focus_hold` posts the WARNING banner on every held tick, with louder
    wording past the first bound.
  - Every `elif not can_inject` family branch attributes the defer to focus
    when `facts.idle`.
  - New option `CCY_FOCUS_HOLD_ESCALATE_SECONDS="300,900"`, stored as
    `CompactPolicy.focus_hold_escalate_seconds`. Any value other than
    `0 < first < second` keeps the default.
- **Task 3.1.**
  - `CLAUDE/development/CcySupervisor.md` has a new focus-hold section. Its
    edit-to-live note says this change is host-side and needs a ccy relaunch.
    It also gives the verification steps.
  - A commented pointer in `.claude/ccy/ccy.env`.
  - Release callout:
    `CLAUDE/UPGRADES/UNRELEASED/release-notes/003-supervisor-holds-sends-while-focus-may-be-on-a-sub-agent.md`.

## Red before green

- **Red:** before any implementation, the new test file failed at collection:
  `AttributeError: module 'claude_supervise_standalone' has no attribute 'FocusHold'`.
- **Green:** 47 passed.
- **Per-task proof** (`untracked/scratch/mutation_check_125.py`): each gate was
  disabled in turn in a copy of the supervisor, and the test file was run
  against that copy. All 10 mutants went RED:

| Task | Gate disabled          | Tests failed |
| ---- | ---------------------- | ------------ |
| 1.2  | `can_inject` AND       | 6            |
| 1.1  | Esc clears             | 1            |
| 1.1  | arrow latches          | 10           |
| 1.3  | model switch           | 1            |
| 1.3  | abandoned flush        | 1            |
| 1.3  | usage pause            | 1            |
| 1.3  | restart `/exit`        | 1            |
| 1.3  | `_apply_decision` belt | 1            |
| 1.4  | rate limit             | 2            |
| 1.4  | banner                 | 2            |

One test was wrong at first. It waited 600 s in AWAIT, past the await timeout,
which re-entered MONITOR. I corrected the test's timing, not the code.

## Task 2.1 finding (journalled, nothing implemented)

The live sub-agent snapshot CAN under-report a started agent:

- It refreshes only on Stop/SubagentStop.
- It uses a 120 s transcript liveness window, so an agent blocked in a long
  tool call or waiting on a permission prompt drops out.
- It skips agents whose turn ended, even though their panel rows remain.
- Its `finished` set matches by description, so a reused name collides.
- It counts RUNNING agents, not selectable rows or transcripts.

So it is not a clearing signal. The full entry is in
`JOURNAL/00537-Journal-26-10-20.md`. It belongs with the Task 3.2 non-screen
focus-signal spike.

Ruling task 0 was NOT verified live. That is the question of whether Esc closes
an OPEN transcript. The brief forbids touching the live session, and the
vendored docs document Esc only for a selected row. I followed the brief: a
single Esc clears the hold. The residual risk is recorded in the journal and in
CcySupervisor.md, for the follow-up plan to verify.

## QA

- `pytest tests/unit/supervise`: 1380 passed, 1 skipped.
- `./scripts/qa/llm_qa.py changed --allow-unmapped`: exit 1, 36/40 passed.
  `--allow-unmapped` is needed because the supervisor's test reach is the whole
  `tests/unit/supervise` tree. That tree was run in full above and in
  `changed_tests`, where 1426 passed.
- The only failures are 4 ADVISE-level (0 block) `docs_qa` and `plan_qa`
  findings. They are in `00474/NIGGLES.md` and the PLAN.md files of Plans
  00534, 00535 and 00536, and they all link to the already-archived Plan 00533.
  This branch did not cause them. `project_handlers` and `changed_tests` read
  NOT MEANINGFUL only because of those two detectors.
- Format, lint, mypy, pyright and every other check are green.

## Not done (out of this brief)

- Task 3.2, the follow-up plan.
- A live dogfood check after a ccy relaunch. The coordinator or a human should
  run the steps in CcySupervisor.md.

## Review fixes

These answer `untracked/agent-reports/261020-issue125-review-opus.md`. Commits
`3e27d39b3` (fixes and tests) and `1ed3da37b` (black formatting).

**C1: an Esc that ended a read reinterpreted the next read.** Fixed in
`MainFocusModel`:

- A string sequence (OSC/DCS/APC/PM/SOS) can still open and close within one
  read, so a complete terminal reply such as `ESC ] 11;rgb… ESC \` never acts
  as a bare Esc. A string sequence left open at the end of a read is dropped.
- An ESC, `ESC [` or `ESC O` left open at the end of a read is kept PENDING,
  and any hold stays in place. The next read resolves it:
  - a completed Up/Down arrow is honoured (`_split_arrow`): with no
    parameters it latches, with parameters it neither latches nor releases;
  - a strict prefix of an arrow stays pending;
  - anything else makes the ESC a bare Esc, and the read is parsed from
    ground.
- With no further byte, `settle()` resolves the pending ESC as a bare Esc after
  `_FOCUS_ESC_SETTLE_SECONDS` (0.5 s). The host calls it every tick, and
  `feed()` calls it first, so letters arriving after the window are text.
- The focus model's paste state is bounded by `_PASTE_LATCH_MAX_BYTES`, like
  `HumanInputLine`, and inside a paste only `ESC [` is followed.

**I1: a send held at apply time was booked as sent.** The worker-outcome
application moved from `_on_poll` into `_apply_worker_outcome`. A payload the
host model refuses at apply time is handled like a failed PTY write: no
`import_state`, no bookkeeping, no `line.clear()`.

**I2: tests.** These were added to `test_main_focus_hold.py` (78 tests now):

- every probe case, A to F, plus one-read variants and `_`/`^` introducers;
- six split-arrow shapes;
- a split arrow with parameters;
- the pending Esc keeping the hold, for a lone Esc and for a prefix read;
- letters after the settle window;
- an open and a complete string sequence;
- the paste bound and a split paste end marker;
- `TestWorkerOutcomeHeldAtApply`, one test per family (compact, usage-pause
  compact, dry-run marker, abandoned flush, own line), plus controls that
  confirm a confirmed apply still adopts the state and clears the box.

The unused-lambda-parameter hint is fixed.

**Red before green.**

- The new tests failed at collection (`_FOCUS_ESC_SETTLE_SECONDS` absent).
- The reviewer's probe on the old code gave the wrong answer for A to E.
- After the fix, A to E are correct. F reads held in the probe only because the
  probe never calls `settle()`. That is the required "keep the hold until the
  Esc resolves" behaviour; the host settles every tick.
- The mutation check now has 15 mutants, including 5 for C1 and 1 for I1, and
  all 15 go RED. One survivor from a first run, a prefix read clearing the
  hold, was closed with a test.

**Suggestions not taken.**

- Writing the audit-flush line before the belt's early return. A held outcome's
  state is not adopted, so the audit backlog is re-flushed and logged on the
  next sent tick. Logging it now would duplicate it.
- Not overwriting a different live WARNING with the hold banner. Left as is: the
  hold banner is what tells the human how to unblock every send.

**Found, not fixed (outside this brief):** `HumanInputLine` has the same
carry-over. Its parser state persists across reads, and `_consume_esc` enters
string state on `P`, `X`, `]`, `^` or `_`. After a lone Esc, typing "Please…"
would therefore be swallowed, and the box would read empty while the human
types. That lets the supervisor paste over the human's text. It predates this
plan, and `_finish_csi` is off-limits under the ruling. It should be filed as
its own issue.

**QA after the fixes.**

- `pytest tests/unit/supervise`: 1411 passed, 1 skipped.
- `llm_qa.py changed --allow-unmapped`, on a still tree: 36/40, with format
  clean. The same 4 pre-existing ADVISE findings on the 00533 links remain, and
  `changed_tests` passed 1457.
