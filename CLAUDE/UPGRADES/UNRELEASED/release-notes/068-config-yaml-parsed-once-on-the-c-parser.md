# Callout: the daemon parses its config once per start, on the C YAML parser

**Plan**: 00495
**Audience**: client projects

The daemon start read `.claude/hooks-daemon.yaml` four times with PyYAML's pure-Python `SafeLoader`: once to load the config, once in the controller's config validation, and once in each of the two config-driven asset syncs (agent assets, directory-role rules), which each rebuilt the whole config model as well. The file is now parsed once and the loaded config is reused by all four steps. Config validation still runs on the parsed document, so a config the validator rejects still starts the daemon in degraded mode exactly as before.

The parse uses PyYAML's `CSafeLoader` where PyYAML was built with libyaml, and falls back to `SafeLoader` where it was not. Both are safe loaders; the unsafe loader is never used. Start-up CPU on this repository's own 87 KB config fell from about 1.9 s to about 1.2 s (median of 6 interleaved runs). A config nested deeply enough to overflow libyaml's C stack (thousands of brackets, or a line led by thousands of indentation columns or `-`/`?`/`:` indicators) is parsed by the pure-Python loader instead and reported as an invalid config rather than crashing the daemon. Nothing needs to change in your config.
