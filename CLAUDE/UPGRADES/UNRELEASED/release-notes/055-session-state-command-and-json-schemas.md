# Callout: new `hooks-daemon session-state` command, and versioned JSON Schemas for machine-read output

**Plan**: 00601
**Audience**: client projects

A tool that supervises several sessions can now read one session's state through a documented interface instead of the daemon's internal files:

- `hooks-daemon session-state --json --session ID` prints one JSON line: the session's modes, its last turn edge (`start`, `stop` or `stop_failure` with the error), account usage (`five_hour` and `seven_day` with `used_percentage` and `resets_at`), `limit_reset` and the usage pause. A session with no records gets `null` fields, not an error.
- `hooks-daemon session-state --watch --session ID` prints one JSON line per change, so the consumer does not poll.
- `limit_reset` answers when a rate-limited session can continue. A `rate_limit` stop is recorded without a reset time, so the daemon joins it to the usage window that is at its limit; it is `null` when no live usage reading exists (a plan that reports no usage, or a window that has already rolled over) rather than guessed.
- Every `--json` document, including `mode-history --json`, now carries `schema_version` (semver). `mode-history --json` keeps every field it had.
- JSON Schema 2020-12 files for `mode-history`, `session-state` and the `--watch` line ship inside the package (`claude_code_hooks_daemon/schemas/`), each with a versioned `$id`. Pin the major version and refuse an unknown one; a breaking change is a new major. The daemon's own tests validate its output against these schemas.
