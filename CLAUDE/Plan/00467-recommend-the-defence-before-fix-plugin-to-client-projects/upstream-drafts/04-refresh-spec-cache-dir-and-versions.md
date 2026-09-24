# Draft: refresh-spec.bash, where its cache lands and the versions it prints

**Target**: `Defence-Before-Fix/claude-plugin`
**Status**: draft, not filed.

- Part 1 rests on Claude Code's plugins reference, quoted below. We have not observed it in a
  live session: the headless probe could not log in.
- Part 2 is reproduced.

## Title

`refresh-spec.bash` never sees `CLAUDE_PLUGIN_DATA`, so the spec cache goes to `~/.cache`; and
the prompt's version prints as `-`

## Part 1: the cache lands in `~/.cache`, not the plugin data directory

SKILL.md step 0 runs `bash "${CLAUDE_SKILL_DIR}/scripts/refresh-spec.bash"`. The script picks its
cache from the environment (lines 44-51): `$CLAUDE_PLUGIN_DATA/spec` first, then
`$XDG_CACHE_HOME/defence-before-fix/spec`, then `$HOME/.cache/defence-before-fix/spec`.

The Claude Code plugins reference ("Environment variables") says of `CLAUDE_PLUGIN_ROOT`,
`CLAUDE_PLUGIN_DATA` and `CLAUDE_PROJECT_DIR`:

> They aren't present in the environment of commands Claude runs through the Bash tool, in the
> main session or in a subagent. In plugin content, write the placeholder instead, and Claude
> Code substitutes the path inline when it loads the content.

It also says skill and agent content substitute the placeholder "anywhere the placeholder
appears".

So the first branch never applies when the skill runs the script. Every run caches in
`$XDG_CACHE_HOME` or `~/.cache/defence-before-fix/spec`. This has three consequences:

- The README's statement that the script fetches "into the plugin's data directory" is not what
  happens.
- Uninstalling the plugin deletes `${CLAUDE_PLUGIN_DATA}` (plugins reference, uninstall section)
  but leaves the `~/.cache` copy behind.
- Two plugin versions, or two harnesses sharing the Agent Skills folder, share one cache.

**Reproduction**: enable the plugin and run `/dbf` once on anything. Then check
`ls ~/.claude/plugins/data/defence-before-fix-defence-before-fix/spec ~/.cache/defence-before-fix/spec`.
The data directory is absent, because it is created on first reference and nothing references it.

**Suggested direction**: pass the directory as an argument, so the command still matches the
skill's `allowed-tools` pattern (`Bash(bash ${CLAUDE_SKILL_DIR}/scripts/refresh-spec.bash *)`).
For example, `bash "${CLAUDE_SKILL_DIR}/scripts/refresh-spec.bash" --cache-dir "${CLAUDE_PLUGIN_DATA}/spec"`,
with a new `--cache-dir` option. An environment-variable prefix would fail that pattern and
prompt for permission. Keep the script's fallbacks for harnesses that leave the placeholder
unsubstituted, and treat a literal `${CLAUDE_PLUGIN_DATA}` value as unset.

## Part 2 (reproduced): `project-prompt.md` and `register.json` print version `-`

The output is tab-separated. The paths below are shortened.

```
$ bash skills/dbf/scripts/refresh-spec.bash --offline
SPEC.md            vendored  1.0.1  .../SPEC.md
DETECTOR-SPEC.md   vendored  1.0.0  .../DETECTOR-SPEC.md
TOOLING-SPEC.md    vendored  0.2.0  .../TOOLING-SPEC.md
project-prompt.md  vendored  -      .../project-prompt.md
register.json      vendored  -      .../register.json
```

`versionOf` (lines 71-80) matches only a `**Version**:` line. The project prompt states its
version in prose on line 3 ("method specification 1.0.1"), and the register carries a per-tool
`checked` date but no version. REPORT-TEMPLATE's "Specification followed" asks for the version
"as printed by the refresh script". SPEC.md's line covers the method version. But the copy of
the prompt the agent actually followed, and the register it chose a tool from, cannot be
identified from the output.

**Suggested direction**: print the method version the prompt names, and a content hash or the
`SPEC-VERSION` commit for both files. That way the report can say exactly which copy was read.
