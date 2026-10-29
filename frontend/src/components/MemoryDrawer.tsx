import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  getMemory,
  correctMemory,
  retractMemory,
  getMemoryMarkdown,
  importMemoryMarkdown,
} from "../api/client";
import type { MemoryEntry, MemoryStore } from "../api/types";

/**
 * 记忆抽屉。
 *
 * 骨架抄 Koder Design《AI memory drawer》：右侧滑入、搜索、分类 chips、
 * 分组列表、每条带来源与「引用 N 次」、行内编辑/删除、底部导出导入。
 * 颜色一律走现有 token，不引入新的色值。
 *
 * 数据的形状：后端 `/memory` 返回的是原始 store（user/project/feedback/reference
 * 四组），条目正文在 `content` 里（是个 dict，字段名不固定），所以这里做一层
 * 防御性取值——宁可显示摘要，也不要因为一个字段名对不上而整页空白。
 */

interface MemoryItem {
  id: string;
  category: string;
  text: string;
  source: string;
  scopeKind: string;
  projectId: string;
  scopeLabel: string;
  createdAt: string;
  usedCount: number;
  status: string;
}

const CATEGORY_LABEL: Record<string, string> = {
  user: "偏好",
  project: "项目",
  feedback: "反馈",
  reference: "参考",
};

const CATEGORY_ORDER = ["user", "project", "feedback", "reference"];

function pickText(entry: MemoryEntry): string {
  const raw: unknown = entry.content;
  if (typeof raw === "string" && raw.trim()) return raw.trim();
  const c = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  for (const key of ["text", "value", "content", "summary", "statement", "claim"]) {
    const v = c[key];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  const first = Object.values(c).find((v) => typeof v === "string" && v.trim());
  return typeof first === "string" ? first.trim() : "";
}

function toItems(store: MemoryStore | null | undefined): MemoryItem[] {
  const out: MemoryItem[] = [];
  try {
    if (!store || typeof store !== "object") return out;
    for (const category of CATEGORY_ORDER) {
      const list = (store as unknown as Record<string, MemoryEntry[]>)[category];
      if (!Array.isArray(list)) continue;
      for (const entry of list) {
        try {
          if (!entry || typeof entry.id !== "string") continue;
          const content = (entry.content ?? {}) as Record<string, unknown>;
          out.push({
            id: entry.id,
            category,
            text: pickText(entry),
            source: typeof entry.source === "string" ? entry.source : "—",
            scopeKind: typeof entry.scope?.kind === "string" ? entry.scope.kind : "unassigned",
            projectId: typeof entry.scope?.project_id === "string" ? entry.scope.project_id : "",
            scopeLabel: typeof entry.scope?.scenario_type === "string" ? entry.scope.scenario_type : "",
            createdAt: typeof entry.occurred_at === "string" ? entry.occurred_at : typeof content.created_at === "string" ? content.created_at : "",
            usedCount: Number((entry as unknown as { used_count?: number }).used_count ?? 0) || 0,
            status: typeof entry.status === "string" ? entry.status : "active",
          });
        } catch {
          // 单条数据形状不对就跳过这一条，不让它拖垮整个抽屉
        }
      }
    }
  } catch {
    return out;
  }
  return out;
}


export function MemoryDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<string>("all");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const load = useCallback(async () => {
    try {
      const raw = await getMemory();
      const store = (raw as unknown as { data?: MemoryStore })?.data ?? (raw as unknown as MemoryStore);
      setItems(toItems(store));
    } catch {
      setItems([]);
    }
  }, []);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const counts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const it of items) m[it.category] = (m[it.category] ?? 0) + 1;
    return m;
  }, [items]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items.filter((it) => {
      if (tab !== "all" && it.category !== tab) return false;
      if (!q) return true;
      return it.text.toLowerCase().includes(q);
    });
  }, [items, query, tab]);

  const total = items.length;
  const used = items.reduce((s, it) => s + it.usedCount, 0);

  const saveEdit = async (item: MemoryItem) => {
    setBusy(true);
    try {
      await correctMemory(item.id, { ...(item as unknown as { content?: Record<string, unknown> }).content, text: draft });
      setEditing(null);
      await load();
      setNote("已更新");
    } catch (e) {
      setNote(`更新失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (item: MemoryItem) => {
    if (!window.confirm("删除这条记忆？之后它不会再被用到。")) return;
    setBusy(true);
    try {
      await retractMemory(item.id);
      await load();
    } catch (e) {
      setNote(`删除失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const exportMd = async () => {
    setBusy(true);
    try {
      const res = await getMemoryMarkdown();
      const md = (res as unknown as { markdown?: string })?.markdown ?? "";
      const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "lifeos-memory.md";
      a.click();
      URL.revokeObjectURL(a.href);
      setNote("已导出 memory.md");
    } catch (e) {
      setNote(`导出失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  return (
    <div className="mem-drawer-root" role="dialog" aria-modal="true" aria-label="记忆">
      <button className="mem-drawer-backdrop" aria-label="关闭记忆" onClick={onClose} />
      <aside className="mem-drawer">
        <header className="mem-drawer-head">
          <strong>记忆</strong>
          <span className="mem-drawer-count">
            {total} 条{used > 0 ? ` · 引用 ${used} 次` : ""}
          </span>
          <button className="mem-drawer-close" onClick={onClose} aria-label="关闭" title="关闭">×</button>
        </header>

        <input
          className="mem-drawer-search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索记忆…"
          aria-label="搜索记忆"
        />

        <nav className="mem-drawer-tabs" aria-label="分类">
          <button className={tab === "all" ? "active" : ""} onClick={() => setTab("all")}>
            全部 <i>{total}</i>
          </button>
          {CATEGORY_ORDER.filter((c) => counts[c]).map((c) => (
            <button key={c} className={tab === c ? "active" : ""} onClick={() => setTab(c)}>
              {CATEGORY_LABEL[c]} <i>{counts[c]}</i>
            </button>
          ))}
        </nav>

        <div className="mem-drawer-list">
          {shown.length === 0 ? (
            <p className="mem-drawer-empty">没有匹配的记忆。</p>
          ) : (
            shown.map((it) => (
              <article key={it.id} className="mem-item">
                {editing === it.id ? (
                  <>
                    <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={3} aria-label="编辑记忆" />
                    <div className="mem-item-actions">
                      <button onClick={() => void saveEdit(it)} disabled={busy}>保存</button>
                      <button onClick={() => setEditing(null)}>取消</button>
                    </div>
                  </>
                ) : (
                  <>
                    <p className="mem-item-text">{it.text || "（无正文）"}</p>
                    <div className="mem-item-meta">
                      {it.scopeKind === "project" && it.projectId ? (
                        <span className="mem-item-scope mono" title="来源项目">{it.projectId}</span>
                      ) : null}
                      {it.scopeKind === "scenario" && it.scopeLabel ? (
                        <span className="mem-item-scope mono" title="来源场景">{it.scopeLabel}</span>
                      ) : null}
                      {it.createdAt ? <span className="mono">{String(it.createdAt).slice(0, 10)}</span> : null}
                      <span className="mem-item-used">引用 {it.usedCount} 次</span>
                    </div>
                    <div className="mem-item-actions">
                      <button
                        onClick={() => {
                          setEditing(it.id);
                          setDraft(it.text);
                        }}
                      >
                        编辑
                      </button>
                      <button className="danger" onClick={() => void remove(it)} disabled={busy}>删除</button>
                    </div>
                  </>
                )}
              </article>
            ))
          )}
        </div>

        <footer className="mem-drawer-foot">
          <button onClick={() => void exportMd()} disabled={busy}>导出 markdown</button>
          {note ? <span className="mem-drawer-note">{note}</span> : null}
        </footer>
      </aside>
    </div>
  );
}
