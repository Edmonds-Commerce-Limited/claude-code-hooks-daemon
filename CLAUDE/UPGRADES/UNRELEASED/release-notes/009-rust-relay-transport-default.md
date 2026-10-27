# Callout: the Rust relay is now the default hook transport on Linux

**Plan**: 00554
**Audience**: everyone

Hooks now travel through the compiled Rust relay by default instead of the bash and python3 forwarder, which cuts the per-hook cost from tens of milliseconds to a few. The default depends on the host. A config with no `daemon.transport.relay_enabled` key resolves to relay ON where the host can run it and to the legacy transport everywhere else:

| Host            | Default | How the binary arrives                                 |
| --------------- | ------- | ------------------------------------------------------ |
| Linux x86_64    | relay   | downloaded from the matching release (digest-verified) |
| Linux aarch64   | relay   | built from source (needs a musl-capable `rustc`)       |
| macOS and other | legacy  | none; the relay is never built or downloaded           |

The install or upgrade provisions the binary (`relay_source` now defaults to `auto`: build when a musl toolchain is present, otherwise download where a release binary exists). The fallback ladder is unchanged: if the binary is missing or unusable, the call falls through to the legacy transport and the session-start check warns and starts a repair. On a host that cannot run the relay, an explicit `relay_enabled: true` is still honoured and warns, with `bin/hooks-daemon transport off` as the fix.

To keep the legacy bash and python3 transport, set `daemon.transport.relay_enabled: false` in `.claude/hooks-daemon.yaml`, or run `bin/hooks-daemon transport off`; an explicit `false` is always respected. Only `true` and `false` are valid values: `relay_enabled: null` is a config validation error. A config file the loader cannot read also falls back to the legacy transport. If the relay misbehaves on your host, opt out as above and report it on the issue tracker.

Two fixes ship with this change and also apply to clients who had already opted in to the relay:

- **bash 3.2 safety**: the generated forwarders and the relay guard no longer use bash 4-only constructs (`${v,,}` lower-casing, `read -N`), so they run on the bash 3.2 that macOS ships.
- **wrong-platform binaries**: a relay binary built for another OS or architecture (for example one copied from a different machine) is now detected as defective and removed, rather than left in the exec path; the install then provisions the right one or reports why it cannot.
