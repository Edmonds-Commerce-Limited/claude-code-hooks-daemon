# Callout: `exclude_paths` and `extra_whitelist` entries can carry a reason, and `strict_mode` requires one

**Plan**: 00484
**Audience**: operators

An entry of `exclude_paths` (project-wide `daemon.exclude_paths` and any handler's `options.exclude_paths`) or of `extra_whitelist` may now be written either as the plain string you already have, or as a mapping: `{pattern: "vendor/**", reason: "third-party code we do not edit"}`. Handlers receive the same plain pattern either way, so behaviour is unchanged. A placeholder reason (`tbd`, `because`, `n/a`, an empty string and similar) is a config validation error, and so is a mapping with no `pattern`, no `reason` or an unknown key.

With `daemon.strict_mode: true`, a plain string in any of these lists is a config validation error that names the list and the entry, so every exception in a strict project says why it exists. Projects without `strict_mode` are unaffected. Requiring a reason for every project is planned for the next major release.

The session-start config-drift report compares exclusions by pattern, so rewriting a plain entry into the mapping form is not reported as a widened exclusion.
