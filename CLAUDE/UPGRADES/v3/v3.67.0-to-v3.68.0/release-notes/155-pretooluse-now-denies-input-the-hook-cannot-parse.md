# Callout: `PreToolUse` now denies input the hook cannot parse

**Plan**: 00466
**Audience**: operators

When the bash forwarder could not parse a `PreToolUse` hook input, it
answered with context only, and Claude Code ran the call with no guard
applied. JSON nested about 1000 levels deep is enough, which in practice
means an MCP tool's input. Input slightly less deep, or input that is not
UTF-8, made the forwarder write nothing at all, with the same result. Each of
these is now denied with the reason "Hook input could not be parsed, so no
guard judged this call". This applies to the plain forwarder and to a call
the relay hands over. Other events keep their fail-open answer.

A deny no longer depends on `python3` either. The deny message used
`python3` to name the recovery command, and the forwarder itself runs on
`python3`. With `python3` missing or failing, the hook exited with no answer
and the call ran. It now denies with fixed text. That text says no recovery
command is exempt, because `python3` is also what recognises them, and that a
human must run the launcher.
