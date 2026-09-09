# Callout: a stdout-only sed deny explains itself, and validate-config works

**Plan**: 00362
**Audience**: client projects

`sed -n 'N,Mp' file` is still denied by `sed_blocker` -- that is deliberate,
since `-n` and `-i` differ by one character -- but the deny message now says
so and hands over the two working replacements (`Read` with `offset`/`limit`,
or `awk 'NR>=N && NR<=M' file`), and the handler reference no longer claims
read-only sed is allowed in general. Separately, `hooks-daemon validate-config` is accepted as an alias of `config-validate`, the config path
defaults to the project's `.claude/hooks-daemon.yaml` when omitted, and a test
now checks every verb the skill text routes against the CLI parser.
