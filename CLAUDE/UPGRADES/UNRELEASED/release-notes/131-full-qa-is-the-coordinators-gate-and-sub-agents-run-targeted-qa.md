# Callout: full QA is the coordinator's gate, and sub-agents run targeted QA

**Plan**: 00463
**Audience**: operators

A new opt-in handler, `subagent_full_qa_blocker`, denies a sub-agent's full-suite
QA run and names the targeted commands to run instead. The coordinator runs the
full gate as a batch. Every ready branch is merged into one integration
worktree, and the suite runs once on the combined head, not once per agent per
fix round. The main thread is never affected. You declare which commands
count as full (`full_qa_patterns`). Commands are parsed, not substring-matched,
so a commit message or `grep` that mentions one is never denied. It follows
substitutions (including inside double quotes), `eval`, variables the command
sets, code piped or read from a file into a shell or Python, Python code that
calls `pytest.main`, launchers such as `setsid`, `flock` and `time`, globs and
brace expansion. Only a path-like word targets a run, and it is normalised,
resolved against any `cd`, and judged against the repository that contains it,
so `pytest tests/./unit`, `cd tests && pytest unit` and a worktree's `tests/`
named from the main checkout are full runs. A script run by its name or path,
or fed to a shell on stdin, is read and judged with its own arguments, within
one parse budget per command; code past the budget is denied. What it cannot see FAILS CLOSED: a command it
cannot parse, one too long to parse, a program named only at run time
(`$(which pytest)`), an operand built at run time, and code from a producer it
does not understand are denied when they may be the suite, and the reason says
which. A listing of changed files is a targeted run only when it cannot leave
the run bare: `git diff --name-only main -- tests | xargs -r pytest`, or a
`$(git diff ...)` beside a named path. `full_words` declares words that mean
the whole suite wherever the command runs (`llm_qa.py all`), apart from
`full_args`, which are paths. The handler reference lists what "full" does not
cover (a program you have not declared, and one whose name is built at run
time from pieces) and the false denies the fail-closed rules accept.
`option_grammar: pytest` supplies pytest's complete option set, so a flag's
value is never mistaken for a path. A plugin flag the grammar does not know is
read as taking a value. Nothing ships by default. `hooks-daemon check`
reports a handler enabled with no patterns, and a `scope` other than SUB, which
would deny the coordinator's own run.

The handler recognises a sub-agent by the `agent_id` field in its hook
payload. That is proven for Agent-tool sub-agents and in-process teammates. A
Workflow-tool agent's payload has not been measured, so the handler is not
claimed to cover one.

In this repository, `./scripts/qa/llm_qa.py changed` is the new targeted
command. It runs the fast static tools, the project handlers' own tests, docs
and plan QA, shellcheck, and pytest on the tests mapped from files changed since
the merge base. It also runs the tests of what depends on each changed file. A
changed file whose tests cannot be targeted fails the run and is named, with the
reason. `llm_qa.py --read-only` now fails a result in three cases:

- it was recorded for a different commit or working tree;
- its report is not the one that run wrote;
- that run exited non-zero.

So neither an old green run nor a crashed tool's leftover report reads as a
pass.

`llm_qa.py main-moved --start` records a batch's base in the git ref
`refs/integration/base/<branch>`, and refuses a second start unless given
`--restart` for a batch rebuilt from scratch. A passing `llm_qa.py all` on a
clean tree records the head it judged in
`refs/integration/certified/<branch>`. `llm_qa.py main-moved` then answers
what must re-run before the fast-forward, with an exit code to branch on:
`head-moved` (7) when the head is not the certified one, the tree is dirty, or
the head lacks `main` (a head holding only `main` merged in since the certified
head is judged by that movement instead); `unmoved` (0) fast-forwards `main` to the certified
head's SHA, which it prints; `docs-only` (5) re-runs the doc checks;
`targeted` (6) runs `llm_qa.py changed` over exactly the moved range, because
a moved document that tests read is judged by the same test mapper `changed`
uses; `full-gate` (4) runs the whole suite. A runtime-read path (`CLAUDE.md`,
`CHANGELOG.md`, `.claude/**`), code, a symlink, or a document the mapper cannot
target always means the full gate. After the recheck, `main-moved --advance`
moves the base on and certifies the head. It refuses a dirty tree, a head
holding anything but `main` merged in since the certified head, and a recheck
whose recorded provenance does not show it passed on the current tree. When
`main` is already merged into the certified head and its recheck already
passed, the verdict prints only `--advance`, so the suite never runs twice on
one head. Once the batch has landed, `main-moved --finish` deletes both refs;
it refuses unless `main` is exactly the certified head (or a merge of it with
the same tree).
