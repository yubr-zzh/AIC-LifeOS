import { useEffect, useMemo, useState } from "react";
import type { MemoryCandidate } from "../api/types";
import type { Store } from "../state/store";
import { commitMemoryCandidate } from "../api/client";
import { MarkdownEditor } from "../components/MarkdownEditor";

function claimOf(candidate: MemoryCandidate): string {
  const claim = candidate.content.claim;
  return typeof claim === "string" ? claim : JSON.stringify(candidate.content, null, 2);
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
  const fromContent = candidate.content.project_id;
  if (typeof fromContent === "string" && fromContent.trim()) return fromContent.trim();
  if (scope?.kind === "scenario") return scope.scenario_type ?? "场景";
  if (scope?.kind === "global") return "全局";
  return "未标注项目";
}

export function MemoryReviewPage({ store }: { store: Store }) {
  const candidates = store.state.memory.candidates;
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
      await commitMemoryCandidate(active.id, { ...active.content, claim });
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
      <span className="card-kicker">记忆候选</span>
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
    </section>

    <aside className="content-card entry-history-card">
      <div className="entry-history-heading">
        <div><span className="card-kicker">候选池</span><h3>所有记忆候选</h3></div>
        <span className="soft-count">{candidates.length} 条</span>
      </div>
      {candidates.length === 0 ? <p className="entry-history-empty">还没有记忆候选。</p> : (
        <div className="entry-history-list">
          {candidates.map((candidate) => {
            const text = claimOf(candidate);
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
