import React, { useEffect, useRef, useState } from "react";
import type { AgentRoutingPolicy, ChatMessage, PlanStep, Store } from "../state/store";
import { FEEDBACK_RATINGS } from "../api/types";
import type { FeedbackRating } from "../api/types";
import { IconBolt, IconSend } from "../components/Icons";
import { ModelSwitcher } from "./ModelSwitcher";

interface Props {
  store: Store;
  onOpenPlanning?: () => void;
}

export function ChatPanel({ store, onOpenPlanning }: Props) {
  const { state, sendMessage } = store;
  const conversation = store.activeConversation;
  const messages = conversation?.messages ?? [];
  const visibleMessages = messages.filter((message, index) => !(index === 0 && message.role === "assistant" && message.content.startsWith("LifeOS 已连接。")));
  const [text, setText] = useState("");
  const [routingPolicy, setRoutingPolicy] = useState<AgentRoutingPolicy>(() => {
    const saved = window.localStorage.getItem("lifeos-agent-routing-policy");
    return saved === "force_self_plan" || saved === "force_agent" ? saved : "auto";
  });
  const scroller = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (scroller.current) {
      scroller.current.scrollTop = scroller.current.scrollHeight;
    }
  }, [conversation?.id, visibleMessages.length]);

  useEffect(() => setText(""), [conversation?.id]);

  useEffect(() => {
    try {
      window.localStorage.setItem("lifeos-agent-routing-policy", routingPolicy);
    } catch {
      // The selected mode remains in memory if localStorage is unavailable.
    }
  }, [routingPolicy]);

  const submit = () => {
    const t = text.trim();
    if (!t || state.loading.chat) return;
    setText("");
    void sendMessage(t, routingPolicy);
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const chooseStarter = (value: string) => {
    setText(value);
    requestAnimationFrame(() => composerRef.current?.focus());
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <div ref={scroller} className="scroll chat-thread">
        {visibleMessages.length === 0 ? <ChatWelcome onChoose={chooseStarter} /> : (
          <div className="chat-message-stack">
            {visibleMessages.map((m) => (
              <Bubble key={m.id} msg={m} store={store} onOpenPlanning={onOpenPlanning} />
            ))}
          </div>
        )}
      </div>
      <Composer
        value={text}
        onChange={setText}
        onSubmit={submit}
        onKey={onKey}
        inputRef={composerRef}
        disabled={state.loading.chat}
        store={store}
      />
    </div>
  );
}

function ChatWelcome({ onChoose }: { onChoose: (value: string) => void }) {
  const suggestions = ["帮我梳理今天的计划", "我想记录一件刚发生的事", "继续推进一个项目"];
  return <div className="chat-welcome">
    <div className="chat-welcome-mark"><IconBolt size={20} /></div>
    <span className="card-kicker">一个可以慢慢展开的空间</span>
    <h2>今天想聊些什么？</h2>
    <p>计划、学习、项目进展，或任何想记下来的念头。LifeOS 会陪你一起整理。</p>
    <div className="chat-starters" aria-label="对话建议">
      {suggestions.map((suggestion) => <button type="button" key={suggestion} onClick={() => onChoose(suggestion)}>{suggestion}<span aria-hidden="true">→</span></button>)}
    </div>
  </div>;
}

function AgentRouteResult({ message }: { message: ChatMessage }) {
  return (
    <section className="agent-route-result" aria-label="分步骤建议">
      <div>
        <span className="agent-route-mark">✦</span>
        <div>
          <strong>这件事可以分几步来做</strong>
          <small>先看看计划，再决定下一步</small>
        </div>
      </div>
      <p>你可以先看看步骤，再决定是否继续。</p>
    </section>
  );
}

function Bubble({ msg, store, onOpenPlanning }: { msg: ChatMessage; store: Store; onOpenPlanning?: () => void }) {
  if (msg.role === "user") {
    return (
      <div className="arrival message-row user-message">
        <div className="message-bubble">
          {msg.content}
        </div>
      </div>
    );
  }
  const pending = msg.execution === "pending";
  const errored = msg.execution === "error";
  return (
    <div className="arrival message-row assistant-message">
      <div className="assistant-avatar"><IconBolt size={15} /></div>
      <div className="assistant-message-content">
        <div className="assistant-message-meta">
          <strong>LifeOS</strong>
          <time>{new Date(msg.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</time>
          {pending ? <span className="pill processing sm"><span className="dot" />正在整理</span> : null}
          {errored ? <span className="pill failed sm"><span className="dot" />暂时没完成</span> : null}
        </div>
        {msg.decision === "self_plan" && !pending ? (
          <SelfPlanResult message={msg} onOpenPlanning={onOpenPlanning} />
        ) : (
          <>
            {msg.decision === "agent" && !pending ? <AgentRouteResult message={msg} /> : null}
            <div
              className={`message-bubble assistant-bubble${errored ? " has-error" : ""}`}
            >
              {pending ? <span className="muted">正在整理你的问题…</span> : msg.content || <span className="muted">还没有回复内容</span>}
            </div>
          </>
        )}
        {msg.tool_calls && msg.tool_calls.length > 0 ? (
          <div className="col" style={{ marginTop: 6, gap: 6 }}>
            {msg.tool_calls.map((tc, i) => (
              <div key={i} className="card-flat">
                <div className="row between">
                  <span className="tool-request-title">
                    请求使用：{tc.name ?? tc.action ?? "工具"}
                  </span>
                  <span className={`pill sm ${msg.tool_results?.[i]?.status === "blocked" ? "failed" : msg.tool_results?.[i]?.status === "executed" ? "done" : "idle"}`}>
                    <span className="dot" />{msg.tool_results?.[i]?.status === "blocked" ? "未执行" : msg.tool_results?.[i]?.status === "executed" ? "已完成" : "等待确认"}
                  </span>
                </div>
                {tc.arguments ? (
                  <details className="tool-request-details"><summary>查看操作内容</summary><pre>{JSON.stringify(tc.arguments, null, 2)}</pre></details>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}
        {msg.trace_id && msg.execution === "succeeded" ? <FeedbackRow msg={msg} store={store} /> : null}
      </div>
    </div>
  );
}

function SelfPlanResult({ message, onOpenPlanning }: { message: ChatMessage; onOpenPlanning?: () => void }) {
  return (
    <section className="self-plan-result" aria-label="LifeOS 的步骤建议">
      <div className="self-plan-result-head">
        <span className="self-plan-result-mark">✦</span>
        <div>
          <strong>先给你一个可调整的建议</strong>
          <small>你可以按自己的节奏取舍</small>
        </div>
      </div>
      <p className="self-plan-reason">我先根据你刚才说的内容整理了一个建议，你可以随时调整。</p>
      {message.plan_steps?.length ? <SelfPlanSteps steps={message.plan_steps} /> : (
        <p className="self-plan-reason">{message.content}</p>
      )}
      <div className="self-plan-actions">
        <button type="button" className="green-button" onClick={onOpenPlanning}>打开阶段计划 <span>→</span></button>
        <span>内容会先展示给你，由你决定是否保存。</span>
      </div>
    </section>
  );
}

function SelfPlanSteps({ steps }: { steps: PlanStep[] }) {
  return (
    <div className="self-plan-steps">
      {steps.map((step, index) => (
        <div className="self-plan-step" key={step.id ?? `${step.title}-${index}`}>
          <span className="self-plan-step-index">{String(index + 1).padStart(2, "0")}</span>
          <div>
            <strong>{step.title}</strong>
            {step.detail ? <small>{step.detail}</small> : null}
          </div>
          {step.time ? <span className="self-plan-step-time">{step.time}</span> : null}
        </div>
      ))}
    </div>
  );
}

function FeedbackRow({ msg, store }: { msg: ChatMessage; store: Store }) {
  const { submitRating } = store;
  const sending = msg.feedbackSending;
  return (
    <div className="row" style={{ gap: 4, marginTop: 6, flexWrap: "wrap", alignItems: "center" }}>
      <span className="mono dim" style={{ fontSize: 10, marginRight: 2 }}>
        这条回复有帮助吗？
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
          已收到
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
  store: Store;
  inputRef: React.RefObject<HTMLTextAreaElement>;
}

function Composer({ value, onChange, onSubmit, onKey, disabled, store, inputRef }: ComposerProps) {
  return (
    <div className="composer">
      <div className="composer-toolbar">
        <ModelSwitcher store={store} disabled={disabled} />
        <span className="composer-hint">Enter 发送 · Shift + Enter 换行</span>
      </div>
      <div className="composer-row">
        <textarea
          rows={2}
          ref={inputRef}
          aria-label="发送给 LifeOS 的消息"
          placeholder="和 LifeOS 聊聊你正在推进的事情…"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKey}
          disabled={disabled}
        />
        <button type="button" className="primary composer-send" onClick={onSubmit} disabled={disabled || !value.trim()} title="发送">
          <span className="row" style={{ gap: 6 }}>
            <IconSend size={13} /> 发送
          </span>
        </button>
      </div>
    </div>
  );
}
