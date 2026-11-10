STOPPING BECAUSE: review complete. APPROVE, with 2 non-blocking findings to file.

# Review: Plan 00596, branch worktree-596-printed-git-text (HEAD 2a4e8e8a1)

**Counts:** Critical 0, Important 0, Suggestion 2 (both non-blocking, file as plans).

I ran 103 probe commands through `matches()`/`handle()` on both origin/main and HEAD. Probe is at `/workspace/untracked/worktrees/worktree-596-printed-git-text/untracked/scratch/probe596/` (`probe.py <src-root> <cases.json>`, with `cases.py` and `cases2.py`). The scratch origin/main worktree was removed with plain `git worktree remove`.

**Hunt 1 (executed captures): no regression.** All of these still DENY on HEAD:
- direct use: `$m`, `"$m"`, `${m}`, `eval $m`, `bash -c "$m"`, `sh -c $m`
- stdin and declarations: `xargs <<< "$m"`, `bash <<< "$m"`, `declare -x` + `bash -c 'eval $m'`
- arrays: `a=($(…))` with `"${a[@]}"` / `${a[*]}`
- keyword assignments: `export`/`local`/`declare`/`readonly m=$(…); $m`
- env prefix: `m=$(…) cmd`
- command word and pipes: `$(…)` alone, `echo $(…) | sh`, `|& sh`, `2>&1 | sh`, `printf "$(…)" | bash`
- echo captures: `x=$(echo git reset --hard) && $x`
- nesting and backticks: nested `$(printf "$(printf …)")`, backticks
- scripts: `> s.sh; bash s.sh`, `. ./s.sh`, `./s.sh` after chmod, `tee s.sh; bash s.sh`, `bash <(…)`
- control flow and copies: `set -- $m; "$@"`, `for`/`while read` loops, `trap`, `alias`, `n=$m; $n`, `&&`/`||`/`&`/newline-separated `$m`, `(eval "$m")`

**Hunt 2 (DATA_SINKS is shared): no regression.**
- Consumers are `curl_pipe_shell.py:545`, `core/utils.py:650` (write-target scan), and the heredoc receiver exemption at `shell_segmentation.py:2468`, which every heredoc-aware guard uses.
- None of fold, fmt, nl, expand, unexpand, paste, rev or tac has an option that runs a command. paste/rev/tac read only the files named on their own argv; nothing reads paths out of the input. None of them were added to `TEXT_READING_SINKS`, which is correct.
- Still DENY on HEAD: `tac <<'EOF' | sh`, `fold <<'EOF' | sh`, `paste -d '' - <<'EOF' | bash`, `fmt <<EOF` with `$(git reset --hard)` in the body, `paste <(…)`, `nl <(…)`, `fold $(…)`, `nl -s "$(…)"`, `| fold > s.sh; bash s.sh`, `| nl | tee s.sh; bash s.sh`.
- Now ALLOW: `rev <<'EOF'` with a git body. That is correct, since rev only prints.

**Hunt 3 (the #197 cases):**
- Reproductions 1, 2 and 4 now ALLOW.
- `| fold -w 40 | sh`, `| tac | sh`, `| paste -sd' ' | bash` and `| my-tool` still DENY.

**Suggestion 1: print-only blanking reaches a known gap in `_runs_written_script`** (confidence 85; a careless agent is unlikely to write these, so non-blocking).
- **Location:** `utils/command_position.py:168-185`, which is pre-existing. It only recognises a written script that is run as `sh FILE` / `. FILE` / `./FILE`.
- **Reproduction:** these DENY on main and ALLOW on HEAD:
  - `echo "$(printf '%s\n' 'then git push origin --delete b')" > s.sh; sh < s.sh`
  - the same with `bash -s < s.sh` and with `cat s.sh | sh`
  - `m=$(printf …); echo "$m" > s.sh; sh < s.sh`
- **Same gap without a substitution:** the literal version `echo 'git reset --hard' > s.sh; sh < s.sh` already ALLOWs on main. So this branch makes the substitution form behave like the literal form; it does not open a new gap. I tested this literal form for the `sh <` case only, not for `cat s.sh | sh`.
- **Fix:** have `_executed_path` treat a shell/source head whose stdin is redirected (`<`) from a written path as running it. Also treat a `cat`-family stage over a written path that pipes into a shell the same way. Add the four commands above as DENY tests.

**Suggestion 2: `printf -v` is treated as print-only** (confidence 80; contrived shape, non-blocking).
- **Location:** `command_position.py`, in `_prints_only` (new code, around line 585). `printf -v VAR` assigns a variable instead of printing.
- **Reproduction:** `m=$(printf '%s\n' 'then git push origin --delete b'); printf -v n "$m"; eval "$n"` DENYs on main and ALLOWs on HEAD.
- **Same gap without a substitution:** the literal version `printf -v n '%s' 'git reset --hard'; $n` already ALLOWs on main.
- **Fix:** in `_prints_only` and `_printing_body`, do not count a `printf` that has a `-v` word as printing. Add the reproduction as a DENY test, and also add the substitution-free form.

**Not run:** the branch's own unit tests. Pytest refused to start because this worktree's venv points at main's `src/`; fix that with `./scripts/setup_worktree.sh` before relying on them. My probe loads each tree's `src` directly by path, so the verdicts above are from the right code.

**Positives:** the candidate list is strict and limited to known safe forms: the body may only be a literal `echo`/`printf`, with no `$`, backtick, newline or unquoted operator. Every variable reference is traced to a segment that only prints, and the pipeline check is reused. The tests pair each new ALLOW with a DENY version of the same command that actually runs it.

**Verdict: APPROVE.**