STOPPING BECAUSE: the review is done. Verdict: **APPROVE**. I found 0 Critical, 0 Important and 2 Minor issues, and the branch tightens guards without loosening any.

**Method.** I ran a differential check: every one of the 78 PreToolUse handlers (all calling `matches`/`handle`) ran on HEAD and on a fresh detached checkout of origin/main, over 6,108 generated commands. The commands cover all the forms you listed in priority 1 and more (`${x:-;}`, `${x:-'}'}`, `${x:-"a b"}; git reset --hard`, `${x:-\}}`, an unbalanced `${`, `${x:-a}$(...)`, `"${x:-'}'}"`, 40-deep nesting, the operator forms hiding spaces like `git ${x:-reset --hard}` and `eval ${x:-...}`). Each form was combined with 23 dangerous payloads: destructive git, `rm -rf`, secret-file reads, the forbidden in-place editor, `curl | bash`, `pytest | tail`, `chmod 777`, `gh auth token`, `crontab -r`, `git stash`, and writes outside the project.

**Scanner change (priority 1).** Zero verdicts changed between the trees, so no command that origin/main denies is allowed on HEAD. Re-running the previous review's probes (`wpp_probe`, `wpp2`, `wpp_fix`, `opform`, `pb`), every change goes allow→deny, except one correct deny→allow: `${PWD:-.}/other/x` under `paths: [protected/x]` was a false positive on main.

**Minor 1: the cwd regex closes early on a quoted or escaped `}`** (confidence 75; outside the threat model; `src/claude_code_hooks_daemon/core/utils.py:463-465`).
- `[^{}]*` stops at a `\}` or a quoted `}` that bash does not treat as the end of the expansion. The leftover text then adds extra path depth that bash never sees.
- Reproduction, with project_containment, root and cwd both `/repo`:
  - `echo hi > ${PWD:-\}/a/b/c}/../../../zz` is denied on main and allowed on HEAD; bash writes `/zz`.
  - The same happens with `${PWD:-'}/a/b/c'}/../../../zz`.
  - `bash -c 'echo ${PWD:-\}/a/b/c}/../../../zz'` confirms bash reads the whole thing as one expansion.
- No careless agent writes this shape, so it does not block the merge.
- Fix: use `[^{}'"\\]*` for the word, so these forms stay unresolved and are denied as before. Ordinary `${PWD:-.}` is unaffected. Add both forms as deny tests in `tests/unit/core/test_utils_cwd_expansions.py`.
- The other `${PWD...}` forms behave correctly:
  - `${PWD:+/etc}`, `${PWD#/}`, `${PWD%/*}` and `${PWD:-$(...)}` still deny.
  - `${PWD:-/etc}/zz` now allows, which matches bash because PWD is set.
  - `git -C ${PWD:-/etc}` is allowed on both trees.

**Minor 2: the docs understate the heredoc exception** (confidence 80).
- Release note 037 line 6 says only a body that reaches a `.md` file or a git/gh message is exempt, and `docs/guides/HANDLER_REFERENCE.md:744` says the same.
- In fact `strip_unrun_heredoc_bodies` also skips a quoted body read by any plain text reader writing to stdout. `cat <<'EOF'`, `grep x <<'EOF'` and `wc -l <<'EOF'`, each with a `pytest` body followed by `docker ps | tail -1`, are allowed with an advisory on both trees.
- The behaviour is right; the docs are wrong. Fix: add "or is only read as text by `cat`/`grep`/… without being written to a file" in both places.

**Prose-sink heredocs (priority 3).** Every shape that hands the body to something that runs it still denies: `tee a.md <<'EOF' | bash`, `cat > x.md <<'EOF' | sh`, `gh … -F - <<'EOF' | bash`, `bash <<'EOF' > x.md`, `xargs -0 > x.md <<'EOF'`, a `while` loop body, an unquoted `git commit -F - <<EOF` holding `$(pytest | tail)`, `cat > x.md <<EOF $(...)`, and `cat > x.md <<'A' && bash <<'B'`. Mixed or non-markdown targets (`tee x.md run.sh`, `> run.sh`, `| tee run.sh`, `x.md/../run.sh`) keep their bodies, so those bodies are still scanned. `cat > x.md <<'EOF' … ; bash x.md | tail` is allowed, but it was allowed on main too and it means running a markdown file as a script, which is outside the threat model.

**Previous findings (priority 4).**
- The Critical is closed: `awk '{print > FILENAME}' "${PWD:-.}" ./protected/x` and `"${IN:-a.txt}" protected/x` now deny.
- The heredoc and `py.test` fixes hold: all 13 `py.test` wrapper shapes and the `t.sh`, `<<-` and two-heredoc shapes deny.
- Release note 037 is accurate apart from Minor 2.
- Targeted tests: 1239 passed across 10 files, the changed test files plus the unit tests for pipe_blocker and project_containment.

The probe scripts are kept as evidence in `/workspace/untracked/worktrees/worktree-478-2f-review-minors/untracked/scratch/probe2/`:
- `diff.py`, `gen.py`, `gen2.py`, `gen3.py`, `cmp.py`: the differential check.
- `pc.py`: Minor 1.
- `pb3.py`, `pb4.py`: priority 3.
- `pb5.py`: Minor 2.

The origin/main checkout has been removed.