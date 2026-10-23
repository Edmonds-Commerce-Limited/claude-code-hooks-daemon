# Release 3.71.0 review: instruction-loading contract refresh, N535, footprint daemon-block fix

Branch `worktree-r371-instructions-contract`, base `17d1cce34`.

## 1. Re-anchoring (vendored `memory.md`, capture of 2026-10-23)

| Fact  | Old anchor (heading / quote)                                                                                                              | New anchor (heading / quote)                                                                                 | Still holds?                                                                                                                                                                                                                                                                        |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| G2-01 | `import-additional-files` / "Imported files are expanded and loaded into context at launch alongside the CLAUDE.md that references them." | same heading / "... loaded into context alongside the CLAUDE.md that references them." (`at launch` dropped) | Substance changed. An import loads WITH its importer: at launch for a launch file, on demand for a subdirectory CLAUDE.md (the page's subdirectory-limit section lists "the files they import"). Statement updated; footprint now counts a nested CLAUDE.md's imports as on-demand. |
| G2-06 | `write-effective-instructions` / "... because imported files also load at launch."                                                        | same heading / "... because imported files load together with the CLAUDE.md that imports them."              | Holds (imports never reduce context cost); wording follows G2-01.                                                                                                                                                                                                                   |
| G3-03 | `path-specific-rules` / "`paths` is the only field Claude Code reads from a rule; ..."                                                    | `rule-frontmatter-reference` (new #### heading) / same quote                                                 | Holds, text unchanged; only the section moved.                                                                                                                                                                                                                                      |
| G3-06 | `path-specific-rules` / "If the YAML between the markers doesn't parse, ..."                                                              | `rule-frontmatter-reference` / same quote                                                                    | Holds, text unchanged.                                                                                                                                                                                                                                                              |

META.json: `fetch_date` 2026-10-23 (frontmatter `fetched_at`), `docs_bytes` 54356, `docs_sha256` 82d60341...c7bb6e7 (frontmatter `source_sha256`, as the guide requires), `last_audited_claude_code_version` 2.1.309 (hooks contract is 2.1.296, so the version-record ordering holds).

## 2. N535 (2.1.309: over-limit nested CLAUDE.md loads only its start)

The refreshed page DOES state the limit, under the new heading "Claude ignores the end of my subdirectory CLAUDE.md": on-demand files (subdirectory CLAUDE.md/CLAUDE.local.md and their imports, a subdirectory's `.claude/rules/`, path-scoped rules) over a per-file limit deliver only their start plus a note to Read the rest. Limit: 40,000 characters (200K window); 200,000 (Opus/Sonnet 4.6) or 150,000 (later models) with a 1M window. "Before v2.1.309, Claude Code didn't apply this limit to files that load on demand."

- G4-03 narrowed: re-anchored to `how-it-works` ("Claude gets the whole of each CLAUDE.md file that loads at launch, as long as the file is 4 MiB or smaller. Claude Code skips a file over 4 MiB and loads none of it."). Applies to launch files only.
- New G4-05 (min version 2.1.309), anchored to `claude-ignores-the-end-of-my-subdirectory-claude-md`, with the documented numbers.
- G1-05 refined: a Bash read (`cat`/`head` on one file) also triggers the load; over-limit -> G4-05. Its anchor still resolves.
- `footprint.py`: `FILE_SKIP_BYTES` comment scoped to launch files; new `ON_DEMAND_CHAR_LIMIT = 40_000` (the smallest documented limit; the footprint does not know the context window). `skipped` is now only a launch file over 4 MiB. New entry field `truncated` (also in `to_dict`): an on-demand file over 40,000 characters, or over 4 MiB (not read; note says its lines were not counted). Report note: "over the 40,000-character on-demand limit of a 200K context window: Claude Code loads only its start". No on-demand file is ever called "skipped".

## 3. Daemon-block regex (review defect)

`_DAEMON_BLOCK_RE` replaced by `_FENCE_OR_DAEMON_BLOCK_RE`: tags must be whole lines, and a fenced block is matched first, so a backticked or fenced `<hooksdaemon>` is not taken for the block. Test reproduces the 8-line probe shape: block lines 3, proposable 5 (old code: 8). This repo's real CLAUDE.md still measures 694/694 block lines.

## Tests

`tests/unit/docs_qa/test_footprint.py` (written first, RED on import of `ON_DEMAND_CHAR_LIMIT`): G4-03/G4-05 constant pins, two daemon-block tests, nested-import on-demand and launch-precedence tests, five truncation/skip tests. `test_instructions_contract.py` + `test_claude_code_version_record.py` + `test_ruleset_matches_instructions_contract.py`: 47 passed. `tests/unit/docs_qa/`, `test_cli_docs_qa.py`, `test_docs_optimise_skill.py`: 742 passed.

QA: `llm_qa.py changed --range 17d1cce34..HEAD --allow-unmapped` on the code commit `c4c4c6fc5`: `QA: 41/41 PASSED`, no failures.

## Notes for the coordinator

- Not changed (pre-existing, out of scope): the footprint does not walk nested `CLAUDE.local.md` or a subdirectory's `.claude/rules/`, both on-demand per G1-01/G4-05.
- No release-notes entry was added. The footprint gains a `truncated` field, and the 3.71.0 release note `001-docs-optimise-skill-and-instruction-footprint.md` may want a line on it.
