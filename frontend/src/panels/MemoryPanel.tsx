import { useCallback, useEffect, useState } from "react";
import type { LifecycleStage, MemoryCandidate, MemoryEntry } from "../api/types";
import { LIFECYCLE_STAGES } from "../api/types";
import type { Store } from "../state/store";
import {
  correctMemory,
  getMemoryProfile,
  getMemoryMarkdown,
  importMemoryMarkdown,
  retractMemory,
} from "../api/client";
import { IconApprove, IconReject, IconCheck } from "../components/Icons";

type Tab =
  | "user"
  | "project"
  | "feedback"
  | "reference"
  | "candidates"
  | "profile"
  | "backups"
  | "markdown";

const TABS: { id: Tab; label: string }[] = [
  { id: "candidates", label: "候选" },
  { id: "user", label: "User" },
  { id: "project", label: "Project" },
  { id: "feedback", label: "Feedback" },
  { id: "reference", label: "Reference" },
  { id: "profile", label: "画像" },
  { id: "backups", label: "Backups" },
  { id: "markdown", label: "Markdown" },
];

interface Props {
  store: Store;
}

export function MemoryPanel({ store }: Props) {
  const { state } = store;
  const [tab, setTab] = useState<Tab>("candidates");
  const mem = state.memory;

  return (
    <section className="mem-panel">
      <header className="mem-head">
        <p>候选审核 · 生命周期 · 纠正 / 撤回 · 画像重建 · Markdown 镜像。</p>
        <span className="mem-mode">{state.ui.dataMode === "backend" ? "实时后端" : "本地预览"}</span>
      </header>

      <div className="mem-tabs" role="tablist">
        {TABS.map((t) => {
          const active = tab === t.id;
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={active}
              className={`mem-tab ${active ? "is-active" : ""}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
              {t.id === "candidates" && mem.candidates.length > 0 ? (
                <span className="mem-tab-count">{mem.candidates.length}</span>
              ) : null}
            </button>
          );
        })}
      </div>

      <div className="mem-body">
        {tab === "user" ? <EntryList entries={mem.user} empty="还没有 User 记忆" store={store} /> : null}
        {tab === "project" ? <EntryList entries={mem.project} empty="还没有 Project 记忆" store={store} /> : null}
        {tab === "feedback" ? <EntryList entries={mem.feedback} empty="还没有 Feedback 记忆" store={store} /> : null}
        {tab === "reference" ? <EntryList entries={mem.reference} empty="还没有 Reference 记忆" store={store} /> : null}
        {tab === "markdown" ? <MarkdownTab store={store} /> : null}
        {tab === "profile" ? <ProfileTab /> : null}
        {tab === "candidates" ? <CandidateList candidates={mem.candidates} store={store} /> : null}
        {tab === "backups" ? <BackupsTab items={mem.backups} /> : null}
      </div>
    </section>
  );
}

function BackupsTab({ items }: { items: { created_at: string }[] }) {
  if (items.length === 0) {
    return <p className="mem-empty">还没有备份。</p>;
  }
  return (
    <ol className="mem-backup-list" reversed>
      {items.map((b, i) => (
        <li key={i}>
          <span className="mono mem-backup-idx">#{items.length - i}</span>
          <time className="mono muted" dateTime={b.created_at}>
            {new Date(b.created_at).toLocaleString()}
          </time>
        </li>
      ))}
    </ol>
  );
}

function ProfileTab() {
  const [result, setResult] = useState<Awaited<ReturnType<typeof getMemoryProfile>> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const load = useCallback(() => {
    setLoading(true); setError("");
    getMemoryProfile()
      .then(setResult).catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);
  useEffect(load, [load]);
  const view = result?.data;
  return (
    <div className="mem-profile">
      <div className="mem-profile-head">
        <span className="muted small">由 active memory 动态重建 · {result?.source === "backend" ? "实时后端" : "预览数据"}{view?.version ? ` · ${view.version.slice(0, 12)}` : ""}</span>
        <button className="ghost sm" onClick={load} disabled={loading}>{loading ? "读取中…" : "刷新画像"}</button>
      </div>
      {error ? <div className="state-error" role="alert">画像读取失败：{error}</div> : null}
      {loading && !view ? <p className="mem-empty">正在从当前记忆重建画像…</p> : null}
      {view ? (
        <>
          <ProfileGroups title="全局核心画像" groups={view.core_profiles} />
          <ProfileGroups title="场景画像" groups={view.scenario_profiles} />
          <ProfileGroups title="项目画像" groups={view.project_profiles} />
          {view.core_profiles.length + view.scenario_profiles.length + view.project_profiles.length === 0
            ? <p className="mem-empty">当前没有可展示的 active 记忆。先在候选页审核并采纳。</p>
            : null}
        </>
      ) : null}
    </div>
  );
}

function ProfileGroups({ title, groups }: { title: string; groups: import("../api/types").MemoryProfileGroup[] }) {
  if (!groups.length) return null;
  return (
    <section className="mem-profile-group">
      <h3>{title}</h3>
      {groups.map((group, index) => (
        <div key={`${group.scope.kind}-${group.scope.project_id ?? group.scope.scenario_type ?? index}`} className="mem-card">
          <div className="mem-card-head">
            <strong>{scopeLabel(group.scope)}</strong>
            <span className="muted small mono">{group.memory_count} 条依据</span>
          </div>
          {group.memories.map((memory) => (
            <div key={memory.id} className="mem-card-row">
              <div className="mem-card-claim">{claimText(memory.content)}</div>
              <Provenance item={memory} />
            </div>
          ))}
        </div>
      ))}
    </section>
  );
}

function scopeLabel(scope?: import("../api/types").MemoryScope) {
  if (!scope) return "范围未标注";
  if (scope.kind === "global") return "全局";
  if (scope.kind === "scenario") return `场景 · ${scope.scenario_type ?? "未命名"}`;
  if (scope.kind === "project") return `项目 · ${scope.project_id ?? "未命名"}`;
  return "未分配";
}

function claimText(content: Record<string, unknown>) {
  return typeof content.claim === "string" ? content.claim : JSON.stringify(content);
}

function Provenance({ item }: { item: Pick<MemoryCandidate, "source" | "source_ref" | "scope" | "confidence" | "confidence_method" | "occurred_at" | "created_at"> }) {
  const ref = item.source_ref;
  return (
    <div className="mem-provenance muted small">
      来源：{ref ? `${ref.kind} / ${ref.record_kind ?? "record"} / ${ref.record_id}` : item.source}{ref?.revision ? ` · 版本 ${ref.revision}` : ""}
      {` · ${scopeLabel(item.scope)}`}
      {item.occurred_at ? ` · 发生于 ${item.occurred_at}` : ""}
      {item.confidence != null ? ` · 置信度 ${item.confidence}${item.confidence_method ? `（${item.confidence_method}）` : ""}` : ""}
    </div>
  );
}

function MarkdownTab({ store }: { store: Store }) {
  const [md, setMd] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [message, setMessage] = useState("");

  const load = useCallback(() => {
    setStatus("loading");
    getMemoryMarkdown()
      .then((r) => { setMd(r.markdown); setStatus("idle"); })
      .catch((e) => { setStatus("error"); setMessage(e instanceof Error ? e.message : String(e)); });
  }, []);

  useEffect(load, [load]);

  const save = () => {
    importMemoryMarkdown(md)
      .then((r) => {
        setMessage(`imported — user:${r.categories.user} project:${r.categories.project} feedback:${r.categories.feedback} reference:${r.categories.reference}`);
        void store.refreshAll();
      })
      .catch((e) => { setMessage(`import failed: ${e instanceof Error ? e.message : String(e)}`); });
  };

  return (
    <div className="mem-markdown">
      <div className="mem-markdown-actions">
        <button className="ghost sm" onClick={load} disabled={status === "loading"}>Refresh</button>
        <button className="ghost sm" onClick={save}>Import edited markdown</button>
        {message ? <span className="muted small mono">{message}</span> : null}
      </div>
      <textarea
        className="mono mem-markdown-area"
        value={md}
        onChange={(e) => setMd(e.target.value)}
        placeholder={status === "error" ? `failed to load: ${message}` : "loading markdown…"}
        spellCheck={false}
      />
      <p className="muted small">memory.md mirror — review and import; existing memory must use explicit correction or retraction</p>
    </div>
  );
}

function EntryList({ entries, empty, store }: { entries: MemoryEntry[]; empty: string; store: Store }) {
  if (entries.length === 0) return <p className="mem-empty">{empty}</p>;
  return (
    <ul className="mem-entry-list">
      {entries.map((e) => <li key={e.id}><MemoryEntryCard entry={e} store={store} /></li>)}
    </ul>
  );
}

function MemoryEntryCard({ entry, store }: { entry: MemoryEntry; store: Store }) {
  const [editing, setEditing] = useState(false);
  const [confirmRetract, setConfirmRetract] = useState(false);
  const [content, setContent] = useState(JSON.stringify(entry.content, null, 2));
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const active = (entry.status ?? "active") === "active";
  const backend = store.state.ui.dataMode === "backend";

  const submitCorrection = async () => {
    let parsed: unknown;
    try { parsed = JSON.parse(content); } catch { setMessage("内容必须是有效 JSON。"); return; }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      setMessage("新记忆内容必须是 JSON 对象。"); return;
    }
    setBusy(true); setMessage("");
    try {
      await correctMemory(entry.id, parsed as Record<string, unknown>, reason || undefined);
      await store.refreshAll();
      setEditing(false);
      setMessage("已保存为新版本；旧版本保留但不再参与召回。");
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  };

  const submitRetraction = async () => {
    setBusy(true); setMessage("");
    try {
      await retractMemory(entry.id, reason || undefined);
      await store.refreshAll();
      setConfirmRetract(false);
      setMessage("已撤回；这条记忆将不再用于后续召回，来源记录未删除。");
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  };

  return (
    <article className={`mem-card ${active ? "is-active" : "is-retracted"}`}>
      <header className="mem-card-head">
        <span className="mem-source">{entry.source}</span>
        <span className={`mem-pill ${active ? "is-active" : "is-retracted"}`}>
          {active ? <IconCheck size={11} /> : <IconReject size={11} />}
          {entry.status ?? "active"}
        </span>
        <time className="muted small mono" dateTime={entry.created_at}>
          {new Date(entry.created_at).toLocaleString()}
        </time>
      </header>
      <pre className="mem-claim">{JSON.stringify(entry.content, null, 2)}</pre>
      <Provenance item={entry} />
      {entry.version_of ? <p className="muted small">corrects <span className="mono">{entry.version_of}</span></p> : null}
      {entry.superseded_by ? <p className="muted small">superseded by <span className="mono">{entry.superseded_by}</span></p> : null}
      {entry.trace_id ? <p className="muted small">trace <span className="mono">{entry.trace_id}</span></p> : null}
      {active ? (
        <div className="mem-card-actions">
          <button className="ghost sm" disabled={!backend || busy} onClick={() => { setEditing(!editing); setConfirmRetract(false); setReason(""); setMessage(""); }}>
            {editing ? "取消纠正" : "纠正记忆"}
          </button>
          <button className="ghost sm danger" disabled={!backend || busy} onClick={() => { setConfirmRetract(!confirmRetract); setEditing(false); setReason(""); setMessage(""); }}>
            撤回记忆
          </button>
          {!backend ? <span className="muted small mono">预览模式不可修改</span> : null}
        </div>
      ) : null}
      {editing ? (
        <div className="mem-edit">
          <label className="muted small mono">新版本内容预览（JSON）</label>
          <textarea className="mono mem-edit-area" value={content} onChange={(event) => setContent(event.target.value)} spellCheck={false} />
          <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="纠正原因（可选）" />
          <div className="mem-edit-actions">
            <button disabled={busy} onClick={() => void submitCorrection()}>{busy ? "保存中…" : "确认保存为新版本"}</button>
            <span className="muted small mono">旧版本会保留为历史记录，但退出召回。</span>
          </div>
        </div>
      ) : null}
      {confirmRetract ? (
        <div className="mem-confirm">
          <strong>确认撤回这条记忆？</strong>
          <span className="muted small">撤回后不再参与召回和画像；原始来源与审计记录会保留。此操作不是彻底删除。</span>
          <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="撤回原因（可选）" />
          <div className="mem-edit-actions">
            <button className="danger" disabled={busy} onClick={() => void submitRetraction()}>{busy ? "处理中…" : "我确认撤回"}</button>
            <button className="ghost sm" disabled={busy} onClick={() => setConfirmRetract(false)}>取消</button>
          </div>
        </div>
      ) : null}
      {message ? <div className="muted small mem-message" role="status">{message}</div> : null}
    </article>
  );
}

function CandidateList({ candidates, store }: { candidates: MemoryCandidate[]; store: Store }) {
  if (candidates.length === 0)
    return <p className="mem-empty">还没有候选记忆 — 跑一次对话再 <span className="mono">run BG once</span>，会从这里冒出来。</p>;
  return (
    <ul className="mem-entry-list">
      {candidates.map((c) => <li key={c.id}><CandidateCard c={c} store={store} /></li>)}
    </ul>
  );
}

function CandidateCard({ c, store }: { c: MemoryCandidate; store: Store }) {
  const inProject = store.state.memory.project.some((p) => p.id === c.id);
  let stages: LifecycleStage[] = ["candidate"];
  if (c.status === "rejected") {
    stages = ["candidate"];
  } else if (c.status === "committed" || inProject) {
    stages = ["candidate", "validated", "backed_up", "applied", "vector_upserted", "cache_invalidated"];
  }

  const tone = c.status === "committed" ? "is-committed" : c.status === "rejected" ? "is-rejected" : "is-pending";
  const backend = store.state.ui.dataMode === "backend";

  return (
    <article className={`mem-card mem-candidate ${tone}`}>
      <header className="mem-card-head">
        <span className="mem-source">{c.source}</span>
        <span className={`mem-pill ${tone}`}>{c.status}</span>
        <span className="muted small mono mem-candidate-id">{c.id.slice(0, 13)}…</span>
      </header>
      <pre className="mem-claim">{JSON.stringify(c.content, null, 2)}</pre>
      <Provenance item={c} />
      <div className="mem-lifecycle" aria-label="lifecycle">
        {LIFECYCLE_STAGES.map((s, i) => (
          <span key={s} className={`mem-stage ${stages.includes(s) ? "is-done" : "is-pending"}`}>
            <span className="mem-stage-dot" />
            <span className="mem-stage-label">{s}</span>
            {i < LIFECYCLE_STAGES.length - 1 ? <span className="mem-stage-bar" /> : null}
          </span>
        ))}
      </div>
      {c.status === "candidate" ? (
        <div className="mem-card-actions">
          <button disabled={!backend} onClick={() => void store.approveCandidate(c.id)} title="Commit memory candidate">
            <span className="row" style={{ gap: 6 }}>
              <IconApprove size={11} /> Approve
            </span>
          </button>
          <button className="ghost danger" disabled={!backend} onClick={() => void store.rejectCandidate(c.id)}>
            <span className="row" style={{ gap: 6 }}>
              <IconReject size={11} /> Reject
            </span>
          </button>
          <span className="muted small mono">{backend ? "saved by backend" : "preview data — actions unavailable"}</span>
        </div>
      ) : null}
    </article>
  );
}
