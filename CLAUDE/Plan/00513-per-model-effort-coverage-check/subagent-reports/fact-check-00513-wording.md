# Fact check: Plan 00513 PLAN.md wording diff

Claim 1: "A model with no entry therefore takes the top-level `effortLevel` if one applies, and otherwise runs at its own default effort, and those defaults differ between releases."

Verdict: VERIFIED (0 refuted).

Evidence (vendored docs; code.claude.com copy identical to docs.claude.com copy):
- remote-docs/code.claude.com/docs/en/settings-reference.md:676 effortLevel is "a default effort level for models without a saved level of their own".
- settings-reference.md:958 and :1248 a model's modelSettings level beats the top-level key in the same file; across files the highest-precedence file setting either wins.
- settings-reference.md:977 and docs.claude.com/en/docs/claude-code/model-config.md:613: a top-level effortLevel in USER settings is ignored by Opus 5.5 and later, which start at their own default. In project, local, managed and --settings it applies to every model. This is why "if one applies" is correct and necessary.
- model-config.md:613 "Opus 5.5 starts at `medium`" shows defaults are per model; "differ between releases" is supported by the older/newer split there.

Caveat: other sources (CLAUDE_CODE_EFFORT_LEVEL, --effort) outrank both; the sentence is about the settings fallback only, so it is not wrong.
