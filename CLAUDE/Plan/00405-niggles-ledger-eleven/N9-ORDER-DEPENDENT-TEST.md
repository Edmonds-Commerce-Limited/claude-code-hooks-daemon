# N9 — a test that passes in its file and fails on its own

Supporting evidence for [N9](PLAN.md). The mechanism is NOT yet identified;
what follows is what has been established and, more usefully, what has been
ruled out.

## The failure

```text
tests/integration/test_handler_config_blocking.py::
  TestMarkdownOrganizationHandlerIntegration::test_planning_mode_redirect_e2e

ValidationError: 2 validation errors for Config
  Extra inputs are not permitted [input_value='CLAUDE/PlanWorkflow.md']
  Extra inputs are not permitted [input_value='CLAUDE/Plan']
```

Raised at `config/models.py:2147`, the `cls.model_validate(data)` inside
`Config.load`.

## Established

- **Deterministic, not flaky.** The enclosing class alone fails 1 of 5, on
  three consecutive identical runs.
- **The whole file passes 18/18**, and the full suite passes 30/30, so it is
  not a symptom of any recent change.
- **It genuinely passes when preceded** — `-v` reports PASSED, not SKIPPED or
  XFAIL.
- **Which predecessor matters**: any single test from
  `TestTerminalHandlerBlocking`, `TestEndToEndBlockingScenarios` or
  `TestConfigPriorityOverride` is enough. `TestHandlerConfigLoading` is not.
- **The test's own ordering is inverted**: it calls `ConfigLoader.load` at line
  668 and `registry.discover()` at line 671, so it validates before it
  discovers. That is what first suggested a discovery dependency.

## Ruled out

In a fresh process, `Config.model_validate` REJECTS the test's exact config
dict after every one of these:

| state reached first                                | verdict  |
| -------------------------------------------------- | -------- |
| nothing                                            | REJECTED |
| `HandlerRegistry().discover()`                     | REJECTED |
| `registry.register_all(EventRouter())`             | REJECTED |
| `registry.register_all(EventRouter(), config=…)`   | REJECTED |
| `ProjectContext.initialize(...)`                   | REJECTED |
| re-discover + re-register with ProjectContext live | REJECTED |

Order randomisation is also out: no ordering plugin is active and repeated
identical invocations agree.

So an earlier TEST mutates shared state in a way none of the five obvious
candidates reproduces.

## What is left

The conftest fixture interaction — `tests/integration/conftest.py`'s
`project_context`, and the function-scoped autouse fixtures in
`tests/conftest.py`. Note that `reset_project_context` resets the singleton
AFTER each test, so a predecessor leaves ProjectContext uninitialised, the same
as a fresh process; that makes the obvious reading of it wrong too.

Deliberately not guessed at. The guess that looked certain in
[N3](N3-IMPORT-EXEMPTION.md) was true and was still the wrong explanation, and
writing it down would have closed the entry against the wrong cause.
