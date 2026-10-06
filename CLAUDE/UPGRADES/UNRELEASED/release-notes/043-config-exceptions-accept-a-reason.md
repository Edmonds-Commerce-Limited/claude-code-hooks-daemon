# Callout: `exclude_paths` and `extra_whitelist` entries can carry a reason, and `strict_mode` asks for one

**Plan**: 00484
**Audience**: client projects

An entry of `exclude_paths` (project-wide `daemon.exclude_paths` and any handler's `options.exclude_paths`) or of `extra_whitelist` may now be written either as the plain string you already have, or as a mapping: `{pattern: "vendor/**", reason: "third-party code we do not edit"}`. Handlers receive the same plain pattern either way, so behaviour is unchanged. A mapping whose reason is a placeholder (`tbd`, `because`, `n/a`, an empty string and similar), or that has no `pattern` or an unknown key, is a config validation error. That cannot affect an existing config, because the mapping form could not be loaded before.

With `daemon.strict_mode: true`, a plain string in any of these lists is reported as a config problem: a warning in the daemon log and a line in the SessionStart config-problem advisory naming the list and the entry. The config still loads and nothing is denied, since a missing reason is not a dangerous config. A post-upgrade task describes converting the entries. Requiring a reason for every project is planned for the next major release.

The session-start config-drift report compares exclusions by pattern, so rewriting a plain entry into the mapping form is not reported as a widened exclusion.
