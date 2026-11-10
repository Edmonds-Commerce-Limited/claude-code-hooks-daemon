# Task 1 implementer report: Plan 00593

Lock update commit: d1d248e1d (branch worktree-593-dependabot-lock-bumps). Not pushed or merged.

## Result

One `uv lock --upgrade-package` run covering all nine packages cleared six alerts and left three held.

| Package           | From   | To      | Cleared | Holder                                        |
| ----------------- | ------ | ------- | ------- | --------------------------------------------- |
| nltk              | 3.9.4  | 3.10.4  | yes     |                                               |
| anyio             | 4.13.0 | 4.16.0  | yes     |                                               |
| virtualenv        | 21.7.1 | 21.15.6 | yes     |                                               |
| urllib3           | 2.6.3  | 2.8.0   | yes     |                                               |
| cryptography      | 46.0.7 | 50.0.2  | yes     |                                               |
| idna              | 3.13   | 3.20    | yes     |                                               |
| filelock          | 3.29.0 | 3.32.7  | no      | safety 3.8.1 (latest on PyPI) requires \<4.0  |
| mcp               | 1.29.0 | 1.29.0  | no      | semgrep 1.184.0 (latest) requires mcp==1.29.0 |
| opentelemetry-api | 1.37.0 | 1.37.0  | no      | semgrep 1.184.0 (latest) requires ~=1.37.0    |

Also moved: defusedxml 0.7.1 added (new nltk dependency), packaging 26.1 to 26.3, python-discovery 1.5.1 to 1.9.5.

Forcing `mcp>=1.30.0` or `filelock>=4.2.1` was tried to see the resolver outcome: it downgrades semgrep or safety
(and drops mcp, nltk, httpx and others). Those lock results were discarded, so the committed lock holds none of them.
No dependency was removed and pyproject is unchanged.

## Decisions

- No release note: no `[project] dependencies` runtime package changed (all moved packages are dev-only or transitive of
  dev extras).
- PLAN.md has the Outcome table and Tasks 1.1 and 1.2 ticked.

## Verification

- Worktree venv synced with `uv sync --frozen --all-extras` (matches `scripts/venv-include.bash`).
- `llm_qa.py changed --range main..HEAD --allow-unmapped`: 42/42 passed (uv.lock reported unmapped, allowed);
  345 changed-tests passed.
- `llm_qa.py dependencies`: 0 issues.
- No code changes were needed.
