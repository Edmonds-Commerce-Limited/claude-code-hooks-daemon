# Session state contract

A tool that supervises sessions (a coordinator that wants to know whether a
seat is working, idle, blocked or rate-limited) reads the daemon through
three machine-readable outputs, never through the files under `untracked/`.
Those files are internal and may change layout in any release; the outputs
below are the contract.

| Output                                            | Schema                |
| ------------------------------------------------- | --------------------- |
| `hooks-daemon session-state --json --session ID`  | `session-state`       |
| `hooks-daemon session-state --watch --session ID` | `session-state-watch` |
| `hooks-daemon mode-history --json`                | `mode-history`        |

The modes themselves are described in [SessionModes.md](../../CLAUDE/SessionModes.md).

## Versioning rule

- Versions are semver. Every document carries `schema_version` (for example `"1.0.0"`).
- A new optional field is a minor bump. Removing a field, renaming it or changing its type is a breaking change and a new major.
- A consumer pins a major, refuses a document whose `schema_version` has another major, and ignores fields it does not know within the major it pinned.
- The current version is `claude_code_hooks_daemon.core.state_schemas.SCHEMA_VERSION`; the pinned major is `SCHEMA_MAJOR`.

## Where the schemas are and how to load them

JSON Schema 2020-12 files ship inside the package, in
`claude_code_hooks_daemon/schemas/` (`mode-history.json`, `session-state.json`,
`session-state-watch.json`). Each has a versioned `$id` ending in
`<name>/<version>.json`. Load one with:

```python
from claude_code_hooks_daemon.core.state_schemas import load_schema, schema_registry

schema = load_schema("session-state")   # dict; ValueError on an unknown name
registry = schema_registry()            # resolves cross-schema $ref by $id
```

`session-state-watch` references `session-state`, so validate the watch line
with `Draft202012Validator(schema, registry=schema_registry())`.

## `session-state` document

One JSON line. Fields: `schema_version`, `session_id`, `observed_at`, `modes`
(each with `since`-style `entered_at`), `last_turn_edge` (`start`, `stop` or
`stop_failure` with its `error`), `usage` (`five_hour` and `seven_day`, each
`used_percentage`, `resets_at`, `observed_at`, or `null`), `limit_reset` and
`usage_pause`. A session with no records gets `null` fields, not an error. The
exit code is 1 only when the daemon is down or errs.

### `resets_at` is optional

A `rate_limit` stop is recorded without a reset time. The daemon joins it, at
read time, to the usage window that is at its limit (95 percent or more; the
later reset when both are), and reports it as `limit_reset`
(`{"window": ..., "resets_at": ...}`). Without a live usage snapshot (a plan
that reports no usage, or a window that has already rolled over) `limit_reset`
is `null`: the reset time is absent, never guessed. A consumer must treat it as
optional and fall back to its own backoff.

## `--watch` line format

`session-state --watch` prints one compact JSON object per line, flushed, and
runs until interrupted (exit 0). The first line is the full state; later lines
appear only when a state field changed. A usage `observed_at` heartbeat alone
is not a change. A line is:

```json
{"schema_version": "1.0.0", "changed": ["last_turn_edge"], "state": { ...a full session-state document... }}
```

`changed` names the top-level fields that differ from the previous line (every
field on the first line). `--interval SECONDS` sets the check rate (default 2).
The stream ends, with exit 1, if the daemon goes away.

## Consumer example

```python
import json
import subprocess

from jsonschema import Draft202012Validator

from claude_code_hooks_daemon.core.state_schemas import load_schema, schema_registry

PINNED_MAJOR = 1
validator = Draft202012Validator(load_schema("session-state"), registry=schema_registry())

raw = subprocess.run(
    ["hooks-daemon", "session-state", "--json", "--session", "SESSION_ID"],
    check=True, capture_output=True, text=True,
).stdout
state = json.loads(raw)
if int(state["schema_version"].split(".")[0]) != PINNED_MAJOR:
    raise RuntimeError(f"unsupported schema_version {state['schema_version']}")
validator.validate(state)  # optional; the pin check above is the contract
reset = state["limit_reset"]  # None: no reset time known
```

A consumer that does not run Python reads the same schema files from the
installed package and performs the same major check.

## Cost

One call is cheap enough for every hook edge; the measurement is in
`CLAUDE/Plan/00601-session-state-contract-and-schemas/FINDINGS.md`.
