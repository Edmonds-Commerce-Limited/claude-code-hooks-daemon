# N364 fact check (sonnet)

Source: src/claude_code_hooks_daemon/handlers/pre_tool_use/sensitive_content.py

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | Handler treats `git config ... user.name/user.email` as an identity-write surface | VERIFIED, with nuance | Guidance text line 1560 names it; comment line 138 (`config -> author/committer identity`). In code (`_writes_git_metadata`, line 1267) the surface is the whole `config` subcommand (`_GIT_METADATA_WRITE_SUBCOMMANDS`, line 150-158), not keyed on user.name/user.email. |
| 2 | `git config --get-regexp '...user\.name...'` is classified as a write | VERIFIED | Read-only exemption is exact-token membership `any(flag in tokens for flag in _GIT_READ_ONLY_FLAGS)` (line 1294) with flags `--grep --list -l --get` (line 164). `--get-regexp`, `--get-all`, `--show-origin` are not exact matches, so they fall through to `return True`. |
| 3 | Guidance text says reading is never blocked | VERIFIED | Line 1583: "**Reading is never blocked.** Only commands that WRITE metadata are candidates". Its examples list `git log --grep=`, `git show`, `git branch --list`, `git tag -l`; `git config --get` appears only in a code comment (1292). |
| 4 | Denied as `R-SENSITIVE-SECRET-TERM` | VERIFIED (id exists) | constants/rule_ids.py:475. Whether the denied command matched an entry not checked (secret list not opened). |

Nuance for the plan: the fix is broader than N364 states. Every `git config` without an exact `--get`/`--list`/`-l` token (including a bare `git config user.name` read, `--get-all`, `--get-urlmatch`, `--show-origin`) is treated as a write; the cleaner fix is to classify by "assigns a value" or extend the exempt set, as N364 proposes.
