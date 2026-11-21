# Task 1.1: does the secret guard judge a symlink on its resolved target?

Method: ran the real `SecretFileGuardHandler` (default patterns) by script against
throwaway git repos: a primary checkout holding a synthetic protected file (name
`id_rsa`, content DUMMY, also under `sub/`), a registered `git worktree` of it, and
links inside the worktree. Hook payloads were built as the unit tests build them
(`tool_name`, `tool_input`, `cwd`; `tests/indexed_project.index_project` for the
index; `resolve_project_root` patched). Probe script and raw output:
`untracked/scratch/symlink-probe/probe.py`, `out.txt` (daemon-like process cwd, not
the worktree) and `out_chdir.txt` (process cwd = worktree). No real secret was read.
Each case was run with project root = worktree and project root = primary.

Links: L1 `link1.txt` -> relative `../primary/<P>`; L2 `link2.txt` -> `dlink/<P>`
where `dlink` is a relative directory symlink to `primary/sub`; L4 a link to L1;
L5 an absolute link; `dlink` and `plink` (directory link to the whole primary).

## Result table

| Case (link name innocuous unless stated)                                                             | Verdict                                                                               | Evidence                                                                                                                                                            |
| ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Read / Grep / Write / Edit, ABSOLUTE path of L1, L2, L4, L5                                          | DENIED (all, both project roots)                                                      | `protecting_pattern` -> `resolve_checking_loop` realpath, `_pattern_for_spellings` matches spelling OR real path (`secret_file_matching.py` 365-402); probe out.txt |
| Bash `head <absolute L>`                                                                             | DENIED                                                                                | token realpath, `_realpath_if_resolvable` (3285-3295)                                                                                                               |
| Bash `cat L1` / `cat < L1` / `python3 -c open('L1')`, RELATIVE token, daemon process cwd != worktree | ALLOWED (GAP)                                                                         | out.txt: ALLOW for L1, L2, L4, L5                                                                                                                                   |
| Same Bash relative cases when process cwd == worktree                                                | DENIED                                                                                | out_chdir.txt                                                                                                                                                       |
| Read with relative path                                                                              | n/a (Claude Code gives absolute Read paths); same ALLOW when relative and cwd differs | out.txt                                                                                                                                                             |
| Path spelled through the directory link with the protected NAME (`dlink/<P>`, `plink/<P>`)           | DENIED                                                                                | name matches by spelling, so not a resolution test                                                                                                                  |
| Grep tool / `grep -r x dlink` / `plink/`, project root = primary                                     | DENIED                                                                                | index of primary matches the realpath base (`find_under` bases, `protected_file_index.py` 128)                                                                      |
| Grep tool / `grep -r x dlink` / `plink/`, project root = WORKTREE                                    | ALLOWED (GAP)                                                                         | worktree index lists no primary files; directory link target is not followed                                                                                        |
| Bash `cat dlink/*` (glob through a directory link), either project root                              | ALLOWED (GAP)                                                                         | glob token is not realpath-resolved (3106-3121 skips glob-shaped tokens by design)                                                                                  |
| Glob tool on any link                                                                                | ALLOWED                                                                               | by design: presence/metadata stay available (`secret_file_guard.py` ~1783)                                                                                          |
| Controls (`readme.txt` Read, `cat readme.txt`, `ls dlink`)                                           | ALLOWED                                                                               | as expected                                                                                                                                                         |

## Code reading

- Link resolution exists: `protecting_pattern` realpaths the file path
  (`resolve_checking_loop`), treats a symlink loop as protected, and matches both
  spellings. Absolute link paths (and chains L4, absolute L5, directory-link
  intermediates L2) are therefore judged on the resolved target. This is the
  documented worktree_create seeding case.
- Bash tokens: `_realpath_if_resolvable(token)` calls `Path(token).is_symlink()` on
  the RAW token, so a relative token resolves against the daemon PROCESS cwd, not
  the hook's `cwd`. The daemon calls `os.chdir("/")` at start (`daemon/cli.py:929`),
  so in production a relative `cat link1.txt` from a worktree is not recognised as
  a link at all. The text-form matching (`_normalised_token_forms`) does honour the
  hook cwd; only the realpath step does not.
- `_realpath_if_resolvable` only fires when the FINAL component is a symlink and
  skips glob-shaped tokens, so a protected file reached through a directory
  symlink plus a glob is not resolved.
- Recursive reads (Grep, `grep -r`) are judged against the protected-file index of
  the project root only, and bases are `normpath` + `realpath` of the root, not of
  a directory link's target. A directory link from the worktree to the primary
  checkout is only caught when the primary is the indexed root.

## Real gaps (not fixed)

An agent whose project root is a worktree can read a protected file of the
primary checkout through a link, via: (1) a RELATIVE-path Bash command naming a
link (`cat link`), (2) a recursive grep/Grep rooted at a directory link, (3) a
glob under a directory link (`cat dlink/*`). Absolute-path forms are all denied.
This matters for plan 00613: once the verb creates such a link, every relative
`cat <link>` reaches content past the guard unless gap (1) is closed first.

Minimal fixes, in order of importance:

1. In `_realpath_if_resolvable` (both call sites, 3118 and 3199) join a relative
   token to the hook `cwd` (the same `effective_cwds` the glob path uses) before
   `is_symlink`/`realpath`; also resolve when ANY component is a symlink, not only
   the last (`os.path.realpath(p) != normpath(p)`).
2. In `ProtectedFileIndex.find_under` / `directories_matching`, add the realpath of
   the requested root (the directory-link target) to the bases and, when it lies
   outside the indexed project, either index that checkout or deny by default.
3. For glob tokens, expand against the filesystem and realpath each result (or deny
   a glob whose literal prefix is a symlinked directory).

## Caveats

Verdicts come from calling `matches`/`handle` directly, not through the daemon
socket; the process-cwd claim rests on `cli.py:929` plus the out.txt versus
out_chdir.txt difference, not a live daemon run.
