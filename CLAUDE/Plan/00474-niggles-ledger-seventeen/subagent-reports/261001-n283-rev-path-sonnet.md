# N283: secret_file_guard and git rev:path syntax

**Fix**: `_normalised_token_forms` in `src/claude_code_hooks_daemon/utils/secret_file_matching.py`
now also yields the path after each `:` of a token (the first eight colons plus
the last), each given the existing home and `./` stripping. The whole token is
still judged first, so nothing denied before is allowed.

**Now denied**: `HEAD:<p>`, `<sha>:<p>`, `main:<p>`, `HEAD~2:<p>`,
`HEAD^{tree}:<p>`, `:<p>`, `:0:<p>`, `:2:<p>`, `HEAD:./<p>`, within `git show`,
`cat-file -p|blob`, `archive`, `diff` (any token position), and the same shape
in `scp host:<p>` and `rsync host:<p>` (both were missed too; fixed in the same change).

**Left alone**: Read, Grep and Write tools take filesystem paths (unchanged,
existing tests cover them). `git grep <pat> HEAD -- <p>` carries the path as a
plain token and was already judged. A token with more than nine colons is split
only at its first eight and its last, to bound cost; a protected name hidden
after a middle colon of such a token is not separately judged (the last-colon
split covers the real `rev:path` shapes).

**Tests**: new parametrised matcher tests and handler tests (denied forms,
ordinary-file forms allowed, colon-stuffed token). Red phase could not be shown
against unfixed code: the worktree venv imports `/workspace/src` and
`tests.source_tree_guard` aborts the session. Green run (worktree `src` on
`sys.path`, confirmed by `__file__`): the four named suites, 1371 passed.

**QA**: ruff, black (py311), mypy, pyright, `audit_error_hiding.py` and
`check_input_contract.py` all clean on the touched files.

Release note 203 added; NIGGLES.md N283 marked fixed.
