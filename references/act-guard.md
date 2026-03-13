# ACT & GUARD Mode — Detailed Specification

> See REFERENCES.md for pattern attribution (bkit, ESLint, Terraform, Snyk).

---

## ACT Mode — Automated Fix Generation

### ACT after AUDIT (Contamination Fix)

```
Phase 1 — Fix Plan Generation (read-only)
  ├─ Parse AUDIT output: root cause type + contamination path + impact scope
  ├─ Generate fix plan based on root cause:
  │   A. Isolation policy leak  → Add missing tenant filter / RLS policy
  │   B. Component contamination → Remove upper-only imports, create adapter or shared version
  │   C. State contamination    → Split shared store/context by layer
  │   D. Boundary violation     → Replace direct import with API call / shared package
  ├─ Show diff preview:
  │     📋 DUDA FIX PLAN — 3 files to modify
  │     [1] src/tenant/api/menu.ts  — add org_id filter to query
  │     [2] src/tenant/stores/menuStore.ts — remove platform import
  │     [3] src/shared/adapters/menuAdapter.ts — CREATE new adapter
  └─ Confirm? (Y/N/edit)

Phase 2 — Apply (write mode, only after confirmation)
  ├─ Apply fixes in reverse file order (prevents offset drift)
  ├─ Create new files (adapters, shared wrappers) if needed
  └─ Never modify [UPPER-ONLY] source files

Phase 3 — Verify (Evaluator-Optimizer loop, max 3 iterations)
  ├─ Re-run: python scripts/audit.py --target [affected_paths] --quick
  ├─ If contamination cleared → ✅ PASS → update map + memory
  ├─ If contamination remains → generate next fix iteration
  └─ If 3 iterations exhausted → ⚠️ escalate to manual review
```

### ACT after TRANSPLANT (Code Generation)

```
Phase 1 — Code Generation (based on selected strategy)
  ├─ Strategy 1 (Direct Reference):
  │     Generate import statement pointing to shared package
  │     Verify target package exports the needed interface
  │
  ├─ Strategy 2 (Adapter):
  │     Generate adapter file in shared layer
  │     Generate interface matching source signature
  │     Wire adapter to use lower-layer-safe dependencies only
  │
  ├─ Strategy 3 (Reimplementation):
  │     Generate skeleton with same interface as source
  │     Replace all upper-only dependencies with lower-layer equivalents
  │     Mark sections requiring manual implementation with TODO
  │
  └─ Strategy 4 (Deny):
        No code generated — output denial reason + alternatives

Phase 2 — Apply (same as AUDIT ACT Phase 2)

Phase 3 — Verify
  ├─ Re-run: python scripts/trust.py --mode transplant --source [s] --target [t]
  ├─ Trust still ≥ 95 → ✅ PASS
  ├─ Trust dropped → undo + report why
  └─ Update map + memory
```

### ACT Output Example

```
🔧 DUDA ACT — Fix Applied

Mode:        AUDIT fix / TRANSPLANT strategy [N]
Files modified:  3
Files created:   1
Iterations:      1 (clean on first pass)

Changes:
  [M] src/tenant/api/menu.ts        +2 -1  (added org_id filter)
  [M] src/tenant/stores/menuStore.ts +1 -3  (removed platform import)
  [M] src/tenant/components/Menu.tsx +1 -1  (switched to adapter)
  [A] src/shared/adapters/menuAdapter.ts  (new adapter)

Verification: ✅ PASS — contamination cleared
Trust score:  97 → 99 (post-fix)

Memory recorded: pattern AUDIT__menu__tenant → confidence LOW (first occurrence)
```

---

## GUARD Mode — CI / Pre-commit Isolation Gate

### Pre-commit Hook Setup

```bash
# .git/hooks/pre-commit (add this)
#!/bin/sh
python3 ${DUDA_PATH}/scripts/audit.py \
  --mode ci \
  --target staged \
  --fail-on-breach
# Exit 0 = pass, 1 = breach blocked, 2 = ambiguous (warning only)
```

### GitHub Actions Integration

```yaml
name: DUDA Isolation Guard
on: [pull_request]
jobs:
  isolation-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: '3.9'
      - name: Run DUDA Guard
        run: |
          git diff --name-only origin/main...HEAD > changed.txt
          python3 scripts/audit.py \
            --mode ci \
            --changed-files changed.txt \
            --output json > audit.json
          python3 -c "
          import json, sys
          r = json.load(open('audit.json'))
          if r.get('breaches', 0) > 0:
              print(f'🔴 {r[\"breaches\"]} isolation breach(es) detected')
              for b in r.get('details', []):
                  print(f'  - {b[\"file\"]}: {b[\"reason\"]}')
              sys.exit(1)
          print('✅ Isolation check passed')
          "
```

### GUARD Output (Interactive)

```
🛡️ DUDA GUARD — Pre-commit Check

Staged files:  12
Checked:       12
Breaches:      1

🔴 src/tenant/utils/pricing.ts
   Imports from @/platform/admin/costConfig (UPPER-ONLY)
   Suggestion: Use adapter or import from @/shared/pricing instead

Commit blocked. Fix the breach or run: git commit --no-verify (not recommended)
```

### GUARD Output (CI — JSON)

```json
{
  "status": "FAIL",
  "breaches": 1,
  "checked": 12,
  "details": [
    {
      "file": "src/tenant/utils/pricing.ts",
      "line": 3,
      "type": "UPPER-ONLY import in lower layer",
      "severity": "HIGH",
      "reason": "Imports @/platform/admin/costConfig",
      "suggestion": "Use @/shared/pricing adapter"
    }
  ]
}
```
