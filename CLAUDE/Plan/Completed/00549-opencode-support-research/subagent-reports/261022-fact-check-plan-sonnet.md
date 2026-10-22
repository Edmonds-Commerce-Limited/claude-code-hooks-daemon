# Fact check: Plan 00549 RESEARCH-opencode-extension-surface.md (diff)

Spot-checked the load-bearing claims against /workspace/untracked/repos/opencode. The diff adds a 383-line external-repo research file, so a full line-by-line check was not done.

## REFUTED / qualified

1. "`git describe`: `github-v1.2.27-52-gc93aaae371`" -- plain `git describe` in the clone prints `latest-10161-gc93aaae371`. The quoted string only appears with `git describe --tags --match 'github-v*'`. Fix: state the match flag, or drop it.

## Verified

| Claim                                                                                                         | Evidence                                  |
| ------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| HEAD c93aaae371..., committed 2026-10-21                                                                      | git rev-parse, git show -s                |
| cli, core, plugin versions 2.1.2; CHANGELOG "OpenCode V2", v2.1.2 2026-10-21                                  | package.json:3-4, CHANGELOG.md:3,5        |
| Package name @opencode/plugin; `@opencode-ai/plugin` has zero hits in core, plugin, cli/src, specs, CHANGELOG | grep -rl returned nothing                 |
| plugins.mdx exists                                                                                            | packages/web/src/content/docs/plugins.mdx |
| Loader requires default `{id, effect}` or `{id, setup}`, with the quoted LoadError message                    | core/src/plugin/module.ts:78-91, 125-133  |
| Runtime hook domains are exactly aisdk, session, permission, shell, tool                                      | core/src/plugin/hooks.ts:13-19            |
| Config deny short-circuits before the permission.evaluate hook                                                | core/src/permission.ts:159-175            |
| No tool/tools source-directory loader in config/plugin                                                        | directory listing                         |
| instruction.ts has no "claude" match                                                                          | grep -c = 0                               |
| effect/PLAN.md is 515 lines, tui/context.ts is 560 lines, V2_HTTP_API_AUDIT.md exists                         | wc -l                                     |
| Plan 00292 exists in Completed/                                                                               | ls                                        |

## Notes

- The claim "no `file.edited` event in V2" is correct for the V2 definitions. Only a V1 definition exists, at packages/schema/src/v1/filesystem.ts:7.
- The remaining line-number citations and the ~110 event list were not individually checked. The document marks its own unverified items.
