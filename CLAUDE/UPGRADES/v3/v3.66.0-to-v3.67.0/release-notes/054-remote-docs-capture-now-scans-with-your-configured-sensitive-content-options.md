# Callout: `remote-docs` now scans captures with your configured sensitive-content options

**Plan**: 00466
**Audience**: client projects

`hooks-daemon remote-docs add` and `refresh` scan a fetched page before writing
it, but they built the `sensitive_content` handler without its configured
options. So the scan applied none of your `public_patterns`, and it read your
secret word list only when the list sat at the default path and the daemon's
project context happened to be initialised. Captures and refreshes now scan
with the project's configured patterns and word list, wherever that list lives,
and refuse a page that matches. Documents vendored with an earlier version were
never checked against your public patterns. `remote-docs refresh --all`
re-fetches each one through the new scan and names every document whose
upstream content matches. It leaves that stored copy untouched, so fix those
copies yourself.
`hooks-daemon check` also now probes `lint_on_edit` with its configured
`languages` and your `daemon.languages`, so it no longer reports missing
extended linters for languages you do not lint.
