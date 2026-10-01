# N254: one resolver for `secret_word_list_path`

## Resolvers found

Every reader of the option except one already called
`secret_redaction.resolve_secret_word_list_path`: the redaction sinks via
`_resolve_active_path`, `daemon/cli.py` (skill scan, `check` degradation report),
`secret_file_hygiene_checker`, `scripts/qa/check_sensitive_content.py` and
`scripts/qa/check_git_history.py`. The odd one out was
`SensitiveContentHandler._resolved_secret_list_path`.

| Configured value | Redaction resolver              | Handler (before)                                                           |
| ---------------- | ------------------------------- | -------------------------------------------------------------------------- |
| unset            | project/default path            | `None`, then the daemon-wide path (no self-exemption for the default list) |
| relative         | root / value                    | root / value                                                               |
| absolute         | logged, replaced by the default | the absolute path, honoured                                                |
| `{REPO_ROOT}/x`  | root / x                        | root / `{REPO_ROOT}` / x (a literal directory)                             |

`daemon/cli.py` (`remote-docs add`) hid the disagreement by passing the handler an
already-resolved absolute path.

## Semantics chosen

The docs win: `docs/guides/CONFIGURATION.md` (Plan 00303) says an absolute value is
logged and replaced by the default; `repo_relative_path` documents the optional
leading `{REPO_ROOT}/`. The handler docstring ("relative unless absolute") was the
outlier and is corrected. A configured-but-missing file is inert for every reader
(`load_secret_terms` returns no terms) and `secret_file_hygiene_checker` reports it.

## Change

- Handler resolves through `sr.resolve_secret_word_list_path`; with no project root
  and no configured value it still returns `None` (falls back to the daemon-wide
  path), so a unit test never reads the real list. New `_project_root_override`
  option lets a CLI that builds the handler itself name its root.
- `remote-docs add` passes the raw option plus the root instead of an absolute path.
- Test helpers that injected an absolute temp path now use a relative name plus the
  root override.
- Tests (red first, 5 failing): `TestWordListPathResolvesLikeTheRedactionSinks` in
  `tests/unit/handlers/pre_tool_use/test_sensitive_content.py` covers default,
  relative, absolute and `{REPO_ROOT}` shapes, term loading and the degrade.
- Release note 201.

## Results

Green: the seven test files touching the option (sensitive_content handler,
leak_surface_coverage, remote_docs CLI, secret_redaction, hygiene checker,
check_sensitive_content, cli_secret_redaction_status). ruff, black, error-hiding
audit and input-contract check clean.

## Not verified

- mypy reports one pre-existing `no-any-return` at
  `tests/unit/qa/test_leak_surface_coverage.py:141` (`json.loads`), a line this
  change did not touch.
- pyright in the worktree venv cannot resolve `pydantic`/`pytest` imports (the
  environment, not the change); it reported nothing else.
- The full suite was not run (`test_cli_degraded_mode_visibility.py` was, 9 passed).
- A project that configured an absolute path now degrades to the default list;
  no deployed config was checked for that shape.
