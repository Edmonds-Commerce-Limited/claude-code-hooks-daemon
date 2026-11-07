# Callout: the ccy supervisor finds hooks-screen by host architecture

**Plan**: 00569
**Audience**: client projects

The ccy supervisor used to look for the `screen/build.sh` output under a name pinned to `x86_64-unknown-linux-musl`, whatever the CPU. It now derives the target from the host architecture: x86_64/amd64 and aarch64/arm64, both on musl. An unsupported architecture skips that candidate (the `CCY_HOOKS_SCREEN` override and `untracked/bin/hooks-screen` still apply), and the fail-open note in the supervisor log names the architecture and the build it searched for. `screen/build.sh` defaults `SCREEN_TARGET` from `uname -m` the same way and refuses an unknown architecture. A client that excluded the deployed supervisor from its QA because of the pinned triple can drop that exclude (reported as issue #174).
