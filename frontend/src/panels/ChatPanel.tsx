import React, { useEffect, useRef, useState } from "react";
import type { ChatMessage, Store } from "../state/store";
import { FEEDBACK_RATINGS } from "../api/types";
import type { FeedbackRating } from "../api/types";
import type { DelegationPlan } from "../api/agentTypes";
import { IconSend, IconCopy, IconMessage } from "../components/Icons";
import { CopyId } from "../components/CopyId";
import { DelegationCard } from "./DelegationCard";
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
  updatedAt: string;
  messages: ChatMessage[];
  projectId?: string;
}

const HISTORY_KEY = "lifeos.chat.history.v1";
const WELCOME_ID = "system-welcome";

function readHistory(): LocalConversation[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((item) =>
      item && typeof item.id === "string" && Array.isArray(item.messages),
    ) as LocalConversation[] : [];
  } catch {
    return [];
  }
}

function newConversationId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function titleFor(messages: ChatMessage[]): string {
  const first = messages.find((message) => message.role === "user")?.content?.trim();
  return first ? first.slice(0, 32) + (first.length > 32 ? "…" : "") : "新对话";
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
  const [projectId, setProjectId] = useState("");
  const [contextOpen, setContextOpen] = useState(false);
  const [history, setHistory] = useState<LocalConversation[]>(readHistory);
  const [activeId, setActiveId] = useState(() => newConversationId());
  const [historyReady, setHistoryReady] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const saved = readHistory();
    const active = saved[0];
    if (active) {
      setHistory(saved);
      setActiveId(active.id);
      store.dispatch({ type: "REPLACE_MESSAGES", messages: active.messages });
    }
    setHistoryReady(true);
  // Restore once; this store intentionally remains the active conversation state.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!historyReady) return;
    const current: LocalConversation = {
      id: activeId,
      title: titleFor(state.messages),
      updatedAt: new Date().toISOString(),
      messages: state.messages,
      projectId,
    };
    setHistory((previous) => {
      const next = [current, ...previous.filter((item) => item.id !== activeId)].slice(0, 30);
      try { localStorage.setItem(HISTORY_KEY, JSON.stringify(next)); } catch { /* local history is best-effort */ }
      return next;
    });
  }, [activeId, historyReady, projectId, state.messages]);

  useEffect(() => {
    if (scroller.current) {
      scroller.current.scrollTop = scroller.current.scrollHeight;
    }
  }, [activeId, state.messages.length]);

  const submit = () => {
    const t = text.trim();
    if (!t || state.loading.chat) return;
    setText("");
    void sendMessage(t, projectId.trim()
      ? { kind: "project", project_id: projectId.trim() }
      : undefined, agent?.active?.sessionId);
  };

  const startNew = () => {
    if (state.loading.chat) return;
    setActiveId(newConversationId());
    setText("");
    setProjectId("");
    setContextOpen(false);
    store.dispatch({ type: "REPLACE_MESSAGES", messages: [] });
  };

  const openConversation = (conversation: LocalConversation) => {
    if (state.loading.chat) return;
    setActiveId(conversation.id);
    setText("");
    setProjectId(conversation.projectId ?? "");
    store.dispatch({ type: "REPLACE_MESSAGES", messages: conversation.messages });
  };

  const showWelcome = state.messages.length === 0 ||
    (state.messages.length === 1 && state.messages[0].id === WELCOME_ID);

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // 中文输入法选词按 Enter 会误发送。isComposing 期间不当作提交。
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="chat-workspace">
      <aside className="chat-history" aria-label="对话历史">
        <button className="chat-new" onClick={startNew} disabled={state.loading.chat}>
          <span aria-hidden="true">＋</span> 新建对话
        </button>
        <div className="chat-history-label">最近对话</div>
        <div className="chat-history-list">
          {history.map((item) => (
            <button key={item.id} className={`chat-history-item ${item.id === activeId ? "active" : ""}`}
              onClick={() => openConversation(item)} disabled={state.loading.chat}>
              <IconMessage size={15} />
              <span className="chat-history-title">{item.title || "新对话"}</span>
              <time>{shortDate(item.updatedAt)}</time>
            </button>
          ))}
          {history.length === 0 ? <p className="chat-history-empty">你的对话会出现在这里</p> : null}
        </div>
        <div className="chat-history-foot">历史仅保存在此浏览器</div>
      </aside>

      <section className="chat-conversation" aria-label="当前对话">
        <header className="chat-toolbar">
          <div className="chat-toolbar-title">
            <strong>{titleFor(state.messages)}</strong>
            <span>{agent?.active ? `正在与 ${agent.active.agentLabel} 协作` : "LifeOS 会结合你的记忆理解上下文"}</span>
          </div>
          <div className="chat-context-wrap">
            <button className={`chat-context ${projectId.trim() ? "selected" : ""}`}
              onClick={() => setContextOpen((open) => !open)} aria-expanded={contextOpen}>
              <span className="context-dot" />
              {projectId.trim() ? projectId.trim() : "全局记忆"}
              <span aria-hidden="true">⌄</span>
            </button>
            {contextOpen ? (
              <div className="chat-context-popover">
                <label htmlFor="chat-project-id">项目记忆</label>
                <input id="chat-project-id" value={projectId} onChange={(event) => setProjectId(event.target.value)}
                  placeholder="输入项目名称或 ID" autoFocus />
                <small>留空时仅使用全局记忆；项目记忆与其他项目隔离。</small>
                <button onClick={() => setContextOpen(false)}>完成</button>
              </div>
            ) : null}
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
          <Composer value={text} onChange={setText} onSubmit={submit} onKey={onKey} disabled={state.loading.chat} />
          <div className="chat-compose-hint">Enter 发送 · Shift + Enter 换行</div>
        </div>
      </section>
    </div>
  );
}

function Bubble({ msg, store, agent, api }: { msg: ChatMessage; store: Store; agent?: AgentStore; api?: AgentActions }) {
  if (msg.role === "user") {
    return (
      <div className="arrival chat-message user-message">
        <div className="chat-message-content">{msg.content}</div>
        <div className="chat-message-time">{new Date(msg.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</div>
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
          {pending ? <span className="muted">正在整理思路…</span> : msg.content || <span className="muted">没有生成文字回复</span>}
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
        {msg.trace_id && msg.execution === "succeeded" ? <FeedbackRow msg={msg} store={store} /> : null}
      </div>
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

function FeedbackRow({ msg, store }: { msg: ChatMessage; store: Store }) {
  const { submitRating } = store;
  const sending = msg.feedbackSending;
  return (
    <div className="row" style={{ gap: 4, marginTop: 6, flexWrap: "wrap", alignItems: "center" }}>
      <span className="mono dim" style={{ fontSize: 10, marginRight: 2 }}>
        feedback
      </span>
      {FEEDBACK_RATINGS.map((r) => {
        const active = msg.feedback === r.value;
        return (
          <button
            key={r.value}
            onClick={() => void submitRating(msg.id, r.value)}
            disabled={sending || msg.execution === "pending"}
            title={r.hint}
            className={active ? "primary" : "ghost"}
            style={{
              borderRadius: "var(--r-pill)",
              padding: "2px 10px",
              fontSize: 11,
              opacity: sending ? 0.5 : 1,
            }}
          >
            {active ? "✓ " : ""}
            {r.label}
          </button>
        );
      })}
      {msg.feedback ? (
        <span className="mono dim" style={{ fontSize: 10 }}>
          rated
        </span>
      ) : null}
    </div>
  );
}

interface ComposerProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onKey: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  disabled?: boolean;
}

function Composer({ value, onChange, onSubmit, onKey, disabled }: ComposerProps) {
  return (
    <div className="chat-composer">
      <textarea
        rows={3}
        aria-label="发送消息给 LifeOS"
        placeholder="给 LifeOS 发消息…"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKey}
        disabled={disabled}
      />
      <button className="chat-send" onClick={onSubmit} disabled={disabled || !value.trim()} title="发送消息" aria-label="发送消息">
        <IconSend size={17} />
      </button>
    </div>
  );
}
