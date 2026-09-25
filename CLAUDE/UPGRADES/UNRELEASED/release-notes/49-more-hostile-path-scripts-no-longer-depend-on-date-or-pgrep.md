# Callout: more hostile-PATH scripts no longer depend on `date` or `pgrep`

**Plan**: 00466
**Audience**: operators

Plan 00466 N1 fixed one place where a hostile or stripped `PATH` (the
bootstrap scenario these scripts exist to survive) silently mis-timed a
watchdog: `resolve_venv.sh`'s probe used `sleep`, and with none on `PATH`
the watchdog fell straight through to killing a healthy candidate. A DBF
sweep for the same class found the same hazard for `date` and `pgrep`
across `venv_bootstrap.sh`, `scripts/install/venv.sh`,
`scripts/install/daemon_control.sh`, `config_preserve.sh`, `rollback.sh`
and `settings_deploy.sh` — a value computed from an unreachable `date`
was embedded, unchecked, into a timeout comparison or a build-start
timestamp, and `pgrep`'s absence silently answered "daemon not running".

A new shared library, `scripts/lib/portable_time.sh`, gives every such
script a PATH-lookup-free way to get the time (bash's own `printf '%(...)T'` builtin on bash >= 4.2, `date` as the bash-3.2/macOS fallback,
a loud failure only when neither is available), and `daemon_control.sh`'s
process check now falls back to a pure-bash `/proc` scan when `pgrep` is
unreachable. Seven instances fixed; none silently guesses a wrong answer
anymore.
