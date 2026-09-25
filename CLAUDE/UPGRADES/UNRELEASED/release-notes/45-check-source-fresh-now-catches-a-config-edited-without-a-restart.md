# Callout: check-source-fresh now catches a config edited without a restart

**Plan**: 00415
**Audience**: everyone

A running daemon binds its config at startup, the same as its code, but
`bin/hooks-daemon check-source-fresh` compared only the code. So after an edit
to `.claude/hooks-daemon.yaml` with no restart, it reported FRESH while every
live dispatch was still judged against the old config. The daemon now reports
a `config_fingerprint` of the resolved config model beside `source_fingerprint`.
`check-source-fresh`, the smoke test and the acceptance harness read both
through one verdict, and a STALE message says whether the code, the config or
both moved. A comment-only edit is not drift. An on-disk config that no longer
loads gives a verdict that says so rather than a crash. The remedy is still
`bin/hooks-daemon restart`.
