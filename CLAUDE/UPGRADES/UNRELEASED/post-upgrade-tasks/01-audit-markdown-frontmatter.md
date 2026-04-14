# Task: Audit Markdown Files for Mangled YAML Frontmatter

**Type**: audit
**Severity**: recommended
**Applies to**: v3.0.0..v3.2.1
**Idempotent**: yes

## Why

Versions v3.0.0 through v3.2.1 shipped the `markdown_table_formatter` (PostToolUse) handler and the `format-markdown` CLI command with a bug: `mdformat` does not understand YAML frontmatter, and the handler passed the entire file (including frontmatter) to it. This caused any `.md` file whose first line was `---` — notably Claude Code `SKILL.md` files, but also Jekyll/Hugo/MkDocs pages and any documentation using frontmatter — to be silently rewritten so that:

- The opening `---` became a 70-underscore thematic break (`______________________________________________________________________`).
- The YAML body (e.g. `name:`, `description:`, `argument-hint:`) was collapsed onto a single line prefixed with `##`, turning it into a heading.
- The closing `---` was lost (or, if preceded by more content, preserved as another thematic break).

The fix ensures frontmatter is now stripped before formatting and re-attached byte-for-byte afterwards, but **files that were already damaged on disk before the upgrade remain damaged**. A clean install of the fixed daemon does not undo prior corruption.

## How to detect if this applies to you

If the project has never been on v3.0.0–v3.2.1, skip this task.

Otherwise, scan the project for markdown files showing the corruption signature. The signature is a leading 70-underscore thematic break, optionally followed (possibly with blank lines) by a `##` heading containing `name:`, `description:`, `argument-hint:`, `allowed-tools:`, or another typical frontmatter key collapsed onto one line.

**Sample detection (bash + ripgrep)** — adapt paths for the project's conventions:

```bash
# Find files whose first non-empty line is the 70-underscore thematic break.
# These are the highest-confidence matches.
rg --files -g '*.md' -g '*.markdown' \
  | while IFS= read -r f; do
      head -n 1 "$f" | grep -q '^_\{70\}$' && echo "SUSPECT: $f"
    done

# Secondary signal: a `##` heading containing collapsed frontmatter keys.
rg -n --no-heading '^## .*\b(name|description|argument-hint|allowed-tools):' \
  -g '*.md' -g '*.markdown'
```

Typical locations to check (non-exhaustive):

- `.claude/skills/**/SKILL.md` — the most likely victims on this project
- `.claude/agents/**/*.md` — if agents use frontmatter
- Any static-site content directories (Jekyll `_posts/`, Hugo `content/`, MkDocs `docs/`)
- Any `.md` file that the user knows started with `---`

## How to handle

For each suspected file:

1. **Read the file and confirm the corruption.** False positives are possible — a document could legitimately start with a thematic break. Compare against the signature described above.

2. **Check git history for an uncorrupted version:**

   ```bash
   git log --all --follow -- path/to/suspect.md
   # Inspect a candidate revision:
   git show <commit>:path/to/suspect.md
   ```

3. **Restore from the most recent clean revision** if one exists:

   ```bash
   git checkout <clean-commit> -- path/to/suspect.md
   ```

4. **If no clean revision exists in git** (file was created after the bug was introduced and never committed clean):

   - For SKILL.md files: ask the user to provide the original frontmatter or regenerate the skill via its authoring process.
   - For other files: ask the user what the original frontmatter should contain. **Do not guess** — fabricated frontmatter (especially `name:` / `description:` for SKILL.md) can silently change skill discoverability or behaviour.

5. **If the user has no backup and can't remember the frontmatter**: leave the file as-is and surface the issue. Destructive writes from an LLM that guessed the contents are worse than a visibly-broken file the user can recognise and fix.

Report the full list of suspects, what action was taken for each, and any that require the user's input.

## How to confirm

Re-run the detection commands. Zero matches means all known corruption has been addressed for this project.

For any file that was restored from git, open it and confirm the frontmatter block now starts with `---` on line 1 and closes with a standalone `---` on its own line.

## Rollback / if this goes wrong

Every suggested remediation uses `git checkout` against an existing commit, which is non-destructive — the restored file lives in the working tree and can be inspected before committing.

If a wrong revision is chosen, run `git checkout HEAD -- path/to/file.md` to restore the current working-tree version, or `git log -p -- path/to/file.md` to pick a different commit.
