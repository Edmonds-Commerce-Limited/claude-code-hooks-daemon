# Entries carried from the dropped N53 branch

Verbatim from `worktree-n466-n53`'s ledger 00466 NIGGLES.md. That branch
was dropped (211 commits behind, an unstarted round left), so every fix it
describes is NOT on `main`: a "Remedied" heading below means remedied on that
branch only. All seven are open again; see the index in [PLAN.md](PLAN.md).

### N246 — plan and docs QA judge a same-command `git add` as two partial trees

Found by N53 round 9d5's committed-tree differential. For
`git add new.py && git mv new.py moved.py && git commit`, `judged_views`
gives two views: the index without the added file, and HEAD plus the added
paths without the index's other staged changes. The commit records one tree,
the index with the added paths' working-tree content, and neither view is
it. A cross-file check can therefore pass on each view and miss a defect
that only the whole tree shows, or report one the tree does not have.

Candidate remedy: give `GitFactsBase` an index-plus-overlay mode, in which
the named paths' working-tree content replaces the index's and untracked
paths are added, and have `judged_views` build one such view for a
same-command add.

### N245 — a pathspec commit is judged on the index as well as the named paths

Found by the same differential. `recorded_content` gives
`git commit -m x a.py` `reads_index=True` on purpose ("a gate over-reading
costs a false deny, never a missed file"). Since each gate now reads the
index's content rather than the disk's, a staged break in `a.py` that the
disk repairs makes `staged_lint_gate`, `remote_docs_commit_gate` and
`sensitive_content` judge content the commit never records. Under the
committed-tree ruling that is a false deny.

Candidate remedy: `reads_index=includes_index(options)` for a pathspec
commit, and for `--include` the overlay view N246 needs.

### N244 — ✅ Remedied — the QA commit gates judge the disk, not the tree the commit records

Found in N53 round 9d and ruled on in round 9d2. After a `git rm -r --cached`
of a plan folder, the folder is still on disk but is not in the commit. A
README row that still links to it dangles in the committed tree, and the
plan QA commit gate allowed it. On main, `plan_qa/context._tree_and_readme`
builds the tree with `PlanTree.scan` over the disk and reads the README from
disk. `row_folder_bijection._link_findings` tests `target_parent.is_dir()`.
So main has the same gap.

The coordinator ruled that a commit gate judges the tree the commit will
record. That is the index after every operation recorded in the same
command, never the disk.

**Remedy (N53 branch).** Plan QA judges the committed tree from commit
`52631a687`, and reads each file's content from it from `4cbbaa540`. The
docs half is remedied in `64e123feb` and `2866452c2`: `pointer-resolves`,
`quote-drift`, `plan-promotion-disposition` and `rules-file-orphan-shrink`
read the committed tree through `GitFactsBase`, and so does the staged
document view. `tests/unit/utils/test_committed_tree_differential.py`
compares both gates' committed tree with the commit git makes.

### N189 — ✅ Remedied on the N53 branch — no commit gate saw a commit hidden in text only bash could read

**Found:** N53 review 6 (D-RULE), M2, shared by `main` and the branch. Bash
commits in each of these, and every commit gate on `main` let each one
through:

- `X='git commit -m x'; bash -c "$X"`, `eval "$X"`, a bare `$X`, and
  `source <(printf '%s' "$X")`;
- `bash -c "$(printf 'g%sit commit -m x' '')"`, the same through `eval`, and
  `bash <<< "$(printf …)"`.

The branch refused the shapes whose text spelled git, and let the rest
through. It also refused `curl … | bash` and `bash < f` outright, so
`remote_docs_commit_gate` denied them even when nothing in the tree was
wrong.

**Why:** a gate can only judge a commit it can place, and the text of these
commits exists only once bash expands it. Main looked for `git commit` in
the command's words. The branch looked for `git` in the unread text, and
then refused rather than judged.

**Remedy:** text bash runs that the walk cannot read is a commit judged on
its worst-case content (`RecordedContent.worst_case()`): the index, every
tracked working-tree change (as `commit -a` records it), and every untracked
file that is not ignored (as `add -A` records it). It is placed in each
directory the command may be in, and in the start. It is refused only when
the repository cannot be told. This applies to a computed `-c` script,
`eval` string, command name or git subcommand, a shell fed unread input, a
non-shell fed input that names a commit, and a walk past its step budget.
Each of the six gates reads the untracked files
(`git_repo.untracked_paths`). A `[` with no `]` after it is no longer read
as a glob, so `[ -d x ]` is not a computed command. Tests:
`TestWhatCannotBeReadIsJudgedAtItsWorst` in
`tests/unit/utils/test_commit_placement.py`, the `review 6 M2` rows of the
bash-differential corpus, and a worst-case pair (violating, clean) in each
gate's test file.

### N177 — ✅ Remedied on the N53 branch — no commit gate saw a commit after a `case` inside `function f {` inside `$( )`

**Found:** N53 review 5 (D-RULE), minor m3, shared by `main` and the
branch. In `echo $(function f { case a in *) git commit -m x;; esac; }; f)`
bash runs the commit.

**Why:** the reader in `shell_words` treats `case` as reserved only at the
start of a command, and `function` did not count as a word after which the
next word is still at a command's start. So `case` was read as an ordinary
word, and the pattern's `)` closed the `$( )` early.

**Remedy:** after `function`, the name and the body's `{` keep the reader at
a command's start, so `case` opens its construct and its `)` closes nothing.
Test: `TestWhereReview5FoundTheReaderAndBashDisagree` in
`tests/unit/utils/test_shell_words.py`, and the bash-differential corpus in
`tests/unit/utils/test_commit_placement_differential.py`.

### N176 — ✅ Remedied on the N53 branch — no commit gate saw a commit inside `$(( $(…) ))` arithmetic

**Found:** N53 review 5 (D-RULE), minor m2, shared by `main` and the
branch. `echo $(( $(git commit -m x) ))` runs the commit.

**Why:** the reader stepped over an arithmetic expansion as one computed
word and never read the substitutions inside it.

**Remedy:** the body of `$(( ))`, of a `(( ))` command and of
`for (( ))` is read for substitutions, which the walk then runs as child
commands. Tests: `tests/unit/utils/test_shell_words.py`
(`test_a_substitution_in_arithmetic_is_run`) and the bash-differential
corpus.

### N135 — ✅ Remedied on the N53 branch — no commit gate saw a commit run from text, through an alias, or after `builtin cd`

**Found:** N53 review 4 (D-RULE), in its "both trees allow" list. Every
commit gate located a commit by reading the command's own words for `git`
followed by `commit`, on `main` and on the N53 branch alike. So the gates
never saw a commit that the shell runs from TEXT or that git resolves
itself:

- `bash -c "git commit ..."`, `sh -c`, `eval "git commit ..."`;
- a git alias, whether configured (`git ci`, with `alias.ci = commit`) or
  given on the command line (`git -c alias.x=commit x`);
- `builtin cd sub; git commit ...`, which both trees judged from the
  directory the command started in.

In every case `sensitive_content`, `staged_lint_gate`, `docs_qa_commit_gate`,
`plan_qa_commit_gate`, `remote_docs_commit_gate` and
`guard_config_commit_gate` allowed a commit they would have denied or
reported if it had been spelled `git commit`.

**Why:** each gate asked its own question of the command: a regex, `shlex`
tokens, or the branch's reader. None of them read a word as a script, and
none of them asked git what a subcommand means.

**Remedy:** every gate now asks `commit_placement.runs_a_commit` and places
commits with `placed_commits`. That walk reads text the shell runs as
commands (`-c` scripts, `eval`, substitutions, and scripts fed to a shell on
standard input), and it strips `builtin`/`command` so the `cd` still moves
the directory. It resolves a non-builtin git subcommand as an alias with
`git config --get alias.<name>`, run in the directory the commit runs in and
with the command's own `-c` options. A shell alias (`!...`) is read as a
script run from the top level. The walk refuses (fails closed) when it
cannot resolve a name: the config cannot be read, the command changes which
config is read (`HOME`, `GIT_CONFIG_*`), the subcommand is computed, or the
alias chain loops. Tests: `tests/unit/utils/test_commit_placement.py`
(`TestShellsEvalAndBuiltins`, `TestGitAliases`) and the cross-gate corpus
`tests/unit/handlers/pre_tool_use/test_commit_gates_read_every_commit_shape.py`.
Each went RED against the pre-fix tree.

