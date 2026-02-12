# LLM Command Wrappers - Implementation Guide

## Philosophy

Traditional QA tools (ESLint, pytest, PHPStan, go vet, RuboCop) produce verbose,
human-readable stdout: coloured output, progress bars, decorative formatting,
hundreds of lines for large codebases. This wastes LLM context tokens and is
difficult to parse programmatically.

**LLM command wrappers** solve this by providing a parallel set of commands that:

- **Minimal stdout**: 3-5 lines with pass/fail status, summary counts, and a
  pointer to the detail file
- **Structured JSON file**: Full machine-readable results written to a known path
- **JQ-optimizable**: JSON structure designed for common jq queries
- **Human commands untouched**: The original commands stay exactly as they are;
  LLM wrappers are added alongside them

The principle is separation of concerns: humans read coloured terminal output,
LLMs read structured JSON. Both workflows coexist.

## The Pattern

### Naming Convention

Use an `llm:` or `llm-` prefix depending on the ecosystem's script runner:

| Ecosystem | Runner | Convention | Examples |
|-----------|--------|------------|----------|
| Node.js | npm scripts | `llm:` prefix | `llm:lint`, `llm:test`, `llm:typecheck` |
| Python | Makefile | `llm-` prefix | `llm-lint`, `llm-test`, `llm-typecheck` |
| PHP | Composer scripts | `llm:` prefix | `llm:analyse`, `llm:test` |
| Go | Makefile | `llm-` prefix | `llm-lint`, `llm-test`, `llm-vet` |
| Ruby | Rake tasks | `llm:` namespace | `llm:lint`, `llm:test` |

The prefix makes LLM commands instantly discoverable and distinguishable from
human commands.

### Stdout Contract (3-5 lines max)

Every LLM command prints a short summary to stdout:

```
Line 1: Status emoji + summary (pass/fail + counts)
Line 2: Path to the detail JSON file
Line 3: Example jq command for the most common query
Line 4: (optional) Additional jq example or schema hint
```

**Example output (passing)**:
```
OK 45 files checked, 0 errors, 3 warnings
Details: ./var/qa/eslint-cache.json
Query: jq '.[] | select(.warningCount > 0) | .filePath' ./var/qa/eslint-cache.json
```

**Example output (failing)**:
```
FAIL 45 files checked, 12 errors, 3 warnings
Details: ./var/qa/eslint-cache.json
Query: jq '.[] | select(.errorCount > 0) | {file: .filePath, errors: .messages}' ./var/qa/eslint-cache.json
```

### JSON Output Contract

- **Output directory**: `./var/qa/`
- **File naming**: `{tool}-cache.json` (e.g., `eslint-cache.json`, `pytest-cache.json`)
- **Format**: Valid JSON (no trailing commas, no comments, no ANSI codes)
- **Structure**: Array of result objects where possible, or tool-native JSON format
- **Optimized for jq**: Flat structures preferred; arrays for iteration

The `var/` directory is gitignored (ephemeral build artifacts). The `qa/`
subdirectory keeps QA output separate from other var data. The `-cache` suffix
indicates regeneratable data.

### Exit Codes

- **Exit 0**: All checks passed (warnings are acceptable)
- **Exit 1**: Errors found (failures that must be fixed)
- **Exit 2**: Tool error (could not run, config missing, etc.)

## Language-Specific Examples

### JavaScript / TypeScript (npm scripts in package.json)

#### ESLint

ESLint has native JSON output via `--format json`:

```json
{
  "scripts": {
    "lint": "eslint .",
    "llm:lint": "mkdir -p var/qa && eslint . --format json --output-file ./var/qa/eslint-cache.json; node -e \"const r=require('./var/qa/eslint-cache.json'),e=r.reduce((a,f)=>a+f.errorCount,0),w=r.reduce((a,f)=>a+f.warningCount,0);console.log(e?'FAIL':'OK',r.length,'files,',e,'errors,',w,'warnings');console.log('Details: ./var/qa/eslint-cache.json');console.log('Query: jq \\'.[] | select(.errorCount > 0) | {file: .filePath, errors: .messages}\\' ./var/qa/eslint-cache.json');process.exit(e?1:0)\""
  }
}
```

**Common jq queries for ESLint JSON**:
```bash
# Files with errors
jq '.[] | select(.errorCount > 0) | .filePath' ./var/qa/eslint-cache.json

# All error messages with locations
jq '.[] | .messages[] | select(.severity == 2) | {file: .filePath, line: .line, msg: .message}' ./var/qa/eslint-cache.json

# Count errors by rule
jq '[.[] | .messages[] | select(.severity == 2) | .ruleId] | group_by(.) | map({rule: .[0], count: length}) | sort_by(-.count)' ./var/qa/eslint-cache.json
```

#### Jest / Vitest

Jest has native JSON output via `--json`:

```json
{
  "scripts": {
    "test": "jest",
    "llm:test": "mkdir -p var/qa && jest --json --outputFile=./var/qa/jest-results.json 2>/dev/null; node -e \"const r=require('./var/qa/jest-results.json');console.log(r.success?'OK':'FAIL',r.numTotalTests,'tests,',r.numFailedTests,'failed,',r.numPassedTests,'passed');console.log('Details: ./var/qa/jest-results.json');console.log('Query: jq \\'.testResults[] | select(.status != \\\"passed\\\") | .name\\' ./var/qa/jest-results.json');process.exit(r.success?0:1)\""
  }
}
```

**Common jq queries for Jest JSON**:
```bash
# Failed test files
jq '.testResults[] | select(.status != "passed") | .name' ./var/qa/jest-results.json

# Failed test names with messages
jq '.testResults[] | .assertionResults[] | select(.status == "failed") | {test: .fullName, msg: .failureMessages[0]}' ./var/qa/jest-results.json
```

#### TypeScript Compiler (tsc)

TypeScript does not have native JSON output. Use a wrapper script:

```json
{
  "scripts": {
    "type-check": "tsc --noEmit",
    "llm:type-check": "mkdir -p var/qa && tsc --noEmit --pretty false 2>&1 | node -e \"const lines=require('fs').readFileSync('/dev/stdin','utf8').trim().split('\\n').filter(Boolean);const errs=lines.filter(l=>/\\(\\d+,\\d+\\):/.test(l));require('fs').writeFileSync('./var/qa/tsc-cache.json',JSON.stringify(errs.map(l=>{const m=l.match(/^(.+)\\((\\d+),(\\d+)\\): error (TS\\d+): (.+)/);return m?{file:m[1],line:+m[2],col:+m[3],code:m[4],message:m[5]}:{raw:l}})));console.log(errs.length?'FAIL':'OK',errs.length,'type errors');console.log('Details: ./var/qa/tsc-cache.json');console.log('Query: jq \\'.[] | {file,line,message}\\' ./var/qa/tsc-cache.json');process.exit(errs.length?1:0)\""
  }
}
```

### Python (Makefile or pyproject.toml scripts)

#### pytest

pytest has JSON output via the `pytest-json-report` plugin:

```makefile
test:
	pytest

llm-test:
	@mkdir -p var/qa
	@pytest --json-report --json-report-file=./var/qa/pytest-cache.json -q 2>/dev/null; \
	python3 -c "import json,sys; \
	r=json.load(open('./var/qa/pytest-cache.json')); \
	t=r['summary']; \
	ok=t.get('failed',0)==0; \
	print('OK' if ok else 'FAIL', t.get('total',0), 'tests,', t.get('failed',0), 'failed,', t.get('passed',0), 'passed'); \
	print('Details: ./var/qa/pytest-cache.json'); \
	print('Query: jq \'.tests[] | select(.outcome == \"failed\") | {name: .nodeid, msg: .call.crash.message}\' ./var/qa/pytest-cache.json'); \
	sys.exit(0 if ok else 1)"
```

#### Ruff

Ruff has native JSON output via `--output-format json`:

```makefile
lint:
	ruff check .

llm-lint:
	@mkdir -p var/qa
	@ruff check . --output-format json > ./var/qa/ruff-cache.json 2>/dev/null || true
	@python3 -c "import json,sys; \
	r=json.load(open('./var/qa/ruff-cache.json')); \
	print('OK' if not r else 'FAIL', len(r), 'issues found'); \
	print('Details: ./var/qa/ruff-cache.json'); \
	print('Query: jq \'.[] | {file: .filename, line: .location.row, code: .code, msg: .message}\' ./var/qa/ruff-cache.json'); \
	sys.exit(1 if r else 0)"
```

#### mypy

mypy has JSON output via `--output json` (mypy 1.5+):

```makefile
llm-typecheck:
	@mkdir -p var/qa
	@mypy src/ --output json > ./var/qa/mypy-cache.json 2>/dev/null || true
	@python3 -c "import json,sys; \
	lines=open('./var/qa/mypy-cache.json').read().strip().split('\n'); \
	results=[json.loads(l) for l in lines if l.strip()]; \
	errs=[r for r in results if r.get('severity')=='error']; \
	print('OK' if not errs else 'FAIL', len(errs), 'type errors'); \
	print('Details: ./var/qa/mypy-cache.json'); \
	print('Query: jq -s \'.[] | select(.severity == \"error\") | {file, line, message}\' ./var/qa/mypy-cache.json'); \
	sys.exit(1 if errs else 0)"
```

### PHP (Composer scripts)

#### PHPStan

PHPStan has native JSON output via `--error-format=json`:

```json
{
  "scripts": {
    "analyse": "phpstan analyse",
    "llm:analyse": "mkdir -p var/qa && phpstan analyse --error-format=json > ./var/qa/phpstan-cache.json 2>/dev/null; php -r \"$r=json_decode(file_get_contents('./var/qa/phpstan-cache.json'),true); $e=$r['totals']['errors']??0; $fe=$r['totals']['file_errors']??0; echo ($fe?'FAIL':'OK').' '.$fe.' errors in '.(count($r['files']??[])).' files'.PHP_EOL; echo 'Details: ./var/qa/phpstan-cache.json'.PHP_EOL; echo 'Query: jq \\'.files | to_entries[] | select(.value.errors > 0) | {file: .key, messages: .value.messages[].message}\\' ./var/qa/phpstan-cache.json'.PHP_EOL; exit($fe?1:0);\""
  }
}
```

#### PHPUnit

PHPUnit supports XML log output via `--log-junit`:

```json
{
  "scripts": {
    "test": "phpunit",
    "llm:test": "mkdir -p var/qa && phpunit --log-junit ./var/qa/phpunit-cache.xml 2>/dev/null; php -r \"$x=simplexml_load_file('./var/qa/phpunit-cache.xml'); $t=(int)$x['tests']; $f=(int)$x['failures']; $e=(int)$x['errors']; echo ($f+$e?'FAIL':'OK').' '.$t.' tests, '.$f.' failures, '.$e.' errors'.PHP_EOL; echo 'Details: ./var/qa/phpunit-cache.xml'.PHP_EOL; exit($f+$e?1:0);\""
  }
}
```

### Go

#### golangci-lint

golangci-lint has native JSON output via `--out-format json`:

```makefile
lint:
	golangci-lint run

llm-lint:
	@mkdir -p var/qa
	@golangci-lint run --out-format json > ./var/qa/golangci-cache.json 2>/dev/null || true
	@python3 -c "import json,sys; \
	r=json.load(open('./var/qa/golangci-cache.json')); \
	issues=r.get('Issues') or []; \
	print('OK' if not issues else 'FAIL', len(issues), 'issues found'); \
	print('Details: ./var/qa/golangci-cache.json'); \
	print('Query: jq \'.Issues[] | {file: .Pos.Filename, line: .Pos.Line, msg: .Text, linter: .FromLinter}\' ./var/qa/golangci-cache.json'); \
	sys.exit(1 if issues else 0)"
```

#### go test

go test has native JSON output via `-json` flag:

```makefile
llm-test:
	@mkdir -p var/qa
	@go test ./... -json > ./var/qa/gotest-cache.json 2>/dev/null || true
	@python3 -c "import json,sys; \
	lines=open('./var/qa/gotest-cache.json').read().strip().split('\n'); \
	events=[json.loads(l) for l in lines if l.strip()]; \
	fails=[e for e in events if e.get('Action')=='fail' and e.get('Test')]; \
	total=[e for e in events if e.get('Action')=='pass' and e.get('Test')]; \
	print('OK' if not fails else 'FAIL', len(total)+len(fails), 'tests,', len(fails), 'failed'); \
	print('Details: ./var/qa/gotest-cache.json'); \
	print('Query: jq -s \\'[.[] | select(.Action==\"fail\" and .Test)] | .[] | {pkg: .Package, test: .Test}\\' ./var/qa/gotest-cache.json'); \
	sys.exit(1 if fails else 0)"
```

### Ruby

#### RuboCop

RuboCop has native JSON output via `--format json`:

```ruby
# Rakefile
task :lint do
  sh "rubocop"
end

namespace :llm do
  task :lint do
    sh "mkdir -p var/qa"
    sh "rubocop --format json --out ./var/qa/rubocop-cache.json || true"
    ruby <<~RUBY
      require 'json'
      r = JSON.parse(File.read('./var/qa/rubocop-cache.json'))
      s = r['summary']
      ok = s['offense_count'].zero?
      puts "\#{ok ? 'OK' : 'FAIL'} \#{s['target_file_count']} files, \#{s['offense_count']} offenses"
      puts "Details: ./var/qa/rubocop-cache.json"
      puts "Query: jq '.files[] | select(.offenses | length > 0) | {file: .path, offenses: [.offenses[].message]}' ./var/qa/rubocop-cache.json"
      exit(ok ? 0 : 1)
    RUBY
  end
end
```

## Common jq Patterns

These patterns work across most tool JSON outputs:

```bash
# Filter to errors/failures only
jq '.[] | select(.severity == "error")' ./var/qa/{tool}-cache.json
jq '.[] | select(.status == "failed")' ./var/qa/{tool}-cache.json

# Count issues by file
jq 'group_by(.file) | map({file: .[0].file, count: length}) | sort_by(-.count)' ./var/qa/{tool}-cache.json

# Extract just messages
jq '.[].message' ./var/qa/{tool}-cache.json

# Get file + line + message (most common query)
jq '.[] | {file, line, message}' ./var/qa/{tool}-cache.json

# Count total issues
jq 'length' ./var/qa/{tool}-cache.json

# Get unique rule/code violations
jq '[.[].code // .[].ruleId] | unique' ./var/qa/{tool}-cache.json

# First N issues only (for context-limited reads)
jq '.[0:5]' ./var/qa/{tool}-cache.json
```

## Directory Convention

```
project-root/
  var/                    # Gitignored ephemeral data
    qa/                   # QA tool output
      eslint-cache.json   # ESLint results
      jest-results.json   # Jest test results
      tsc-cache.json      # TypeScript compiler errors
      pytest-cache.json   # pytest results
      ruff-cache.json     # Ruff linter results
      mypy-cache.json     # mypy type check results
      phpstan-cache.json  # PHPStan analysis results
      golangci-cache.json # golangci-lint results
      rubocop-cache.json  # RuboCop results
```

Add to `.gitignore`:
```
var/
```

## Quick-Start Checklist

To add LLM command wrappers to your project:

1. Create the output directory: `mkdir -p var/qa`
2. Add `var/` to `.gitignore`
3. For each QA tool, check if it supports `--format json` or equivalent
4. Create the wrapper command with the naming convention for your ecosystem
5. Ensure stdout follows the 3-line contract (status, path, jq query)
6. Ensure JSON output goes to `./var/qa/{tool}-cache.json`
7. Test: run the wrapper, verify stdout is 3-5 lines, verify JSON is valid

## Tool JSON Support Reference

| Tool | Native JSON | Flag | Notes |
|------|-------------|------|-------|
| ESLint | Yes | `--format json` | Array of file results |
| Jest | Yes | `--json` | Single result object |
| Vitest | Yes | `--reporter json` | Jest-compatible format |
| tsc | No | N/A | Requires text parsing wrapper |
| Ruff | Yes | `--output-format json` | Array of violations |
| mypy | Yes | `--output json` | NDJSON (one object per line, mypy 1.5+) |
| pytest | Plugin | `pytest-json-report` | Requires plugin install |
| PHPStan | Yes | `--error-format=json` | Object with files and totals |
| PHPUnit | Partial | `--log-junit` (XML) | No native JSON; XML available |
| golangci-lint | Yes | `--out-format json` | Object with Issues array |
| go test | Yes | `-json` | NDJSON (one event per line) |
| RuboCop | Yes | `--format json` | Object with files array |
| Bandit | Yes | `--format json` | Object with results array |
| Black | No | `--check --diff` | Requires text parsing wrapper |
