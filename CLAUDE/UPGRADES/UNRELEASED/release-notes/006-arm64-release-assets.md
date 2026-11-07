# Callout: releases now ship attested arm64 relay and hooks-screen binaries

**Plan**: 00572
**Audience**: client projects

Each release now carries the relay and hooks-screen for both x86_64 and aarch64 (`hooks-relay-<triple>`, `hooks-screen-<triple>`), built natively on each architecture's GitHub runner, covered by one `SHA256SUMS` and attested with GitHub build provenance (`gh attestation verify <file> --repo Edmonds-Commerce-Limited/claude-code-hooks-daemon`). With `daemon.transport.relay_source: download` (or `auto` without a musl toolchain), an arm64 Linux host now downloads its own digest-verified relay instead of having to build it from source; any other architecture is still refused before anything is fetched. Building from source remains the first-class route.
