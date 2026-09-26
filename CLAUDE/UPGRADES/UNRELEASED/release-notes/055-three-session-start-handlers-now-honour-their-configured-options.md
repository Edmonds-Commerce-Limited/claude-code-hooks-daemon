# Callout: three session-start handlers now honour their configured options

**Plan**: 00466
**Audience**: client projects

Three session-start handlers read their options from a place the daemon never
filled, so every configured value was ignored and the default applied:

- `hook_registration_checker`: `auto_migrate_settings: false` and
  `auto_repair_registrations: false` did not stop the handler rewriting
  `settings.json`.
- `skill_opportunity_detector`: `check_interval_days` and the other scan
  options were ignored.
- `version_check`: `cache_ttl_hours` was ignored.

All three now read the options you configure. If you set either
`hook_registration_checker` option to `false`, it takes effect from this
release, so check that `settings.json` is the way you want it. The reference
now documents `version_check`'s `cache_ttl_hours`. A test now builds every
handler with a non-default value for each documented option and fails if the
handler ignores one.
