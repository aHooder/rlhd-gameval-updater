#!/usr/bin/env python3
import json
import subprocess
import sys
import os
import re
from pathlib import Path
from typing import Dict, Set

REPO_GAMEVALS_PATH = Path(os.environ["GAMEVALS_PATH"])
NEW_GAMEVALS_PATH = Path(sys.argv[1])

STRING_RE = re.compile(r'"([^"]+)"')

def strip_comments(text: str) -> str:
    if text.startswith("//"):
        return "\n".join(text.split("\n")[1:])
    return text

def load_json(path: Path) -> Dict:
    return json.loads(strip_comments(path.read_text(encoding="utf-8")))

def load_old_gamevals() -> Dict:
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD:{REPO_GAMEVALS_PATH}"],
            capture_output=True,
            text=True,
            check=True
        )
        return json.loads(strip_comments(result.stdout))
    except subprocess.CalledProcessError:
        return {}

def flatten(gamevals: Dict[str, Dict[str, int]]) -> Dict[str, int]:
    flat = {}
    for category in gamevals.values():
        flat.update(category)
    return flat

def invert(flat: Dict[str, int]) -> Dict[int, Set[str]]:
    inv: Dict[int, Set[str]] = {}
    for name, id_val in flat.items():
        inv.setdefault(id_val, set()).add(name)
    return inv

def format_line(change_type: str, name: str, id_val: int, new_name: str = None) -> str:
    if change_type == "added":
        return f"+{name}"
    if change_type == "removed":
        return f"-{name}"
    if change_type == "renamed":
        return f"!{name} → {new_name}"
    return name

def compute_changes(old, new):
    """
    Returns:
    {
        category: [
            (type, name, id, new_name)
        ]
    }
    """
    result = {}

    categories = set(old) | set(new)

    for cat in categories:
        old_map = old.get(cat, {})
        new_map = new.get(cat, {})

        changes = []

        # Build ID -> names (per category)
        def invert(d):
            inv = {}
            for name, id_val in d.items():
                inv.setdefault(id_val, set()).add(name)
            return inv

        old_ids = invert(old_map)
        new_ids = invert(new_map)

        renamed_ids = set()

        # Renames (same ID, different names)
        for id_val in old_ids.keys() & new_ids.keys():
            old_names = old_ids[id_val]
            new_names = new_ids[id_val]

            if old_names != new_names:
                renamed_ids.add(id_val)

                for o in old_names - new_names:
                    for n in new_names - old_names:
                        changes.append(("renamed", o, id_val, n))

        # Removed
        for name, id_val in old_map.items():
            if id_val in renamed_ids:
                continue
            if name not in new_map:
                changes.append(("removed", name, id_val, None))

        # Added
        for name, id_val in new_map.items():
            if name not in old_map:
                changes.append(("added", name, id_val, None))

        if changes:
            result[cat] = changes

    return result

def find_json_files():
    return [
        p for p in Path(".").rglob("*.json")
        if p.name != "gamevals.json" and not p.name.endswith('.schema.json')
    ]

def scan_usage(names: Set[str]):
    usage = {}
    used_names = set()

    for path in find_json_files():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue


        file_hits = {}

        for i, line in enumerate(lines, start=1):
            if '"' not in line:
                continue
            # extract all quoted strings once
            for match in STRING_RE.findall(line):
                if match in names:
                    file_hits.setdefault(match, []).append(i)
                    used_names.add(match)

        if file_hits:
            usage[path.name] = file_hits

    return usage, used_names

def generate_report(changes, usage, used_names):
    lines = []

    if usage:
        lines.extend([ "Includes potentially breaking changes for the following files:" ])

        for file, matches in usage.items():
            lines.extend([
                "<details>",
                f"<summary><code>{file}</code></summary>",
                "",
                "```diff"
            ])

            for cat, cat_changes in changes.items():
                for change_type, name, id_val, new_name in cat_changes:
                    if name not in matches:
                        continue

                    line_nums = ", ".join(map(str, matches[name]))
                    formatted = format_line(change_type, name, id_val, new_name)
                    lines.append(f"{formatted} (lines: {line_nums})")

            lines.extend(["```", "</details>", ""])
    else:
        lines.append("No potentially breaking changes detected.")

    return "\n".join(lines)

def main():
    old = load_old_gamevals()
    new = load_json(NEW_GAMEVALS_PATH)

    changes = compute_changes(old, new)

    names_to_check = {
        name
        for cat_changes in changes.values()
        for (change_type, name, _, _) in cat_changes
    }
    usage, used_names = scan_usage(names_to_check)

    report = generate_report(changes, usage, used_names)
    print(report)

if __name__ == "__main__":
    main()
