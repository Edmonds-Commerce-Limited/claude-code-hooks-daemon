# Callout: the relay clamps an old forwarder's timeout, and a hook writes one answer

**Plan**: 00466
**Audience**: operators

- `daemon.transport.timeout_seconds` above 45 is clamped to 45 when the
  config loads, but a forwarder deployed earlier still passes its old
  `--timeout-ms` to `hooks-relay`. The relay now applies the same 45-second
  cap itself and says so on stderr. Upgrading regenerates the forwarders
  with the clamped value.
- When the hook's `python3` transport failed after it had already written
  an answer, a `PreToolUse` hook also wrote the fixed deny, so Claude Code
  received two JSON documents. The transport's output is now captured
  first: a `PreToolUse` call whose transport failed gets only the deny, and
  every other answer is passed on byte for byte.
