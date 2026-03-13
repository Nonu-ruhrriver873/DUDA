#!/usr/bin/env python3
"""
DUDA audit.py — Contamination path detection + root cause determination
AUDIT mode: Symptom → Trace → Root cause determination → Restore prompt generation

Usage:
  python audit.py --symptom "[symptom]" --layer "[layer_name]"  # Full AUDIT
  python audit.py --target [path] --quick                       # TRANSPLANT pre-check
"""

import re
import os
import json
import subprocess
import argparse
from pathlib import Path
from datetime import datetime


# ── Contamination pattern definitions ─────────────────────────────────────────

# Detection patterns by root cause type
CONTAMINATION_PATTERNS = {
    "B_component": {
        # Import of upper-only paths from lower layer files
        "description": "Component contamination — [UPPER-ONLY] code copy-paste",
        "grep_template": r"from ['\"].*{upper_path}.*['\"]",
        "search_in": "lower_paths",
    },
    "A_policy": {
        # DB queries without tenant identifier
        "description": "Isolation policy leak — queries without tenant identifier",
        "grep_template": r"\.from\s*\(\s*['\"](\w+)['\"]",
        "search_in": "lower_paths",
    },
    "C_state": {
        # Shared store/context cross-import
        "description": "State contamination — shared store/context scope not separated",
        "grep_template": r"from ['\"].*store.*['\"]|useContext|createContext",
        "search_in": "all",
    },
    "D_boundary": {
        # Direct import between apps
        "description": "Boundary violation — direct import between apps/",
        "grep_template": r"from ['\"].*apps/.*['\"]",
        "search_in": "all",
    },
}

CONTAMINATION_TYPE_NAMES = {
    "A_policy": "A. Isolation policy leak",
    "B_component": "B. Component contamination (most common)",
    "C_state": "C. State contamination",
    "D_boundary": "D. Boundary violation",
}


# ── grep execution ────────────────────────────────────────────────────────────

def run_grep(pattern: str, search_path: Path, extensions: list[str]) -> list[dict]:
    """Run grep + parse results"""
    results = []
    if not search_path.exists():
        return results

    include_args = []
    for ext in extensions:
        include_args.extend(["--include", f"*{ext}"])

    try:
        cmd = ["grep", "-rn", pattern, str(search_path)] + include_args
        output = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30
        )
        for line in output.stdout.strip().split("\n"):
            if line and ":" in line:
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    results.append({
                        "file": parts[0],
                        "line": parts[1],
                        "content": parts[2].strip(),
                    })
    except Exception as e:
        results.append({"error": str(e)})

    return results


def check_rls_policies(root: Path, ctx: dict) -> dict:
    """Check for RLS policy existence (based on migration files)"""
    migration_dir = root / "supabase" / "migrations"
    if not migration_dir.exists():
        return {"exists": False, "reason": "supabase/migrations folder not found"}

    # Search for isolation policy keywords
    tenant_id = ctx.get("tenant_id", "tenant_id")
    policies_found = []

    for sql_file in migration_dir.glob("*.sql"):
        content = sql_file.read_text(encoding="utf-8", errors="ignore")
        if "CREATE POLICY" in content and tenant_id in content:
            policies_found.append(sql_file.name)

    if policies_found:
        return {
            "exists": True,
            "count": len(policies_found),
            "files": policies_found[:5],
        }
    else:
        return {
            "exists": False,
            "reason": f"No RLS policy containing tenant identifier ({tenant_id})",
        }


def check_forbidden_conflict(target_path: str, forbidden_list: list[dict]) -> dict:
    """Check for transplant forbidden list conflicts"""
    target_lower = target_path.lower()
    for item in forbidden_list:
        name_lower = item.get("name", "").lower()
        if name_lower and name_lower in target_lower:
            return {
                "conflict": True,
                "item": item["name"],
                "reason": item.get("reason", ""),
            }
    return {"conflict": False}


# ── Type-specific contamination detection ─────────────────────────────────────

def detect_type_a(root: Path, ctx: dict, symptom_layer: str) -> list[dict]:
    """Type A: Isolation policy leak — queries without tenant identifier"""
    findings = []
    extensions = [".ts", ".tsx", ".js", ".jsx"]

    lower_paths = ctx.get("lower_paths", [])
    tenant_id = ctx.get("tenant_id", "")

    for lower_path in lower_paths:
        search_dir = root / lower_path
        # Find DB queries
        from_queries = run_grep(r"\.from\s*\(", search_dir, extensions)
        for q in from_queries:
            # Contamination if tenant identifier is missing from surrounding context
            if tenant_id and tenant_id not in q.get("content", ""):
                findings.append({
                    "type": "A_policy",
                    "file": q["file"],
                    "line": q["line"],
                    "detail": f"Query without tenant identifier ({tenant_id}): {q['content'][:80]}",
                })

    return findings


def detect_type_b(root: Path, ctx: dict) -> list[dict]:
    """Type B: Component contamination — upper-only imports from lower layer"""
    findings = []
    extensions = [".ts", ".tsx", ".js", ".jsx"]

    upper_paths = ctx.get("upper_paths", ["system", "admin"])
    lower_paths = ctx.get("lower_paths", ["franchise", "store"])

    for lower_path in lower_paths:
        search_dir = root / lower_path
        if not search_dir.exists():
            # Search apps/ structure
            for apps_dir in root.glob("apps/*"):
                if lower_path.lower() in apps_dir.name.lower():
                    search_dir = apps_dir
                    break

        for upper_path in upper_paths:
            pattern = f"from ['\"].*{upper_path}.*['\"]"
            results = run_grep(pattern, search_dir, extensions)
            for r in results:
                findings.append({
                    "type": "B_component",
                    "file": r["file"],
                    "line": r["line"],
                    "detail": f"Upper-only import from lower layer: {r['content'][:80]}",
                    "contamination_path": f"{upper_path} → {lower_path}",
                })

    return findings


def detect_type_c(root: Path, ctx: dict) -> list[dict]:
    """Type C: State contamination — shared store cross-import"""
    findings = []
    extensions = [".ts", ".tsx", ".js", ".jsx"]

    # Find all store files
    store_files = []
    for pattern in ["**/store/**/*.ts", "**/stores/**/*.ts", "**/*store*.ts"]:
        store_files.extend(root.glob(pattern))

    # Detect store imports crossing layer boundaries
    upper_paths = ctx.get("upper_paths", [])
    lower_paths = ctx.get("lower_paths", [])

    for store_file in store_files[:20]:  # Max 20
        rel = str(store_file.relative_to(root))
        is_upper = any(p in rel for p in upper_paths if p)
        is_lower = any(p in rel for p in lower_paths if p)

        if is_upper:
            # Check if upper-only store is imported from lower layer
            for lower_path in lower_paths:
                search_dir = root / lower_path
                pattern = f"from ['\"].*{store_file.stem}.*['\"]"
                results = run_grep(pattern, search_dir, extensions)
                for r in results:
                    findings.append({
                        "type": "C_state",
                        "file": r["file"],
                        "line": r["line"],
                        "detail": f"Upper-only store imported from lower layer: {store_file.name}",
                    })

    return findings


def detect_type_d(root: Path, ctx: dict) -> list[dict]:
    """Type D: Boundary violation — direct import between apps/"""
    findings = []
    extensions = [".ts", ".tsx", ".js", ".jsx"]

    apps_dir = root / "apps"
    if not apps_dir.exists():
        return findings

    app_names = [d.name for d in apps_dir.iterdir() if d.is_dir()]

    for app_name in app_names:
        search_dir = apps_dir / app_name
        for other_app in app_names:
            if other_app == app_name:
                continue
            pattern = f"from ['\"].*apps/{other_app}.*['\"]"
            results = run_grep(pattern, search_dir, extensions)
            for r in results:
                findings.append({
                    "type": "D_boundary",
                    "file": r["file"],
                    "line": r["line"],
                    "detail": f"Direct import between apps: {app_name} → {other_app}",
                })

    return findings


def detect_type_d_microservice(root: Path, ctx: dict) -> list[dict]:
    """Type D (microservice): Boundary violation — direct DB access or function imports across services"""
    findings = []
    extensions = [".py", ".ts", ".js", ".go", ".java", ".rb"]

    # Detect microservice structure via docker-compose.yml or services/ directory
    services_dir = root / "services"
    docker_compose = root / "docker-compose.yml"
    if not docker_compose.exists():
        docker_compose = root / "docker-compose.yaml"

    service_dirs = []

    if services_dir.exists() and services_dir.is_dir():
        service_dirs = [d for d in services_dir.iterdir() if d.is_dir()]
    elif docker_compose.exists():
        # Parse docker-compose to find service build contexts
        try:
            content = docker_compose.read_text(encoding="utf-8", errors="ignore")
            # Look for build context paths like "./service_name" or "./services/service_name"
            build_matches = re.findall(r'build:\s*(?:context:\s*)?["\']?\./([\w/\-]+)', content)
            for match in build_matches:
                candidate = root / match
                if candidate.exists() and candidate.is_dir():
                    service_dirs.append(candidate)
        except Exception:
            pass

    if len(service_dirs) < 2:
        return findings

    service_names = {d.name: d for d in service_dirs}

    # Check 1: Direct DB access patterns across services
    # Each service should only access its own DB; detect shared DB access patterns
    db_patterns = [
        r"(CREATE TABLE|ALTER TABLE|INSERT INTO|SELECT .* FROM|UPDATE .* SET|DELETE FROM)\s+\w+",
        r"(mongoose\.model|Schema\(|sequelize\.define|prisma\.\w+)",
        r"(engine\.execute|session\.query|Base\.metadata)",
        r"(psycopg2\.connect|mysql\.connector|MongoClient)",
    ]

    service_tables = {}
    for svc_name, svc_dir in service_names.items():
        tables = set()
        for db_pattern in db_patterns:
            results = run_grep(db_pattern, svc_dir, extensions)
            for r in results:
                content = r.get("content", "")
                # Extract table/model names from queries
                table_match = re.search(
                    r'(?:FROM|INTO|UPDATE|TABLE|model\(|define\()\s*["\']?(\w+)',
                    content, re.IGNORECASE
                )
                if table_match:
                    tables.add(table_match.group(1).lower())
        service_tables[svc_name] = tables

    # Detect overlapping table access (direct DB access across service boundaries)
    svc_list = list(service_tables.keys())
    for i, svc_a in enumerate(svc_list):
        for svc_b in svc_list[i + 1:]:
            overlap = service_tables[svc_a] & service_tables[svc_b]
            # Filter out common/generic names
            overlap = {t for t in overlap if t not in {"id", "user", "users", "test", "migration"}}
            if overlap:
                findings.append({
                    "type": "D_boundary",
                    "file": str(service_names[svc_a]),
                    "line": "0",
                    "detail": (
                        f"Direct DB access across services: "
                        f"{svc_a} and {svc_b} both access table(s): {', '.join(sorted(overlap))}"
                    ),
                })

    # Check 2: Direct function imports between services (not via API)
    for svc_name, svc_dir in service_names.items():
        for other_name, other_dir in service_names.items():
            if other_name == svc_name:
                continue
            # Detect direct imports referencing another service's module
            import_patterns = [
                f"from {other_name}",
                f"import {other_name}",
                f"from ['\"].*services/{other_name}",
                f"require\\(['\"].*services/{other_name}",
                f"from ['\"].*{other_name}/",
                f"require\\(['\"].*{other_name}/",
            ]
            for imp_pattern in import_patterns:
                results = run_grep(imp_pattern, svc_dir, extensions)
                for r in results:
                    findings.append({
                        "type": "D_boundary",
                        "file": r["file"],
                        "line": r["line"],
                        "detail": (
                            f"Direct function import between services: "
                            f"{svc_name} imports from {other_name}: {r['content'][:80]}"
                        ),
                    })

    return findings


# ── Restore prompt generation ─────────────────────────────────────────────────

def generate_restore_prompt(findings: list[dict], ctx: dict) -> str:
    """Generate restore execution prompt by root cause type"""
    if not findings:
        return "No contamination — no restore needed"

    # Group by type
    by_type = {}
    for f in findings:
        t = f["type"]
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(f)

    lines = ["## DUDA AUDIT — Restore Execution Prompt\n"]

    for type_key, type_findings in by_type.items():
        type_name = CONTAMINATION_TYPE_NAMES.get(type_key, type_key)
        lines.append(f"### {type_name}")
        lines.append(f"Affected files: {len(type_findings)}\n")

        if type_key == "B_component":
            lines.append("Remove [UPPER-ONLY] imports from the following files:")
            for f in type_findings[:5]:
                lines.append(f"  - {f['file']}:{f['line']}")
                lines.append(f"    → {f['detail']}")
            lines.append("\nAfter fixing, use DUDA TRANSPLANT to establish the correct transplant strategy.\n")

        elif type_key == "A_policy":
            tenant_id = ctx.get("tenant_id", "tenant_id")
            lines.append(f"Add tenant identifier ({tenant_id}) to the following queries:")
            for f in type_findings[:5]:
                lines.append(f"  - {f['file']}:{f['line']}")
            lines.append(f"\nExample: .eq('{tenant_id}', currentUser.{tenant_id})\n")

        elif type_key == "C_state":
            lines.append("Separate the following store imports by layer:")
            for f in type_findings[:5]:
                lines.append(f"  - {f['file']}:{f['line']}")
            lines.append("\nFix: Separate stores by layer or use scope-key-based instantiation\n")

        elif type_key == "D_boundary":
            lines.append("Replace the following cross-app imports with API boundaries:")
            for f in type_findings[:5]:
                lines.append(f"  - {f['file']}:{f['line']}")
            lines.append("\nFix: Use only shared types in packages/, no direct imports\n")

    lines.append("## Verification\n")
    for type_key in by_type:
        if type_key == "B_component":
            upper_paths = ctx.get("upper_paths", ["system"])
            for p in upper_paths:
                lines.append(f"grep -r \"from.*{p}\" {ctx.get('lower_paths', ['franchise'])[0] if ctx.get('lower_paths') else '.'} → should be 0 matches")
        elif type_key == "A_policy":
            lines.append(f"grep -r \"\\.from(\" {ctx.get('lower_paths', ['.'])[0] if ctx.get('lower_paths') else '.'} → verify tenant identifier in all queries")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="DUDA contamination path detection")
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument("--symptom", default=None, help="Symptom description")
    parser.add_argument("--layer", default=None, help="Layer where symptom occurs")
    parser.add_argument("--target", default=None, help="TRANSPLANT pre-check target")
    parser.add_argument("--quick", action="store_true", help="Quick pre-check only")
    parser.add_argument("--type", choices=["A", "B", "C", "D", "all"], default="all")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    from init import load_claude_context
    ctx = load_claude_context(root)

    # TRANSPLANT pre-check (--quick)
    if args.quick and args.target:
        print(f"[SCAN] DUDA pre-check — {args.target}")

        # Quick check Type B only
        findings_b = detect_type_b(root, ctx)
        target_findings = [f for f in findings_b if args.target in f.get("file", "")]

        # Check RLS policies
        rls = check_rls_policies(root, ctx)

        # Transplant forbidden conflict
        forbidden = check_forbidden_conflict(args.target, ctx.get("forbidden", []))

        result = {
            "contamination_found": len(target_findings) > 0,
            "contamination_detail": target_findings[0]["detail"] if target_findings else "",
            "isolation_policy_exists": rls["exists"],
            "forbidden_conflict": forbidden["conflict"],
            "forbidden_item": forbidden.get("item", ""),
        }

        result_path = root / ".duda" / "duda-audit-quick.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))

        if result["contamination_found"]:
            print(f"  [FAIL] Contamination detected: {result['contamination_detail'][:60]}")
        else:
            print("  [PASS] No contamination")
        if not result["isolation_policy_exists"]:
            print(f"  [WARN] Isolation policy not verified")
        if result["forbidden_conflict"]:
            print(f"  [FAIL] Transplant forbidden conflict: {result['forbidden_item']}")
        return

    # Full AUDIT
    print(f"[SCAN] DUDA AUDIT started")
    if args.symptom:
        print(f"  Symptom: {args.symptom}")
    if args.layer:
        print(f"  Layer: {args.layer}")

    all_findings = []

    run_types = {"A", "B", "C", "D"} if args.type == "all" else {args.type}

    if "A" in run_types:
        print("\n  Type A (Isolation policy leak) scanning...")
        findings = detect_type_a(root, ctx, args.layer or "")
        all_findings.extend(findings)
        print(f"    {len(findings)} found")

    if "B" in run_types:
        print("  Type B (Component contamination) scanning...")
        findings = detect_type_b(root, ctx)
        all_findings.extend(findings)
        print(f"    {len(findings)} found")

    if "C" in run_types:
        print("  Type C (State contamination) scanning...")
        findings = detect_type_c(root, ctx)
        all_findings.extend(findings)
        print(f"    {len(findings)} found")

    if "D" in run_types:
        print("  Type D (Boundary violation) scanning...")
        findings = detect_type_d(root, ctx)
        all_findings.extend(findings)
        print(f"    {len(findings)} found")

        print("  Type D (Microservice boundary violation) scanning...")
        findings_ms = detect_type_d_microservice(root, ctx)
        all_findings.extend(findings_ms)
        print(f"    {len(findings_ms)} found")

    # Output results
    print("\n" + "="*60)
    if not all_findings:
        print("[PASS] No contamination — isolation structure is healthy")
    else:
        print(f"[FAIL] Total {len(all_findings)} contamination(s) found\n")
        by_type = {}
        for f in all_findings:
            t = f["type"]
            by_type.setdefault(t, []).append(f)

        for type_key, findings in by_type.items():
            print(f"  {CONTAMINATION_TYPE_NAMES[type_key]}: {len(findings)}")
            for f in findings[:3]:
                print(f"    {f['file']}:{f['line']}")
                print(f"    → {f['detail'][:60]}")

        restore_prompt = generate_restore_prompt(all_findings, ctx)
        print(f"\n{'─'*60}")
        print(restore_prompt)

    print("="*60)

    # Save results
    result = {
        "total_findings": len(all_findings),
        "findings": all_findings[:30],
        "by_type": {
            k: len([f for f in all_findings if f["type"] == k])
            for k in ["A_policy", "B_component", "C_state", "D_boundary"]
        },
        "restore_prompt": generate_restore_prompt(all_findings, ctx),
        "timestamp": datetime.now().isoformat(),
    }

    result_path = root / ".duda" / "duda-audit-result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nResults saved: {result_path}")


if __name__ == "__main__":
    main()
