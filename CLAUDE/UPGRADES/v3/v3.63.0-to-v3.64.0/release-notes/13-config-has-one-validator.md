# Callout: the config package has one validator, and it covers every wired event

**Plan**: 00172
**Audience**: handler authors

`claude_code_hooks_daemon.config` no longer exports `ConfigSchema`, the
JSON-schema validator that sat beside `ConfigValidator`. It was never run by
the daemon, and its hand-listed `handlers` section named three event types
while the daemon wires thirty-one, so a config it accepted and a config the
daemon accepted were two different things. Anything that imported it should
call `ConfigValidator.validate` or `ConfigValidator.validate_and_raise`,
which is what the daemon runs at startup.

That validator, the `HandlersConfig` model and `PluginConfig.event_type` now
all take their event-type coverage from the wired-event catalogue, so a
`handlers.<event>` section or a plugin targeting any wired event is accepted,
and a test locks each of them to the catalogue. The two documentation
generators that deliberately look at a narrow set of events say so in
place, so a future coverage audit can rule them out without re-deriving why.
