# Callout: a handler option that names a method is refused, and a broken config no longer switches redaction off

**Plan**: 00483
**Audience**: everyone

A handler option whose name matches a method of the handler, a read-only property, or that starts with `_` is no longer applied. Options are set as `self._<name>`, so a stale or renamed option such as `human_docs_dir` (markdown_organization) or `pauses_path` (the cron handlers) used to overwrite the handler's own method with the option's value, and the handler then crashed. Such an option is now withheld, the handler keeps its default, and the refusal is reported at session start with the handler's other invalid options. Remove the option from `.claude/hooks-daemon.yaml`.

A project config that fails to load (a typo, a key the schema does not know) no longer turns secret redaction off for logs and captured payloads. Redaction falls back to the word list path named in the raw config, else the default path, and logs a warning until the config validates again. A Stop that finds a broken config also reuses one cached default config instead of rebuilding it (about 50 ms) each time.
