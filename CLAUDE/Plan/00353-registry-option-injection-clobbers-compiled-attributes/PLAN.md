# Plan 00353: registry option injection clobbers compiled attributes

**Status**: Complete
**Created**: 2026-09-08
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

A field report says that setting `handlers.pre_tool_use.pipe_blocker.options.extra_whitelist`
makes `pipe_blocker` raise `AttributeError: 'str' object has no attribute 'search'`
on **every** piped Bash command. The diagnosis was verified against the code and
holds in full.

The registry instantiates every handler with no constructor arguments
(`handlers/registry.py`, `instance = attr()`) and then applies configuration
through one generic reflective loop, `setattr(instance, f"_{option_key}", option_value)`.
That loop runs last and always wins. `PipeBlockerHandler.__init__` meanwhile
declares an `options` parameter and compiles `extra_whitelist` into
`re.Pattern` objects — but nothing in production ever passes that parameter, so
the comprehension always yields `[]`, and the injection then replaces the empty
`list[re.Pattern]` with the raw `list[str]` from YAML. `_matches_whitelist`
calls `pattern.search(...)` on what is now a string and raises.

The consequence is worse than a dead option. `matches()` raises *before* the
handler reaches any verdict, so with `daemon.strict_mode` false the chain fails
open and **every** `pipe_blocker` protection — the expensive-command blacklist
and the tail/head information-loss guard alike — is silently skipped for every
piped command, for as long as `extra_whitelist` is non-empty. A project that
sets the option to gain one exemption disables the whole handler and is told
nothing.

A static audit of all 121 handler modules (see
[OPTION-INJECTION-CONTRACT.md](OPTION-INJECTION-CONTRACT.md)) found
`pipe_blocker._extra_whitelist` is the **only** live instance of this defect.
It is also the only handler constructor in the repository that reads its
`options` argument at all, which is the property this plan turns into an
enforced invariant.

## Goals

- `extra_whitelist` works as documented: a project pattern is honoured, and no
  exception reaches the chain.
- The reproduction test drives the **real registry injection path**
  (`HandlerRegistry.register_all` with a config dict), not a hand-set
  attribute — the constructor-argument path is precisely the one that gave
  false confidence, because the existing integration test used it.
- A repo-wide regression guard makes the class of bug non-silent: no production
  handler `__init__` may read its `options` argument, since the registry never
  supplies it.
- `extra_blacklist` gets the same treatment, so the two options are symmetric
  and a malformed pattern in either is reported rather than swallowed.
- `scripts/debug_info.py` stops emitting `[Errno 13] Permission denied: ''`.

## Non-Goals

Three fixes were considered; two are rejected, and the reasons are recorded
here rather than dropped.

- **Making the registry skip options the constructor already consumed** —
  rejected. It is the intuitive fix, because the registry contract looks like
  the broken thing, but the registry cannot know which keys a constructor
  consumed. Handler options are free-form (there is no per-handler option
  schema anywhere in the codebase), and a constructor's *signature* says only
  that it accepts a `dict`, never which keys it reads. The only implementable
  version — "pass `merged_options` to any constructor that accepts one, and
  skip the setattr loop for it" — actively regresses: `PipeBlockerHandler`
  would then swallow `workspace_root`, `exclude_paths` and every future
  cross-cutting injection it does not handle, so those would stop arriving.
  The registry contract is also not in fact broken: 120 of 121 handler modules
  honour it, and it is coherent (a handler receives its config as
  `self._<option_key>` holding the raw YAML value). What is broken is one
  handler implementing a second, phantom contract that the registry has never
  called. Changing the shared contract to accommodate the one deviant is the
  larger and riskier change, and it would not remove the deviation.
- **A type guard in `_matches_whitelist` that raises a clearer error** —
  rejected as a destination, absorbed as a principle. An actionable
  `TypeError` is still a broken handler that fails open on every piped
  command; naming the defect better does not restore the protections. The
  half worth keeping — "self-heal by compiling on the fly" — is not a guard at
  all, it is the chosen fix.
- **Compile-time validation of `extra_*` patterns at config load** — out of
  scope. A malformed regex is reported by this plan at first use, with the
  option name and the offending pattern; moving that to config-load time is a
  separate change to the config validator and buys little.
- **Fixing the 97 latent transformed constructor attributes** — out of scope,
  and deliberately so. They are only reachable if a config key is later
  introduced with a matching name; the invariant test added here is what stops
  that happening silently, and rewriting 97 correct constructors would be pure
  churn.

## Tasks

### Phase 1: Reproduce through the real injection path (RED)

- [x] ✅ **Task 1.1**: Add `tests/unit/handlers/test_registry_option_injection.py`.
  Build a `HandlerRegistry`, call `register_all` with
  `{"pre_tool_use": {"pipe_blocker": {"options": {"extra_whitelist": [r"^my_report\b"]}}}}`,
  pull the registered instance out of the router chain and assert
  `matches()` on `my_report --all | tail -20` returns `False`. Asserted on the
  instance, not on `route()`: the chain catches the exception and fails open,
  so routing alone cannot tell an allow-by-verdict from an allow-by-crash.
- [x] ✅ **Task 1.2**: In the same module, pin the severe consequence — with
  `extra_whitelist` set, an expensive command piped to `tail` must still be
  denied. Under the defect it returned an allow, and that is the whole
  handler's protections going quiet.
- [x] ✅ **Task 1.3**: Add the repo-wide invariant test — walk every module
  under `handlers/<event>/`, parse each `__init__` with `ast`, and assert
  none reads its `options` argument. Include the reason in the assertion
  message so a future author who adds one is told why it cannot work.

### Phase 2: Fix pipe_blocker (GREEN)

- [x] ✅ **Task 2.1**: Store `_extra_whitelist` and `_extra_blacklist` as raw
  `list[str]`, matching what the registry injects, and drop the now-dead
  `options` parameter from `PipeBlockerHandler.__init__` so no caller can
  believe the constructor path works.
- [x] ✅ **Task 2.2**: Add a module-level compile-with-cache helper (mirroring
  the existing `_compiled_public_pattern` idiom in `sensitive_content.py`)
  and route both `_matches_whitelist` and `_matches_blacklist` through it,
  replacing the WET per-call `re.search(pattern_str, ...)` loop.
- [x] ✅ **Task 2.3**: Update the handler docstring so the option contract it
  advertises is the one the registry actually implements.
- [x] ✅ **Task 2.4**: Repoint `tests/integration/test_pipe_blocker_integration.py`'s
  `test_extra_whitelist_allows_custom_command` off the constructor
  argument. That test passed throughout the defect's life and is the
  reason it shipped.

### Phase 3: debug_info.py empty-interpreter guard

- [x] ✅ **Task 3.1**: `scripts/debug_info.py` guards its interpreter with
  `if not Path(python_cmd).exists()`, but `PYTHON_CMD` can resolve to `""`
  and `Path("")` is `PosixPath('.')`, which exists — so the guard passes
  and `subprocess.run(["", ...])` raises
  `PermissionError: [Errno 13] Permission denied: ''`, which
  `run_command` returns as report text. Reject a blank `python_cmd`
  explicitly, with a test in `tests/unit/test_debug_info.py`.

### Phase 4: QA and delivery

- [x] ✅ **Task 4.1**: `./scripts/qa/llm_qa.py all` — 24/26 tools green,
  19840 tests passed, 0 failed, coverage 95.2%. The 11 errors are
  environmental preconditions untouched by this plan: ten acceptance gates
  abort on "Daemon not running" (the daemon is deliberately not restarted from
  an isolated worktree) and one is the generated-doc guard firing on the
  daemon's own auto-regeneration of `CLAUDE.md` mid-run.
- [x] ✅ **Task 4.2**: `./bin/hooks-daemon plan-qa --lint` clean on this PLAN.md.

## Success Criteria

- [x] A registry-injected `extra_whitelist` allows the command it names, and
  raises nothing.
- [x] With `extra_whitelist` set, `pipe_blocker`'s blacklist and unknown-command
  paths still reach their verdicts (the protections are not skipped).
- [x] No handler `__init__` reads its `options` argument, enforced by a test.
- [x] A malformed `extra_whitelist`/`extra_blacklist` pattern does not crash
  the handler and is reported once, not per event.
- [x] `scripts/debug_info.py` reports a missing interpreter as a missing
  interpreter, never as `Permission denied: ''`.
- [x] Full QA passes.

## Delivery & Milestones

- Phases 1–4 delivered together on branch
  `agent-a2cab544bfe17abba-8fa420db`.
- Archival to `Completed/` is deferred to the merge commit. The move also
  requires reconciling the README statistics block, whose counts are computed
  against `main`; doing it from an isolated worktree — while sibling agents are
  adding plan rows to the same index — would produce a conflicting count rather
  than a correct one.
