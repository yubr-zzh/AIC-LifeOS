import React, { useEffect, useRef, useState } from "react";
import type { ChatAttachment, ChatMessage, Store } from "../state/store";
import type { AgentRoutingPolicy, MemoryScope } from "../api/types";
import { proposeTraceMemoryCandidate } from "../api/client";
import type { DelegationPlan } from "../api/agentTypes";
import { IconSend, IconCopy, IconMessage, IconPaperclip, IconPencil, IconPanelLeft } from "../components/Icons";
import { CopyId } from "../components/CopyId";
import { CopyTextButton } from "../components/CopyTextButton";
import { DelegationCard } from "./DelegationCard";
import { Markdown } from "../components/Markdown";
import type { AgentActions } from "../hooks/useAgentStream";
import type { AgentStore } from "../state/agentStore";

interface Props {
  store: Store;
  /** 有连接才渲染委派卡；没连接时卡片会自己提示「先连接 Agent」。 */
  agent?: AgentStore;
  api?: AgentActions;
}

interface LocalConversation {
  id: string;
  title: string;
  customTitle?: boolean;
  updatedAt: string;
  messages: ChatMessage[];
  projectId?: string;
  memoryScope?: MemoryScope;
}

const HISTORY_KEY = "lifeos.chat.history.v1";
const HISTORY_COLLAPSED_KEY = "lifeos.chat.historyCollapsed.v1";
const ROUTING_POLICY_KEY = "lifeos-agent-routing-policy";
const WELCOME_ID = "system-welcome";
const TEXT_FILE_EXTS = new Set(["txt", "md", "markdown", "json", "csv", "log", "py", "ts", "tsx", "js", "jsx", "html", "css", "xml", "yml", "yaml", "toml", "ini", "sql"]);
const MAX_ATTACHMENT_BYTES = 200 * 1024;
const MAX_ATTACHMENTS = 3;

function readHistoryCollapsed(): boolean {
  try { return localStorage.getItem(HISTORY_COLLAPSED_KEY) === "1"; } catch { return false; }
}

function readRoutingPolicy(): AgentRoutingPolicy {
  try {
    const value = localStorage.getItem(ROUTING_POLICY_KEY);
    return value === "force_agent" || value === "force_self_plan" ? value : "auto";
  } catch {
    return "auto";
  }
}

function readHistory(): LocalConversation[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return (parsed.filter((item) =>
      item && typeof item.id === "string" && Array.isArray(item.messages),
    ) as LocalConversation[]).map((item) => ({
      ...item,
      messages: item.messages.map((message) => message.id === WELCOME_ID
        && message.content.startsWith("LifeOS Chat Agent online.")
        ? { ...message, content: "LifeOS 已就绪。发来一条消息，我会结合你的记忆回答，并把值得沉淀的内容交给后台整理。" }
        : message),
    }));
  } catch {
    return [];
  }
}

function newConversationId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function titleFor(messages: ChatMessage[]): string {
  const firstMessage = messages.find((message) => message.role === "user");
  const first = firstMessage?.content?.trim() || firstMessage?.attachments?.[0]?.name || "";
  return first ? first.slice(0, 32) + (first.length > 32 ? "…" : "") : "新对话";
}

function savedScope(conversation: LocalConversation): MemoryScope {
  return conversation.memoryScope ?? (conversation.projectId
    ? { kind: "project", project_id: conversation.projectId }
    : { kind: "global" });
}

function shortDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "";
  const today = new Date();
  return date.toDateString() === today.toDateString()
    ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleDateString([], { month: "numeric", day: "numeric" });
}

export function ChatPanel({ store, agent, api }: Props) {
  const { state, sendMessage } = store;
  const [text, setText] = useState("");
  const [scopeKind, setScopeKind] = useState<"global" | "scenario" | "project">("global");
  const [scenarioType, setScenarioType] = useState("learning");
  const [projectId, setProjectId] = useState("");
  const [scopeError, setScopeError] = useState("");
  const [contextOpen, setContextOpen] = useState(false);
  const [routingPolicy, setRoutingPolicy] = useState<AgentRoutingPolicy>(readRoutingPolicy);
  const [history, setHistory] = useState<LocalConversation[]>(readHistory);
  const [historyCollapsed, setHistoryCollapsed] = useState(readHistoryCollapsed);
  const [activeId, setActiveId] = useState(() => newConversationId());
  const [historyReady, setHistoryReady] = useState(false);
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [fileError, setFileError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const saved = readHistory();
    const active = saved[0];
    if (active) {
      setHistory(saved);
      setActiveId(active.id);
      const scope = savedScope(active);
      setScopeKind(scope.kind === "scenario" || scope.kind === "project" ? scope.kind : "global");
      setScenarioType(scope.scenario_type ?? "learning");
      setProjectId(scope.project_id ?? active.projectId ?? "");
      store.dispatch({ type: "REPLACE_MESSAGES", messages: active.messages });
    }
    setHistoryReady(true);
  // Restore once; this store intentionally remains the active conversation state.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!historyReady) return;
    setHistory((previous) => {
      const old = previous.find((item) => item.id === activeId);
      const current: LocalConversation = {
        id: activeId,
        title: old?.customTitle ? old.title : titleFor(state.messages),
        customTitle: old?.customTitle,
        updatedAt: new Date().toISOString(),
        messages: state.messages,
        projectId,
        memoryScope: scopeKind === "project"
          ? { kind: "project", project_id: projectId.trim() }
          : scopeKind === "scenario"
            ? { kind: "scenario", scenario_type: scenarioType }
            : { kind: "global" },
      };
      const next = [current, ...previous.filter((item) => item.id !== activeId)].slice(0, 30);
      try { localStorage.setItem(HISTORY_KEY, JSON.stringify(next)); } catch { /* local history is best-effort */ }
      return next;
    });
  }, [activeId, historyReady, projectId, scenarioType, scopeKind, state.messages]);

  useEffect(() => {
    try { localStorage.setItem(ROUTING_POLICY_KEY, routingPolicy); } catch { /* preference is best-effort */ }
  }, [routingPolicy]);

  useEffect(() => {
    try { localStorage.setItem(HISTORY_COLLAPSED_KEY, historyCollapsed ? "1" : "0"); } catch { /* preference is best-effort */ }
  }, [historyCollapsed]);

  useEffect(() => {
    if (scroller.current) {
      scroller.current.scrollTop = scroller.current.scrollHeight;
    }
  }, [activeId, state.messages.length]);

  const submit = () => {
    const t = text.trim();
    if ((!t && attachments.length === 0) || state.loading.chat) return;
    if (scopeKind === "project" && !projectId.trim()) {
      setScopeError("填写项目 ID 后才能发送，避免项目记忆串用。");
      setContextOpen(true);
      return;
    }
    setScopeError("");
    setText("");
    const sentAttachments = attachments;
    setAttachments([]);
    setFileError("");
    const memoryScope: MemoryScope = scopeKind === "project"
      ? { kind: "project", project_id: projectId.trim() }
      : scopeKind === "scenario"
        ? { kind: "scenario", scenario_type: scenarioType }
        : { kind: "global" };
    void sendMessage(t, memoryScope, agent?.active?.sessionId, routingPolicy, sentAttachments);
  };

  const startNew = () => {
    if (state.loading.chat) return;
    setActiveId(newConversationId());
    setText("");
    setScopeKind("global");
    setScenarioType("learning");
    setProjectId("");
    setScopeError("");
    setContextOpen(false);
    setAttachments([]);
    setFileError("");
    store.dispatch({ type: "REPLACE_MESSAGES", messages: [] });
  };

  const openConversation = (conversation: LocalConversation) => {
    if (state.loading.chat) return;
    setActiveId(conversation.id);
    setText("");
    const scope = savedScope(conversation);
    setScopeKind(scope.kind === "scenario" || scope.kind === "project" ? scope.kind : "global");
    setScenarioType(scope.scenario_type ?? "learning");
    setProjectId(scope.project_id ?? conversation.projectId ?? "");
    setScopeError("");
    setAttachments([]);
    setFileError("");
    store.dispatch({ type: "REPLACE_MESSAGES", messages: conversation.messages });
  };

  const removeConversation = (conversationId: string) => {
    if (state.loading.chat) return;
    const target = history.find((item) => item.id === conversationId);
    if (!window.confirm(`删除对话「${target?.title || "新对话"}」？删除后无法恢复。`)) return;
    const next = history.filter((item) => item.id !== conversationId);
    setHistory(next);
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(next)); } catch { /* local history is best-effort */ }
    if (conversationId === activeId) {
      if (next[0]) openConversation(next[0]);
      else startNew();
    }
  };

  const renameConversation = (conversation: LocalConversation) => {
    const title = window.prompt("给这段对话起个名字", conversation.title || "新对话")?.trim();
    if (!title) return;
    const next = history.map((item) => item.id === conversation.id
      ? { ...item, title, customTitle: true, updatedAt: new Date().toISOString() }
      : item);
    setHistory(next);
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(next)); } catch { /* local history is best-effort */ }
  };

  const addFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    setFileError("");
    const incoming = Array.from(files);
    const accepted: ChatAttachment[] = [];
    for (const file of incoming) {
      const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
      if (!TEXT_FILE_EXTS.has(ext)) {
        setFileError(`暂不支持 ${file.name}，请上传文本、代码或配置文件。`);
        continue;
      }
      if (file.size > MAX_ATTACHMENT_BYTES) {
        setFileError(`${file.name} 超过 200 KB，请先精简后再上传。`);
        continue;
      }
      try {
        accepted.push({ id: `file-${Date.now()}-${accepted.length}`, name: file.name, size: file.size, content: await file.text() });
      } catch {
        setFileError(`${file.name} 读取失败，请重试。`);
      }
    }
    if (accepted.length) {
      setAttachments((current) => {
        const merged = [...current, ...accepted].slice(0, MAX_ATTACHMENTS);
        if (current.length + accepted.length > MAX_ATTACHMENTS) setFileError(`最多同时上传 ${MAX_ATTACHMENTS} 个文件。`);
        return merged;
      });
    }
    if (fileInput.current) fileInput.current.value = "";
  };

  const discardCurrent = () => {
    if (state.loading.chat) return;
    const current = history.find((item) => item.id === activeId);
    if (!current) { startNew(); return; }
    removeConversation(activeId);
  };
  const showWelcome = state.messages.length === 0 ||
    (state.messages.length === 1 && state.messages[0].id === WELCOME_ID);
  const activeConversation = history.find((item) => item.id === activeId);
  const currentTitle = activeConversation?.customTitle ? activeConversation.title : titleFor(state.messages);

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // 中文输入法选词按 Enter 会误发送。isComposing 期间不当作提交。
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className={`chat-workspace ${historyCollapsed ? "history-collapsed" : ""}`}>
      {!historyCollapsed ? <aside id="chat-history-panel" className="chat-history" aria-label="对话历史">
        <div className="chat-history-top">
          <button className="chat-new" onClick={startNew} disabled={state.loading.chat}>
            <span aria-hidden="true">＋</span> 新建对话
          </button>
          <button type="button" className="chat-history-collapse" onClick={() => setHistoryCollapsed(true)}
            title="隐藏对话历史" aria-label="隐藏对话历史"><IconPanelLeft size={16} /></button>
        </div>
        <div className="chat-history-label">最近对话</div>
        <div className="chat-history-list">
          {history.map((item) => (
            <div key={item.id} className={`chat-history-item ${item.id === activeId ? "active" : ""}`}>
              <button type="button" className="chat-history-open" onClick={() => openConversation(item)} disabled={state.loading.chat}>
                <IconMessage size={15} />
                <span className="chat-history-title">{item.title || "新对话"}</span>
                <time>{shortDate(item.updatedAt)}</time>
              </button>
              <div className="chat-history-item-actions">
                <button type="button" className="chat-history-rename" title="重命名对话" aria-label={`重命名对话：${item.title || "新对话"}`}
                  onClick={() => renameConversation(item)} disabled={state.loading.chat}><IconPencil size={13} /></button>
                <button type="button" className="chat-history-delete" title="删除对话" aria-label={`删除对话：${item.title || "新对话"}`}
                  onClick={() => removeConversation(item.id)} disabled={state.loading.chat}>×</button>
              </div>
            </div>
          ))}
          {history.length === 0 ? <p className="chat-history-empty">你的对话会出现在这里</p> : null}
        </div>
      </aside> : null}

      <section className="chat-conversation" aria-label="当前对话">
        <header className="chat-toolbar">
          <div className="chat-toolbar-left">
            {historyCollapsed ? (
              <button type="button" className="chat-history-toggle" onClick={() => setHistoryCollapsed(false)}
                title="显示对话历史" aria-label="显示对话历史" aria-expanded={false} aria-controls="chat-history-panel">
                <IconPanelLeft size={16} className="chat-history-restore-icon" />
              </button>
            ) : null}
            <div className="chat-toolbar-title">
              <strong>{currentTitle}</strong>
              <span>{agent?.active ? `正在与 ${agent.active.agentLabel} 协作` : "LifeOS 会结合你的记忆理解上下文"}</span>
            </div>
          </div>
          <div className="chat-toolbar-right">
            <button type="button" className="chat-delete-current" title="删除当前对话" aria-label="删除当前对话" onClick={discardCurrent} disabled={state.loading.chat}>删除</button>
            <div className="chat-context-wrap">
            <button className={`chat-context ${scopeKind !== "global" ? "selected" : ""}`}
              onClick={() => setContextOpen((open) => !open)} aria-expanded={contextOpen}>
              {scopeKind === "project" ? (projectId.trim() || "选择项目") : scopeKind === "scenario" ? ({ learning: "学习型", project: "项目型", document: "文档型", information_execution: "信息型执行", external_operation: "外部操作型" }[scenarioType] ?? scenarioType) : "全局记忆"}
              <span aria-hidden="true">⌄</span>
            </button>
            {contextOpen ? (
              <div className="chat-context-popover">
                <label htmlFor="chat-memory-scope">本轮记忆范围</label>
                <select id="chat-memory-scope" value={scopeKind} onChange={(event) => setScopeKind(event.target.value as typeof scopeKind)}>
                  <option value="global">全局记忆</option>
                  <option value="scenario">场景记忆</option>
                  <option value="project">项目记忆</option>
                </select>
                {scopeKind === "scenario" ? (
                  <select aria-label="选择记忆场景" value={scenarioType} onChange={(event) => setScenarioType(event.target.value)}>
                    <option value="learning">学习型</option><option value="project">项目型</option>
                    <option value="document">文档型</option><option value="information_execution">信息型执行</option>
                    <option value="external_operation">外部操作型</option>
                  </select>
                ) : null}
                {scopeKind === "project" ? (
                  <input id="chat-project-id" value={projectId} onChange={(event) => setProjectId(event.target.value)}
                    placeholder="填写稳定的项目 ID" autoFocus />
                ) : null}
                <small>{scopeKind === "global" ? "只检索全局记忆。" : scopeKind === "scenario" ? "只检索所选场景；不会自动扩大到其他范围。" : "项目记忆与其他项目隔离。"}</small>
                {scopeError ? <small role="alert">{scopeError}</small> : null}
                <button onClick={() => setContextOpen(false)}>完成</button>
              </div>
            ) : null}
            </div>
          </div>
        </header>

        <div ref={scroller} className="chat-messages scroll" aria-live="polite">
          {showWelcome ? (
            <div className="chat-welcome">
              <div className="chat-welcome-mark"><IconMessage size={22} /></div>
              <span className="chat-eyebrow">LifeOS · 你的第二大脑</span>
              <h2>今天想从哪里开始？</h2>
              <p>聊聊正在思考的事，或把一个想法变成可以行动的下一步。</p>
              <div className="chat-prompts">
                {["帮我梳理今天最重要的事", "基于我的项目记忆继续推进", "把一个想法拆成行动步骤"].map((prompt) => (
                  <button key={prompt} onClick={() => { setText(prompt); }} disabled={state.loading.chat}>{prompt}<span>→</span></button>
                ))}
              </div>
            </div>
          ) : (
            <div className="chat-message-list">
              {state.messages.map((m) => (
                  <Bubble key={m.id} msg={m} store={store} agent={agent} api={api} />
              ))}
            </div>
          )}
        </div>

        <div className="chat-compose-wrap">
          <Composer value={text} onChange={setText} onSubmit={submit} onKey={onKey}
            routingPolicy={routingPolicy} onRoutingPolicyChange={setRoutingPolicy}
            disabled={state.loading.chat} attachments={attachments} fileError={fileError}
            onPickFile={() => fileInput.current?.click()}
            onRemoveFile={(id) => setAttachments((current) => current.filter((file) => file.id !== id))} />
          <input ref={fileInput} type="file" multiple hidden accept=".txt,.md,.markdown,.json,.csv,.log,.py,.ts,.tsx,.js,.jsx,.html,.css,.xml,.yml,.yaml,.toml,.ini,.sql"
            onChange={(event) => void addFiles(event.target.files)} />
        </div>
      </section>
    </div>
  );
}

function Bubble({ msg, store, agent, api }: { msg: ChatMessage; store: Store; agent?: AgentStore; api?: AgentActions }) {
  if (msg.role === "user") {
    return (
      <div className="arrival chat-message user-message">
        {msg.content ? <div className="chat-message-content">{msg.content}</div> : null}
        {msg.attachments?.length ? <div className="chat-message-files">
          {msg.attachments.map((file) => <span key={file.id}><IconPaperclip size={11} /> {file.name} <small>{Math.max(1, Math.round(file.size / 1024))} KB</small></span>)}
        </div> : null}
        <div className="chat-message-foot">
          <span className="chat-message-time">{new Date(msg.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
          <CopyTextButton text={[msg.content, ...(msg.attachments ?? []).map((file) => `[附件] ${file.name}\n${file.content}`)].filter(Boolean).join("\n\n")} />
        </div>
      </div>
    );
  }
  const pending = msg.execution === "pending";
  const errored = msg.execution === "error";
  return (
    <div className="arrival chat-message assistant-message">
      <div className="assistant-avatar" aria-hidden="true"><IconMessage size={15} /></div>
      <div className="assistant-body">
        <div className="assistant-meta">
          <strong>LifeOS</strong>
          {pending ? <span className="chat-thinking"><span className="dot" />正在思考</span> : null}
          {errored ? <span className="chat-error">暂时遇到问题</span> : null}
        </div>
        <div className={`assistant-content ${errored ? "has-error" : ""}`}>
          {pending ? (
            <span className="muted">正在整理思路…</span>
          ) : msg.content ? (
            <Markdown text={msg.content} />
          ) : (
            <span className="muted">没有生成文字回复</span>
          )}
        </div>
        {msg.tool_calls && msg.tool_calls.length > 0 ? (
          <details className="chat-execution-details">
            <summary>{msg.tool_calls.length} 项执行记录</summary>
            <div className="chat-tool-list">
              {msg.tool_calls.map((tc, i) => (
                <div key={i} className="chat-tool-item">
                  <div className="row between">
                    <span>{tc.name ?? tc.action ?? "工具操作"}</span>
                    <span className={`pill sm ${msg.tool_results?.[i]?.status === "blocked" ? "failed" : msg.tool_results?.[i]?.status === "executed" ? "done" : "idle"}`}>
                      <span className="dot" />{msg.tool_results?.[i]?.status ?? "已请求"}
                    </span>
                  </div>
                  {tc.arguments ? <pre>{JSON.stringify(tc.arguments, null, 2)}</pre> : null}
                </div>
              ))}
            </div>
          </details>
        ) : null}
        {msg.trace_id ? <details className="chat-trace-details"><summary>查看本轮详情</summary><CopyId value={msg.trace_id} /></details> : null}
        {msg.delegation && agent && api ? (
          <DelegationCardBox msg={msg} plan={msg.delegation} agent={agent} api={api} store={store} />
        ) : null}
        {msg.trace_id && msg.execution === "succeeded" ? (
          <ConversationMemoryCapture msg={msg} store={store} />
        ) : null}
        {!pending && msg.content ? (
          <div className="assistant-message-foot">
            <CopyTextButton text={msg.content} />
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ConversationMemoryCapture({ msg, store }: { msg: ChatMessage; store: Store }) {
  const [open, setOpen] = useState(false);
  const [claim, setClaim] = useState("");
  const [scopeKind, setScopeKind] = useState<"global" | "scenario" | "project">("global");
  const [scenarioType, setScenarioType] = useState("learning");
  const [projectId, setProjectId] = useState("");
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [notice, setNotice] = useState("");

  const submit = async () => {
    const distilledClaim = claim.trim();
    if (!distilledClaim) { setNotice("请先写下你希望 LifeOS 记住的结论。"); return; }
    if (scopeKind === "project" && !projectId.trim()) { setNotice("请填写项目 ID，避免项目记忆串用。"); return; }
    const scope: MemoryScope = scopeKind === "project"
      ? { kind: "project", project_id: projectId.trim() }
      : scopeKind === "scenario"
        ? { kind: "scenario", scenario_type: scenarioType }
        : { kind: "global" };
    setBusy(true); setNotice("");
    try {
      await proposeTraceMemoryCandidate(msg.trace_id!, {
        claim: distilledClaim,
        scope,
        category: scopeKind === "project" ? "project" : "user",
      });
      await store.refreshAll();
      setSubmitted(true);
      setNotice("已提交到记忆候选；批准前不会写入长期记忆或同步到外部 Provider。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error));
    } finally { setBusy(false); }
  };

  return (
    <div className="conversation-memory-capture">
      <button type="button" className="ghost" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        {open ? "收起记忆提炼" : "从这段对话提炼记忆"}
      </button>
      {open ? (
        <div className="conversation-memory-form">
          <p>只提交你写下的结论和对话来源编号，不复制聊天原文。提交后仍需审核。</p>
          <label>希望 LifeOS 记住什么？
            <textarea value={claim} onChange={(event) => setClaim(event.target.value)} rows={2} maxLength={2000}
              placeholder="例如：我更容易通过具体例子理解新概念。" />
          </label>
          <label>记忆范围
            <select value={scopeKind} onChange={(event) => setScopeKind(event.target.value as typeof scopeKind)}>
              <option value="global">全局核心</option><option value="scenario">场景</option><option value="project">具体项目</option>
            </select>
          </label>
          {scopeKind === "scenario" ? <label>场景
            <select value={scenarioType} onChange={(event) => setScenarioType(event.target.value)}>
              <option value="learning">学习型</option><option value="project">项目型</option><option value="document">文档型</option>
              <option value="information_execution">信息型执行</option><option value="external_operation">外部操作型</option>
            </select>
          </label> : null}
          {scopeKind === "project" ? <label>项目 ID
            <input value={projectId} onChange={(event) => setProjectId(event.target.value)} placeholder="填写稳定的项目标识" />
          </label> : null}
          <button type="button" className="green-button" onClick={() => void submit()} disabled={busy || submitted || store.state.ui.dataMode !== "backend"}>
            {busy ? "提交中…" : submitted ? "已提交候选" : "提交待审核候选"}
          </button>
          {store.state.ui.dataMode !== "backend" ? <small>预览模式不可写入。</small> : null}
          {notice ? <div role="status" className="conversation-memory-notice">{notice}</div> : null}
        </div>
      ) : null}
    </div>
  );
}

function DelegationCardBox({
  msg,
  plan,
  agent,
  api,
  store,
}: {
  msg: ChatMessage;
  plan: DelegationPlan;
  agent: AgentStore;
  api: AgentActions;
  store: Store;
}) {
  const fa = async (zhi: string[]) => {
    const sid = agent.active?.sessionId;
    if (!sid) return;
    agent.setLayout("split");
    await api.act.send(sid, { instructions: zhi });
    // 计划就地改成已下发，别让它看起来还能再发一次。
    store.dispatch({
      type: "PATCH_DELEGATION",
      traceId: msg.trace_id ?? "",
      plan: {
        ...plan,
        status: "inflight",
        items: plan.items.map((i) => ({ ...i, status: i.enabled ? "inflight" : "skipped" })),
      },
    });
  };

  return (
    <DelegationCard
      plan={plan}
      canSend={Boolean(agent.active?.sessionId)}
      onChange={(p) =>
        store.dispatch({ type: "PATCH_DELEGATION", traceId: msg.trace_id ?? "", plan: p })
      }
      onSend={(zhi) => void fa(zhi)}
      onOpenPanel={() => agent.setLayout("split")}
    />
  );
}

interface ComposerProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onKey: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  routingPolicy: AgentRoutingPolicy;
  onRoutingPolicyChange: (value: AgentRoutingPolicy) => void;
  disabled?: boolean;
  attachments: ChatAttachment[];
  fileError: string;
  onPickFile: () => void;
  onRemoveFile: (id: string) => void;
}

function Composer({ value, onChange, onSubmit, onKey, routingPolicy, onRoutingPolicyChange, disabled, attachments, fileError, onPickFile, onRemoveFile }: ComposerProps) {
  return (
    <div className="chat-composer">
      {attachments.length || fileError ? (
        <div className="chat-attachment-tray">
          {attachments.map((file) => (
            <span className="chat-attachment-chip" key={file.id}>
              <span>{file.name}</span>
              <button type="button" onClick={() => onRemoveFile(file.id)} aria-label={`移除附件：${file.name}`}>×</button>
            </span>
          ))}
          {fileError ? <small role="alert">{fileError}</small> : null}
        </div>
      ) : null}
      <textarea
        rows={3}
        aria-label="发送消息给 LifeOS"
        placeholder="给 LifeOS 发消息…"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKey}
        disabled={disabled}
      />
      <div className="chat-composer-bottom">
        <button type="button" className="chat-attach-button" onClick={onPickFile} disabled={disabled}
          title="添加文本文件" aria-label="添加文本文件">
          <IconPaperclip size={15} />
        </button>
        <div className="chat-composer-side">
          <select aria-label="处理方式" value={routingPolicy} onChange={(event) => onRoutingPolicyChange(event.target.value as AgentRoutingPolicy)} disabled={disabled}>
            <option value="auto">自动判断</option>
            <option value="force_self_plan">只给文本建议</option>
            <option value="force_agent">使用执行型 Agent</option>
          </select>
          <button className="chat-send" onClick={onSubmit} disabled={disabled || (!value.trim() && attachments.length === 0)} title="发送消息" aria-label="发送消息">
            <IconSend size={15} />
          </button>
        </div>
      </div>
    </div>
  );
}
