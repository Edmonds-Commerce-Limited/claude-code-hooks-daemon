# Niggles ledger sixteen: write-ups

Newest first. Each entry says how it was found, why it happens, and the
candidate remedies.

### N40 — ✅ Blockers/Majors/minors/nits all remedied — adversarial security review of the N24/N25/N34 fix (2 blockers, 3 majors, 6 minors, 4 nits)

**Found by an adversarial, read-only security review**
(`subagent-reports/260924-n466-n24-review-opus-5-5.md`) of `d7f2c875` (N24 +
N25 + N34 combined). Verdict: NOT READY — inputs existed that turned a
SAFETY+BLOCKING decision into ALLOW. Full report committed at `f8f2dfeb`.
Findings and remediation status, in the report's own order:

**B1 (blocker) — ✅ Remedied.** A lone UTF-16 surrogate anywhere in
`tool_input` crashed `_safety_payload_size` (`chain.py`, strict
`.encode("utf-8")`) OUTSIDE every handler's own try/except; the crash
propagated to `controller.py`'s catch-all, which built an ALLOW (no
decision) via the pre-existing, deliberately-fail-open `HookResult.error()`.
Reproduced live: `git reset --hard HEAD # \ud800` allowed on this branch,
denied on base `3104434b`; fail-open was new here, not pre-existing.

Fixed in three layers: (1) `_safety_payload_size` rewritten to serialise the
WHOLE `tool_input` via `json.dumps(..., ensure_ascii=False)` then
`.encode("utf-8", "surrogatepass")`, wrapped in try/except returning 0 on
`TypeError`/`ValueError` — this also happens to satisfy the report's m5
finding (the old 4-field summation missed `file_path`/MultiEdit's `edits[]`/
NotebookEdit's `new_source`) as a side effect, since the whole dict is now
measured regardless of shape; (2) the measurement call site in
`HandlerChain.execute` is now itself wrapped: any exception computing it
denies immediately, chain-level, when the chain holds a SAFETY+BLOCKING
handler (nothing to protect ⇒ degrades to an unmeasured/uncapped chain
instead, never a regression); (3) new `HookResult.error_deny()` factory
(fail-closed counterpart to the pre-existing `error()`, reason names the
error, context gives `bin/hooks-daemon status`/`restart` recovery
instructions) — `DaemonController.process_event`'s and `process_request`'s
catch-all exception handlers now use it, but ONLY when the event is
`PreToolUse`; every other event type keeps the pre-existing fail-open
`error()` deliberately, per the review's own scoping. RED tests: a lone
surrogate in each of `command`/`content`/`new_string`/`old_string` denies
via the guard's own reason, not a crash
(`tests/unit/core/test_chain.py`); a forced size-measurement crash denies
chain-level when a SAFETY+BLOCKING handler exists and degrades gracefully
when none does; `controller.py`'s router-exception and pre-validation
catch-alls deny for `PreToolUse` and still fail open for every other event
(`tests/unit/daemon/test_controller.py`, 4 new cases plus one pre-existing
case's assertion flipped from ALLOW to DENY — a deliberate behaviour change,
not a mistake). These tests exercise `chain.execute`/
`controller.process_event`/`process_request` directly; the report's own
real-socket reproducer is now ALSO automated, in
`tests/integration/test_b1_surrogate_isolated_daemon.py`: an isolated daemon
with the DEFAULT handler set (no probe handler needed — B1 lives in core
dispatch) receives `git reset --hard HEAD~1 # \ud800` (B1's own manual
reproducer) over a real socket and is still denied by
`prevent-destructive-git`, plus a second case putting the same surrogate in
`file_path` (B2's own vector) and asserting the daemon returns a
well-formed verdict rather than crashing or hanging.

**B2 (blocker) — ✅ Remedied.** `path_exclusion.py`'s `path_matches_globs`
translated a client's exclude glob into a regex (`_glob_to_regex`) and
matched it via `compiled.fullmatch(candidate)`. Against a `file_path` built
from many short segments (`"a/" * n`) the backtracking regex engine went
quadratic-or-worse AND held the GIL for the ENTIRE call: N34's
`BoundedDispatcher` waits on `Future.result(timeout=remaining)` from a
DIFFERENT thread, but nothing can run on that thread while the C-level `re`
call holds the GIL, so the timed wait cannot even observe, let alone
interrupt, the hang — N34's own core claim defeated by its own root cause.
Reproduced live: `probe_n24r_p9_pathhang.py` measured 1.9s at 4000 segments
(unbounded growth from there); `probe_n24r_p11_gil.py` over the real socket
showed a single adversarial Write freezing concurrent PreToolUse calls until
the CLIENT's 30s timeout (fail-open); `hooks-daemon stop` returned in ~6s
but the daemon was still alive at 99% CPU (Python signal handlers only run
between bytecodes) and needed SIGKILL.

Replaced the regex translator with a hand-written linear matcher
(`_tokenize_glob` + `_apply_prefix`/`_apply_literal`/`_apply_qmark`/
`_apply_star`/`_apply_segstar`/`_glob_fullmatch`): each pattern tokenizes
once (cached, as before) into `PREFIX`/`LITSTR`/`QMARK`/`STAR`/`SEGSTAR`/
`ANYALL`, and matching is a left-to-right sweep over a boolean "reachable
position" array per token — no backtracking is possible by construction.
`SEGSTAR` (mid-pattern `**/`) needed care: an earlier, simpler design that
treated it like a plain `.*` was caught by hand-tracing `**/secret` against
`xsecret` — that shortcut would have matched (treating "x" as an admissible
empty prefix) where the original regex correctly does not, since `**/`
requires a COMPLETE, non-empty path segment. The shipped `SEGSTAR`
implementation tracks two flags across one sweep (`armed`: a segment may
start here but has consumed 0 chars; `open`: it has consumed ≥1) so a `/`
only completes a landing when `open`, never on a zero-length attempt.
Verified equivalent to the OLD regex translator (reconstructed standalone,
not deleted from history) across 567 hand-picked edge cases (double
slashes, embedded `\n`, empty patterns/text) plus 65,000 random-fuzzed
`(pattern, text)` pairs spanning both alphabets — zero mismatches.

Performance was iterated three times against the review's own ask ("a
timing test on a 90 KB `file_path` under 50ms") plus a MORE realistic case
(`error_hiding_blocker`'s actual 14 default excludes: 11 vendored-dir globs

- 3 fixture globs, all sharing the `**/X/**` shape) — a naive per-token
  sweep passed the first but not the second (81ms):

1. `_apply_prefix` and `_apply_star` initially used a plain O(n) Python
   loop; switched to `str.find`-driven scans, faster in isolation but WORSE
   once combined with other patterns on this repo's own dense-slash
   adversarial shape (many small `find` calls beat a tight loop only when
   boundaries are sparse).
2. The real win: a `**/<name>/**`-shaped exclude list shares its ENTIRE
   `PREFIX`+`SEGSTAR` prefix across every pattern, diverging only at the
   literal name — but each pattern recomputed that shared O(n) prefix from
   scratch. Added a `step_cache` (keyed by `(token, id(input reachable), id(text))`, scoped to one `path_matches_globs` call, safe because the
   cache and everything it references share that call's lifetime) so the
   shared prefix work runs once per candidate, not once per pattern.
3. With PREFIX/SEGSTAR now cached, `_apply_literal`'s per-position
   `reachable[j] and text[j:j+ln]==literal` loop became the dominant cost,
   because SEGSTAR's output on this dense text is itself dense (most
   positions reachable). Rewrote it to drive from `text.find(literal, pos)`
   instead: a literal like `node_modules` is typically ABSENT from the
   candidate entirely, and `find` returning "not found" is one fast
   C-level scan rather than up to `len(text)` Python-level slice
   compares. Stress-tested this specifically against the classic
   pathological shapes for naive substring search (dense overlapping
   matches, periodic near-misses) up to 640 KB — stayed linear, no hidden
   blowup reintroduced.

Final measured timings (this repo's venv): the review's own 90 KB/4-pattern
timing ask, ~25ms; the realistic 14-pattern `error_hiding_blocker` set on
the same 90 KB adversarial path, ~30ms — both comfortably under the 50ms
ask. The review's own `probe_n24r_p9_pathhang.py` reproducer, re-run
unmodified against the fix: the final `n=45_000` case (the one that used to
require `faulthandler`'s 8s watchdog + SIGKILL to recover from) now
completes in 0.48s. RED tests in
`tests/unit/utils/test_path_exclusion.py`: `TestGlobstarDoesNotCrossPartialSegments`
(the `**/secret` vs `xsecret` regression, pinned permanently) and
`TestLinearMatcherPerformance` (the review's own 90 KB/50ms ask, plus a
45,000-segment/1s sanity bound matching the review's adversarial shape).
Full `tests/unit/utils/test_path_exclusion.py` suite green (63 tests), plus
423 passing across every handler test touching `path_exclusion`
(`error_hiding_blocker`, `comment_size`, `comment_changelog`,
`qa_suppression`, `security_antipattern`, vendor-exclusion tests) — no
regressions.

**B2 direction #4 sweep (fnmatch/regex-over-glob-translated-text
elsewhere).** Grepped `src/` for other dynamic glob-to-regex translation
(`fnmatch.translate`/hand-rolled `[^/]*`-style translators) matched via
`.fullmatch()`/`.match()`. Four call sites use stdlib `fnmatch.fnmatch`
(`core/project_layout.py`, `docs_qa/checks/generated_doc_hand_edit.py`,
`utils/worktree_seed_suggestions.py`, `utils/secret_file_matching.py`):
all match a BOUNDED string (a single path component/basename, or a small
fixed-size joined window of path parts), never an attacker-supplied
unbounded `file_path` reaching a SAFETY+BLOCKING guard in the hot PreToolUse
path the way `path_exclusion.py` did — and `fnmatch.translate`'s output has
no `**`-style nested-quantifier segment logic to begin with. Not fixed;
noted here as the sweep's result rather than left silently undone. Every
other `.fullmatch`/`.match` call in `utils/` is a static, hand-written,
non-glob-derived regex against structured input (header lines, shell
tokens, bracket expressions) — a different audit (ReDoS review of
hand-written regexes), out of B2's specific scope.

**Client fail-closed for PreToolUse — ✅ Remedied.** `init.sh`'s
`send_request_stdin` (the python3 transport embedded in every hook
forwarder) previously fell open for every event except Stop/SubagentStop on
ANY failure, including a socket timeout against a daemon B2 had already
proven could be demonstrably alive and simply stuck — the client-side half
of exactly the gap B2 exploited. Team-lead's explicit, unattended decision
(2026-09-24) superseded an earlier "the client does not fail closed"
constraint. Two new failure classes now deny for `PreToolUse` specifically,
leaving every other event and every other `PreToolUse` error type
unchanged:

1. `socket_timeout` (connect+send succeeded, the daemon was reached and is
   alive, but nothing came back within `CLAUDE_HOOKS_SOCKET_TIMEOUT`,
   default 30s).
2. A new `malformed_response` check on the SUCCESS path: the round-trip
   completed, but the bytes received are not one of PreToolUse's two
   legitimate shapes (`{}` — a real ALLOW with nothing to say, matching
   `HookResult.to_json`'s documented empty-response case — or a dict with a
   `hookSpecificOutput` key whose `permissionDecision`, if present, is one
   of the four known values). Previously the response was echoed to stdout
   completely unvalidated.

Both are DELIBERATELY narrower than "any transport failure at all":
`socket_not_found`, `connection_refused` and `invalid_hook_input` (the
daemon was never reached, or the caller's own payload never parsed
client-side) keep the existing, separately-documented fail-open path
(`ensure_daemon`'s auto-start already ran before this point) — denying
every tool call whenever the daemon is merely absent would make Claude Code
itself unusable during any daemon downtime, a materially different cost
from a rare timeout or garbled response. A new
`_is_daemon_recovery_command` allowlist (exact match only, no compound
commands) exempts `bin/hooks-daemon`/`.claude/hooks-daemon/bin/hooks-daemon`
`restart`/`status`/`logs`/`stop`/`start` from BOTH new deny paths, so a
wedged daemon can always still be restarted from inside the same session —
`bin/hooks-daemon restart && rm -rf /` is deliberately NOT exempt (the
allowlist check is a whole-string `==`, not a prefix match).

Pinned end-to-end against the REAL script (sourced, not reimplemented) in
`tests/integration/test_init_sh_pretooluse_fail_closed.py`: a real bound
AF_UNIX socket that accepts, reads the request, then never responds (the
socket_timeout/GIL-hang shape) denies for PreToolUse but leaves Stop's
existing fail-open unaffected; a socket that responds with unparseable
bytes or valid-JSON-wrong-shape both deny; the exact recovery command still
gets through under either failure (a compound variant does not); a
legitimate `{}` and a legitimate real deny both pass through byte-identical
to before; a nonexistent socket (genuinely no daemon) keeps the existing
fail-open path. Confirmed RED first: replayed the same hanging-socket
fixture against the pre-fix `init.sh` (git blob `362e2516`) and got the old
fail-open `additionalContext`-only response with no `permissionDecision`.
`shellcheck init.sh` clean; the embedded python3 block (extracted by line
range) independently `compile()`-checked and its two new helper functions
unit-tested in isolation before the end-to-end run. `.claude/init.sh` is a
symlink to `../init.sh`, so no separate deploy-sync step was needed.

**M1 — ✅ Remedied.** The chain deadline was measured from `HandlerChain. execute`'s own call, not request arrival — executor queueing between the
socket read and the worker thread actually starting was invisible to the
budget, so a request already judged late by the CLIENT's own 30s timeout
could still look on-time to the chain. `HooksDaemon._handle_client`/
`_handle_event_client` now stamp `arrival_time = time.perf_counter()`
immediately after the socket read, threaded through `_process_request` →
`DaemonController.process_request`/`process_event` → `EventRouter.route` →
`HandlerChain.execute` as a new keyword-only parameter (`None` for every
caller that predates M1, falling back to `execute()`'s own call time —
unchanged behaviour). RED tests: a stale `arrival_time` (10s in the past)
denies a SAFETY+BLOCKING handler immediately even though nothing is slow
(`tests/unit/core/test_chain.py`); omitting `arrival_time` keeps the
pre-existing behaviour. Pseudo-event dispatch and verdict logging in
`process_event` still run AFTER the chain returns and are not themselves
inside the arrival-anchored budget — a smaller, separately-tracked gap the
review's own direction treated as optional ("or run them after the response
is written"), left for a follow-up niggle rather than expanding this one's
scope further.

**M2 — ✅ Remedied.** `BoundedDispatcher`'s semaphore permit was released
only when an abandoned ("straggler") call FINISHED, never when the caller
gave up waiting on it — so enough concurrent stragglers (the review's own
16-straggler reproducer) denied every future PreToolUse call permanently,
with no way out short of a manual restart, and the restart command itself
is a PreToolUse call. Three parts:

1. *Release the slot.* `BoundedDispatcher.run` now releases its semaphore
   permit the MOMENT `future.result(timeout=...)` gives up (not when the
   straggler eventually finishes) via a new `_SinglePermit` wrapper shared
   between the waiting thread and the worker thread, guaranteeing the
   permit is released exactly once regardless of which side gets there
   first. A new dispatch can proceed immediately even while the abandoned
   call is still running.
2. *Bound the stragglers.* Releasing the permit early reopens the gap it
   used to close: nothing bounded how many abandoned calls could pile up.
   A SEPARATE `max_stragglers` cap (defaults to `max_inflight`, Single
   Source of Truth unless a caller splits them) refuses a NEW dispatch
   outright once that many stragglers are already alive, independent of
   ordinary inflight capacity. `BoundedDispatcher.straggler_health()`
   reports the live count and the oldest one's age.
3. *DEGRADED health + self-restart.* `DaemonController.get_health()` now
   reports `status: "degraded"` (with `degraded_reasons: ["stragglers"]`)
   once the straggler count reaches `daemon.chain.straggler_unhealthy_count`
   (new `ChainConfig` field, default 4), and carries the count/oldest-age/
   restart-threshold in a `stragglers` sub-dict. A new watchdog task,
   `HooksDaemon._monitor_straggler_health`, polls this every 10s and
   self-restarts (calls `shutdown()`, i.e. exits) once the OLDEST straggler
   has run past `daemon.chain.straggler_restart_after_seconds` (default
   120s) — recovery, not an outage: the client's own lazy `ensure_daemon`
   auto-start in `init.sh` brings up a fresh, zero-straggler process on the
   very next hook call.

RED-first TDD throughout: `tests/unit/core/test_bounded_dispatch.py` (permit
released immediately on timeout without double-releasing on the straggler's
own later completion; straggler count/age tracked correctly; a new dispatch
refused once the straggler cap is reached even with free inflight capacity);
`tests/unit/daemon/test_controller.py` (`get_health()` reports zero/below-
threshold/at-threshold/disabled straggler states); `tests/unit/daemon/ test_server_coverage.py` (the watchdog self-restarts past the threshold,
stays quiet below it, tolerates a `None` threshold/missing `stragglers` key/
a raising `get_health()`/a legacy controller with no `get_health()` at all,
without crashing the loop). Also folded in review m3's two `BoundedDispatcher`
edge cases while touching the same code: `thread.start()` raising no longer
leaks the semaphore permit or the thread-tracking entry, and the worker now
catches `BaseException` (not only `Exception`) so a `SystemExit`/
`KeyboardInterrupt` inside a handler resolves the future instead of leaving
it unresolved for the FULL remaining timeout.

**M3 — ✅ Remedied (narrowed scope).** Fail-closed-on-raise was TAG-dependent
(`chain.py`'s `_record_unjudged` requires both `HandlerTag.SAFETY` and
`HandlerTag.BLOCKING`), and the review found 19 PreToolUse handlers that can
genuinely deny but carried neither. Of those, 14 were COMPLETELY untagged
(no fail-closed-relevant decision had ever been made about them at all);
the other 5 (`enforce-tdd`, `qa-suppression-blocker`, `plan-*`, and 19 more
across the whole tree) already carry `BLOCKING` alone, which reads as a
deliberate-if-incomplete choice rather than an oversight — auditing that
much larger 22-handler bucket one-by-one was judged out of scope for this
niggle (see the follow-up note below) rather than rushed alongside the
other review items still open.

Of the 14 completely-untagged handlers: 6 are now `HandlerTag.SAFETY` +
`HandlerTag.BLOCKING` — `artifact_publish_blocker` (irreversible external
disclosure), `curl_pipe_shell`/`dangerous_permissions`/`sudo_pip`/
`pip_break_system`/`lock_file_edit_blocker` (team-lead's explicit list: RCE,
privilege escalation, system Python corruption, dependency-hash tampering).
The other 8 are workflow/QA gates, not dangerous-action guards, and none
gets `SAFETY`. Six are now explicitly `HandlerTag.ADVISORY` (a deliberate,
commented opt-out rather than a silent gap): `bash_safe_mode` (ships
disabled by default, has its own escape hatch), `docs_qa_commit_gate`,
`docs_qa_edit`, `plan_qa_commit_gate`, `staged_lint_gate`,
`verification_result_gate` (a heuristic detector, imperfect by its own
docstring) — each denies only under a non-default config value. The other
two, `ask_user_question_blocker` (strict mode, the shipped default, denies
unconditionally) and `validate_instruction_content` (denies unconditionally
on a pattern match, no config gate at all), deny under a DEFAULT install, so
`HandlerTag.ADVISORY` would have understated them: a full-suite run (below)
surfaced the pre-existing sibling guard
`test_declared_behaviour_matches_source.py`, which independently requires
`HandlerTag.BLOCKING` for any handler whose default behaviour denies (it
feeds `scripts/qa/check_doc_truth.py`'s ground truth for the generated
`.claude/HOOKS-DAEMON.md`). Tagged `HandlerTag.BLOCKING` instead —
satisfies both registry tests, since this test's own early-return treats
`BLOCKING` alone as an already-made fail-closed decision.

New registry test, `tests/unit/handlers/test_pretooluse_fail_closed_tagging.py`:
parametrised over every `pre_tool_use` handler, source-inspects each for a
deny signal (`HookResult.deny`/`Decision.DENY`/`Decision.BLOCK` — the same
heuristic the review's own enumeration probe used), and fails any COMPLETELY
untagged denier that carries neither `SAFETY`+`BLOCKING` nor `ADVISORY` —
opt-out-not-opt-in, so a NEW handler in this state fails the suite instead
of the gap growing silently. Deliberately does not flag the pre-existing
`BLOCKING`-only bucket (out of this niggle's narrowed scope, see above).
RED confirmed first (exactly the 14 named above failed, nothing else).
Full `pre_tool_use`/registry/chain regression stays green (4167 passed).

**Follow-up recorded here, done below:** a full audit of the 22-handler
`BLOCKING`-without-`SAFETY` bucket (`enforce-tdd`, `qa-suppression-blocker`,
`plan-qa-edit`, `comment_size`, `comment_changelog`, `dispatch_declaration`,
`merge_to_main_approval`, `plan_close_approval`, `plan_time_estimates`,
`reference_repo_freshness`, `remote_docs_*`, `require_gh_*_comments`,
`enforce_lsp_usage`, `enforce_markdown_organization`, and others) — deciding
per-handler whether each should become `SAFETY`+`BLOCKING` or explicitly
document why not — was deferred as real work this niggle did not do at the
time. See "22-handler BLOCKING-without-SAFETY audit" below for the
completed pass.

**m1 — ✅ Remedied.** Thread-per-handler dispatch added ~12ms per event
(69 thread creations for this repo's PreToolUse handler set, even when
every one of them was fast). `HandlerChain.execute` now dispatches the
WHOLE handler loop (a new private `_execute_handlers` method) as ONE call
on the shared pool when `deadline_seconds` is set, not one dispatch per
handler — `deadline_seconds=None` keeps the original zero-overhead
synchronous path unchanged. The per-handler deadline CHECK stays inline
(a cheap `time.perf_counter()` comparison, not a thread) and still
attributes "not judged in time" to a SPECIFIC handler whenever the loop is
still making progress — every handler that FINISHES, however late, is
caught exactly as before. Only when the WHOLE dispatched call itself times
out or the pool is saturated (some handler never returns at all, or the
pool has no free capacity even for the whole chain) does the deny/skip
reason name "chain" instead of a specific handler — nothing is left
running on the calling thread that could still say which one it was. An
edge case surfaced during implementation: an ALREADY-expired deadline
(e.g. a stale `arrival_time`) is handled by calling `_execute_handlers`
directly rather than dispatching it with `timeout=0.0` — every handler's
own pre-loop check sees the same already-blown deadline from the first
iteration, so nothing risks hanging, and this also avoids a genuine race
`Future.result(timeout=0.0)` would have had (whether the freshly-started
thread gets scheduled at all before the wait gives up).

Five existing tests (`tests/unit/core/test_chain.py` ×4,
`tests/unit/core/test_router.py` ×1) asserted the OLD per-handler
attribution for a slow-but-finite handler exceeding the budget; updated to
assert the new chain-level attribution instead — a deliberate behaviour
change, not a regression, and the module docstring in `test_chain.py`
records why. One real-socket E2E test
(`tests/integration/test_n34_deadline_probe_isolated_daemon.py`) needed the
same update. `_dispatch_matches_and_handle` and `_make_dispatch_call`
(the per-handler dispatch closures) were dead code afterwards and deleted.
Full targeted sweep green: `tests/unit/core/`, `tests/unit/daemon/`,
`tests/unit/handlers/test_pretooluse_fail_closed_tagging.py`,
`tests/unit/config/` (4729 passed, 1 skipped), plus the real-socket
integration files touching chain dispatch (18 passed).
`scripts/qa/check_fail_open_inventory.py`'s rows for the two `except Exception` boundaries that moved from `execute` into `_execute_handlers`
were updated to match (boundaries unchanged, only their enclosing method).

**m3 — ✅ Remedied** (folded into M2's work above, same files): the two
`BoundedDispatcher.run` edge cases (`thread.start()` raising leaking the
semaphore permit; `except Exception` not catching `BaseException`, leaving
the future unresolved for the full timeout) are both fixed.

**m2 — ✅ Remedied.** A straggler (a handler dispatch the caller already gave
up waiting on, per M2 above) could still mutate PROCESS-LIFETIME state after
its own verdict was discarded, for a decision nobody would ever see. Added
`core/dispatch_cancellation.py`: a `DispatchCancellation` (wraps a
`threading.Event`) created once per `HandlerChain.execute()` call, bound via
a `contextvars.ContextVar` around the dispatched handler loop so nested
handler code (in a different file, on the dispatched thread) can call
`is_dispatch_cancelled()` without a parameter threaded through every
signature. `execute()` calls `cancellation.cancel()` at the exact point it
gives up on a `DispatchTimeout`/`DispatchSaturated` outcome, BEFORE building
the fallback deny/allow. Two handlers had their own state write gated on it:
`sensitive_content._compute_and_cache` (skips writing `_cached_dispatch`)
and `github_auto_close_keywords.handle` (skips `tracker.mark_disclosed`).
`lsp_enforcement` needed no change: its "spend" flows through
`DaemonController.process_event`'s iteration over `result.decisions`, which
is empty for an abandoned dispatch — the m1 one-thread-per-request redesign
already structurally closed that one. RED test:
`test_chain.py::TestDispatchCancellationReachesStragglingHandlerCode` (a
handler that sleeps past its own deadline, then checks
`is_dispatch_cancelled()` before recording a "written" vs "skipped-cancelled"
outcome), plus one regression test per fixed handler
(`test_sensitive_content.py`, `test_github_auto_close_keywords.py`).

**m4 — ✅ Remedied.** `check_fail_open_inventory.py` only ever walked
`ast.ExceptHandler` nodes, so `bounded_dispatch.py` — not even in its surface
list — and the chain-level `isinstance(outcome, DispatchTimeout)`/
`DispatchSaturated` branches in `chain.py::execute` (the fail-open decision
BoundedDispatcher.run()'s sentinel-return shape produces) were both
invisible to it. Added `bounded_dispatch.py` to `_PYTHON_SURFACES`; added
`_isinstance_dispatch_boundaries`, walking `ast.If` nodes whose test is
`isinstance(x, DispatchTimeout | DispatchSaturated)` (a new "isinstance-
dispatch" construct shape alongside the existing "except X" one). RED test
(`test_fail_open_inventory_checker.py::TestIsinstanceDispatchBoundaries`,
with a narrowing-control test proving an ordinary unrelated `isinstance`
check is NOT flagged) confirmed against the unmodified detector first. Six
new inventory rows added: `chain.py::execute::isinstance-dispatch DispatchTimeout`/`DispatchSaturated` (both `fail-open` — ALLOW when no
SAFETY+BLOCKING handler is registered) and four `bounded_dispatch.py` rows
(`run::except FutureTimeoutError`, `_run_and_release::except BaseException`,
both `not-fail-open` — they are the SOURCE of the decision, made by the
caller, not a verdict made here). Fixing n2 below (replacing the `assert`
with an explicit `elif`) split the single `isinstance-dispatch DispatchTimeout`
row that had covered both sentinels via an `else`-branch `assert` into two
independent rows, which is the more accurate shape. `check_fail_open_ inventory.py` passes clean (39/39).

**m6 — ✅ Remedied.** `ChainConfig.deadline_seconds` only enforced `gt=0`; a
configured value at or past the client's own socket timeout
(`Timeout.SOCKET_DISPATCH_ROUNDTRIP`, 30s) would reproduce the exact bypass
`deadline_seconds` exists to close — the client gives up and fails the WHOLE
chain open before the daemon's own deadline-triggered deny can be built and
sent back. Added a `model_validator(mode="after")` on `ChainConfig` that
raises `ValueError` (surfaces as `pydantic.ValidationError`) when
`deadline_seconds` is at/past `SOCKET_DISPATCH_ROUNDTRIP`, or leaves less
than a new `Timeout.CHAIN_DEADLINE_SOCKET_MARGIN_SECONDS` (5s) margin —
naming the configured value, the client timeout, and how much to lower it
by. `None` (disabled enforcement) is never checked. RED-first in
`test_chain_config.py::TestDeadlineBelowClientSocketTimeout`; includes a
test that the shipped default (`Timeout.CHAIN_DEADLINE_DEFAULT` = 20s, 10s
of margin) satisfies its own rule.

**m5 — ✅ Remedied.** Three sub-findings, all fixed:

1. *Non-monotonic measurement* was already fixed before this session
   (`362e2516`, prior to this niggle's own work): `_safety_payload_size`
   serialises the WHOLE `tool_input` dict with `surrogatepass` rather than
   summing a fixed field list, closing the MultiEdit `edits[]`/NotebookEdit
   `new_source`/`file_path` gaps the review measured.
2. *Misattributed deny reason*: the size check runs BEFORE scope/`matches()`,
   so it fires for the FIRST SAFETY+BLOCKING handler in PRIORITY order,
   whichever that is — an oversized Write got denied naming
   `prevent-destructive-git` regardless of relevance. `_apply_oversized_input`
   now builds `reason=f"chain: input too large..."` instead of
   `f"{handler.name}: ..."`, matching the existing "chain: not judged in
   time" convention. RED test
   (`test_oversized_input_deny_reason_does_not_misattribute_to_an_unrelated_handler`)
   uses two SAFETY+BLOCKING handlers and asserts NEITHER name appears.
3. *Server-side transport fail-open*: a request past
   `SocketLimit.REQUEST_BUFFER_BYTES` (16 MiB) overran
   `reader.readline()`'s own limit; the bare `ValueError` fell into
   `_handle_client`'s generic exception handler, which tried to write an
   error response and close WITHOUT draining the still-unread remainder of
   the oversized send first — on a Unix domain socket this can make the
   close send an RST instead of a clean FIN, and the client saw a raw
   `ConnectionResetError`/`BrokenPipeError` with NO response at all (real
   socket, `probe_n24r_p7_size.py`), indistinguishable from the daemon
   having crashed outright and NOT covered by `.claude/init.sh`'s
   `malformed_response` fail-closed-for-PreToolUse handling (which needs an
   actual response to act on). Added `_drain_oversized_request`: drains the
   remainder before responding, each `read()` bounded by a 0.5s
   per-read timeout (the protocol carries no length header, so silence that
   long reads as "the sender is done", not "still arriving" — the real
   client sends its whole request in one blocking call before it ever tries
   to read a response) and a running total capped at
   `SocketLimit.REQUEST_BUFFER_BYTES` so a sender that never stops writing
   cannot hang the connection either. RED test (real isolated daemon,
   `test_a_payload_past_the_socket_buffer_limit_fails_closed_for_pretooluse`,
   a genuine >16 MiB payload) confirmed the connection-reset-with-nothing
   failure first; GREEN confirms a real `{"error": ...}` response now always
   arrives.

- **n1 — ✅ Remedied.** "Shared pool"/"thread pool" wording in
  `bounded_dispatch.py` (class docstring, singleton comment),
  `chain.py` (two docstrings), `config/models.py`'s `deadline_seconds`
  field docstring, and `test_chain.py`'s module docstring all corrected:
  `BoundedDispatcher` gives every call a FRESH daemon thread, bounded by a
  shared semaphore — there is no fixed worker set and nothing is queued.
- **n2 — ✅ Remedied.** `chain.py::execute`'s
  `assert isinstance(outcome, DispatchSaturated)` (narrowing the `else` of
  the DispatchTimeout check) replaced with an explicit `elif isinstance(...)`
  and a `raise TypeError(...)` `else` — `-O` strips asserts, which would
  have left `detail` silently unbound instead of failing loudly. Test:
  `test_chain.py::TestUnexpectedDispatchOutcomeFailsLoud`, driving a fake
  `BoundedDispatcher` subclass whose `run()` returns neither sentinel.
- **n4 — ✅ Remedied.** Added `test_chain.py::TestUnderShippedDefaultDeadline`,
  parametrised over `deadline_seconds` `[None, Timeout.CHAIN_DEADLINE_DEFAULT]`
  — five representative core `execute()` behaviours (empty-chain allow,
  matches-called-on-every-handler, terminal-deny-stops-the-chain,
  raise-denies-only-in-strict-mode, first-restrictive-wins) now run under
  BOTH the synchronous path and the real production-shipped threaded
  dispatch path (a genuine thread, semaphore, and cancellation-token
  bind/reset), not just `None`.
- **n3** informational only (two SAFETY+BLOCKING handlers exceed the
  review's 1s advisory threshold under 100 KB, both already under the
  harness's 5s bound; `secret_file_guard`'s is the guard-defects branch's
  known constant-factor issue) — no action needed here.
- **P1** (`github_auto_close_keywords` cache bypass) is explicitly OUT of
  this niggle's scope — routed by the coordinator to a different agent.

**22-handler BLOCKING-without-SAFETY audit — ✅ Done.** The follow-up
deferred below (originally "22 handlers") was live-rescanned across the
FULL registry (every event, not only `pre_tool_use` — `HandlerChain.execute`'s
fail-closed logic is generic across events) and found 24 at audit time: the
21 `pre_tool_use` handlers the review named or implied, plus 3 more from
other events (`lint_on_edit` (PostToolUse), `subagent_report_path_verifier`
(SubagentStop), `failsafe_cron_blockage_suppressor` (UserPromptSubmit)) that
carry the same tag shape. Audited each individually: all 24 are workflow/QA/
governance gates (plan approval, doc placement, QA-suppression, TDD
ordering, provenance, cadence optimisation, ...) whose fail-open consequence
is "a process step did not happen", not a dangerous/irreversible ACTION —
the bar the existing SAFETY roster (destructive git, secret disclosure,
RCE-shaped constructs, write-clobbering, ...) is drawn at. None promoted;
each recorded with its own specific reason (not a copy-pasted one) in a new
`_AUDITED_BLOCKING_ONLY_REASONS` table in
`test_pretooluse_fail_closed_tagging.py`, alongside a new
`test_every_blocking_without_safety_handler_is_audited` (parametrised over
the WHOLE registry, opt-out-not-opt-in: a future handler landing here with
neither `SAFETY` nor a table row fails the suite) and a rot-guard
(`test_the_audit_table_names_only_handlers_that_still_exist_and_still_need_it`)
so a stale row — one for a handler later promoted, renamed, or removed —
fails loudly instead of reading as coverage. RED confirmed by temporarily
removing one row and observing the expected failure, then restoring it.

**Full-suite sweep, incidental to M3 — 5 pre-existing failures found and fixed.**
Running the WHOLE test suite (not just targeted files) after M3 surfaced 5
failures predating this niggle's own changes, all from earlier N24/N25/N34
work in this same plan:

1. `test_handler_config_blocking.py`'s `test_sed_blocker_prevents_inline_edits_e2e`
   and `test_disabled_handler_does_not_block_e2e` called `router.route(...)`
   directly without initialising `ProjectContext`. `enforce-project-containment`
   (`SAFETY`+`BLOCKING`) now correctly denies the WHOLE chain when it raises
   for want of it (N24's fail-closed-on-raise, working as designed) — so
   both tests were denied on `enforce-project-containment` before the
   handler under test ever ran, rather than seeing that handler's own
   verdict. Fixed by requesting the file's own pre-existing (opt-in, not
   autouse) `project_context` fixture from `conftest.py` on those two tests
   — the fixture already existed and other classes in the same file already
   used it correctly.
2. Three pending release-note callouts (`40`/`41`/`42`, written earlier in
   this plan for N24/N25) failed `test_pending_release_notes_holding_area.py`'s
   own shape check: `40`'s filename had an underscore
   (`strict_mode`), which the `NN-kebab-slug.md` naming rule rejects —
   `git mv`d to `strict-mode`. `41` and `42` both wrote `**Audience**: operators, security reviewers` — the schema requires exactly ONE of a
   fixed enum (`operators`/`handler authors`/`client projects`/`everyone`),
   not a comma list; "security reviewers" was not a recognised value at
   all. Both narrowed to `**Audience**: operators`, matching this
   directory's other daemon-behaviour notes.
3. `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/05-review-new-denials-from-strict-mode-and-safety-guards.md`
   (also written for N24; numbered 05 at landing, clear of main's 02) existed on disk with no row in its directory's
   `README.md` task index, failing `test_repo_hygiene_check.py`'s
   post-upgrade-index-drift rule. Added the missing row.

None of these three defects were introduced by THIS niggle's B1/B2/M3/init.sh
work; they were latent since the commits that added each file, only
surfaced now because a full (not targeted) suite run happened to be part of
verifying M3. Fixed as small, self-contained corrections rather than left
broken. Full `tests/integration/` suite green after (previously 7 failed /
4187 passed / 8 skipped).

### N34 — ✅ Remedied — `secret_file_guard`'s linear scan has enough constant factor to blow past the chain deadline on its own

**Found while measuring N25's deadline margin, on request from the
coordinator.** `SecretFileGuardHandler` scales LINEARLY with command length
(confirmed up to 800 KB earlier under N25 Task 3 — doubling the input
roughly doubles the time), but its constant factor (~12µs/byte, on a hostile
"many small quoted tokens" command) is steep enough that size alone gets it
into trouble:

| Size | Wall-clock | % of the 20s `chain.deadline_seconds` budget                                 |
| ---- | ---------- | ---------------------------------------------------------------------------- |
| 1 MB | 12.315s    | 61.6%                                                                        |
| 4 MB | 48.958s    | 244.8% — past BOTH the 20s daemon deadline AND the 30s client socket timeout |

**This exposes a gap in N25's own deadline enforcement**, not a new bug in
`secret_file_guard` itself: `HandlerChain.execute`'s deadline check
(`core/chain.py`) runs BETWEEN handlers, in the per-handler loop, before
each one starts. It has no way to interrupt a handler that is already
running — so a single handler slow enough to exceed the deadline WITHIN its
own `matches()`/`handle()` call blows straight through the budget with no
check-in, and the client's own 30s socket timeout can still be reached
before the daemon ever responds. At 4 MB, `secret_file_guard` alone
reproduces the exact failure mode N25 set out to close: a slow handler
silently allowing everything queued behind it (via the client's ALLOW
fallback on timeout), just from ONE handler's own runtime rather than from
being queued behind others.

Originally reported per the coordinator's specific ask ("report
secret_file_guard's wall-clock at 1 MB and 4 MB so we know its margin
against the 20s deadline"), which was a measurement, not a remedy at the
time. The coordinator then asked for remedy 2 (below) to be implemented
before the security review, since the gap is the same fail-open class N25
exists to close and could not ship open.

**✅ Remedied**: remedy 2, an externally enforced per-handler deadline, plus
remedy 3 as defence in depth.

- New module `core/bounded_dispatch.py` (`BoundedDispatcher`): runs a
  handler's combined `matches()`+`handle()` call on its own DAEMON thread
  and waits on it with `Future.result(timeout=remaining)`, where `remaining`
  is whatever is left of the chain's `deadline_seconds` budget when that
  handler starts — not the handler's own execution time. `HandlerChain. execute` now routes every handler through this when `deadline_seconds` is
  set (unchanged, fully synchronous, when it is `None`). On expiry the SAME
  fail-closed verdict N25 already used applies: a `SAFETY`+`BLOCKING`
  handler not judged in time is denied, naming the handler; anything else is
  skipped with an advisory note — both pre-check (N25, between handlers) and
  this new post-dispatch-timeout case now share one `_record_unjudged`
  helper in `chain.py`.
- The overrunning call is genuinely abandoned, not killed (Python cannot
  force-stop a thread) — logged again at WARNING with its actual elapsed
  time whenever it does finish. Deliberately NOT
  `concurrent.futures.ThreadPoolExecutor`: its worker threads are
  non-daemon and CPython registers an `atexit` hook
  (`concurrent.futures.thread._python_exit`) that JOINS every one of them
  before the interpreter may exit — discovered live, via the isolated-daemon
  e2e test below: the daemon's own `stop` hung for the full straggler sleep
  before this was caught and the dispatcher rewritten onto plain
  `threading.Thread(daemon=True)` per call. Concurrency is still bounded (16
  calls at once, by default, via a semaphore): a call beyond that returns
  `DispatchSaturated` immediately rather than queuing, and is treated the
  same as a timeout.
- Remedy 3: a new `daemon.chain.max_safety_input_bytes` config key (default
  2 MiB), checked once per chain execution against the combined size of a
  handler's bulk-text `tool_input` fields (Bash `command`, Write `content`,
  Edit `old_string`/`new_string`). A `SAFETY` handler over the limit is
  denied/skipped (the same split as above) BEFORE dispatch is even
  attempted — cheaper than paying thread-dispatch overhead only to be cut
  off by the deadline regardless. Explicitly NOT the only guarantee — the
  per-handler deadline bound above already caps worst-case wall clock
  regardless of size — so it is safe to raise or disable (`null`) as long as
  `deadline_seconds` stays enforced. `secret_file_guard`'s own constant
  factor was deliberately left alone, per the coordinator: the guard-defects
  branch is rewriting `secret_file_matching` onto a shared bounded expander
  and will profile the 12µs/byte cost there.
- RED tests: `tests/unit/core/test_bounded_dispatch.py` (the dispatcher in
  isolation — completes-within-budget, times-out-without-waiting,
  stray-finishes-in-background, saturation-fails-fast) and new cases in
  `tests/unit/core/test_chain.py` (a SAFETY handler that oversleeps ITSELF
  denies within the deadline, not after its own sleep; a slow advisory-only
  handler allows with an advisory the same way; pool saturation denies; the
  size cap denies/skips/passes-through in each direction; `deadline_seconds: null` leaves an oversleeping handler fully unbounded, confirming the new
  mechanism is disabled exactly like the old one). An end-to-end test,
  `tests/integration/test_n34_deadline_probe_isolated_daemon.py`, starts its
  own isolated daemon with a 1s configured deadline and a probe handler that
  sleeps 8s, and asserts over the REAL socket that the client gets its deny
  back in well under 2s — not after 8s, and nowhere near the client's own
  30s timeout.

N34 is taken on the `worktree-n466-n24` branch (the chain deadline cannot
interrupt a running handler) and lands with that branch. N40 is taken there too
(the fail-open classes behind that branch's security-review blockers). N41 is
taken on the N38 fix branch (the chain's remaining linear per-token cost, which
waits for the shell-parser consolidation).

### N105 — A skill redeploy leaves an untracked, unignored `.claude/hooks-daemon-backups/`

**Found by upgrade review 11 (L9), confirmed by upgrade round 16a.**
`install/skills.py` `_preserve_replaced_skill` moves a deployed skill that
differs from the shipped one into `.claude/hooks-daemon-backups/skills/<name>`.
Neither this repository's `.gitignore` nor the deployed `.claude/.gitignore`
template ignores that directory. So after a dogfood redeploy, or a client
upgrade that replaced an edited skill, `git status` shows
`?? .claude/hooks-daemon-backups/`, and a careless `git add -A` commits the
backup.

**Remedy:** add `/hooks-daemon-backups/` to the deployed `.claude/.gitignore`
template and to this repository's `.gitignore`. Test: run `deploy_skills`
over an edited skill, then check that `git status --porcelain` is empty.
(The upgrade-scripts branch covers the directory in its snapshot, so a
failed upgrade removes a copy it created.)

### N101 — `secret_file_guard` fails closed with `TooManyToEnumerateError` on ordinary `python3 - <<'EOF'` commands

**Found by N38 fix round 11** (report `260926-n38-fix11-opus-5-5.md` on the
N38 branch). The live daemon on main twice denied an ordinary Bash command
with `TooManyToEnumerateError`. Both were quoted-heredoc Python programs,
one editing `secret_file_guard.py` and one building recovery-cron hook
inputs, and neither named a protected path. The guard enumerates the
spellings a command could expand to, and a heredoc body with many
brace-, glob- or bracket-like characters exceeds the bound. Failing closed
is right for a command that could really expand to a protected name. Here
the body is data handed to `python3`, so a legitimate command is denied.

**Remedy:** reproduce with a python heredoc from those commands. Establish
whether the enumeration should run on a quoted-heredoc body at all: it is
fed to an interpreter, not expanded by the shell, so its bytes are not
shell words. Keep fail-closed where the shell does expand the text. Pin both
cases. It touches the guard that guard-defects just changed, so it goes on a
fresh branch from main.

### N100 — A continuation on a heredoc opener line (`cat > s.sh \⏎<<'EOF'`) denies a body that is only written

**Found by N38 reviews 6 to 9 (candidate 4), unchanged on main.** When the
redirect and the `<<'EOF'` sit on two physical lines joined by `\`+newline,
the quoted-delimiter exemption is not granted, so a body that `cat` only
writes is judged as a command. It is the documented fallback shape for
writing a script that mentions a guarded word, so it fails where the docs
send people.

**Remedy:** join continuations before deciding the heredoc receiver, using
the N38 lexer, and pin that the continued and single-line forms get the
same verdict. It goes on the executed-body branch with N87 to N89 and N93,
after N38.

### N99 — `dev-handlers.md` offers an agent a wrapper command that the daemon denies

**Found by the Plan 464 gate fixer** (`260926-p464-gatefix2-sonnet-5.md`
on `worktree-plan-464-commit-gate-repo`). The skill routes agents to the
`init-project-handlers` verb and offers
`bash .claude/skills/hooks-daemon/scripts/init-handlers.sh <…>` "for a human
who prefers prompts". The script's self-update bootstrap re-execs a path
computed by `mktemp`, so on 464's branch `destructive_git` denies it as
`R-GIT-ALIAS-UNREAD`. That script-content scan is Plan 464 Task 1.11's
intended behaviour. The doc does not say that an agent will be refused. An
agent following the page as a whole would therefore hit a denial the page
never mentions.

**Remedy:** once 464 lands, the doc says the wrapper is for a human to run
themselves (`! bash …`), and that an agent uses the verb. A copy-paste test
should pin that each documented agent-facing command is allowed.

### N98 — Past the AF_UNIX limit, every hostname shares one fallback socket, PID file and events dir

**Found by upgrade scripts round 13** (report
`260926-upgrade-scripts13-opus-5-5.md` on `worktree-upgrade-scripts`,
section 4). Every runtime path carries `_get_hostname_suffix()` except the
two fallbacks, both in `daemon/paths.py`:

- `_get_fallback_runtime_dir` names the socket, PID and log
  `hooks-daemon-<project hash>.<ext>`;
- `_get_event_socket_fallback_dir` names the events dir
  `hooks-daemon-<untracked hash>-events`.

So when a project's natural socket path is over the limit, every hostname
on the machine resolves the same three paths. The first daemon serves them
all, and a second one clobbers the first one's files. Calling
`get_socket_path`, `get_pid_path` and `get_event_socket_dir` for a long
project path under `HOSTNAME=host-a` and then `HOSTNAME=host-b` prints
identical paths.

**Remedy:** key both fallback names by the hostname too, for example with a
short hash of the sanitised suffix so the name stays bounded. Check every
reader that derives one path from another: `init.sh` derives the PID path
from the socket's stem, and the forwarder and the relay use the events dir.
It touches the same runtime-path code as N86, so it goes on N86's branch
after N24 merges.

### N97 — `block-curl-pipe-shell` denies prose that only mentions curl and bash

**Found by N38 review 9 (ledger candidate 8), and on base too.** A
docstring written into `test_curl_pipe_shell.py` is denied. The literal is
in `/workspace/untracked/scratch/n38r9/fpcmp_lit.txt`. bash would stop at a
syntax error before the curl line, and the line is not curl piped into
bash anyway.

**Remedy:** judge `curl … | sh` only on a real pipe, taking pipe positions
from the N38 lexer, and not on text inside a quoted string or heredoc data
body. It starts after N38 merges, on the same branch as N92 (a quoted `|`
read as a pipe).

### N96 — `subagent_full_qa_blocker.py` is one 5,300-line handler

**Found by the coordinator while harvesting the Plan 00463 gate fix.** The
module grew over ten review rounds, each closing more evasion shapes, to
5,294 lines. No other handler is close to that size. It holds command
recognition, interpreter classification, wrapper peeling and the verdict
in one file, so every future review reads all of it, and a regression in
one part hides among the rest.

**Remedy:** after Plan 00463 merges, split it along the seams it already
has. Put the recognisers in `utils` next to `shell_segmentation`, keep the
verdict and messages in the handler, and move behaviour-free tables to
constants. It is a pure refactor with the test suite unchanged. Some of
the recognition probably duplicates the 464 script-walk and wrapper
machinery, so reuse that rather than moving it.

### N95 — Test fixtures run setup git commands under a production 5-second budget, so a loaded host flakes the gate

**Found by the N81 to N83 gate fixer.**
`test_sensitive_content.py::TestStagedContentSurface::test_excluded_path_is_not_inspected`
errored because a `git commit` in its FIXTURE timed out on
`Timeout.GIT_CONTEXT` (5 s). That was the last test of a 28,651-test run
with a load average of 6 on 8 cores. About 86 test files' git fixtures use
that same production budget. The budget exists to bound the daemon's own
git calls on the hook path. A fixture's setup is not what is under test,
and it borrowing the hook budget turns host load into gate failures.

**Remedy:** fixtures use a test-owned setup budget, a named constant with a
generous bound. Assertions about the product's own timing stay on the
product constant. A test pins that fixtures never import the hook-path
budget.

### N94 — `github_auto_close_keywords` answers a repeated `git commit -F` from the previous request

**Found by N38 review 8 (its MAJOR, and on main too).** The handler caches
its verdict on the shared handler instance, keyed by the command text alone.
The verdict also depends on the message file, read relative to the request's
cwd. Run `git commit -F msg.txt` with a harmless message in one directory,
then with `Closes #12` in another: the second is allowed. Editing the file
between two identical commands also keeps the stale answer.

**Remedy:** N38 fix round 9 keys the memo by every input, sweeps every
handler for per-instance per-request state, and extends the static detector
to catch it. It lands with N38.

### N93 — `project_containment` misses writes inside `eval '…'` and nested heredocs

**Found by N38 review 8 (ledger candidate).** A write outside the project
that sits inside `eval '…'`, inside `bash <<'OUTER'`, or after a moved
heredoc closer is not seen. Every tree allows it, main included.

**Remedy:** judge executed bodies as commands, as the guards now do. It
belongs on the executed-body branch with N87 to N89.

### N92 — `pipe_blocker` reads a `|` inside a double-quoted regex as a pipe

**Found by N38 review 8 (ledger candidate).** `grep -E "a|HEAD|b" f` is
denied as a pipe to `head`. It happens on every tree, including the live
daemon. A double-quoted string is one word to bash, so there is no pipe
there.

**Remedy:** the pipe split must honour quoting, taking pipe positions from
the N38 lexer. It starts after N38 merges.

### N91 — A project's extra `protected_paths` can be ignored for the life of the daemon by the payload-capture and lint seams

**Found by N38 fix round 8's static shared-state detector.**
`secret_file_matching.resolve_configured_patterns()` sets its "resolved" flag
BEFORE it checks whether `ProjectContext` is initialised. A first call made
before the context is ready therefore fixes the patterns at the shipped
defaults for the rest of the process. The project's own `protected_paths`
are then never applied by the seams that use this function: payload capture
and lint diagnostics. The guard itself reads its options separately.

**Remedy:** the N38 branch replaces the flag with a memo keyed by its inputs,
and a test fails on the old code. It lands with N38.

### N90 — `project_containment` denies every command, even one that writes nothing, when the project root is unresolved

**Found by the guard-defects gate fixer.** `project_containment.matches()`
resolves `ProjectContext.project_root()` before it checks whether the
command names any write target. When the root cannot be resolved, it fails
closed on EVERY command ahead of every lower-priority handler. Three test
harnesses that build a router without initialising `ProjectContext` showed
it. In a real daemon the context is always initialised, but any future
caller that routes events without it is fully locked out.

**Remedy:** return early when `_named_targets()` is empty, before resolving
the root. A command that writes nothing cannot escape the project. Keep
fail-closed for a command that does name a target, and pin both with tests.

### N89 — A data-sink receiver is trusted after the command redefines it

**Found by N38 review 6 (ledger candidate 3).** `cat() { bash; }; cat <<'E'`
and `alias cat=bash` both fail open on every tree. The heredoc blanking treats
`cat` as a data sink, so the body is never judged, but bash runs it.

**Remedy:** a receiver name is not trusted as a data sink once the same
command defines a function or alias of that name, or runs `alias`, `eval` or
`source` beforehand. In that case the body is judged. It builds on the N38
lexer, so it goes on the executed-body branch with N87 and N88.

### N88 — A data sink whose output feeds an executing process substitution hides the body

**Found by N38 review 6 (ledger candidate 2).** In
`tee >(bash) <<'E'` followed by `git reset --hard HEAD` and `E`, bash runs
the reset. HEAD, base and main all allow it. `_downstream_is_all_data_sinks`
looks at pipes only, not at `>(...)` redirect targets. This bypasses every
guard that relies on heredoc blanking.

**Remedy:** a `>(...)` or `<(...)` target that runs a shell (or anything
off the data-sink list) makes the heredoc body executed. It goes on the
executed-body branch with N87 and N89.

### N87 — ANSI-C quoting in text handed to a shell is never decoded, so the command it carries is unseen

**Found by N38 fix round 6.** In `bash -c $'echo a\ngit reset --hard HEAD'`,
bash decodes `\n` to a newline and runs the reset as a second command. The
guards see one `echo` with a literal `\n`, and allow it. Main allows it too.
The same applies wherever an executed body arrives through `$'…'`: `sh -c`,
`eval`, and a here-string fed to a shell.

**Remedy:** decode `$'…'` (the full escape set: `\n`, `\t`, `\xHH`,
`\nnn`, `\uHHHH`, `\cX`) before an executed body is lexed. If a string cannot
be decoded, treat the command as unparseable and fail closed. It uses the
N38 lexer, so it starts after N38 merges.

### N86 — A discovery-file miss leaves the forwarders unable to find or start the daemon

**Found by the upgrade refused-cases investigation**
(`subagent-reports/260925-upgrade-refused-rootcause-opus-5-5.md` on
`worktree-upgrade-scripts`, section 4.2). The daemon publishes its
socket-path discovery file under the OS hostname. A forwarder running with a
different `HOSTNAME` cannot find it. The upgrade apply's `env -i` dropped
`HOSTNAME`, and that is fixed on that branch, but a deleted file or a crash
lands in the same state. Then `cmd_start` sees a socket path over the
AF_UNIX limit, reports "socket exists but its liveness is indeterminate",
and refuses. The file does not exist, so the message is false, and the
forwarder can never start a daemon from that state. Every PreToolUse call
then fails open until N24 lands, and fails closed after it.

**Remedy:** an absent socket path is NOT_LIVE, not indeterminate. The
forwarder (`init.sh`) computes the same `/tmp` fallback name the Python CLI
does, instead of depending only on the discovery file. It touches `init.sh`,
so it starts after N24 merges.

### N85 — `_MESSAGE_BODY_PATTERN` reads `\'` as an escape inside single quotes, which hides a command from every guard

**Found by N38 review 5 (ledger candidate 2).** In
`git commit -m 'a\'; git reset --hard HEAD; echo 'x'`, bash ends the first
string at `a\'`, since a single-quoted string has no escapes. So bash runs
the reset. `strip_message_bodies` instead treats `\'` as an escaped quote,
and blanks everything up to the last `'`. Every guard that uses
`strip_inert_spans` then allows the command. Main and the N38 branch both
allow it.

**Remedy:** the single-quote alternative becomes `'[^']*'`. Sweep `src/` for
the same mistake in any other single-quote matcher. Round 6 of the N38 fix
branch carries it, with a RED test through the real chain.

### N84 — The `daemon_process` test fixture never checks that `stop` succeeded, so daemons leak

**Found by the N24 gate fixer.** When N24's root-attribution check refused
to signal a test daemon, the fixture's teardown ignored `stop`'s exit code.
Eight daemons had been left running in the container from earlier runs, and
nothing reported them.

**Remedy:** teardown asserts `stop` exits 0 and that the pid is gone, and
a test pins that a failed stop fails the test.

### N83 — A parametrised live-daemon test skips its own `tests` case

**Found by the coordinator in CI run 36171017537.**
`tests/unit/qa/test_llm_qa_live_daemon.py:76` parametrises over the whole
`TOOL_REGISTRY` and then calls `pytest.skip` for `tests`, so every run
reports a skip. The owner's rule is that a skip in a release gate is a
failure.

**Remedy:** exclude `tests` from the parametrisation, and pin the reason in
a separate test that asserts `tests` reaches the daemon through
`tests/acceptance`.

**Remedied at commit `21a134f1e`.**

### N82 — A "design test" has been skipped as "implementation pending" since the registry-key work

**Found by the coordinator in CI run 36171017537.**
`tests/unit/handlers/test_config_key_consistency.py:76` calls `pytest.skip`
unconditionally. It records the requirement that the registry derive a
handler's config key from its `HandlerID` constant, not from
`_to_snake_case(class_name)`. It has never run.

**Remedy:** check whether the registry now uses the constant. If it does,
turn the skip into a real assertion. If not, implement the lookup RED-first
and delete the skip.

**Remedied at commit `637fc735a`.** The registry already derived the key
from the constant (`_get_config_key_from_constant`); the skip was replaced
with a real assertion over every handler `iter_builtin_handler_classes()`
yields.

### N81 — `sed_blocker` denies a Bash heredoc that writes markdown, and a strict xfail pins the defect

**Found by the coordinator in CI run 36171017537.** The strict `xfail` at
`tests/unit/handlers/test_sed_blocker.py:1391` records a behaviour defect that
Plan 00260 Task 3.1 deferred. `cat > NOTES.md <<'EOF'` with a body that
mentions sed is DENIED, while the Write tool allows the same `.md` content.
Plan 00260 is archived Complete, so nothing now owns the defect. A deferral
is the owner's call.

**Remedy:** use the redirect-target parsing the other Bash guards now share
to exempt a write whose only target is a `.md` file and whose sed text is
never executed. Flip the xfail into a passing test and remove the marker,
then update the guidance.

**Remedied at commit `e445fecc3`.** A fifth exemption checked with
`bash_write_destinations()` (the same public, shared redirect-target parser
`project_containment` and `get_written_file_paths()` are built on): every
AUTHORED destination must end in `.md` and the sed text must never be
EXECUTED. `get_claude_md()` and the class docstring now state the Bash
`.md` exemption is narrower than `Write`'s unconditional one, not
equivalent to it.

### N80 — A script overwritten earlier in the same command by an unlisted writer is judged by its old content

**Found by Plan 00464 review 5 (M4). Narrowed by fix round 11, then confirmed
by the verify-and-merge pass at 5a14423fb.** The commit-gate script walk
judges a script by its on-disk content. Round 11 made the known
content-changing git writers deny: checkout, switch, reset, pull, merge,
apply, am, stash pop, restore, cherry-pick, rebase, revert, worktree add and
clone. Three writers that overwrite an EXISTING script earlier in the same
command still leak, each reproduced with a real commit: `tar -x`, `curl -o`,
and a `python3` `shutil.copy`. The staged term then reached the commit.

The review's suggested inversion treats any command with an unknown writer
before the script as unjudged. Measured at 53 false denies out of 191 on the
B1 corpus, it was reverted. Text judging cannot enumerate every writer.

**Remedy:** the git-level backstop that is already an owner referral in Plan
00464 (a pre-commit sink that scans the staged content at commit time,
whatever command produced it), which closes this whole class. Until the
owner rules, these three shapes are the known open leaks.

### N79 — The guard-defects false-positive corpus is smaller than review 7 asked

**Found by guard-defects review 8 (L8).** The in-repo corpus holds 171
commands and asserts `>= 150`. Review 7 asked for 200 or more.

**Remedy:** grow the corpus to at least 200 real commands (from session
transcripts, not invented) and raise the assertion to match.

### N78 — Three exotic-shape mismatches in the `gd5_exotic` baseline

**Found by guard-defects review 8 (L6), unchanged since review 5.** A
trailing `#c` after the key name, backslash-octal in an unquoted word, and
one prose false positive.

**Remedy:** decode backslash-octal in an unquoted word, treat `#` after a
word as a comment only at a word start, and fix the prose case. A RED test for each.

### N77 — Four shell shapes still run a protected-path read unjudged

**Found by guard-defects review 8 (L5, gd6_shell2 class d).** They are
`x=...; bash -c "$x"`, `x=...; eval "$x"`, an alias, and a file written and
then run with `sh`. Each lets a protected path be read.

**Remedy:** resolve a literal assignment into `bash -c "$x"` and `eval "$x"`
as the Plan 00464 walker does. Treat an alias definition or a written-then-run
script as unjudged when it could read a protected path.

### N76 — Python's regex fallback and the Go reader miss argv shell launches

**Found by guard-defects review 8 (L4).** The Python regex fallback misses
an argv `['/bin/bash','-c',...]`, although the AST path catches it. Both the
Python AST path and Go miss an argv `env bash -c`.

**Remedy:** bring the fallback to parity with the AST path, and peel `env`
in both. Parity tests run the same fixture through both paths.

### N75 — The Write/Edit content route misses 26 script-launch shapes

**Found by guard-defects review 8 (L3, probe_gd6_files).** The misses cover
Python (a variable-held command, a literal past the 500-character span,
`.pyw`, an extensionless shebang), Ruby `spawn`, PHP `passthru`/`popen`,
Perl (bare `exec`, `open -|`, 2-arg pipe `open`, `.pm`), and Node (template
`exec`, `spawn('sh',['-c'])`, `execFile('bash',['-c'])`, `.cjs`/`.tsx`/`.mts`,
zx `$`, `Bun.$`). They also cover Kotlin, Swift, Dockerfile `RUN`, justfile,
toml tasks, `package.json` scripts and PowerShell.

**Remedy:** Task 4.3 scope. Extend each language strategy, and route an
unknown script-bearing extension to a generic shell-text scan.

### N74 — A recursive grep over a protected directory is allowed

**Found by guard-defects review 8 (L2).** `grep -r '' <protected dir>` is
allowed on main and on the branch, and `HANDLER_REFERENCE.md` documents it
as a residual. A documented residual is not a terminal state.

**Remedy:** deny a recursive read rooted at, or above, a protected path.

### N73 — Two everyday idioms are still denied by the Plan 00464 script walker

**Found by Plan 00464 review 5 (m3).** PLAN Task 1.12 lists them as not
fixed. A `cd "${PROJECT_ROOT}"` is not followed by the walker's cd tracking,
and a bare `~/...` word is not resolved. Both fail closed (they deny, and
nothing leaks), but each is a false deny of an ordinary command.

**Remedy:** resolve `${VAR}` in a `cd` from the same in-order value tracking
the `"$X"` command-position fix uses, and expand a leading `~/` to `$HOME`.
Add both shapes to the B1 corpus.

### N72 — A Python script's computed subprocess argv is dropped, not judged unresolved

**Found by Plan 00464 review 5 (m2).** `python3 s.py`, where `s.py` calls
`subprocess.run(argv_var)` with a git argv built at run time, is allowed, and
the staged term reached a real commit (`probe_464r5_allow_chain.out`).
`Worktree.core.md` documents this as best-effort, but a security caller must
fail closed, and a documented fail-open is still a fail-open.

**Remedy:** when the Python reader meets a `subprocess`/`os` call whose argv
it cannot resolve, mark the script unresolved (deny when it could commit)
rather than dropping the call. Keep the B1 corpus at 0 false denies.

### N71 — The check-to-run race of the commit-gate script walk is undocumented

**Found by Plan 00464 review 5 (m1, carried from review 4 B3).** Another
process, such as a background job or a second agent, can rewrite a script
between the PreToolUse judgement and the run. The walk judges the file as it
was. Neither `Worktree.core.md` nor `HANDLER_REFERENCE.md` says so.

**Remedy:** document the boundary in both, and name the git-level sink
(the Plan 00464 pre-commit owner referral) as what would close it.

### N70 — The pidfd stop path falls back and cleans up too eagerly

**Found by N24 review 4 (two NITs).**

- `_open_pidfd` falls back to by-number signalling on ESRCH and EMFILE, not
  only where pidfd is unsupported. ESRCH means the process is not running and
  needs no fallback.
- When the pinned process dies during the proof, `cmd_stop` deletes the PID
  file and socket even though the proof has just attributed a live process to
  this project.

**Remedy:** fall back only for EMFILE and an unsupported platform, and leave
the files alone in the race. A RED test for each.

### N69 — Two fail-closed deny messages misname what happened

**Found by N24 reviews 3 and 4.**

- `emit_error_json` says "reached" for `socket_not_found` and
  `connection_refused`, which never connected.
- The relay's timeout is labelled "os error 11" instead of a readable name.

**Remedy:** use the version-aware verb already used by `emit_hook_error`, and
map EAGAIN to "timed out".

### N68 — A moved-away daemon checkout reads as NOT_INSTALLED, which fails open

**Found by N24 review 4 (mi-C). Owner decision needed.** An agent's
`mv .claude/hooks-daemon .claude/hd-old && kill <pid>` is allowed. The hook
then reports `NOT_INSTALLED`, which allows every call. That cannot be told
apart from a genuinely fresh clone that has the committed config but no
install yet.

**Candidate remedies:**

- an untracked install stamp, so a stamp with no checkout means removed, and
  removed denies;
- or an install-command carve-out instead of the fail-open.

### N67 — The daemon-down repair carve-out trusts the command text, not the binary it runs

**Found by N24 review 4 (mi-A).** While the daemon is unreachable, PreToolUse
allows a sole `bin/hooks-daemon <read-only|restart>` command. The check reads
the TEXT, so a planted `bin/hooks-daemon` in the hook's cwd runs. The same
indirection exists while the daemon is up, but the carve-out is the one path
that fail-closed mode exists to guard.

**Remedy:** require `realpath(cwd/bin/hooks-daemon)` to equal the project's
own launcher, or the cwd to be the project root. RED test: a planted launcher
in a subdirectory is denied while the daemon is down.

### N66 — Two singleton race tests depend on `time.sleep(0.02)`, so they can pass without the race happening

**Found by N23 review 5 (its L6); carried open by the round 6 fixer.** The race
tests in `test_data_layer.py` and `test_controller.py` sleep inside a slow
initialiser to widen the window. On a loaded host the second thread may not
arrive inside it, so the test passes whether or not the lock is correct.

A naive N-party Barrier inside the initialiser deadlocks under the correct
implementation, because only the winning thread reaches it.

**Candidate remedy:** instrument the ENTRY of `get_data_layer()` (and the
controller equivalent) with a test hook. Hold every thread at an entry barrier,
release them together, and assert exactly one initialisation. Mutation proof:
removing the lock must fail the test every time, not sometimes.

### N65 — `plan_number_helper` denies an `ls` of one named plan's folder as a next-number scan

**Found by the coordinator.** In a worktree it ran
`ls CLAUDE/Plan/*464*/subagent-reports/; ls -d CLAUDE/Plan/*464*`, to list the
reports of a plan it already knew by number. R-PLAN-NUMBER-DISCOVERY denied
the command as a next-plan-number discovery scan. Nothing in the command
sorts, tails, or reads the numbering. A glob that contains a specific plan
number is a lookup, not a discovery.

**Candidate remedy:** treat a glob or path that names a concrete plan number
(`*464*`, `00464-*`) as a lookup and allow it. Keep denying the shapes that
derive a number: a bare `ls CLAUDE/Plan` piped to `sort`, `tail` or `awk`, or
a `find` over the plan root. RED tests: the command above is allowed;
`ls CLAUDE/Plan | sort | tail -1` still denies.

### N64 — `subagent_report_path_verifier` resolves a worktree-relative report path against the main checkout

**Found by an N47 verify agent** working in
`.claude/worktrees/agent-ad81…`. It named its report as
`CLAUDE/Plan/…/subagent-reports/260925-n47-verify6-sonnet-5.md`, relative to
its own worktree, where the file exists. The verifier checked that path
against `/workspace` instead, reported it missing, and pushed the agent into
an extra turn arguing with a false negative.

**Candidate remedy:** resolve a relative claimed path against the agent's own
cwd (the hook input's `cwd`), then against the project root. Report "missing"
only when neither exists. RED test: an agent whose cwd is a worktree claims a
relative path that exists only there.

### N63 — Supervisor unit tests read the ambient `CCY_*` environment, so a ccy session fails a test CI passes

**Found by the N24 fixer.** On main,
`test_effort_restore.py::test_opus_below_default_minimum_injects_high` fails
in this container: it gets `/effort medium` where the test expects
`/effort high`. It passes in CI. The cause is that the container exports
`CCY_MIN_EFFORT_LEVELS=fable=low,opus=medium`, and the supervisor reads it at
decision time.

`tests/unit/supervise/conftest.py` already clears one such variable,
`CCY_FLAG_COMPACT`, after the same failure shape bit before. That fix named one
variable, not the class. The supervisor reads at least five more
(`CCY_MIN_EFFORT_LEVELS`, `CCY_MODEL_RESTORE_SECONDS`,
`CCY_MODEL_CONFIRM_ENTERS`, `CCY_EFFORT_CONFIRM_ENTERS`, and the Ctrl+C guard
variables).

**Remedy:**

- the autouse fixture clears every `CCY_*` variable;
- a guard test fails if the supervisor defines an environment-variable
  constant outside `CCY_*` that the fixture does not also clear.

### N62 — Nothing bounds a subagent's context, so long-lived agents burn the usage budget

**Found by the owner**, who hit the 5-hour limit during a coordinated run. The
measurements:

- 584 subagent transcripts, about 1 GB;
- the largest agents compacted only at about 567k to 581k tokens (Plan 464's
  implementer compacted 9 times);
- messaging a finished agent resumes its whole history (2,374 prior messages
  in one case).

Every tool call re-reads that context, so the cost is roughly (average
context) × (tool calls) × (agents in parallel).

**Candidate remedies** (daemon-enforceable; the hook input carries
`transcript_path` and `agent_id`):

- A subagent context budget. A PreToolUse handler reads the latest usage
  from the agent's transcript. Past a soft budget it advises "write your
  handoff to the report file". Past a hard budget it denies every tool except
  writing that report and messaging the coordinator. The coordinator then
  starts a fresh agent from the report. Both budgets are configurable.
- A resume guard. Deny `SendMessage` to a stopped agent whose transcript is
  over the budget, and name the fresh-agent-from-brief route instead.
- A concurrency cap. Deny `Agent` when the running teammate count is at a
  configured maximum.
- Owner-side: `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` lowers the compaction
  trigger for subagents too. At about 570k today, a 500k trigger saves only
  about 12%. A trigger near 150k to 200k is where the cost falls materially.

### N61 — The `sensitive_content` commit gate misses a file that a same-command `git add` stages

**Found by the upgrade-scripts agent**, on main at a93c4b0ad and on the Plan
00464 branch alike. The commit gate scans only what is ALREADY staged when
the Bash command is judged. So `git add leak.txt && git commit -m x` is
allowed even when `leak.txt` matches a public pattern. The same commit with
`leak.txt` staged beforehand is denied. The realistic script shape, add then
commit, is the one that passes.

**Candidate remedy:** when a command both stages and commits, judge the
union of the current index and every path the same command's `git add`
(and `git commit -a`/`-u`/pathspec) would stage, read from the working tree.
Where the added set cannot be resolved (a glob, a computed argument, `git add .`), take the working-tree changes git itself reports as the set. Never take
an empty set: an unresolvable one denies. This is the same class as N53
review 3's MA-2 shapes, so it is fixed on the N53 branch. RED tests:

- `git add leak.txt && git commit -m x` denies;
- `git add . && git commit -m x` with a leaking untracked file denies;
- a clean add-then-commit is allowed.

### N60 — `curl_pipe_shell` denies a double-quoted `echo` argument that only mentions the pattern

**Found by the coordinator.** It appended a queue note with
`echo "... <download tool> ... | sh ..." >> file`. The text inside the double
quotes is data for `echo`: the shell runs no pipe there, and there is no
substitution in it. R-CURL-PIPE-SHELL denied it anyway. So the handler matches
the raw command text, not the pipeline structure.

**Candidate remedy:** judge only real pipeline stages. The producer stage must
be a download command, the consumer stage must be a shell, and both must be
outside quotes and outside a heredoc body that nothing executes. This belongs
with the shell-parser consolidation (N22, N32, N36, N48, N49, N51, N57, N58).
A second shape was denied too: a QUOTED-delimiter heredoc fed to `cat >>`.
The body of such a heredoc is literal text, and `pipe_blocker` already
exempts it. RED tests:

- the reported `echo` is allowed;
- `cat >> f <<'EOF'` whose body mentions the pattern is allowed;
- a real `<download> URL | sh` still denies;
- `bash -c "<download> URL | sh"` still denies, because the string IS
  executed.

### N59 — A signal is sent to a PID nobody proved is the intended process, and it killed the container twice

**Found by the infra owner.** The container died with exit 137 at 11:07 and
11:36 UTC on 2026-09-25, taking every agent, gate and session with it. The
dev VM showed no OOM kill and no external kill, so the kill came from inside.

**Why the first two deaths happened (proven).** N53's uncommitted B2 work had
`run_git` call `os.killpg(os.getpgid(process.pid), SIGKILL)` on timeout.
Its tests patch `subprocess.Popen` with a plain `MagicMock`. A `MagicMock` pid
coerces to `1` through `__index__`, and `os.getpgid(1)` is `1` here, because
PID 1 is `tini`, the container's init. So a test that reached the timeout path
ran `killpg(1, SIGKILL)` and ended the container. Both deaths came about 10 s
after an N53 fixer ran those tests (11:07:16 and 11:35:54). The daemon restart
at 11:35:59 is not the cause: `cmd_stop` signals only a pid that
`read_pid_file(..., verify_daemon=True)` proved is a daemon.

**The class is wider than N53.** On main, `install/client_validator.py` reads a
pid from a `daemon*.pid` file and sends SIGTERM, then SIGKILL, with no identity
check. PID files survive a container restart, and a restarted container reuses
small PIDs, so a stale file can name `claude` itself.

**Remedy (in progress):**

- a signal with a nonzero number goes only to a pid proven to be the intended
  process: a verified daemon, or a child this code started in its own session
  that still leads its group;
- a detector that fails QA on any `os.kill` or `os.killpg` whose pid is not
  proven that way;
- a test-suite safety net that refuses any signal to pid 1, to init's group,
  or to the test runner's own group or ancestors;
- a guard on N53's branch in `_kill_process_group`: only a real int pid above
  1 that leads its own group, and never this process's own group.

### N58 — R-CHMOD-WORLD-WRITABLE denies a safe chmod when a later argument contains digits

**Found by N53 review 2.** `chmod 755 f && echo <path>` was denied as
R-CHMOD-WORLD-WRITABLE. The path was a venv directory name containing a digit
run such as `-1246-py311-`. Mode 755 is not world-writable, so the deny is a
false positive. The matcher appears to read a mode from text outside chmod's
own mode argument.

**Candidate remedy:** parse chmod's argv and judge only its mode operand,
octal or symbolic, on each chmod invocation in the command. Other words and
other commands must never be read as a mode. RED test: the reported command
is allowed, while `chmod 777 f`, `chmod o+w f` and `chmod a+w f` still deny.

### N57 — `secret_file_guard` misses a protected path reached through an earlier assignment, alias or written file

**Found by the guard-defects fix (gd6_shell2 probe).** The Bash scanner reads a
command once, forward, with no memory of what an earlier statement in the same
command bound. So four shapes reach a protected file without a deny:

- a variable assigned the path, then used in `bash -c "$V"`;
- the same, used via `eval "$V"`;
- an `alias` defined to read the file, then invoked;
- a file written earlier in the command (a redirect with the path in its
  content), then run with `sh <file>`.

These are real fail-opens, not accepted residuals.

**Candidate remedy:** this is assignment and side-effect tracking, which Plan
00464's resolver already does for git (`_substitute_known_path_vars`, disk
writes read back by path). Build one shared tracker in the shell-parser
consolidation and have both secret_file_guard and the commit gates consume
it. RED tests: the four gd6_shell2 rows through the real guard.

### N56 — Tests skip when run as root, so this container never runs them

**Found by the owner, who set the rule:** every test must run as root, and
no test may skip because the process is root. This container, and the
dogfood server, run as root. So a root-guarded skip is a test that never runs
where the work happens. Tests that skip on `os.geteuid() == 0` today:

- `tests/claude_code_hooks_daemon/install/test_skills.py:146`
- `tests/integration/test_settings_deploy_lib.py:189`
- `tests/unit/daemon/test_bootstrap_decision.py:206`
- `tests/integration/test_skipif_reasons_match_their_conditions.py:88`

Plan 00351's `test_skipif_reasons_match_their_conditions.py` also endorses
the pattern: it checks that a root skip's condition is written correctly
rather than forbidding it.

**Candidate remedy:** rewrite each test so it proves its behaviour as root.
Permission checks are ineffective for root, so use a fault that root cannot
bypass: an injected opener or os call that raises `PermissionError`, a
directory or dangling symlink in place of a file, or a read-only bind or
immutable file where one is available. Replace Plan 00351's check with a
detector that fails on any root-conditioned skip. Record the rule in the
testing standards doc.

**Done, on `worktree-n466-n56`:** the three skip sites are rewritten to
fault the operation a way root cannot bypass, keeping each test's original
assertion:

- `test_skills.py`'s `test_deploy_skills_raises_if_target_not_writable`
  monkeypatches `shutil.copytree` to raise `PermissionError` instead of
  `chmod`-ing the target read-only.
- `test_settings_deploy_lib.py`'s `test_a_failed_backup_stops_everything`
  stubs the shell `cp` used for the backup copy (matched on its destination
  suffix `*.bak-*`, so the install copy is untouched) — the same technique
  `TestTheInstallCopyCanFail` already used for the install copy.
- `test_bootstrap_decision.py`'s `test_untracked_not_writable` monkeypatches
  `os.access` itself, since `access(2)` grants `W_OK` to a privileged real
  UID regardless of the mode bits.

`test_skipif_reasons_match_their_conditions.py` is replaced by
`tests/integration/test_no_root_conditioned_skips.py`: a static scan over
EVERY `.py` file under `tests/` — not just `test_*.py`/`conftest.py`, and
with no exclusion list (review 2, B2: an earlier cut excluded a
`fixtures`/`assets`/`__fixtures__` directory name and its own file, which
pytest actually collects through). It classifies by data flow rather than by
name (review 2, B1), so an alias, a local variable, a module constant, or
one level of same-module helper (including a parameterised one called with
literal arguments) is resolved the same as the direct call — covering
`geteuid`/`getuid`/`getegid`/`getgid`/`getresuid`/`getresgid`,
`getpass.getuser`, a `pwd`/`grp` lookup, an env check of
`USER`/`LOGNAME`/`HOME`/`SUDO_*`, `Path.home()`/`os.path.expanduser("~")`,
`os.access(...)`, and `<expr>.stat().st_uid`. It fails on a
`skipif`/`xfail`/`unittest.skipIf`/`skipUnless` decorator, an `IfExp`
marker, a hand-written `if <root check>: skip/xfail/skipTest/return`, or a
conftest `pytest_ignore_collect`/`pytest_collection_modifyitems`/
`pytest_runtest_setup` whose control flow depends on one — **and
independently** on any skip-like call whose stated *reason* names root
regardless of what its condition tests (review 1, F1: this is Plan 00351's
own shape, which the first cut of the detector regressed). A reference it
cannot resolve (a cross-module import, a class attribute) whose own name
suggests process identity is reported as unproven rather than silently
passed. `tests/relay_gate_guard.py` and its test are left alone (documented
why): that guard's "Running as root" case is a reason-string classifier for
a different, CI-only concern, not a root-conditioned skip itself.

Review 1 (F5) also found two tests outside the three skip sites that were
vacuous as root without skipping: `test_auto_continue_stop.py`'s
`test_matches_handles_oserror_reading_transcript` (`chmod(0o000)`, root
still reads the file) now monkeypatches `Path.open` inside
`TranscriptReader._parse_tail`; `test_paths.py`'s
`test_socket_path_over_limit_uses_run_user` (skipped when `/run/user/{uid}`
is absent — a host-dependent skip, not a root one) now monkeypatches
`Path.is_dir` so the branch runs deterministically. Review 2 (M1) found a
third: `test_hooks_deploy_permissions.py`'s chmod-failure contract had been
replaced by a lexical check on the installer's source because root's own
chmod never fails; it now stubs `chmod` as a shell function that fails for
one hook file, the same technique `test_settings_deploy_lib.py` uses for
`cp`.

Review 3 found two more evasions of the hand-written `if <root check>: ...`
shape, both closed: a `pass`-only branch opposite a substantive one (`if root: pass else: assert ...`), and an `assert` gated by identity with no
`else` at all. Both needed a new `_root_polarity` helper to tell which
branch actually runs AS ROOT — only a no-op on that branch is a problem in a
container that is always root; the reverse (no-op on the non-root branch) is
fine and must not be flagged, or `getuid_used_non_skip` (already in the
`_SHOULD_NOT_FIND` corpus) would false-positive. One evasion is left as a
documented, owner-referred residual: `try: <op that only raises PermissionError as non-root> except PermissionError: return` followed by an
unconditional skip has no syntactic root check anywhere — the
root-dependence is a runtime property (what `open()` does), not something a
static AST scan can read. It is tracked as
`_KNOWN_RESIDUALS["try_except_permission_pass"]` in the detector's own test
file, asserted to stay uncaught so a future fix flips that assertion red
rather than the note going stale.

The rule is recorded in `CLAUDE/QA.md`, next to the other test requirements.

### N55 — `register_all` ignores a handler's `get_default_enabled()` when its config block is absent

**Found by goal-flip review 8 (RV8-n3), filed at review 9's request.** When a
handler has no block in `.claude/hooks-daemon.yaml`, `register_all` registers
it as enabled whatever its `get_default_enabled()` says. So a handler that is
opt-in by design runs on an install whose config never mentions it, such as
one made by `init minimal`. The goal-flip branch changed the docs to describe
this behaviour accurately, but the underlying behaviour is still unsettled.

**Candidate remedy:** decide which source is authoritative for an absent
block: `get_default_enabled()` or "absent means enabled". Make
`register_all`, `init minimal`'s generated config and the docs agree on it.
RED test: an opt-in handler with no config block is not registered, or the
docs and the handler's own default are changed to say it is.

### N54 — Every Stop and SubagentStop pays about 50 ms rebuilding `Config()` while the config is broken

**Found by goal-flip review 8, measured again by review 9.** With an
unloadable `.claude/hooks-daemon.yaml`, five callers fall back to building a
default `Config()` on every event, and each build costs about 50 ms.
`cron_stop_enforcer` and `cron_subagent_stop_enforcer` are among them, so
every Stop and SubagentStop pays it for as long as the config stays broken.
The evidence is in `untracked/scratch/probe_gf9_cache/callers_out.txt` in the
goal-flip worktree. The config cache already caches the load failure itself;
the fallback default is what is rebuilt each time.

**Candidate remedy:** build the fallback default once per cached failure (key
it on the same `(st_mtime_ns, st_size)` signature) or share one immutable
default instance. RED test: two consecutive events on a broken config build
the default once.

### N53 — WorktreeCreate fails with exit 127 when the daemon runs `git worktree add` that succeeds from a shell

**Found by the coordinator.** An Agent dispatch with `isolation: worktree`
failed. The WorktreeCreate hook reported "Handler exception:
CalledProcessError: Command \['git', '-C', '/workspace', 'worktree', 'add',
'-b', '<branch>', '<path>'\] returned non-zero exit status 127". The same
command, run from the coordinator's shell, exits 0. It takes over 2 minutes
on this host, with 4,076 files. The main daemon's own PATH includes
`/usr/bin`, and the repo has no post-checkout hook. So the daemon runs git
in an environment where something git executes cannot be found. An agent
dispatch then fails outright, with no fallback.

**Candidate remedy:** reproduce through the handler with the daemon's real
environment. Suspects: an env the handler builds for the subprocess (PATH
or HOME stripped, or GIT_EXEC_PATH), or a timeout wrapper. Fix the root
cause. Make the handler report the command's stderr in the failure, so the
next such failure names what was not found. Check whether a slow checkout
on a loaded host needs a longer timeout. RED test: the handler, given the
daemon's environment, creates a worktree.

### N52 — The sensitive_content commit gate let a matching session UUID into a commit

**Found by N46 review 2.** Commit `3da8c1ed` on the N46 branch added a review
report containing a real session UUID. The project's `session-uuid` public
pattern matches that blob, and no `exclude_paths` entry covers
`CLAUDE/Plan/`. Yet the commit gate, which scans the added lines of staged
files, allowed the commit. Nothing later caught it either:
`check_sensitive_content.py` scans only the current tree, and
`check_git_history.py` scans metadata but not historical blobs. A `--no-ff`
merge followed by a push would have published it permanently.

**Candidate remedy:** reproduce the miss in a scratch repo first. The
reviewer's untested hypothesis is that the commit ran with a cwd or `-C`
target different from the checkout the gate diffed, which is the Plan 00464
class. Then fix the gate. Add a merge and push check that runs the public
patterns over the added lines of `git log -p <upstream>..HEAD`, since that
is exactly the window this leak survived in. RED tests: the reproduced
commit shape is denied; a merge carrying the blob is denied.

### N51 — `pipe_blocker` reads an escaped alternation inside a quoted grep pattern as a pipe into `head`

**Found by Plan 00421 review 2.** `grep -i -n "a\|HEAD\|b" file` was denied.
The `\|HEAD` inside the double-quoted pattern is a basic-regex alternation,
not a pipe. The blocker split on the `|` and matched the next word
case-insensitively against `head`. That is the N32 class (a `|` inside quotes
read as a pipe stage), plus a case-insensitive match on the producer name.

**Candidate remedy:** find pipe stages with the shared shell segmentation, so
a `|` inside any quoted span, or escaped, never splits. Match the stage's
command name case-sensitively, as bash does. RED tests: this grep is allowed;
`pytest | head` is still denied. This belongs to the shell-parser consolidation
(N41) alongside N32.

### N50 — A handler option whose name matches a method overwrites that method, and the handler then crashes open

**Found by N23 review 2.** `registry.py:592` injects each configured option onto
the handler with `setattr`. An option named like one of the handler's methods
replaces the method. For example, the pre-Plan-00288 option `human_docs_dir`, or
`pauses_path`. The handler then raises on every dispatch. For
`markdown_organization` that lets a misplaced `.md` file through.

**Candidate remedy:** never let an option overwrite a callable or any attribute
the class defines. Options go into a dedicated mapping, or the injection
refuses a name that collides with a class attribute, with a clear config error
naming the option and the handler. Known renamed options get a migration
message. RED tests: a colliding option gives a config error and never crashes
the handler; `markdown_organization` still denies with the stale option set.

### N49 — `daemon_location_guard` denies a `cd` into the daemon directory that is only text inside a quoted argument

**Found by the coordinator.** A `printf '...'` whose single-quoted string
mentioned the words cd, then the daemon directory path, was denied
R-DAEMON-DIR-CD. The command appended a note to a queue file and changed no
directory. So the guard matches the shape anywhere in the command text and
does not look for a real `cd` command.

**Candidate remedy:** judge real command heads through the shared shell
segmentation, so only an actual `cd` (or `pushd`) whose target resolves into
the daemon directory is denied. Text inside a quoted argument, a heredoc body
or a commit message is not a directory change. RED tests: the printf case is
allowed; a real `cd` and a `cd` after `&&` or `;` are still denied. This
belongs to the shell-parser consolidation (N41).

### N48 — `sed_blocker`'s git-commit exemption reaches across a newline

**Found by N38 review 2** (pre-existing, not caused by that branch). The
exemption lets `sed` through when it follows `git commit` with no command
separator in between. A newline is a command separator, but the exemption
does not treat it as one. So `git commit -m x` on one line, followed by a
line that runs `sed -i`, is allowed. The command runs sed.

**Candidate remedy:** use the shared shell segmentation, so that a newline
ends the `git commit` segment. The exemption then covers only a `sed` inside
that segment's message argument. RED tests: sed on the next line is denied;
sed after a newline inside a quoted message is still exempt. This belongs to
the shell-parser consolidation (N41).

### N47 — The ccy supervisor and Claude Code's settings.json both own effort, and they fight

**Found by the owner.** They asked for medium effort. Claude Code reads effort
from `settings.json` (`effortLevel`, and `modelSettings.<model-id>.effortLevel`
per model). The supervisor (`.claude/ccy/claude-supervise.py`) keeps its own
answer and types `/effort` over it:

- `_DEFAULT_MIN_EFFORT_LEVELS` (opus=high, sonnet=high) is a floor the
  supervisor raises live effort to. It knows nothing of `settings.json`, and
  has a second override channel of its own, the `CCY_MIN_EFFORT_LEVELS` env
  var in `ccy.env`.
- `_coupled_effort_target` sends `/effort xhigh` after EVERY `/model` switch to
  a non-top family, including the restore back to the session's own Opus. And
  the floor only ever raises. So one downgrade-and-restore cycle leaves the
  session at xhigh for good, whatever `settings.json` says.

Setting medium therefore needed two edits in two formats (`settings.json` and
`ccy.env`, commits 909f9591 and e52bd9e5). Even then the restore path still
lands on xhigh.

**Remedy (redesigned again after adversarial review 2**,
`subagent-reports/260925-n47-review2.md`**, which found review 1's fix was
still architecturally wrong at the root):** BLOCKER 1 — Claude Code SAVES
every interactively-typed `/effort <level>` into `modelSettings` in the
settings file the confirming `Enter` targets (`model-config.md:552-557`,
`settings-reference.md:900`). So ANY supervisor-typed `/effort`, no matter
how well the level behind it was resolved, permanently overwrites the
owner's own saved level — the exact fight the whole redesign exists to end,
just moved one layer down into the single source of truth itself.

The supervisor now injects **no `/effort` of any kind, for any reason,
ever**:

- The built-in floor map, `CCY_MIN_EFFORT_LEVELS`, the settings.json reader,
  the coupled-effort correction and the downgrade-xhigh compensation are all
  gone entirely, not just superseded.
- The two behaviours those mechanisms provided are now DATA the owner adds
  to their own `modelSettings` — a `claude-fable-5-1` entry at `low`
  (replacing DROP ANCHOR) and `claude-opus-5`/`claude-opus-4-8` entries at
  `xhigh` (replacing the downgrade compensation, covering Fable's two
  automatic-fallback targets, and now broader than the old compensation
  since it applies whenever Opus 5 or 4.8 serve, not only a fable-origin
  episode). See `CLAUDE/development/CcySupervisor.md` for the exact entries.
- MAJOR 4 fixed alongside: `model_downgrade_recorder`'s signal republishes
  the SAME record for the life of a session, even after its episode fully
  closed. A human who later manually switched back to the fallback family
  produced the identical observation the old `session:from:to` attribution
  key matched again, reopening an episode and firing `/model fable` at them.
  A record now has an identity (`record_id`: the transcript entry's `uuid`,
  or its line's byte offset; the standalone record of a downgrade keeps its
  block's identity), the state machine spends that identity when the episode
  recovers, and a record attributes only a drop observed within
  `_DOWNGRADE_ATTRIBUTION_WINDOW_SECONDS` (300s) of the downgrade it records
  (review 4 findings 3 and 4). Retroactive attribution of a drop seen before
  its record was published applies the same judgement at the moment the drop
  was seen, after the tick's reading, and writes a decision-log line.
- `hooks-daemon check` holds no effort opinion either (review 4 finding 2):
  "Effort Level" (which failed anything but `high` and recommended
  `CLAUDE_CODE_EFFORT_LEVEL=high`, a pin on every model) is replaced by
  "Effort Source", which warns only about such pins.

**Correction (review 3**, `subagent-reports/260925-n47-review3.md`**): the
`modelSettings` claim above is CONDITIONAL, and review 2's design doc
overstated it.** Claude Code tracks ONE session-level effort value
(`sessionEffort`), which starts `inherit` (per-model `modelSettings` applies)
but is PINNED to a fixed value by ANY of: `/effort <level>`, `/effort auto`,
an effort pick made in the `/model` picker's slider, `--effort`, or
`CLAUDE_CODE_EFFORT_LEVEL`. Once pinned, that ONE value follows the session
across every later model AND every automatic fallback — confirmed against
`model-config.md:544-548` (explicit choice ranks first, no per-model
qualifier) and the installed Claude Code 2.1.282 binary's `sessionEffort`
resolver. `/effort auto` does NOT return to `inherit`; it pins to the
model's BUILT-IN default (ignoring `modelSettings`) and additionally WRITES
— it clears the current model's saved `modelSettings` entry
(`settings-reference.md:1211`). **Nothing found un-pins a session mid-flight.**
So: **`modelSettings` alone can make Fable run at low and its fallback run
at xhigh only for a session that never touches `/effort`, an effort slider
pick, `--effort`, or the env var.** If the owner wants a specific level
right now, typing `/effort` remains a deliberate one-time choice that pins
the REST of that session — exactly as before this plan — and no
settings-only configuration recovers per-model behaviour within it. The
owner decides whether that trade-off is acceptable; the fix here only
removes the SUPERVISOR as a second party to the fight.

`tests/unit/supervise/test_no_effort_injection.py` asserts on the PAYLOADS
that the supervisor never types `/effort`, driving `decide_once` (and
`run_worker` for the raw-input tap) through real sidecar sequences: Fable at
medium, high, xhigh and max (the removed DROP ANCHOR's trigger), a whole
attributed downgrade episode through restore and recovery, a manual model
pick, the operator `/model` switch signal, a compaction and its resume, and a
human-typed `/effort max`. Each scenario also asserts it reached its path.
`test_settings_effort.py`, `test_drop_anchor.py`, `test_effort_restore.py`
and `test_unattributed_effort_drop.py` are deleted outright (the behaviour
they covered no longer exists) — `test_effort_restore.py`'s NON-effort tests
(live `/model` auto-restore: backoff, delay, the off setting, confirm
enters, family ranks, the dry-run marker, and the restore cap pinned as the
literal 2) are restored under `test_model_restore.py`. `test_attributed_downgrade.py`
covers the record identity, the attribution window, every retro-attribution
and hot-reload backfill guard (each asserted on the `/model` payload or the
exported state it owns), and the export round-trips.

### N46 — `budget_exhaustion_detector` fires on a tool result that merely contains budget wording

**Found by the guard-defects review-6 agent.** Reading a diff whose source
code contained the string "exceeded its byte budget" raised the "budget
exhausted" alert. That text belonged to the file under review; the agent's
own budget had not run out. So the detector matches words anywhere in tool
output. A false alarm like this teaches agents to ignore the real one.

**Candidate remedy:** match only the harness's own budget-exhaustion signal,
meaning its exact shape and source. Never match free text inside a tool
result's content, such as a file or a diff. Add a RED test that reads a file
containing the phrase and expects no alert, and keep the real signal firing.

### N45 — A NUL byte in a configured word-list path makes the never-raising secret-term lookup raise

**Found by the Plan 00421 agent** while fixing N43. A NUL byte in a HEALTHY
config's `sensitive_content.secret_word_list_path` gets through
`normalise_repo_relative_path`. It then reaches `get_cached_secret_terms`,
where `path.stat()` raises ValueError, and the code there catches only
OSError. So `get_active_secret_terms` raises, although it is documented as
never raising. It does so on every leak-vector call site: the router's debug
log, the front controller and payload capture. That is where redaction must
never fail.

**Candidate remedy:**

- Validate every configured path option at config load, and reject NUL and
  other non-path bytes with a clear config error.
- Make the term lookup honour its never-raise contract: catch ValueError
  beside OSError, and treat a list that cannot be resolved as a reported
  problem that never means "redact nothing".
- Sweep the other `Path.stat`, `open` and `resolve` calls on config-supplied
  paths for the same gap.

RED tests cover the config error and each leak-vector site.

### N44 — ✅ Remedied — A PreToolUse handler raises `ValueError: no path specified` on an Edit, and the Edit goes through

**Found by the Plan 00464 agent** while editing
`src/claude_code_hooks_daemon/utils/git_command_target.py` in its worktree,
with its hooks served by the main `/workspace` daemon. The hook context
returned `Handler exception: ValueError: no path specified`, and the Edit was
allowed. That message is what `os.path.relpath("")` raises.

**Root cause, confirmed by reproducing through the real chain with the
project's real config and word list**: the `secret_file_guard` Bash-mention
scanner (`R-SECRET-BASH-MENTION`, `utils/secret_file_matching.py`) tokenises a
command and, for a token that starts with a home-directory prefix such as
`~/`, appends the token with the prefix stripped as an additional spelling to
match against protected globs. A token that IS the prefix and nothing else
(a bare `~/`, as in `cp ~/ /tmp/x`) strips to the EMPTY string. That empty
candidate then reaches `utils/path_exclusion.path_matches_globs` (via
`utils/path_segments.matches_path_segment` on a second call path), the shared
chokepoint every content-guard handler funnels a candidate path through,
which computed `os.path.relpath("", project_root)` and raised. The exception
propagated out of the handler and was swallowed upstream, so the command it
was judging went through unblocked — the fail-open half of this defect is
ledger N24's class, closed separately on the n24 branch.

**Fix**: `_normalised_token_forms` now drops the stripped-home form when it is
empty instead of appending it, and — independently, since other callers can
still hand these two chokepoints an empty candidate — both
`path_exclusion._candidate_paths` and `path_segments._project_relative_or_none`
now treat an empty `file_path` as "no match"/`None`, the same answer they
already give a path that resolves outside `project_root`, before it ever
reaches `os.path.relpath`. Swept the rest of `src/` for `relpath`/`commonpath`
calls on hook-input-derived paths: no other call site was reachable with an
empty candidate.

### N43 — Log and payload redaction is inert while the daemon runs degraded on an unloadable config

**Found by the Plan 00421 agent** while closing Task 4.9 on `worktree-d-00421`.
`secret_redaction._resolve_active_path` resolves the secret word list through
the configuration. When the config cannot load (the Plan 00421 degraded
mode), that lookup raises ValueError, and redaction falls back to inert. So a
degraded daemon writes its logs and payload captures UNREDACTED, which is
exactly when a broken config makes a protective fallback matter most. The
same root cause left degraded `sensitive_content` with no secret terms; that
was fixed on the branch by pinning the default list explicitly.

**Candidate remedy:** while degraded, redaction uses the default word list
UNION the last-known-good snapshot's lists, the same set degraded
`sensitive_content` uses. A redaction failure to resolve a list must never
mean "redact nothing". Pin it with a degraded-start test that captures a
payload containing a term and asserts the term is redacted. Being fixed on
`worktree-d-00421`.

**Same root cause as N24 review 2's P2** (degraded mode turns guards off): a
degraded daemon resolves nothing through the config it could not load. Both
are fixed by that branch's `daemon/degraded_mode.py` and
`secret_redaction.use_degraded_word_lists`, and not on the N24 branch.

### N42 — Quoted-heredoc blanking hides text that bash executes from the Bash command guards

**Found by the N38 review** (its M3), confirmed against real bash, and
unchanged between the old regex and the new N38 scanner. `shell_segmentation`
treats a quoted-heredoc body as inert data. Several guards then blank that
text and never judge it, among them destructive_git, pipe_blocker,
curl_pipe_shell, force-push detection and, for one shape, sed_blocker. There
are seven shapes where the blanked text is not a heredoc body at all, and
bash runs it:

- an EMPTY body (`cat > n <<'E'` with `E` on the very next line, followed by
  a command and a second `E` line), with its `<<-` form and a
  `git commit -F -` form;
- an opener inside a `#` comment;
- an opener inside a double-quoted string;
- a `<<<'E'` here-string read as an opener;
- a quoted opener inside an UNQUOTED heredoc's body;
- the same inside a multi-line double-quoted string;
- an unquoted heredoc followed by a quoted one on the same line.

In each shape, a destructive or piped command is ALLOWED. The probes are in
`untracked/scratch/probe_n38r_*`. This is a fail-open in the guards
themselves, so it is fixed now on the N38 branch and not deferred to the
consolidation.

**Candidate remedy:** recognise an opener only where bash would: outside
quotes, comments and here-strings, and not inside another heredoc's body.
Close an empty body on the first delimiter line. Keep the scan to one linear,
quote-aware pass. Pin every shape through the real chain.

### N39 — Nine unit tests fail in a whole-suite run and pass when their files run alone

**Partially Remedied on this branch (main-based worktree, commit below):**
the widened-scope items 2 (socket-listener fixed-sleep race,
`started_event`) and 3 (`blocking_gate_guard` skip-to-failure escalation) are
fixed here. Widened item 1 (docs-rewrite mid-run) is recorded as a procedure
note plus a sharpened teardown-guard message, not a code fix (no test-side
leak was found). **The original defect** (the two-layer-patch leak in
`test_project_containment.py`) is diagnosed but NOT fixed on this branch — it
is being fixed on `worktree-n466-guard-defects` by a different agent, per the
fix recipe below.

**Found by the guard-defects agent** (its review-4 fix round). A plain whole
unit-suite run on `worktree-n466-guard-defects` (main merged at `e14cdca4`)
gave 9 failures. They were in `test_model_fallback_detector.py`,
`test_absolute_path.py`, `test_lookup.py` and
`test_dangerous_invocation_corpus_checker.py`. The same four files run alone
gave 105 passed, 0 failed. So some earlier test leaks state (a module global,
a singleton, the environment or the cwd) into these. The full gate passed on
`main`, so the leak depends on order or on how the suite is split across
workers.

A suite that fails in one order is a hidden defect: it can hide a real
failure behind a "flaky" label, and it breaks the first time the ordering
shifts.

**Diagnosed by a follow-up agent.** `main` does NOT reproduce it: a plain
sequential `pytest tests/unit -p no:xdist -q` on `main` at `c92bfbc1` gives
22451 passed, 0 failed. The same run on `worktree-n466-guard-defects` at
`ef0600ed` reproduces exactly 9 failures (22606 passed) in
`tests/unit/handlers/session_start/test_model_fallback_detector.py` (6),
`tests/unit/handlers/test_absolute_path.py` (1),
`tests/unit/rule_explain/test_lookup.py` (1, NOT
`tests/unit/remote_docs/test_lookup.py` — the two victim files share a
basename) and `tests/unit/scripts/test_dangerous_invocation_corpus_checker.py`
(1). So the leak's source exists only on `worktree-n466-guard-defects`, not
on `main`.

**Root cause, bisected to two exact test methods and confirmed with an
isolated 20-line repro (independent of this project's own code).**
`tests/unit/handlers/pre_tool_use/test_project_containment.py` carries a
class-wide `autouse` fixture, `_project_root` (added long before this defect):

```python
@pytest.fixture(autouse=True)
def _project_root() -> Any:
    with patch("...ProjectContext.project_root") as mock:
        mock.return_value = _ROOT  # Path("/repo")
        yield mock
```

Two tests added by commit `d0de526d1`
(`TestFailsClosedOnEvaluationError::test_an_uninitialised_project_root_still_denies`
and `::test_an_evaluation_error_denial_uses_its_own_rule_id`), plus one added
by commit `3e3164bd`
(`TestChainLevelFailClosedBehaviour::test_an_evaluation_exception_still_denies_through_the_chain`),
each ALSO calls
`monkeypatch.setattr("...ProjectContext.project_root", classmethod(lambda cls: _raise()))`
— a SECOND, independent patcher layered on top of the first,
targeting the exact same attribute. `monkeypatch`'s own finalizer runs AFTER
the `_project_root` fixture's `with patch(...)` block has already exited and
restored the TRUE original classmethod, so `monkeypatch.setattr`'s teardown
overwrites it AGAIN — with whatever it had captured as "current" at
`setattr()` time, which is the `_project_root` fixture's own `MagicMock`.
Result: `ProjectContext.project_root` is left PERMANENTLY pointing at that
mock (`return_value=Path("/repo")`, no `_initialized` check at all) for the
rest of the pytest PROCESS. Confirmed with a minimal repro outside this
project (`untracked/scratch/repro_fixture_order/test_order.py`, not
committed): a class with the same two-layer-patch shape leaves the SAME kind
of leak, reproducibly.

Every later test that calls `ProjectContext.project_root()` in that process
then gets the fake `/repo` root, unconditionally — explaining all four victim
files:

- `test_absolute_path.py`: `_absolute_example()` calls
  `ProjectContext.project_root()` directly; the leak makes it return `/repo`
  instead of raising `RuntimeError`, so `"Example: /repo/test.py"` appears
  where the test expects it omitted.
- `test_model_fallback_detector.py` (6 tests): `_resolve_snapshot_dir()`
  (`model_fallback_detector.py:558`) returns `ProjectContext.project_root() / configured` once "initialised", instead of falling back to the cwd its own
  `handler` fixture `monkeypatch.chdir`s to `tmp_path` for; snapshots land
  under `/repo/reports` (off the sandboxed `tmp_path`), so every
  `(tmp_path / "reports").glob("*.md")` in these tests finds nothing.
- `rule_explain/test_lookup.py::TestProjectHandlersAreDiscoverable:: test_project_handlers_included_when_requested`: project-handler discovery
  resolves against the fake `/repo` instead of the real project root, so it
  cannot find `.claude/project-handlers/`'s `daemon_restart_verifier`.
- `test_dangerous_invocation_corpus_checker.py::TestRealTree:: test_the_real_corpus_matches_the_real_chain`: the REAL chain's
  `ProjectContainmentHandler` resolves its containment boundary via the same
  leaked mock, so `supply-pip-index-url` is newly (and wrongly, for the
  corpus's purposes) denied via `enforce-project-containment` against a
  boundary of `/repo` instead of the real repository root.

Bisection evidence (`worktree-n466-guard-defects`, read-only, its own venv):
`pytest -p no:xdist -q TestFailsClosedOnEvaluationError:: test_an_uninitialised_project_root_still_denies test_absolute_path.py::...test_handle_omits_the_example_rather_than_guessing_a_root`
→ 1 failed, 1 passed (same failure as the whole-suite run). Each of the three
leaking test methods reproduces it alone paired with the victim;
`test_get_rules_includes_the_evaluation_error_rule` (same class, does not
touch `project_root`) does not.

**Status.** This agent's own worktree is based on `main`
(`c92bfbc1`), which does not contain this defect — `test_project_containment.py`
there has no `TestFailsClosedOnEvaluationError`/
`TestChainLevelFailClosedBehaviour` classes at all, so there is nothing to
edit or commit here. `worktree-n466-guard-defects` is a separate, git-isolated
worktree this agent could read but not write or commit to. **The original
leak (the two-layer-patch in `test_project_containment.py`) stays diagnosed
but unfixed here — the fix is being applied on
`worktree-n466-guard-defects`** (a different agent has been handed the recipe
below; not yet landed there as of this writing). Items 2 and 3 of the widened
scope below (the socket-listener race and `blocking_gate_guard`'s escalation)
turned out to live on `main` itself, reachable from this worktree, and **are
Remedied here** — see each item for the commit. Item 1 (docs-rewrite) is
recorded as a procedure note only; no test-side leak was found to fix.

**Fix recipe (for `worktree-n466-guard-defects`):** in the three offending
tests, stop introducing a second patcher. Request the class's own
`_project_root` fixture by name (it already yields its `mock`) and reconfigure
THAT mock instead of calling `monkeypatch.setattr` on the same target —
e.g. `mock.side_effect = _raise` in place of the `monkeypatch.setattr(..., classmethod(lambda cls: _raise()))` call, dropping the `monkeypatch` parameter
from tests that no longer need it. As a structural tripwire against the same
class of bug from ANY future test in this file, add a post-`yield` assertion
to `_project_root` itself:

```python
    yield mock
    assert isinstance(ProjectContext.__dict__["project_root"], classmethod), (
        "ProjectContext.project_root leaked past this fixture's teardown "
        "(Plan 00466 N39) -- a test double-patched it instead of "
        "reconfiguring this fixture's own mock"
    )
```

Pin the specific pair with a regression test appended to the file (runs after
the fixed `TestFailsClosedOnEvaluationError`, so it exercises real,
unpatched behaviour exactly like `test_absolute_path.py` does downstream):
mirror that test's own assertion — `monkeypatch.setattr` `ProjectContext. _initialized`/`_instance` to a clean, uninitialised state, run
`AbsolutePathHandler().handle(...)`, assert `"Example:"` is absent from the
reason.

**Candidate remedy (superseded by the diagnosis above):** ~~reproduce it on
`main` with a plain sequential run, then bisect for the polluting test.~~
Done; see above.

**Widened scope (coordinator directive).** A separate agent's whole-suite
`pytest tests/ -q` on `worktree-n466-goal-flip` (tip `95ac6de9`) found three
more defects in the same suite-isolation class: 1 failed, 26782 passed, 35
skipped, 3 xfailed, 13 errors. `worktree-n466-goal-flip` is, like
`worktree-n466-guard-defects`, a separate git-isolated worktree: this agent
verified directly that even `git worktree add` of a brand-new path from its
own worktree is refused ("a worktree-isolated agent's git operations must
target its own worktree"), so none of the three fixes below could be
committed from here either. All three are diagnosed to a concrete fix.

**Follow-up (coordinator directive): items 2 and 3 are NOT branch-only — the
affected files (`tests/unit/daemon/test_event_socket_listeners.py`,
`tests/acceptance/blocking_gate_guard.py`) are on `main`, hence reachable
from this agent's own `main`-based worktree. Both are Remedied HERE** (see
each item for the commit and tests added); the fix does not need to land on
`worktree-n466-goal-flip` separately — merging `main` forward carries it.
Item 1 remains diagnosis-only: the coordinator accepted the external-daemon-
restart evidence and asked for a procedure note plus, if cheap, a sharper
teardown-guard message — also done here, see item 1.

1. **Docs-rewrite-mid-run, evidence points to an EXTERNAL daemon restart, not
   a test.** `tests/conftest.py`'s `no_test_writes_tracked_generated_docs`
   fixture (autouse, per-test baseline+diff) caught `CLAUDE.md` mutated during
   the run, attributed to whichever test's window the write fell into (3
   errors: `test_skill_scripts_venv_resolution.py`,
   `test_skipif_reasons_match_their_conditions.py` x2 — the fixture already
   names these as VICTIMS, not culprits, and its own docstring anticipates
   exactly this). Timestamp correlation: `CLAUDE.md`'s mtime is
   `2026-09-25 01:48:53`, to the second the same moment a REAL
   `claude_code_hooks_daemon.daemon.cli --project-root .../worktree-n466-goal-flip restart` process (pid 612977, still running)
   started — squarely inside the run's `01:37`-`01:58` window. `CLAUDE.md`'s
   own header states it is regenerated on daemon restart. This reads as a
   live, concurrent session restarting that worktree's own daemon while the
   21-minute suite happened to be running — an external edit landing inside
   an unrelated test's window, not a test bug. A `grep` for
   `ClaudeMdInjector`/`DaemonController(` still names ~19 candidate test
   files that construct a real controller, so an actual test-side leak is not
   fully ruled out, but the second-precision timestamp match is strong
   evidence against it. **Recipe if further evidence implicates a test
   instead:** point its `workspace_root` at `tmp_path` (as the fixture's own
   docstring instructs) rather than the real repo.

   **Accepted as a procedure note (coordinator directive): do not restart
   this project's own daemon while a test run is in progress.** A restart
   re-runs `ClaudeMdInjector` against the real repository exactly like a
   misconfigured test would, and lands inside whichever test's window the
   restart happens to overlap — there is nothing test-side to fix for this
   part.

   **Guard sharpened (cheap, done here on `main`):**
   `no_test_writes_tracked_generated_docs` now also stats this project's own
   daemon pid file (`get_pid_path(_REPO_ROOT)`) at fixture setup and
   teardown. When a mutation is caught AND the pid file's mtime changed
   across that same window, the assertion names the pid file and its
   before/after mtimes directly ("an external daemon restart/start/stop
   happened WHILE THIS TEST RAN") instead of only the generic "IF NO TEST
   TOUCHES THESE FILES, suspect an EXTERNAL edit" text — precisely the signal
   that would have named pid 612977's restart above without needing the
   manual timestamp correlation. The extracted helper,
   `_daemon_pid_file_mtime`, has 3 regression tests in
   `tests/unit/test_conftest_docs_guard_culprit.py` (does-not-exist ->
   `None`, exists -> its mtime, restart-shaped unlink+recreate -> mtimes
   differ). This does not fully close the gap (an external edit that does
   NOT touch the pid file, e.g. a hand edit, still falls back to the generic
   text — the fixture still cannot distinguish that from a test's own write),
   but it now names the one external cause actually observed here.

2. **`test_bind_time_rmtree_failure_is_logged_not_swallowed[asyncio]` is a
   plain fixed-sleep race.** `tests/unit/daemon/test_event_socket_listeners.py`:
   `server_task = asyncio.create_task(daemon.start()); await asyncio.sleep(0.1); assert len(daemon._event_servers) > 0`.
   `HooksDaemon.start()` (`src/claude_code_hooks_daemon/daemon/server.py:687`)
   awaits `_acquire_socket_and_bind` then `_bind_event_sockets` (which sets
   `self._event_servers`) before reaching `shutdown_event.wait()` — under host
   load those two awaits can outlast a fixed 100 ms, and the test observes
   `_event_servers` still empty. **The same fixed-`asyncio.sleep(0.1)` +
   assert shape appears 13 times in this ONE file** (lines 104, 119, 137, 167,
   195, 246, 291, 315, 330, 362, 396, 445, 470) — a pre-existing, repo-wide
   copy-paste pattern this defect merely surfaced once under load; every one
   of the 13 is equally racy. **Fix recipe:** replace the fixed sleep with a
   bounded poll shared by all 13 call sites, e.g.
   `for _ in range(100): \n    if daemon._event_servers or server_task.done(): break \n    await asyncio.sleep(0.01)`
   (1 s bound, typically resolves in under 10 ms), or — more robust — give
   `HooksDaemon` its own `self.started_event = asyncio.Event()` set right
   after `_bind_event_sockets()` (there is currently no such readiness
   signal, only `shutdown_event`) and `await asyncio.wait_for(daemon.started_event.wait(), timeout=1.0)` in the tests.

   **Remedied here, on `main`.** Added `HooksDaemon.started_event: asyncio.Event()` (`src/claude_code_hooks_daemon/daemon/server.py`,
   `__slots__` + `__init__`), `.set()`'d in `start()` immediately after both
   `_acquire_socket_and_bind` and `_bind_event_sockets` complete — TDD'd via
   `TestStartedEvent` in `test_event_socket_listeners.py` (RED: attribute
   missing; GREEN: 3 tests, added before implementing, 2 of which exercise
   the new readiness signal directly). All 13 original
   `asyncio.sleep(0.1)`-then-assert call sites in that file now await
   `daemon.started_event.wait()` bounded by
   `Timeout.SOCKET_CONNECT` (5 s; `magic_values` QA forbids the bare literal).
   **Swept the rest of `tests/` for the identical daemon-startup-race shape**
   (not the generic `asyncio.sleep` pattern, which has legitimate unrelated
   uses elsewhere) and found the same
   `create_task(daemon.start()); await asyncio.sleep(0.1)` idiom in 4 more
   files, all converted the same way:
   `tests/daemon/test_server_response_schema.py` (2),
   `tests/integration/test_relay_event_socket_real_payloads.py` (1),
   `tests/unit/daemon/test_event_socket_hook_event_name_enrichment.py` (2),
   `tests/daemon/test_server.py` (34), `tests/daemon/test_log_level_override.py`
   (11). `tests/unit/daemon/test_server_liveness_reuse.py` and
   `tests/integration/test_parallel_start_reuse.py` were inspected and left
   alone — both already use a bounded poll or an unrelated background-thread
   loop, not the broken fixed-sleep-then-assert shape. All 132 tests across
   the 6 converted files pass; `magic_values` QA: 0 violations.

3. **10 BLOCKING-release-gate acceptance tests ERROR on a plain run by
   design, not by accident — but the design over-fires.**
   `tests/acceptance/blocking_gate_guard.py` is a session-wide
   `pytest_runtest_makereport` hook: it reads `CLAUDE/development/RELEASING.md`
   Step 12.0's own pytest command line (the SOLE declaration of the blocking
   set — `test_diagnostic_scripts.py`, `test_install_sh_end_to_end.py`,
   `test_tool_use_error_recovery.py`, `test_stop_hook_hard_block.py`,
   `test_skill_install_python_discovery.py`, `test_playbook_harness.py`) and
   turns ANY skip of those files into a hard failure, unconditionally —
   Plan 00250's fix for CI silently reporting a never-run gate as green.
   `.github/workflows/qa.yml` starts a real daemon BEFORE running the whole
   suite, so in CI these tests never skip (they run and pass genuinely) and
   the hook is inert there; RELEASING.md's own Step 12.0 invocation also
   always runs with the daemon already started, so the hook firing there is
   correct — that IS an abort condition. The break is a THIRD case neither
   of those anticipated: any OTHER whole-suite run with no daemon running
   (exactly the ad hoc `pytest tests/ -q` that produced this run) now hard
   ERRORs instead of getting the ordinary, harmless skip every other
   daemon-dependent test in the suite gets. **Fix recipe:** gate the
   skip-to-failure escalation on an explicit signal that THIS invocation
   means to be the release gate, not on file identity alone — e.g. an
   environment variable (`HOOKS_DAEMON_ACCEPTANCE_GATE=1`) that RELEASING.md
   Step 12.0's own command block sets before the `pytest` call, checked
   alongside `skip_is_an_abort_condition(item.path)` in
   `pytest_runtest_makereport`. CI needs no change (the tests never skip
   there, daemon or no signal), and RELEASING.md's own invocation still fails
   closed once it sets the variable — a marker-based `addopts` deselection
   was considered and rejected: it would also deselect these tests from CI's
   OWN full-suite run, which the coordinator's brief explicitly said not to
   weaken.

   **Remedied here, on `main`.** `blocking_gate_guard.py` gained
   `_RELEASE_GATE_ENV_VAR = "HOOKS_DAEMON_RELEASE_GATE"`,
   `release_gate_invocation()` (exact `"1"` match only — a stray truthy
   string set for an unrelated purpose must not silently opt a run in) and
   `should_escalate_skip(test_file)` (`declared_blocking_gate_files()` match
   AND `release_gate_invocation()`, both required — the signal alone is not
   enough, or every skip anywhere would fail). `pytest_runtest_makereport`
   now calls `should_escalate_skip` in place of the old
   `skip_is_an_abort_condition`. `CLAUDE/development/RELEASING.md` Step 12.0's
   command block now sets `HOOKS_DAEMON_RELEASE_GATE=1` before the `pytest`
   call; `.github/workflows/qa.yml`'s daemon-start step now exports the same
   variable via `GITHUB_ENV` so CI's protective behaviour (a daemon that
   silently failed to start there still fails the job) is preserved, not
   weakened. A third caller was found by checking every acceptance-reaching
   entry point named in the coordinator's directive:
   `scripts/qa/run_tests.sh` (the `tests` tool in `llm_qa.py`, `live_daemon=True`)
   calls `ensure_live_daemon` first, but a daemon-start failure there does
   not abort the script — it only prints a message and `run_tests.sh` still
   runs. That script now also exports `HOOKS_DAEMON_RELEASE_GATE=1` before
   invoking pytest, for the identical reason. `run_smoke_test.sh` was checked
   and does not invoke pytest against `tests/acceptance/` at all (a separate
   live-daemon-probe mechanism), so it needed no change. Verified end-to-end
   against a real acceptance file
   (`test_playbook_harness.py`, no daemon running): plain run — 5 skipped,
   exit 0; `HOOKS_DAEMON_RELEASE_GATE=1` — 5 errors naming the file as a
   BLOCKING release gate, exit 1. 6 new unit tests in
   `tests/unit/scripts/test_blocking_gate_guard.py` cover both functions and
   both modes (absent/exact-match/wrong-value for the env var; declared vs
   undeclared file under each).

### N38 — The PreToolUse chain takes quadratic time on a command of quoted heredoc openers

**Found by the Plan 00463 sixth review** (its nit n6), measured on `main` and
on the 463 branch alike (`untracked/scratch/probe_463v6_chain_main_heredoc.py`).
A main-thread Bash command made of repeated `cat <<'E'` openers takes the
whole in-process PreToolUse chain 1.9 s at 16 KiB, 6.8 s at 32 KiB and 51.7 s
at 94 KiB. So the cost roughly quadruples when the size doubles. The verdict
is allow, but at 94 KiB it runs past the client's 30 s budget. Until N25's
fail-closed client lands, that timeout is itself an ALLOW for the whole chain.
After it lands, it is a false deny of a harmless command, and the daemon
keeps burning a worker thread on it either way.

The handler, or handlers, carrying the quadratic heredoc scan has not yet
been identified; profiling is the first step.

**Candidate remedy:** profile the chain per handler on the 94 KiB fixture, and
make each heredoc scan linear. The likely shape is one that re-scans the rest
of the command for each opener. Pin it with a test: the 94 KiB fixture takes
the whole chain under 2 s.

### N37 — `resolve_venv.sh` caches an override's interpreter for later callers that set no override

**Found by the Plan 00376 agent** while closing the upgrade gate's
interpreter bypass. `scripts/lib/resolve_venv.sh` writes
`untracked/.python-cmd-cache` even when the answer came from
`HOOKS_DAEMON_PYTHON` or `HOOKS_DAEMON_VENV_PATH`. A later call that sets
neither override is then served the overridden interpreter from the cache.
So a one-off override sticks, and a caller that deliberately runs without
overrides still inherits one. Layer 2 of the upgrade now works around this
with its own containment check. Every other caller still inherits it.

**Candidate remedy:** never write the cache from an override-derived answer.
Also key the cache on the absence of overrides, or skip it whenever an
override is set. RED test: resolve with `HOOKS_DAEMON_PYTHON=/x`, then with
no override, and the second call must not return `/x`. Being fixed on
`worktree-d-00376`.

### N39 — Nine unit tests fail in a whole-suite run and pass when their files run alone

**Found by the guard-defects agent** (its review-4 fix round): a plain
whole-suite `pytest tests/unit` on this worktree gave 9 failures across
`test_model_fallback_detector.py` (6), `test_absolute_path.py` (1),
`rule_explain/test_lookup.py` (1) and
`test_dangerous_invocation_corpus_checker.py` (1); the same four files run
alone gave 0 failed. **Diagnosed by a parallel agent** (a companion
worktree, full write-up cross-referenced from there): `main` does not
reproduce it; this worktree does. Bisected to
`test_project_containment.py`'s class-wide `_project_root` autouse fixture
(`with patch(...) as mock`) being double-patched by three tests
(`TestFailsClosedOnEvaluationError::test_an_uninitialised_project_root_still_denies`,
`::test_an_evaluation_error_denial_uses_its_own_rule_id`,
`TestChainLevelFailClosedBehaviour::test_an_evaluation_exception_still_denies_through_the_chain`)
that ALSO called `monkeypatch.setattr(..., classmethod(lambda cls: _raise()))` on the exact same target.
`monkeypatch`'s finalizer runs AFTER the fixture's own `with patch(...)`
block has already restored the real classmethod, so the second patcher's
teardown overwrote it AGAIN with the fixture's own stale `MagicMock` --
permanently, for the rest of the pytest PROCESS. Every later test calling
`ProjectContext.project_root()` in that process then inherited the fake
root, explaining all four victim files.

**Fixed** (guard-defects agent, review-5 fix round): the three tests now
reconfigure the fixture's own `mock` (`mock.side_effect = ...`) instead of
introducing a second patcher; the fixture gained a post-teardown tripwire
assertion so any FUTURE double-patch in this file fails immediately, at
the fixture boundary; a regression test
(`TestProjectRootDoublePatchDoesNotLeakAcrossFiles`) runs the exact
polluter/victim pair together in one subprocess pytest invocation and
asserts both pass. RED-pinned by reverting the polluter test alone: the
regression test reproduces the identical original symptom
(`Example: /repo/test.py` leaking into a reason string). ✅ Remedied.

### N36 — `destructive_git` denies a `grep` whose search pattern is the text of a force branch delete

**Found by the Plan 00463 agent** (review-5 fix round, its nit n9). Searching
the tree for the literal force-branch-delete command text (a grep argument,
for example `grep -rn "git branch -D" docs/`) is denied as
R-GIT-BRANCH-FORCE-DELETE. Nothing in the command deletes a branch: the
text is data given to `grep`. It is the same class as N22
(`lsp_enforcement` takes another command's argument for a symbol lookup)
and the N32 pipe split: a guard matches a dangerous shape anywhere in the
command string instead of at a command position.

**Candidate remedy:** judge destructive-git shapes only at a real command
position, using the shared shell lexer from the Plan 00464 shell-parser
consolidation. Treat a quoted argument to a known data consumer (`grep`,
`rg`, `echo`, `printf`, a git `-m` message) as data. RED tests: the grep
above is allowed; `git branch -D x`, `cd r && git branch -D x`, and
`bash -c 'git branch -D x'` are still denied.

### N35 — `daemon_sync_after_merge` judges a `cd <worktree> && git merge` against the session root's ORIG_HEAD

**Found by the Plan 00421 agent.** It ran `cd <worktree> && git merge main`
inside a worktree. The advisory then reported the MAIN checkout's own
`ORIG_HEAD..HEAD` and named `.claude/hooks-daemon.yaml` and project-handlers
as changed. The worktree merge had touched neither.

**Why:** `_is_foreign_repo` and the diff both use the hook payload's cwd,
which is the session root. They ignore the directory the command itself
`cd`s into. This is the same attribution family as N28 (project_containment
ignoring a same-command `cd`) and N33 (which daemon, or which checkout,
a worktree agent's action is judged against).

**Candidate remedy:** resolve the merge's working directory from the
command, using the shell lexer's `cd` tracking from Plan 00464 (the
shell-parser consolidation). Run the ORIG_HEAD diff in THAT repository, and
say nothing when it is a different checkout from the one the daemon
serves. RED test: `cd <other-worktree> && git merge main` emits no advisory
about the session root.

### N33 — a worktree agent's `secret_file_guard.exclude_paths` change had no effect after a daemon restart

**Found by the integration-B2 fix agent.** The agent was writing tests in
`worktree-integration-b2` that must name protected-looking filenames.
R-SECRET-SCRIPT-AUTHOR kept denying the writes. It added the two test files
to `secret_file_guard.options.exclude_paths` in the WORKTREE's
`.claude/hooks-daemon.yaml` and restarted the worktree's daemon. The denials
continued. It worked around it by building the filenames at runtime.

**Why (unverified):** the likeliest cause is that a sub-agent's hook calls
are served by the daemon of the Claude Code session's project root (the
main checkout), not by the worktree's own daemon. If so, a worktree config
change cannot affect that agent's own enforcement until it lands on main.
The docs say "restart the daemon" without saying WHICH daemon enforces a
worktree agent's tool calls, so the agent could not diagnose it.

**Candidate remedy:** first reproduce it and establish which daemon served
the denial (the hook log's project root and socket). Then either make the
deny reason name the config file it was judged against, or document
worktree-agent enforcement in CLAUDE/Worktree.md. Also consider an advisory
when a worktree's handler config differs from the enforcing daemon's.

### N32 — `pipe_blocker` splits at a `\|` inside double quotes and reads the next word as a pipe stage

**Found by the Plan 00463 agent.** The command
`grep -n "a\|--finish\|head-moved\|^#" CLAUDE/QA.md | bin/echd-capture --head 80`
was denied as R-PIPE-TO-HEAD. The only real pipe goes to the whitelisted
`bin/echd-capture`. The `\|` alternations inside the double-quoted grep
pattern were split as pipes, and the "stage" `head-moved` was read as `head`.
Two defects: a quoted `|` is not a pipe, and `head-moved` is not the
command `head`.

**Candidate remedy:** move pipe_blocker onto the shared shell lexer from
Plan 00464 (the shell-parser consolidation), so pipe boundaries come from
real tokenisation. Match a stage's command by whole word. RED tests: the
command above is allowed; `pytest | head -1` is still denied; and
`grep "x|y" f | head` is judged on `grep` (whitelisted), not on `y`.

**Widened (Plan 00463 agent, review-5 n9):** an UNESCAPED `|` inside double
quotes trips it too, not only `\|`. The RED tests must cover both spellings.

### N31 — ✅ Remedied — the dispatch-declaration advisory does not recognise "File to write to: <path>"

**Found by the 00467 dogfood agent.** A dispatch brief that named its report
path as `File to write to: <path>` still drew the Plan 00307
dispatch-declaration advisory saying no report destination was declared.
The advisory matches a narrower set of phrasings than briefs actually use,
so it nags on a correct dispatch, and a nag that is often wrong teaches
people to skim it.

**Candidate remedy:** recognise any phrasing that pairs a write verb or noun
("write", "report", "file", "output", "save") with a path in the brief, not
only fixed phrases. RED tests: the phrasing above is recognised, and a brief
with no path at all still draws the advisory.

**Remedy:** `dispatch_declaration.py`'s destination check no longer requires
a fixed "verb + to/in/under/into + path" grammar. `_prompt_declares_destination`
now pairs any destination KEYWORD ("write"/"save"/"report"/"output"/"store",
now including the noun "file") with a path-shaped token in the SAME CLAUSE
(split on sentence-ending punctuation or a newline) — a keyword match that
falls INSIDE the path token itself (e.g. "file"/"report" as hyphen-bounded
substrings of a plan-folder name like `...-file-based-report-handoff`) is
excluded, which is what keeps the Plan 00460 review finding m4 distinction
intact (a bare plan-folder mention in one sentence, with the actual verb in
the next, still does not count). Five new RED-then-GREEN tests in
`TestDestinationPhrasingRecognition`
(`tests/unit/handlers/pre_tool_use/test_dispatch_declaration.py`) cover the
exact reported phrasing, two other natural phrasings ("save ... at ...", a
bare "<label>: <path>"), a keyword-with-no-path prompt (still advises), and
the m4 clause-boundary regression guard.

### N30 — ✅ Remedied — more shell code that must survive a hostile PATH depends on a PATH command

**Found by the 00467 dogfood agent**, applying the Defence Before Fix method
to the watchdog defect fixed at 766677c1 (00466 N1's follow-up). An
independent search for the same class ("shell code that must survive a
hostile or stripped `PATH` runs a command looked up on `PATH`, and its
absence silently takes a wrong branch") found four more candidates:

- `scripts/venv_bootstrap.sh:443` and `:474` (`date`). The agent reproduced
  this idiom.
- `scripts/install/venv.sh:427` (`date`).
- `scripts/install/daemon_control.sh:40-43` (`pgrep`).

These are the venv and install paths, which exist to work when the host's
tools are broken, exactly as `resolve_venv.sh` does.

**Candidate remedy:**

1. Fix each instance: use a bash builtin (`printf '%(...)T'` for dates,
   `/proc` or `kill -0` for process checks). Where there is no builtin,
   make the missing command a loud, explicit failure rather than a silent
   wrong branch.
2. The detector the method asks for: a check over the scripts that must
   survive a hostile PATH (`resolve_venv.sh`, `venv_bootstrap.sh`,
   `scripts/install/*.sh`, the `bin/` wrappers) that flags an external
   command whose failure is not handled. It could be a `shell_audit` rule, or
   a test that runs each such script's functions under an empty `PATH`. It
   must catch the original watchdog shape, verified by reverting 766677c1 in
   a scratch copy.

**Remedy:** a new shared library, `scripts/lib/portable_time.sh`
(`_hp_epoch_seconds`, `_hp_timestamp <fmt> [--utc]`), gives every hostile-PATH
script a PATH-lookup-free way to get the time: bash's own `printf '%(...)T'`
builtin (>= 4.2) first, `date` on PATH second (the bash-3.2/macOS fallback,
since that builtin needs 4.2+), a loud stderr diagnostic + non-zero return
last — never a silently-empty/zero value feeding a decision. All five
`venv_bootstrap.sh` call sites, `venv.sh`'s `_venv_detached_build_wait`, and
three more instances the sweep (below) found in `config_preserve.sh`,
`rollback.sh` (x2) and `settings_deploy.sh` now go through it, each restructured
so a failure is either an explicit loud abort (`set -e` on a standalone
assignment, or an explicit `state=error`/`print_error` + `return 1`) or a
documented graceful fallback (`_venv_detached_build_wait` returning 1, which
its caller already treats as "use the generic wait bound") — never a garbled
or wrongly-branching value. `daemon_control.sh`'s `_daemon_process_exists`
gained a `/proc/*/cmdline` fallback (pure bash glob + `read -d ''`, no
external command) for when `pgrep` is unreachable, and when NEITHER is
available it says so loudly and answers "maybe" (assumes the daemon might be
running) rather than silently "no" — the caller only uses the answer to
decide whether to retry a status poll a little longer, so a false positive
costs a few seconds and a false negative costs a failed restart report.
`bin/hooks-daemon` and `bin/echd-capture` were reviewed and found not to need
this: the wrapper's PATH-dependent lookups are all standalone assignments
under `set -euo pipefail`, which already abort loudly, and the capture
helper's `date` use already has an explicit `|| echo 0` fallback for a
non-decision-affecting filename-uniqueness suffix.

The detector has both halves DBF asks for. Dynamic (primary): empty/narrowed-PATH
integration tests exercise every fixed call site directly —
`tests/integration/test_venv_bootstrap_hostile_path_epoch.py` (9 tests, all
five `venv_bootstrap.sh` sites), `test_venv_lock_wait_hostile_path.py` (3
tests), `test_daemon_control_pgrep_portability.py` (+3 new hostile-PATH
tests, using a FIXTURE `/proc` via the test-only `_HP_PROC_DIR` seam rather
than the host's real `/proc`, which could already hold an unrelated real
daemon process in this shared container). Static (complement, not the only
guard): `audit_shell.py` gained a `hostile-path-unguarded-command` rule,
scoped to the declared file list, flagging `date`/`pgrep` used without a
file-wide `command -v` guard — it does not judge control flow, just "the
fallback is still there". `test_hostile_path_detector_proof.py` is the DBF
step-3 proof: a scratch copy of `resolve_venv.sh` with 766677c1's fix
literally reverted (`_rv_wait_secs` swapped back for the bare `( sleep ...; kill -KILL ... ) &` list) reproducibly fails under a `sleep`-less PATH
(RED), while the real, current file passes the same scenario (GREEN) — using
a candidate that takes ~2 real seconds via a pure-bash `$SECONDS` busy-wait
(no external `sleep`/`date` needed in the fixture itself) so the proof is
not a timing race.

The sweep found and fixed 3 more instances beyond the 4 named in this
niggle's candidate remedy (all `date`, all `scripts/install/*.sh` siblings
of `daemon_control.sh`, sourced only from the same interactive
`install_version.sh`/`upgrade_version.sh` entry points as `daemon_control.sh`
itself — so architecturally the same class, not scope creep): a backup
timestamp in `config_preserve.sh`, a snapshot ID + manifest timestamp in
`rollback.sh`, and a backup timestamp in `settings_deploy.sh`. Total
instance count: 7 (4 named + 3 swept), all fixed.

### N29 — ✅ Remedied — `error_hiding`'s return-None-in-except check is evaded by returning a local assigned in the handler

**Found by the coordinator** reading the goal-flip agent's report. To clear the
`error_hiding` finding on a literal `return None` inside an `except` handler,
that agent assigned `None` to a local in the handler and returned the local
after the `try`. The behaviour is identical, and the detector no longer sees
it. So the check keys on syntax, not on the flow it exists to catch, and an
agent under QA pressure finds the gap on the first try. The goal-flip branch
has been told to undo the evasion and fix the code honestly.

**Candidate remedy:** judge the flow, not the token. An `except` handler that
binds a name read by a later `return`, where that name's only values are
`None` or a default and the handler logs or re-raises nothing, is the same
finding as a literal `return None`. RED tests: the evasion shape is flagged,
a handler that logs at warning or above and returns a documented sentinel is
not, and the literal form is still flagged. Then sweep the tree for existing
instances of the evasion shape, which would currently pass unseen.

**Remedied on the d-fresh branch** (`worktree-d-fresh`). `audit_error_hiding.py`
has a new rule, `return-none-via-local`. It flags an `except` handler that binds
`None` or an empty default (`[]`, `{}`, `()`, `""`, `list()`, ...) to a local
when the function returns that local after the `try`, or returns `None` under
`if local is None:` / `if not local:`, with no real rebinding in between. It
does not flag a handler that re-raises or logs at warning or above. A named
sentinel constant is not this finding. The rule has its own id, so none of the
existing `return-none-on-error` exclusions can cover it. The literal check is
unchanged, and it now runs on `async def` too, which it silently skipped
before. Tests: `TestReturnNoneThroughALocal` in
`tests/unit/qa/test_audit_error_hiding.py`.

The flow now also follows these variants, each pinned by a RED-first test:

- a tuple-unpacked binding (`value, extra = None, []`);
- a binding under a condition inside the handler;
- an augmented assignment after the `try` (`rows += more`), which builds on
  the fallback and so does not clear it;
- a return in the `try`'s own `finally:`, later in the same handler, or in an
  enclosing `try`'s `else:`.

The same `try`'s `else:` is not flagged, because it never runs after a
handler. Appending to a list counts as surfacing only when the function
returns that list, raises it, or passes it to a logging call at warning or
above, `print`, `sys.stderr.write`, or a callee named for reporting
(`report`, `render`, `emit`). A caller-owned list does not count. The re-sweep
found no new instance. It also fixed an `IndexError` that ended the whole
audit on a single-part relative path such as `install.py`.

The sweep found 8 sites, and each was fixed with no exclusion. Two fixes
removed now-stale `silent-fallback` exclusions:
`sensitive_content._compiled_public_pattern` and
`flaggable_content_channel_guard._compiled_shape_pattern`. A guard regex
that does not compile now logs at WARNING once, naming the pattern.
`secret_redaction._resolve_active_path` logs an unreadable config at WARNING
(INERT), the same as a config that fails validation. `staged_lint_gate` says
at WARNING that a file was NOT checked when its lint tool cannot run.
`auto_continue_stop._parse_iso_timestamp` logs an unparseable transcript
timestamp at WARNING. `merge_to_main_approval` handles the unbalanced-quote
`ValueError` by running the next tokenising strategy inside the handler.
`server._handle_event_client` (the async literal) moves the success path into
`else:`. In `cli._qa_run_lock_holder`, a comment described the evasion as
deliberate. The site also hid a bug: a held lock with an unreadable pid was
reported as "nothing holds it", which dropped the restart warning. It now
reports `"unknown"`, and "cannot tell" is logged at WARNING.

### N28 — `project_containment` resolves a relative target against the payload cwd and ignores a same-command `cd`

**Found by the Plan 00464 agent** during its re-review fix round (S12). It is
an instance of 00464's own defect class: the payload `cwd` is where the
session started, not where the command runs. So `cd <elsewhere> && <write to a relative path>` was judged against the wrong directory, and the containment
verdict could be wrong in both directions.

**Remedied on the 00464 branch** (`worktree-plan-464-commit-gate-repo`,
827c45df) through the new `find_command_placements`, which every
path-judging guard is meant to share. Two sibling walkers still resolve
their own way: `reference_repo_freshness` (the 00464 agent fixes it on that
branch) and `secret_file_matching` (after the guard-defects branch merges,
in the shell-parser consolidation). Mark Remedied when 00464 lands; the
siblings are tracked in the coordinator's consolidation work.

### N27 — ✅ Remedied — `skill_scan` and `tool_report` build the transcript directory name two different ways

**Found by the 00468 core agent** (report on its branch,
`subagent-reports/260924-p468-core-opus-5-5.md`). Claude Code keeps a
project's transcripts under a directory named after the project path, with
characters it cannot use in a name replaced. `skill_scan` and `tool_report`
each derive that name with their own code, and they disagree for a path
containing `.` or `_`. So for such a project one of them reads the wrong
directory, finds nothing, and reports "no data" rather than an error.

**Candidate remedy:** one helper derives the transcript directory from the
project path, pinned to Claude Code's real rule (checked against a real
`~/.claude/projects/` entry for a path with `.`, `_` and `-`). Both commands
and every other derivation site use it (sweep for the other derivations).
The helper raises, not returns empty, when the directory does not exist and
the caller asked for it. RED test: a project path with `.` and `_` resolves
to the same directory from both commands.

**Remedy** (branch `worktree-p468-core`): Claude Code's real rule was read
from its shipped bundle. The per-project directory is
`join(<config dir>, "projects", uC(realpath(cwd)))`. `uC` replaces each UTF-16
code unit outside `[a-zA-Z0-9]` with `-`, and a name over 200 characters is
cut to 200 and suffixed with `-` plus the base-36 absolute value of a 32-bit
Java-style string hash. No real `projects/` entry for a path with `.` or `_`
exists in this container (only `-workspace`). So the expected values in the
tests were computed by running that JavaScript under node.

- `utils/claude_config.project_dir_name()` and `claude_project_dir(project_root, *, config_dir=None, must_exist=False)`
  implement it. `must_exist` raises `FileNotFoundError` naming the directory.
- Every derivation site delegates: `skill_scan.extraction.derive_transcript_dir`,
  `tool_report.analyser.transcripts_root_for` (which `block_report` re-exports),
  and the `cache-gaps` auto-discovery.
- `cache-gaps` names the directory it looked in. `tool-report` and
  `block-report` name a missing derived directory on stderr.
- Tests: `tests/unit/utils/test_transcript_dir_derivations_agree.py` (RED:
  skill_scan named the wrong directory), `TestProjectDirName`,
  `TestClaudeProjectDir`, and a
  `test_a_missing_derived_directory_is_named_on_stderr` test in both cli
  report test files. Release note 39.

### N26 — ✅ Remedied — `check_skill_references.py` scans zero files when run from a worktree

**Found by the 00468 core agent.** Run from any worktree, the skill
references QA check reports success after scanning 0 files. A check that
examines nothing and passes is a fail-open gate: every sub-agent's targeted
QA runs from a worktree, so the check has been silently vacuous exactly
where branches are verified.

**Candidate remedy:** find why the file discovery comes up empty in a
worktree (a `.git` file rather than a directory, or a path anchored to the
main checkout), and fix it. Separately, the check FAILS when it scans zero
files where skills exist, so a vacuous pass cannot recur. Audit the other
`scripts/qa/check_*.py` for the same "0 examined, PASS" shape and pin the
class with a test that runs each check from a worktree fixture.

**The cause, and two more instances (integration B2).** Each checker drops a
file whose path contains a noise-directory name such as `untracked` or
`worktrees`, and it tests the ABSOLUTE path. Every agent checkout lives at
`untracked/worktrees/<name>/`, so every file matches:

- `check_doc_truth.py` `_iter_markdown`: 0 docs scanned in every worktree.
  **Fixed on the B2 branch** (08c4be0e): it tests the path below `--root`.
  1785 docs scanned after, 0 violations. The test is
  `test_a_checkout_inside_a_worktrees_directory_is_still_scanned`.
- `audit_shell.py` `_is_excluded`: it keeps 0 of the worktree's `.sh` files, so
  `shell_audit` passes vacuously. Not fixed. B2 ran it by hand over the
  relative `scripts/` and skill-scripts directories: 52 files, no violations.
- `check_skill_references.py` (this entry): `_EXCLUDED_DIRS` holds both names
  and is tested against `path.parts`, so it is very likely the same cause.
  `check_github_urls.py` tests `path.parts` the same way and should be checked.

**Remedy** (branch `worktree-p468-core`):

- **Cause.** Not the `.git` file: `_should_exclude` matched `_EXCLUDED_DIRS`
  against the ABSOLUTE path's parts. `untracked` and `worktrees` are
  excluded names, and every worktree lives under `untracked/worktrees/`.

- **Audit.** All 22 `check_*.py` were audited. Two more had the same shape:
  `check_doc_truth.py` (0 docs from a worktree) and `check_github_urls.py`
  (0 files). `check_magic_values.py` matched `constants`, `fixtures` and
  `test` the same way, which is latent here and live for a checkout under
  such a directory. Only `check_project_handler_tests.py` had a zero guard.

- **Fix.** New `utils/scan_scope.py`:

  - `relative_parts(path, root)` gives the components below the scan root;
  - `vacuous_scan_failure(examined=, candidates=, noun=)` turns "examined 0 of
    N" into a failure.

  The four checks use both. From this worktree they now scan 699 (skill
  refs), 1,774 (doc truth), 4,038 (GitHub URLs) and 1,763 (magic values)
  files, with no new violations.

- **Class pin.** `tests/integration/test_qa_walkers_examine_files_from_any_checkout.py`
  copies the tracked tree under a path made of every excluded name
  (`test/fixtures/constants/build/examples/Completed/venv/ccy/untracked/worktrees/wt`).
  It runs each of the 14 tree-walking checks there and requires a non-zero
  examined count. RED: 4 failed (skill refs, doc truth, GitHub URLs, magic
  values). A second test requires every `check_*.py` to be listed as a
  walker or a fixed-input check, so a new check cannot skip the pin.

- **Existing tests.** The exclusion tests that asserted `passed` over a tree
  holding only the excluded file (the vacuous shape itself) now scan a clean
  companion file and assert the examined count. Release note 40.

The other 10 walkers are worktree-safe, and are pinned by the integration
test rather than given their own zero guard.

- **`audit_*.py` too.** The first audit globbed only `check_*.py`, so it
  missed `audit_shell.py`, which had the same absolute-path exclusion
  (`untracked`) and passed on 0 scripts from a worktree (the B2 integration
  found it too). It now uses `relative_parts`, reports `files_scanned`
  (62 from this worktree) and fails on examining 0 of N scripts. The pin
  classifies `audit_*.py` as well. `audit_error_hiding.py` and
  `audit_capture_corruption.py` were already relative, and already exit 1
  when they collect nothing (Plan 00364 Task 5.4). They are pinned by
  requiring their artefact from the hostile location.

- **Reconciled with B2.** B2's doc_truth fix (08c4be0e) and its git-visible
  and protected-path filter (fd6c5438) are kept. The noise-name test in
  `_iter_markdown` now goes through `scan_scope.relative_parts`, the one
  mechanism. B2's `test_a_checkout_inside_a_worktrees_directory_is_still_scanned`
  is kept. There was no duplicate helper to delete: B2 had used an inline
  `relative_to`. B2's new `check_unreachable_handle_branch.py` is classified in
  the pin as a counted walker.

- **The missing-root variant.** A walker could also examine 0 of 0, and pass,
  when its scan root was absent or empty. `check_unreachable_handle_branch`
  was the first one found. `vacuous_scan_failure` now fails on 0 examined in
  every case, and names the root as missing or empty. Every walker applies it
  now:

  - the five that already used it get the stricter rule;
  - it is added to `check_authored_path_stat`, `check_british_english`,
    `check_doc_snippets`, `check_eacces_safe_predicates`,
    `check_python_var_guidance`, `check_repo_hygiene`,
    `check_security_downgrade_flags`, `check_sensitive_content`,
    `check_skip_list_substring` and `check_unreachable_handle_branch`;
  - `check_git_history` fails on a `--repo` that is not a git repository. It
    no longer passes as "inert". 0 commits in a real repository still passes:
    a baseline at HEAD leaves nothing new to sweep.
  - `check_python_var_guidance` also fails when one of its declared default
    roots or files is gone, rather than skipping it.

  Pins in the same integration test:

  - every walker, run from a checkout that holds only `scripts/qa/` minus its
    shell scripts, fails or examines something. RED: 6 walkers passed on 0.
  - every walker pointed at a missing root, and at an empty one, through its
    own root option, exits non-zero. RED: 3 more (`check_git_history`,
    `check_python_var_guidance`, `check_sensitive_content`), then
    `check_repo_hygiene` on an empty git repository.
  - `ROOT_OPTIONS` must name every walker's root option except
    `check_magic_values`, which has none (the gutted checkout covers it), and
    `audit_error_hiding`.

  Tests that asserted a pass over a tree with nothing to scan now add a clean
  scanned file, or assert the failure. Release note 40.

- **`.git` and nested checkouts.** In `--path` mode, `check_sensitive_content`
  walked the tree with a raw `rglob("*")`. That read `.git` internals (commit
  messages, hook samples) and nested repositories as the tree's own files.
  `git ls-files` lists neither in the default mode. Sixteen walkers had the
  same raw recursive walk (`rglob`, or a `**/` glob in `check_doc_snippets`).

  - **Fix.** New `scan_scope.walk_files(root, pattern)` never enters `.git`, and
    it skips any directory below the root that holds a `.git` entry (a
    worktree, submodule or clone). Every walker now enumerates through it.
    `audit_capture_corruption` runs under a bare `python3`, so it loads the
    stdlib-only module by file path. A test pins that `scan_scope` imports only
    the standard library.
  - **RED.** A `--path` tree reported a planted term from `.git/COMMIT_EDITMSG`,
    from a nested repository and from a linked worktree. Only `real.txt` is
    reported now. The pin
    `test_a_walker_enumerates_through_the_shared_walk` failed for all 16
    walkers. Examined counts on this repository are unchanged.

### N25 — ✅ Remedied — a slow handler runs out the client's 30 s budget, and a timeout is an ALLOW for the whole PreToolUse chain

**Found by the guard-defects security review 2**
([report](subagent-reports/260924-n466-guards-review2-opus-5-5.md), B1 and
m3). `.claude/hooks/pre-tool-use` gives the daemon `--timeout-ms 30000`. On a
read-side socket timeout, `.claude/init.sh` (about lines 1654-1661) emits
`hookSpecificOutput` with context only, which is an ALLOW for every non-Stop
event. So any handler that can be made slow enough bypasses every guard
behind it, not just itself. Two instances are measured:

- `destructive_git`'s `strip_inert_spans` takes 99 s on a 200 KB command.
  That is already on main.
- The guard-defects branch's interior-wildcard DP takes 31 s on a crafted
  60 KB command. That one is fixed on its branch as review 2's B1.

Fixing each slow handler one by one leaves the class open: the next
super-linear regex or DP reopens it silently.

**Candidate remedies (the class, not the instance):**

1. The daemon enforces a per-event deadline well under the client budget
   (for example 20 s for the whole chain). When it passes, the remaining
   SAFETY+BLOCKING handlers are treated as having raised, which means DENY
   with a "not judged in time" reason under N24's fail-closed rule.
   Advisory handlers are skipped with a note.
2. Fix the measured instance: `strip_inert_spans` becomes linear, with a
   timing test at 200 KB.
3. A test harness drives every SAFETY handler with large hostile inputs
   (long runs of quotes, backslashes, wildcards and nesting) under a time
   bound, so a super-linear path fails CI rather than a client.

Deliberately NOT a remedy: making the client fail closed on timeout. A
daemon that is merely slow (an overloaded host) would then block every tool
call. The deadline belongs inside the daemon, where it can tell safety
handlers from advisories.

**✅ Remedied.** All three candidate remedies landed, on the same branch as
N24 (which this depends on for its fail-closed wording):

1. `ChainConfig.deadline_seconds` (`config/models.py`) is a new config key,
   default `Timeout.CHAIN_DEADLINE_DEFAULT = 20` (seconds), threaded through
   `DaemonController.initialise()` -> `process_event()` ->
   `EventRouter.route()` -> `HandlerChain.execute()` the same narrow-slice DI
   idiom N24 used for `strict_mode`. Inside `execute()`'s per-handler loop, a
   deadline check runs before each handler: once exceeded, every remaining
   SAFETY+BLOCKING handler is denied under N24's fail-closed rule with a "not
   judged in time" reason naming the handler; every other remaining handler
   is skipped with an advisory note instead of running. `deadline_seconds: None` disables enforcement entirely. Unit coverage: `test_chain.py`,
   `test_router.py`, `test_chain_config.py`, `test_controller.py` (deadline
   reaches the router end-to-end).
2. `strip_inert_spans` (via `shell_segmentation.py`) is now linear. The root
   cause was the same shape in three places: `strip_message_bodies`'s
   segment/binary/subcommand resolution and `strip_quoted_heredoc_bodies`'s
   substitution-depth and receiving-segment lookups all re-derived
   prefix-dependent state from scratch (`command[:match_start]`) for every
   regex match, instead of advancing incrementally in the guaranteed
   left-to-right match order. Replaced with three stateful trackers
   (`_SegmentTracker`, `_SubstitutionDepthTracker`, `_LastNewlineTracker`)
   that each bound their per-match cost to the gap since the previous query.
   Reproduced review 2's exact repros directly: the 40000-`-m`-flag case
   (99.179s on main) now runs in 0.139s; the 5000-heredoc case (98.342s on
   main) now runs in 0.453s. Timing tests pinned at 200 KB in
   `tests/unit/utils/test_shell_segmentation_performance.py`; full
   `destructive_git`/`curl_pipe_shell`/`shell_segmentation` regression stays
   green.
3. `tests/unit/handlers/test_safety_handlers_hostile_input_performance.py`
   drives every `HandlerTag.SAFETY` `pre_tool_use` handler (23 of them,
   discovered via `iter_builtin_handler_classes()`, never a hardcoded list)
   with four hostile shapes — many small quoted/backslashed/wildcarded
   tokens (the shape that actually caused #2's bug: many MATCHES, not one
   giant token) and deep `$(...)` nesting — against both a `Bash` command
   payload and a `Write` file-content payload, each under a 5s bound at
   100 KB. Found no other super-linear handler. One handler,
   `SecretFileGuardHandler`, is markedly slower than its peers (~1.3s at
   100 KB vs \<0.25s for everything else) but measured LINEAR up to 800 KB
   (doubling input doubles time) — a high constant factor, not a
   superlinearity bug, so it is noted here rather than "fixed": worth a
   follow-up look if it ever becomes a real bottleneck, but out of this
   niggle's scope (which is specifically superlinear paths).

**Harness extended (guard-defects review 3 follow-up).** Review 3 found a
DIFFERENT class from the 100 KB-scale shapes above: COMBINATORIAL blowup on
a SHORT input — `echo {a,b}` x20 (110 bytes) took 36s on a guard whose bug
lives on the `guard-defects`/`463` branches, not this one.
`TestCombinatorialSmallInputShapesStayLinear` (same file) adds brace
expansion (x16/x20/x24), nested braces, `/**/` and `**/*` globs, bracket
classes, and deep `eval`/`bash -c` nesting, all under 300 bytes, applied to
both a `Bash` command and a `Write` `file_path`. It also sweeps this
repository's own `.claude/project-handlers/` (`enforce_llm_qa` included)
best-effort, via the same `ProjectHandlerLoader` the daemon uses — 28
handlers swept in total. Clean on this branch (27/27 pass, ~7s): expected,
since the vulnerable code these shapes target is not present here yet — the
harness is the "class detector" the guard-defects/463 branches fix against,
not a fix itself. Measuring `secret_file_guard`'s margin against the 20s
deadline at 1 MB/4 MB (requested alongside this) surfaced a related but
DISTINCT gap, filed separately as N34: the deadline check in `chain.py`
only runs BETWEEN handlers, so one handler slow enough within its OWN
execution is not covered at all.

### N24 — ✅ Remedied — `daemon.strict_mode` never reaches the live daemon, so every guard fails OPEN on a handler exception

**Found by the guard-defects security review 2**
([report](subagent-reports/260924-n466-guards-review2-opus-5-5.md), M3), with a
live probe against this repository's own daemon. `.claude/hooks-daemon.yaml`
sets `strict_mode: true`. A Write payload that makes a handler raise
(`ValueError: no path specified`, the still-live N5 shape) came back as
`additionalContext: "Handler exception: ..."`: an ALLOW, not the strict-mode
`SYSTEM ERROR ... blocking for safety` deny.

`daemon/controller.py:959` reads `self._config.strict_mode if self._config else False`. The constructor's own comment (`:162-166`) says the `config`
parameter "is not populated by the real daemon startup path", and
`get_controller()` (`:1210`) builds `DaemonController()` with no config. So
`strict_mode` is inert in every install. Every SAFETY guard treats its own
crash as "no match". The per-guard wrapper that N11 adds to `secret_file_guard`
is the only thing between a crash and a bypass, and no other guard has one.
The N5 and N11 entries' claim that "this repository runs `strict_mode: true`,
so here the crash denied" is false.

**Candidate remedy (both halves):**

1. Plumb `config.daemon.strict_mode` into the controller's real startup path,
   through the same narrow-slice injection already used for `ChainConfig`.
   Test it through `get_controller()` and a real daemon start, not by
   constructing the controller with a config the daemon never passes.
2. Independently of `strict_mode`, the chain denies when a handler tagged
   SAFETY and BLOCKING raises, because a safety guard that crashes has not
   judged the call. That closes the class for every guard at once, including
   the review's m1 (`handle()` outside the fail-closed wrapper).

RED tests: a live-path daemon with `strict_mode: true` denies on a raising
handler; a SAFETY+BLOCKING handler that raises denies even with `strict_mode`
off; a non-safety advisory handler that raises still allows, and says so.

**✅ Remedied.** Both halves landed:

1. `DaemonController` gained a narrow-slice `_strict_mode` (Plan 00466 N24),
   the same DI idiom `_chain_config`/`_verdict_log_config` already use:
   `initialise(strict_mode=...)` sets it, `process_event` reads
   `self._strict_mode` instead of the never-populated `self._config`.
   `_build_initialised_controller` (`daemon/cli.py`) threads
   `config.daemon.strict_mode` through, so the real startup path (`cmd_start`
   → `_build_initialised_controller` → `initialise()`) now actually carries
   it. Unit coverage: `tests/unit/daemon/test_cli_strict_mode_wiring.py`
   (the `_build_initialised_controller` DI slice) and
   `tests/unit/daemon/test_controller.py` (through `get_controller()` +
   `initialise(strict_mode=...)`, both True and False).
2. `HandlerChain.execute` (`core/chain.py`) now denies unconditionally, on
   any raise from `matches()` or `handle()`, when the handler carries both
   `HandlerTag.SAFETY` and `HandlerTag.BLOCKING` — independent of
   `strict_mode`. The reason names the handler and the underlying exception
   ("evaluation error, denied for safety"), distinct from the strict-mode
   "SYSTEM ERROR" wording so a verdict log can tell the two paths apart.
   Non-safety/advisory handlers keep the pre-existing fail-open behaviour.
   Unit coverage: `tests/unit/core/test_chain.py` (5 new cases: raise in
   `handle()`, raise in `matches()`, the SAFETY-without-BLOCKING negative
   control, the non-safety negative control, and strict_mode's own wording
   still winning when both apply).

Also added an acceptance-level, live-daemon check
(`tests/integration/test_n24_strict_mode_probe_isolated_daemon.py`) that
proves the wiring end-to-end against a real daemon process, without
depending on N5's lifecycle: a probe handler raises ONLY for a payload
marked `synthetic_source: n24-probe`, which no real Claude Code session ever
sends. It started as a permanent file under this repository's own
`.claude/project-handlers/` plus a socket test against the already-running
shared daemon; both are now gone, superseded by this file, which starts its
own isolated daemon (the same pattern `test_daemon_smoke.py` uses) in a tmp
project and writes the probe's source into that tmp project's own
`.claude/project-handlers/` before starting it — a probe this narrow has no
business permanently installed in a maintainer-visible directory meant for
genuinely useful project handlers.

**NUL-byte realpath sweep (guard-defects review 2, m3, follow-up).** The
fuzzer found `sensitive_content` raising `ValueError: embedded null byte`
from a `realpath` call on 485/12000 fuzzed Write/Edit paths. With N24's
Part 2 fix this had already stopped being a silent bypass (it denies as
"evaluation error, denied for safety"), but that is the generic
chain-level catch-all, not a clear handler-specific reason — so the raise
itself is still a defect worth fixing at its source, four places:

1. `core/workspace.py`'s `ProjectRegistry.for_path`/`layout_for` both called
   `file_path.resolve()` unguarded — the shared root cause behind THREE
   handlers, since it is reached via the `Handler.layout_for()` base method:
   `error_hiding_blocker`, `security_antipattern` and `secret_file_guard`
   (via `_is_excluded`), plus `sensitive_content` itself. A new
   `_resolve_or_self` helper catches `(OSError, ValueError)` and falls back
   to the unresolved path, which safely fails to match any real declared
   project and so falls through to the same root-project/root-layout answer
   an ordinary undeclared path already gets — never a crash, matching both
   methods' own "never returns None" contract. Unit coverage:
   `tests/unit/core/test_project_registry.py::TestAnUnresolvableFilePathDoesNotRaise`.
2. `secret_file_guard`'s OWN separate raise: `utils/secret_file_matching.py`'s
   `path_is_protected` calls `os.path.realpath` and only caught `OSError`,
   not `ValueError`. Widened to `(OSError, ValueError)` — a NUL-bearing path
   cannot BE a symlink to anything, so there is nothing for the realpath
   check to discover; the raw-path glob match (which already ran first)
   still stands. Unit coverage:
   `tests/unit/utils/test_secret_file_matching.py::TestPathIsProtected::test_nul_byte_in_path_does_not_raise`.
3. `issue_filing_gate`'s `_read` calls `path.stat()` on a `gh --body-file`
   path and only caught `OSError`, not `ValueError`. Widened the same way —
   still just "could not be read", the existing refusal-not-pass verdict.
   Unit coverage:
   `tests/unit/handlers/pre_tool_use/test_issue_filing_gate.py::TestABodyItDidNot::test_a_nul_byte_in_the_body_file_path_is_denied_not_raised`.
4. `project_containment` was ALREADY safe: its `_is_within` wraps
   `Path(candidate).resolve().relative_to(container)` in a single
   `except ValueError:`, which already catches `.resolve()`'s NUL-byte raise
   the same way it catches `.relative_to()`'s mismatch — no fix needed.

`sensitive_content` itself gets a DIFFERENT, deliberate treatment beyond
just "does not crash": a NUL byte can never appear in a real filesystem
path, so a Write/Edit `file_path` carrying one is now denied OUTRIGHT with
a clear, handler-specific reason ("file_path contains an embedded NUL
byte...") — this is a classic path-truncation attack shape, and letting the
now-safe fallback silently continue to "not excluded, not the secret list,
scan whatever haystacks come back" would have been the wrong verdict even
though it would no longer crash. Checked via `matches()` before any haystack
computation runs, both `Write` and `Edit`. Unit coverage:
`tests/unit/handlers/pre_tool_use/test_sensitive_content.py::TestNulByteFilePathIsDenied`.

Swept every `HandlerTag.SAFETY` `pre_tool_use` handler (23, the same
dynamic discovery as N25 Task 3) with NUL-bearing Write/Edit/Bash payloads
after all four fixes: none raise.

The N5 and N11 entries' "this repository runs `strict_mode: true`, so here
the crash denied" claim is corrected below, in place, rather than restated
here.

**Review 2's pre-existing observations** (the N24/N40 review 2 report, P1 and
P2), taken into scope by the coordinator:

- **P2, degraded mode switches guards off.** An invalid config sends the
  daemon DEGRADED, and that mode then ALLOWS `curl | bash` and skips project
  SAFETY handlers. This is the same root cause as N43: a degraded daemon
  resolves nothing through the config it could not load. It is NOT fixed on
  this branch, because Plan 00421's branch `worktree-d-00421` already fixes
  both. It adds `daemon/degraded_mode.py`, which runs every SAFETY or
  BLOCKING built-in and project handler at its defaults, widened by the
  last-known-good snapshot and HEAD's config. A `FailClosedGuard` stands in
  for any guard that cannot be built. It also tags `curl_pipe_shell` SAFETY,
  and redacts with `use_degraded_word_lists` (N43). A second mechanism here
  would duplicate that one and conflict with it in `controller.py`.
- **P2, nested layout.** The fix is on this branch. `get_project_path`
  walked past a project whose own config failed to load, so the daemon ran
  on the ENCLOSING repository's config and reported that file's unrelated
  error. A directory whose `.claude/` holds `hooks-daemon.yaml` is now the
  project root, valid or not, and a broken config there exits with its own
  error. `load_transport_config` also stopped searching upward. Tests:
  `TestGetProjectPath` in `tests/unit/daemon/test_cli_commands.py`, and
  `test_load_transport_config_never_reads_an_enclosing_projects_config`.
- **P1, silently skipped per-event socket.** The server records each skipped
  event (path length, bind, chmod, a symlinked events dir) with its reason.
  `health` goes degraded with the `event_sockets` reason and lists
  `event_socket_skips`, and `status` and `check` name each event. The events
  dir already falls back to a short directory. Test:
  `TestSkippedSocketsReachHealth` in `test_event_socket_listeners.py`.
- **`CLAUDE_HOOKS_SOCKET_TIMEOUT` below the deadline.** A PreToolUse socket
  timeout still denies. The deny reason, its context and the stderr line now
  name the variable and its value, and say it is shorter than the chain
  deadline. `init.sh` carries a pinned copy of `Timeout.CHAIN_DEADLINE_DEFAULT`,
  so the comparison is against the default. A project that configures a
  different deadline is not seen by the client.

### N23 — `recovery_cron_advisor` hands one request's lifecycle phase to another, through the singleton

**Found by Plan 00449's agent** while fixing the eviction race in the same handler. `matches()` stores the detected phase on the handler (`self._cached_phase`) and `handle()` consumes it. The handler is a daemon-lifetime singleton and `server.py` dispatches on a thread pool, so request B's `matches()` can overwrite the value between request A's `matches()` and `handle()`. A then advises on B's phase (CREATION guidance for a PROGRESS edit, say), and B finds the cache already cleared and detects again. It raises nothing, so no test or log shows it. This is a different class from Plan 00449's select-then-evict: per-call state parked on a shared object between two calls. It is out of that plan's scope by its own Non-Goals ("no audit of every mutable handler attribute").

**Candidate remedy:** stop caching on the instance (detect in `handle()`, or key the cache by thread with `threading.local`), with a RED test that interleaves two requests' `matches()` and `handle()`. Then treat it as a class: sweep for any `self._x` assigned in `matches()` and read in `handle()`. That shape is mechanical enough for a semgrep rule like `scripts/qa/semgrep/unlocked-eviction.yaml`.

**Checked against main after integration B2 (2026-09-24): still Open, not
fixed.** `recovery_cron_advisor.py` still declares `self._cached_phase: LifecyclePhase | None = None` in `__init__`, sets it in `matches()`
(`self._cached_phase = _detect_lifecycle_phase(...)`) and reads/clears it in
`handle()` (`cached = self._cached_phase; self._cached_phase = None`) — the
exact shape this entry names. `tests/unit/handlers/post_tool_use/test_recovery_cron_advisor.py`
has `test_matches_then_handle_uses_cached_phase` but no interleaving/
concurrency test. d-00449's `BoundedFifoMap` work (Plan 00449) fixed the
select-then-evict class across 12 sites in 10 handlers, including three
other spots in this same file, but explicitly excluded this per-call-state
class from its Non-Goals and recorded it here instead — see its report,
"Recorded, not fixed". Nothing else in integration batch B2 touches this
attribute. Remains a candidate for whoever picks up this ledger.

### N22 — `lsp_enforcement` takes another command's argument for a grep symbol lookup

**Found by the coordinator**, live. The command was `python scripts/qa/llm_qa.py format lint ... plan_qa docs_qa ... > out.txt; grep -E '^(✅|❌)|^QA:' out.txt`. It was denied with `BLOCKED [R-LSP-SYMBOL-LOOKUP]: ... pattern 'plan_qa' looks like a symbol search`. `plan_qa` is a positional argument to `llm_qa.py`, not to `grep`. The grep's real pattern, `^(✅|❌)|^QA:`, is not symbol-shaped at all. The handler found a `grep` somewhere in the command and then took a symbol-like word from elsewhere in it. `block_once` let the identical retry through, so the cost was one wasted turn. But every "run a QA tool, then grep its capture" command is the everyday shape here, and each one is a coin toss on which word gets picked.

**Candidate remedy:** tokenise the command into its separate simple commands (`;`, `&&`, `||`, `|`), and judge only the pattern argument of a `grep`/`rg` command, never a word belonging to a different command. RED test: the command above is allowed, and `python x.py foo; grep -rn 'def my_function' src/` is still caught on `my_function`. Once 00463/00464 land, this belongs on the shared shell lexer that the parser consolidation (coordinator queue) produces.

### N21 — ✅ Remedied — the semgrep QA gate passes when a rule times out

**Found by the 00414/00415 agent.** Its first version of a new semgrep rule timed out on `daemon/cli.py`, and `scripts/qa/run_semgrep_check.sh` reported PASS. A rule that times out has checked nothing for that file, so the gate fails OPEN, and the slower and more complex a rule is, the more likely it is to be silently skipped on exactly the large files it exists for.

**Candidate remedy:** a timeout, or any semgrep error entry in its JSON output (`errors[]`), fails the gate and names the rule and file. RED test: a rule forced to time out on a fixture makes the gate exit non-zero with the rule named. Check the other QA wrappers for the same "tool error reads as clean" shape, and pin the class.

**Remedied on the d-fresh branch** (`worktree-d-fresh`, 7946008c). Every `errors[]` entry is a violation naming the rule and file. A crash or an empty report fails as `semgrep-did-not-run`. RED test: `tests/unit/qa/test_run_semgrep_check.py`. The fixed gate caught a real timeout of `bounded-intent-unbounded-read-deferred` on `daemon/cli.py`, so the per-rule timeout is now 30 s. The same shape was fixed and pinned in 13 more wrappers. Separately, `github_urls`, `shell_audit`, `skill_refs` and `doc_truth` scanned 0 files from any worktree and passed; that overlaps N26. Detail: `subagent-reports/260924-d-fresh-opus-5-5.md`.

### N20 — ✅ Remedied — the capture-corruption auditor judges a multi-line single-quoted string one line at a time

**Found by the B1 integration agent**, as the stated limit of its fix for the auditor's backslash-continuation false positive. `scripts/qa/audit_capture_corruption.py` now joins `\`-continued lines, but a single-quoted string that spans physical lines (`echo 'x` followed by `y' >&2`) is still judged per line. So the redirect on the second line is not seen, and the echo is flagged. Nothing in the repository has that shape today, so it is latent. The same false positive that broke B1's gate would come back the first time someone writes one.

**Candidate remedy:** carry the open-quote state across physical lines for single-quoted strings too, joining the logical line the same way continuations are joined. RED test: the two-line single-quoted echo with the redirect on the second line is not flagged, and one without the redirect is.

**Remedy:** the auditor now reads each file through one tokeniser (`_logical_lines`), not a heredoc regex plus a per-line continuation join. The tokeniser tracks a stack of single, double and `$'` quotes, `$(...)`, backticks and arithmetic across physical lines. A command stays open while a quote or substitution is open, or while a line ends in a backslash. Each command is joined onto the line it starts on, and the lines it swallows are blanked, so findings keep their physical line numbers. Double-quoted strings, backticks and `$(` captures are covered too. A capture that names its function on the line after `$(` is now seen.

Checking the rest of the file for the same one-line-at-a-time assumption found three more defects in heredoc detection, fixed in the same change:

- **A heredoc operator was recognised anywhere on a line**, including inside quotes and comments. `scripts/upgrade.sh:949` (`printf '\n<<<UPGRADE_METADATA\n'`) made the auditor skip the last 12 non-empty lines of that file. That was a latent false negative: code nobody was auditing.
- **`<<"EOF"` and `<<\EOF` were not recognised**, so their bodies were audited as code.
- **Here-strings (`<<<`) and arithmetic shifts** could both be misread as heredocs.

A heredoc operator now counts only in code. A heredoc body starts after the first newline that is real shell syntax.

Because quote state now decides which lines are judged, a file whose quote, substitution or heredoc never closes is reported as `unparseable-shell`. Before, it was silently audited as one run-on line. Inside a `$(...)` it also tracks `case ... esac`, so a pattern's `)` never closes the substitution. That covers a pattern's optional leading `(`, extglob parens, `;;`, `;&` and `;;&`, a last clause without `;;`, and a `case` nested in a substitution inside a clause. `case` counts as a reserved word only where a command can start.

On all 65 scanned scripts, the new tokeniser extracts the same 227 functions and the same captured names as before, and reports no unclosed spans. Report: [subagent-reports/260924-n466-n20-opus-5-5.md](subagent-reports/260924-n466-n20-opus-5-5.md).

### N16 — `secret_file_guard`'s N4 splat exemption still false-positives against a BOTH-EDGES pattern

**Found by the 00466 review** (nit n2, `subagent-reports/260924-n466-review-opus-5-5.md`), out of scope for the N10/N11 fix turn. N4 fixed the Python unpacking splat false positive (`*words[position + 1 :]`, `*wordlist`) against `*.vault-password` — the ONE shipped pattern with a leading wildcard and NO trailing one. The same splat shape is still denied against `*vault_pass*`, which has a wildcard on BOTH edges: `f(*assets)`, `f(*ssh_args)`, `f(*passthrough)` and `f(*assertions)` are each denied live, because the N4 fix's `pattern_has_trailing_wildcard` escape only widens the gate for a pattern with NO trailing wildcard — `*vault_pass*` has one, so the gate's stricter requirement never applies and the pre-N4 overlap-only behaviour (which is what produces this false positive) is untouched. `*assets`/`*args`-style splats are common Python, so this is a live nuisance, not a rare shape.

**Candidate remedy:** the both-edges branch of `_glob_token_overlaps_stem` already has a stricter "near-total-match" discriminator (`_both_edges_residue_is_near_total_stem_match`) for exactly this over-promiscuity — a leading-wildcard-only token (no trailing wildcard of its own) matched against a both-edges pattern is presently routed through the SAME lenient overlap check as a genuine `*passXXX`-style truncation, rather than through that stricter discriminator. Route a token with no trailing wildcard of its own through the near-total-match test regardless of which edge(s) the PATTERN has open, and keep the existing near-total-match behaviour for tokens that themselves have a trailing wildcard too. RED tests: each `f(*assets)`-style splat against `*vault_pass*` is allowed; a genuine both-edges truncation (`*vault_pass*` reached via, e.g., `*zzz-passwd*`-shaped tokens) still denies.

### N19 — ✅ Remedied — the registry's options-collection failure is logged at debug level

**Found by the N13/N14 agent.** The handler registry's pass-1 `except Exception` logs a failure to collect a handler's options at debug level only. During the N14 work, a local variable that shadowed the new accessor made the registry silently drop EVERY handler's options, and only an existing registry test caught it before commit. In production, that failure would have looked like every handler running on defaults, with nothing at a visible log level.

**Candidate remedy:** narrow the catch to the exceptions that option collection can legitimately raise, and log anything else at error level with the handler name. If a handler's configured options cannot be applied, that is a degraded protection state and should surface in `health`. RED test: an injected failure while collecting options is visible at error level and in health.

**Remedy** (`worktree-n466-n13n14`, 4bb2a733 and fd8778a3): the pass-1 `try` covers only the `handler_options` call, which reads every block shape without raising, so anything it catches is a daemon defect. Each failure is logged at ERROR with the handler's registry key and a traceback, and recorded in `HandlerRegistry.option_failures`. The handler still registers, on its defaults: loud fail-open, which the coordinator chose over fail-fast because a daemon that will not start protects nothing. `health` lists the failures under "Handler options" and exits 1. Because `health` is only seen when someone runs it, `project_handler_load_checker` also receives the failures and opens each session with a "HANDLER OPTIONS NOT APPLIED" advisory naming each handler. Pinned by `tests/unit/handlers/test_registry_option_collection_failure.py` and `TestOptionFailures` in the checker's tests. Release note 62.

### N18 — ✅ Remedied — PlanWorkflow.core.md says the plan index is linted against one rule

**Found by the N13/N14 agent.** `CLAUDE/core/PlanWorkflow.core.md:407` and its deployed template copy say the plan index is linted "against one rule". `index-no-log` already made that false, and N13 adds `plan-stats-arithmetic` to the commit gate. The page is a deployed template pair, so it ships to clients.

**Candidate remedy:** name the rules, or better, point at the plan QA rule list, which is the source of truth, instead of counting. Change both copies of the pair together, and pin it with a doc-truth test that the page names no count that disagrees with the registry.

**Remedy** (`worktree-n466-n13n14`, e00a16c4): both copies now name `index-row-length` only as an example and point at a new `plan-qa --list-checks`, which prints every registered check with its `stage:level` pairs straight from `all_checks()`. `tests/unit/plan_qa/test_plan_qa_doc_truth.py` pins both copies: no count of rules or checks, the listing is named, every named check is registered, and the two sections are identical. Release note 63.

### N17 — ✅ Remedied — `skill_opportunity_detector` never receives its configured options

**Found by the N13/N14 agent.** `_options()` reads `self.config["options"]`, which only `configure()` populates. Nothing in `src/` calls `configure()`; the registry injects options as `_<key>` attributes instead. So a configured `check_interval_days` is ignored at runtime, and only the unit tests, which call `configure()` directly, exercise the option.

**Candidate remedy:** read options the way the registry delivers them, through the shared accessor. RED test: a handler built by the real registry from a config with a non-default `check_interval_days` uses it. Then audit every handler for a `configure()`-only options path, and pin the class with a test that instantiates each handler through the registry with a non-default value for every declared option and checks that it is honoured.

**Remedy** (`worktree-n466-n13n14`, bcd9bf61): two class pins in `tests/unit/handlers/test_registry_option_injection.py`. One builds every handler through the real `register_all` with a non-default value for each option in its `HANDLER_REFERENCE.md` Options table, and fails if the value is not delivered or never read. The other fails on any read of an option from a `self.config` dict. They failed on exactly three handlers, all now fixed: `skill_opportunity_detector`; `hook_registration_checker`, which ignored `auto_migrate_settings: false` (set in this repository's own config) and `auto_repair_registrations`; and `version_check`, which ignored `cache_ttl_hours` (now documented). Release note 61.

### N15 — ✅ Remedied — `remote-docs add` scans a capture with an unconfigured `sensitive_content` handler

**Found by the Plan 00468 docs agent.** `daemon/cli.py` (~:6377) builds `SensitiveContentHandler()` with none of its configured options for the capture-time `scan_text` in `remote-docs add`. So the scan at the moment a page is vendored runs with no public patterns at all. That is how 28 example UUIDs were vendored into `hooks.md` without a warning, to be caught only later by the tree-wide QA scan. The secret word list happens to be found only because the configured path equals the default. This is the same class as N14: a component reads a handler's behaviour without that handler's configured options.

**Candidate remedy:** construct the handler from the project's resolved config, through the same shared handler-options accessor N14 introduces. RED test: `remote-docs add` of a page carrying a configured public-pattern match reports it at capture time, and a non-default `secret_word_list_path` is honoured. Add the construct-without-config shape to N14's class audit.

**Remedy** (`worktree-n466-n13n14`, 0881dc94): `_sensitive_content_guard(project_root)` builds the handler from the project's config through `handler_options` and a new shared `registry.apply_handler_options`, with the word-list path resolved against the project root. `remote-docs add` and `refresh` now refuse a page matching a configured public pattern or a term from a non-default word list (`TestCaptureScanUsesTheConfiguredHandler`). The class audit found one more instance, `hooks-daemon check` probing `lint_on_edit` without its languages, also fixed. A new pin fails on any built-in handler constructed outside the registry without `apply_handler_options`. Release note 59.

### N14 — ✅ Remedied — log and payload redaction ignore a configured secret word list path

**Found by the 00414/00415 agent**, outside its brief. `utils/secret_redaction.py` `_resolve_active_path` reads `handler_cfg.get("options", {})` only when `isinstance(handler_cfg, dict)`. But `Config` coerces every handler entry to a `HandlerConfig` model (`type(c.handlers.pre_tool_use.get("sensitive_content"))` is `HandlerConfig`), so the isinstance test is never true. The daemon-wide resolver therefore never reads a configured `secret_word_list_path`, and always falls back to the default `.claude/block-words.secret`. The `sensitive_content` handler reads its own option correctly, so blocking still works. But payload capture and log redaction silently use the wrong list, or no list, in any project whose word list lives somewhere else. That is exactly how a secret term reaches a log. This repository is unaffected only because its configured path equals the default. `secret_file_matching.resolve_configured_patterns` carries a comment about this same mistake and fixed its own copy, so this is the second sighting of the class.

**Candidate remedy:** read the option through `HandlerConfig.options`, via one shared accessor for handler options that accepts either shape. RED test: with a non-default `secret_word_list_path`, a term from that list is redacted from a captured payload and a log line. Then audit every `isinstance(<handler config>, dict)` read of handler config across `src/`, and pin the class with a test or QA check that fails when handler config is read as a dict.

**Remedy** (`worktree-n466-n13n14`, e7f6b3d8): one accessor, `config.models.handler_options`, reads a block's options whichever shape it arrives in, and all 17 hand reads of `options` in `src/` go through it. A configured `secret_word_list_path` now reaches payload capture and log redaction (`TestConfiguredWordListPathReachesEveryLeakVector`). `tests/unit/config/test_handler_options_accessor.py` fails on any hand read of `options` outside the accessor, and on any local that shadows it. Release note 57, plus post-upgrade task 02 for projects with a non-default path to audit files written before the fix.

### N13 — ✅ Remedied — the plan-index statistics arithmetic is checked only by full QA, so a wrong count reaches main

**Found by the coordinator**, through Plan 00421's agent. Opening Plan 00468 updated the README statistics bullets (468 allocated, 455 distinct) but missed the closing self-check line (`454 + 13 = 467`). `check_repo_hygiene.py`'s `plan-stats-arithmetic` check catches exactly this. But it runs only in `llm_qa.py all`, and the commit-time plan QA gate that runs on every README commit does not include it. The inconsistent index was therefore committed and pushed (d10bbf13), and was found only when an agent ran the hygiene checker by hand. The same README gate already enforces row length and the 30-row completed window at commit time.

**Candidate remedy:** run the `plan-stats-arithmetic` check in the commit-time plan QA gate whenever the staged tree touches the plan index, or move the check into plan QA and have repo_hygiene call it. Either way there is one implementation. RED test: a commit staging a README whose statistics disagree with the self-check line is denied, and names the line to fix.

**Remedy** (`worktree-n466-n13n14`, 724c2d7f): the check moved into plan QA as `plan_qa/checks/stats_arithmetic.py`, and `check_repo_hygiene.py` keeps only a thin adapter, so there is one implementation (pinned). It blocks at commit when the commit stages the plan index and the disagreement is not already in HEAD, advises otherwise so inherited drift traps no unrelated commit, blocks in the sweep and advises at edit time. The denial names the line (`TestPlanStatsArithmetic`). Release note 58. It also delivers Plan 00408 Task 3.2.

### N12 — ✅ Remedied — a hand-built probe payload is logged as real traffic, because nothing tells a prober to mark it

**Found by the Plan 00467 plugin audit.** The audit fed synthetic PreToolUse payloads through `.claude/hooks/pre-tool-use` to probe handler verdicts. They carried no `synthetic_source` field, and their session ids (`plugin-audit-probe` and similar) match no known synthetic shape. So `daemon/synthetic_traffic.py` classed them as REAL traffic in `verdicts.jsonl`, including the orchestrator-simulate record that Plan 00418's enforcement decision will be read from. The marker (`SYNTHETIC_SOURCE_FIELD`, `synthetic_traffic.py:39`) is documented only in that module's docstring. CLAUDE/DEBUGGING_HOOKS.md, the handler-development guide and the agent-facing docs never mention it, so a prober cannot know to set it.

**Candidate remedy:** document the marker wherever probing a handler is taught (DEBUGGING_HOOKS.md, HANDLER_DEVELOPMENT.md, and the acceptance and playbook guidance), with a copy-paste payload that sets it. Consider a small `bin/hooks-daemon probe <event> <json>` helper that sets the marker itself. Add a test that the probing docs name the field.

**Remedied on `worktree-n466-n12`** (8fa4c354 to f813156a, merged in integration B3). `hooks-daemon probe <event> --json|--file [--as main|sub]` sends a payload through the project's own hook script with `synthetic_source: manual-probe` filled in, and refuses a marker the classifier would ignore. A probe names the thread it stands for with `probe_as`, so marking it no longer costs it the scoped handler it was probing. Every test and script that probes the live daemon is marked, and a guard pins that class. The probing docs name the field. Detail: [subagent-reports/260924-n466-n12-opus-5-5.md](subagent-reports/260924-n466-n12-opus-5-5.md).

### N11 — any exception in `secret_file_guard.matches()` lets the call through unless `strict_mode` is on

**Found by the 00466 review** (major M4, `subagent-reports/260924-n466-review-opus-5-5.md`). N5's crash was the second time an exception in this guard's `matches()` skipped the guard entirely; Plan 00357 was the first. Under `strict_mode: false` the chain logs the exception and allows the call. **Correction (N24, guard-defects security review 2):** the sentence that stood here — "This repository runs `strict_mode: true`, so here the crash denied" — was false. `daemon.strict_mode` never reached the live daemon (see N24, now remedied), so a crash here fell open in EVERY install, including this repository's own, whatever `hooks-daemon.yaml` declared. With N24's fix live, a crash here now denies in this repository (`strict_mode: true`) and, independently, would also deny on any install once this guard is tagged `SAFETY`+`BLOCKING` (it already is) — see N24's Part 2. One raise path is still live after N5, though it isn't exploitable: a file path containing a NUL byte.

**Candidate remedy:** make the guard structurally fail closed. A raise anywhere in its match or route computation becomes a deny naming the internal error, whatever the global `strict_mode`, because a protected-read guard that fails open is worse than a false deny. Pin it with a test that injects an exception at each stage. Then audit the other security guards that should behave the same (`sensitive_content`, `project_containment`, the destructive-git rules) and decide each one explicitly.

### N10 — a wildcard in the middle of a protected filename gets past `secret_file_guard`

**Found by the 00466 review** as a pre-existing problem on main, security-relevant. `cat .vault-pas?word` and `cat prod.vault-passw*rd` name a protected file through a glob the shell expands, and the guard does not deny them. The mention scan handles a leading or trailing wildcard (the N4 overlap logic), but not a `?`, `*` or `[...]` inside the name.

**Candidate remedy:** treat any shell-glob token as a pattern, and deny when the pattern could match a protected name. Compare against the protected basenames and stems, or expand it against the directory when that exists. Keep it no looser than the N4 rule. RED tests: interior `?`, `*` and bracket globs of each shipped protected pattern are denied, while unrelated globs such as `*.py` and `src/*.md` are allowed.

**Remedy (implemented):** `secret_file_matching.py` gained `_globs_can_intersect(a, b)`, a real two-glob language-intersection test (standard sequence-alignment DP over `*`/`?`, O(len(a) · len(b))) — not another edge heuristic, because an interior wildcard has no edge for the existing leading/trailing overlap check to key on. A new `_interior_wildcard_mention` runs it for every token whose raw spelling carries glob syntax (`_is_glob_shaped(raw_form)`), over each of its bracket-expanded forms — so a finite bracket class (`.vault-pa[sz]word`) is covered too, even after expansion strips its wildcard-ness down to a plain literal, since the intersection test degenerates correctly to exact-match in that case. Scoped narrowly to keep N4 intact: only a token with NEITHER a leading NOR a trailing wildcard reaches it (an open-edge token is already handled by the pre-existing checks, N4/m1 fixes and all), and a pattern with wildcards on BOTH edges (`*.secret*`, `*vault_pass*`) is excluded — full intersection against a "contains this text anywhere" pattern is satisfiable by nearly any token carrying its own wildcard (`report-[0-9]*.txt` and `secret*.py` genuinely glob-intersect with `*.secret*`, live-verified as new false positives during implementation, neither is evidence of a protected file), the same over-promiscuity `_both_edges_residue_is_near_total_stem_match` already exists to guard against elsewhere in this module. RED tests (confirmed failing pre-fix, passing after) in `TestBashMentionsProtectedPath`: `test_interior_question_mark_truncation_is_matched`, `test_interior_star_with_unrelated_prefix_is_matched`, `test_interior_bracket_expression_truncation_is_matched`, plus `test_unrelated_interior_wildcard_tokens_are_not_matched` and `test_splat_false_positive_from_n4_still_allowed` pinning the N4 fix stays intact. Full `test_secret_file_matching.py` (203 tests) and `test_secret_file_guard.py` (82 tests) pass.

**Correction (M2, guard-defects review 2)**: this entry's acceptance criterion
("interior `?`, `*` and bracket globs of each shipped protected pattern are
denied") was not met for 2 of the 6 shipped patterns — `*.secret*` and
`*vault_pass*` (both-edges patterns, deliberately excluded from
`_interior_wildcard_mention` above) stayed fully open to every interior
spelling, an edge-plus-interior combination on any pattern escaped every
check, and an unenumerable bracket class (`[!x]`, `[^x]`, `[[:alpha:]]`, an
over-cap range) reached the DP with its brackets read as LITERAL characters
instead of a wildcard, so it failed OPEN rather than closed. Brace expansion
(`.vault-pas{s,}word`) was also uncovered for every pattern. Fixed on the
guard-defects-review-2 branch: the DP now runs for edge-open tokens too
(against every pattern that is not both-edges, gated by a new degenerate-
orientation check so a leading-wildcard token is never blindly tested
against a trailing-wildcard pattern — that combination is satisfiable by
ANY literal on either side, which is not evidence of anything); an
unexpanded bracket expression is substituted with `?` before the DP runs (a
safe superset); both-edges patterns get a filesystem-truth route instead
(`_both_edges_glob_mention`, gated by a cheap literal-overlap pre-filter so
it never pays for a real directory listing on an unrelated token); and
brace groups are expanded against the raw command text before tokenising,
the same conflict `enforce_llm_qa`'s own M1 fix resolves. Pinned with 4 new
test classes (16 tests) in `tests/unit/utils/test_secret_file_matching.py`.

**Correction (M-1, guard-defects review 4)**: the brace-group expansion added
by review 2's correction only ever split a group on `,` — a brace SEQUENCE
(`{start..end[..step]}`, e.g. `id_rs{a..a}` reaching the exact protected name
`id_rsa`) and quote-stripping inside a group or word (`id_"rs"a`, `i'd'_rsa`,
`id_rs{'a',x}`) were both unhandled, and neither the module's crude
delimiter-split tokeniser nor the brace stream ever saw a word carrying `$`,
a backtick, or a quote as anything but a boundary — so a substitution-carrying
word (`cat id_rs$x`) produced no token resembling the name at all. Fixed by
scoping the remedy to the whole CLASS, not the two reported spellings: a lazy
brace-sequence generator (numeric/alpha, either direction, optionally
stepped, capped by the same `max_spellings` guard so `{1..100000}` still
fails closed) plus a from-scratch bounded shell-word normaliser
(`shell_expansion.normalise_word`/`iter_normalised_shell_words`) that strips
quotes, decodes backslash/ANSI-C escapes, concatenates adjacent
quoted/unquoted spans into one word the way a real shell does, and collapses
any statically-unresolvable substitution (`$VAR`, `${...}`, `$(...)`, a
backtick, `$((...))`) to a single `*` — turning the whole containing word
into a glob judged by the pre-existing `_globs_can_intersect` DP infrastructure
this same N10 remedy built, rather than needing new matching logic. Chained
as a third additive stream in `iter_protected_mentions`. Own findings caught
before commit (not in the review): the new stream initially bypassed the
import-module-path exemption and double-reported ordinary mentions already
found by the plain tokeniser — both fixed (see the review-4 fix report).
Verified end-to-end through the real `SecretFileGuardHandler`, both shipped
defaults and a project-configured exact pattern. Full detail:
`subagent-reports/260924-n466-guards-review4-fix-sonnet-5.md`.

**Correction (addendum, guard-defects review 4)**: two more gaps folded into
the same class. (1) A false positive: ordinary Python (`[*words[:subcommand_index], ...]`) tripped the guard, because `_token_literal_residue` treated an
UNCLOSED `[` as a wildcard character to strip (bash reads it as literal),
and because Write/Edit CONTENT scanning ran the same AGGRESSIVE glob-shaped
heuristics a real shell command needs, on source code that no shell ever
expands. Fixed both: the residue fix, and a `context="bash"|"content"`
parameter threaded through the whole mention-scan API, restricting content
scanning to the literal/glob-pattern matcher only. (2) m-2 (the both-edges
FS-truth route is cwd/existence-dependent): a `?`-only interior spelling of
a both-edges pattern (`demo.se?ret`, `vault?passwords.yml`) now denies
TEXTUALLY, via a both-edges branch in `_dp_intersection_is_meaningful` that
treats the DP call as meaningful only when the token carries no `*` — a
both-edges pattern's own wildcards can absorb the required substring
adjacent to ANY `*` the token has, making the DP trivially satisfiable and
reopening Plan 00306/00311's false-positive class otherwise
(`report-[0-9]*.txt`, `secret*.py`); a `?` can only absorb one character
each, so a genuine `?`-only intersection is a real signal. A `*`-bearing
both-edges truncation (`demo.s*t`) still needs the FS-truth route
unchanged — flagged to team-lead as a judgement call, not a full resolution
of every example in the addendum's own RED-test wording. Full detail:
`subagent-reports/260924-n466-guards-review4-fix-sonnet-5.md`, Addenda 1-2.

**Correction (addendum, guard-defects review 5)**: review 5 found the
addendum-4 `context` fix above was itself too broad -- `context="content"`
was applied uniformly to EVERY `_SCRIPT_EXTENSIONS` entry, including
`.sh`/`.bash`, whose content genuinely IS shell text a shell expands when
the script runs, reopening the write-then-execute gap for those two
extensions specifically. Fixed, and per team-lead's own follow-up widened
further: `context="bash"` now applies to a `.sh`/`.bash` extension, a
Makefile (`Makefile`/`makefile`/`GNUmakefile`/`.mk`), a CI workflow YAML
(`.github/workflows/*.yml`/`.yaml`, `.gitlab-ci.yml`/`.yaml`), or an
extensionless script identified by its own shebang naming a shell
interpreter -- all newly recognised as scan-worthy at all, not just
reclassified, since none but `.sh`/`.bash` was previously in
`_SCRIPT_EXTENSIONS`. Full detail:
`subagent-reports/260924-n466-guards-review4-fix-sonnet-5.md`, Addendum 3.

### N9 — ✅ Remedied — `docs_qa` judges gitignored markdown, so installing a Claude Code plugin fails local full QA

**Found by the coordinator** right after installing the Defence Before Fix plugin at project scope (Plan 00467). In this container Claude Code's config directory is `.claude/ccy/`, so the plugin's cache (`.claude/ccy/plugins/cache/...`) and marketplace clone (`.claude/ccy/plugins/marketplaces/...`) land inside the repository. Both are gitignored (`.claude/ccy/.gitignore:3: *`). `llm_qa.py docs_qa` then reported 12 `source-tree-markdown` findings, one per vendored spec file, and the tool FAILED. It reported 0 findings at batch A's gate, before the install. CI does not see this, because a fresh checkout has no `.claude/ccy/`. Every local full QA run, including the coordinator's integration gate, now fails on files that are not part of the project.

The docs corpus walks the filesystem without honouring `.gitignore` (`docs_qa/corpus.py`; it already special-cases `.claude/ccy/CLAUDE.md`, lines 149 and 421).

**Candidate remedy:** the corpus considers only tracked files plus untracked files that are NOT ignored, i.e. `git ls-files --cached --others --exclude-standard`, with a defined fallback outside a git repository. Keep any deliberate inclusion that is ignored but meant to be scanned explicit and named. RED test: a gitignored markdown file under a source-like directory produces no finding, and a tracked one still does. Audit the other QA corpora (plan_qa, doc_snippets, doc_truth, repo_hygiene, sensitive_content, british_english) for the same filesystem-walk assumption, and pin the class.

**Remedied.** `utils/git_repo.py` gained `git_visible_paths(project_root)`: one combined `git ls-files --cached --others --exclude-standard -z` call returning every path git would add, or `None` outside a git repository (callers then fall back to their pre-existing unfiltered walk). `docs_qa/corpus.py`'s `iter_markdown_paths` and `iter_corpus_paths` both filter through it; `.claude/ccy/CLAUDE.md` — deliberately untracked and gitignored, yet named in scope by `is_module_doc_path`'s own docstring — is kept via a small named exception set (`_GITIGNORED_MARKDOWN_INCLUDES`) rather than left an accidental gap, with a directory-descent rule (`_git_visible_ancestor_dirs`) so the walk still reaches it.

The class audit found a SECOND live instance of the same defect: `scripts/qa/check_doc_truth.py`'s `_iter_markdown` denylisted `.claude/ccy/plugins/marketplaces/` by name but not its sibling `cache/` directory, so a plugin's cached spec markdown could still reach `_check_shell_fences` as a false finding. Fixed the same way (filtered through `git_visible_paths`) and reproduced directly with a fixture that git-ignores `.claude/ccy/` and plants a violation inside it.

The rest of the named corpora were audited and left unmigrated, each for a stated, mechanically-pinned reason: `repo_hygiene`, `sensitive_content` and `british_english` already scan `git ls-files` directly by design (tracked-only is deliberate for hygiene/secret-scanning); `magic_values` and `error_hiding` are scoped to `src/`/`tests/`/`scripts/` only, which carry no `.gitignore` gap; `doc_snippets`'s glob set never reaches a nested `.claude/ccy/` subtree; `handler_reference` never walks a directory at all (it introspects the live `HandlerRegistry`); `plan_qa`'s `PlanTree.scan` descends only the configured plan directory via `iterdir()`, never a project-root-wide walk. `tests/unit/qa/test_qa_corpus_git_visibility_audit.py` pins this table as a ratchet: every `MIGRATED` entry is verified by AST to actually import and call `git_visible_paths`, every declared source path is checked to still exist, and every `ALLOWLISTED` entry must carry a non-trivial reason — mirroring `test_qa_package_dependency_direction.py`'s shape.

### N8 — ✅ Remedied — `reference_repo_freshness` says BLOCKED on a call it allows

**Found by the coordinator.** A Read of a fresh clone under `untracked/repos/` was denied (`R-REFERENCE-REPO-NOT-VERIFIED`), as the default `block_once` posture intends. The next command that named that clone, a `mv` moving it to `untracked/work/`, RAN. Its hook context still opened with `BLOCKED [R-REFERENCE-REPO-NOT-VERIFIED]: a read of a governed reference clone...`.

`_verdict()` (`handlers/pre_tool_use/reference_repo_freshness.py:575-576`) returns `GatingResult(decision=Decision.ALLOW, context=[message])` for a repeat in `block_once` mode, and for `advise` mode at :565. `message` is the verbose DENY rendering (`self._formatter.verbose(rule)`), which starts with `BLOCKED`. An agent reading its context is therefore told a call was blocked when it ran. It either retries something that already happened, or learns that "BLOCKED" means nothing.

**Remedy:** `RuleFormatter` gained a fourth rendering, `advisory(rule)` (`core/rule.py`) — same `rule_id` and the same `Rule.verbose` teaching content as `verbose()`, headed `ADVISORY` instead of `BLOCKED`, matching the "ADVISORY:" convention several handlers already use for their own hand-rolled non-blocking reports (no new format was invented). `reference_repo_freshness.handle()` now computes `_is_blocking(session_id, subject, mode)` — a preview of `_verdict()`'s own decision, pinned to it by `TestIsBlockingMatchesVerdict` — BEFORE building the message, and `_not_verified`/`_stale` select `verbose()` when the call will actually be denied and `advisory()` when it will not (an `advise`-mode result or a `block_once` repeat). `_verdict()` itself is unchanged; it stays the sole place that decides and records.

An AST-based static sweep of every handler for `Decision.ALLOW` built from `formatter.verbose`/`terse` content (directly or through an assignment chain) found exactly one other confirmed occurrence: `reference_repo_freshness` itself — the fix above. Two structurally similar but SAFE call sites surfaced for manual review (`lint_on_edit._run_lint_command`'s `language_name` parameter, `plan_qa_edit._advisory_result`'s `findings` parameter) and were confirmed not to carry deny-shaped content. `lsp_enforcement`, named by name as a suspect, was confirmed already correct: its `block_once` repeat and `advisory` mode both return a plain `dynamic_detail` string with no rule-id/BLOCKED prefix.

The class-wide guard lives at `tests/integration/test_allow_never_carries_deny_headline.py`: it drives every handler's own declared BLOCKING acceptance test twice against the SAME instance, replicating the history-recording step `DaemonController.dispatch()` performs after every route (`daemon/controller.py`) so a handler whose block-once state lives in the shared `HandlerHistory` data layer (not an in-instance dict, e.g. `lsp_enforcement`) genuinely sees its repeat call transition to ALLOW — and asserts the repeat's `reason`/`context` never contains the `"BLOCKED ["` signature. Confirmed RED against a deliberately reintroduced defect in `lsp_enforcement` (caught it), then GREEN once reverted. `reference_repo_freshness`'s own regression coverage lives in its unit tests (`TestBlockOnce`, `TestConfiguredModes`, `TestNotVerified`) instead, RED/GREEN-verified the same way — its only DENY acceptance test declares `harness_cannot_produce` (no fixture can build a real governed checkout), so the integration harness cannot reach it.

### N7 — ✅ Remedied — the regenerated CLAUDE.md guidance block is not deterministic, so every daemon restart can commit a reorder

**Found by the coordinator** at the batch A merge. The integration worktree's daemon had just regenerated CLAUDE.md, and that result was committed. The main checkout's daemon then restarted on the same tree and auto-committed `ce31d6d8` ("Auto: hooks daemon regenerated CLAUDE.md handler guidance"). The commit changed 18 lines both ways. Every change is the same handler markers in a new order: `tool-disable-advisor`, `project-handler-load-checker`, `hook-registration-checker`, `routine-qa-sweep` and `secret-file-hygiene-checker` among them. The earlier 00462 merge restart committed `6359ad0c`, changing 83 lines both ways, with the same shape.

`ClaudeMdInjector._collect_tiers()` emits handlers in the order of `self._handlers` (`core/claude_md_injector.py:642`) and never sorts them. Two daemons on one tree can therefore produce different blocks, apparently for handlers that share a priority. The results:

- A spurious auto-commit on restart.
- A CLAUDE.md conflict whenever two branches merge. This happened twice while building batch A.
- A worktree's regenerated block that never matches main's.

**Candidate remedy:** emit in a total order that depends only on the handler set, for example tier, then priority, then handler name. Test that two injector runs over the same handlers in shuffled input order produce byte-identical blocks. Check whether `HOOKS-DAEMON.md` generation has the same tie problem, and give it the same fix.

**Remedy shipped in commit `0dba7bfb`.** `_collect_tiers()`
(`core/claude_md_injector.py`) now sorts each of the three tier lists
(`promoted`, `progressive`, `fallback`) by handler name before returning
them — name alone is a complete total order because two active handlers
never share a name, and priority is not consulted because handlers from
different event chains are mixed into one flat CLAUDE.md tier where
priority carries no meaningful cross-event-type ordering. `daemon/ controller.py`'s handler collection was reading the chain's private,
unsorted `_handlers` list instead of its public `handlers` property (which
already sorts by `(priority, name)` on access, the same pattern
`EventRouter.get_all_handlers()` uses) — fixed to use `chain.handlers`.
`TestGuidanceOrderIsIndependentOfDiscoveryOrder`
(4 tests, RED against the pre-fix code) asserts forward- and
reverse-ordered handler lists inject byte-identical `<hooksdaemon>`
blocks. The sibling tie in `.claude/HOOKS-DAEMON.md` generation
(`daemon/docs_generator.py`'s `_render_handler_table()`) sorted by
priority only, so same-priority handlers kept registry order; fixed to
sort by `(priority, config_key)`, pinned by
`test_same_priority_handlers_are_order_independent` (1 test, RED against
the pre-fix code). Verified idempotent: `regenerate-docs` run twice in a
row produces the identical diff both times.

**Correction (00466 review, minor m6):** the commit message and the
paragraph above blamed `pkgutil.walk_packages()` for the unsorted input.
That is wrong — `pkgutil` sorts `os.listdir` output internally
(`_iter_file_finder_modules` calls `filenames.sort()`). The real unsorted
source is `HandlerRegistry`'s two `event_dir.glob("*.py")` loops
(`handlers/registry.py:467` and `:511`), which iterate in `os.scandir`
order; a third loop in the same file (line 198) already wraps its glob in
`sorted(...)`. The injector-level and docs_generator-level sorts above
still make each rendered artefact a pure function of the handler set on
their own — this correction is to the narrative, not to the fix's
soundness. Both `registry.py` glob loops are now wrapped in `sorted(...)`
too, so discovery order is deterministic at its source as well as at
every rendering layer.

**Also fixed (00466 review, nit n6):** the promoted tier's alphabetical
sort lost the reason a handler is promoted at all — the config author's
own `promoted_handlers` list order, chosen so the most-triggered guidance
reads first. `_collect_tiers()` now sorts the promoted tier by each
entry's INDEX in `self._promoted_handlers_order` (the author-authored
config list, kept alongside the pre-existing `frozenset` used for the O(1)
membership check) instead of alphabetically — still a complete,
deterministic total order, because that config list is a fixed value, not
a filesystem walk. The progressive and fallback tiers are unaffected;
alphabetical is the right call there, since nothing about them carries
author-chosen intent. Pinned by
`test_promoted_tier_follows_the_authors_promoted_handlers_order` (RED
against the pre-fix alphabetical code).

### N3 — ✅ Remedied — `goal_injection` treats any edit of an In Progress plan as the plan starting, and displaces the live goal

**Found by the coordinator**, live. The supervisor had set the goal to Plan
00461\. The coordinator then added a table row to this ledger's PLAN.md. That
edit drew `⚠️ GOAL DISPLACED: ... Plan(s) 00461 is now superseded by Plan 00466's goal`, and the handler wrote a goal-intent signal for 00466.

The handler's docstring says it writes the signal "when a plan flips to In
Progress". `handle()` never looks for a flip. It reads the PLAN.md from disk
after the write, and `_STATUS_IN_PROGRESS_RE` matches any plan whose
**Status** line reads In Progress. The once-per-plan-per-session latch is
the only limit. So the first Write or Edit in a session to any plan that is
already In Progress fires, however unrelated to its status. That includes a
ledger row, a task tick or a typo fix. The results:

- The supervisor receives a goal for a plan nobody started. For a rolling
  ledger that goal cannot complete.
- The displacement advisory tells the session that the goal it is really
  working was superseded.
- The ledger now tracks the edited plan as owed work, and the Stop hook
  challenges stops on its behalf.

**Candidate remedy:** fire only on a real transition. For `Edit`, the
`old_string` → `new_string` pair changes the **Status** line to In Progress.
For `Write`, the file's previous content (for example the pre-write copy
`write_clobber_guard` already reasons about, or git's `HEAD` version) did
not read In Progress, or the file is new. An edit that leaves an In
Progress status unchanged emits nothing and displaces nothing. RED tests:
an Edit that adds a table row to an In Progress plan emits no signal and no
advisory; an Edit flipping Not Started to In Progress still emits; a Write
creating a new In Progress plan still emits.

**Remedy shipped in commit `5676772d`.** `GoalInjectionHandler` gained
`_is_real_flip_to_in_progress`: for `Edit` it parses `old_string` with
`PlanDoc.parse` and answers directly from that fragment's own Status line
(absent → this edit never touched it → not a flip; present and not In
Progress → a flip). For `Write` there is no pre-write disk copy left by the
time PostToolUse runs, so git HEAD stands in for "before" — deliberately
not the Write/Edit `tool_response`, whose shape this codebase has never
verified for either tool (see this same folder's
`POSTTOOLUSE_FIXTURE_VERIFICATION.md`). A path absent at HEAD (new or never
committed) reads as nothing to flip FROM, matching the pre-existing
single-plan contract. The once-per-`(plan, session)` latch and the
retirement-refresh path are unchanged. `TestStatusFlipDetection` (8 tests,
3 RED against the old code) pins the contract; the module docstring, the
class docstring and `get_claude_md()` now state it explicitly.

**Follow-up in commits `6699fbbd` and `4813adc8`**, after review. The first
`_head_plan_text` caught `RuntimeError`/`OSError`/`ValueError` and returned
`None`, which `error_hiding`'s `return-none-on-error` check flagged; the
initial fix added an exclusion, which the review correctly rejected —
this project allows no new QA suppressions. Restructured instead: path
membership is now a plain `Path.is_relative_to` comparison, never a caught
`ValueError`, and `ProjectContext.project_root()` is called unguarded — by
the time any handler dispatches the daemon has always initialised it, so a
`RuntimeError` here means genuine misconfiguration and is left to propagate
to the dispatcher (`core/chain.py`'s existing per-handler exception
handling), rather than being swallowed into a false "nothing to compare
against". The lookup moved out to
`utils.git_facts.project_relative_head_text` so it has one home instead of
a per-handler copy. `error_hiding` now passes with zero violations and no
exclusion for this code.

The review also asked for the sibling to be fixed, not just documented as
accepted: `recovery_cron_advisor`'s Write-path completion check
(`_STATUS_COMPLETE_RE.search(content)` against the whole new file) shared
the exact same state-vs-transition defect shape for `**Status**: Complete`
— "only an advisory" was not a reason to keep it. `_detect_lifecycle_phase`
now calls `_write_is_real_completion`, which reuses
`project_relative_head_text` rather than a second copy: a Write whose
content reads Complete is COMPLETION only when the plan was not already
Complete at HEAD; otherwise the event matches no phase at all (never falls
through to PROGRESS/CREATION). `TestWriteCompletionIsTransitionBased` (4
tests, 1 RED against the pre-fix code) pins the contract. Its Edit path
(`_edit_results_in_status_complete`) already required the edit's own
`old_string`/`new_string` to assert Complete and needed no change.
`plan_close_approval._is_terminal_flip` was already transition-based
(compares `PlanDoc.parse(current).status` against the proposed status).
`plan_qa_edit.py`'s "In Progress" occurrences are guidance prose, not
status-detection logic.

**Second review pass (majors M2/M3, minors m4/m5, nits n3/n4/n7)**, fixed
together on the same branch:

- **M2 — a daemon restart silently disabled the retirement refresh.**
  `_maybe_refresh_on_retirement` gated on the IN-MEMORY `self._fired`
  latch, which a restart (`daemon_restart_verifier` requires one before
  every commit) empties, and N3's flip-only rule meant a later non-flip
  write no longer re-latched either — so a plan flipped in one daemon
  lifetime and completed in the next never dropped out of the combined
  `/goal` signal. Fixed by asking the PERSISTENT `GoalLedger` instead
  (`GoalLedger.has_live_entry` at the time; superseded by
  `owning_sessions` in the third review pass below), which survives the
  restart the latch does not. Pinned by
  `test_completing_a_plan_after_a_daemon_restart_still_refreshes_signal`
  (a fresh `GoalInjectionHandler` instance simulates the restart; RED
  against the pre-fix code).
- **M3 — the "goal survives a session restart" contract was silently
  dropped, not replaced.** Plan 00269 Task 2.1 deliberately chose "the
  first edit to an already-In-Progress plan in a NEW session re-fires" so
  a resumed session got its `/goal` back; N3's flip requirement removed
  that with no replacement, and the original release note wrongly called
  it "no action needed". Restored via `GoalLedger.reassert_session` (two
  new ledger methods: `session_has_entries` decides whether THIS session
  is new at all; `reassert_session` transfers ownership of the plan's
  already-live entry with NONE of `record_emission`'s displacement
  bookkeeping) and `_maybe_reassert_for_new_session`: a session with no
  ledger entries whatsoever that touches an already-live plan without
  itself producing a real flip gets its own signal written, no new ledger
  record, no "GOAL DISPLACED" advisory, and no risk of wrongly displacing
  some OTHER live plan. A session that already has its own live goal is
  unaffected. Pinned by three new tests in
  `TestNewSessionReassertion` (one RED against the pre-fix code) plus
  three new `GoalLedger` test classes. Release note 65 and the module
  docstring corrected to describe the restored contract instead of
  claiming no behaviour changed.
- **m4 — an Edit whose `old_string` carried only the bare status VALUE
  (no `**Status**:` prefix) missed a genuine flip.** `PlanDoc.parse` on
  `old_string` alone then found no Status line and read "never touched
  it". Fixed by reconstructing the pre-edit text from what is already on
  disk when this happens — reversing the SAME substitution the Edit tool
  performed (`_reconstruct_pre_edit_text`, honouring `replace_all`) — and
  parsing that instead of giving up. Pinned by
  `test_edit_whose_old_string_is_only_the_status_value_still_emits` (RED
  against the pre-fix code) plus a no-op control test.
- **m5 — a Write in a nested repository (a linked worktree, any nested
  clone) read HEAD from the PROJECT ROOT's repo, which never tracks the
  nested path, so it always answered "absent" and misread every write
  there as a genuine flip.** `project_relative_head_text` now resolves
  the FILE's own enclosing repository via `GitRepo.resolve_for` (the same
  `git -C <dir> rev-parse --show-toplevel` this project already
  centralises) and reads HEAD relative to THAT root; a project root that
  is itself a plain checkout is unaffected. Pinned by
  `test_a_file_in_a_nested_repository_reads_from_its_OWN_head` (RED
  against the pre-fix code) in `test_git_facts.py`, which also fixes
  `recovery_cron_advisor`'s Write-path COMPLETION check for the same
  reason (it shares the helper).
- **n3 — `git_facts.py` imported `core.project_context`, breaking its own
  documented "docs QA depends on this module alone" claim.**
  `project_relative_head_text` now takes `project_root` as a plain
  parameter instead — both callers already resolve
  `ProjectContext.project_root()` for other purposes, so nothing is lost.
- **n4 — acknowledged, not changed.** `_is_inside_project` fails open on
  an uninitialised `ProjectContext`; `project_relative_head_text` lets it
  propagate (by design, from the first review pass). Both new M2/M3
  helpers (`_maybe_refresh_on_retirement`, `_maybe_reassert_for_new_session`)
  now follow the SAME unguarded-propagation convention for consistency
  (and because `error_hiding` flagged the None-returning one) — the
  review itself called this "only reachable uninitialised", i.e. never on
  the real dispatch path, so the two conventions differing is intentional
  per the first review's explicit design, not an oversight.
- **n7 — release note 65's title said "already-terminal-status"; In
  Progress is not terminal.** Corrected to match the filename's wording.

`TestStatusFlipDetection`, `TestCombinedGoalSignal`,
`TestNewSessionReassertion`, `TestWriteCompletionIsTransitionBased`,
`TestProjectRelativeHeadText` and the new `GoalLedger` test classes all
pass; 518 tests across every touched handler/utils/core/daemon test file.

**Third review pass (major RV-M1, minors RV-m1 through RV-m5, nits RV-n1
through RV-n3)**: the second pass's M3 re-assert and M2 retraction worked
AGAINST each other — fixed together with an ownership schema change:

- **RV-M1 — `reassert_session`'s single-owner TRANSFER broke retraction the
  moment a second session touched a plan.** Once TEAMMATE reasserted a plan
  LEAD had flipped, `has_live_entry`'s exact `session_id` match stopped
  matching LEAD, so LEAD's own signal could never be retracted again when
  the plan completed — and a pre-existing gap on `main` meant a DIFFERENT
  completing session never retracted the flipping session's stale signal
  either. Fixed by making ownership ADDITIVE: `GoalLedgerEntry` gained a
  `sessions: list[str]` field that `record_emission`/`reassert_session` both
  APPEND to, never overwrite; `has_live_entry` checks membership in
  `sessions`; a new `GoalLedger.owning_sessions(plan_number)` (accepting an
  entry retired a moment ago for `RETIRED_TERMINAL_STATUS` too, subsuming
  RV-m2 below) feeds `_maybe_refresh_on_retirement`, which now refreshes
  EVERY owning session's own combined signal on a terminal write, not just
  whichever session's write triggered the check. Pinned by
  `TestOwnershipSurvivesASecondSession` (single plan, two plans, a second
  session owning a plan it never flipped — all RED against the pre-fix
  code) plus `TestReassertSession`/`TestOwningSessions` in
  `test_goal_ledger.py`.
- **RV-m2 — subsumed by RV-M1's fix.** `owning_sessions`' terminal-status
  grace window (live OR just-retired-as-terminal) means a concurrent
  reconciliation racing between a terminal write landing and this read
  cannot suppress a real owner's retraction.
- **RV-m3 — a SAME-session-id resume (`--resume`/`--continue`) never got
  its `/goal` back**, because the M3 gate (`session_has_entries`) reads the
  PERSISTED ledger, which still "knows" the session from its OWN earlier
  real flip even after its signal FILE was lost across a restart. Fixed
  with a second in-memory latch, `self._reasserted: dict[(session_id, plan_number), bool]`, reset every daemon lifetime and independent of
  `self._fired` — "have I, this process, already confirmed a signal for
  this pair" answers both a genuinely new session id and a same-id resume
  identically. The busy-session contract (a session that already
  real-flipped a DIFFERENT plan must not implicitly absorb an unrelated
  one) still holds via `session_has_entries`, now checked only when the
  session is NOT already a stakeholder of THIS specific plan
  (`has_live_entry`). Pinned by
  `test_same_session_id_after_a_restart_gets_its_signal_rewritten` (RED
  against the pre-fix code).
- **RV-m1 — the m4 reconstruction reversed the FIRST occurrence of
  `new_string`, not necessarily the actual edit site.** A table cell or
  title sharing the same text as the Status VALUE (e.g. "In Progress")
  could reconstruct the wrong span and report a false flip. Fixed:
  `_is_flip_via_reconstruction` now tries every occurrence of `new_string`
  as a candidate, keeps only candidates whose reversal leaves `old_string`
  unique (the Edit tool's own precondition for a non-`replace_all` edit),
  and reports a flip only when every surviving candidate agrees; disagreement
  or no viable candidate reads conservatively as "not a flip".
  `replace_all` has no uniqueness precondition to exploit, so it instead
  requires `old_string` to be ABSENT from the post-edit text (a clean
  application leaves none behind) before reversing every occurrence at
  once — otherwise conservatively "not a flip", the same trade-off as a
  contrived title-collision missed-flip case this review accepted as
  out of scope. **The `replace_all` half was not actually fixed by this**:
  review 3 (RV3-m1, below) found the "absent `old_string`" guard never
  fires on real `replace_all` output (a clean application always removes
  every `old_string`), and both pinning tests used a post-edit fixture no
  Edit tool call could produce. See RV3-m1 for the real fix.
- **RV-n1 — the m6 fix narrative still blamed `pkgutil.walk_packages()`**,
  which already sorts its own directory scan; the real (now fixed) source
  was `HandlerRegistry.register_all`'s two previously-unsorted
  `event_dir.glob("*.py")` passes. Corrected in `claude_md_injector.py`,
  `docs_generator.py`, and both files' test docstrings.
- **RV-n2 — the fail-open convention split flagged by the first review's n4
  was read as unresolved, not intentional.** Unified behind one helper,
  `_open_ledger()`, that every ledger-opening call site in the class now
  goes through. The FIRST fix (this bullet, as originally written) caught
  `RuntimeError` inside `_open_ledger()` itself and returned `None`. The
  coordinator's own review of that fix (niggle N29) found it evaded
  `error_hiding`'s `return-none-on-error` check by assigning the caught
  error to a local read by a later, separate `return` — same behaviour,
  different AST shape. Commit `c40d4ce6` undid that: `_open_ledger()` now
  raises with no `try`/`except` at all, and each caller decides its own
  fail-open action explicitly (see its docstring). `error_hiding`'s
  `log-and-continue` check independently confirmed the two callers with
  nothing substantive to fall back to (`_maybe_refresh_on_retirement`,
  `_maybe_reassert_for_new_session`) cannot legitimately catch-and-log
  either, so both now propagate to `core/chain.py`'s own documented
  per-handler fail-open boundary instead.
- **RV-n3 — no test covered the RV-M1 scenarios or RV-m1's collision case
  (now fixed above); a registry test read the chain's PRIVATE
  `._handlers` list, which only worked because the lazy `.handlers` sort
  had not run yet.** Made the precondition explicit: the test now asserts
  `chain._sorted is False` before reading `._handlers`, so an accidental
  earlier `.handlers` access fails loudly instead of silently passing for
  the wrong reason.

Release note 65 and the module/class docstrings corrected again to
describe the ADDITIVE ownership and per-daemon-lifetime reassert latch
instead of the second pass's (now superseded) single-owner transfer.

**Fourth review pass (major RV3-M1, minors RV3-m1 through RV3-m8, nits
RV3-n1/n3/n4)**, fixed together:

- **RV3-M1 — the retirement refresh was state-based, not transition-based,
  and `owning_sessions` answered from the FIRST ledger entry for a plan
  number, including long-retired ones.** A reopened-and-recompleted plan
  retracted the WRONG (original) session, and any later edit to an
  already-Complete, not-yet-archived plan re-signalled every past owner —
  handing a session a goal for a plan it never touched, or clearing a
  session's own unrelated manual `inject-goal` goal. Fixed on both halves:
  `_maybe_refresh_on_retirement` now shares `_is_real_transition` with the
  flip side (target: a terminal status), gated exactly like N3 already
  gates the flip; `GoalLedger.owning_sessions` answers from the plan's LIVE
  entry when one exists, or else its MOST RECENTLY retired terminal one,
  never the first in the list. Pinned by RED tests for a reopened plan
  completed by a different session, the same with a second unrelated live
  plan, a note on an already-Complete plan, and the same note not clearing
  a manual goal.
- **RV3-m1 — the `replace_all` guard from the third pass never fires on
  real Edit-tool output.** A clean `replace_all` application always removes
  every `old_string`, so the "bail if `old_string` survives" guard was
  vacuous, and the reconstruction blindly reversed EVERY occurrence of
  `new_string` — including an untouched Status line that merely already
  read the same text as a genuinely-replaced table cell. Fixed: when an
  occurrence overlaps the real (non-fenced) Status line AND at least one
  other occurrence exists, two verdicts are compared — reverse everything,
  and reverse everything except the Status line's own occurrence;
  disagreement reads conservatively as "not a flip" (the same accepted
  trade-off the third pass already used elsewhere, now correctly extended
  to also miss a genuine bulk Status-line-plus-cells flip, which cannot be
  told apart from the collision from post-edit text alone). A single
  occurrence with nothing to disambiguate against is answered directly, so
  the ordinary single-site case is untouched. Both third-pass tests
  rewritten to use a REAL post-edit fixture (the pre-edit text with the
  transformation actually applied), plus a two-cell variant and a
  single-occurrence regression control.
- **RV3-m2 — the post-write "is it In Progress now?" check used a
  literal-only regex, disagreeing with the fenced-block-aware, first-line-
  wins `PlanDoc` the pre-write side already used.** A fenced example or a
  per-phase second `**Status**:` line could make an unrelated edit look
  like a flip, or (via the Edit fast path trusting `old_string`'s own
  fragment in isolation) make a per-phase Status line edit look like a
  top-level one. Fixed: `handle()`'s post-state check now uses
  `PlanDoc.parse(plan_text).status`, and the Edit fast path is removed —
  every Edit goes through the same reconstruct-and-compare `PlanDoc.parse`
  machinery the Write side already used, so both sides of the transition
  agree on what "the real Status line" is. A useful side effect: a Status
  line carrying a trailing date qualifier (`In Progress (2026-09-24)`),
  which the old literal regex could never match, is now correctly detected
  too.
- **RV3-m3 — a session whose own combined `/goal` text NAMES a plan it
  does not own is never refreshed when that plan later completes.** The
  combined text lists every live ledgered plan project-wide, but ownership
  only grew through a flip or reassert of THAT specific plan, so a session
  reading a plan's number in its own text could still be carrying a stale
  copy of it forever. Fixed: `_write_combined_signal` now registers its
  session as an owner of every plan its own rendered text just named
  (`_extend_ownership`), not only the one that triggered the write.
  Deliberately NOT applied to the retirement-refresh fan-out (RV3-m5 below
  needs that path's cost bounded by EXISTING owners only).
- **RV3-m4 — the flip path never set the reassert latch, and the latch map
  was unbounded.** The session that just flipped a plan could write a
  second, redundant signal on its own very next non-flip edit in the same
  daemon lifetime (the reassert path's own latch had never been armed),
  and 400 distinct reasserting sessions grew `self._reasserted` without
  bound, unlike `self._fired`'s existing 256-entry FIFO cap. Fixed: the
  flip path now sets both latches on a confirmed write, and `_record_latch`
  is a single bounded-insert helper shared by both maps.
- **RV3-m5 — plan ownership grew without bound, and refreshing many owners
  re-derived the combined text once PER owner.** 150 teammate sessions
  touching one live plan gave 151 owners with nothing pruning `sessions`,
  and completing that plan took 0.25s (a full live-plan-directory read per
  owner) against 0.003s on main. Fixed: `GoalLedgerEntry.sessions` is
  capped (`_add_owner`, FIFO-drops the oldest owner past the cap), and
  `_maybe_refresh_on_retirement` renders the combined payload ONCE
  (`_render_combined`) and writes it to every owner, rather than
  recomputing it per owner.
- **RV3-m6 — the Write path still fired on an already-In-Progress plan
  that was not yet committed as such.** git HEAD lagging an uncommitted
  flip meant a teammate's plain Write to an already-live plan could be
  misread as a fresh flip, wrongly re-emitting a ledger record and
  displacing another live plan. Fixed: for a Write only (Edit reads its
  own before/after span directly, immune to this race), a positive
  transition verdict is narrowed further by `_ledger_plan_is_live` — the
  ledger, not HEAD, is authoritative for whether a plan has already
  started.
- **RV3-m7 — documentation drift**, all corrected: the third pass's RV-n2
  bullet still described the round-1 catch-and-log helper after `c40d4ce6`
  reverted it to a propagating raise; two mentions of a
  `_session_ledgered_plan` method that was never actually named that; the
  RV-m1 bullet's "pinned by two RED tests" claim for `replace_all` (see
  RV3-m1 above); release note 65's three over-claims (see the note itself).
  This entry's status is held at 🔄 until this pass lands.
- **RV3-m8 — a non-UTF-8 PLAN.md of any LIVE ledgered plan crashed the
  handler, on more paths than the ledger-file case review RV-m5 already
  fixed.** `goal_ledger.py`'s `_plan_state` and `_find_plan_md_text` (used
  by reconciliation and by rendering the combined text respectively), and
  `goal_injection.py`'s own `_read_plan`, each caught only `OSError`.
  Under `strict_mode` (this repo), an unrelated plan's bad bytes turned a
  routine reassert or refresh into a blocking "SYSTEM ERROR" for the
  handler's whole PostToolUse chain. Fixed: all three now also catch
  `ValueError` (covers `read_text`'s `UnicodeDecodeError`), treating the
  plan as unreadable rather than crashing — matching RV-m5's existing
  tolerance for the ledger file itself.
- **RV3-n1 — held for a follow-up, not code changed.** `c40d4ce6`'s
  propagating `_open_ledger()` is correct; the failure it exposes (a
  `RuntimeError` reaching a real dispatch) cannot happen in a real daemon,
  since the controller initialises `ProjectContext` before
  `register_all`. The one true gap this nit found — the docstrings not
  mentioning that `strict_mode` also STOPS the rest of the PostToolUse
  chain, not just denies — is now documented in `_open_ledger`'s
  docstring.
- **RV3-n3 — review-round narration trimmed from code comments and
  docstrings** (the module docstring, `_open_ledger`'s docstring, and the
  `docs_generator.py`/`claude_md_injector.py` `pkgutil` asides) to describe
  current state; the module docstring now points at this file for full
  history instead of citing review labels inline. This pass was
  incomplete — the method-level docstrings still narrated before/after
  comparisons; see RV4-n1 below.
- **RV4-n1 — the RV3-n3 trim was incomplete: method docstrings still
  narrated before/after comparisons.** Fixed the three the report cited:
  `goal_injection.py`'s `_maybe_refresh_on_retirement` docstring dropped
  the "measured at 0.25s … against 0.003s on main" benchmark comparison
  in favour of the current-state perf rationale it was making;
  `goal_ledger.py`'s `GoalLedgerEntry`/`reassert_session` docstrings
  reworded "the pre-fix shape … broke/let" into a present-tense "a
  transfer would break …" hypothetical; `session_has_entries`'s docstring
  dropped "the previous implementation read" in favour of stating
  directly what the per-entry field does not mean. Rationale comments
  that explain WHY an invariant exists by naming the review finding that
  motivated it (e.g. `RV4-M1: protect names …`) are kept — that is the
  sanctioned rationale pattern, not the narration this nit targets.
- **RV3-n4 — the committed CLAUDE.md block was main's handler order, not
  this branch's own code's order** (last written by a main merge, one
  restart away from a spurious reorder commit). Regenerated by a daemon
  restart before this pass's commit.
- **RV3-n5 — fixed via a PreToolUse ground-truth snapshot, not another
  inference patch.** A value-only real flip missed when "In Progress" also
  appears as a table cell or a plan title (C3b, m4d's C3) was genuinely
  indistinguishable from the Edit payload alone — no amount of layering on
  `_is_transition_via_reconstruction` could resolve it, since the two
  candidate pre-edit texts really do parse to different verdicts. Fixed by
  removing the need to infer anything in the common case: a new PreToolUse
  handler, `plan_status_snapshot`, runs immediately before the SAME
  Write/Edit `goal_injection` sees after it lands, reads the plan's
  CURRENT (pre-write) status straight off disk, and records it in a
  bounded, TTL'd (`utils/plan_status_snapshot.py`) in-memory store keyed by
  `tool_use_id` (carried by both the PreToolUse and PostToolUse payloads
  for the same call). `goal_injection`'s new `_resolve_transition` consumes
  it as ground truth — no reconstruction, no collision possible. The old
  inference (`_is_real_transition` and everything it calls) is KEPT as the
  fallback for the narrow window where no snapshot exists (a daemon
  restart between the two dispatches, or a payload with no `tool_use_id`),
  and that fallback path is logged when taken. RV3-m6's `_ledger_plan_is_live`
  narrowing is scoped to apply ONLY on the fallback path now: a
  snapshot-backed verdict already read the plan's true pre-write status off
  disk, so the git-HEAD race it guards against cannot have occurred. Both
  handlers share one trigger-matching implementation
  (`utils/plan_trigger.py`) so they cannot silently disagree about what
  counts as "the trigger" the snapshot was recorded for. New tests:
  `TestGroundTruthSnapshotResolution` in `test_goal_injection.py` (C3b,
  m4d's C3, a restart-fallback pair, and an empty-`tool_use_id` case),
  `test_plan_status_snapshot.py`, `test_plan_trigger.py`, and
  `tests/unit/handlers/pre_tool_use/test_plan_status_snapshot.py`. Both
  `_read_plan` sites (`goal_injection.py`, `plan_status_snapshot.py`) raise
  a shared `PlanUnreadable` (`utils/plan_trigger.py`) instead of returning
  `None` on a read/decode failure — a missing file is checked BEFORE the
  `try` (not an error; the ordinary brand-new-plan case), so nothing
  inside either function's `except` block ever returns `None`. Each single
  caller catches `PlanUnreadable` explicitly, logs a WARNING naming the
  path and cause, and takes its own documented fail-open branch. This
  replaces the error_hiding exclusion both functions carried; there is no
  exclusion for either any more.
- **RV3-n2 — `session_has_entries` now tracks what its name says, and the
  B4 decision is pinned here.** `record_emission` overwrites an entry's
  single `session_id` field with whoever re-emits for the SAME plan next,
  and `_prune` can drop the entry out of the ledger entirely — either one
  silently lost the "this session once recorded a real emission" fact the
  method's own docstring claimed to answer. Fixed: a ledger-wide, bounded,
  order-preserving `ever_recorded_sessions` list (`_EVER_RECORDED_KEY`),
  populated ONLY by `record_emission` (both the new-entry and re-emission
  branches) and read/persisted through the SAME locked read-modify-write
  every other mutator already uses — it survives both the field overwrite
  and pruning, because it is no longer derived from either. Deliberately
  NOT populated by `reassert_session`: a session that has only ever been
  ADDED to a plan's ownership (never performed a real emission itself)
  must still read as having no entries of its own, so it correctly remains
  free to become a stakeholder of a second, unrelated live plan it is
  asked to track too (Plan 00269's own motivating case, still pinned by
  `TestOwnershipSurvivesASecondSession` in `test_goal_injection.py`).
  **B4 decision (accepted by team-lead, review-4-prep):** review 3's own
  worked example for B4 ("T becomes an owner of 00298") is
  `_extend_ownership`'s (RV3-m3) project-wide combined-signal side effect
  — the combined `/goal` text is global, so absorption only decides WHO IS
  REFRESHED when a plan retires, not who owns what in any sense that needs
  gating. `session_has_entries` is a SEPARATE, narrower question ("has
  this session ever performed a real emission"), and `_extend_ownership`
  is left untouched — this pass did not restrict it further. **Updated by
  RV4-M1:** that premise held only up to the RV3-m5 owner cap, which
  absorption could push the FLIPPING session itself past — evicting the
  one session that most needs its own signal refreshed when the plan it
  started completes (main never had this bug; the cap introduced it once
  combined with absorption). Fixed by pinning the flipper as the entry's
  `primary_owner`, exempt from the cap; absorbed (non-flipping) owners are
  still FIFO-capped exactly as B4 already decided. `session_has_entries`
  and `_extend_ownership` are otherwise unchanged by this. Backing
  `GoalLedger`-level tests: `TestSessionHasEntries` in `test_goal_ledger.py`
  (`test_survives_session_id_overwrite_by_a_different_re_emitting_session`,
  `test_survives_pruning_past_the_entry_cap`,
  `test_false_for_a_reassert_only_session`). `_load_raw` raises a shared
  `LedgerUnreadable` (`utils/goal_ledger.py`) instead of returning `None`
  on a genuine read/parse failure — a missing file (nothing written yet)
  is checked BEFORE the `try`, not an error. Every one of its five public
  callers (`entries`, `record_emission`, `reassert_session`,
  `live_plan_numbers`, `session_has_entries`) catches it explicitly, logs
  its OWN WARNING naming the path, cause, and which fail-open branch it is
  taking, rather than sharing one central catch-and-log. This replaces the
  error_hiding exclusion `_load_raw` carried; there is no exclusion for it
  any more. New tests: `TestUnreadableLedgerRaisesADomainException` in
  `test_goal_ledger.py`.

New tests: `TestOwnershipSurvivesASecondSession`-adjacent scenarios in
`test_goal_injection.py` (`TestReview3Fixes`, inheriting the
`TestNewSessionReassertion` fixture plumbing), new `replace_all`/fenced-
Status/uncommitted-Write cases in `TestStatusFlipDetection`, and new
`GoalLedger` test classes (`TestOwningSessionsAfterReopen`, `TestIsPlanLive`,
`TestNonUtf8PlanMd`) plus a `line_spans_outside_fences` primitive and its
tests in `utils/markdown_fences.py`.

**Fifth review pass (major RV4-M1, minors RV4-m1 through RV4-m7, nits
RV4-n1 through RV4-n7)**, fixed together (report:
`subagent-reports/260924-n466-goalflip-review4-opus-5-5.md`):

- **RV4-M1 — see the B4 decision update above:** the RV3-m5 owner cap
  combined with RV3-m3's absorption could evict the flipping session from
  its own plan's owner set once enough OTHER sessions touched any live
  plan it also named, so completing the plan never refreshed the
  flipper's own `/goal`. Fixed by pinning the flipper as the entry's
  `primary_owner` (never reassigned, exempt from the cap via a `protect`
  parameter threaded through `_add_bounded`), and by always including the
  completing write's own `session_id` in the refresh set regardless of
  what the ledger's owner set says. Pinned by
  `test_flipper_survives_absorption_past_the_owner_cap` (50-teammate
  absorption, `probe_gf4_evict2.py`'s E2) and
  `test_completing_session_is_refreshed_even_if_the_ledger_names_no_owner`
  in `TestReview4Fixes` (`test_goal_injection.py`).
- **RV4-m1 — the snapshot store's dict was mutated and iterated across
  threads with no lock.** The daemon dispatches every hook event through
  a `ThreadPoolExecutor`, and `record`'s eviction racing `consume`'s
  iteration raised `RuntimeError`/`KeyError` under real concurrency.
  Fixed: `PlanStatusSnapshotStore` now holds a `threading.Lock` around
  every mutation and iteration, matching `utils/config_cache.py`'s
  existing pattern. Pinned by a 4-thread stress test in
  `TestConcurrency` (`test_plan_status_snapshot.py`), confirmed RED
  (raised on 3/3 runs) before the lock and GREEN (3/3) after.
- **RV4-m2 — a snapshot could be stale by the time its own write landed.**
  PreToolUse runs before the permission prompt, which can precede the
  write by minutes; another session's write landing in that gap left the
  snapshot describing a file that no longer existed in that form. Fixed:
  `PlanStatusSnapshot` now carries a content hash (`hash_plan_text`) of
  the text it read; for a non-`replace_all` Edit, `_snapshot_is_fresh`
  reconstructs the candidate pre-edit text(s) and requires an exact hash
  match; a `replace_all` Edit or a Write cannot be reconstructed
  unambiguously (a collision can reverse an unrelated site too — the same
  shape RV3-m1 already works around at the verdict level, which does not
  extend to exact byte reconstruction), so those fall back to a
  `_SNAPSHOT_RECENCY_BOUND_SECONDS` (5s) staleness bound instead. On a
  stale snapshot, it is discarded and the existing inference fallback
  runs, logged as a distinct WARNING from the "no snapshot" case. Pinned
  by a race test modelling `probe_gf4_race.py`'s F3 (three plans; a
  second session's later flip of one must not let a first session's
  stale-snapshot-driven tick erase a THIRD plan's own displacement).
- **RV4-m3 — an `EACCES` (or other `OSError`) from the existence
  pre-check itself escaped as a raw, unwrapped exception**, in both
  `goal_ledger.py`'s `_load_raw` and `plan_status_snapshot.py` (the
  PreToolUse handler)'s `_read_plan`: the `is_file()` check ran BEFORE
  the `try`, so an unreadable parent directory or `ENAMETOOLONG` bypassed
  the domain-exception wrapping entirely. Fixed: the existence check now
  runs INSIDE the `try` — `return None` there sits in the try body, not
  an except handler, so it is not the shape `audit_error_hiding.py`
  flags — and every other `OSError` (including from `is_file()` itself)
  is caught and wrapped as the domain exception (`LedgerUnreadable`,
  `PlanUnreadable`) with a WARNING at the caller. Pinned by a
  permission-denied-file test in each affected test file, monkeypatching
  `Path.is_file` to raise `PermissionError`.
- **RV4-m4 — nothing told an operator that `goal_injection`'s
  ground-truth snapshot path needs `plan_status_snapshot` enabled.** The
  handler shipped opt-in (disabled by default), so a fresh install ran on
  inference alone with no signal that the ground-truth path was even
  available. `Handler.depends_on` looked like the natural coupling
  mechanism but has zero consumers anywhere in `src/` — not a real
  option. Fixed the simpler way team-lead offered: `get_default_enabled()`
  flipped from `False` to `True` (opt-out), with the docstring, the
  generated-config template (`daemon/init_config.py`), and the upgrade
  reference config (`.claude/hooks-daemon.yaml.example`) all updated to
  match — three independent sources of truth for one handler's default,
  each with its own drift-guard test
  (`test_default_enabled_template_consistency.py`,
  `test_reference_config_completeness.py`), both of which were ALREADY
  failing before this pass touched anything (the handler was never
  registered in either).
- **RV4-m5 — two gaps in what review 3's own fixes were pinned against.**
  (1) `test_task_tick_on_a_not_started_plan_with_a_fenced_status_example_ stays_silent` (C7b) and the phase-2 collision test (C8) carried
  PRE-edit fixture content, but PostToolUse dispatches AFTER the tool has
  already landed the edit — the fixture defect masked the very collision
  the tests exist to catch. Fixed the fixtures to hold POST-edit content.
  (2) the RV3-m2 fix itself (`handle()`'s `PlanDoc.parse(plan_text).status`
  gate, not a literal `'**Status**: In Progress' in plan_text` check) had
  no direct mutation-testing pin — `probe_gf4_mutate.py` confirmed the
  suite stayed GREEN under that exact literal-substring mutant. Fixed by
  adding `test_terminal_transition_ignores_a_fenced_in_progress_example_ in_the_post_edit_text` to `TestReview4Fixes`, using a recorded
  pre-write snapshot (ground truth, RV3-n5) to isolate the OUTER
  post-write gate from the unrelated INNER reconstruction-uniqueness
  filter a byte-identical fenced collision would otherwise also trip.
  Confirmed RED against the literal mutant, GREEN against HEAD.
- **RV4-m6 — the daemon needed an actual restart and doc regeneration in
  THIS pass, not a stale claim that a previous pass already did it.** Ran
  `bin/hooks-daemon restart` then `bin/hooks-daemon regenerate-docs`;
  `CLAUDE.md` was already correct (no diff) at this point. **Correction
  (this claim was wrong when first written):** `.claude/HOOKS-DAEMON.md`
  was NOT already correct — the full-suite fallout later in this same
  pass (`test_real_repository_handler_doc_is_fresh`, below) found it
  still missing `plan_status_snapshot`'s row and handler count, because
  `regenerate-docs` here talks to the already-running daemon's in-memory
  handler registry rather than a fresh reimport. A plain
  `bin/hooks-daemon generate-docs` afterwards is what actually fixed it.
  The claim in RV3-n4 above is genuinely true only as of that later step,
  not this one.
- **RV4-m7 — documentation drift, corrected:** `HANDLER_REFERENCE.md`'s
  `goal_injection` entry described the OLD state-based trigger
  ("STATE-based … not transition-based") contradicting what N3 actually
  does; reworded to TRANSITION-based with the new-session-reassert
  exception named explicitly. `goal_injection.py`'s `_is_real_transition`
  docstring still described a removed "`old_string` FIRST witness, used
  DIRECTLY" fast path (RV3-m2 removed it); reworded to describe only the
  current always-reconstruct behaviour. `get_claude_md()`'s "every
  session ever handed a plan's goal keeps its own claim" was an overclaim
  past the owner cap even before RV4-M1; reworded to describe the
  pinned-primary-owner/FIFO-capped-absorbed-owners model precisely.
  Release note 65 updated: the terminal-drop claim now names the
  completing session's own guaranteed inclusion; the cap description now
  names the primary-owner exemption; the "can no longer be misread either
  way" claim is now scoped to "while that snapshot is trusted", with the
  staleness fallback named; the closing line now conditions "no action
  needed" on `plan_status_snapshot`'s default-enabled state rather than
  asserting it unconditionally. `auto_continue_stop`'s existing
  "Fail-open: a missing or unreadable ledger" claim (`HANDLER_REFERENCE.md`
  line ~3662) was re-verified rather than reworded — `live_plan_numbers`
  already catches `LedgerUnreadable` explicitly. **Correction (this claim
  was wrong when first written): RV4-m3 did NOT make that catch complete.**
  It fixed only `_load_raw`'s own existence check; `_plan_state` and
  `_find_plan_md_text` — `live_plan_numbers`' own siblings, reached via
  `_reconcile` on every call — kept a raw `PLAN.md.is_file()` outside
  their try, so an `EACCES` on a search-denied plan folder still escaped
  `live_plan_numbers` unwrapped. Not fixed until RV5-m6 below (see
  review-5's entry). `PLAN.md`'s N3 row, shown as ✅ Remedied, corrected
  back to 🔄 In progress per team-lead's standing instruction that it
  stays there until merged.
- **RV4-n1 — see above** (folded into the RV3-n3 entry it follows
  directly, for locality with what it corrects).
- **RV4-n2 — `GoalInjectionHandler.matches()`/`handle()` re-implemented
  `matched_plan_write_or_edit` instead of calling it**, duplicating the
  tool-name/path/`Completed`/project-membership checks `utils/plan_trigger.py`
  already centralises for both handlers (its own module docstring claimed
  they were shared, when only `plan_status_snapshot` actually called it).
  Fixed: both methods now delegate to `matched_plan_write_or_edit`
  directly, which made `_plan_path_pattern()`, `_is_inside_project()` and
  `_COMPLETED_SEGMENT` genuinely dead code — removed along with their
  now-unused imports.
- **RV4-n3 — `record_emission`'s `LedgerUnreadable` warning did not say
  the save about to happen OVERWRITES the unreadable file.** For a
  transient `OSError` (as opposed to corrupt JSON), this silently
  destroys every live entry and `ever_recorded_sessions`. Fixed: the log
  message now says so explicitly.
- **RV4-n4 — `test_goal_injection.py` and `test_recovery_cron_advisor.py`
  each added their own copy of `test_git_facts.py`'s `_git` helper, each
  with its own `# nosec B603 B607` suppression** — two new suppressions
  reviewing the same trusted-subprocess-call shape a third file already
  carried. Fixed: extracted the ONE helper (`run_git`) to
  `tests/support/git_fixtures.py` (a new `tests/support/` package,
  outside the daemon's own `src/`), with a single suppression; all three
  test files now `from tests.support.git_fixtures import run_git as _git`
  instead of defining their own copy.
- **RV4-n5 — `TestOwnershipSurvivesASecondSession`, `TestResumedSameSessionReassertion`
  and `TestReview3Fixes` each SUBCLASSED `TestNewSessionReassertion` to
  reuse its fixtures, so pytest collected and RE-RAN its tests once per
  subclass too** (108 `def test_` methods, 117 collected). Fixed:
  extracted the shared fixture plumbing into `_ReassertionFixtures` (a
  leading underscore keeps it out of pytest's `Test*` collection), and
  every class above now inherits ONLY the fixtures, not each other's test
  methods.
- **RV4-n6 — docstrings asserted unconditionally that this repo's
  `strict_mode` DENIES**, contradicting N24 (`strict_mode` never reaches
  the live daemon, so it is inert in every install including this one).
  Fixed in `goal_ledger.py`'s `_load_raw` and `goal_injection.py`'s
  `_open_ledger` docstrings: both now state that the config DECLARES
  `strict_mode: true` while noting, citing N24, that the setting does not
  currently reach the live daemon, so the fail-open branch is what
  actually runs.
- **RV4-n7 — a symlink-loop `PLAN.md` raised `RuntimeError` from
  `is_inside_project`'s `resolve()` call** (`utils/plan_trigger.py`,
  copied from `goal_injection`'s pre-existing shape) instead of being
  treated as "not inside the project". Fixed: `RuntimeError` added
  alongside `ValueError`/`OSError` in the except tuple. Pinned by
  `test_symlink_loop_never_raises` in `TestIsInsideProject`
  (`test_plan_trigger.py`), confirmed RED (raw `RuntimeError` propagated)
  before the fix.

**Full-suite fallout from RV4-m3/m4, found by a whole-tree run after the
fifth pass above and fixed together (none of these were in the review-4
report itself):**

- **`eacces_safe_predicates_static_check` flagged RV4-m3's own fix.**
  `plan_status_snapshot.py`'s (PreToolUse handler) raw `is_file` predicate
  is exactly the shape that checker exists to catch, regardless of the
  `except OSError` one line below it -- it is a pure regex over the
  source text, not a flow analysis, so it also matched the SAME method's
  own docstring prose describing the predicate. Fixed: the existence
  check now goes through `utils.path_predicates.path_is_file(path, unreadable_means=True)`; on a stat failure this assumes "yes, try to
  read it" rather than silently answering `False`, so an EACCES does not
  vanish -- it reaches the SAME read attempt immediately after, which
  hits the identical permission error and is what the method's own
  `except` still converts to `PlanUnreadable`. The docstring's prose
  mention of the predicate reworded to not contain the literal
  `.is_file()` substring the checker also matches. The RED/GREEN
  permission-denied test updated to patch `Path.read_text` alongside
  `Path.is_file` -- patching only the stat call no longer reproduces the
  failure now that the stat alone does not stop the method.
- **`test_no_handler_is_unclassified` had no `get_claude_md()` verdict
  for `PlanStatusSnapshotHandler`.** It does return guidance text (not
  `None`), so it needed a `_EARNS_GUIDANCE` entry, not an exempt one.
  Added, alongside fixing that handler's own docstring/`get_claude_md()`
  text still saying "ships disabled" after RV4-m4 flipped the default.
- **`test_no_undeclared_module_imports_plan_qa` flagged
  `utils/plan_status_snapshot.py -> plan_qa.model`.** The SAME import
  `utils/goal_ledger.py` already carries, for the same reason (reading a
  plan's status via `PlanDoc`/`PlanStatus`) and already declared in that
  test's `_KNOWN_EDGES` allowlist. Declared alongside it with the same
  rationale, rather than treated as a new design question.
- **`test_real_repository_handler_doc_is_fresh` found `.claude/HOOKS- DAEMON.md` still missing `plan_status_snapshot`'s row and the handler
  count.** The RV4-m6 `regenerate-docs` run earlier in this pass did not
  pick this up (talks to the already-running daemon's in-memory handler
  registry, not a fresh reimport); a plain `bin/hooks-daemon generate-docs`
  run afterwards did. Regenerated again; committed alongside this pass.

**Fifth review pass (review-5, `260925-goal-flip-review5-opus-5-5.md`) — 3
majors, 6 minors, 5 nits, all fixed with a RED test first for each:**

- **RV5-M1 — the RV4-M1 fix was itself a NEW regression against main.**
  `_maybe_refresh_on_retirement`'s unconditional `if session_id and session_id not in owners: owners = [*owners, session_id]` handed a
  `/goal` to a session that never owned the completing plan (K1: a
  non-owner teammate ticking a Plan Completion Checklist box got a goal
  for an unrelated live plan, PERMANENTLY — nothing later retracts it),
  and could WIPE a session's own manually-injected goal (K2: `inject-goal 00400` cleared by an unrelated plan's completion). Fixed: removed the
  unconditional add entirely — only an owner the ledger already names is
  refreshed. `primary_owner` pinning (RV4-M1) alone still fixes the
  original E2 scenario (the flipper survives absorption past the owner
  cap); nothing else was needed for that case. Pinned by
  `test_a_non_owner_completer_gets_no_goal` and
  `test_a_manual_goal_survives_an_unrelated_plans_completion`
  (`test_goal_injection.py`), both confirmed RED against the reverted
  unconditional-add line before the fix.
- **RV5-m4 (paired with RV5-M1) — the retirement-refresh fan-out never
  registered a refreshed owner as an OWNER of the other plans its own
  freshly rewritten text named.** So a session refreshed by one plan's
  retirement, whose combined text now names a SECOND still-live plan,
  never got retracted when THAT plan later completed (K4) — the fan-out
  path never applied RV3-m3's `_extend_ownership` the flip path already
  has. Fixed: `GoalLedger.add_owners(sessions, plan_numbers)`, a new
  BATCHED method registering every refreshed owner as an owner of every
  plan its combined text names, under ONE lock/save (not
  `len(sessions)*len(plans)` individual `reassert_session` calls).
  Pinned by
  `test_a_retirement_refreshed_owner_becomes_an_owner_of_the_plans_its_text_names`,
  confirmed RED with the `add_owners` call temporarily disabled.
- **RV5-M2 — the RV4-m2 5 s recency bound was fundamentally broken, in
  both directions.** PreToolUse runs BEFORE Claude Code's permission
  prompt, so ANY prompt a person takes longer than 5 s to answer made a
  genuinely-correct snapshot look "stale" and fall back to inference —
  reproducing N3's original bug (T1: a real `replace_all` flip missed
  after 6 s; T3/T4: a Write misread after 6 s). A BACKWARD clock step
  (T5) had the opposite failure: it could make an arbitrarily stale
  snapshot look fresh. Fixed by removing the time bound ENTIRELY —
  team-lead's own instruction, over the review report's softer "use
  `time.monotonic()`" suggestion: the store's orphan-eviction is now
  bounded purely by entry count (`_MAX_ENTRIES=256`, FIFO on a full
  store), never by a clock of either kind, which also resolves T5 as a
  side effect (no clock logic left to exploit). Freshness itself is now a
  pure hash comparison: the Pre handler PREDICTS the post-write text by
  applying the same Write/Edit FORWARD to the pre-write text it just read
  (reusing the existing shared `would_be_content` helper, already used by
  three other handlers, rather than inventing a parallel
  implementation), records the hash of that prediction; the Post handler
  hashes the REAL post-edit text and compares directly — no
  reconstruction, no clock, and it handles a deletion Edit (T7,
  `new_string=""`) uniformly, which the OLD reverse-reconstruction design
  could not (`_reconstruct_pre_edit_candidates` returned `[]` for it).
  **Correction (RV6-m2): "uniformly" here is about needing no
  reconstruction for any tool shape, not about detecting every race
  uniformly.** For a Write the predicted image is the write's own
  `content` field, independent of the pre-write text, so the freshness
  check can only ever catch a LATER write landing on the file before this
  one's own Post dispatch runs — it is blind to an EARLIER write that
  changed the plan's status between the Pre snapshot and this Write
  landing (probe W1). An Edit's prediction is built from its own
  before/after span, so the same race IS caught for it (probe W1e). Stated
  explicitly now in `_snapshot_is_fresh`'s own docstring and release note
  13, per the review's Direction.
  `PlanStatusSnapshot.text_hash`/`recorded_at` renamed/removed to
  `predicted_post_hash`; `PlanStatusSnapshotStore`'s `ttl_seconds`
  constructor param and `TestTtlExpiry` removed outright (the whole
  premise is gone). New tests:
  `test_snapshot_freshness_never_consults_the_clock` (the "bound never
  expires" mutant's kill — confirmed RED by temporarily reinserting a
  `time.time()` call into `_snapshot_is_fresh`, then reverted),
  `test_t1_replace_all_bulk_flip_survives_an_arbitrary_pre_post_gap`,
  `test_t3_write_with_unchanged_status_is_not_a_flip`,
  `test_t4_write_reopening_a_complete_plan_is_a_genuine_flip`,
  `test_t7_deletion_edit_is_resolved_by_the_snapshot` (all in
  `test_goal_injection.py`). RV5-m5's test-gap items folded in here: the
  RV3-m2 pin test's `old_string` was non-unique in its own pre-image (the
  real Status line and a fenced example both read
  `**Status**: In Progress`) — a real Edit tool call with that shape is
  REJECTED before this handler ever sees it — rewritten to use a unique
  `old_string` so it genuinely exercises the hash path instead of an
  Edit call that could never happen.
- **RV5-M3 — the `_KNOWN_EDGES` entry this pass's own prior session added
  for `utils/plan_status_snapshot.py -> plan_qa.model` was itself a NEW
  ratchet violation** (`test_qa_package_dependency_direction.py`'s
  allowlist: "Shrink this list when one goes; never grow it to make a
  new edge pass"). Unlike `goal_ledger.py`'s grandfathered entry (predates
  the ratchet, does REAL `PlanDoc` parsing), `plan_status_snapshot.py`
  only imported `PlanStatus` to annotate a dataclass field — no plan-text
  parsing of its own. Fixed per team-lead's simplification of the
  report's three options ("store `status.value` as a plain string, or
  make the store generic; do not move the module"): `PlanStatusSnapshot. status` is now a plain `str | None` (the status VALUE, not the enum);
  the Pre handler converts at its own boundary (`status.value`),
  `goal_injection` rehydrates at its own boundary (`PlanStatus(value)`)
  — both of those modules already import `plan_qa.model` for other
  reasons and sit outside the ratcheted `utils`/`docs_qa` trees, so the
  import moves to where it was always legitimate. The `_KNOWN_EDGES`
  entry and its module docstring's "six ... five that remain" count
  corrected to match.
- **RV5-m1 — `plan_status_snapshot`'s "harmless when goal_injection is
  off" claim was false.** `get_relevance()` is NOT a runtime gate — its
  only caller is `daemon/cli.py`'s `optimise` command (the
  config-optimisation REVIEW), never real dispatch, and `matches()`
  doesn't consult it either. So the handler genuinely runs (a file read,
  a `PlanDoc.parse`, a SHA-256 hash) on EVERY active plan's `PLAN.md`
  write in EVERY client where it is enabled (the shipped default),
  whether or not `goal_injection` is enabled and whether or not a ccy
  supervisor is armed. No existing primitive in this codebase lets one
  handler read another's resolved enabled-state at runtime (`Handler. depends_on` is stored but has zero consumers anywhere in `src/` — not a
  real option, confirmed by grep), so building genuine cross-handler
  gating would be a much larger architecture change than a minor finding
  warrants. Took team-lead's explicit alternative instead: corrected the
  module docstring and `get_claude_md()` to state the true, unconditional
  cost plainly, and to drop the stale "TTL'd" description (RV5-M2 removed
  the TTL — RV6-n1 found the phrase had survived in two OTHER spots this
  pass missed, `plan_status_snapshot.py:13` and its acceptance-test
  `safety_notes`; both fixed now).
  **Correction (RV6-m1): the "no existing primitive" claim above was
  wrong.** Five handlers already read a resolved config at runtime via
  `utils.config_cache.load_config_cached` (`recovery_cron_advisor.py`,
  `cron_stop_enforcer.py`, `cron_subagent_stop_enforcer.py`,
  `failsafe_cron_session_advisor.py`, `remote_docs_routing.py`), and the
  registry's own `handlers.registry.config_skip_reason` decides "enabled"
  from exactly that with a one-line rule. `Handler.depends_on` genuinely
  has zero consumers, as stated — that just was not the only route, and a
  smaller one existed. Fixed properly instead of documented: `matches()`
  is now gated on `goal_injection`'s resolved `enabled` state
  (`PlanStatusSnapshotHandler._goal_injection_enabled`), with an ABSENT
  block resolving to `goal_injection`'s OWN opt-in default (`False`), not
  `config_skip_reason`'s generic "absent means enabled" convention (which
  is tuned for the common opt-out handler shape). Pinned by
  `TestGoalInjectionGate` in `test_plan_status_snapshot.py`.
- **RV5-m2 — registration docs were missing.** Added
  `handlers.pre_tool_use.plan_status_snapshot` to
  `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.67.0.yaml` and a full
  entry plus summary-table row to `docs/guides/HANDLER_REFERENCE.md`
  (RV4-m4 already asked for the latter and it was never done).
  `check_handler_reference.py`, `check_generated_doc_drift.py` and
  `check_doc_truth.py` all still pass after adding these.
- **RV5-m3/K3 — a resumed lead under a NEW session id is still
  evictable, and the release note over-claimed otherwise.** The
  `primary_owner` pin (RV4-M1) protects only the ORIGINAL flipping
  session's id; a lead that resumes under a genuinely different id and
  reasserts ownership is an absorbed owner like any other, subject to the
  same FIFO cap as 50 teammates ticking a box. Team-lead's own fallback
  instruction: "Fix it if the payload gives you a stable link... If there
  is truly no signal, correct the release note... and record the
  reasoning in NIGGLES." **Researched and confirmed no such signal
  exists**: grepped this codebase for any existing session-lineage
  concept (`parent_session_id`, `previous_session_id`, `lineage`,
  `resumed_from`, `prior_session`, `session_lineage`) — none found.
  Checked the vendored `hooks.md` docs for any hook-payload field linking
  a resumed session's new id back to an old one — PostToolUse carries
  only `session_id` and `transcript_path`; no parent/previous-session
  field is documented anywhere. So there is genuinely nothing to key a
  fix on without fabricating a link the daemon cannot verify — a fix here
  would be a guess dressed as a fix. Corrected release note 65's "can
  never evict the one session that most needs its own signal refreshed"
  claim to name this limitation precisely (the pin is keyed on the
  flipping session's OWN id, not a resumed one), rather than either
  silently leaving the over-claim or inventing an unreliable fix.
- **RV5-m5 — see RV5-M2 above** (the RV3-m2 pin rewrite folded in
  there); the second half, "kill the `primary_owner` reassignment
  mutant" (`goal_ledger.py`'s `record_emission` re-emission branch
  handing `primary_owner` to the re-emitter), addressed separately — see
  the dedicated entry below.
- **RV5-m6 — doc over-claims, several distinct ones, each corrected
  where found rather than in one place:** (1) release note 65's snapshot
  match-check description updated for RV5-M2's forward-prediction design
  (was: "a content hash of the text it read"; now: "a content hash of
  the text it PREDICTS ... will produce", with the no-time-bound
  behaviour stated explicitly). (2) release note 65's terminal-drop
  bullet reworded to drop RV4-M1's now-REMOVED "including the completing
  session itself, always, even ... the ledger's own owner set does not
  (yet) name it" claim (RV5-M1 removed that behaviour) and to describe
  RV5-m4's batched cross-plan ownership instead. (3) release note 65's
  cap description corrected per RV5-m3/K3 above. (4) `NIGGLES.md`'s own
  RV4-m3/RV4-m7 entries corrected in place, above — see the two
  "Correction (this claim was wrong when first written)" notes. (5)
  `plan_status_snapshot.py`'s "harmless" claim — see RV5-m1 above. Also
  fixed as part of this item, the actual `EACCES` gap the RV4-m7 entry's
  false claim had papered over: `goal_ledger.py`'s `_plan_state` and
  `_find_plan_md_text` kept a raw `PLAN.md.is_file()` outside their own
  try (RV4-m3 fixed only `_load_raw`'s equivalent) — a live ledgered
  plan whose folder denies search escaped `live_plan_numbers` as a raw,
  unwrapped `PermissionError`. Fixed with the same
  `path_is_file(unreadable_means=True)` pattern RV4-m3 established;
  pinned by
  `test_live_plan_numbers_does_not_raise_on_eacces_from_plan_md_is_file`,
  confirmed RED against a reverted raw `is_file()` call.
- **RV5-n1 — the consolidated `# nosec` at `tests/support/git_fixtures. py:17` suppresses NOTHING** (bandit only scans `src/`, never `tests/`
  — confirmed via `scripts/qa/run_security_check.sh`/`pyproject.toml`),
  so it was inert in all three OLD per-file locations too, before RV4-n4
  consolidated them. Net change vs main is 3→1 suppressions, not
  "removed" as an earlier NIGGLES entry (RV4-n4, above) implied — noted
  here rather than reworded there, since RV4-n4's own description of
  what it DID (extracted one shared helper) is still accurate; only the
  "3→0" framing this later review corrects was implicit, not stated.
- **RV5-n2 — the legacy `primary_owner` back-fill
  (`goal_ledger.py:423-427`) uses `session_id`, the field for the LAST
  re-emitter, not the original creator.** A documented approximation
  that applies only to pre-upgrade entries (every NEW entry sets
  `primary_owner` at creation, correctly). Left as-is; the imprecision
  was already named in the surrounding comment, so this is a
  confirmation, not a fix.
- **RV5-n3 — a directory literally named `PLAN.md` records `status=None`
  ("no prior status") via `path_is_file` correctly answering `False` for
  a directory.** Harmless: the real Write this models would itself fail
  (a directory cannot be written as a file), so no Post ever fires to
  consume the recorded `None`. No functional fix needed; noted as an
  intentionally benign edge case.
- **RV5-n4 — the RV5-M2-era docstrings (`utils/plan_status_snapshot.py`'s
  module docstring, `_snapshot_is_fresh`) narrate the RV4-m2 → RV5-M2
  design transition at some length.** Rationale keyed to a failure mode
  (the old bound's exact break, T1/T5) is allowed per `comment_changelog`
  — this is not a version changelog — but the reviewer's own softer
  framing ("adds length") was taken as a signal to keep it as-is rather
  than trim further: the transition explanation is load-bearing for
  understanding why the design has NO time-based logic at all, which a
  future reviewer would otherwise reasonably reintroduce.
- **RV5-n5 — `probe_gf4_threads2.py` breaking (2-argument `record()`
  calls, now 3-argument) is confirmed NOT a defect** — the reviewer's own
  report already states this explicitly ("superseded by
  `probe_gf5_threads.py`"); no action taken.

**Review 6 (`260925-goal-flip-review6-opus-5-5.md`).**

- **RV6-M1 — `markdown_table_formatter` rewrote `PLAN.md` before it was hashed.**
  It runs at PostToolUse priority 26, ahead of `goal_injection` at 31, so
  RV5-M2's forward-hash freshness check read STALE on any write whose
  markdown was not already mdformat's canonical form -- worse than main on
  exactly the Write/reopen/bulk-edit shapes RV5-M2 set out to rescue
  (probe `probe_gf6_formatter.py`'s FE and FT4). This project enables all
  three handlers. Fixed by reordering: `Priority.GOAL_INJECTION` is now
  `30` and `Priority.MARKDOWN_TABLE_FORMATTER` is `31`
  (`constants/priority.py`), with the same swap in
  `.claude/hooks-daemon.yaml`, so `goal_injection` hashes exactly what the
  tool wrote, before the formatter ever touches the file. A guard test
  (`test_goal_injection_precedes_markdown_table_formatter`) pins
  `Priority.GOAL_INJECTION < Priority.MARKDOWN_TABLE_FORMATTER` and the
  real chain's resolved handler order, so a future priority shuffle fails
  loudly instead of silently reintroducing this. Two chain-level tests in
  `TestFormatterOrderingChain` (`test_goal_injection.py`) --
  `test_fe_edit_flip_adding_an_unpadded_table_still_writes_a_signal` and
  `test_ft4_write_reopening_a_complete_plan_with_an_unpadded_table_still_writes_a_signal`
  -- build a REAL `HandlerChain` from `PlanStatusSnapshotHandler` +
  `GoalInjectionHandler` + `MarkdownTableFormatterHandler` and confirm
  both that the flip is still detected AND that the formatter still runs
  (not passing merely because it never fired); the old (pre-fix) priority
  order was confirmed to reproduce the miss via a throwaway script,
  matching the reviewer's own repro. The report's Direction #3 ("check
  every other non-terminal Post handler that can rewrite a `.md` file
  before priority 31") was not separately audited this pass --
  `markdown_table_formatter` is the only PostToolUse handler below the new
  `goal_injection` priority that rewrites file CONTENT at all
  (`git_hooks_executable_fixer` only chmods); left as a standing check for
  a future PostToolUse handler that also rewrites `.md` content. The same
  stale ordering was also baked into `.claude/hooks-daemon.yaml.example`
  (the shipped template every fresh client install copies) and
  `daemon/init_config.py`'s generated project config (the string
  `hooks-daemon init` itself writes) -- both fixed the same way, with the
  same `MUST stay below/above` comments, or a fresh install would have
  reproduced this exact regression from day one. Also fixed a stale
  cross-reference comment (`constants/priority.py`'s
  `PLAN_STATUS_SNAPSHOT` docstring cited `GOAL_INJECTION = 31`, the OLD
  value). `tests/integration/test_template_priorities_match_the_constants.py`
  (pre-existing) confirms all three sources now agree with the code.
- **RV6-m1 — the RV5-m1 NIGGLES claim that "no existing primitive...
  lets one handler read another's resolved enabled-state at runtime" was
  wrong**, corrected in place above. Fixed properly instead of merely
  re-documented: `plan_status_snapshot.matches()` is now gated on
  `goal_injection`'s resolved config state
  (`PlanStatusSnapshotHandler._goal_injection_enabled`, via
  `utils.config_cache.load_config_cached`), with an absent block
  resolving to `goal_injection`'s OWN opt-in default (`False`) rather than
  the generic opt-out-shaped "absent means enabled" convention. Pinned by
  `TestGoalInjectionGate` (`test_plan_status_snapshot.py`, PreToolUse).
- **RV6-m2 — a Write's RV5-M2 freshness check only ever catches a LATER
  writer, and three docs claimed it "covers every shape uniformly."**
  `would_be_content` returns a Write's `content` field verbatim,
  independent of the pre-write text, so the comparison cannot see a race
  that changed the plan's status BEFORE this Write landed (probe W1); an
  Edit's prediction is built from its own before/after span and DOES
  catch that race (probe W1e). "Uniformly" in the RV5-M2 design was about
  needing no reconstruction for any tool shape, not about detecting every
  race uniformly — the claim was imprecise, not the design. Corrected in
  `_snapshot_is_fresh`'s own docstring
  (`handlers/post_tool_use/goal_injection.py`), release note 65, and the
  RV5-M2 NIGGLES entry above (this file).
- **RV6-m3 — the "narrow window" framing for `goal_injection`'s inference
  fallback undersold it in three places.** Besides a daemon restart
  between the Pre/Post dispatch of the same call and a payload carrying
  no `tool_use_id`, the fallback is also taken whenever nothing could be
  predicted at Pre time (`would_be_content` returned `None`, or the plan
  file could not be read), whenever the bounded store evicted the entry
  under load, and whenever a recorded snapshot is rejected as STALE
  (RV6-M1 is one concrete source of STALE, not the only one). Consolidated
  into one authoritative list in `_resolve_transition`'s own docstring
  (`goal_injection.py`), with `plan_status_snapshot.py`'s module docstring
  and `get_claude_md()` now pointing at it instead of re-narrating a
  shorter, stale version.
- **RV6-n1 — "TTL'd" survived RV5-m1's claimed removal**, at
  `plan_status_snapshot.py:13` and its acceptance-test `safety_notes`.
  Both fixed (see the RV5-m1 correction above).
- **RV6-n2 — `.claude/hooks-daemon.yaml`'s `plan_status_snapshot` comment
  said "Opt-in (false) elsewhere" while shipping `enabled: true`
  (`hooks-daemon.yaml.example`).** Fixed to state the true, unconditional
  default plainly.
- **RV6-n3 — a symlinked plan folder is ledgered under the link's number,
  not the target's.** ~~Confirmed harmless~~ -- **wrong.** Review 7
  (RV7-m3) reproduced it as a real defect: a plan COMPLETED through the
  real (non-symlink) path leaves a live ledger entry keyed to the link's
  number forever, because that entry was created through the link and
  never retires. See the Review 7 section below for the fix.
- **RV6-n4 — the snapshot store hand-rolled its own select-then-evict.**
  Correct under its own lock (the `unlocked-eviction` semgrep rule exempts
  a held lock) but a duplicate of exactly what `goal_injection`'s own
  `_fired`/`_reasserted` latches already use. Fixed: `PlanStatusSnapshotStore`
  is now backed by `handlers.utils.bounded_fifo_map.BoundedFifoMap` (Plan
  00449 P2), removing the second implementation; pinned by
  `TestUsesTheSharedBoundedMap` in `tests/unit/utils/test_plan_status_snapshot.py`.
  All of `TestRecordAndConsume`, `TestConsumeSnapshot`, `TestBoundedGrowth`
  and `TestConcurrency` (the existing black-box regression suite for this
  store) still pass unchanged.

**Review 7 (`260925-goal-flip-review7-opus-5-5.md`).**

- **RV7-B1 — review 6's renumbering broke four PostToolUse unit tests it
  never ran.** `constants/priority.py:205-218` shifted
  `git_hooks_executable_fixer` (27→26), `background_process_tracker`
  (28→27), `command_hints` (29→28) and `recovery_cron_advisor` (30→29) to
  stay adjacent to the `goal_injection`/`markdown_table_formatter` swap,
  but four `test_priority`-shaped assertions in those handlers' own test
  files still asserted the OLD literal. Fixed by asserting against the
  `Priority` constant instead of a literal in all four (renaming
  `test_priority_is_30` to `test_priority_matches_constant` in
  `test_recovery_cron_advisor.py`, since it is no longer 30) — the same
  fix the report itself directed, so a future priority shuffle cannot
  reintroduce this. The whole `tests/unit/handlers/post_tool_use/`
  directory was run once before finishing, since B1 was itself a missed
  sibling.
- **RV7-M1 — the RV6-m1 gate ran BEFORE the cheap trigger match, so every
  PreToolUse event paid a config read, and a broken config cost ~80ms per
  event.** `plan_status_snapshot.matches()` now checks
  `matched_plan_write_or_edit` (a tuple-membership test, no I/O) FIRST,
  and only consults the config-backed gate for an actual plan Write/Edit —
  the overwhelming majority of PreToolUse events never reach it at all.
  Separately, `utils.config_cache.load_config_cached` now caches a
  RAISED parse failure under the same `(st_mtime_ns, st_size)` signature
  as a successful parse, so a config broken by an edit after startup is
  re-parsed once per change rather than once per event — this benefits
  all six callers of the cache, not just this gate. The misnamed
  `test_gate_runs_before_the_trigger_match_so_a_non_plan_write_is_still_false`
  test already exercised the right shape and needed no change; new tests
  in `TestABrokenConfigIsCachedByFailure`
  (`tests/unit/utils/test_config_cache.py`) pin the caching behaviour.
- **RV7-m1 — the gate disagreed with what the daemon actually registers,
  in two shapes RV7-m1 measured (an absent `goal_injection` block, and
  `disable_tags` covering it), and its own docstring/test asserted the
  disagreement was correct.** `_goal_injection_enabled` now decides from
  `handlers.registry.handler_is_enabled` over the SAME per-event mapping
  `daemon.cli._build_handler_config_mapping` builds for `register_all`
  itself — the checklist's own "would `register_all` register this
  handler" predicate — rather than a hand-rolled reading of the config
  block that (wrongly) tried to honour `goal_injection`'s own opt-in
  default, which `register_all` never actually consults. An absent block
  now resolves to TRUE (matching the registry's own "absent means
  enabled" convention), reversing the RV6-m1 test's assertion; the load-
  failure test now writes genuinely unparseable YAML to a real config
  path instead of monkeypatching `_load_config` past the `except` branch
  it claimed to exercise. A new table-driven test
  (`test_gate_agrees_with_register_all_for_every_shape`) builds a REAL
  `HandlerRegistry`/`EventRouter` and asserts the gate's answer equals
  what got registered, for all six shapes RV7-m1's own table names.
- **RV7-m2 — the FT4 chain test passed against the PRE-fix priority
  order, so review 6's commit message claim "every finding has a
  RED-confirmed test" was false for it; FC3b (review 6's own Direction #2)
  had no chain test at all.** Both `TestFormatterOrderingChain` tests now
  assert the snapshot was consumed FRESH (no "is stale" WARNING in
  `caplog`), not merely that a signal file exists — the file-exists
  assertion alone cannot tell a fresh-snapshot pass from a lucky
  fallback-inference pass. FT4 now runs inside a real git repo whose HEAD
  already reads `**Status**: In Progress` (diverged from the actual,
  uncommitted `Complete` pre-write disk state) — the Write-only fallback
  reads that stale HEAD as "already there, no transition" and would write
  NO signal, so the test genuinely fails without a fresh snapshot; before
  this, `tmp_path` was not a git repo at all, so the fallback's
  `before_text is None -> True` branch always reported a transition
  regardless of ordering. Confirmed RED against the pre-fix priority
  order via a throwaway in-process monkeypatch of `Priority.GOAL_INJECTION`/
  `Priority.MARKDOWN_TABLE_FORMATTER` (matching the reviewer's own repro
  method): all three of FE, FT4 and the new FC3b failed. A new
  `test_fc3b_completion_write_with_reformatted_columns_still_retires_and_clears`
  test mirrors FT4's shape for the terminal-transition detector (a
  completing Write with an unpadded table, HEAD diverged the other way —
  already `Complete` — so the fallback would wrongly conclude no
  transition), first establishing ledger ownership via a real prior flip
  (`clear_goal_signal` only fires for a plan the ledger already names an
  owning session for). This NIGGLES entry — not the immutable `88991a06`
  commit message — is the correction of record for the RED-confirmation
  claim.
- **RV7-m3 — RV6-n3 was wrongly closed as harmless: a plan flipped
  through a symlinked folder is ledgered under the link's number and
  never retires.** `matched_plan_write_or_edit` (`utils/plan_trigger.py`)
  now re-applies the trigger pattern to the FULLY RESOLVED path (symlinks
  followed), expressed relative to the resolved project root, once
  `is_inside_project` has already confirmed containment (which resolves
  the same path itself) — that resolved capture is what both
  `goal_injection` and `plan_status_snapshot` key on, since both share
  this one function. A path that resolves outside the pattern entirely
  returns unmatched (logged), rather than trusting the unresolved
  capture. Regression test
  `test_a_symlinked_plan_folder_resolves_to_the_targets_number`
  (`tests/unit/utils/test_plan_trigger.py`) asserts a plan reached via
  `00301-l -> 00300-c` is captured as `00300-c`; confirmed RED against the
  pre-fix logic via a throwaway in-process comparison against the OLD
  (unresolved-capture) implementation. The RV6-n3 "confirmed harmless"
  text above is struck through and superseded by this entry.
- **RV7-m4 — release artefacts drifted from the RV6-m1/RV7-m1 fixes.**
  `config-changes/v3.67.0.yaml` gained `changed` entries for all six
  priorities RV6-M1 moved, with a `migration_note` on the two that matter
  (an operator who set custom priorities for `goal_injection`/
  `markdown_table_formatter` must keep the former below the latter).
  Both `config-changes/v3.67.0.yaml` and `docs/guides/HANDLER_REFERENCE.md`
  no longer claim `plan_status_snapshot` "runs unconditionally... whether
  or not `goal_injection` itself is enabled" — false since RV6-m1 gated
  it, and doubly false now that RV7-m1 fixed what the gate agrees with.
  The optional `ConfigValidator` startup warning (RV7-m4 Direction #2) was
  NOT added — genuinely optional per the report, and the guard test
  (`test_goal_injection_precedes_markdown_table_formatter`) plus the new
  `changed` migration_notes already cover the cases that matter.
- **RV7-n1 — `.claude/hooks-daemon.yaml`'s commented `options:` block sat
  under `markdown_table_formatter` instead of `goal_injection`,** so
  uncommenting it configured the wrong handler (it names `mode`,
  `once_per_plan_per_session` and `lines`, all `goal_injection` options).
  Moved to sit under `goal_injection`, matching `.claude/hooks-daemon.yaml.example`'s
  arrangement, which was already correct.
- **RV7-n2 — the release note shared ordinal 13 with an unrelated one and
  ran to ~1,300 words against a "one to three sentences" schema.**
  Renumbered to `33` (the next free ordinal, matching main), and cut to
  three sentences naming the operator-facing change, that the snapshot
  sensor ships on by default, and what a project running the inference
  fallback (an explicit opt-out) keeps instead. The mechanism narrative it
  carried is not lost: it already lives in `goal_injection.py`'s and
  `plan_status_snapshot.py`'s own module docstrings, which the shortened
  note now points at instead of re-narrating.
- **RV7-n3 — the "single authoritative list" of fallback triggers
  (`goal_injection.py:909-943`) omitted a trigger this same branch
  introduced:** the sensor not running at all, because
  `plan_status_snapshot` is disabled or its (RV7-m1-corrected) gate reads
  `goal_injection` as off. Added as its own bullet under "No snapshot
  recorded at all".

### N2 — `setup_worktree.sh` tells every agent to run the full suite through `run_all.sh`

**Found by the coordinator** when it set up an integration worktree.
`scripts/setup_worktree.sh` ends with an "Agent prompt template" whose last
line is `Run ./scripts/qa/run_all.sh before committing.`, and a "Run QA" hint
with the same command (lines 389 and 400). Step 7 also treats `run_all.sh` as
the QA entry point (line 343). Two things are wrong with that:

- `enforce_llm_qa` denies `run_all.sh`; `./scripts/qa/llm_qa.py all` is the
  only full-QA entry. An agent that follows the template is denied at once.
- Plan 00463 makes full QA a coordinator gate. A sub-agent runs targeted QA
  only, and the coordinator runs one full pass over the batch of merged
  branches. The template sends every sub-agent to run the full suite, which
  is the concurrent full QA that 00463 exists to stop.

**Candidate remedy:** the template names targeted QA (`llm_qa.py <tools>`
plus the touched tests) and says that full QA is the coordinator's
integration gate. The "Run QA" hint and Step 7 name `llm_qa.py`. A test
checks that the script names no denied QA entry point.

**Graduated to Plan 00463**, which owns the sub-agent QA policy.

### N1 — ✅ Remedied — `resolve_venv_python`'s fallback accepts a venv interpreter that cannot run on this host

**Found by Plan 00457's agent** (#55; recorded in 00457's JOURNAL as a
finding). When the slug-exact venv is absent, `resolve_venv_python` falls
back to globbing `untracked/venv-*/bin/python`, and accepts a candidate on
its executable bit alone. #55 is about a host whose only venv was built
inside a container. That interpreter may be for another architecture or
libc, or may symlink into a path that exists only in the container. It is
executable but cannot run. The fallback would then report "resolved", so
`bin/hooks-daemon` never reaches `_run_venv_free_verb` (the `repair` and
`signal` arms from Plans 00456 and 00457). It would fail when it runs the
interpreter, not with the clear venv-missing path. No test covers it on
either side of #53 or #55.

**Candidate remedies:**

1. The fallback proves a candidate RUNS, e.g.
   `"$candidate" -c 'import sys'` with a short bound, before accepting it.
   It moves on to the next candidate, then to the venv-free path, on
   failure. Test it with a fake executable that exits non-zero, and with a
   dangling symlink.
2. At minimum, a candidate that fails at exec time produces a message
   naming the venv it tried and the `repair` command, not a raw exec error.

**Remedy** (remedy 1, plus remedy 2's diagnostic): every implementation
that trusted a venv interpreter's executable bit alone now proves it RUNS
first.

- Bash: `scripts/lib/resolve_venv.sh::_rv_pick_python`'s two glob loops
  (`venv-*/bin/python`, `venv-*/bin/python3`) probe each candidate with a
  new `_rv_candidate_runs` helper (`"$candidate" -c 'import sys'`) before
  accepting it, falling through to the next candidate — and eventually to
  `bin/hooks-daemon`'s venv-free path — on failure. The bound is enforced
  by a watchdog subprocess (`( sleep N; kill -KILL "$pid" )  &` + a
  blocking `wait "$pid"`), not a `sleep`-poll loop: a poll loop always
  costs at least one full poll interval even for a candidate that exits
  in milliseconds, because the first check almost always lands before the
  process has exited. Measured on this repo's own real venv `bin/python`:
  ~1005ms/candidate under an earlier `sleep 1`-poll draft, ~15-40ms/candidate
  under the watchdog. `HOOKS_DAEMON_VENV_PROBE_TIMEOUT` overrides the
  5-second default bound (mirrors `Timeout.VALIDATION_CHECK`). Both glob
  loops now report which candidate they rejected and why on stderr before
  moving on, closing remedy 2 for the bash side.
- Python: `resolve_existing_venv_python_with_diagnostics`'s shared
  `_pick_interpreter` closure (used by steps 3, 4 and 5) and step 2's
  metadata `python_path` check now all route through a new
  `_venv_interpreter_runs` helper before accepting a candidate — the SAME
  `-c 'import sys'` probe, via `subprocess.run(..., timeout=5)`. Steps 3
  and 5 (single-candidate) and step 4 (scan) each report which candidate(s)
  were executable-but-unrunnable and name the `repair` command, closing
  remedy 2 there too. The "slug-exact" fingerprint-keyed venv (step 3) is
  probed too, not exempted — #55 already showed an exact-fingerprint match
  can be container-built and still unrunnable (e.g. a shared/NFS-mounted
  `untracked/`), and this resolver only runs on a bash-side resolver-cache
  MISS, so the extra spawn never lands on the per-hook hot path.
- `resolve_existing_venv_python` (the simpler, no-diagnostics function)
  deliberately stays un-probed: it is called fresh on every user turn by
  `daemon_upgrade_detector`, which only reads `.daemon-metadata.json` next
  to the returned path and never executes it, so probing there would add
  a real hot-path cost for no correctness gain.
  `client_validator.py::validate_daemon_can_start` — the other caller,
  which DOES execute the result — already ran its own
  `subprocess.run(..., timeout=Timeout.VALIDATION_CHECK)` probe before
  doing so, so it needed no change. Both are recorded in the sibling audit
  in the delivery report.
- `check_canonical_callers.sh` was already the sibling-audit backstop for
  the bash side: it denies any OTHER shell script that iterates
  `untracked/venv-*` directly, so `_rv_pick_python` is the only bash glob
  site that needed the fix.

TDD: RED tests confirmed failing against the pre-fix code first, in both
`tests/unit/daemon/test_paths_resolve_venv_diagnostics.py::TestRunnabilityProbe`
and the new `tests/integration/test_resolve_venv_runnability_probe.py`,
covering a fake executable that exits non-zero, a dangling symlink, a
hanging candidate (bound respected), fall-through to a good second
candidate, all-candidates-bad reaching the venv-free path, and the
slug-exact venv unaffected when it genuinely works.

**Follow-up defect, fixed at integration (766677c1).** The B1 full gate
failed `tests/acceptance/test_v391_field_regression.py`. That test runs the
resolver with a PATH holding only a broken `python3`. The watchdog ran
`sleep` from PATH, so with no `sleep` it went straight to `kill -KILL`. A
working venv was then rejected as "timed out after 5s", which is the v3.9.1
field case this resolver exists to survive. The branch's targeted QA had
not run that acceptance test. `_rv_wait_secs` now uses `sleep` when PATH
has one. Otherwise it waits on `read -t` against a read-write
process-substitution pipe, which needs no PATH lookup, and the kill runs
only if the full bound elapsed. Two regression tests cover a PATH with no
`sleep`: a good candidate still resolves, and a hanging one is still
bounded.

**✅ Remedied** on main (B1, 2e6483a3).
