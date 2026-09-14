# Callout: an unreadable config no longer takes down the event

**Plan**: 00405
**Audience**: everyone

**Robustness fix.** Secret redaction resolves its word-list path once per
process, and that resolver reads your `.claude/hooks-daemon.yaml`. It was
documented as never raising — every caller is a leak-vector site on a live path
— but it caught only `OSError` and `RuntimeError`, and pydantic's
`ValidationError` is a `ValueError`. A config holding a single key the
installed schema does not recognise therefore escaped that boundary and failed
the event being routed.

Two ways to hit it, and the commoner one is the duller one. A **syntax error** —
a stray tab, an unclosed quote — raises `yaml.YAMLError`, which derives from
`Exception` rather than `ValueError` and so slipped past the same boundary. A
**version skew** does it too: a legacy spelling the schema has since moved, or a
key from a newer daemon than the one installed. Either way the config was merely
unreadable, and the cost was the tool call.

Malformed YAML is now reported as a configuration error by `Config.load` itself,
so it leaves by the same door as an unsupported file extension, and the JSON
path already behaved that way.

An unusable config now makes redaction inert, which is what its contract always
promised. Nothing changes for a config that validates.

Inert is not free, so it is logged at WARNING rather than debug: with no terms
resolved, neither redaction nor the sensitive-content guard has anything to
match. That is a real weakening, and trading a crash for it is only defensible
if whoever can fix the config is told. Its siblings — no word list configured,
file unreadable — stay quiet, because those mean "nothing to do" rather than
"something is broken".

Worth knowing if you ever chase this class of failure: the resolver caches for
the life of the process, so whichever event is routed FIRST pays the cost and
every later one is silently fine. That is what made this look like a
test-ordering quirk for as long as it did.
