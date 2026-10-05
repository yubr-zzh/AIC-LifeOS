import React, { useEffect, useRef, useState } from "react";
import type { ChatMessage, Store } from "../state/store";
import { FEEDBACK_RATINGS } from "../api/types";
import type { FeedbackRating } from "../api/types";
import type { DelegationPlan } from "../api/agentTypes";
import { IconSend, IconCopy } from "../components/Icons";
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

export function ChatPanel({ store, agent, api }: Props) {
  const { state, sendMessage } = store;
  const [text, setText] = useState("");
  const [projectId, setProjectId] = useState("");
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scroller.current) {
      scroller.current.scrollTop = scroller.current.scrollHeight;
    }
  }, [state.messages.length]);

  const submit = () => {
    const t = text.trim();
    if (!t || state.loading.chat) return;
    setText("");
    void sendMessage(t, projectId.trim()
      ? { kind: "project", project_id: projectId.trim() }
      : undefined, agent?.active?.sessionId);
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // 中文输入法选词按 Enter 会误发送。isComposing 期间不当作提交。
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <div ref={scroller} className="scroll" style={{ flex: 1, padding: "12px 16px", display: "flex", flexDirection: "column", gap: 14 }}>
        {state.messages.map((m) => (
          <Bubble key={m.id} msg={m} store={store} agent={agent} api={api} />
        ))}
      </div>
      <label style={{ padding: "6px 16px", fontSize: 12 }}>
        当前项目 ID（填写后召回该项目已审核的记忆）
        <input value={projectId} onChange={(event) => setProjectId(event.target.value)}
          placeholder="例如 lifeos；留空只召回全局记忆" />
      </label>
      <Composer
        value={text}
        onChange={setText}
        onSubmit={submit}
        onKey={onKey}
        disabled={state.loading.chat}
      />
    </div>
  );
}

function Bubble({ msg, store, agent, api }: { msg: ChatMessage; store: Store; agent?: AgentStore; api?: AgentActions }) {
  if (msg.role === "user") {
    return (
      <div className="arrival" style={{ display: "flex", justifyContent: "flex-end" }}>
        <div style={{ maxWidth: "78%" }}>
          <div
            style={{
              background: "var(--bg-2)",
              border: "1px solid var(--bd-2)",
              borderRadius: "var(--r-2)",
              padding: "9px 12px",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              boxShadow: "var(--shadow-1)",
            }}
          >
            {msg.content}
          </div>
          <div className="row mono" style={{ justifyContent: "flex-end", marginTop: 4, color: "var(--fg-3)", fontSize: 11 }}>
            user · {new Date(msg.created_at).toLocaleTimeString()}
          </div>
        </div>
      </div>
    );
  }
  const pending = msg.execution === "pending";
  const errored = msg.execution === "error";
  return (
    <div className="arrival">
      <div style={{ maxWidth: "82%" }}>
        <div className="row" style={{ gap: 8, marginBottom: 4 }}>
          <span className="mono" style={{ color: "var(--accent)", fontSize: 11 }}>
            assistant
          </span>
          <span className="mono dim" style={{ fontSize: 11 }}>
            {new Date(msg.created_at).toLocaleTimeString()}
          </span>
          {pending ? <span className="pill processing sm"><span className="dot" />thinking</span> : null}
          {errored ? <span className="pill failed sm"><span className="dot" />error</span> : null}
        </div>
        <div
          style={{
            background: "var(--bg-2)",
            border: "1px solid var(--bd-2)",
            borderLeft: "2px solid var(--accent)",
            borderRadius: "var(--r-2)",
            padding: "10px 12px",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            color: errored ? "var(--st-failed)" : "var(--fg-1)",
            boxShadow: "var(--shadow-1)",
          }}
        >
          {pending ? <span className="muted">awaiting /chat…</span> : msg.content || <span className="muted">(empty response)</span>}
        </div>
        {msg.tool_calls && msg.tool_calls.length > 0 ? (
          <div className="col" style={{ marginTop: 6, gap: 6 }}>
            {msg.tool_calls.map((tc, i) => (
              <div key={i} className="card-flat">
                <div className="row between">
                  <span className="mono" style={{ color: "var(--accent)" }}>
                    tool_call · {tc.name ?? tc.action ?? "(unnamed)"}
                  </span>
                  <span className={`pill sm ${msg.tool_results?.[i]?.status === "blocked" ? "failed" : msg.tool_results?.[i]?.status === "executed" ? "done" : "idle"}`}>
                    <span className="dot" />{msg.tool_results?.[i]?.status ?? "requested"}
                  </span>
                </div>
                {tc.arguments ? (
                  <pre className="mono" style={{ margin: 0, color: "var(--fg-2)", fontSize: 11, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                    {JSON.stringify(tc.arguments, null, 2)}
                  </pre>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}
        {msg.trace_id ? (
          <div className="row" style={{ marginTop: 4, color: "var(--fg-3)" }}>
            <span className="mono" style={{ fontSize: 11 }}>trace</span>
            <CopyId value={msg.trace_id} />
          </div>
        ) : null}
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
    <div
      style={{
        borderTop: "1px solid var(--bd-1)",
        padding: "10px 12px",
        background: "linear-gradient(180deg, var(--bg-1), var(--bg-2))",
        display: "flex",
        gap: 8,
        alignItems: "flex-end",
      }}
    >
      <textarea
        rows={2}
        placeholder="Send a message to the Chat Agent (Shift+Enter for newline)"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKey}
        disabled={disabled}
        style={{ flex: 1, minHeight: 38 }}
      />
      <button className="primary" onClick={onSubmit} disabled={disabled || !value.trim()} title="Send">
        <span className="row" style={{ gap: 6 }}>
          <IconSend size={13} /> Send
        </span>
      </button>
    </div>
  );
}
