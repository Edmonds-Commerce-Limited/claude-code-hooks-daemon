# Callout: the documented `plugins:` examples were unloadable

**Plan**: 00426
**Audience**: operators

Every `plugins:` example this project ships has been corrected, and a test now
validates them against the model that has to accept them.

If you copied a `plugins:` block from `docs/guides/CONFIGURATION.md`,
`examples/basic_setup/hooks-daemon.yaml` or the commented example in
`.claude/hooks-daemon.yaml.example`, it would have been rejected at config load.
Two different problems were in play:

- the config template showed a `type`/`class`/`events` shape that does not parse
  at all — it predates the current schema;
- the guide and the basic-setup example both omitted `event_type`, which is
  **required** on every plugin entry and has no default.

Nothing about the plugin system itself changed: `event_type` was always
required. Only the examples were wrong, and they had drifted unnoticed because
both YAML copies are commented out, so no config validation ever parsed them.

If you have a working `plugins:` block, it already carries `event_type` or it
would not be loading — no action needed.
