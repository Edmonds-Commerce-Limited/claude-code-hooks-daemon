# Field report: markdown_organization blocks an edit two vendor levels deep

Imported from `untracked/hooks-daemon-issue.md`; reporter identifiers
replaced per `CLAUDE/development/DOC-CONVENTIONS.md`.

## What happened

`markdown_organization` (R-MARKDOWN-WRONG-LOCATION) blocks an `Edit` of an
existing `.md` inside a first-party git clone that is vendored two `vendor/`
levels deep, and neither documented escape hatch changes the verdict.

Daemon version 3.63.0. Repository root `client-a-api`. The file:

```
vendor/org-a/pkg-a/vendor/org-b/pkg-b/docs/upgrading.md
```

Both `vendor/org-a/pkg-a` and `vendor/org-a/pkg-a/vendor/org-b/pkg-b` are
real git checkouts (Composer source installs) with their own
`.claude/hooks-daemon.yaml`, `docs/` and `CLAUDE/`.

## What I tried

1. Plain `Edit` (a three-line change to an existing table). Blocked. The
   message says `a new .md file written to an unrecognised location`, although
   the file exists and the tool was `Edit`, and lists `./vendor/` as an allowed
   location.
2. `handlers.pre_tool_use.markdown_organization.options.extra_allowed_markdown_paths: ['^vendor/org-a/pkg-a/vendor/org-b/pkg-b/']`,
   daemon restarted. Blocked, same message.
3. Declared both clones under `projects:` (repo-relative `root`, `kind: php`,
   `bin_dirs: [bin]`), `config-validate` reports valid, daemon restarted.
   Blocked, same message.

The same `Edit` on the same file in the clone that sits one level down
(`vendor/org-b/pkg-b/docs/upgrading.md`) is allowed.

## Expected

Any one of: the `./vendor/` allowance covering a path under `vendor/` at any
depth; the `extra_allowed_markdown_paths` pattern matching; or the declared
sub-project's own `docs/` counting as its `docs/`. Also the message should not
call an `Edit` of an existing file a new file.

## Notes

`CLAUDE/Code/WorkspaceResolution.md` notes that several handlers were never
rewired from `ProjectContext.project_root()` to the per-project registry. If
`markdown_organization` is one of them, that would explain why `projects:` has
no effect here. A `bug-report` bundle from the affected session is available
on request.
