# N9 — a test that passes in its file and fails on its own

Supporting evidence for [N9](PLAN.md). The order dependence was the SYMPTOM;
the cause is a daemon defect on a live path, and it is fixed.

## The failure

```text
tests/integration/test_handler_config_blocking.py::
  TestMarkdownOrganizationHandlerIntegration::test_planning_mode_redirect_e2e

ValidationError: 2 validation errors for Config
  Extra inputs are not permitted [input_value='CLAUDE/PlanWorkflow.md']
  Extra inputs are not permitted [input_value='CLAUDE/Plan']
```

## The stack that settled it

Six hypotheses were disproved before anyone read the traceback, which is the
lesson worth keeping: the frames were available the whole time.

```text
tests/integration/test_handler_config_blocking.py:698   (routing an event)
src/claude_code_hooks_daemon/core/router.py:178
src/claude_code_hooks_daemon/utils/secret_redaction.py:241  get_active_secret_terms
src/claude_code_hooks_daemon/utils/secret_redaction.py:215  Config.load_or_default
src/claude_code_hooks_daemon/config/models.py:2147          ValidationError
```

Two details in it are load-bearing:

- The error's `loc` is `handlers.pre_tool_use.track_plans_in_project`, one
  level ABOVE where the test nests the key. That is not a hoist: the coercion
  runs as a `field_validator` on the event field and calls
  `HandlerConfig.model_validate` itself, so the inner error's `loc` is appended
  to the FIELD's and the handler name never appears. Reading the path literally
  sent the first search to the wrong model.
- `ConfigLoader.load`, which the test calls, is a bare `yaml.safe_load` with no
  validation and no cache. The `Config.load` in the traceback is reached from
  somewhere the test never mentions.

## The defect

`get_active_secret_terms()` is documented "never raises", and every caller is a
leak-vector site on a live path — the router, the front controller's error log,
payload capture, the transcript archiver. `_resolve_active_path` backed that
promise with `except (OSError, RuntimeError)`.

Pydantic's `ValidationError` subclasses `ValueError`, which is neither. So a
config carrying one key the installed schema does not recognise — a legacy
spelling, or a newer daemon's — escaped the boundary and failed whatever event
was being ROUTED. `Config.load` raises a plain `ValueError` for an unsupported
suffix too, by the same gap.

Fixed by adding `ValueError` to the caught set: an unusable config makes the
feature inert, which is what the docstring already promised.

**The trade-off, made visible rather than hidden.** Inert means NO terms are
resolved, so neither redaction nor the sensitive-content guard has anything to
match — the fix swaps a loud crash for a quietly weakened guard. That is the
right trade (the daemon's own startup validation is the loud gate; this is a
secondary read on a best-effort path) but only if it is not silent, so this
branch logs at WARNING while its siblings stay at debug. A missing word list
means "nothing to do"; an unreadable config means "something an operator can
fix".

## Why it only showed in isolation

`_resolve_active_path` caches for the process lifetime
(`_ACTIVE_PATH_RESOLVED`), and no autouse fixture resets it — the reset hatch
is referenced by three test modules for their own tests, and
`tests/integration/test_handler_config_blocking.py` is not one of them.

So whichever test routes an event FIRST pays the resolution cost:

- **In the file**: a predecessor routes first, against a valid config. The
  cache is set, and this test never re-reads anything.
- **Alone**: this test is first, and by then it has deliberately written a
  config in the LEGACY shape (`track_plans_in_project` at handler level rather
  than under `options:`) into the fixture project.

That cache — not `ProjectContext` — was the carrier, which is why the obvious
reading of `reset_project_context` came out wrong: it resets the singleton
after each test, so a predecessor leaves it uninitialised exactly as a fresh
process does.

## Ruled out along the way

In a fresh process, `Config.model_validate` REJECTS the test's config dict
after every one of these, so none of them is the mechanism:

| state reached first                                | verdict  |
| -------------------------------------------------- | -------- |
| nothing                                            | REJECTED |
| `HandlerRegistry().discover()`                     | REJECTED |
| `registry.register_all(EventRouter())`             | REJECTED |
| `registry.register_all(EventRouter(), config=…)`   | REJECTED |
| `ProjectContext.initialize(...)`                   | REJECTED |
| re-discover + re-register with ProjectContext live | REJECTED |

Order randomisation is out too: no ordering plugin is active and repeated
identical invocations agree.

Every one of those is consistent with the real cause — the config is rejected
in all of them, and always was. What varied was never the validation; it was
whether anything asked for it.

## Verification

- A unit reproduction was written first and ERRORED with that exact
  `ValidationError` rather than failing an assertion — the defect stated
  exactly. It passes with the fix.
- The isolated test now passes on its own, and the enclosing class is 5/5
  where it was 4/5.
