# LSP / Pyright Troubleshooting

**Audience**: contributors (human or agent) seeing spurious Python diagnostics
in this repo — most commonly a flood of `Import "..." could not be resolved (reportMissingImports)` for `pydantic`, `pytest`, or first-party
`claude_code_hooks_daemon.*` modules.

## The configuration SSoT

`pyrightconfig.json` at the project root is the single source of truth for
Python import resolution, for BOTH the CLI (`pyright --project /workspace`)
and the long-running `pyright-langserver` that editors and Claude Code's LSP
integration spawn:

- `venvPath: untracked` + `venv: venv` — resolves through the stable
  `untracked/venv` symlink, which points at the current fingerprint-keyed venv
  (see the venv layout section in [SELF_INSTALL.md](../SELF_INSTALL.md)).
  Never replace this with a hardcoded fingerprint path; the fingerprint
  changes and the symlink is maintained to track it.
- `extraPaths: ["src"]` — first-party imports resolve from source, not from
  an installed package.
- `exclude` — `untracked/` (every linked worktree, venv, fixture install and
  canary clone), the plan archive, the acceptance-test and unit-test fixture
  trees, and `remote-docs/`. Without it the server analyses other
  checkouts' in-progress branches and reports their half-built symbols as
  errors in THIS checkout: two sub-agents working in worktrees produced
  thousands of "unknown attribute" diagnostics against files they had not
  touched here. `tests/unit/test_pyright_config.py` pins the list.

## The QA gate

`scripts/qa/run_pyright_check.py` (the `pyright` tool in `llm_qa.py`, Plan
00368\) runs the same CLI over the same config and fails on ANY error, so a
clean gate means a clean diagnostics stream. It passes the QA venv's
interpreter as `--pythonpath`: the `untracked/venv` symlink above exists only
in the main checkout, and in a worktree or on a CI runner a bare
`pyright --project .` resolves no site-packages and reports every third-party
import missing. Use the script, not the bare command, when the count matters.
The `lsp_noise_checker` SessionStart advisory reports an `exclude` entry the
config is missing, and a language server older than the config file.

## Diagnosing: is it the config or a stale server?

Run the CLI against a flagged file:

```bash
pyright --project /workspace src/claude_code_hooks_daemon/daemon/cli.py
```

- **CLI clean, live diagnostics noisy** → the running language server is
  STALE: it started before `pyrightconfig.json` existed (or before the venv
  symlink was created) and never re-read its environment. This is the common
  case — a long-lived server survives config changes made after it started.
- **CLI also fails** → the config or the venv is genuinely broken: check the
  `untracked/venv` symlink resolves (`ls -la untracked/venv`) and that its
  interpreter imports the missing package.

## Fixing a stale server

The language server has no reload command exposed through the LSP tool
surface, but it is safe to terminate — the harness respawns it on the next
LSP request, and the fresh process reads `pyrightconfig.json`:

```bash
pkill -f "pyright-langserver"   # respawned automatically on next LSP use
```

Verify recovery with any LSP hover/definition request on a previously-flagged
import, or re-run the CLI.

**Editor users**: the equivalent is your editor's "Restart Language Server" /
window reload. `.vscode/` is git-ignored here (per-developer preference), so
pin your interpreter locally if your editor needs it:
`.vscode/settings.json` with `python.defaultInterpreterPath` set to
`${workspaceFolder}/untracked/venv/bin/python`. <!-- python-var-guidance-exempt: editor interpreter pinning via the stable venv symlink, not shell-invocation guidance -->

## Known non-issues

A stale server also reports "not accessed" hints for symbols that ARE used
(tuple-unpack discards like `_label`, functions referenced later in the same
file) and stale attribute errors against just-edited files. Judge by the CLI,
which is always run fresh: if `pyright --project /workspace` is clean and QA's
mypy gate passes, live diagnostic spam is server staleness, not a code defect.
