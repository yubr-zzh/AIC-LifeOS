"""Markdown export / import for the LifeOS memory store.

The memory store is JSON internally, but the project's knowledge
management story is "readable, editable, auditable". This module
renders the store to a human-friendly Markdown file (memory.md) and
parses an edited Markdown document back into the store, so users can
review and edit long-term memory with any text editor.

Format:

    # LifeOS Memory

    ## user (2)

    ### 1. ab12cd34 - 2026-08-26T... [source: direct]

    ```json
    {"preference": "keep answers short"}
    ```
"""

import json
from datetime import datetime

# Categories rendered as Markdown sections, in display order.
CATEGORY_ORDER = ["user", "project", "feedback", "reference"]

# System-only sections that are preserved on import but not rendered
# as editable content (candidates / backups / vector index / cache).
_SYSTEM_SECTIONS = ["candidates", "backups", "vector_index", "cache"]


def render_markdown(store: dict) -> str:
    """Render a memory store dict to Markdown text."""
    lines = [
        "# LifeOS Memory",
        "",
        "导出时间: " + datetime.utcnow().isoformat(),
        "",
        "> 本文件由 LifeOS 自动生成。编辑后可通过导入接口写回 memory.json。",
        "",
    ]
    for category in CATEGORY_ORDER:
        entries = store.get(category, []) or []
        lines.append("## " + category + " (" + str(len(entries)) + ")")
        lines.append("")
        if not entries:
            lines.append("_（空）_")
            lines.append("")
            continue
        for index, entry in enumerate(entries, 1):
            entry_id = str(entry.get("id", ""))[:8]
            created = entry.get("created_at", "")
            source = entry.get("source", "")
            lines.append("### " + str(index) + ". " + entry_id + " - " + created + " [source: " + source + "]")
            lines.append("")
            content = entry.get("content", {})
            lines.append("```json")
            lines.append(json.dumps(content, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")
    return "\n".join(lines)


def parse_markdown(text: str) -> dict:
    """Parse an edited Markdown document back into a memory store.

    Only the editable categories (user / project / feedback / reference)
    are reconstructed; system sections are reset to empty. Entries keep
    their id / created_at / source when the header lines are intact.
    """
    store = {
        "user": [],
        "project": [],
        "feedback": [],
        "reference": [],
        "candidates": [],
        "backups": [],
        "vector_index": {},
        "cache": {},
    }
    current_category = None
    current_entry = None
    in_json = False
    json_buffer = []

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            name = line[3:].split(" ")[0]
            if name in CATEGORY_ORDER:
                current_category = name
            else:
                current_category = None
            continue
        if line.startswith("### ") and current_category in CATEGORY_ORDER:
            header = line[4:]
            entry = {"id": "", "source": "", "content": {}, "created_at": ""}
            # header: "1. ab12cd34 - 2026-... [source: direct]"
            rest = header
            if "] " in rest or "]" in rest:
                left, _, right = rest.rpartition("[source: ")
                source = right.rstrip("]")
                entry["source"] = source
                rest = left
            if " - " in rest:
                left, _, right = rest.rpartition(" - ")
                entry["created_at"] = right.strip()
                rest = left
            # "1. ab12cd34" -> id = second token
            parts = rest.split(".")
            if len(parts) >= 2:
                entry["id"] = parts[1].strip()
            current_entry = entry
            continue
        if line.startswith("```json"):
            in_json = True
            json_buffer = []
            continue
        if line.startswith("```") and in_json:
            in_json = False
            try:
                current_entry["content"] = json.loads("\n".join(json_buffer))
            except json.JSONDecodeError:
                current_entry["content"] = {"raw": "\n".join(json_buffer)}
            if current_category and current_entry:
                store[current_category].append(current_entry)
            current_entry = None
            continue
        if in_json:
            json_buffer.append(line)

    return store
