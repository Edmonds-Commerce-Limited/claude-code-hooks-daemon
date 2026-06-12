# Task: Migrate `allowed_markdown_paths` override to additive `extra_allowed_markdown_paths`

**Type**: config-migration
**Severity**: recommended
**Applies to**: all projects that set `allowed_markdown_paths` in `.claude/hooks-daemon.yaml`
**Idempotent**: yes

## Why

The `markdown_organization` handler now supports `extra_allowed_markdown_paths` — an
**additive** list of allowed-location regex patterns layered on top of the built-in
defaults. Previously the only way to allow an extra markdown location was
`allowed_markdown_paths`, which **completely replaces** the built-in rules. That forces
a project to copy the entire default set and maintain it forever: every new built-in
location the daemon ships (for example, all markdown inside `.claude/skills/`) silently
fails to apply until the project manually copies it into its override.

If your project only needs to **add** a location, the additive option is strictly better:
you keep all upstream defaults automatically and declare only your extras.

## How to detect if this applies to you

Check whether `.claude/hooks-daemon.yaml` sets `allowed_markdown_paths` under
`handlers.pre_tool_use.markdown_organization.options`:

```bash
# sample — adapt to your config layout
grep -n "allowed_markdown_paths" .claude/hooks-daemon.yaml
```

- If only `extra_allowed_markdown_paths` appears (or neither): nothing to do.
- If `allowed_markdown_paths` (the override) is present: this task applies — consider migrating.

## How to handle

1. Compare your override list against the built-in defaults (see
   `docs/guides/handlers/markdown_organization.md` → "Built-in Allowed Paths" and the
   always-allowed files). The built-ins cover `CLAUDE/`, `docs/`, `untracked/`,
   `RELEASES/`, `eslint-rules/`, `src/<pkg>/guides/`, `src/<pkg>/skills/`,
   `CLAUDE.md`/`README.md`/`CHANGELOG.md` anywhere, the standard repo-root files
   (`CONTRIBUTING.md`, `LICENSE.md`, `SECURITY.md`, …), and
   `.claude/{agents,commands,rules,skills}`.

2. Identify which of your override patterns are **NOT** already covered by the built-ins
   — those are your genuine extras (e.g. `^content/blog/.*\.md$`, `^\.github/.*\.md$`).

3. Replace the `allowed_markdown_paths` block with `extra_allowed_markdown_paths`
   containing only the genuine extras. Sample:

   ```yaml
   handlers:
     pre_tool_use:
       markdown_organization:
         options:
           extra_allowed_markdown_paths:
             - "^\\.github/.*\\.md$"
             - "^content/blog/.*\\.md$"
   ```

4. Restart the daemon and verify it reports RUNNING.

**Keep the override only if you deliberately want to FORBID a built-in default location**
(the one case where full replacement is the right tool). If so, no migration is needed —
`allowed_markdown_paths` is still fully supported.

**When to ask the user**: if the override forbids a location the built-ins would allow
(i.e. the override is narrower than the defaults on purpose), confirm with the user before
switching to additive, since additive would re-permit those locations.

## How to confirm

- `grep -n "allowed_markdown_paths" .claude/hooks-daemon.yaml` shows only the additive key.
- Daemon restarts and reports RUNNING.
- A test write to a built-in location (e.g. `docs/`) and to one of your extras both succeed;
  an unrelated location (e.g. `src/notes.md`) is still blocked.

## Rollback / if this goes wrong

The change is config-only. Restore the previous `allowed_markdown_paths` block from
`git` (`git show HEAD:.claude/hooks-daemon.yaml`) and restart the daemon.
