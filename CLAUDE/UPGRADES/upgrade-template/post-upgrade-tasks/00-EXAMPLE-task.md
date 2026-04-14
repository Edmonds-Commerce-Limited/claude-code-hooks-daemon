# Task: [Short human title]

> **TEMPLATE FILE.** Copy this for new tasks and rename with a two-digit ordinal and kebab-case slug, e.g. `01-audit-markdown-frontmatter.md`. Delete this file from each released upgrade guide — it only belongs in the template.

**Type**: audit | config-migration | data-migration | workflow-change | notification | other
**Severity**: critical | recommended | optional
**Applies to**: [e.g. "≤vX.Y.Z", "vA.B.C..vX.Y.Z", or "all"]
**Idempotent**: yes | no

## Why

One short paragraph on what motivated this task. Reference the commit, issue, or changelog entry that introduced the change if applicable.

## How to detect if this applies to you

Plain-language guidance telling an LLM how to decide whether the task applies to this specific project. Embed **sample** commands the LLM can adapt — they are illustrative, not canonical, and should never be copy-pasted without judgement.

If `Applies to: all`, this section can be a single sentence saying so.

## How to handle

Plain-language instructions. Cover:

- What the LLM should look for in detection output.
- Suggested remediation paths.
- When to act autonomously vs. when to escalate to the user.
- Any destructive operations to avoid unless the user explicitly approves.

Sample commands are allowed — bash for simple operations, Python for complex transformations. Label them **sample** to make it clear they may need adapting to the user's project.

## How to confirm

One or two short checks that demonstrate the task is complete.

## Rollback / if this goes wrong

Optional but strongly encouraged for any task that modifies files. Describe how to recover if the remediation turns out to be wrong for this project.
