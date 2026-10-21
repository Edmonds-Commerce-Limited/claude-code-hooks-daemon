# Callout: the Rust relay is on by default for new installs, and install and upgrade provision it

**Plan**: 00529
**Audience**: operators

A new config, whether from `init-config` or copied from `.claude/hooks-daemon.yaml.example`, now enables the relay: `daemon.transport.relay_enabled: true` with `relay_source: auto`. `auto` builds the relay with `rustc` and the musl target when both are present, and otherwise downloads the digest-verified release asset. Install and upgrade now put the binary in place through one shared script (`scripts/install/relay_provision.sh`) instead of three copies of inline code. When neither route works the output prints a loud banner naming the binary path and the fix (`bin/hooks-daemon transport on`, or how to install `rustc` and the musl target), and repeats the banner just before the final exit so it is the last thing you read. The install or upgrade still completes: the bash transport enforces every rule, the relay is only the fast path. The SessionStart `relay_binary_checker` and the `status` WARNING report the same condition afterwards.

Existing configs: an explicit `relay_enabled: false` is kept. A config with no `transport` block adopts the relay at its next upgrade through the example merge (a coordinator ruling the owner can overturn). A partial `transport` block, such as one naming only `nc_enabled`, is kept whole, so the relay stays off until you add `relay_enabled: true`. To opt out, set `daemon.transport.relay_enabled: false`. The model default in code is unchanged. (reported as issue #131)
