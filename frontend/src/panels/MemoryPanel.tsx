import React, { useCallback, useEffect, useState } from "react";
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
import { Panel } from "../components/Panel";
import { IconApprove, IconReject } from "../components/Icons";

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
  { id: "user", label: "关于我" },
  { id: "project", label: "项目" },
  { id: "feedback", label: "反馈" },
  { id: "reference", label: "参考" },
  { id: "candidates", label: "待确认" },
  { id: "profile", label: "画像" },
  { id: "backups", label: "历史版本" },
  { id: "markdown", label: "记忆文件" },
];

interface Props {
  store: Store;
}

export function MemoryPanel({ store }: Props) {
  const { state } = store;
  const [tab, setTab] = useState<Tab>("candidates");
  const mem = state.memory;

  return (
    <Panel
      title="我的记忆"
      subtitle="LifeOS 从你的记录中沉淀出的长期认知；每一条都可以查看依据、修改或撤回。"
      source={state.ui.dataMode}
      dense
    >
      <div className="row" style={{ gap: 4, padding: "0 6px 8px", flexWrap: "wrap" }}>
        {TABS.map((t) => {
          const active = tab === t.id;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={active ? "primary" : "ghost"}
              style={{ borderRadius: "var(--r-pill)", padding: "3px 10px", fontSize: 11 }}
            >
              {t.label}
              {t.id === "candidates" && mem.candidates.length > 0 ? (
                <span className="mono" style={{ marginLeft: 6, opacity: 0.8 }}>
                  {mem.candidates.length}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      {tab === "user" ? <EntryList entries={mem.user} empty="还没有关于你的长期记忆。" store={store} /> : null}
      {tab === "project" ? <EntryList entries={mem.project} empty="还没有项目记忆。" store={store} /> : null}
      {tab === "feedback" ? <EntryList entries={mem.feedback} empty="还没有从反馈中整理出的记忆。" store={store} /> : null}
      {tab === "reference" ? <EntryList entries={mem.reference} empty="还没有保存的参考信息。" store={store} /> : null}
      {tab === "markdown" ? <MarkdownTab store={store} /> : null}
      {tab === "profile" ? <ProfileTab /> : null}
      {tab === "candidates" ? (
        <CandidateList candidates={mem.candidates} store={store} />
      ) : null}
      {tab === "backups" ? (
        <div className="scroll" style={{ padding: "4px 6px" }}>
          {mem.backups.length === 0 ? (
            <div className="state-empty">no backups yet</div>
          ) : (
            mem.backups.map((b, i) => (
              <div key={i} className="row between" style={{ padding: "6px 0", borderBottom: "1px solid var(--bd-1)" }}>
                <span className="mono" style={{ fontSize: 11 }}>
                  backup #{mem.backups.length - i}
                </span>
                <span className="mono muted" style={{ fontSize: 11 }} title={b.created_at}>
                  {new Date(b.created_at).toLocaleString()}
                </span>
              </div>
            ))
          )}
        </div>
      ) : null}
    </Panel>
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
  return <div className="col" style={{ padding: "4px 6px", gap: 8 }}>
    <div className="row between" style={{ flexWrap: "wrap" }}>
      <span className="muted" style={{ fontSize: 11 }}>根据当前已采纳的记忆整理，可随记忆更新。</span>
      <button className="ghost" onClick={load} disabled={loading}>{loading ? "正在更新…" : "更新画像"}</button>
    </div>
    {error ? <div className="state-error" role="alert">画像读取失败：{error}</div> : null}
    {loading && !view ? <div className="state-empty" role="status">正在整理你的记忆…</div> : null}
    {view ? <>
      <ProfileGroups title="全局核心画像" groups={view.core_profiles} />
      <ProfileGroups title="场景画像" groups={view.scenario_profiles} />
      <ProfileGroups title="项目画像" groups={view.project_profiles} />
      {view.core_profiles.length + view.scenario_profiles.length + view.project_profiles.length === 0 ? <div className="state-empty">还没有形成画像。你确认采纳一些记忆后，这里会逐渐呈现 LifeOS 对你的理解。</div> : null}
    </> : null}
  </div>;
}

function ProfileGroups({ title, groups }: { title: string; groups: import("../api/types").MemoryProfileGroup[] }) {
  if (!groups.length) return null;
  return <section className="col" style={{ gap: 6 }}><h3 style={{ margin: "4px 0", fontSize: 13 }}>{title}</h3>{groups.map((group, index) => <div key={`${group.scope.kind}-${group.scope.project_id ?? group.scope.scenario_type ?? index}`} className="card-flat">
    <div className="row between"><strong style={{ fontSize: 12 }}>{scopeLabel(group.scope)}</strong><span className="mono muted" style={{ fontSize: 10 }}>{group.memory_count} 条依据</span></div>
    {group.memories.map((memory) => <div key={memory.id} style={{ borderTop: "1px solid var(--bd-1)", marginTop: 7, paddingTop: 7 }}>
      <div style={{ fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{claimText(memory.content)}</div>
      <Provenance item={memory} />
    </div>)}
  </div>)}</section>;
}

function scopeLabel(scope?: import("../api/types").MemoryScope) {
  if (!scope) return "范围未标注";
  if (scope.kind === "global") return "全局";
  if (scope.kind === "scenario") return `场景 · ${scenarioLabel(scope.scenario_type)}`;
  if (scope.kind === "project") return `项目 · ${scope.project_id ?? "未命名"}`;
  return "未分配";
}

function scenarioLabel(value?: string | null) {
  const labels: Record<string, string> = { learning: "学习", project: "项目", document: "文档写作", information: "信息整理", external_operation: "外部操作" };
  return value ? labels[value] ?? value : "未命名";
}

function sourceLabel(value: string) {
  const labels: Record<string, string> = { chat: "对话", daily_plan: "每日计划", daily_review: "每日回顾", phase_plan: "阶段计划", phase_review: "阶段回顾", diary: "日记", insight: "心得", feedback: "反馈", agent_trace: "执行记录" };
  return labels[value] ?? value;
}

function claimText(content: Record<string, unknown>) {
  return typeof content.claim === "string" ? content.claim : JSON.stringify(content);
}

function Provenance({ item }: { item: Pick<MemoryCandidate, "source" | "source_ref" | "scope" | "confidence" | "confidence_method" | "occurred_at" | "created_at"> }) {
  const ref = item.source_ref;
  return <details style={{ marginTop: 5, fontSize: 11 }}>
    <summary>查看来源依据</summary>
    <div className="muted" style={{ marginTop: 5, lineHeight: 1.6 }}>
      <div>来自：{ref ? sourceLabel(ref.record_kind ?? ref.kind) : sourceLabel(item.source)}</div>
      {item.scope ? <div>适用范围：{scopeLabel(item.scope)}</div> : null}
      {item.occurred_at ? <div>记录时间：{new Date(item.occurred_at).toLocaleString()}</div> : null}
      {ref?.record_id ? <div>来源记录编号：{ref.record_id}{ref.revision ? ` · 第 ${ref.revision} 版` : ""}</div> : null}
      {item.confidence != null ? <div>参考把握度：{item.confidence}</div> : null}
    </div>
  </details>;
}

function MarkdownTab({ store }: { store: Store }) {
  const [md, setMd] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [message, setMessage] = useState("");

  const load = useCallback(() => {
    setStatus("loading");
    getMemoryMarkdown()
      .then((r) => {
        setMd(r.markdown);
        setStatus("idle");
      })
      .catch((e) => {
        setStatus("error");
        setMessage(e instanceof Error ? e.message : String(e));
      });
  }, []);

  useEffect(load, [load]);

  const save = () => {
    importMemoryMarkdown(md)
      .then((r) => {
        setMessage(`已导入：关于我 ${r.categories.user} 条、项目 ${r.categories.project} 条、反馈 ${r.categories.feedback} 条、参考 ${r.categories.reference} 条。`);
        void store.refreshAll();
      })
      .catch((e) => {
        setMessage(`导入失败：${e instanceof Error ? e.message : String(e)}`);
      });
  };

  return (
    <div className="col" style={{ padding: "4px 6px", gap: 6 }}>
      <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
        <button onClick={load} disabled={status === "loading"}>{status === "loading" ? "正在读取…" : "重新读取"}</button>
        <button className="ghost" onClick={save}>导入修改</button>
        {message ? <span className="mono muted" style={{ fontSize: 10 }}>{message}</span> : null}
      </div>
      <textarea
        className="mono"
        value={md}
        onChange={(e) => setMd(e.target.value)}
        placeholder={status === "error" ? `读取失败：${message}` : "正在读取记忆文件…"}
        spellCheck={false}
        style={{ width: "100%", minHeight: 220, fontSize: 11, lineHeight: 1.5, resize: "vertical" }}
      />
      <div className="mono muted" style={{ fontSize: 10 }}>
        这是记忆的可编辑文本副本。导入只会新增内容；如需修改或撤回已有记忆，请在对应记忆卡片中操作。
      </div>
    </div>
  );
}

function EntryList({ entries, empty, store }: { entries: MemoryEntry[]; empty: string; store: Store }) {
  if (entries.length === 0) return <div className="state-empty">{empty}</div>;
  return (
    <div className="scroll" style={{ padding: "4px 6px", display: "flex", flexDirection: "column", gap: 6 }}>
      {entries.map((e) => (
        <MemoryEntryCard key={e.id} entry={e} store={store} />
      ))}
    </div>
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
    try {
      parsed = JSON.parse(content);
    } catch {
      setMessage("内容必须是有效 JSON。");
      return;
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      setMessage("新记忆内容必须是 JSON 对象。");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      await correctMemory(entry.id, parsed as Record<string, unknown>, reason || undefined);
      await store.refreshAll();
      setEditing(false);
      setMessage("已保存为新版本；旧版本保留但不再参与召回。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  const submitRetraction = async () => {
    setBusy(true);
    setMessage("");
    try {
      await retractMemory(entry.id, reason || undefined);
      await store.refreshAll();
      setConfirmRetract(false);
      setMessage("已撤回；这条记忆将不再用于后续召回，来源记录未删除。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card-flat">
      <div className="row between">
        <span style={{ color: "var(--accent)", fontSize: 12 }}>
          {sourceLabel(entry.source)}
        </span>
        <span className="row" style={{ gap: 8 }}>
          <span className={`pill sm ${active ? "done" : "idle"}`}><span className="dot" />{active ? "正在使用" : "已撤回"}</span>
          <span className="mono muted" style={{ fontSize: 11 }}>
            {new Date(entry.created_at).toLocaleString()}
          </span>
        </span>
      </div>
      <div style={{ margin: "7px 0 0", whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 13, color: "var(--fg-2)" }}>{claimText(entry.content)}</div>
      <details style={{ marginTop: 5, fontSize: 11 }}>
        <summary>查看完整内容</summary>
        <pre className="mono" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 11, color: "var(--fg-2)" }}>{JSON.stringify(entry.content, null, 2)}</pre>
      </details>
      <Provenance item={entry} />
      {entry.version_of ? <div className="muted" style={{ fontSize: 10, marginTop: 4 }}>这是对旧记忆的修正。</div> : null}
      {entry.superseded_by ? <div className="muted" style={{ fontSize: 10, marginTop: 4 }}>这条内容已被后续版本替代。</div> : null}
      {active ? (
        <div className="row" style={{ gap: 6, marginTop: 9, flexWrap: "wrap" }}>
          <button className="ghost" disabled={!backend || busy} onClick={() => { setEditing(!editing); setConfirmRetract(false); setReason(""); setMessage(""); }}>
            {editing ? "取消纠正" : "纠正记忆"}
          </button>
          <button className="ghost danger" disabled={!backend || busy} onClick={() => { setConfirmRetract(!confirmRetract); setEditing(false); setReason(""); setMessage(""); }}>
            撤回记忆
          </button>
          {!backend ? <span className="mono muted" style={{ fontSize: 10 }}>预览模式不可修改</span> : null}
        </div>
      ) : null}
      {editing ? (
        <div className="col" style={{ gap: 7, marginTop: 10 }}>
          <label className="muted" style={{ fontSize: 11 }}>新记忆内容（高级格式）</label>
          <textarea className="mono" value={content} onChange={(event) => setContent(event.target.value)} spellCheck={false} style={{ width: "100%", minHeight: 100, resize: "vertical", fontSize: 11 }} />
          <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="纠正原因（可选）" />
          <div className="row" style={{ gap: 6 }}>
            <button disabled={busy} onClick={() => void submitCorrection()}>{busy ? "保存中…" : "确认保存为新版本"}</button>
            <span className="mono muted" style={{ fontSize: 10 }}>旧版本会保留为历史记录，但退出召回。</span>
          </div>
        </div>
      ) : null}
      {confirmRetract ? (
        <div className="col" style={{ gap: 7, marginTop: 10, padding: 10, border: "1px solid var(--bd-2)", borderRadius: "var(--r-2)" }}>
          <strong style={{ fontSize: 12 }}>确认撤回这条记忆？</strong>
          <span className="mono muted" style={{ fontSize: 10 }}>撤回后不再参与召回和画像；原始来源与审计记录会保留。此操作不是彻底删除。</span>
          <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="撤回原因（可选）" />
          <div className="row" style={{ gap: 6 }}>
            <button className="ghost danger" disabled={busy} onClick={() => void submitRetraction()}>{busy ? "处理中…" : "我确认撤回"}</button>
            <button className="ghost" disabled={busy} onClick={() => setConfirmRetract(false)}>取消</button>
          </div>
        </div>
      ) : null}
      {message ? <div className="mono muted" role="status" style={{ fontSize: 10, marginTop: 7 }}>{message}</div> : null}
    </div>
  );
}

function CandidateList({ candidates, store }: { candidates: MemoryCandidate[]; store: Store }) {
  if (candidates.length === 0)
    return <div className="state-empty">暂时没有待确认的记忆。LifeOS 从对话、计划和回顾中整理出候选后，会在这里请你确认。</div>;
  return (
    <div className="scroll" style={{ padding: "4px 6px", display: "flex", flexDirection: "column", gap: 8 }}>
      {candidates.map((c) => (
        <CandidateCard key={c.id} c={c} store={store} />
      ))}
    </div>
  );
}

function lifecycleLabel(stage: LifecycleStage) {
  const labels: Record<LifecycleStage, string> = {
    candidate: "待确认", validated: "已检查", backed_up: "已留存", applied: "已采纳",
    vector_upserted: "可用于理解", cache_invalidated: "已更新",
  };
  return labels[stage];
}

function CandidateCard({ c, store }: { c: MemoryCandidate; store: Store }) {
  // Synthetic lifecycle: candidate -> validated -> backed_up -> applied -> vector_upserted -> cache_invalidated.
  // We compute "how far along" from status + presence in project memory.
  const inProject = store.state.memory.project.some((p) => p.id === c.id);
  let stages: LifecycleStage[] = ["candidate"];
  if (c.status === "rejected") {
    stages = ["candidate"];
  } else if (c.status === "committed" || inProject) {
    stages = [
      "candidate",
      "validated",
      "backed_up",
      "applied",
      "vector_upserted",
      "cache_invalidated",
    ];
  }

  return (
    <div
      style={{
        border: `1px solid ${c.status === "committed" ? "rgba(78,201,138,0.4)" : c.status === "rejected" ? "rgba(255,110,110,0.4)" : "var(--bd-2)"}`,
        background: "var(--bg-2)",
        borderRadius: "var(--r-2)",
        padding: "10px 12px",
      }}
    >
      <div className="row between" style={{ marginBottom: 6 }}>
        <div className="row" style={{ gap: 8 }}>
          <span className="mono" style={{ color: "var(--accent)", fontSize: 12 }}>
          {sourceLabel(c.source)}
          </span>
          <span className="mono dim" style={{ fontSize: 11 }}>{c.id.slice(0, 13)}…</span>
        </div>
        <span className={`pill sm ${c.status === "committed" ? "done" : c.status === "rejected" ? "failed" : "pending"}`}>
          <span className="dot" />
          {c.status === "candidate" ? "待确认" : c.status === "committed" ? "已采纳" : c.status === "rejected" ? "已忽略" : c.status}
        </span>
      </div>
      <pre
        className="mono"
        style={{ margin: 0, fontSize: 11, color: "var(--fg-2)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}
      >
        {JSON.stringify(c.content, null, 2)}
      </pre>
      <Provenance item={c} />
      <div className="row" style={{ gap: 4, marginTop: 8, flexWrap: "wrap" }}>
        {LIFECYCLE_STAGES.map((s) => (
          <span
            key={s}
            className={`pill sm ${stages.includes(s) ? "done" : "idle"}`}
            title={lifecycleLabel(s)}
          >
            <span className="dot" />
            {lifecycleLabel(s)}
          </span>
        ))}
      </div>
      {c.status === "candidate" ? (
        <div className="row" style={{ gap: 6, marginTop: 10 }}>
          <button disabled={store.state.ui.dataMode !== "backend"} onClick={() => void store.approveCandidate(c.id)} title="采纳这条记忆">
            <span className="row" style={{ gap: 6 }}>
              <IconApprove size={11} /> 采纳
            </span>
          </button>
          <button className="ghost danger" disabled={store.state.ui.dataMode !== "backend"} onClick={() => void store.rejectCandidate(c.id)}>
            <span className="row" style={{ gap: 6 }}>
              <IconReject size={11} /> 忽略
            </span>
          </button>
          <span className="mono muted" style={{ fontSize: 10 }}>
            {store.state.ui.dataMode === "backend" ? "只有你采纳的内容才会用于后续理解" : "预览模式下暂不可操作"}
          </span>
        </div>
      ) : null}
    </div>
  );
}
