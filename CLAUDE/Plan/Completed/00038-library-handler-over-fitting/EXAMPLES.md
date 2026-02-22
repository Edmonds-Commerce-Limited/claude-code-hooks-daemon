# Configuration Examples for Different Project Types

This document provides concrete examples of how the refactored handlers will work with different project structures and languages.

## Example 1: Python Project (Default - This Project)

**Project Structure:**
```
my-python-project/
├── src/
│   └── myproject/
│       └── auth.py
├── tests/
│   └── unit/
│       └── test_auth.py
├── docs/
└── .claude/
    └── hooks-daemon.yaml
```

**Configuration:**
```yaml
version: 1.0

# Project path mappings (these are also the defaults)
project_paths:
  plan_directory: "CLAUDE/Plan"
  test_directory: "tests"
  source_directory: "src"
  docs_directory: "docs"

handlers:
  pre_tool_use:
    tdd_enforcement:
      enabled: true
      # Uses Python defaults from LanguageConfig
      # test_file_patterns: ["test_{filename}", "{basename}_test.py"]
```

**Behavior:**
- Creating `src/myproject/auth.py` requires `tests/unit/test_auth.py` or `tests/unit/auth_test.py`
- Supports both pytest conventions (prefix and suffix)

## Example 2: Go Project

**Project Structure:**
```
my-go-project/
├── cmd/
│   └── server/
│       └── main.go
├── pkg/
│   ├── auth/
│   │   ├── auth.go
│   │   └── auth_test.go
├── docs/
└── .claude/
    └── hooks-daemon.yaml
```

**Configuration:**
```yaml
version: 1.0

project_paths:
  source_directory: "pkg"  # Go uses pkg/ not src/
  test_directory: "."      # Go colocates tests with source
  docs_directory: "docs"

handlers:
  pre_tool_use:
    tdd_enforcement:
      enabled: true
      # Uses Go defaults from LanguageConfig
      # test_file_patterns: ["{basename}_test.go"]
```

**Behavior:**
- Creating `pkg/auth/auth.go` requires `pkg/auth/auth_test.go` (colocated)
- Follows Go convention of `*_test.go` suffix

## Example 3: TypeScript/React Project

**Project Structure:**
```
my-react-app/
├── src/
│   ├── components/
│   │   ├── Button.tsx
│   │   └── Button.test.tsx
│   └── utils/
│       ├── format.ts
│       └── format.spec.ts
├── __tests__/
│   └── integration/
├── docs/
└── .claude/
    └── hooks-daemon.yaml
```

**Configuration:**
```yaml
version: 1.0

project_paths:
  source_directory: "src"
  test_directory: "__tests__"  # Jest convention
  docs_directory: "docs"

handlers:
  pre_tool_use:
    tdd_enforcement:
      enabled: true
      # TypeScript supports both .test and .spec
      # test_file_patterns: ["{basename}.test.ts", "{basename}.spec.ts"]

    eslint_disable:
      enabled: true
      extensions: [".ts", ".tsx", ".js", ".jsx"]
      skip_directories: ["node_modules", "dist", "build", "coverage"]
```

**Behavior:**
- Creating `src/components/Button.tsx` requires either:
  - `src/components/Button.test.tsx` (colocated), OR
  - `src/components/Button.spec.tsx` (colocated), OR
  - `__tests__/components/Button.test.tsx`, OR
  - `__tests__/components/Button.spec.tsx`

## Example 4: PHP Project

**Project Structure:**
```
my-php-project/
├── src/
│   └── Auth/
│       └── AuthService.php
├── tests/
│   └── Unit/
│       └── Auth/
│           └── AuthServiceTest.php
├── docs/
└── .claude/
    └── hooks-daemon.yaml
```

**Configuration:**
```yaml
version: 1.0

project_paths:
  source_directory: "src"
  test_directory: "tests"
  docs_directory: "docs"

handlers:
  pre_tool_use:
    tdd_enforcement:
      enabled: true
      # PHP uses PHPUnit convention
      # test_file_patterns: ["{basename}Test.php"]

    php_qa_suppression:
      enabled: true
      skip_directories: ["vendor", "cache"]
```

**Behavior:**
- Creating `src/Auth/AuthService.php` requires `tests/Unit/Auth/AuthServiceTest.php`
- Follows PHPUnit convention of `*Test.php` suffix

## Example 5: Ruby Project

**Project Structure:**
```
my-ruby-project/
├── lib/
│   └── auth.rb
├── spec/
│   └── auth_spec.rb
├── docs/
└── .claude/
    └── hooks-daemon.yaml
```

**Configuration:**
```yaml
version: 1.0

project_paths:
  source_directory: "lib"  # Ruby uses lib/ not src/
  test_directory: "spec"   # RSpec convention
  docs_directory: "docs"

handlers:
  pre_tool_use:
    tdd_enforcement:
      enabled: true
      # Override for Ruby (not in default configs yet)
      test_file_patterns: ["{basename}_spec.rb"]
      language_extensions: [".rb"]
```

**Behavior:**
- Creating `lib/auth.rb` requires `spec/auth_spec.rb`
- Follows RSpec convention of `*_spec.rb` suffix

## Example 6: Non-Standard Project Structure

**Project Structure:**
```
my-custom-project/
├── app/              # Custom source directory
├── testing/          # Custom test directory
├── planning/         # Custom planning directory
│   └── active/
│   └── completed/
├── documentation/    # Custom docs directory
└── .claude/
    └── hooks-daemon.yaml
```

**Configuration:**
```yaml
version: 1.0

project_paths:
  source_directory: "app"
  test_directory: "testing"
  plan_directory: "planning/active"
  docs_directory: "documentation"

handlers:
  pre_tool_use:
    tdd_enforcement:
      enabled: true
      # Handler adapts to custom paths

    markdown_organization:
      enabled: true
      allowed_directories:
        - "planning/active"
        - "planning/completed"
        - "documentation"
        - ".claude/commands"

    validate_plan_number:
      enabled: true
      # Uses planning/active instead of CLAUDE/Plan
```

**Behavior:**
- All handlers adapt to custom directory structure
- No hardcoded paths - everything from config

## Example 7: Monorepo with Multiple Languages

**Project Structure:**
```
my-monorepo/
├── services/
│   ├── api-go/
│   │   ├── cmd/
│   │   └── pkg/
│   └── web-typescript/
│       └── src/
├── libs/
│   └── shared-python/
│       └── src/
├── docs/
└── .claude/
    └── hooks-daemon.yaml
```

**Configuration:**
```yaml
version: 1.0

project_paths:
  # Root-level defaults
  docs_directory: "docs"
  # source_directory and test_directory handled per-service

handlers:
  pre_tool_use:
    tdd_enforcement:
      enabled: true
      # Automatically detects language by file extension
      # Applies appropriate test convention

    # Language-specific QA blockers work per-language
    python_qa_suppression:
      enabled: true
      skip_directories: ["libs/shared-python/.venv"]

    go_qa_suppression:
      enabled: true
      skip_directories: ["services/api-go/vendor"]

    eslint_disable:
      enabled: true
      skip_directories: ["services/web-typescript/node_modules"]
```

**Behavior:**
- TDD handler detects language by extension and applies correct test pattern
- Creating `services/api-go/pkg/auth/auth.go` → requires `auth_test.go` (Go convention)
- Creating `libs/shared-python/src/utils.py` → requires `test_utils.py` (Python convention)
- Creating `services/web-typescript/src/Button.tsx` → requires `Button.test.tsx` (TS convention)

## Example 8: Legacy Project (Graceful Degradation)

**Project Structure:**
```
legacy-project/
├── src/
│   └── old_code.py
└── .claude/
    └── hooks-daemon.yaml
```

**Configuration:**
```yaml
version: 1.0

# Minimal config - uses smart defaults
handlers:
  pre_tool_use:
    tdd_enforcement:
      enabled: true
      # No test_directory configured - handler checks if tests/ exists
      # If not, handler doesn't enforce (graceful degradation)
```

**Behavior:**
- Handler checks if `tests/` directory exists
- If not present, handler logs info and doesn't enforce
- No errors, no blocking - graceful degradation
- User can create `tests/` directory to enable enforcement

## Migration Path for Existing Projects

### Before (Hardcoded):
```python
# tdd_enforcement.py - OLD
def _get_test_file_path(self, handler_path: str) -> Path:
    # Hardcoded: only works for Python in this exact structure
    if "claude_code_hooks_daemon" in path_parts and "handlers" in path_parts:
        workspace_root = Path("/workspace")  # HARDCODED
        return workspace_root / "tests" / "unit" / "handlers" / event_type / test_filename
```

### After (Configurable):
```python
# tdd_enforcement.py - NEW
def _get_test_file_path(self, handler_path: str) -> Path:
    # Get language config based on file extension
    lang_config = get_language_config(handler_path)
    if not lang_config:
        return None

    # Get test directory from project config (or default)
    test_dir = ProjectPaths.get_test_directory(lang_config.test_directory)

    # Apply language-specific test file pattern
    for pattern in lang_config.test_file_patterns:
        # Try each pattern (test_{filename}, {basename}_test.go, etc.)
        test_path = self._apply_pattern(handler_path, pattern, test_dir)
        if test_path.exists():
            return test_path

    # Return first pattern as expected path
    return self._apply_pattern(handler_path, lang_config.test_file_patterns[0], test_dir)
```

## Configuration Schema Reference

```yaml
version: 1.0

# Project-level path mappings (optional - smart defaults used if missing)
project_paths:
  plan_directory: string       # Default: "CLAUDE/Plan" or "docs/plans"
  test_directory: string       # Default: "tests" (Python/PHP) or "." (Go)
  source_directory: string     # Default: "src" (Python/PHP/TS) or "pkg" (Go) or "lib" (Ruby)
  docs_directory: string       # Default: "docs"

handlers:
  pre_tool_use:
    tdd_enforcement:
      enabled: boolean
      # Optional overrides (handler uses LanguageConfig defaults)
      test_directory: string           # Override test directory
      test_file_patterns: [string]     # Override test file patterns
      language_extensions: [string]    # Override file extensions to check

    markdown_organization:
      enabled: boolean
      # Optional overrides
      allowed_directories: [string]    # Additional allowed directories

    validate_plan_number:
      enabled: boolean
      # Uses project_paths.plan_directory

    python_qa_suppression:
      enabled: boolean
      skip_directories: [string]       # Project-specific skip dirs

    go_qa_suppression:
      enabled: boolean
      skip_directories: [string]

    php_qa_suppression:
      enabled: boolean
      skip_directories: [string]

    eslint_disable:
      enabled: boolean
      extensions: [string]             # File extensions to check
      skip_directories: [string]
```

## Testing the Configuration

After updating configuration, verify handlers work correctly:

```bash
# 1. Restart daemon with new config
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart

# 2. Check daemon status
$PYTHON -m claude_code_hooks_daemon.daemon.cli status

# 3. Test TDD enforcement (try creating a source file without test)
# Should block with helpful message showing expected test file path

# 4. Check logs for any configuration warnings
$PYTHON -m claude_code_hooks_daemon.daemon.cli logs | grep -i config
```
