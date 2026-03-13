#!/usr/bin/env python3
"""
DUDA map_update.py — Partial re-fill after work
Re-tags only changed files and their upstream nodes. No full re-scan.

Usage:
  python map_update.py --diff              # Detect changes via git diff
  python map_update.py --files a.ts b.ts  # Specify files explicitly
  python map_update.py --full             # Full regeneration (forced)
"""

import re
import os
import json
import hashlib
import argparse
import subprocess
from pathlib import Path
from datetime import datetime


# -- Detect changed files via git diff ----------------------------------------

def get_changed_files(root: Path) -> list[Path]:
    """Return list of changed source files via git diff"""
    changed = []
    extensions = {".ts", ".tsx", ".js", ".jsx"}

    try:
        # Both staged + unstaged
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, cwd=root, timeout=10
        )
        for line in result.stdout.strip().split("\n"):
            if line and Path(line).suffix in extensions:
                full = root / line
                if full.exists():
                    changed.append(full)

        # Include untracked files
        result2 = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, cwd=root, timeout=10
        )
        for line in result2.stdout.strip().split("\n"):
            if line and Path(line).suffix in extensions:
                full = root / line
                if full.exists():
                    changed.append(full)

    except Exception as e:
        print(f"  Warning: git diff failed: {e}")

    return list(set(changed))


# -- Find upstream dependents (impact propagation scope) ----------------------

def find_dependents(
    changed_files: list[Path],
    all_files: list[Path],
    root: Path
) -> list[Path]:
    """
    Find upstream files that import the changed files.
    Only re-tag files within the change propagation scope.
    """
    changed_names = {f.stem for f in changed_files}
    changed_paths = {str(f.relative_to(root)) for f in changed_files}

    dependents = set()

    for file in all_files:
        if file in changed_files:
            continue
        try:
            content = file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        # Check if file imports any changed file
        import_matches = re.findall(
            r'import\s+.*?\s+from\s+[\'"]([^\'"]+)[\'"]', content
        )
        for imp in import_matches:
            imp_name = Path(imp).stem
            if imp_name in changed_names:
                dependents.add(file)
                break
            # Partial path matching
            for cp in changed_paths:
                if imp.replace("/", os.sep) in cp or cp.replace(os.sep, "/") in imp:
                    dependents.add(file)
                    break

    return list(dependents)


# -- Checksum update ----------------------------------------------------------

def update_checksums(
    map_content: str,
    root: Path,
    changed_files: list[Path]
) -> str:
    """Update checksums only for changed boundary files"""
    changed_rels = {str(f.relative_to(root)) for f in changed_files}

    def replace_checksum(match):
        rel_path = match.group(1).strip()
        old_cs = match.group(2).strip()
        if rel_path in changed_rels:
            full = root / rel_path
            if full.exists():
                new_cs = hashlib.sha256(full.read_bytes()).hexdigest()[:8]
                if new_cs != old_cs:
                    return f"  {rel_path}: {new_cs}"
        return match.group(0)

    updated = re.sub(
        r'^\s+(.+?):\s+([a-f0-9]{8})',
        replace_checksum,
        map_content,
        flags=re.MULTILINE
    )
    return updated


# -- Partial layer tag update -------------------------------------------------

def retag_files(
    files_to_retag: list[Path],
    root: Path,
    ctx: dict
) -> dict[str, str]:
    """Re-tag specified files only (reuses init.py logic)"""
    from init import (
        collect_source_files, extract_imports,
        topological_sort, determine_layer_tag,
        load_claude_context
    )

    # Full file list (for topological sort)
    all_files = collect_source_files(root)
    sorted_files = topological_sort(all_files, root)

    # Load existing tags (from map)
    existing_tags = {}
    map_path = root / "DUDA_MAP.md"
    if not map_path.exists():
        map_path = root / ".duda" / "duda-map.md"
    if map_path.exists():
        content = map_path.read_text(encoding="utf-8", errors="ignore")
        # Tag parsing (simplified)
        upper_matches = re.findall(r'^\s+(.+\.tsx?)', content, re.MULTILINE)
        for m in upper_matches:
            existing_tags[m.strip()] = ("SHARED", "existing")

    # Process only re-tag targets sequentially
    retag_results = {}
    files_to_retag_set = {str(f.relative_to(root)) for f in files_to_retag}

    for file in sorted_files:
        rel = str(file.relative_to(root))
        if rel not in files_to_retag_set:
            continue

        imports = extract_imports(file, root)
        tag, confidence = determine_layer_tag(
            file, root, imports, ctx,
            {k: v[0] if isinstance(v, tuple) else v
             for k, v in existing_tags.items()}
        )
        retag_results[rel] = (tag, confidence)
        existing_tags[rel] = (tag, confidence)

    return retag_results


# -- Stale detection ----------------------------------------------------------

def check_stale(root: Path, map_content: str) -> dict:
    """Evaluate how well the map reflects the current state"""
    # Current file count
    extensions = {".ts", ".tsx", ".js", ".jsx"}
    current_count = 0
    skip_dirs = {"node_modules", ".git", ".next", "dist", "build"}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fname in filenames:
            if Path(fname).suffix in extensions:
                current_count += 1

    # File count in the map
    total_match = re.search(r'total_files:\s*(\d+)', map_content)
    map_count = int(total_match.group(1)) if total_match else 0

    # Checksum verification
    checksum_matches = re.findall(
        r'^\s+(.+?):\s+([a-f0-9]{8})',
        map_content, re.MULTILINE
    )
    changed_boundaries = []
    for rel_path, expected_cs in checksum_matches:
        full = root / rel_path.strip()
        if full.exists():
            actual_cs = hashlib.sha256(full.read_bytes()).hexdigest()[:8]
            if actual_cs != expected_cs.strip():
                changed_boundaries.append(rel_path.strip())
        else:
            changed_boundaries.append(f"{rel_path.strip()} (deleted)")

    diff_ratio = abs(current_count - map_count) / max(map_count, 1)

    if changed_boundaries:
        freshness = "LOW"
        reason = f"Boundary file changes detected: {', '.join(changed_boundaries[:3])}"
    elif diff_ratio > 0.15:
        freshness = "MEDIUM"
        reason = f"File count changed ({map_count} -> {current_count})"
    elif diff_ratio > 0.05:
        freshness = "MEDIUM"
        reason = f"File count slightly changed ({map_count} -> {current_count})"
    else:
        freshness = "HIGH"
        reason = "No changes"

    return {
        "freshness": freshness,
        "reason": reason,
        "map_count": map_count,
        "current_count": current_count,
        "changed_boundaries": changed_boundaries,
    }


# -- Map update ---------------------------------------------------------------

def update_map(
    root: Path,
    changed_files: list[Path],
    retag_results: dict[str, str],
) -> str:
    """Partially update DUDA_MAP.md"""
    map_path = root / "DUDA_MAP.md"
    if not map_path.exists():
        map_path = root / ".duda" / "duda-map.md"

    content = map_path.read_text(encoding="utf-8", errors="ignore")

    # 1. Update checksums
    content = update_checksums(content, root, changed_files)

    # 2. Update file count
    current_count = sum(
        1 for _, _, files in os.walk(root)
        for f in files
        if Path(f).suffix in {".ts", ".tsx", ".js", ".jsx"}
        and "node_modules" not in _
    )
    content = re.sub(
        r'total_files:\s*\d+',
        f'total_files: {current_count}',
        content
    )

    # 3. Add confidence history entry
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    changed_count = len(changed_files)
    history_entry = f"| {now} | — | Partial re-fill: {changed_count} files updated |"
    content = re.sub(
        r'(\| \d{4}-\d{2}-\d{2}.*?\|.*?\n)(\Z|---)',
        r'\1' + history_entry + '\n' + r'\2',
        content,
        flags=re.DOTALL
    )

    # 4. Update generated date
    content = re.sub(
        r'generated:\s*.+',
        f'generated:   {now} (partial update)',
        content
    )

    map_path.write_text(content, encoding="utf-8")
    return str(map_path)


# -- Main ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="DUDA partial re-fill")
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument("--diff", action="store_true", help="Detect changes via git diff")
    parser.add_argument("--files", nargs="+", help="Specify files explicitly")
    parser.add_argument("--full", action="store_true", help="Full regeneration")
    parser.add_argument("--check-stale", action="store_true", help="Check staleness only")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    # Check staleness only
    if args.check_stale:
        map_path = root / "DUDA_MAP.md"
        if not map_path.exists():
            map_path = root / ".duda" / "duda-map.md"
        if not map_path.exists():
            print("No DUDA_MAP found -- init required")
            return

        content = map_path.read_text(encoding="utf-8", errors="ignore")
        stale = check_stale(root, content)

        icon = {"HIGH": "OK", "MEDIUM": "WARNING", "LOW": "STALE"}[stale["freshness"]]
        print(f"{icon} Map freshness: {stale['freshness']}")
        print(f"   {stale['reason']}")
        if stale["changed_boundaries"]:
            print(f"   Changed boundary files: {', '.join(stale['changed_boundaries'][:3])}")
        return

    # Full regeneration
    if args.full:
        print("Full regeneration -- running init.py")
        import subprocess
        subprocess.run(
            ["python", str(root / ".duda/skills/duda/scripts/init.py"),
             "--root", str(root), "--update"]
        )
        return

    # Collect changed files
    changed_files = []
    if args.diff:
        print("Detecting changes via git diff...")
        changed_files = get_changed_files(root)
    elif args.files:
        changed_files = [Path(f) if Path(f).is_absolute() else root / f
                         for f in args.files]

    if not changed_files:
        print("No changed files -- map update not needed")
        return

    print(f"{len(changed_files)} changed file(s) detected:")
    for f in changed_files:
        print(f"  - {f.relative_to(root)}")

    # Find impact propagation scope
    from init import collect_source_files
    all_files = collect_source_files(root)

    print("\nSearching impact propagation scope...")
    dependents = find_dependents(changed_files, all_files, root)
    print(f"  {len(dependents)} upstream node(s) affected")

    files_to_retag = list(set(changed_files + dependents))
    print(f"  Total re-tag targets: {len(files_to_retag)}")
    print(f"  ({len(all_files) - len(files_to_retag)} of {len(all_files)} retained)")

    # Re-tag
    print("\nPartial re-fill in progress...")
    from init import load_claude_context
    ctx = load_claude_context(root)
    retag_results = retag_files(files_to_retag, root, ctx)

    # Update map
    map_path = update_map(root, changed_files, retag_results)

    print(f"\nPartial re-fill complete")
    print(f"  Updated: {len(retag_results)} file(s)")
    print(f"  Map: {map_path}")

    # Save summary
    summary = {
        "changed_files": [str(f.relative_to(root)) for f in changed_files],
        "retagged_files": len(retag_results),
        "total_files": len(all_files),
        "timestamp": datetime.now().isoformat(),
    }
    summary_path = root / ".duda" / "duda-update-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
