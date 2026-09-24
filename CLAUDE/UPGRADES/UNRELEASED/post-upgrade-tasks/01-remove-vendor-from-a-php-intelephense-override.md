# Task: remove `**/vendor` from a PHP intelephense override

**Type**: audit
**Severity**: recommended
**Applies to**: all versions before this fix (Plan 00462) whose PHP project
followed the previous `R-LSP-CONFIG-EXCLUDE` advice
**Idempotent**: yes

## Why

`lsp_noise_checker`'s PHP advice used to ask a project-scope intelephense
override to exclude `**/vendor`. intelephense's `files.exclude` removes
files from its INDEX, not just its diagnostics, so a project that followed
that advice literally has every Composer-installed type (PHPUnit, Doctrine,
Symfony, ...) undefined - intelephense reports "Undefined type" on code that
is correct. The advice now asks for intelephense's own default nested
excludes instead (`**/vendor/**/{Tests,tests}/**` and
`**/vendor/**/vendor/**`), which keep `vendor/` indexed.

## How to detect if this applies to you

A PHP project only has this problem if it has a project-scope LSP plugin
overriding intelephense. Look for `.claude/plugins/*/.lsp.json` or
`.claude/plugins/*/plugin.json` files that register the `.php` extension and
carry `settings.intelephense.files.exclude` (sample):

```bash
grep -rl '"intelephense.files.exclude"' .claude/plugins/*/.lsp.json .claude/plugins/*/plugin.json 2>/dev/null
```

For each match, check whether the exclude list contains a bare `vendor`
entry (`"**/vendor"`, `"vendor"`, or `"**/vendor/**"`) rather than the
nested forms.

## How to handle

In the matched file's `intelephense.files.exclude` array:

- Remove the bare entry (`"**/vendor"`, `"vendor"`, or `"**/vendor/**"`).
- Make sure the two nested entries are present instead:
  `"**/vendor/**/{Tests,tests}/**"` and `"**/vendor/**/vendor/**"`.
- Leave every other entry in the array untouched.

End the running `intelephense` process afterwards so it re-reads the config
(`pkill -f '[i]ntelephense'`); the harness respawns a fresh one on the next
LSP use.

## How to confirm

Open a PHP file that uses a Composer-installed class (e.g. extends
`PHPUnit\Framework\TestCase`) and confirm intelephense no longer reports it
as an undefined type.

## Rollback / if this goes wrong

The edit is a single JSON array entry; revert it with `git checkout` (or
`git diff`/`git restore` on the file) if the change was unwanted.
