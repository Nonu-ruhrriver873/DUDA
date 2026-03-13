#!/usr/bin/env python3
"""
DUDA analyze.py — import dependency analysis + layer tagging
TRANSPLANT Phase 2: Dissects source files and assigns a layer tag to each dependency.

Usage:
  python analyze.py --source [file or directory] [--root project_root]
"""

import re
import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

# Memory layer import (optional — works without it)
try:
    from .memory import DudaMemory
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False


# -- Pattern definitions -------------------------------------------------------

# Statically unverifiable patterns
UNVERIFIABLE_PATTERNS = {
    r"import\s*\(":        "dynamic import()",
    r"require\s*\(":       "conditional require()",
    r"role\s*===":         "runtime role check",
    r"process\.env\.":     "environment variable branch",
    r"window\.":           "browser-only API",
}

# DB query patterns (Supabase-based, extensible)
DB_QUERY_PATTERNS = [
    r"\.from\s*\(\s*['\"](\w+)['\"]",        # supabase .from('table')
    r"SELECT\s+.*?\s+FROM\s+(\w+)",           # raw SQL
    r"prisma\.\w+\.find",                     # Prisma
    r"db\.query",                             # generic
]

# Tenant identifier patterns (overridable from CLAUDE.md)
DEFAULT_TENANT_PATTERNS = [
    r"org_id", r"tenant_id", r"company_id",
    r"tenant_id", r"brand_id", r"store_id",
    r"user_id",  # plain user_id is weak isolation
]


# -- File analysis -------------------------------------------------------------

def extract_imports_detailed(file_path: Path) -> list[dict]:
    """Extract detailed imports from a file"""
    imports = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return imports

    lines = content.split("\n")
    for i, line in enumerate(lines, 1):
        # ES6 import
        m = re.search(r'import\s+(?:.*?\s+from\s+)?[\'"]([^\'"]+)[\'"]', line)
        if m:
            imports.append({
                "path": m.group(1),
                "line": i,
                "raw": line.strip(),
                "type": "static",
            })

        # dynamic import
        m = re.search(r'import\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)', line)
        if m:
            imports.append({
                "path": m.group(1),
                "line": i,
                "raw": line.strip(),
                "type": "dynamic",
            })

        # require
        m = re.search(r'require\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)', line)
        if m:
            imports.append({
                "path": m.group(1),
                "line": i,
                "raw": line.strip(),
                "type": "require",
            })

    return imports


def extract_db_queries(content: str, tenant_patterns: list[str]) -> dict:
    """Extract DB queries + check for tenant identifier presence"""
    queries = []
    queries_with_tenant = 0

    for pattern in DB_QUERY_PATTERNS:
        matches = re.finditer(pattern, content, re.IGNORECASE)
        for m in matches:
            # Extract surrounding context (+/-3 lines)
            start = max(0, m.start() - 200)
            end = min(len(content), m.end() + 200)
            ctx = content[start:end]

            has_tenant = any(
                re.search(tp, ctx, re.IGNORECASE)
                for tp in tenant_patterns
            )
            queries.append({
                "match": m.group(0),
                "has_tenant": has_tenant,
            })
            if has_tenant:
                queries_with_tenant += 1

    return {
        "total": len(queries),
        "with_tenant": queries_with_tenant,
        "queries": queries,
    }


def detect_unverifiable(content: str) -> list[dict]:
    """Detect dynamic/runtime patterns"""
    found = []
    for pattern, description in UNVERIFIABLE_PATTERNS.items():
        matches = re.findall(pattern, content)
        if matches:
            found.append({
                "pattern": pattern,
                "description": description,
                "count": len(matches),
            })
    return found


def detect_hardcoded_identifiers(content: str, upper_hints: list[str]) -> list[str]:
    """Detect hardcoded upper-layer-only identifiers"""
    found = []
    for hint in upper_hints:
        # Patterns like role === 'system_admin'
        patterns = [
            rf'[\'\"]{hint}[\'\"]\s*[,\]}})]',
            rf'role.*[\'\"]{hint}[\'\"]',
            rf'type.*[\'\"]{hint}[\'\"]',
        ]
        for p in patterns:
            if re.search(p, content, re.IGNORECASE):
                found.append(hint)
                break
    return found


# -- Layer tagging -------------------------------------------------------------

def tag_import(
    import_path: str,
    import_type: str,
    map_data: dict,
    ctx: dict,
) -> tuple[str, str]:
    """
    Assign a layer tag to a single import.
    Returns: (tag, reason)
    """
    imp_lower = import_path.lower()

    # dynamic import -> UNVERIFIABLE
    if import_type in ("dynamic", "require"):
        return "UNVERIFIABLE", "Dynamic import — static analysis impossible"

    # Use DUDA_MAP tagging data
    for tagged_path, (tag, _) in map_data.get("tagged_files", {}).items():
        if import_path.replace("/", os.sep) in tagged_path:
            return tag, f"Map tagging confirmed: {tagged_path}"

    # Upper-only path hints
    for hint in ctx.get("upper_paths", ["system", "admin"]):
        if hint and hint.lower() in imp_lower:
            return "UPPER-ONLY", f"Upper-only path detected: {hint}"

    # Lower-only path hints
    for hint in ctx.get("lower_paths", ["tenant", "store"]):
        if hint and hint.lower() in imp_lower:
            return "LOWER-ONLY", f"Lower-only path detected: {hint}"

    # Shared paths
    for hint in ctx.get("shared_paths", ["packages", "shared", "utils", "types"]):
        if hint and hint.lower() in imp_lower:
            return "SHARED", f"Shared path: {hint}"

    # Relative path (assumed same layer)
    if import_path.startswith("."):
        return "SHARED", "Relative path — assumed same layer"

    # External package
    if not import_path.startswith(".") and not import_path.startswith("/"):
        return "SHARED", "External npm package"

    return "SHARED", "Unable to determine — defaulting to SHARED (review recommended)"


# -- Strategy decision ---------------------------------------------------------

def determine_strategy(tags: list[str], unverifiable_count: int) -> dict:
    """
    Automatically determine transplant strategy based on tag distribution.
    """
    tag_counts = {
        "UPPER-ONLY": tags.count("UPPER-ONLY"),
        "SHARED": tags.count("SHARED"),
        "NEEDS-ADAPTER": tags.count("NEEDS-ADAPTER"),
        "REBUILD": tags.count("REBUILD"),
        "LOWER-ONLY": tags.count("LOWER-ONLY"),
        "UNVERIFIABLE": tags.count("UNVERIFIABLE"),
    }
    total = max(len(tags), 1)

    # Strategy 4: Denial condition
    if tag_counts["UPPER-ONLY"] > 0:
        upper_ratio = tag_counts["UPPER-ONLY"] / total
        if upper_ratio > 0.5:
            return {
                "strategy": 4,
                "name": "Transplant denied",
                "reason": f"[UPPER-ONLY] {tag_counts['UPPER-ONLY']} found — core logic is upper-only",
                "risk": "BLOCK",
            }

    # High UNVERIFIABLE count -> CAUTION
    risk = "SAFE"
    if unverifiable_count > 0:
        risk = "CAUTION"
    if tag_counts["UPPER-ONLY"] > 0:
        risk = "CAUTION" if risk == "SAFE" else "BLOCK"

    # Strategy 3: Reimplementation
    if tag_counts["REBUILD"] > 0:
        return {
            "strategy": 3,
            "name": "Reimplementation",
            "reason": f"[REBUILD] {tag_counts['REBUILD']} found — rewrite needed for lower layer",
            "risk": risk,
        }

    # Strategy 2: Adapter branching
    shared_ratio = tag_counts["SHARED"] / total
    if tag_counts["NEEDS-ADAPTER"] > 0 or (tag_counts["UPPER-ONLY"] > 0 and shared_ratio > 0.4):
        return {
            "strategy": 2,
            "name": "Adapter branching",
            "reason": f"Shared logic {shared_ratio*100:.0f}% — mode prop branching approach",
            "risk": risk,
        }

    # Strategy 1: Direct reference
    if tag_counts["UPPER-ONLY"] == 0 and tag_counts["REBUILD"] == 0:
        return {
            "strategy": 1,
            "name": "Direct reference",
            "reason": "All dependencies [SHARED] — direct use after isolation policy check",
            "risk": "SAFE",
        }

    return {
        "strategy": 2,
        "name": "Adapter branching",
        "reason": "Complex dependencies — adapter branching recommended",
        "risk": risk,
    }


# -- Report output -------------------------------------------------------------

def print_analysis_report(result: dict):
    print("\n" + "="*60)
    print(f"DUDA ANALYZE — {result['source']}")
    print("="*60)

    print(f"\n  Total imports: {result['total_imports']}")
    print(f"  Tagged: {result['tagged_imports']}")

    print("\n  Dependency tag distribution:")
    for tag, count in result["tag_distribution"].items():
        if count > 0:
            marker = "[!]" if tag == "UPPER-ONLY" else "[?]" if tag == "UNVERIFIABLE" else "[o]"
            print(f"    {marker} [{tag}]: {count}")

    if result["unverifiable_patterns"]:
        print(f"\n  WARNING: {len(result['unverifiable_patterns'])} statically unverifiable pattern(s):")
        for p in result["unverifiable_patterns"]:
            print(f"    - {p['description']} ({p['count']} occurrence(s))")

    if result["db_analysis"]["total"] > 0:
        db = result["db_analysis"]
        print(f"\n  DB queries: {db['total']}")
        print(f"    With tenant identifier: {db['with_tenant']}")
        if db["total"] > db["with_tenant"]:
            print(f"    WARNING: Without tenant identifier: {db['total'] - db['with_tenant']}")

    if result["hardcoded_identifiers"]:
        print(f"\n  WARNING: Hardcoded upper-only identifiers: {result['hardcoded_identifiers']}")

    strategy = result["strategy"]
    risk_icon = "[!]" if strategy["risk"] == "BLOCK" else "[?]" if strategy["risk"] == "CAUTION" else "[o]"
    print(f"\n  Risk level: {risk_icon} {strategy['risk']}")
    print(f"  Recommended strategy: Strategy {strategy['strategy']} — {strategy['name']}")
    print(f"  Reason: {strategy['reason']}")
    print("="*60 + "\n")


# -- Main ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="DUDA source dissection analysis")
    parser.add_argument("--source", required=True, help="File or directory to analyze")
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument("--output-json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    source_path = Path(args.source)
    if not source_path.is_absolute():
        source_path = root / args.source

    # Load CLAUDE.md context
    from init import load_claude_context
    ctx = load_claude_context(root)

    # Load DUDA_MAP tagging data
    map_tagged = {}
    map_path = root / "DUDA_MAP.md"
    # (simplified — in practice uses JSON summary from init.py)

    # Collect files to analyze
    if source_path.is_dir():
        from init import collect_source_files
        files = collect_source_files(source_path)
    else:
        files = [source_path]

    all_imports = []
    all_tags = []
    all_unverifiable = []
    all_hardcoded = []
    db_total = 0
    db_with_tenant = 0

    tenant_patterns = DEFAULT_TENANT_PATTERNS
    if ctx.get("tenant_id"):
        # Use identifier defined in CLAUDE.md as priority
        tenant_patterns = [ctx["tenant_id"]] + DEFAULT_TENANT_PATTERNS

    for file in files:
        try:
            content = file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        # Extract imports + tagging
        imports = extract_imports_detailed(file)
        for imp in imports:
            tag, reason = tag_import(
                imp["path"], imp["type"],
                {"tagged_files": map_tagged}, ctx
            )
            imp["tag"] = tag
            imp["reason"] = reason
            all_imports.append(imp)
            all_tags.append(tag)

        # DB query analysis
        db_result = extract_db_queries(content, tenant_patterns)
        db_total += db_result["total"]
        db_with_tenant += db_result["with_tenant"]

        # Dynamic pattern detection
        unverifiable = detect_unverifiable(content)
        all_unverifiable.extend(unverifiable)

        # Hardcoded identifiers
        upper_hints = ctx.get("upper_paths", ["system", "admin", "system_admin"])
        hardcoded = detect_hardcoded_identifiers(content, upper_hints)
        all_hardcoded.extend(hardcoded)

    # Tag distribution
    tag_distribution = {
        "UPPER-ONLY": all_tags.count("UPPER-ONLY"),
        "LOWER-ONLY": all_tags.count("LOWER-ONLY"),
        "SHARED": all_tags.count("SHARED"),
        "NEEDS-ADAPTER": all_tags.count("NEEDS-ADAPTER"),
        "REBUILD": all_tags.count("REBUILD"),
        "UNVERIFIABLE": all_tags.count("UNVERIFIABLE"),
    }

    # Strategy decision
    strategy = determine_strategy(all_tags, len(all_unverifiable))

    result = {
        "source": str(source_path),
        "total_imports": len(all_imports),
        "tagged_imports": sum(1 for t in all_tags if t != "UNVERIFIABLE"),
        "tag_distribution": tag_distribution,
        "upper_only_count": tag_distribution["UPPER-ONLY"],
        "upper_only_handled": 0,  # Updated after strategy planning in Phase 3
        "unverifiable_count": len(all_unverifiable),
        "unverifiable_patterns": all_unverifiable[:5],
        "db_analysis": {
            "total": db_total,
            "with_tenant": db_with_tenant,
        },
        "hardcoded_identifiers": list(set(all_hardcoded)),
        "strategy": strategy,
        "imports": all_imports[:20],  # Save only top 20
        "timestamp": datetime.now().isoformat(),
    }

    print_analysis_report(result)

    # Save results (so trust.py can read them)
    result_path = root / ".duda" / "duda-analyze-result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Analysis results saved: {result_path}")

    # -- Memory layer recording ------------------------------------------------
    if MEMORY_AVAILABLE:
        try:
            mem = DudaMemory(root)

            # Cache all import tag results in path cache
            for imp in all_imports:
                if imp.get("tag") and imp["tag"] != "UNVERIFIABLE":
                    mem.record_path_tag(imp["path"], imp["tag"], "analyze")

            # Save strategy decision to pattern DB
            mem.record_pattern(
                mode="TRANSPLANT",
                source=str(source_path),
                target=None,
                result={
                    "strategy": strategy["strategy"],
                    "strategy_name": strategy["name"],
                    "risk": strategy["risk"],
                    "tag_distribution": tag_distribution,
                    "unverifiable_count": len(all_unverifiable),
                },
            )
            print(f"Memory saved ({len(all_imports)} paths cached)")
        except Exception as e:
            print(f"WARNING: Memory save failed (non-fatal): {e}")


if __name__ == "__main__":
    main()
