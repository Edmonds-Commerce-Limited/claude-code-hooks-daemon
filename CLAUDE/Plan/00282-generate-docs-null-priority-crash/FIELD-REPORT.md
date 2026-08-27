<!--
GENERALISED FIELD REPORT (imported into this plan folder as a supporting doc).
This report arrived from a client install of this daemon. It has been read in
full and carries no external-project identifiers — it references only this
daemon's own source files, its version, and a generic "client install". It is
NOT an account of work in this repository; it is the reported symptom that
motivated Plan 00282. See PLAN.md for the fix.
-->

# Bug report — `generate-docs` and `generate-playbook` crash when a handler config entry omits `priority`

**Daemon version**: v3.55.0 (git ref `v3.55.0`)
**Python**: 3.13.14
**Install mode**: client install (`.claude/hooks-daemon/`), config schema `version: '2.0'`
**Severity**: high — silently stops resident guidance from regenerating, and blocks a release step

---

## Summary

If **any** handler entry in a client's `.claude/hooks-daemon.yaml` is present but
omits the `priority:` key, both documentation generators abort:

```
ERROR: Failed to generate docs: '<' not supported between instances of 'NoneType' and 'int'
ERROR: Failed to generate playbook: '<' not supported between instances of 'NoneType' and 'int'
```

The failure mode is bad in three ways:

1. **It is silent in normal use.** A `restart` regenerates docs as a side effect
   and does not surface the failure, so `.claude/HOOKS-DAEMON.md` and the
   `<hooksdaemon>` block in the project's `CLAUDE.md` simply stop updating. We
   only noticed because the resident guidance still described v3.53.1 behaviour
   after upgrading to v3.55.0 — i.e. the agent was reading handler guidance that
   no longer matched the handlers actually running.
2. **The error names nothing.** No handler, no key, no traceback — the message
   is the bare `TypeError` string, so there is no way to find the offending
   entry without reading daemon source.
3. **`generate-playbook` is a release step.** `CLAUDE/development/RELEASING.md`
   Step 12.3 runs it, so a config in this state blocks the acceptance-testing
   gate with the same uninformative message.

---

## Root cause

Both generators read the priority with a `.get()` default:

- `src/claude_code_hooks_daemon/daemon/docs_generator.py:298`
  ```python
  priority = handler_config.get(ConfigKey.PRIORITY, instance.priority)
  ```
- `src/claude_code_hooks_daemon/daemon/playbook_generator.py:217`
  ```python
  priority = handler_config.get(ConfigKey.PRIORITY, instance.priority)
  ```

and then sort on it:

- `docs_generator.py:192` — `handlers.sort(key=lambda h: h[3])`
- `playbook_generator.py:314-315` — `tests_by_handler.sort(key=lambda x: x[2])`

The `handler_config` dict comes from a pydantic dump:

- `daemon/cli.py:2305` (playbook) and `daemon/cli.py:2385` (docs)
  ```python
  handlers_dict = config.handlers.model_dump()
  ```

`model_dump()` materialises **unset** fields as an explicit `None` rather than
omitting them, so the `.get()` default is unreachable. Verified in-process
against the installed package:

```
>>> HandlerConfig(enabled=True).model_dump()
{'enabled': True, 'priority': None, 'options': {}}

'priority' in dump      : True
dump['priority']        : None
.get('priority', 56)    : None      # <-- default never applies
```

`instance.priority` is therefore never consulted, `None` reaches the sort key,
and the comparison raises.

### This case is already handled correctly elsewhere

`src/claude_code_hooks_daemon/handlers/registry.py:355-359` — the runtime
dispatch path — gets it right, and its comment shows the class of bug was
already known:

```python
# Override priority from config if specified and not None
# (PyYAML parses 'priority:' with no value as None — Plan 00070)
config_priority = handler_config.get(ConfigKey.PRIORITY)
if config_priority is not None:
    instance.priority = config_priority
```

So handler dispatch is unaffected — only the two generators are. The fix is to
apply the same guard at both sites.

Note the module docstring in `constants/config.py:14-15` recommends the
membership form (`if ConfigKey.PRIORITY in handler_config`), which is **also**
wrong against a `model_dump()` result: the key *is* present, it just holds
`None`. `config/validator.py:423-424` follows that recommendation. That is worth
a look even though it is not what crashes here.

---

## Reproduction

Confirmed end-to-end on this install by removing and restoring the key.

1. In `.claude/hooks-daemon.yaml`, take any enabled handler entry and delete its
   `priority:` line, leaving the entry itself present:

   ```yaml
   handlers:
     session_start:
       git_upstream_checker:
         enabled: true
         # priority: 56          <-- omitted
         options:
           mode: agent-pull
   ```

2. Run either generator:

   ```bash
   .claude/hooks-daemon/bin/hooks-daemon generate-docs
   # ERROR: Failed to generate docs: '<' not supported between instances of 'NoneType' and 'int'   (exit 1)

   .claude/hooks-daemon/bin/hooks-daemon generate-playbook
   # ERROR: Failed to generate playbook: '<' not supported between instances of 'NoneType' and 'int'   (exit 1)
   ```

3. Restore the `priority:` line — both commands exit 0 immediately.

A `priority:` key present with an empty value (`priority:`, which PyYAML parses
as `None`) should reproduce identically, and is the shape Plan 00070 already
names.

---

## Suggested fix

Mirror `registry.py` at both call sites:

```python
config_priority = handler_config.get(ConfigKey.PRIORITY)
priority = config_priority if config_priority is not None else instance.priority
```

Since three sites now need the same rule, a shared helper (next to `ConfigKey`,
or on `HandlerConfig` itself) would suit the project's DRY / single-source-of-truth
standard better than a third copy. Alternatively, dumping with
`model_dump(exclude_unset=True)` — or `exclude_none=True` — would make the
existing `.get()` defaults work as written at every consumer at once; that is the
narrower change if the dumped dict has no other consumer relying on the null keys.

### Secondary: the error swallows its own diagnosis

`daemon/cli.py:2411-2412`:

```python
except Exception as e:
    print(f"ERROR: Failed to generate docs: {e}", file=sys.stderr)
    return 1
```

The bare `TypeError` string reaches the operator with no traceback and no
handler name. Logging the exception (or naming the handler being processed)
would have turned a source-reading exercise into a one-line diagnosis. The
playbook generator does the same.

### Tertiary: a silent failure behind `restart`

Because doc regeneration runs as a side effect of `restart` and its failure is
not surfaced there, a project can run indefinitely on stale resident guidance
with no signal. Worth surfacing the generator's exit status through `restart`,
given that the `<hooksdaemon>` block is what the agent actually reads.

---

## Why dogfooding did not catch it

The daemon's own repository config sets `priority` on its handlers, so the null
never arises there. The trigger is specifically a **client** config where an
entry was hand-written or partially migrated without the key — exactly the gap
`CLAUDE/development/CLIENT-MODE-TESTING.md` warns about. A regression test that
builds a `HandlerConfig` with no priority and asserts both generators still
produce output would close it.

Our workaround was to pin `priority: 56` on the affected entry (the value the
handler already ships with), which restored regeneration.
