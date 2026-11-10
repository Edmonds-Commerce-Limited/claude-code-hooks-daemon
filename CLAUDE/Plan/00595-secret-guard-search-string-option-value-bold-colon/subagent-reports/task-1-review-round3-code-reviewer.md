STOPPING BECAUSE: the review is finished. The verdict is REQUEST CHANGES: 1 Critical, 1 Important, 0 suggestions.

**Plan 00595 final review: `git diff origin/main...HEAD` at 2bc59046c**

I ran 74 probes on both trees. One new bypass class is denied on main and allowed on HEAD, and real grep/rg print protected content through it. Every probe the previous review asked for now denies.

**Critical 1 (95%): an unquoted glob given as the separate value of a filter option is relaxed, but bash expands it into the cwd's file names**
- **Where:** `src/claude_code_hooks_daemon/utils/secret_file_matching.py`, `_is_scoped_filter_value`. It accepts `_follows_separate_filter_option(before)` for any word. The generic branch in `iter_protected_mentions` calls it for UNQUOTED words too (`found is not None and (... or _is_scoped_filter_value(...))`).
- **What happens:** bash expands `--exclude-dir *` into cwd entries. The first entry becomes the option value and the rest become search operands, so the protected file is read by name.
- **Denied on main, allowed on HEAD:**
  - `grep -r x --exclude-dir * sub`
  - `grep -r x --exclude * sub`
  - `grep -r x --include * sub`
  - `rg x -g * sub`
  - `rg x --glob * sub`
  - `rg x --iglob * sub`
  - `grep -r x --exclude-dir d* sub`
  - `rg x -g [d]* sub`
  - `rg x -g *.secret sub`
- **Real tools, on a safe `.tok` fixture with `demo.tok` and `deep/key.tok`:**
  - `grep -r MARK --exclude-dir * sub` printed `demo.tok:MARK` and `deep/key.tok:MARK`.
  - `--exclude *` gave the same output.
  - `rg MARK -g * sub` and `rg MARK -g [d]* sub` printed `demo.tok:MARK`.
  - With a second `*.tok` file present, `rg MARK -g *.tok sub` printed `demo.tok:MARK`.
- **Fix:** in `_is_scoped_filter_value`, accept the separate spelling only when the word is a quoted literal. The simplest way is to pass a flag from the quoted branch, or to accept only `before.endswith(_FILTER_VALUE_PREFIXES)` from the generic branch.

**Important 1 (85%): no test covers the unquoted separate form**
- **Where:** `tests/unit/handlers/pre_tool_use/test_secret_file_guard_option_values.py`.
- **Fix:** add the nine commands above to the still-denied cases. Keep `-g '*' sub` and `--include "*" deep` as they are: they are correctly allowed and denied.

**Item 1, the previous probes: all deny on HEAD.** That covers the out-of-project roots (`/root/.ssh`, `/etc`, `fixture/outside`), the `outlnk` symlink root, `-R`, `--dereference-recursive`, `rg -L`, and `rg --follow x clean -g '*'`. `rg -L x clean -g '*'` and `grep -rR x clean --include '*'` were allowed on main and now deny.

**Item 2, other bypasses I tried: none found.** All of these deny:
- roots: `$HOME`, `~`, `..`, `//etc`, `"fixture/outside"`
- relative roots that lead outside or to a protected file: `clean2/up` (a link to `..`), `clean2/up/deep`, `sub/../deep`
- multiple roots with one outside, and a brace root `{/etc,sub}`
- `-r` with no root, and `-- deep`
- `-e x -e y` and `-m 1` with an outside root; `-rex`, `--regexp x`
- `rg --files -g '*'` with no root, with `sub`, and with `/etc`
- `--include=*.{secret,x}` over `sub` and over `deep`
- `find . | xargs grep`
- `git grep -- '*.secret'`
- a backslash-newline continuation onto a second root (denied, because `\n` splits the segment and the leftover root is judged on its own)

These are allowed on both trees and are not caused by this branch: `cwd=outlnk` or `cwd=sublnk` with `grep -r x --include=* .`, `rg x --glob '*' -uuu sub`, `find sub ... | xargs grep`, `git grep x -- '*'`, and `grep -r x --exclude ? sub`. The `cwd=outlnk` one may deserve its own pre-existing finding: the guard does not judge `.` when the cwd is a symlink that leads out of the project.

**Item 4, #200 and controls:** the three #200 reproductions (git `-S`, `--include=* | wc -l`, the bold-colon Python heredoc) go from DENY to ALLOW. The controls still deny: `cat demo.secret`, `git log -S x -p -- demo.secret`, `--include=*` over `deep` and over `.`.

**Evidence** (in the worktree's `untracked/scratch/`):
- probe script: `probe595r.py` (supports a per-command `CWD=`)
- command lists: `cmdsR.txt`, `cmdsR2.txt`
- results: `rR_main.txt`/`rR_head.txt` and `r2m.txt`/`r2h.txt`
- safe real-tool fixture: `fxG/`

I removed the detached main checkout with plain `git worktree remove`. I opened no real protected file and not the word list.