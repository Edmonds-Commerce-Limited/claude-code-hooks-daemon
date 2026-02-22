# Plan 00038: Library Handler Over-fitting - Quick Reference

**Status**: Not Started | **Priority**: High

## Problem Statement

Multiple handlers contain project-specific assumptions (hardcoded paths, Python-only logic) that make them unusable as library handlers. This violates the core design principle that handlers should be GENERIC and configurable.

## Key Issues

- **TddEnforcementHandler**: Python-only, hardcoded `test_*.py` pattern, cannot enforce TDD for Go/PHP/TypeScript/etc.
- **Plan Handlers (5)**: Hardcoded `CLAUDE/Plan/` path structure
- **MarkdownOrganizationHandler**: Hardcoded `CLAUDE/`, `docs/`, `eslint-rules/` directories
- **QA Suppression Blockers (3)**: Hardcoded skip directories
- **EslintDisableHandler**: Hardcoded extensions and skip directories

**Total**: 11 handlers affected (6 critical, 4 moderate, 1 low)

## Solution Approach

1. **Configuration-Driven Paths**: Add `project_paths` section to YAML config
2. **Multi-Language Support**: Extend `LanguageConfig` with test file patterns
3. **Smart Defaults**: Graceful degradation when paths don't exist
4. **Backward Compatible**: This project continues working identically

## Document Overview

| Document | Purpose | Lines |
|----------|---------|-------|
| **PLAN.md** | Complete plan with tasks, decisions, phases | 453 |
| **INVESTIGATION.md** | Detailed analysis of all affected handlers | 441 |
| **EXAMPLES.md** | Configuration examples for different project types | 440 |
| **IMPLEMENTATION.md** | Detailed code changes and migration guide | 693 |

**Total Documentation**: 2,027 lines

## Quick Start

### For Reviewers
1. Read **PLAN.md** (overview, goals, tasks)
2. Skim **INVESTIGATION.md** (understand scope)
3. Review **Technical Decisions** section in PLAN.md

### For Implementers
1. Start with **IMPLEMENTATION.md** (detailed code changes)
2. Reference **EXAMPLES.md** (see how it works)
3. Follow **Tasks** section in PLAN.md

### For Users (After Implementation)
1. Read **EXAMPLES.md** (find your project type)
2. Update `.claude/hooks-daemon.yaml` with your paths
3. Test with: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`

## Success Criteria

- [ ] All handlers use configuration (no hardcoded paths)
- [ ] TDD enforcement supports Python, Go, PHP, TypeScript, Rust, Java
- [ ] This project continues working identically (dogfooding)
- [ ] 95%+ test coverage maintained
- [ ] All QA checks pass
- [ ] Daemon restarts successfully

## Implementation Phases

- **Phase 1**: Design & Documentation
- **Phase 2**: Core Infrastructure (ProjectPaths, LanguageConfig)
- **Phase 3**: Refactor Critical Handlers (TDD, Plans)
- **Phase 4**: Refactor Moderate Handlers (QA blockers)
- **Phase 5**: Update Project Configuration
- **Phase 6**: Testing & Validation

## Research Sources

- [ESLint Configuration Files](https://eslint.org/docs/latest/use/configure/configuration-files)
- [ESLint v10.0.0 Testing Enhancements](https://eslint.org/blog/2026/02/eslint-v10.0.0-released/)
- [Pytest Test Discovery Conventions](https://www.learnthatstack.com/interview-questions/testing/pytest/what-are-the-naming-conventions-for-pytest-test-discovery-25718)
- [Language-Agnostic Testing - TESTed Framework](https://www.sciencedirect.com/science/article/pii/S2352711023001000)
- [Go Testing Frameworks 2026](https://speedscale.com/blog/golang-testing-frameworks-for-every-type-of-test/)

## Next Steps

1. Review plan with team/stakeholders
2. Get approval to proceed
3. Begin Phase 1: Design & Documentation
4. Implement using TDD (write failing tests first!)
5. Verify daemon restarts successfully after each phase
6. Run full QA suite before marking complete

## Questions?

- **What's the biggest issue?** TddEnforcementHandler - blocks all multi-language TDD enforcement
- **Will this break existing functionality?** No - backward compatible with smart defaults
- **Can we do this incrementally?** Yes - phased approach by severity
- **What if we skip this?** Daemon remains project-specific, limits adoption

---

**Created**: 2026-02-09
**Owner**: Unassigned
**See**: PLAN.md for complete details
