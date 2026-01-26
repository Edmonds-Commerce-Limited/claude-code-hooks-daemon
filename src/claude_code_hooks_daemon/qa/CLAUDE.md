# QA Runner Module

**Fast quality assurance execution for Python projects.**

Provides automated QA runner that executes all Python quality checks (ruff, mypy, black, pytest, bandit) and provides structured summary for downstream processing.

## Purpose

- Execute Python QA tools quickly via subprocess
- Parse tool output and extract error/warning counts
- Generate structured results (JSON-serializable)
- Support integration with hook system or CLI

## Architecture

### Core Classes

**QAExecutionError**
- Exception raised when QA tool execution fails
- Wraps subprocess errors (timeout, crash, etc.)

**ToolResult**
- Data class representing single tool execution
- Fields: tool_name, passed, error_count, warning_count, output, duration_ms, files_affected
- Serializable to dict/JSON

**QAResult**
- Data class representing overall QA execution
- Fields: status (passed/failed), tools_run, total_errors, total_warnings, tool_results, summary
- Contains results from all tools
- Serializable to dict/JSON

**QARunner**
- Main orchestrator class
- Methods:
  - `run_ruff()` - Execute ruff linting (JSON output)
  - `run_mypy()` - Execute mypy type checking
  - `run_black()` - Execute black format check
  - `run_pytest()` - Execute pytest tests
  - `run_bandit()` - Execute bandit security linting (optional)
  - `run_all()` - Execute all configured tools
  - `save_results()` - Save QAResult to JSON file
  - `print_summary()` - Print results to console

### Parsing

Static helper methods to extract counts from tool output:
- `_parse_ruff_output()` - Parse JSON array from ruff
- `_parse_mypy_output()` - Count errors from "Found X errors" pattern
- `_parse_black_output()` - Count "would reformat" lines
- `_parse_pytest_output()` - Count "X failed" from output
- `_parse_bandit_output()` - Parse JSON results array

## Usage

### As Module

```python
from claude_code_hooks_daemon.qa import QARunner

runner = QARunner(project_root="/path/to/project")
result = runner.run_all()

print(f"Status: {result.status}")
print(f"Total errors: {result.total_errors}")

# Save to JSON
filepath = runner.save_results(result)
```

### As Command Line

```bash
python3 -m claude_code_hooks_daemon.qa.runner \
  --project-root /path/to/project \
  --tools ruff,mypy,black,pytest \
  --save-results
```

Exit codes:
- 0: All checks passed
- 1: Some checks failed
- 2: Execution error

## Configuration

**Tools to run** (via `tools_to_run` attribute):
```python
runner.tools_to_run = ["ruff", "mypy", "black", "pytest"]
# Optional: add bandit for security checks
runner.tools_to_run = ["ruff", "mypy", "black", "pytest", "bandit"]
```

**Output directory** (for JSON results):
```python
runner = QARunner(
    project_root="/path/to/project",
    output_dir="/var/qa"
)
```

## Output Format

### JSON Structure

```json
{
  "status": "passed",
  "tools_run": ["ruff", "mypy", "black", "pytest"],
  "total_errors": 0,
  "total_warnings": 0,
  "timestamp": "2025-01-20T10:00:00Z",
  "tool_results": [
    {
      "tool_name": "ruff",
      "passed": true,
      "error_count": 0,
      "warning_count": 0,
      "output": "[]",
      "duration_ms": 1234
    },
    {
      "tool_name": "mypy",
      "passed": true,
      "error_count": 0,
      "warning_count": 0,
      "output": "Success: no issues found in 42 source files",
      "duration_ms": 5678
    }
  ],
  "summary": "..."
}
```

### Console Output

```
======================================================================
QA SUMMARY (Python Tools)
======================================================================
Total Errors: 0
Total Warnings: 0
Tools Passed: 4
Tools Failed: 0

Status: PASSED
======================================================================
```

## Tool-Specific Output Parsing

### Ruff (JSON)
```json
[
  {
    "code": "F401",
    "message": "'os' imported but unused",
    "location": {"row": 1, "column": 0},
    "filename": "src/module.py"
  }
]
```

### Mypy (Text)
```
src/module.py:10: error: Incompatible return value type
Found 5 errors in 2 files
```

### Black (Text)
```
would reformat src/module.py
would reformat tests/test_module.py
Oh no! 2 files would be reformatted, 10 files would be left unchanged.
```

### Pytest (Text)
```
collected 28 items
tests/test_module.py ............................                              [100%]
============================== 28 passed in 1.5s ===============================
```

### Bandit (JSON)
```json
{
  "results": [
    {
      "test_id": "B602",
      "issue_text": "subprocess call with shell=True",
      "filename": "src/module.py",
      "line_number": 10
    }
  ],
  "errors": []
}
```

## Error Handling

Errors during tool execution:
- Timeout: QAExecutionError("Command timeout: ...")
- Crash: QAExecutionError("Execution error: ...")
- Exception: Caught and logged in tool result with error_count=-1

Tool execution is resilient - one tool failure doesn't stop others.

## Performance

- Typical execution: 15-60 seconds for all checks
- ruff check: ~1-3s (very fast)
- mypy check: ~5-15s (can be slow on large codebases)
- black check: ~1-3s
- pytest: ~5-30s (depends on test count)
- bandit check: ~2-5s

## Testing

All functionality covered by unit tests:
- Data class serialisation
- Tool execution (mocked subprocess)
- Output parsing (regex patterns)
- Error handling
- File I/O (results saving)
- Integration flow

Run tests:
```bash
python3 -m pytest tests/unit/test_qa_runner.py -v
```

## Dependencies

**Required** (in pyproject.toml):
- ruff>=0.1.0
- mypy>=1.0
- black>=23.0
- pytest>=7.0
- pytest-cov>=4.0

**Optional**:
- bandit>=1.7 (security linting)

## Integration Points

- **Hooks daemon**: Can be invoked as handler for QA validation
- **CLI**: Command-line interface for manual QA runs
- **Agents**: QA agents can import and use this module
- **Build system**: Can be integrated into build hooks
- **CI/CD**: Exit codes suitable for CI pipelines

## Maintenance

- Tests cover all public methods
- Output parsing via stable regex patterns (based on tool output formats)
- Robust error handling for tool failures
- Clear error messages for debugging

---

**Created**: 20 January 2025
**Module**: claude_code_hooks_daemon.qa.runner
**Status**: Production ready
**Python Tools**: ruff, mypy, black, pytest, bandit (optional)
