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
import re
import uuid
from copy import deepcopy
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
            entry_id = str(entry.get("id", ""))
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


def parse_markdown(text: str, existing_store: dict | None = None) -> dict:
    """Parse an edited Markdown document back into a memory store.

    Only the editable categories are reconstructed. Runtime sections are
    preserved from the existing store, and omitted categories are untouched.
    """
    empty = {
        "user": [],
        "project": [],
        "feedback": [],
        "reference": [],
        "candidates": [],
        "backups": [],
        "vector_index": {},
        "cache": {},
    }
    store = deepcopy(existing_store) if existing_store is not None else empty
    if not text.lstrip().startswith("# LifeOS Memory"):
        raise ValueError("not a LifeOS memory document")
    seen_categories = set()
    seen_ids = set()
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
                if name in seen_categories:
                    raise ValueError(f"duplicate memory category: {name}")
                seen_categories.add(name)
                store[name] = []
            else:
                current_category = None
            continue
        if line.startswith("### ") and current_category in CATEGORY_ORDER:
            match = re.fullmatch(r"\d+\.\s+(.+?)\s+-\s+(.+?)\s+\[source:\s*(.+?)\]", line[4:])
            if match is None:
                raise ValueError("invalid memory entry header")
            entry_id, created_at, source = match.groups()
            if existing_store and len(entry_id) == 8:
                matches = [
                    item["id"] for category in CATEGORY_ORDER
                    for item in existing_store.get(category, [])
                    if item.get("id", "").startswith(entry_id)
                ]
                if len(matches) != 1:
                    raise ValueError(f"ambiguous legacy memory id: {entry_id}")
                entry_id = matches[0]
            if not entry_id:
                entry_id = str(uuid.uuid4())
            if entry_id in seen_ids:
                raise ValueError(f"duplicate memory id: {entry_id}")
            seen_ids.add(entry_id)
            previous = next(
                (
                    item for category in CATEGORY_ORDER
                    for item in (existing_store or {}).get(category, [])
                    if item.get("id") == entry_id
                ),
                {},
            )
            entry = {**previous, "id": entry_id, "source": source, "content": {}, "created_at": created_at}
            current_entry = entry
            continue
        if line.startswith("```json"):
            if current_entry is None:
                raise ValueError("memory content has no entry header")
            in_json = True
            json_buffer = []
            continue
        if line.startswith("```") and in_json:
            in_json = False
            current_entry["content"] = json.loads("\n".join(json_buffer))
            if current_category and current_entry:
                store[current_category].append(current_entry)
            current_entry = None
            continue
        if in_json:
            json_buffer.append(line)

    if in_json or current_entry is not None or not seen_categories:
        raise ValueError("incomplete LifeOS memory document")
    all_ids = [
        entry["id"] for category in CATEGORY_ORDER for entry in store.get(category, [])
    ]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("duplicate memory id across categories")
    store["vector_index"] = {
        entry["id"]: entry["content"]
        for category in CATEGORY_ORDER for entry in store.get(category, [])
    }
    store["cache"] = {}
    return store
