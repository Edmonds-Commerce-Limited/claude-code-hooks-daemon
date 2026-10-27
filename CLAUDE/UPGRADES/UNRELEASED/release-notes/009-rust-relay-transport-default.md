# Callout: the Rust relay is now the default hook transport

**Plan**: 00554
**Audience**: everyone

Hooks now travel through the compiled Rust relay by default instead of the bash and python3 forwarder, which cuts the per-hook cost from tens of milliseconds to a few. A config with no `daemon.transport.relay_enabled` key picks the relay up at its next install or upgrade, which builds or downloads the binary (`relay_source` now defaults to `auto`). The fallback ladder is unchanged: if the binary is missing or unusable, the call falls through to the legacy transport and the session-start check warns and starts a repair.

To keep the legacy bash and python3 transport, set `daemon.transport.relay_enabled: false` in `.claude/hooks-daemon.yaml`, or run `bin/hooks-daemon transport off`; an explicit `false` is always respected. A config file the loader cannot read also falls back to the legacy transport. If the relay misbehaves on your host, opt out as above and report it on the issue tracker.
