# Research: Markdown Table Auto-Formatting Tools

**Date**: 2026-04-09
**Context**: Claude writes markdown tables with unaligned pipes. We need a tool to auto-format them into human-friendly aligned tables while remaining valid markdown.

## The Problem

Claude produces tables like this:

```
| Field | Key | Zoho Type | Required | Visibility |
|-------|-----|-----------|----------|------------|
| Snapshot Taken At | `cf_stat_snapshot_taken_at` | DateTime | No | Stats |
| Total Orders | `cf_stat_total_orders` | Number | No | Stats |
```

Pipes do not line up vertically. The header rule row (`|-------|`) does not match the cell widths. It is valid markdown but unreadable as source.

We want this:

```
| Field             | Key                           | Zoho Type | Required | Visibility |
| ----------------- | ----------------------------- | --------- | -------- | ---------- |
| Snapshot Taken At | `cf_stat_snapshot_taken_at`   | DateTime  | No       | Stats      |
| Total Orders      | `cf_stat_total_orders`        | Number    | No       | Stats      |
```

All pipes aligned. Columns padded to consistent width. Delimiter row widened to match. Still valid markdown.

## Candidate Tools

### 1. mdformat + mdformat-gfm (RECOMMENDED)

**What**: Pure-Python CommonMark formatter by Taneli Hukkinen, hosted under executablebooks.

**Install**:
```bash
pip install mdformat mdformat-gfm
```

**Default behaviour**: Aligns pipes in GFM tables by default. Columns are padded to consistent width. Delimiter row widened to match. Outer pipes added on both sides.

**Before**:
```
a | b | c
:- | -: | :-:
1 | 2 | 3
xxxxxx | yyyyyy | zzzzzz
```

**After**:
```
| a      |      b |   c    |
| :----- | -----: | :----: |
| 1      |      2 |   3    |
| xxxxxx | yyyyyy | zzzzzz |
```

Note that colons for column alignment (`:-`, `-:`, `:-:`) are preserved and cell content is visually aligned accordingly (left / right / centre).

**CLI**:
```bash
mdformat path/to/file.md              # In-place format
mdformat --check path/to/file.md      # Check only
cat file.md | mdformat -               # Read stdin, write stdout
```

**Python API**:
```python
import mdformat
formatted = mdformat.text(raw_markdown)          # Format a string
mdformat.file("path/to/file.md")                  # Format a file in place
```

**Pros**:
- Pure Python — integrates cleanly with the daemon venv (already Python)
- Idempotent — safe to re-run, produces stable output
- Maintained actively under executablebooks
- MIT licensed
- Plugin architecture allows extending for other needs (footnotes, frontmatter, etc.)
- Has a `--check` mode for validation (useful for PostToolUse advisory)
- Can work on stdin/stdout (useful for daemon socket exposure without touching disk)

**Cons**:
- Reformats entire file, not just tables (may reflow code blocks, normalise headings, etc.) — this is desirable for consistency but surprising if unexpected. Can be controlled via config: `[plugin.gfm]` and other sections in `.mdformat.toml`
- Requires Python 3.10+ (project already meets this)

**Opinion**: Strongest candidate. Python-native, pip-installable, produces aligned output by default, has both CLI and API, already matches the project's stack.

### 2. markdown-table-prettify (npm)

**What**: Node.js library and VS Code extension specifically for prettifying markdown tables.

**Install**:
```bash
npm install -g markdown-table-prettify
```

**Pros**:
- Table-specific (doesn't touch anything else)
- Clean before/after behaviour
- Available as CLI and as a library

**Cons**:
- Requires Node runtime — extra dependency for a Python project
- Not as widely maintained

### 3. markdownlint-cli2 with MD060

**What**: The markdownlint rule MD060 (`table-column-style`) defines three styles: `aligned`, `compact`, `tight`.

**Pros**:
- Well-known lint tool
- `aligned` style matches the human-friendly target

**Cons**:
- **MD060 is NOT auto-fixable by `markdownlint-cli2 --fix`** (known limitation, confirmed in upstream issues)
- Only detects violations, doesn't rewrite tables
- Requires Node runtime

**Verdict**: Useful for validation, not for auto-fixing. Not suitable for our core goal.

### 4. Prettier (markdown mode)

**What**: Prettier added markdown support in v1.8 (2017), including table formatting.

**Pros**:
- Ubiquitous, well-known

**Cons**:
- Expands tables significantly — wider than necessary
- Known to handle large tables poorly (upstream issues)
- Requires Node runtime
- Not configurable enough for this use case

### 5. Pure-Python table libraries (tabulate, py-markdown-table, pytablewriter)

**What**: These libraries GENERATE markdown tables from data (dicts, CSVs, pandas DataFrames). They do NOT reformat existing markdown.

**Verdict**: Wrong tool for the job. Useful for generating tables from data, not for reformatting Claude's output.

### 6. markdown-table-formatter (npm / megalinter)

**What**: A dedicated Node.js table formatter that MD060-aligns tables.

**Pros**:
- Table-specific
- Compliant with markdownlint MD060 aligned style

**Cons**:
- Node runtime dependency
- Less mature than mdformat

## Comparison Matrix

| Tool                      | Language | Scope         | Auto-Align | Library API | CLI | Idempotent | Project Fit |
| ------------------------- | -------- | ------------- | ---------- | ----------- | --- | ---------- | ----------- |
| mdformat + mdformat-gfm   | Python   | Whole file    | Yes        | Yes         | Yes | Yes        | Excellent   |
| markdown-table-prettify   | Node     | Tables only   | Yes        | Yes         | Yes | Yes        | Poor (node) |
| markdownlint-cli2         | Node     | Lint (detect) | No (fix)   | Yes         | Yes | N/A        | Poor (no fix) |
| Prettier (markdown)       | Node     | Whole file    | Partial    | Yes         | Yes | Yes        | Poor (node, expands) |
| tabulate / py-markdown-table | Python | Generate only | N/A        | Yes         | No  | N/A        | Wrong tool  |
| markdown-table-formatter  | Node     | Tables only   | Yes        | Yes         | Yes | Yes        | Poor (node) |

## Recommendation

**Use `mdformat` + `mdformat-gfm`**.

Rationale:
1. Python-native — installs into the existing daemon venv with no new runtime dependency
2. Produces the exact aligned output we want by default
3. Has both a CLI (for quick file formatting) and a Python API (for socket exposure inside the daemon)
4. Idempotent — re-running produces the same output, so it's safe to run in a PostToolUse handler after every Write/Edit
5. Actively maintained under the executablebooks org
6. Has a `--check` mode for advisory validation without modification
7. Matches the project's style of solving problems with Python libraries

## Integration Options

Once `mdformat + mdformat-gfm` is installed, there are several ways to wire it in:

### Option A — PostToolUse handler that runs mdformat after `.md` writes

A PostToolUse handler (like `lint_on_edit`) fires on Write/Edit of `.md` files, runs `mdformat.file(path)` on the file after write, and returns an advisory context message noting the format. Simple, automatic, invisible to the user on success.

Risks: Reformats the whole file, not just tables. Might reflow code blocks or other content unexpectedly. Mitigation: configure mdformat with conservative options via `.mdformat.toml` in the project, or limit the handler to files that contain table markers.

### Option B — PreToolUse advisory on `.md` writes

A PreToolUse handler detects Write/Edit of `.md` content containing tables, runs `mdformat --check` on the proposed content, and if unaligned returns a DENY with the reformatted content embedded in the reason. Claude must then re-submit the Write with the aligned content.

Risks: More intrusive. Every `.md` write becomes a two-step process when tables are involved. Burns tokens.

### Option C — Daemon socket endpoint + slash command

Expose a `format_markdown` operation via the daemon socket. Add a slash command like `/format-md` that Claude can invoke on demand. No automatic enforcement, just a tool.

Risks: Relies on Claude remembering to use it.

### Option D — Combined: auto-format + optional block

Install `mdformat + mdformat-gfm` in the venv. Add a PostToolUse handler that runs `mdformat.file()` on `.md` files after write (Option A). Also expose it as a CLI command `$PYTHON -m claude_code_hooks_daemon.daemon.cli format-markdown <path>` for ad-hoc use. Best of both worlds: automatic when writing, on-demand when fixing existing files.

**Recommended**: Option D. Start with Option A (PostToolUse auto-format) and add the CLI for batch fixes to existing files.

## Sample Implementation Sketch

```python
# src/claude_code_hooks_daemon/handlers/post_tool_use/markdown_table_formatter.py
import mdformat
from pathlib import Path

from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.decision import Decision

_MARKDOWN_EXTENSIONS = (".md", ".markdown")
_HANDLER_NAME = "markdown_table_formatter"
_HANDLER_PRIORITY = 26

class MarkdownTableFormatterHandler(Handler):
    def __init__(self) -> None:
        super().__init__(
            name=_HANDLER_NAME,
            priority=_HANDLER_PRIORITY,
            terminal=False,
        )

    def matches(self, hook_input: dict) -> bool:
        tool_name = hook_input.get("tool_name", "")
        if tool_name not in ("Write", "Edit"):
            return False
        file_path = hook_input.get("tool_input", {}).get("file_path", "")
        return file_path.lower().endswith(_MARKDOWN_EXTENSIONS)

    def handle(self, hook_input: dict) -> HookResult:
        file_path = Path(hook_input["tool_input"]["file_path"])
        if not file_path.exists():
            return HookResult(decision=Decision.ALLOW)
        try:
            before = file_path.read_text(encoding="utf-8")
            mdformat.file(str(file_path))
            after = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            # FAIL FAST on formatter errors
            return HookResult(
                decision=Decision.ALLOW,
                context=f"markdown_table_formatter: {exc}",
            )
        if before == after:
            return HookResult(decision=Decision.ALLOW)
        return HookResult(
            decision=Decision.ALLOW,
            context=f"Reformatted markdown tables in {file_path.name}",
        )
```

## Sources

- [mdformat (Python, CommonMark)](https://github.com/hukkin/mdformat)
- [mdformat-gfm (GFM tables plugin)](https://github.com/hukkin/mdformat-gfm)
- [mdformat-tables (archived, moved into mdformat-gfm)](https://github.com/executablebooks/mdformat-tables)
- [mdformat docs - installation and usage](https://mdformat.readthedocs.io/en/stable/users/installation_and_usage.html)
- [mdformat-gfm on PyPI](https://pypi.org/project/mdformat-gfm/)
- [markdownlint MD060 rule](https://github.com/DavidAnson/markdownlint/blob/main/doc/md060.md)
- [markdownlint-cli2](https://github.com/DavidAnson/markdownlint-cli2)
- [markdown-table-prettify (npm)](https://www.npmjs.com/package/markdown-table-prettify)
- [Prettier 1.8 markdown support (2017)](https://prettier.io/blog/2017/11/07/1.8.0.html)
- [Prettier large-table issue](https://github.com/prettier/prettier/issues/3211)
- [tabulate (generation only)](https://pypi.org/project/tabulate/)
- [py-markdown-table (generation only)](https://pypi.org/project/py-markdown-table/)
