import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from lifeos.storage.sqlite import StructuredStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str, fallback: str = "untitled") -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|#\[\]]+", " ", value or "").strip()
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = cleaned.strip(".-")[:60]
    return cleaned or fallback


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        items = ", ".join(json.dumps(str(item), ensure_ascii=False) for item in value)
        return f"[{items}]"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return json.dumps(str(value), ensure_ascii=False)


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value in {"null", "None"}:
        return None
    if value in {"true", "false"}:
        return value == "true"
    if value.startswith("{") and value.endswith("}"):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else value
        except json.JSONDecodeError:
            return value
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("'\"") for item in inner.split(",")]
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        try:
            return json.loads(value) if value.startswith('"') else value[1:-1]
        except json.JSONDecodeError:
            return value.strip("'\"")
    return value


def _render_markdown(entry: Dict[str, Any]) -> str:
    metadata = entry.get("metadata") or {}
    tags = metadata.get("tags") if isinstance(metadata.get("tags"), list) else []
    frontmatter = {
        "lifeos_schema": 1,
        "lifeos_id": entry.get("id"),
        "lifeos_kind": entry.get("kind"),
        "title": entry.get("title") or "",
        "date": entry.get("entry_date"),
        "mood": entry.get("mood"),
        "tags": tags,
        "updated_at": entry.get("updated_at") or _now(),
        "lifeos_metadata": metadata,
    }
    lines = ["---"]
    lines.extend(f"{key}: {_yaml_scalar(value)}" for key, value in frontmatter.items())
    lines.append("---")
    lines.append("")
    title = entry.get("title") or "未命名记录"
    lines.extend([f"# {title}", "", entry.get("content") or ""])
    return "\n".join(lines).rstrip() + "\n"


def _parse_frontmatter(text: str) -> tuple[Dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, text
    metadata: Dict[str, Any] = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        metadata[key.strip()] = _parse_scalar(raw)
    body = "\n".join(lines[end + 1:]).lstrip("\n")
    return metadata, body


def _dedupe(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value).strip().lstrip("#")
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _strip_title_heading(body: str, title: str) -> str:
    lines = body.splitlines()
    heading = f"# {title}".strip()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if line.strip() == heading:
            return "\n".join(lines[index + 1:]).lstrip("\n")
        break
    return body


def _extract_body_metadata(body: str, kind: str) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    hashtags = re.findall(r"(?<!\w)#([\w\u4e00-\u9fff/-]+)", body)
    if hashtags:
        metadata["tags"] = _dedupe(hashtags)
    tasks = re.findall(r"^\s*-\s*\[[ xX]\]\s*(.+?)\s*$", body, flags=re.MULTILINE)
    if tasks:
        metadata["tasks"] = tasks
    intent_match = re.search(r"(?:今日意图|阶段命题|意图)\s*[:：]?\s*(.+)", body)
    if intent_match:
        metadata["intent"] = intent_match.group(1).strip()
    score_match = re.search(r"(?:自评|状态)\s*[:：]?\s*([1-5])\s*/\s*5", body)
    if score_match:
        metadata["score"] = int(score_match.group(1))
    if kind in {"daily_review", "phase_review"}:
        answers: list[str] = []
        sections = re.split(r"^##\s+", body, flags=re.MULTILINE)[1:]
        for section in sections:
            lines = section.splitlines()
            answer = "\n".join(lines[1:]).strip().strip("_")
            if answer:
                answers.append(answer)
        if answers:
            metadata["answers"] = answers
    return metadata


class VaultManager:
    """Local Obsidian Vault bridge for structured LifeOS entries.

    The manager only resolves relative paths under the configured vault root.
    It deliberately exposes a narrow Markdown-focused API instead of arbitrary
    filesystem access.
    """

    FOLDER_MAP = {
        "daily_plan": ("周期笔记", "Daily"),
        "daily_review": ("周期笔记", "Review"),
        "phase_plan": ("周期笔记", "Phase"),
        "phase_review": ("周期笔记", "Phase"),
        "diary": ("周期笔记", "Daily"),
        "insight": ("资源", "Insights"),
    }

    def __init__(
        self,
        settings_path: str | Path = ".lifeos/vault.json",
        structured_store: Optional[StructuredStore] = None,
    ):
        self.settings_path = Path(settings_path)
        self.structured_store = structured_store or StructuredStore()

    def _read_config(self) -> Dict[str, Any]:
        if not self.settings_path.exists():
            return {"vault_path": "", "folder": "LifeOS"}
        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"vault_path": "", "folder": "LifeOS"}
        return {
            "vault_path": str(payload.get("vault_path") or ""),
            "folder": str(payload.get("folder") or "LifeOS"),
        }

    def _write_config(self, config: Dict[str, Any]) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _root(self, required: bool = True) -> Optional[Path]:
        raw = self._read_config().get("vault_path", "")
        if not raw:
            if required:
                raise ValueError("Obsidian Vault 尚未配置")
            return None
        root = Path(raw).expanduser().resolve()
        if required and not root.is_dir():
            raise ValueError(f"Vault 路径不存在或不是目录: {root}")
        return root

    def _resolve_relative(self, relative_path: str) -> Path:
        root = self._root(required=True)
        candidate = (root / relative_path).resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("文件路径超出 Vault 目录")
        return candidate

    def _iter_markdown(self, limit: int = 500) -> Iterable[Path]:
        root = self._root(required=True)
        yielded = 0
        for path in root.rglob("*.md"):
            relative = path.relative_to(root)
            if any(part.startswith(".") for part in relative.parts):
                continue
            if not path.is_file():
                continue
            yield path
            yielded += 1
            if yielded >= max(1, min(limit, 5000)):
                break

    def status(self) -> Dict[str, Any]:
        config = self._read_config()
        raw = config.get("vault_path", "")
        if not raw:
            return {
                "configured": False,
                "path": "",
                "folder": config.get("folder", "LifeOS"),
                "exists": False,
                "file_count": 0,
            }
        root = Path(raw).expanduser().resolve()
        exists = root.is_dir()
        count = 0
        if exists:
            count = sum(1 for _ in self._iter_markdown(limit=5000))
        return {
            "configured": True,
            "path": str(root),
            "folder": config.get("folder", "LifeOS"),
            "exists": exists,
            "file_count": count,
        }

    def configure(self, vault_path: str, folder: str = "LifeOS") -> Dict[str, Any]:
        raw = (vault_path or "").strip()
        safe_folder = (folder or "LifeOS").strip().strip("/\\") or "LifeOS"
        if not raw:
            self._write_config({"vault_path": "", "folder": safe_folder})
            return self.status()
        root = Path(raw).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Vault 路径不存在或不是目录: {root}")
        self._write_config({"vault_path": str(root), "folder": safe_folder})
        return self.status()

    def list_files(self, query: str = "", limit: int = 100) -> list[Dict[str, Any]]:
        root = self._root(required=True)
        needle = (query or "").lower()
        files: list[Dict[str, Any]] = []
        for path in self._iter_markdown(limit=5000):
            relative = path.relative_to(root).as_posix()
            if needle and needle not in relative.lower():
                continue
            stat = path.stat()
            files.append({
                "path": relative,
                "name": path.name,
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            })
            if len(files) >= max(1, min(limit, 500)):
                break
        files.sort(key=lambda item: item["modified_at"], reverse=True)
        return files

    def read_file(self, relative_path: str) -> Dict[str, Any]:
        path = self._resolve_relative(relative_path)
        if not path.is_file():
            raise ValueError(f"Markdown 文件不存在: {relative_path}")
        text = path.read_text(encoding="utf-8", errors="replace")
        metadata, body = _parse_frontmatter(text)
        return {
            "path": relative_path,
            "metadata": metadata,
            "content": text,
            "body": body,
        }

    def _export_folder(self, kind: str, entry_date: str, folder: str) -> Path:
        category, subcategory = self.FOLDER_MAP.get(kind, ("记录", "Other"))
        year = (entry_date or _now())[:4]
        return Path(folder) / category / year / subcategory

    def export_entry(self, entry_id: str) -> Dict[str, Any]:
        if not entry_id:
            raise ValueError("entry_id is required")
        if self.structured_store is None:
            raise ValueError("structured store is unavailable")
        entry = self.structured_store.get(entry_id)
        if entry is None:
            raise ValueError(f"结构化记录不存在: {entry_id}")
        root = self._root(required=True)
        config = self._read_config()
        folder = self._export_folder(entry["kind"], entry["entry_date"], config["folder"])
        filename = f"{entry['entry_date']}-{entry['kind']}-{entry['id'][:8]}.md"
        target = (root / folder / filename).resolve()
        if target != root and root not in target.parents:
            raise ValueError("导出路径超出 Vault 目录")
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        metadata = dict(entry.get("metadata") or {})
        metadata["vault_path"] = target.relative_to(root).as_posix()
        metadata["vault_exported_at"] = _now()
        export_entry = {**entry, "metadata": metadata}
        target.write_text(_render_markdown(export_entry), encoding="utf-8")
        persisted = self.structured_store.upsert(
            {
                "kind": entry["kind"],
                "entry_date": entry["entry_date"],
                "title": entry.get("title") or "",
                "content": entry.get("content") or "",
                "mood": entry.get("mood"),
                "metadata": metadata,
            },
            entry_id=entry_id,
        )
        return {
            "entry_id": entry_id,
            "entry": persisted,
            "path": str(target),
            "relative_path": target.relative_to(root).as_posix(),
            "folder": folder.as_posix(),
            "filename": filename,
            "updated": existed,
        }

    def import_file(self, relative_path: str, kind: Optional[str] = None) -> Dict[str, Any]:
        if self.structured_store is None:
            raise ValueError("structured store is unavailable")
        path = self._resolve_relative(relative_path)
        if not path.is_file():
            raise ValueError(f"Markdown 文件不存在: {relative_path}")
        text = path.read_text(encoding="utf-8", errors="replace")
        frontmatter, body = _parse_frontmatter(text)
        entry_kind = str(frontmatter.get("lifeos_kind") or kind or "insight")
        if entry_kind not in self.structured_store.VALID_KINDS:
            raise ValueError(f"不支持记录类型: {entry_kind}")
        title = str(frontmatter.get("title") or "")
        if not title:
            for line in body.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
        if not title:
            title = path.stem
        entry_date = str(frontmatter.get("date") or datetime.now().date().isoformat())[:10]
        frontmatter_tags = frontmatter.get("tags")
        if not isinstance(frontmatter_tags, list):
            frontmatter_tags = []
        content = _strip_title_heading(body, title)
        stored_metadata = frontmatter.get("lifeos_metadata")
        if not isinstance(stored_metadata, dict):
            stored_metadata = {}
        stored_tags = stored_metadata.get("tags")
        if not isinstance(stored_tags, list):
            stored_tags = []
        extracted = _extract_body_metadata(content, entry_kind)
        extracted_tags = extracted.get("tags")
        if not isinstance(extracted_tags, list):
            extracted_tags = []
        metadata = {
            **stored_metadata,
            **extracted,
            "vault_path": path.relative_to(self._root(required=True)).as_posix(),
            "vault_imported_at": _now(),
            "tags": _dedupe([*frontmatter_tags, *extracted_tags, *stored_tags]),
        }
        entry = self.structured_store.upsert(
            {
                "kind": entry_kind,
                "entry_date": entry_date,
                "title": title,
                "content": content,
                "mood": frontmatter.get("mood"),
                "metadata": metadata,
            },
            entry_id=str(frontmatter.get("lifeos_id") or "") or None,
        )
        return {"entry": entry, "relative_path": metadata["vault_path"]}

    def sync_entry(self, entry_id: str) -> Dict[str, Any]:
        entry = self.structured_store.get(entry_id)
        if entry is None:
            raise ValueError(f"结构化记录不存在: {entry_id}")
        relative_path = str((entry.get("metadata") or {}).get("vault_path") or "")
        if not relative_path:
            raise ValueError("该记录还没有关联 Vault Markdown 文件")
        return self.import_file(relative_path, kind=entry["kind"])
