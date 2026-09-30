# N275: Edit of a workflow denied as an unreadable shell command

> **Superseded in part by review round 1 (5244e58a5).** The literal fallback
> described below applies only to content NOT scanned as shell (`.py`, `.ts`,
> ...). Everything scanned as shell, Makefiles and CI YAML included (after the
> `${{ }}` neutralisation), still fails closed as unreadable, because a
> Makefile recipe runs locally and no other check sees it.

**Route**: `SecretFileGuardHandler._script_content_mention` in
`src/claude_code_hooks_daemon/handlers/pre_tool_use/secret_file_guard.py`.
Only the ADDED text is judged (`content` or `new_string`); `old_string` is never
read. A `.github/workflows/*.yml` path is scanned whole with `context="bash"`,
and the shell brace reader raises `UnresolvableBraceQuotingError` on a doubled
`{{`, which `_matched_pattern_and_route` files as R-SECRET-COMMAND-UNREADABLE.

**Wider than the ledger said**: `context="content"` runs the same brace reader,
so any non-shell file (`.py`, `.ts`, Makefile) containing a doubled brace after
a dollar sign was denied too.

**Change**:

- CI workflow: GitHub expressions are replaced by an inert word before the scan,
  so `run:` steps beside them are still scanned as shell.
- Any file that is not `.sh`/`.bash` or a shell shebang: an unreadable scan is
  repeated literally (`context="content"`, dollar-brace spaced apart). A real
  mention still denies; unparseable text alone no longer does.
- `.sh`/`.bash` and shebang scripts keep failing closed. No allowlist, no
  exclusion, no suppression.

**Tests**: new `TestNonShellContentIsNotJudgedAsUnreadableShell` (14 cases) in
`tests/unit/handlers/pre_tool_use/test_secret_file_guard.py`. Red first: 3
failures (workflow Edit, workflow Write, Makefile). Green: the class passes;
`test_secret_file_guard.py` plus `test_heredoc_grammar_chain.py` 771 passed.
ruff, black (py311), mypy, pyright, `audit_error_hiding.py` and
`check_input_contract.py` clean.

**Not verified**: the wider suite and `llm_qa.py all` (coordinator's gate); the
live daemon (not restarted, so the running guard is unchanged until it is).
Residual weakening, judged acceptable: in a non-shell file a mention spelled
via a braced variable now scans with the brace spaced apart, which still
matches a literal protected name but is not the shell's exact view.
