# Callout: LSP output is signal, not noise

**Plan**: 00368
**Audience**: everyone

Claude Code injects the Python language server's diagnostics into the
agent's context after every edit. In this repository that stream carried
thousands of errors about symbols the checkout does not have: the pyright
config had no `exclude`, so the server analysed every linked worktree under
`untracked/`, the plan archive's probes and the deliberately broken test
fixtures, and reported their defects here. The agent learnt to skim the
stream, and a skimmed stream reports nothing.

Two things now hold that property in place.

The pyright CLI is a QA gate (`./scripts/qa/llm_qa.py pyright`, a step in
CI, a numbered check in `run_all.sh`), pinned as the PyPI `pyright` dev
extra and failing on any error, so a diagnostic that survives it is real.
The gate passes the QA venv's interpreter explicitly: the config names a
`untracked/venv` symlink only the main checkout has, and a bare
`pyright --project .` in a worktree or on a CI runner reported 597
third-party imports missing on top of the real count. A missing binary
fails the check with the install line rather than skipping it.

The `lsp_noise_checker` SessionStart advisory, on by default for every
supported language present -- Python, TypeScript/JavaScript, Go, Rust and
PHP -- reports that language's server missing the same daemon-known
non-project trees (its runtime directory, the plan directory, vendored and
build directories, the remote-docs tree, and now the ccy supervisor's own
`.claude/ccy/plugins/` runtime tree -- vendored third-party Claude Code
marketplace plugins ccy itself clones) with that language's exact fix:
Python and TypeScript print the entries ready to paste into a config file's
`exclude`; Go and Rust (whose servers take no exclude list at all) report
only a tree that actually holds their language's source files, with Rust's
fix pointing at `Cargo.toml`'s `[workspace] exclude`; PHP's intelephense
reads no project file whatsoever, so its fix is a project-scope LSP plugin
snippet, printed in full rather than left as "unsupported". Every mechanism
is verified against Claude Code's own marketplace plugin configs, not
assumed. A companion check reports a language server that started before
its check's anchor file was last written, with the command that ends it.
Both checks are advisory and silent when there is nothing to fix.

The count is now zero. Every real error the gate found -- two
`reportIncompatibleVariableOverride`s from three narrowed `HookResult`
subclasses each re-declaring the `decision` field, four stale test
attribute accesses, and the marketplace-plugin noise above -- is fixed
rather than suppressed: `HookResult` is now generic over the decision
`Literal` its tier permits (`core/hook_result.py`'s `DecisionT`), so each
tier PARAMETERISES the base instead of overriding a field on it, and no
`# type: ignore`, `# pyright: ignore` or rule downgrade was added anywhere
to reach zero.
