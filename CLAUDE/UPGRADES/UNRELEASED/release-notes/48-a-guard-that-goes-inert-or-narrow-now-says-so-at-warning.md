# Callout: a guard that goes inert or narrow now says so at WARNING

**Plan**: 00466
**Audience**: operators

`hooks-daemon restart` now warns that a QA run is in progress when the run's
lock is held but its pid cannot be read (it names the holder as `unknown`).
Before, it said nothing. When it cannot tell whether a run holds the lock, it
logs that at WARNING instead of staying silent. The daemon log also gets a
WARNING when a guard is quietly weaker than your config says: a
`sensitive_content` public pattern or a `flaggable_content_channel_guard`
shape that does not compile (named, once), a project config that cannot be
read and so leaves secret redaction inert, and a staged file `staged_lint_gate`
could not lint.
