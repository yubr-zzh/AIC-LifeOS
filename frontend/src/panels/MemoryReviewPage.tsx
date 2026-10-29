import { useEffect, useMemo, useState } from "react";
import type { MemoryCandidate } from "../api/types";
import type { Store } from "../state/store";
import { commitMemoryCandidate } from "../api/client";
import { MarkdownEditor } from "../components/MarkdownEditor";
import { MemoryLibrary } from "../components/MemoryDrawer";

const RATING_LABEL: Record<string, string> = {
  just_right: "刚刚好",
  helpful: "有帮助",
  too_wordy: "太啰嗦",
  unclear: "不清楚",
  wrong: "不对",
  other: "其他",
};

/**
 * 候选正文。
 *
 * 反馈类候选没有 claim 字段，只有评分和附言——原来这种情况直接把整个
 * content 打成 JSON 当正文显示，界面上就是一坨原始数据。
 * content 可能是 null（新候选还没填），这里一并兜住。
 */
function claimOf(candidate: MemoryCandidate): string {
  const content = (candidate.content ?? {}) as Record<string, unknown>;
  const claim = content.claim;
  if (typeof claim === "string" && claim.trim()) return claim;
  const rating = content.rating;
  const note = content.note;
  if (typeof rating === "string" || typeof note === "string") {
    const label = typeof rating === "string" ? (RATING_LABEL[rating] ?? rating) : "未评分";
    const parts = [`评分：${label}`];
    if (typeof note === "string" && note.trim()) parts.push(note.trim());
    return parts.join("\n\n");
  }
  return JSON.stringify(content, null, 2);
}

/** 列表里用的一行摘要，永远不出现 JSON。 */
function summaryOf(candidate: MemoryCandidate): string {
  return claimOf(candidate).replace(/\s+/g, " ").trim();
}

const STATUS_LABEL: Record<string, string> = {
  candidate: "待审核",
  committed: "已并入",
  rejected: "已放弃",
};

/** 候选池每行左侧只留一个字：并入过就是“已”，其余都是“未”。 */
function statusShort(status: string): string {
  return status === "committed" ? "已" : "未";
}

/** 候选所属项目名；没有项目范围时退回范围类型，避免出现空标题。 */
function projectName(candidate: MemoryCandidate): string {
  const scope = candidate.scope;
  if (scope?.kind === "project" && scope.project_id) return scope.project_id;
  const fromContent = (candidate.content ?? {}).project_id;
  if (typeof fromContent === "string" && fromContent.trim()) return fromContent.trim();
  if (scope?.kind === "scenario") return scope.scenario_type ?? "场景";
  if (scope?.kind === "global") return "全局";
  return "未标注项目";
}

export function MemoryReviewPage({ store }: { store: Store }) {
  // state.memory 在后端还没返回时是 undefined，直接取 .candidates 会整页崩
  const candidates = store.state.memory?.candidates ?? [];
  const backend = store.state.ui.dataMode === "backend";
  const [activeId, setActiveId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  const active = useMemo(
    () => candidates.find((candidate) => candidate.id === activeId) ?? candidates[0] ?? null,
    [candidates, activeId],
  );

  // 换候选就换成该候选的正文；用户改过的草稿不跨候选带过去。
  useEffect(() => {
    setDraft(active ? claimOf(active) : "");
    setNotice(null);
  }, [active?.id]);

  const commit = async () => {
    if (!active) return;
    const claim = draft.trim();
    if (!claim) {
      setNotice({ tone: "error", text: "正文不能为空，先写一条要记住的结论。" });
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      await commitMemoryCandidate(active.id, { ...(active.content ?? {}), claim });
      await store.refreshAll();
      setNotice({ tone: "success", text: "已并入长期记忆，画像会跟着重建。" });
    } catch (error) {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  };

  return <div className="feedback-layout">
    <section className="content-card feedback-main">
      <MemoryLibrary />
      <details className="memory-pending">
        <summary>待审记忆候选</summary>
        <div className="memory-pending-body">
      <h2>{active ? "这条结论值得长期记住吗？" : "还没有待审核的记忆候选"}</h2>
      {active ? <>
        <p className="memory-meta">
          {STATUS_LABEL[active.status] ?? active.status}
          {active.confidence != null ? ` · 置信度 ${active.confidence}` : ""}
          {` · ${new Date(active.created_at).toLocaleString()}`}
        </p>
        <MarkdownEditor value={draft} onChange={setDraft} minHeight={280}
          ariaLabel="记忆候选正文编辑器"
          placeholder="写下你希望 LifeOS 长期记住的结论…支持 Markdown。" />
        <div className="editor-footer actions-only">
          <button className="green-button" onClick={() => void commit()}
            disabled={busy || !backend || active.status !== "candidate"}>
            {busy ? "并入中…" : "确认并入记忆"} <span>→</span>
          </button>
        </div>
        {!backend ? <p className="memory-note">预览模式不能写入记忆。</p> : null}
        {active.status !== "candidate" ? <p className="memory-note">这条候选的状态是{STATUS_LABEL[active.status] ?? active.status}，不能再并入。</p> : null}
        {notice ? <p className={`save-feedback ${notice.tone}`} role="status">{notice.text}</p> : null}
      </> : <p className="memory-note">先在右侧选一条候选；也可以去日记、复盘里提炼一条新的。</p>}
        </div>
      </details>
    </section>

    <aside className="content-card entry-history-card">
      <div className="entry-history-heading">
        <div><span className="card-kicker">候选池</span><h3>所有记忆候选</h3></div>
        <span className="soft-count">{candidates.length} 条</span>
      </div>
      {candidates.length === 0 ? <p className="entry-history-empty">还没有记忆候选。</p> : (
        <div className="entry-history-list">
          {candidates.map((candidate) => {
            const text = summaryOf(candidate);
            return <button key={candidate.id} type="button"
              className={`entry-history-item ${candidate.id === active?.id ? "active" : ""}`}
              onClick={() => setActiveId(candidate.id)}>
              <span className="entry-history-date">{statusShort(candidate.status)}</span>
              <strong>{projectName(candidate)}</strong>
              <small>{text.replace(/\s+/g, " ").slice(0, 64) || "暂无正文"}</small>
            </button>;
          })}
        </div>
      )}
    </aside>
  </div>;
}
