# Callout: list every exception, probe one handler alone, and the disable footer asks why

**Plan**: 00484
**Audience**: operators

Three small changes to how exceptions to a guard are handled.

`hooks-daemon exceptions [--json]` lists what exempts something from a guard, with the reason each carries: `exclude_paths` and `extra_whitelist` entries (a reason is read from the raw config, because loading drops it), handlers set to `enabled: false` or `mode: warn`, `MUST_EXCEED_*_BECAUSE` hatches in tracked files, and the QA exception files. An entry with nowhere to write a reason shows `(no reason)`.

`hooks-daemon probe <event> --only <handler>` runs that one handler instead of the whole chain, so a detector can be exercised alone. It is honoured only for a probe-class source; an unknown handler name is refused rather than answered with an allow.

Every deny's `To disable:` footer now reads `(set enabled: false and record why beside it)`. Reasons on config exceptions stay optional, and under `daemon.strict_mode` a plain string is a warning, not an error. Nothing to do on upgrade.
