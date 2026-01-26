# QA Infrastructure

**Created**: 2026-01-20
**Status**: Complete
**TDD**: All tests written first, implementation follows

## Overview

Comprehensive QA infrastructure with JSON output logging for the daemon project.

## Directory Structure

```
/workspace/.claude/hooks/claude-code-hooks-daemon/
├── untracked/
│   ├── .gitignore                  # Ignores all untracked files
│   └── qa/                          # QA output directory
│       ├── lint.json                # Ruff linter results
│       ├── type_check.json          # Mypy type checker results
│       ├── tests.json               # Pytest test results
│       ├── format.json              # Black format check results
│       └── coverage.json            # Coverage report
├── scripts/
│   └── qa/
│       ├── run_all.sh               # Master script - runs all checks
│       ├── run_lint.sh              # Ruff linter
│       ├── run_type_check.sh        # Mypy type checker
│       ├── run_tests.sh             # Pytest with coverage
│       └── run_format_check.sh      # Black format checker
└── tests/
    └── test_qa_scripts.py           # TDD tests for QA infrastructure
```

## QA Scripts

### 1. `run_lint.sh` - Ruff Linter

**Purpose**: Run ruff linter and output violations to JSON

**Output**: `untracked/qa/lint.json`

**Format**:
```json
{
  "tool": "ruff",
  "summary": {
    "total_files_checked": 36,
    "total_violations": 92,
    "errors": 0,
    "warnings": 92,
    "passed": false
  },
  "violations": [
    {
      "file": "src/module.py",
      "line": 10,
      "column": 5,
      "rule": "I001",
      "message": "Import block is un-sorted",
      "severity": "warning"
    }
  ],
  "files": ["src/file1.py", "src/file2.py"]
}
```

**Exit Code**:
- `0` = No violations
- `1` = Violations found

### 2. `run_type_check.sh` - Mypy Type Checker

**Purpose**: Run mypy type checker and output errors to JSON

**Output**: `untracked/qa/type_check.json`

**Format**:
```json
{
  "tool": "mypy",
  "summary": {
    "total_files_checked": 5,
    "total_errors": 10,
    "passed": false
  },
  "errors": [
    {
      "file": "src/module.py",
      "line": 42,
      "column": 0,
      "severity": "error",
      "message": "Incompatible types in assignment"
    }
  ],
  "files": ["src/file1.py", "src/file2.py"]
}
```

**Exit Code**:
- `0` = No type errors
- `1` = Type errors found

### 3. `run_tests.sh` - Pytest with Coverage

**Purpose**: Run pytest test suite with coverage reporting

**Output**:
- `untracked/qa/tests.json` - Test results
- `untracked/qa/coverage.json` - Coverage data

**Format**:
```json
{
  "tool": "pytest",
  "summary": {
    "total": 364,
    "passed": 364,
    "failed": 0,
    "skipped": 0,
    "passed_all": true
  },
  "tests": [
    {
      "name": "tests/test_module.py::test_function",
      "outcome": "passed",
      "duration": 0.01
    }
  ],
  "coverage": {
    "percent_covered": 95.5,
    "num_statements": 1865,
    "missing_lines": 85
  }
}
```

**Exit Code**:
- `0` = All tests passed
- `1` = Tests failed

### 4. `run_format_check.sh` - Black Format Checker

**Purpose**: Check code formatting with black

**Output**: `untracked/qa/format.json`

**Format**:
```json
{
  "tool": "black",
  "summary": {
    "total_violations": 20,
    "passed": false
  },
  "violations": [
    {
      "file": "/path/to/file.py",
      "message": "File would be reformatted by black"
    }
  ]
}
```

**Exit Code**:
- `0` = All files formatted correctly
- `1` = Formatting issues found

### 5. `run_all.sh` - Master Script

**Purpose**: Run ALL QA checks in sequence and provide summary

**Execution Order**:
1. Format Check
2. Linter
3. Type Checker
4. Tests

**Output**: All JSON files in `untracked/qa/`

**Console Output**:
```
========================================
Running ALL QA Checks
========================================

1. Running Format Check...
----------------------------------------
✅ Format check PASSED

2. Running Linter...
----------------------------------------
❌ Linter FAILED

3. Running Type Checker...
----------------------------------------
✅ Type checker PASSED

4. Running Tests with Coverage...
----------------------------------------
✅ Tests PASSED

========================================
QA Summary
========================================
  Format Check        : ✅ PASSED
  Linter              : ❌ FAILED
  Type Check          : ✅ PASSED
  Tests               : ✅ PASSED

Overall Status: ❌ SOME CHECKS FAILED
```

**Exit Code**:
- `0` = ALL checks passed
- `1` = At least one check failed

## Usage

### Run Individual Checks

```bash
# Run linter only
./scripts/qa/run_lint.sh

# Run type checker only
./scripts/qa/run_type_check.sh

# Run tests only
./scripts/qa/run_tests.sh

# Run format check only
./scripts/qa/run_format_check.sh
```

### Run All Checks

```bash
# Run everything
./scripts/qa/run_all.sh
```

### Parse JSON Output

```bash
# Read lint summary
python3 -c "
import json
with open('untracked/qa/lint.json') as f:
    data = json.load(f)
    print(f\"Violations: {data['summary']['total_violations']}\")
    print(f\"Status: {'PASSED' if data['summary']['passed'] else 'FAILED'}\")
"
```

## Integration with pyproject.toml

All QA tools are configured in `pyproject.toml`:

### Ruff Configuration

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "C4", "UP", "ARG", "SIM"]
ignore = ["E501", "B008"]
```

### Mypy Configuration

```toml
[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
```

### Black Configuration

```toml
[tool.black]
line-length = 100
target-version = ["py311", "py312", "py313"]
```

### Pytest Configuration

```toml
[tool.pytest.ini_options]
addopts = [
    "--cov=src/claude_code_hooks_daemon",
    "--cov-branch",
    "--cov-report=json:untracked/qa/coverage.json",
    "--cov-report=html",
    "--cov-report=xml",
]
```

## Testing (TDD)

All QA infrastructure is tested following TDD principles.

**Test File**: `tests/test_qa_scripts.py`

**Test Coverage**:
- Directory structure exists
- Scripts exist and are executable
- Scripts create JSON output files
- JSON output has correct structure
- Exit codes are correct
- `run_all.sh` runs all checks

**Run Tests**:
```bash
# Run QA infrastructure tests
python3 -m pytest tests/test_qa_scripts.py -v

# Run specific test class
python3 -m pytest tests/test_qa_scripts.py::TestLintScript -v
```

## Pre-Commit Integration (Future)

QA scripts can be integrated with Git pre-commit hooks:

```bash
#!/bin/bash
# .git/hooks/pre-commit

# Run QA checks before commit
./scripts/qa/run_all.sh

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ QA checks failed. Commit aborted."
    echo "Fix issues or use 'git commit --no-verify' to bypass."
    exit 1
fi

exit 0
```

## CI/CD Integration

QA scripts are designed for CI/CD pipeline integration:

```yaml
# .github/workflows/qa.yml
name: QA Checks

on: [push, pull_request]

jobs:
  qa:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: Run QA checks
        run: ./scripts/qa/run_all.sh
      - name: Upload QA results
        uses: actions/upload-artifact@v3
        with:
          name: qa-results
          path: untracked/qa/*.json
```

## Output File Locations

All QA outputs are written to `untracked/qa/` which is ignored by Git:

- `lint.json` - Ruff linter results
- `type_check.json` - Mypy type checker results
- `tests.json` - Pytest test results
- `coverage.json` - Coverage report
- `format.json` - Black format check results

**Git Ignore**: `untracked/.gitignore` ensures these files are never committed.

## Benefits

1. **Machine-Readable**: JSON output easy to parse in scripts/tools
2. **Cacheable**: Output files can be cached between runs
3. **Consistent**: All tools follow same output format structure
4. **Testable**: Full TDD coverage of QA infrastructure
5. **Integrated**: Works with existing pyproject.toml configuration
6. **Scriptable**: Easy to integrate with CI/CD and automation
7. **Summary**: run_all.sh provides comprehensive status overview

## Next Steps

1. **Pre-commit hook**: Create `.git/hooks/pre-commit` to run QA automatically
2. **CI/CD**: Integrate QA scripts into GitHub Actions workflow
3. **Dashboard**: Create HTML dashboard from JSON outputs
4. **Trending**: Track QA metrics over time (violations, coverage, etc.)
5. **Notifications**: Alert on QA regressions

## Related Documentation

- `pyproject.toml` - Tool configuration
- `tests/test_qa_scripts.py` - TDD tests
- `.pre-commit-config.yaml` - Pre-commit hooks configuration
