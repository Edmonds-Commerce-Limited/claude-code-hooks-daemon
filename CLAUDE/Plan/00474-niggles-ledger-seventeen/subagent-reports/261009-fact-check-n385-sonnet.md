# Fact check: N385 (commit 652c36a1b)

Method: `matches()` called directly on `{"tool_name":"Bash","tool_input":{"command":...}}` for CurlPipeShellHandler, RootRecursionGuardHandler and WorktreeFileCopyHandler, from `/workspace/untracked/scratch/n385/p.py` using `PYTHONPATH=/workspace/src .venv/bin/python`. Raw output is in `untracked/scratch/n385/out.txt`.

Worktree spellings used for `<wt>`: `untracked/worktrees/X`, `.claude/worktrees/X` and `/workspace/.claude/worktrees/X`. All three gave the same verdicts.

Positive controls, to show the probes can deny: `curl URL | sh`, `grep -r x /` and `cp <wt>/src/f.py src/f.py` were each DENIED.

## REFUTED

None.

## Table

| #   | Claim (quoted)                                      | Verdict           | Evidence                                                                                                                            |
| --- | --------------------------------------------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| 1   | curl_pipe_shell allows `sh -c "$(curl …)"`          | VERIFIED          | allow                                                                                                                               |
| 2   | allows `bash <(curl …)`                             | VERIFIED          | allow                                                                                                                               |
| 3   | allows `curl url -o x.sh && bash x.sh`              | VERIFIED          | allow                                                                                                                               |
| 4   | allows `\| env python3`                             | VERIFIED          | allow                                                                                                                               |
| 5   | allows `\| sudo -u bob python3`                     | VERIFIED          | allow                                                                                                                               |
| 6   | allows `\| node`                                    | VERIFIED          | allow                                                                                                                               |
| 7   | worktree_file_copy allows `cp -r <wt>/src .`        | VERIFIED          | allow, all 3 spellings                                                                                                              |
| 8   | allows `rsync -a <wt>/ ./`                          | VERIFIED          | allow, all 3 spellings                                                                                                              |
| 9   | allows `cd /workspace; cp -r <wt>/src .`            | VERIFIED          | allow, all 3 spellings                                                                                                              |
| 10  | allows `(cp …)`                                     | VERIFIED          | `(cp -r <wt>/src .)` allow                                                                                                          |
| 11  | allows `command cp`                                 | VERIFIED          | allow                                                                                                                               |
| 12  | allows `nice cp`                                    | VERIFIED          | allow                                                                                                                               |
| 13  | allows `xargs cp`                                   | VERIFIED          | `xargs cp <wt>/src/f.py .` and `echo … \| xargs cp -t .` both allow                                                                 |
| 14  | allows `cp -t src/ <wt>/…`                          | VERIFIED          | allow                                                                                                                               |
| 15  | allows `find -exec cp`                              | VERIFIED          | `find <wt> -exec cp {} src/ \;` allow                                                                                               |
| 16  | root_recursion_guard allows `bash -c 'grep -r x /'` | VERIFIED          | allow                                                                                                                               |
| 17  | allows `time grep -r x /`                           | VERIFIED          | allow                                                                                                                               |
| 18  | allows `sudo find / …`                              | VERIFIED          | `sudo find / -name x` allow                                                                                                         |
| 19  | allows `grep -rm1 x /`                              | VERIFIED          | allow                                                                                                                               |
| 20  | allows `du -sh /`                                   | VERIFIED          | allow                                                                                                                               |
| 21  | allows `ls -R /`                                    | VERIFIED          | allow                                                                                                                               |
| 22  | allows `rg x /home/user`                            | VERIFIED          | allow                                                                                                                               |
| 23  | Evidence is in `untracked/scratch/batchc-review/`   | VERIFIED          | The directory exists and holds probe.py and \*.tsv files.                                                                           |
| 24  | "None of these came from batch (c)"                 | UNVERIFIABLE-HERE | This is a claim about which branch introduced what. Diffing the handler sources on batch (c)'s branch against main would settle it. |

Counts: 24 claims, 23 verified, 0 refuted, 1 unverifiable.

Caveat on 24: row 24 is a statement about branch provenance, not about the current tree, so it was not checked.
