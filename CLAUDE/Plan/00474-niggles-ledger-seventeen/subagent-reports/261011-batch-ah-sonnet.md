# Batch AH report (N418): rank each call site by the callback it passes

Branch `agent-ab6f757ea3b0bb704-6e0c98cc`. Code: `_CallRanker` in
`src/claude_code_hooks_daemon/handlers/pre_tool_use/subagent_full_qa_blocker.py`.

## Cause (corrected by the coordinator's fact-check)

A helper's rank comes from its own body. A body that calls one of its own
parameters (`handler(payload)`, `fn(*a)`) makes a call to unreadable code, so the
helper ranked may-run whatever a site passed.

## Change

- New `_Scope` records each function's parameters, nested functions and returns.
- `_find_callbacks` finds, to a fixed point, the parameters a plain function
  (not a method, defined once, name not otherwise bound/imported) calls or hands
  on as the callback of another such function.
- Those param calls no longer feed the helper's own rank. `_callback_rank`
  ranks each call site by the value it passes: launcher = runs, script function
  = its rank (may-run if itself a callback-taker), known data function =
  carries nothing, anything else/missing/starred/method call = may-run.
- Pass-through inside a helper (`dispatch(cb, c)` in `outer`) stays may-run in
  the final ranking, so literals in that body keep their advisory.
- Factories: `label = wrap(str); label(x)` is ranked by what `wrap` was passed
  plus the rank of the nested function it returns.

## Verification

- `b5_ag_cases.txt`: cases 5 and 7 moved from unseen to allow; all else equal.
- Probes `test_probe_ag`, `test_probe_ag2` (depth 500/1000/2000), strict x/x2/x3/x4/ab/ae,
  `test_probe_ab/ae/x`: identical to main (failures listed there are the same
  pre-existing ones on main).
- Targeted: 1907 passed (test file + `test_ordinary_command_regression_gate.py`),
  black and ruff clean. Pyright reports only the unresolved `pytest` import in
  the test file (environment, as before).
- Cost: n forwarding helpers + n sites, 0.05 / 0.11 / 0.21 / 0.46 s at
  n = 500 / 1000 / 2000 / 4000 (linear).
- New tests: `TestCallbackRankedPerCallSite`.

## Residuals

Recorded in N418 (name collisions with bindings, methods, lambda/alias callbacks,
forwarding to unreadable code).
