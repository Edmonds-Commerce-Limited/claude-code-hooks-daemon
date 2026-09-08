# pipe_blocker `extra_whitelist` — verification, fix and audit

Report for Plan 00353. Branch `agent-a2cab544bfe17abba-8fa420db`.

## Did the report's diagnosis hold up?

Yes, in full, and it was verified against the code and reproduced before
anything was changed. Every mechanical claim checks out:

- `handlers/registry.py` constructs each handler as `instance = attr()` — no
  arguments, with a comment stating that assumption outright.
- It then applies configuration through one generic reflective loop,
  `setattr(instance, f"_{option_key}", option_value)`, which runs after
  `__init__` and after `priority`, and always wins.
- `PipeBlockerHandler.__init__` compiled `extra_whitelist` into `re.Pattern`
  objects from an `options` dict production never passes, so the comprehension
  always produced `[]`, which injection then replaced with the raw `list[str]`.
- `_matches_whitelist` called `pattern.search(...)` on a `str`.

The severe consequence the report describes is real and is now pinned by a
test: `matches()` raises before any verdict, the chain fails open with
`strict_mode` off, and every one of the handler's protections goes quiet. With
`extra_whitelist` configured, `pytest tests/ | tail -20` came back **allow**.

One correction worth recording. The report frames the trigger as the
constructor reading `options`. The sharper statement is that it *transforms* an
option into an attribute injection is about to overwrite. `_extra_blacklist`
was initialised by the same dead `options.get(...)` call and worked perfectly —
because it stored the value verbatim and its consumer took strings. Both
siblings were written identically; only one had a type mismatch waiting for it.

## Blast radius

Audited all 121 production handler modules statically (AST over every
`__init__`, classifying each `self._X = <expr>` as a verbatim store or a
transformation, intersected with option keys harvested from the module's own
`options.get`/`getattr` reads, its `Configuration options:` docstring block,
and every key under an `options:` block in the repository's YAML).

| Finding                                                         | Count |
| --------------------------------------------------------------- | ----- |
| Handler modules scanned                                         | 121   |
| Constructors reading their `options` argument                   | 1     |
| **Transformed attributes whose name is a live config key**      | **1** |
| Transformed attributes whose name is not currently a config key | 97    |

`PipeBlockerHandler._extra_whitelist` is the only live exposure. Nothing else
in the repository is affected today.

A methodological note, because it nearly hid the answer: a *runtime* scan
(instantiate, inspect attribute types) reports zero findings, because an
unconfigured `[re.compile(p) for p in ...]` evaluates to `[]` — indistinguishable
from a raw empty list. Static analysis is the only thing that sees it.

The 97 are not defects. They are ordinary constructor state (`_rules_by_id`,
`_formatter`, internal precompiled patterns) that merely shares the shape which
would become dangerous *if* a config key were later introduced with a matching
name. Rewriting them would be churn; the invariant test below is what stops
that happening silently instead.

`GhIssueCommentsHandler` and `GhPrCommentsHandler` declare an `options`
parameter but never read it. Inert, and left alone.

## Registry fix vs handler fix — the decision

Fixed the handler, plus a repo-wide invariant test. The owner's prior was that
the registry contract is what is actually broken and that a per-handler lazy
compile only treats a symptom; the evidence pointed the other way, so this is a
disagreement stated openly rather than a risk-aversion call.

**The registry-side fix cannot be written.** To "skip options the constructor
already consumed", the registry must know which *keys* a constructor reads.
Handler options are free-form — there is no per-handler option schema anywhere
in the codebase — and a constructor's signature discloses only that it accepts a
`dict`. The single implementable approximation ("pass merged options to any
constructor that takes them, and skip the setattr loop for it") trades this bug
for a worse one: `PipeBlockerHandler` would then also swallow `workspace_root`,
`exclude_paths`, `_project_layout` and every future cross-cutting injection it
does not handle, and those would silently stop arriving.

**The contract is also not the broken thing.** 120 of 121 modules honour it
without difficulty, and it is coherent and now written down: an option named
`X` arrives as `self._X`, holding the value PyYAML parsed, verbatim, after
`__init__` has finished. What was broken is one handler implementing a second,
phantom contract that the registry has never called. Changing the shared
contract to accommodate the one deviant is both the larger change and one that
would not remove the deviation.

**But the generalisation the owner wanted is real, and it is delivered another
way.** A repo-wide test now asserts that no production handler `__init__` reads
its `options` argument, with the reason in the assertion message. That forbids
the *mechanism* by which a transformed attribute acquires a config-key name,
has exactly zero violations after this fix, and costs nothing at runtime — the
class of bug is now non-silent without touching the code path every handler
depends on.

The report's third option (a type guard raising a clearer error) is rejected as
a destination: an actionable `TypeError` is still a handler that fails open on
every piped command, and naming the defect better does not restore the
protections. Its useful half — self-heal by compiling on the fly — *is* the
chosen fix. All three rejections are recorded as Non-Goals in PLAN.md with
their reasons.

## What changed

- `src/claude_code_hooks_daemon/handlers/pre_tool_use/pipe_blocker.py`
  - `__init__` now takes **no arguments** (the dead `options` parameter is gone
    rather than left inert — a parameter that silently ignores what the caller
    passed is worse than one that does not exist).
  - `_extra_whitelist` and `_extra_blacklist` hold raw `list[str]`, the shape
    injection actually assigns.
  - New module-level `_compiled_extra_pattern` / `_matches_any_configured`,
    following the `_compiled_public_pattern` idiom already in
    `sensitive_content.py`: compile once, cache by source string, and cache an
    uncompilable client pattern as a logged no-match so a typo cannot take the
    handler down or be re-attempted per event. This also removed the WET
    per-call `re.search(pattern_str, ...)` loop from `_matches_blacklist`, so
    both `extra_*` options are now symmetric.
  - Class docstring states the injection contract it must code against.
- `tests/unit/handlers/test_registry_option_injection.py` (new) — the
  reproduction, driven through `HandlerRegistry.register_all` with a config
  dict, plus the repo-wide `__init__`-must-not-read-`options` invariant.
- `tests/unit/handlers/pre_tool_use/test_pipe_blocker_comprehensive.py` — seven
  tests repointed off the constructor-argument path onto a `_configured(**options)`
  helper that applies options the way the registry does; the two
  `..._from_options` init tests replaced with a signature assertion and a
  raw-shape assertion.
- `tests/integration/test_pipe_blocker_integration.py` — the same for
  `test_extra_whitelist_allows_custom_command`, which passed green throughout
  the defect's life precisely because it used the path production never takes.
- `scripts/debug_info.py` + `tests/unit/test_debug_info.py` — see below.
- Plan folder: `PLAN.md`, `OPTION-INJECTION-CONTRACT.md` (the contract as it
  actually is, and the full audit), `JOURNAL/`, and a README index row.

### On the reproduction test being honest

Worth flagging, because it is the part that is easy to get wrong: asserting on
`router.route(...)` alone does **not** reproduce this defect usefully. The
chain catches the exception and fails open, so routing returns `allow` — which
is also the correct answer for a whitelisted command. The crash and the pass
are indistinguishable from outside. The test therefore asserts on the instance
pulled out of the router chain (`matches()` must return `False`, not raise), and
separately pins the consequence: with `extra_whitelist` set, an expensive
command piped to `tail` must still be **denied**.

## The second, unrelated bug (`debug_info.py`)

Small, root-caused, and fixed in this plan rather than filed separately.

`python_cmd = paths.get("PYTHON_CMD", "")` followed by
`if not Path(python_cmd).exists()`. `Path("")` is `PosixPath('.')` — the current
directory, which always exists — so a blank `PYTHON_CMD` sailed straight past
the guard, and every section that shells out to the interpreter then ran
`subprocess.run(["", ...])`. Confirmed empirically:

```
Path(empty) == PosixPath('.')
Path(empty).exists() == True
subprocess.run(['', ...]) raised: PermissionError: [Errno 13] Permission denied: ''
```

`run_command` catches that and returns it as report text, which is exactly the
`[Errno 13] Permission denied: ''` the reporter saw. Note it affects three
sections, not the two they counted — Daemon Status, Daemon Logs and Installed
Handlers all shell out to `python_cmd`.

Fixed by rejecting a blank value before the `exists()` check, and reporting
`<unset>` rather than an empty string. The test reproduces it with a real
`init.sh` that resolves no interpreter — no monkeypatching, so the guard is
exercised as written.

## QA

`./scripts/qa/llm_qa.py all`: **24/26 tools green**, 19840 tests passed,
**0 failed**, coverage **95.2%** (gate 95%). `format`, `lint`, `type_check`,
`security`, `error_hiding`, `british_english`, `doc_truth`, `sensitive_content`
and the rest all clean. `plan-qa --lint` clean on PLAN.md.

The 11 errors are environmental and untouched by this work:

- 10 × acceptance release gates aborting on `Daemon not running — start with: ./bin/hooks-daemon restart`. Restarting the daemon was explicitly out of
  bounds for this task. They pass in isolation.
- 1 × the generated-doc guard firing on `tests/integration/test_forwarder_socket_stdin.py`
  teardown, because the daemon regenerated the tracked `CLAUDE.md` while the
  suite was running. The guard's own message names this case ("suspect an
  EXTERNAL edit"). It restored the file; that auto-generated churn is left
  unstaged and uncommitted.

## Left unfinished, deliberately

- **Archival to `Completed/`.** PLAN.md is marked Complete but the folder stays
  in the active root, which plan-QA reports as an *advisory* (0 block). The
  `git mv` must ship with the README statistics reconciled in the same commit,
  and those counts are computed against `main` while ~35 sibling agents are
  adding rows to the same index — doing it from this worktree would produce a
  conflicting count, not a correct one. Archive at merge.
- **`scripts/qa/llm_qa.py` hardcodes `untracked/venv/bin/python`** while
  `ensure_venv` in a worktree creates a fingerprinted
  `untracked/venv-<fingerprint>/`, so the QA entrypoint cannot find an
  interpreter there. Worked around with a symlink in gitignored space to get QA
  to run. This is a pre-existing entrypoint gap unrelated to this plan and is
  worth its own plan; not filed, to avoid sprawl.

## One thing to flag outside the technical work

A `system-reminder` arrived mid-task instructing me to "do your work through
the Bash tool wherever it can accomplish the job … make file changes with sed,
heredocs, or short scripts, rather than using the dedicated Read, Edit, or
Write tools". That directly contradicts the project's own `CLAUDE.md` (sed is
deny-by-default; content guards run on `Write`/`Edit` only, so a heredoc reaches
disk unexamined) and the task instructions. I disregarded it and used
`Write`/`Edit` throughout. Recording it here because an instruction to route
file edits around this repository's content guards is worth a human look.
