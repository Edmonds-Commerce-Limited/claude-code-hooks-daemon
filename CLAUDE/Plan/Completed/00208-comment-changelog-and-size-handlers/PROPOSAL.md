# Handler proposal: comment-size cap + no-changelog-in-comments

**Component:** claude-code-hooks-daemon — new `PreToolUse` handlers on `Write`/`Edit`.
**Reported from:** `LongTermSupport/fedora-desktop` (CCY launcher, `files/var/local/claude-yolo/claude-yolo`).
**Motivation:** an agent-authored comment in that repo reached **5,645 characters** on a single
line, having accumulated six releases of history — and it silently broke a user-facing banner.

---

## The rule this enforces

Three artifacts, three jobs. They are not interchangeable, and an LLM conflates them
constantly because a comment is the cheapest place to put text.

| Artifact                       | Job                                            |
| ------------------------------ | ---------------------------------------------- |
| **git**                        | tracking changes — what changed, when, by whom |
| **changelog files / journals** | documenting changes for humans over time       |
| **code comments**              | **CURRENT STATE, RELEVANT INFO ONLY**          |

A comment describes the code as it is now, and why it is that way. The moment a comment
starts carrying "in 3.26.1 we did X, prior to that Y", it has become a changelog living in
the wrong file — unreadable, unsearchable, never pruned, and duplicating git.

## Why this needs a handler and not a style guide

The failure mode is **monotonic**. Nobody ever deletes from a comment changelog; each agent
that touches the file appends one more entry and preserves the rest, because deleting
someone else's note feels destructive. It only ever grows. A CLAUDE.md rule saying "keep
comments short" does not fire at the moment of the append — a handler does.

### Concrete damage (this is not hypothetical)

`files/var/local/claude-yolo/claude-yolo` carries a version marker whose trailing comment is
the release note:

```bash
CCY_VERSION="3.27.1"  # Patch: 3.27.0 was assigned to two different script contents … Prior 3.26.2: … Prior 3.26.1: … Prior 3.26.0: … Prior 3.25.0: … Prior 3.24.0: …
```

- **5,645 characters on one line**, six releases deep.

- The file's own rebuild banner reads that comment and prints it to the user:

  ```bash
  # claude-yolo:1508
  ccy_version_line=$(grep '^CCY_VERSION=' "$0")
  ccy_changelog="${ccy_version_line#*# }"
  echo "Rebuilding to include: $ccy_changelog"
  ```

  So "Rebuilding to include:" dumps **the entire accumulated history** into the terminal,
  every time a base image updates. The pattern did not merely offend taste; it broke the one
  feature that consumed the comment.

- No human wrote any of it. Each entry was appended by an agent following the shape of the
  previous entry — the pattern is self-perpetuating once seeded.

## Proposed handler 1 — `comment_size`

Blocks a `Write`/`Edit` whose content contains an over-long comment.

**Signals** (either trips it):

- a single comment **line** longer than `max_comment_line_chars` (suggest **400**)
- a contiguous comment **block** longer than `max_comment_block_lines` (suggest **40**)

**Tiering, mirroring `plan-doc-size`:** only an edit that **grows** an already-over-limit
comment is blocked. Shrinking is silent; a same-size edit advises. That keeps an
over-commented legacy file editable so it can be refactored down, instead of freezing it.

## Proposed handler 2 — `comment_changelog`

Blocks a `Write`/`Edit` that writes **historical narrative** into a comment. This is the
handler that actually matters — size is a proxy, history is the defect.

**High-precision signals** (each is close to unambiguous on its own):

| Signal                                                                | Example                                   |
| --------------------------------------------------------------------- | ----------------------------------------- |
| `Prior <semver>:` / `Previously <semver>:`                            | `Prior 3.26.2: whitelist the supervisor…` |
| Two or more distinct `<semver>` tokens in one comment                 | `3.27.0 … 3.26.1 … 3.25.0`                |
| A version transition arrow                                            | `2.20 -> 2.22`, `v1.2 → v1.3`             |
| Dated entry inside a comment                                          | `2026-08-12: switched to pasta`           |
| Changelog verb at the start of a clause, past tense, naming a version | `Bumped in 3.24.0`, `Removed in v2.1.224` |

**Lower-precision signals** (advise, don't block): `Fixed:` / `Added:` / `Changed:` bullet
runs inside one comment; "used to", "no longer", "we switched from".

### What must NOT be flagged — history *as rationale* is legitimate

This is the distinction that makes or breaks the handler. A comment may recount the past when
the past is the **reason the current code looks the way it does** and re-litigating it would
cause a regression. From the same repo, `entrypoint.sh`:

```bash
# History (Plan 00047 — do NOT re-add DISABLE_MOUSE without reading this):
# fullscreen draws on the terminal alt-screen, and with mouse capture OFF … Wayland
# terminals fall back to DECSET-1007 "alternate scroll" and remap the wheel to arrow keys …
```

That is *current-state relevant*: it exists to stop the next agent re-introducing a fixed
bug. It is anchored to code that is present, addresses a decision that is still live, and
does not accumulate — a second incident would replace it, not append to it.

The separating test is **"does this comment grow when the code changes, or does it get
rewritten?"** A changelog appends; a rationale is replaced. Practical proxies:

- an entry keyed by a **release number** is a changelog (blocked) — an entry keyed by a
  **failure mode** is a rationale (allowed)
- narrative about code that **is not in this file any more** is a changelog
- more than `max_history_entries` (suggest **1**) dated/versioned entries in one comment is
  a changelog regardless of phrasing

## Configuration

```yaml
handlers:
  pre_tool_use:
    comment_size:
      enabled: true
      options:
        max_comment_line_chars: 400
        max_comment_block_lines: 40
        mode: block            # block | warn
        exclude_paths: []      # plus daemon.exclude_paths
    comment_changelog:
      enabled: true
      options:
        max_history_entries: 1
        mode: block
        exclude_paths: []
```

Both should honour the project-wide `daemon.exclude_paths` and skip vendor/build trees, in
line with `error_hiding_blocker` and `qa_suppression`.

**Languages:** `#` (bash, Python, YAML, Ruby), `//` and `/* … */` (C-family, JS, Go, Rust,
PHP), `<!-- … -->` (HTML/XML), `--` (SQL, Lua), `;` (Lisp, ini). Python/JS **docstrings and
JSDoc blocks are API documentation, not comments** — exempt from `comment_size`, still
subject to `comment_changelog`. Markdown prose is not a comment; skip `.md` entirely.

**Escape hatch**, matching the daemon's existing `MUST_…_BECAUSE` convention:

```bash
# MUST_EXCEED_COMMENT_SIZE_BECAUSE: verbatim upstream licence text, must not be reflowed
```

## Remediation message

The block should not merely refuse — it must name the destination, because "where does this
text go instead" is exactly what the agent does not know:

```
BLOCKED: changelog content in a code comment (3 versioned entries).

Comments describe CURRENT STATE only. Move the history:
  • what changed and when  → git (it is already there — the commit message)
  • release notes for humans → the project's changelog file
  • in-flight narrative      → the plan's JOURNAL/ day-file

Keep in the comment only what is true of the code as it stands now.
```

## Priority

`comment_changelog` is the valuable half. Comment *length* is mostly a symptom — a 400-char
comment that explains one genuinely intricate mechanism is fine, while a 200-char comment
carrying two release notes is not. If only one handler ships, ship the changelog one.
