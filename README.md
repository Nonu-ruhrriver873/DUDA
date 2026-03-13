# 🦔 DUDA — Isolation Guardian for Claude Code

**Prevent, diagnose, and recover isolation contamination in multi-layered architectures.**

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-blueviolet)](https://claude.ai/claude-code)
[![Eval Score](https://img.shields.io/badge/Eval%20Score-98%25-brightgreen)]()

---

## What is DUDA?

DUDA (named after moles — "두더지" in Korean — because they appear separate above ground but are all connected underground) is a **Claude Code skill** that guards isolation boundaries in complex architectures.

It prevents developers from accidentally:
- **Leaking tenant data** across multi-tenant boundaries
- **Importing platform-only code** into tenant/derivative layers
- **Violating monorepo app boundaries** with direct cross-app imports
- **Bypassing microservice API boundaries** with direct DB access

### The Problem

In multi-layered architectures, "just copy it over" is the most dangerous phrase:

```
Developer: "Use the AdminPanel from platform in the tenant app"
AI Agent:  "Sure! *copies files, creates imports*"
Result:    Tenant users can now see platform admin controls 💀
```

DUDA structurally prevents this by:
1. **Mapping** the entire project's isolation structure (topological sort)
2. **Analyzing** every import and dependency before any code moves
3. **Measuring** a 4-axis trust score (95-point threshold)
4. **Blocking** execution until the trust score is met

---

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/popup-studio-ai/duda-skill.git

# Copy to your Claude Code skills directory
cp -r duda-skill/duda ~/.claude/skills/duda
```

Or add directly as a Claude Code skill:
```bash
# From your project root
mkdir -p .claude/skills
cp -r path/to/duda .claude/skills/duda
```

### Optional: Install Hook for Auto-Detection

Add to your `.claude/settings.json`:
```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "type": "command",
        "command": "node .claude/skills/duda/hooks/duda-hook.js"
      }
    ]
  }
}
```

### First Use

```
You: duda init
DUDA: 🦔 Running topological exploration...
      ✅ DUDA_MAP generated
      Files tagged: 234 complete / 5 ambiguous
      Does this structure look correct? (Y / enter corrections)
```

---

## Modes

### 🗺️ INIT — Map Your Architecture

```
You: duda init
```

Explores your project using topological sort (leaf files → upward) and generates `DUDA_MAP.md` with isolation tags for every file.

### 🔍 SCAN — Quick File Check (No Map Required)

```
You: duda scan src/tenant/components/OrderForm.tsx
```

Lightweight analysis of a single file. Answers: "Is this safe to import in my layer?"

### 🚚 TRANSPLANT — Safe Code Migration

```
You: I want to use the MenuCard component from platform in tenant
```

Analyzes dependencies, measures trust score, and only permits migration when score ≥ 95. Selects the safest strategy:

| Strategy | When |
|----------|------|
| **1. Direct Reference** | All dependencies are `[SHARED]` |
| **2. Adapter** | Mixed deps, shared logic > 60% |
| **3. Rebuild** | Too many platform-specific deps |
| **4. Deny** | Core `[UPPER-ONLY]` or deny-listed |

### 🔬 AUDIT — Find & Fix Contamination

```
You: Tenant A is seeing tenant B's data on the menu page
```

Traces the contamination path, determines root cause, and provides fix with verification checklist.

---

## Isolation Types

| Type | Description | Example |
|------|-------------|---------|
| **Type A** Platform-Derivative | Upper→lower inheritance | Platform → Org → Tenant → Store |
| **Type B** Multi-tenant | Per-org data isolation | Shared code, separated data via RLS |
| **Type C** Monorepo | Cross-app code isolation | apps/ can only share via packages/ |
| **Type D** Microservice | Service boundary isolation | Services communicate only via APIs |

---

## Trust Score System

DUDA uses a 4-axis trust measurement. **95 points required to proceed.**

```
Map Trust      (×0.20): Map completeness, checksums, approval
Analysis Trust (×0.35): Import tagging, dynamic logic, DB isolation
Boundary Trust (×0.30): Policy existence, no contamination, no deny-list conflict
Intent Trust   (×0.15): Source/destination specified, scope confirmed
```

| Score | Verdict |
|-------|---------|
| 95-100 | ✅ Execution permitted |
| 85-94 | 🟡 Conditional — fix shortfalls first |
| 70-84 | 🟠 Hold — user judgment required |
| <70 | 🔴 Denied |

---

## Recursive Learning Memory

DUDA gets faster with use. The memory system caches analysis results:

```
First run    [UNKNOWN]  → Full analysis required
1 experience [LOW]      → Full analysis + reference previous
2 experiences [MEDIUM]  → Quick analysis + cache comparison
3 experiences [HIGH]    → Skip analysis, use cache  ← acceleration starts
5+ experiences [CERTAIN] → Instant processing
```

Check status:
```
You: python scripts/memory.py stats
```

---

## Manual Mode (No Python)

If Python is not available, DUDA includes a manual analysis guide in SKILL.md. It walks you through:
- Manual INIT using grep commands
- Manual TRANSPLANT via import analysis
- Manual AUDIT via contamination search

---

## Project Structure

```
duda/
├── SKILL.md              ← Main skill definition
├── README.md             ← This file
├── LICENSE               ← Apache-2.0
├── CONTRIBUTING.md       ← How to contribute
├── scripts/
│   ├── init.py           ← Topological exploration + map generation
│   ├── analyze.py        ← Import dependency analysis + layer tagging
│   ├── trust.py          ← 4-axis trust measurement + 95-point gate
│   ├── audit.py          ← Contamination path detection + root cause
│   ├── map_update.py     ← Post-work partial map refresh
│   └── memory.py         ← Recursive learning memory
├── references/
│   └── patterns.md       ← Risk/fix patterns by isolation type
├── hooks/
│   └── duda-hook.js      ← Claude Code trigger detection hook
└── evals/
    └── evals.json        ← Skill validation test cases
```

---

## CLAUDE.md Integration

Add this to your project's `CLAUDE.md` for DUDA auto-configuration:

```markdown
## DUDA Context

Isolation type: Type A + Type B

Hierarchy:
  - Platform: Core feature definitions
  - Organization: Org-level customization
  - Tenant: Per-tenant operations

Isolation boundary:
  - Method: RLS + import rules
  - Tenant identifier: org_id
  - Upper-only paths: src/platform/
  - Lower-only paths: src/tenant/
  - Shared paths: packages/

Transplant deny list:
  - Admin config management: Platform-only feature
  - Cost master data: Sensitive pricing data
```

---

## Requirements

- **Claude Code** v2.1.0+ (Skills 2.0 support)
- **Python 3.8+** (optional — for script automation; manual mode works without)
- No external pip packages required (stdlib only)

---

## FAQ

### Why 95 points, not 100?

100 would block operations where minor ambiguities exist but the core isolation is sound. 95 allows those cases while still blocking genuinely risky operations. The remaining 5 points account for inherent uncertainty in static analysis.

### What if I don't have Python?

DUDA includes a complete Manual Mode in SKILL.md with grep-based analysis commands. Python scripts automate the process but aren't required.

### Does DUDA work with any framework?

Yes. DUDA analyzes import paths and file structure, not framework-specific APIs. It works with Next.js, React, Vue, Angular, Express, NestJS, and any TypeScript/JavaScript project. Python project support is included for import analysis.

### Can I use DUDA in a greenfield project?

Yes! Run `duda init` at project start to establish the isolation map early. This prevents contamination from the beginning rather than fixing it later.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## License

[Apache License 2.0](LICENSE)

---

## Credits

Created by [POPUP STUDIO PTE. LTD.](https://github.com/popup-studio-ai)

> *"Moles appear separate above ground, but underground they're all connected by tunnels."*
