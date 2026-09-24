# Callout: `daemon.strict_mode` now actually reaches the daemon

**Plan**: 00466
**Audience**: operators, security reviewers

`DaemonController.process_event` read `self._config.strict_mode`, and
`self._config` is never populated by the real daemon startup path — every
`get_controller()`-based daemon starts a bare `DaemonController()` and
threads individual config slices into `initialise()` instead (the same
pattern already used for `chain`/`verdict_log`). So `daemon.strict_mode: true` in `hooks-daemon.yaml` never reached a live daemon: a handler that
raised was always treated as "no match" and the call allowed, in every
install, regardless of the setting.

`strict_mode` now follows the same narrow config-slice DI idiom and is threaded
through `initialise()` from the real startup path
(`_build_initialised_controller`). Independently of `strict_mode`, a handler
tagged both `SAFETY` and `BLOCKING` that raises — from `matches()` or
`handle()` — now always denies, naming the handler and the underlying error:
a safety guard that crashed has not judged the call, so treating that as "no
match" was a silent bypass. A non-`SAFETY`+`BLOCKING` handler under
`strict_mode: false` (the client default) is unchanged.

If your own security review or documentation ever cited "this repository
runs `strict_mode: true`, so a handler crash here denies" as the reason a
defect was not exploitable, re-check that claim — it was false everywhere
before this fix, including in this repository's own dogfooding config.
