# Callout: on an arm64 host, the transport probe now checks for the arm64 musl target

**Plan**: 00572
**Audience**: client projects

The transport probe's "musl toolchain present" answer asked `rustc` for the x86_64 target whatever the host was, so on an aarch64 Linux host it reported the toolchain missing when the aarch64 target was installed, and present when only the x86_64 one was. It now checks the host's own relay target (`aarch64-unknown-linux-musl` on arm64), the same target the build route already used. Found by the new non-blocking arm64 test job in CI.
