# Changelog

All notable changes to DUDA will be documented in this file.

## [2.0.0] - 2026-03-14

### Added
- **ACT mode** — Automated fix generation after AUDIT/TRANSPLANT diagnosis
  - Fix plan generation with diff preview (read-only until confirmation)
  - Evaluator-Optimizer loop: re-audit after fix, max 3 iterations
  - Strategy-specific code generation (adapter, reimplementation, direct reference)
  - Progressive automation: SHOW → SUGGEST → APPLY → AUTO
- **GUARD mode** — CI/pre-commit isolation gate
  - Pre-commit hook integration (exit 0/1)
  - GitHub Actions workflow template
  - JSON output for CI parsing
  - Checks staged/changed files for isolation breaches
- **REFERENCES.md** — Attribution for patterns referenced from bkit v1.6.1 and industry tools
- Hook triggers for ACT and GUARD modes in duda-hook.js

### Referenced Patterns (see REFERENCES.md)
- bkit pdca-iterator: Evaluator-Optimizer loop (agents/pdca-iterator.md)
- bkit automation.js: Progressive automation levels (lib/pdca/automation.js)
- bkit gap-detector: Match rate → conditional branching (agents/gap-detector.md)
- bkit code-analyzer: Read-only analysis mode (agents/code-analyzer.md)
- ESLint --fix: Reverse-position batch apply
- Terraform: Plan-before-apply, drift detection
- Snyk: Fixability scoring

## [1.0.1] - 2026-03-14

### Fixed
- Python 3.8/3.9 compatibility: added `from __future__ import annotations` to init.py, trust.py, memory.py
  - `Path | None` union type syntax requires Python 3.10+; future annotations enables deferred evaluation for 3.7+

### Changed
- Restructured as Claude Code Plugin Marketplace compatible
  - `SKILL.md` → `skills/duda/SKILL.md`
  - Added `hooks/hooks.json` for automatic hook registration
- README updated with plugin install commands:
  ```
  /plugin marketplace add DavidKim0326/DUDA
  /plugin install duda
  ```

## [1.0.0] - 2026-03-14

### Added
- Initial public release
- 4 modes: INIT, SCAN, TRANSPLANT, AUDIT
- 4 isolation types: Platform-Derivative (A), Multi-tenant (B), Monorepo (C), Microservice (D)
- 4-axis trust score system with 95-point execution gate
- 6 Python automation scripts (stdlib only, no pip dependencies)
- Recursive learning memory system (UNKNOWN → CERTAIN progression)
- UserPromptSubmit hook for English trigger auto-detection
- Manual mode fallback (grep-based, no Python required)
- 16 eval test cases
- Reference patterns for all isolation types
- Apache-2.0 license
