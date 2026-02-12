# Plan: LLM Command Wrappers for Project QA Tools (Dogfooding Plan 052)

## Context

This project created a guide (Plan 052) explaining the LLM command wrapper pattern - minimal stdout, structured JSON to file, JQ-optimizable. The project should dogfood its own recommendations. The existing QA scripts (`scripts/qa/run_*.sh`) already produce JSON output to `untracked/qa/*.json` with a consistent schema (`summary.passed`, violation arrays, etc.). What's missing is the **minimal stdout layer** - a way to run QA with LLM-optimized output (3-5 lines per tool instead of 50+).

## Approach: Single Python Script (`scripts/qa/llm_qa.py`)

Rather than creating 7 separate wrapper scripts, create **one unified Python script** that:
- Takes tool name(s) as arguments (or `all`)
- Runs the underlying bash script with stdout/stderr suppressed
- Reads the JSON output from `untracked/qa/`
- Prints 3-5 lines of minimal, machine-friendly stdout per tool
- Returns proper exit code (0 = all pass, 1 = any fail)

### Why one script, not seven

- **DRY**: Same summarization pattern for every tool
- **Consistent**: Identical output format regardless of tool
- **Maintainable**: Add new tools by adding a config entry, not a new file
- **Discoverable**: One entry point to learn
- **The JSON is already standardized**: All tools write to `untracked/qa/*.json` with `summary.passed`

## Output Format (Per Tool)

```
✅ tests: 5408 passed, 0 failed, 3 skipped | coverage: 95.27%
   untracked/qa/tests.json | jq '.summary'
```

Or on failure:
```
❌ lint: 3 violations (2 errors, 1 warning)
   untracked/qa/lint.json | jq '.violations[] | {file, rule, message}'
```

Each tool gets exactly 2 lines:
- **Line 1**: Pass/fail emoji + tool name + key metrics
- **Line 2**: JSON path + useful jq command

## Output Format (All Mode)

```
✅ magic_values: 0 violations
   untracked/qa/magic_values.json | jq '.summary'
✅ format: 0 files reformatted
   untracked/qa/format.json | jq '.violations[].file'
✅ lint: 0 violations
   untracked/qa/lint.json | jq '.violations[]'
✅ type_check: 0 errors
   untracked/qa/type_check.json | jq '.errors[]'
✅ tests: 5408 passed, 0 failed, 3 skipped | coverage: 95.27%
   untracked/qa/tests.json | jq '.summary'
✅ security: 0 issues
   untracked/qa/security.json | jq '.issues[]'
✅ dependencies: 0 issues
   untracked/qa/dependencies.json | jq '.issues[]'

QA: 7/7 PASSED
```

Total: ~16 lines for all 7 tools. Compare to 200+ lines from `run_all.sh`.

## Usage

```bash
# Run all QA checks with LLM-friendly output
./scripts/qa/llm_qa.py all

# Run individual tools
./scripts/qa/llm_qa.py tests
./scripts/qa/llm_qa.py lint
./scripts/qa/llm_qa.py security

# Run multiple specific tools
./scripts/qa/llm_qa.py tests lint type_check

# Just read existing JSON (don't re-run tools, --read-only flag)
./scripts/qa/llm_qa.py --read-only all
```

## Tool Registry (Config Inside Script)

```python
TOOLS = {
    "magic_values": {
        "script": "check_magic_values.py",  # Special: runs via python
        "json_file": "magic_values.json",
        "summary_fn": lambda s: f"{s.get('total_violations', 0)} violations",
        "jq_hint": "jq '.violations[] | {file, rule, message}'",
    },
    "format": {
        "script": "run_format_check.sh",
        "json_file": "format.json",
        "summary_fn": lambda s: f"{s.get('total_violations', 0)} files reformatted",
        "jq_hint": "jq '.violations[].file'",
    },
    "lint": {
        "script": "run_lint.sh",
        "json_file": "lint.json",
        "summary_fn": ...,
        "jq_hint": "jq '.violations[] | {file, rule, message}'",
    },
    # ... etc for each tool
}
```

## Files to Create/Modify

### New Files
1. **`scripts/qa/llm_qa.py`** - The unified LLM QA wrapper (~200 lines)
   - Executable (`chmod +x`, shebang `#!/usr/bin/env python3`)
   - Tool registry with per-tool config
   - `run_tool()` - executes script, suppresses stdout, reads JSON
   - `summarize_tool()` - formats 2-line output from JSON
   - `main()` - CLI argument parsing, run/summarize loop
   - `--read-only` flag to just summarize existing JSON without re-running

### Modified Files
2. **`CLAUDE.md`** - Add `llm_qa.py` to Quick Commands section
3. **`scripts/qa/run_all.sh`** - No changes (keep as-is for human use)

### No Test Files Needed
This is a CLI utility script, not daemon code. It reads JSON and prints text. Testing is done by running it and verifying output. No pytest coverage requirement since it's not in `src/`.

## Implementation Steps

1. Create `scripts/qa/llm_qa.py` with tool registry and CLI
2. Implement per-tool summary formatters (each reads JSON, extracts key metrics)
3. Implement `--read-only` mode (skip script execution, just read existing JSON)
4. Make executable (`chmod +x`)
5. Test manually: `./scripts/qa/llm_qa.py all` vs `./scripts/qa/run_all.sh`
6. Update CLAUDE.md quick commands
7. Run daemon restart verification (changes to CLAUDE.md)
8. Commit

## Verification

```bash
# Compare output volume
./scripts/qa/run_all.sh 2>&1 | wc -l    # Expected: 200+ lines
./scripts/qa/llm_qa.py all 2>&1 | wc -l  # Expected: ~16 lines

# Verify exit codes match
./scripts/qa/run_all.sh; echo $?
./scripts/qa/llm_qa.py all; echo $?

# Verify read-only mode
./scripts/qa/llm_qa.py --read-only all   # Just reads existing JSON

# Verify individual tool mode
./scripts/qa/llm_qa.py tests             # Just runs pytest + summary

# Verify jq hints work
eval "$(./scripts/qa/llm_qa.py --read-only tests 2>/dev/null | grep jq)"
```
