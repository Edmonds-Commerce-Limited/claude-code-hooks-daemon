# markdown_organization

| Property | Value |
|----------|-------|
| **Config key** | `markdown_organization` |
| **Priority** | 50 |
| **Type** | Blocking |
| **Event** | PreToolUse |

Enforces markdown file organization rules and plan tracking. Intercepts Claude Code planning mode writes to `~/.claude/plans/` and redirects them to the project's `CLAUDE/Plan/` structure when configured.

## Config

```yaml
handlers:
  pre_tool_use:
    markdown_organization:
      enabled: true
      priority: 50
      options:
        track_plans_in_project: "CLAUDE/Plan"
        plan_workflow_docs: "CLAUDE/PlanWorkflow.md"
        # allowed_markdown_paths: [...]
        # monorepo_subproject_patterns: [...]
```

## Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `track_plans_in_project` | `string \| null` | `null` | Path to plan folder (e.g. `"CLAUDE/Plan"`). Enables planning mode redirect. |
| `plan_workflow_docs` | `string \| null` | `null` | Path to workflow doc referenced in redirect context. |
| `allowed_markdown_paths` | `list[string] \| null` | `null` | Regex patterns for allowed locations. **Overrides ALL built-in paths when set.** |
| `monorepo_subproject_patterns` | `list[string] \| null` | `null` | Regex patterns matching sub-project root directories. |

## Built-in Allowed Paths

When `allowed_markdown_paths` is **not set** (default), the handler uses these built-in rules:

| Path pattern | Purpose |
|---|---|
| `CLAUDE/**/*.md` | LLM documentation (with plan number validation) |
| `docs/**/*.md` | Human-facing documentation |
| `untracked/**/*.md` | Temporary/scratch docs |
| `RELEASES/**/*.md` | Release notes |
| `eslint-rules/**/*.md` | ESLint rule documentation |
| `src/claude_code_hooks_daemon/guides/**/*.md` | Shipped daemon guides |

These files are **always allowed** regardless of any config:
- `CLAUDE.md`, `README.md`, `CHANGELOG.md` (anywhere in project)
- `.claude/agents/*.md`, `.claude/commands/*.md`, `.claude/skills/*/SKILL.md`

## Custom Allowed Paths

Set `allowed_markdown_paths` to **completely replace** all built-in rules with your own regex patterns. Each pattern is matched against the project-relative file path.

```yaml
options:
  allowed_markdown_paths:
    - "^CLAUDE/.*\\.md$"        # LLM documentation
    - "^docs/.*\\.md$"          # Human-facing docs
    - "^content/blog/.*\\.md$"  # Blog content (project-specific)
```

Only paths matching at least one pattern are allowed; everything else is blocked.

**Empty list blocks everything** (except always-allowed files like CLAUDE.md).

## Monorepo Support

Set `monorepo_subproject_patterns` to recognise sub-project directories. Matched paths have their prefix stripped before path rules apply.

```yaml
options:
  monorepo_subproject_patterns:
    - "packages/[^/]+"   # packages/frontend/, packages/backend/
    - "apps/[^/]+"       # apps/web/, apps/mobile/
```

## Monorepo + Custom Paths Interaction

Custom `allowed_markdown_paths` patterns match against the **sub-project-relative path** (after prefix stripping). This means the same rules apply uniformly to root and all sub-projects.

| Input path | Stripped to | Pattern matches against |
|---|---|---|
| `docs/guide.md` | *(root, used as-is)* | `docs/guide.md` |
| `packages/frontend/docs/guide.md` | `docs/guide.md` | `docs/guide.md` |
| `packages/backend/CLAUDE/test.md` | `CLAUDE/test.md` | `CLAUDE/test.md` |

### Gotcha

A pattern like `^packages/frontend/docs/.*` will **never match** because the monorepo prefix is already stripped before custom paths are checked. Use `^docs/.*` instead.

This is intentional: write rules once, apply everywhere (DRY).

## Planning Mode Redirect

When `track_plans_in_project` is set, writes to `~/.claude/plans/*.md` (Claude Code planning mode) are intercepted and redirected:

1. Plan content written to `{track_plans_in_project}/{number}-{name}/PLAN.md`
2. Stub redirect file created at original location
3. Context message tells Claude where the plan was saved

Plan numbers are auto-incremented (5-digit zero-padded). Plan folder names are sanitised from the original filename.

## Plan Number Validation

Plans in `CLAUDE/Plan/` must follow the format `{NNN}-description/` where `NNN` is at least 3 digits. Plans without numeric prefixes or with fewer than 3 digits are blocked.

## Examples

**Allow only specific locations:**
```yaml
options:
  allowed_markdown_paths:
    - "^CLAUDE/.*\\.md$"
    - "^docs/.*\\.md$"
```
Result: `CLAUDE/test.md` allowed, `src/notes.md` blocked, `CLAUDE.md` always allowed.

**Monorepo with shared rules:**
```yaml
options:
  monorepo_subproject_patterns:
    - "packages/[^/]+"
  allowed_markdown_paths:
    - "^docs/.*\\.md$"
    - "^CLAUDE/.*\\.md$"
```
Result: Both `docs/api.md` and `packages/frontend/docs/api.md` allowed (same pattern).
