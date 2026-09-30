# Release code review — lifecycle handlers (v3.64.0..HEAD)

RELEASING.md Step 10 gate. Reviewed by the `review-lifecycle` teammate.

## Scope

Diff `v3.64.0..HEAD`, restricted to:

- `src/claude_code_hooks_daemon/handlers/session_start/` — new
  `guard_config_drift.py`, `routine_qa_sweep.py`, `session_actions_directive.py`;
  modified `gitignore_safety_checker.py`, `hook_registration_checker.py`,
  `persistent_cron_assertor.py`, `project_handler_load_checker.py`, `__init__.py`
- `src/claude_code_hooks_daemon/handlers/stop/` — new `cron_stop_enforcer.py`,
  `teammate_reap_advisor.py`; modified `__init__.py`
- `src/claude_code_hooks_daemon/handlers/subagent_stop/` — new
  `cron_subagent_stop_enforcer.py`; modified `__init__.py`
- `src/claude_code_hooks_daemon/handlers/status_line/` — new `host_hostname.py`;
  modified `__init__.py`
- `src/claude_code_hooks_daemon/handlers/user_prompt_submit/` — **no changes in range**

1576 insertions / 27 deletions across 15 files. The supporting modules the new
handlers are thin wrappers over were read too, since the reviewable behaviour
lives there: `utils/cron_enforcement.py`, `utils/host_identity.py`,
`utils/guard_config_drift.py`, `core/session_start_tiers.py`.

## Caveat on verification

`pytest` is not installed in this container — `.venv/bin/python` has no pytest
module — so **the test suite was not executed**. Every claim below was instead
verified by executing the library code directly through `.venv/bin/python`, or
by reading the test modules. I am not asserting the suite is green.

## Result

**2 DEFECT, 7 NON-DEFECT. Verdict: REQUEST CHANGES.**

---

## Stop-chain ordering — the specific thing asked about

**Verified correct.** Live instantiation of every handler registered on the
blocking lifecycle events:

| handler | event | priority | terminal | default |
|---|---|---|---|---|
| `cron-stop-enforcer` | Stop | 7 | False | on |
| `teammate-reap-advisor` | Stop | 9 | False | on |
| `auto-continue-stop` | Stop | 15 (10 via project config) | **True** | on |
| `cron-subagent-stop-enforcer` | SubagentStop | 7 | False | on |
| `subagent-report-size-blocker` | SubagentStop | 15 | **True** | on |

Both new Stop handlers and the SubagentStop twin sit numerically BELOW the
terminal catch-all on their event, so neither is shadowed on a blocked stop.
Both are `terminal=False`, which matters because both match near-universally
(`cron_stop_enforcer` whenever any job is declared; `teammate_reap_advisor`
whenever `background_tasks` is non-empty) — terminal placement there would have
made each a new shadow for everything behind it.

`tests/integration/test_stop_chain_terminal_shadowing.py:336` enforces this
registry-wide, and does so behaviourally: it walks the real chain and finds the
first terminal handler that MATCHES, so it correctly tolerates `release_blocker`
sitting at priority 8 as terminal-but-narrow.

No ordering defect found.

---

## DEFECTS

### D1 — `gitignore_safety_checker` derives its never-commit list from the SHIPPED defaults, not the project's effective protected set

**Location:** `src/claude_code_hooks_daemon/handlers/session_start/gitignore_safety_checker.py:44-71`

**The contract the code states.** The new `_protected_pattern_entries()`
docstring: "A file whose contents may never be read into context certainly may
never enter git history, so the never-commit list must cover the never-read
one". The change is framed explicitly as closing F-HYG-1 — a hand-written
approximation of a glob is not the glob.

**What it actually reads.** `DEFAULT_PROTECTED_PATTERNS`, the six SHIPPED globs.
The effective never-read set is `resolve_configured_patterns()`, which merges a
project's own `protected_paths` option on the secret-file guard handler onto the
defaults — additive is the default mode
(`utils/secret_file_matching.py:215-231`).

**Failure scenario, verified by execution.** A project adds `*.creds` to
`secret_file_guard.options.protected_paths`:

```
effective protected globs (additive):  7
required gitignore entries derived:    9   (3 static + 6 shipped defaults)
is *.creds in the required list?       False
```

`secret_file_guard` then refuses to read `deploy.creds` by any route, while
`gitignore_safety_checker` never once advises the project to gitignore it — so
the file is committable, silently. That is precisely the gap the change claims
to close. The `replace` mode fails in the other direction: the advisory demands
gitignore entries for globs that are no longer protected at all.

**Secondary.** `_REQUIRED_GITIGNORE_PATTERNS` is evaluated at **module import
time** (line 71), so even swapping the call would freeze the answer at first
import rather than following the loaded config.

**Suggested fix.** Call `resolve_configured_patterns()` from inside
`_find_missing_entries()` — call time, not import time — and build the derived
entries there. That function already carries a process-lifetime cache and already
fails open to the shipped defaults, so this costs nothing and preserves the
fail-open direction the module wants.

---

### D2 — `guard_config_drift`'s remediation instructs a command this daemon denies

**Location:** `src/claude_code_hooks_daemon/handlers/session_start/guard_config_drift.py:207-210`

The advisory closes by telling the agent to restore the config with a
`git checkout HEAD` invocation carrying the config file as a pathspec.

That exact form is matched and DENIED by this project's own `destructive_git`
handler — `src/claude_code_hooks_daemon/handlers/pre_tool_use/destructive_git.py:101-105`
names the checkout-with-pathspec shape in its own comment, `HEAD` ref included.

**Failure scenario, verified live.** Drift is detected, the agent reads the
advisory, runs the command it was handed, and `R-GIT-CHECKOUT-DISCARD` denies it
with "The LLM is NOT ALLOWED to run destructive git commands. Ask the user to do
it." A turn is spent and the drift the handler exists to surface is still
unfixed. I hit this deny myself while probing the pattern — the block fires on
the mere presence of that command shape in a Bash command, which is also why
this report words it in prose rather than quoting it.

The handler is default-enabled and matches every session start, including
resumes, so this is the advisory's normal path rather than an edge case.

**Suggested fix.** One line in `_render`: word the remedy as a hand-off the
daemon permits (ask the user to run the restore, noting the LLM is blocked from
it), or point at a `git diff` review plus an explicit hand-off. The existing
acceptance test asserts on `GUARD CONFIG DRIFT|uncommitted`, not on this
sentence, so no test churn.

---

## NON-DEFECTS

### N1 — the Priority Guide now contradicts what ships, and steers a new Stop handler into the shadow

**Location:** `CLAUDE/HANDLER_DEVELOPMENT.md:506`, `src/claude_code_hooks_daemon/constants/priority.py:8`

The table row reads: `0-9 | Test | Reserved for purpose-built test fixtures
(Priority.TEST_HANDLER); no built-in handlers ship here`.

After this release, built-in handlers ship at 6 (`HOST_HOSTNAME`), 7
(`CRON_STOP_ENFORCER`, `CRON_SUBAGENT_STOP_ENFORCER`) and 9
(`TEAMMATE_REAP_ADVISOR`). The status-line band already occupied 2-5, so the row
was partly wrong before; this release makes it wrong on the blocking events too.

Why this matters beyond accuracy: the guide's next row says 10-20 is the safety
band. An author adding a new Stop handler and following the guide lands at 10+,
lands after the terminal catch-all, and is silently unreachable on every stop
lacking a `STOPPING BECAUSE:` line — the exact hazard the rest of this release
spends three module docstrings and an integration test hardening against. The
guide is the one document that does not warn about it.

**Suggested fix.** Amend the 0-9 row to record the Stop/SubagentStop exception
and add a one-line pointer to `test_stop_chain_terminal_shadowing.py`.

### N2 — both cron enforcers parse the full config twice per event, uncached

**Location:** `handlers/stop/cron_stop_enforcer.py:94-113` and `:115-135`;
`handlers/subagent_stop/cron_subagent_stop_enforcer.py:78-92` and `:94-112`

`matches()` calls `_active_jobs()` to `_load_config()` to
`Config.load_or_default()`, and `handle()` calls `_active_jobs()` again.
`Config.load_or_default` has no cache (`config/models.py:2160-2174`) — it
re-reads and re-validates the YAML on each call.

Measured warm against this repository's own 68,605-byte config:

```
median 81.5 ms   min 73.3   max 119.7   (per load_or_default)
```

So roughly 165 ms is added to every Stop event here, and the same again on every
SubagentStop. A project that declares no crons still pays the `matches()` half
on every stop for a handler that then returns False. Client configs are smaller,
so the absolute number will be lower — but the work is pure waste either way,
since daemon config changes only take effect on restart.

**Suggested fix.** A process-lifetime cache, exactly the shape
`utils/secret_file_matching.resolve_configured_patterns()` already uses and
documents. At minimum, have `handle()` reuse what `matches()` computed.

### N3 — `_should_advise` and its two constants are a verbatim copy

**Location:** `handlers/stop/teammate_reap_advisor.py:59-62, 137-147` vs
`handlers/post_tool_use/background_process_tracker.py:52, 226, 259-269`

`_COUNT_START`, `_MAX_TRACKED_SESSIONS` and the whole `_should_advise` body
(including the insertion-order eviction) are identical. Three docstrings say
"mirroring background_process_tracker", which is the honest admission that this
is a copy. Two copies of a bounded-LRU-plus-modulo rate limiter will drift.

**Suggested fix.** Extract to `utils/` (e.g. `SessionAdviceRateLimiter`) and have
both handlers hold one. The interval stays per-handler; only the mechanism is
shared.

**Related, not a separate finding.** Handler dispatch runs in a thread pool
(`daemon/server.py:1443` — `run_in_executor(None, self.controller.dispatch, ...)`),
so `_session_counts` is touched concurrently, and the `len(...) >= MAX` check
followed by `del self._session_counts[next(iter(...))]` can raise `KeyError`
under a race. This is PRE-EXISTING — identical code in
`background_process_tracker` — not introduced by this release. A shared
extraction is the natural place to put the lock both are missing.

### N4 — `stop/__init__.py` names the wrong priority, in the file a new author is told to read

**Location:** `src/claude_code_hooks_daemon/handlers/stop/__init__.py:11`

> Plan 00416's ``cron_stop_enforcer`` therefore sits BEFORE it (priority 8)

It is priority 7. 8 is the `release_blocker` project handler — and
`constants/priority.py:113-117` explains at length that 7 was chosen precisely
because 8 was taken. The module docstring at `cron_stop_enforcer.py:12` says 7
correctly; only the package `__init__` is wrong. Since this docstring exists to
orient someone adding a Stop handler, a wrong number here is worse than average
doc drift.

### N5 — `resolve_host_name`'s ladder short-circuits instead of falling through

**Location:** `src/claude_code_hooks_daemon/utils/host_identity.py:258-268`

The module docstring presents a four-rung ladder, "first hit wins", with the
hosts file as rung 3. In the code, when the runtime is host-or-LXC and
`_clean_host_name(socket.gethostname())` returns `None` (name longer than 64
characters, or carrying a character outside the allowlist), the function returns
`None` immediately rather than trying rung 3.

**Scenario.** A Debian host whose hosts file carries a `127.0.1.1 mybox`
self-alias but whose kernel hostname is over the cap renders no segment, where
the documented ladder says it should render the inferred `mybox`.

Defensible as written — on a host, `gethostname()` is the authoritative answer
and a bad one is not improved by guessing — which is why this is a judgement
call rather than a defect. But the code says something the docstring does not.
Either fall through, or add a sentence at line 263 saying why not.

### N6 — two unit tests assert against the shipped priority, not the effective one

**Location:** `tests/unit/handlers/stop/test_cron_stop_enforcer.py:201-205`,
`tests/unit/handlers/stop/test_teammate_reap_advisor.py:168-174`

Both assert `priority < Priority.AUTO_CONTINUE_STOP`, i.e. `< 15`. This project
overrides `auto_continue_stop` to 10. A handler placed at 12 would pass both unit
tests while being shadowed in this very repository.

The invariant IS covered — `test_stop_chain_terminal_shadowing.py` walks the
configured chain — but each test's own docstring claims more than its assertion
delivers.

**Suggested fix.** Read the effective priority from config in these assertions,
or shorten the docstrings to "below the shipped terminal priority" and let the
integration test carry the real claim.

### N7 — a prompt that is nothing but a truncation marker matches any declared job

**Location:** `src/claude_code_hooks_daemon/utils/cron_enforcement.py:147-165`

Verified: `_prompts_match('<any declared prompt>', '... [+4000 chars]')` returns
**True**. Stripping the marker leaves `""`, `_was_truncated` is True because the
stripped text differs from the delivered text, and `declared_norm.startswith("")`
is trivially True — so a `session_crons` entry carrying a degenerate prompt
satisfies any declared job sharing its schedule.

This fails in the ALLOW direction: the enforcer reports a missing cron as
present and lets the stop through. Contrived — nothing plausibly delivers a
prompt that is only a marker — and the safe failure direction matters given the
alternative failure mode here is blocking every stop forever. Hence a judgement
call, not a defect.

**Suggested fix.** One line at the top of the truncated branch:
`if not delivered_norm: return False`.

---

## What is done well

Recorded because several of these are the reason the defect count is as low as
it is.

- **`utils/cron_enforcement.py`** is the strongest module in the range. It
  enumerates four contract constraints and marks the fourth as *measured after
  the first three shipped and the handler still blocked every stop*, drawing the
  right general lesson: a delivery MECHANISM and a delivery PATH are different
  things to reason about. The absent-vs-empty distinction is threaded correctly
  through `parse_session_crons`, `handle` and the tests, and the "prefix matching
  ONLY when truncation actually occurred" restriction is the non-obvious call
  that keeps the check honest.
- **`utils/host_identity.py:106`** uses a character ALLOWLIST for a value printed
  to a terminal once a second, and explains why a blocklist cannot work (OSC
  sequences, cursor repositioning). It refuses rather than strips, and refuses to
  log the rejected value because a log is read in a terminal too. It also
  declines to add a config option specifically because the config file is tracked
  and routinely public. No shell invocation anywhere.
- **`core/session_start_tiers.py`** makes `ACTION_REQUIRED` unreachable by
  declaration through three independent barriers: `_DECLARABLE_TIERS` excludes
  it, the constructor raises on it, and `compute_tier` clamps a directly-tampered
  attribute back to `INFO`.
- **`hook_registration_checker.verify_still_needed`** deliberately skips the
  self-heal path that `handle` runs, because a verifier is also invoked by
  `hooks-daemon session-actions`, which a human runs to INSPECT a session.
  Read-only by construction, with the accepted cost (a momentarily pessimistic
  tier) named in the docstring.
- **`tests/unit/handlers/stop/test_teammate_reap_advisor.py:127`** proves the deny
  path is UNREACHABLE by reading the module source, not merely untaken by one
  call. Fixtures are reconstructed from a captured payload with the capture
  cited. No theatre anywhere in the new test modules — every assertion I read
  would fail if the behaviour regressed.

## Step 10 checklist verdicts

| Item | Verdict |
|---|---|
| No bugs in `matches()`/`handle()` | D1 (coverage gap), D2 (unusable remediation); otherwise clean |
| Stop chain priority vs terminal | **Correct** — verified live for all five registered handlers |
| Security anti-patterns | **None.** No shell, no `subprocess(shell=True)`, no interpolated commands, no hardcoded secrets. `yaml.safe_load` throughout; host name allowlist-sanitised |
| Handler priority ranges | Correct against the terminal-shadowing constraint; the DOCUMENTED band table is stale (N1) |
| Tests alongside every handler change | **Yes** — 7 new/extended modules, 97 new test functions, plus the tier and chain integration modules. Not executed here (no pytest in container) |
| Magic strings/numbers | Clean. `ADVISE_INTERVAL` is public specifically so its test cannot hold a second copy of the number |
| SOLID / no if-elif on type names | Clean. `session_start_tiers` duck-types deliberately and documents why |
| Debug code / workarounds / TODOs | **None** — no `TODO`, `FIXME`, `XXX`, `HACK`, `print(` or `breakpoint` on any added line |

## Verdict

**REQUEST CHANGES.** D1 and D2 must be fixed before the release ships: D1 is a
fail-open gap against the invariant the change itself states, and D2 ships an
instruction the daemon denies. Both are small and localised. N1-N7 are
non-blocking and are stated with file:line, scenario and remediation so each can
be filed verbatim as a plan task.
