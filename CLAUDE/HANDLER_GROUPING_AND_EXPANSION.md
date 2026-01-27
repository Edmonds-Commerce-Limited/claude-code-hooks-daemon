# Handler Grouping and Language-Specific Expansion Plan

## Problem Statement

The current handler system has three issues:

1. **Project-specific contamination**: Some handlers (e.g., `validate_sitemap`) are specific to EC's projects, not general-purpose
2. **No language grouping**: Handlers are enabled individually, but users want to enable groups like "all Python handlers" or "all PHP handlers"
3. **Incomplete QA suppression prevention**: We block ESLint ignores, but not PHPStan, Psalm, MyPy, Ruff, or other language-specific QA suppressions

## Proposed Solution

### 1. Handler Tagging System

Add `tags` metadata to handlers for language/ecosystem grouping:

```python
class MyHandler(Handler):
    def __init__(self) -> None:
        super().__init__(
            name="my-handler",
            priority=50,
            terminal=True,
            tags=["python", "qa-enforcement", "tdd"]  # NEW: tags for grouping
        )
```

**Standard Tag Categories:**

**Languages:**
- `python`
- `php`
- `javascript`
- `typescript`
- `go`
- `rust`
- `java`
- `ruby`
- `html`
- `css`

**Frameworks/Ecosystems:**
- `react`
- `vue`
- `angular`
- `laravel`
- `symfony`
- `django`
- `flask`
- `nodejs`
- `nextjs`

**Handler Types:**
- `tdd` - Test-driven development enforcement
- `qa-enforcement` - Code quality/linting enforcement
- `qa-suppression-prevention` - Blocks lazy QA suppression comments
- `safety` - Prevents destructive operations
- `workflow` - Workflow guidance and automation
- `advisory` - Non-blocking suggestions

**Project-Specific:**
- `project-specific` - Handlers that should NOT be in core library

### 2. Configuration Schema for Tag-Based Groups

**Option A: Enable by tags**
```yaml
handlers:
  pre_tool_use:
    # Enable all handlers with these tags
    enable_tags:
      - python
      - qa-enforcement
      - tdd

    # Disable specific handlers (overrides tags)
    disable:
      - my-specific-handler

    # Individual handler config (for enabled handlers)
    tdd_enforcement:
      priority: 25
      terminal: true
```

**Option B: Tag groups + individual overrides**
```yaml
handler_groups:
  python_full:
    tags: [python, tdd, qa-enforcement, qa-suppression-prevention]

  php_full:
    tags: [php, tdd, qa-enforcement, qa-suppression-prevention]

  safety_only:
    tags: [safety]

handlers:
  pre_tool_use:
    # Enable groups
    groups: [python_full, safety_only]

    # Override specific handlers
    disable:
      - british_english  # Maybe you like American English

    # Handler-specific config
    destructive_git:
      priority: 10
```

**Option C: Hybrid (recommended)**
```yaml
handlers:
  pre_tool_use:
    # Quick enable by tags (most common use case)
    enable_tags: [python, php, javascript, safety]

    # Fine-grained control
    enable:
      - custom-handler-1

    disable:
      - british-english

    # Handler config
    destructive_git:
      enabled: true  # Explicit enable (overrides tags)
      priority: 10
```

### 3. QA Suppression Prevention Handlers

Create handlers to block lazy QA suppression across languages:

#### Python: `python_qa_suppression_blocker.py`
**Tags:** `[python, qa-suppression-prevention]`

Blocks:
- `# type: ignore` (MyPy)
- `# noqa` (Ruff, Flake8)
- `# pylint: disable`
- `# pyright: ignore`
- `@pytest.mark.skip` without reason

**Exceptions:**
- Allow with detailed justification: `# type: ignore[import]  # Justification: third-party types unavailable`
- Allow in test fixtures: `tests/fixtures/`
- Allow in migrations: `migrations/`

#### PHP: `php_qa_suppression_blocker.py`
**Tags:** `[php, qa-suppression-prevention]`

Blocks:
- `@phpstan-ignore-next-line`
- `@psalm-suppress`
- `@codingStandardsIgnoreLine`
- `// phpcs:ignore`

**Exceptions:**
- Allow with detailed justification
- Allow in legacy directories (configurable)
- Allow in vendor/

#### TypeScript/JavaScript: `typescript_qa_suppression_blocker.py`
**Tags:** `[typescript, javascript, qa-suppression-prevention]`

Blocks:
- `// eslint-disable` (already exists as `eslint_disable.py`)
- `// @ts-ignore`
- `// @ts-expect-error` without reason
- `// tslint:disable`

**Exceptions:**
- Allow with detailed justification
- Allow in .d.ts files
- Allow in node_modules/

#### Go: `go_qa_suppression_blocker.py`
**Tags:** `[go, qa-suppression-prevention]`

Blocks:
- `//nolint`
- `//go:generate` with dangerous commands

**Exceptions:**
- Allow with detailed justification
- Allow in generated code files

#### Other Languages
- **Rust:** Block `#[allow(clippy::...)]` without justification
- **Java:** Block `@SuppressWarnings` without reason
- **Ruby:** Block `# rubocop:disable` without reason

### 4. Language-Specific Handler Categories

For each language, implement three handler types:

#### TDD Enforcement
**Existing:**
- Python: `tdd_enforcement.py` (tags: `[python, tdd]`)

**To Create:**
- `php_tdd_enforcement.py` (tags: `[php, tdd]`)
  - Ensure test files exist for new classes
  - Prevent changing code without running PHPUnit

- `typescript_tdd_enforcement.py` (tags: `[typescript, javascript, tdd]`)
  - Ensure test files exist for new components
  - Prevent changing code without running Jest/Vitest

- `go_tdd_enforcement.py` (tags: `[go, tdd]`)
  - Ensure test files exist for new packages
  - Prevent changing code without running `go test`

#### QA Enforcement
**To Create:**
- `python_qa_enforcement.py` (tags: `[python, qa-enforcement]`)
  - Ensure MyPy passes before commits
  - Ensure Ruff passes before commits
  - Ensure test coverage threshold met

- `php_qa_enforcement.py` (tags: `[php, qa-enforcement]`)
  - Ensure PHPStan passes before commits
  - Ensure PHP-CS-Fixer passes before commits
  - Ensure Psalm passes before commits

- `typescript_qa_enforcement.py` (tags: `[typescript, javascript, qa-enforcement]`)
  - Ensure TypeScript compiler passes before commits
  - Ensure ESLint passes before commits
  - Ensure Prettier passes before commits

#### Coding Standards
**To Create:**
- `python_standards.py` (tags: `[python, advisory]`)
  - Suggest type hints for function parameters
  - Suggest docstrings for public functions
  - Warn about bare `except:` clauses

- `php_standards.py` (tags: `[php, advisory]`)
  - Suggest type hints for function parameters
  - Suggest PHPDoc blocks for public methods
  - Warn about deprecated PHP features

- `typescript_standards.py` (tags: `[typescript, javascript, advisory]`)
  - Suggest explicit return types
  - Warn about `any` types
  - Suggest JSDoc for public APIs

### 5. Project-Specific Handler Separation

**Handlers to Mark as Project-Specific:**

1. **`validate_sitemap.py`** (tags: `[project-specific]`)
   - Specific to EC's sitemap validation system
   - References `CLAUDE/Sitemap/` directory structure
   - References `sitemap-validator` agent (EC-specific)

   **Action:** Add deprecation warning, suggest moving to plugin system

**Audit Needed:**
- Review all handlers for EC-specific assumptions
- Check for hardcoded paths to EC project structures
- Check for references to EC-specific tooling

### 6. Implementation Plan

#### Phase 1: Core Tagging System (v2.2.0)
1. Add `tags: list[str]` to Handler base class
2. Update all existing handlers with appropriate tags
3. Add tag-based filtering to FrontController
4. Update configuration loader to support `enable_tags`
5. Add tests for tag-based handler selection
6. Document tagging system in HANDLER_DEVELOPMENT.md

#### Phase 2: QA Suppression Prevention (v2.3.0)
1. Create `python_qa_suppression_blocker.py`
2. Create `php_qa_suppression_blocker.py`
3. Extend existing `eslint_disable.py` → `typescript_qa_suppression_blocker.py`
4. Create `go_qa_suppression_blocker.py`
5. Add comprehensive tests for each handler
6. Update default config with QA suppression handlers

#### Phase 3: Language-Specific TDD (v2.4.0)
1. Create `php_tdd_enforcement.py`
2. Create `typescript_tdd_enforcement.py`
3. Create `go_tdd_enforcement.py`
4. Add tests for each handler
5. Update default config

#### Phase 4: QA Enforcement Handlers (v2.5.0)
1. Create `python_qa_enforcement.py`
2. Create `php_qa_enforcement.py`
3. Create `typescript_qa_enforcement.py`
4. Add tests for each handler

#### Phase 5: Coding Standards Handlers (v2.6.0)
1. Create advisory handlers for Python, PHP, TypeScript
2. Make them non-terminal (suggestions only)
3. Add configuration for severity levels

#### Phase 6: Project-Specific Cleanup (v3.0.0 - Breaking)
1. Mark project-specific handlers with deprecation warnings
2. Move project-specific handlers to separate package
3. Document migration path for users with project-specific handlers
4. Release as major version (breaking change)

### 7. Configuration Examples

#### Python Developer Config
```yaml
handlers:
  pre_tool_use:
    enable_tags:
      - python
      - tdd
      - qa-enforcement
      - qa-suppression-prevention
      - safety

    # Fine-tune
    python_qa_suppression_blocker:
      allow_in_paths:
        - tests/fixtures/
        - scripts/legacy/
```

#### Full-Stack Developer Config
```yaml
handlers:
  pre_tool_use:
    enable_tags:
      - python
      - php
      - typescript
      - javascript
      - react
      - tdd
      - qa-enforcement
      - qa-suppression-prevention
      - safety
```

#### Minimal Safety-Only Config
```yaml
handlers:
  pre_tool_use:
    enable_tags:
      - safety

    # Everything else disabled by default
```

## Benefits

1. **Easier onboarding**: New users can enable "python" instead of listing 10 handlers
2. **Language-specific workflows**: Enable all Python tools with one tag
3. **Consistent QA enforcement**: Block lazy QA suppression across all languages
4. **Cleaner separation**: Project-specific handlers clearly marked
5. **Flexible configuration**: Tag-based groups + fine-grained overrides
6. **Extensible**: Easy to add new languages and handler categories

## Migration Path

**v2.1.0 → v2.2.0 (Tagging System):**
- No breaking changes
- Old config still works (enable handlers individually)
- New `enable_tags` feature is optional
- All handlers get default tags

**v2.2.0 → v3.0.0 (Project-Specific Cleanup):**
- Breaking: Remove project-specific handlers from core
- Migration guide: Move to plugin system
- Deprecated handlers show warnings in v2.x

## Open Questions

1. **Tag naming convention?** Lowercase with hyphens? (e.g., `qa-enforcement` vs `qa_enforcement`)
2. **Multiple tags per handler?** Yes - handlers can have multiple tags (e.g., `[python, tdd, qa-enforcement]`)
3. **Tag inheritance?** Should `typescript` automatically include `javascript` tags?
4. **Dynamic tag registration?** Allow plugins to define custom tags?
5. **Tag documentation?** Auto-generate list of all tags and handlers per tag?

## Next Steps

1. **Create GitHub issue** to track this work
2. **Get feedback** on tagging approach and configuration schema
3. **Start with Phase 1** (Core Tagging System) in v2.2.0
4. **Implement QA suppression handlers** as high priority (Phase 2)
