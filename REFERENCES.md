# DUDA v2.0 — References & Attribution

## bkit v1.6.1 Patterns Referenced

DUDA v2.0 references architectural patterns from [bkit Vibecoding Kit](https://github.com/popup-studio-ai/bkit-claude-code) v1.6.1.
These are pattern-level references (design concepts), not code copies.

### 1. Evaluator-Optimizer Loop

**Source:** `bkit/agents/pdca-iterator.md` (lines 60-86, 157-185)

**Pattern:** Generator → Output → Evaluator → Decision (Pass/Fail) → Loop or Complete.
Max 5 iterations per session, converges when Match Rate >= 90%.

**Used in DUDA:** ACT mode iteration — after applying a fix, re-run AUDIT to verify
contamination is cleared. Loop until clean or max 3 iterations.

### 2. Progressive Automation Levels

**Source:** `bkit/lib/pdca/automation.js` (lines 28-64)

**Pattern:** Three-tier automation: `manual` → `semi-auto` → `full-auto`.
`shouldAutoAdvance(phase)` decides whether to auto-trigger next phase.

**Used in DUDA:** 4-stage progressive automation: SHOW → SUGGEST → APPLY → AUTO.
Each stage requires explicit opt-in or sufficient memory confidence.

### 3. Gap Detection → Conditional Branching

**Source:** `bkit/agents/gap-detector.md` (lines 205-327)

**Pattern:** Structured findings with match rate → conditional action.
Match Rate < 90% triggers auto-improvement cycle.

**Used in DUDA:** Trust Score < 95 → list shortfalls + resolution order.
Trust Score >= 95 → proceed to code generation.
Maps gap-detector's "match rate" concept to DUDA's "trust score" concept.

### 4. Read-Only Analysis Mode

**Source:** `bkit/agents/code-analyzer.md` (lines 2-18)

**Pattern:** `permissionMode: plan` + `disallowedTools: [Write, Edit]`.
Structured output with severity levels for downstream processing.

**Used in DUDA:** SCAN and AUDIT diagnosis phases are read-only.
Only ACT mode transitions to write permissions after trust gate passes.

### 5. Report Template Structure

**Source:** `bkit/agents/report-generator.md` (lines 43-251)

**Pattern:** 4-perspective Executive Summary (Problem / Solution / Function-UX Effect / Core Value).
Hierarchical report storage with versioning.

**Used in DUDA:** GUARD mode CI reports and AUDIT summary output
follow the structured template pattern with severity + actionable items.

---

## Industry Patterns Referenced

| Pattern | Source | Used In |
|---------|--------|---------|
| Reverse-position batch apply | ESLint `--fix` | ACT mode: apply fixes in reverse file order to avoid offset drift |
| Fixability scoring | Snyk auto-fix | ACT mode: score fixes by safety-to-apply, not just severity |
| Plan-before-apply | Terraform | ACT mode: show diff of proposed changes before execution |
| Drift detection → remediation | Terraform plan/apply | GUARD mode: detect isolation drift in CI |

---

## License

bkit is licensed under its own terms. DUDA references patterns at the design/architecture
level only. No source code from bkit is included in DUDA.

DUDA itself is licensed under Apache-2.0.
