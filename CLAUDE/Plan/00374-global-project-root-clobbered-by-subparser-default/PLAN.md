# Plan 00374: the global `--project-root` is clobbered by a subparser default

**Status**: In Progress
**Created**: 2026-09-10
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Main Thread

## Overview

`bin/hooks-daemon` anchors every CLI invocation to the project the wrapper
itself lives in, and refuses to run at all if it cannot:

```
exec "$PYTHON" -m claude_code_hooks_daemon.daemon.cli --project-root "$PROJECT_ROOT" "$@"
```

Its comment states the premise — *"Derived anchor FIRST: argparse takes the
last occurrence, so a caller's own `--project-root` still overrides it"* — and
the refusal path beside it explains the stakes: *"Refusing to fall back to the
working directory: that would target whichever project you happen to be
standing in."*

The premise is false. Twenty-five subcommands declare their OWN
`--project-root` with `default=None`, and argparse writes a subparser's
defaults into the namespace whether or not the flag was supplied — so the
subparser's `None` overwrites the anchor the wrapper passed. Measured live,
with a scratch project that has a config but no plan tree:

```
cli --project-root $R plan-qa --sweep   -> exit 0, "plan tree is clean"   (WRONG root)
cli plan-qa --sweep --project-root $R    -> exit 2, "Plan directory does not exist"
```

The same `cmd_plan_qa`, called in-process with the root in the namespace,
correctly returns 2. Only the entry path loses it.

`tests/unit/install/test_bin_wrapper_project_anchoring.py` does not catch this,
and its own docstring says why without noticing: the tests "assert the ACTUAL
command the wrapper builds rather than trusting a reading of the shell." They
stop one layer short — they trust a reading of argparse. The wrapper builds the
right argv; the CLI discards it.

## Goals

- A `--project-root` supplied before the subcommand is honoured by every
  subcommand, so `bin/hooks-daemon`'s anchoring contract is true.
- A `--project-root` supplied AFTER the subcommand still wins, which is the
  override the wrapper's comment promises a caller.
- End-to-end coverage that asserts the CLI's BEHAVIOUR under the wrapper's
  argv shape, not just the argv the wrapper builds.

## Non-Goals

- Removing the per-subcommand `--project-root` flags. Several document
  distinct defaults and are used directly; this plan makes the two layers
  compose, it does not collapse them.
- Changing how `get_project_path` auto-detects when no root is supplied
  anywhere.

## Tasks

### Phase 1: Reproduce and fix

- [x] ✅ **Task 1.1**: Write the failing test — a global `--project-root`
  before a subcommand that declares its own must reach the command function.
- [x] ✅ **Task 1.2**: Give the global flag its own `dest`, then reconcile
  after parsing: a subcommand-supplied value wins, otherwise the global value
  is used. One place, rather than twenty-five subparser edits that would each
  risk changing a documented per-command default.
- [x] ✅ **Task 1.3**: Cover the precedence both ways round, and cover a
  subcommand that has no `--project-root` of its own so the reconciliation
  cannot regress it. A source guard added here found two more: `deploy-plan-workflow`
  and `agents` declared `--project-root` with `default=Path.cwd()`, which sits in
  the namespace before reconciliation and so pre-empted the anchor entirely.
  Both now default to `None` with the cwd fallback resolved in the command function.

### Phase 2: Close the premise gap in the anchoring suite

- [x] ✅ **Task 2.1**: Extend
  `tests/unit/install/test_bin_wrapper_project_anchoring.py` so at least one
  case runs the REAL CLI under the wrapper's argv shape and asserts which
  project it acted on — the layer its docstring stops one short of. Also
  corrected `_anchored_root`'s docstring, which restated the same false
  premise ("argparse takes the final occurrence, so that is the value that
  actually determines the target").

## Success Criteria

- [ ] `cli --project-root <R> plan-qa --sweep` and
  `cli plan-qa --sweep --project-root <R>` agree, for a root with no plan tree.
- [ ] A subcommand-level `--project-root` still overrides a global one.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Discovered while building Plan 00373's QA gate: the gate's own live probe
  disagreed with its unit tests, and the CLI entry path was the reason.
- `05d526be` — Phase 1: split dest + reconciliation, the two cwd defaults
  removed, source guard against their return.
