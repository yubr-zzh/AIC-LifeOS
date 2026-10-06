import React, { useEffect, useRef, useState } from "react";
import type { AgentRoutingPolicy, ChatMessage, PlanStep, Store } from "../state/store";
import { FEEDBACK_RATINGS } from "../api/types";
import type { FeedbackRating } from "../api/types";
import { IconSend, IconCopy } from "../components/Icons";
import { CopyId } from "../components/CopyId";
import { ModelSwitcher } from "./ModelSwitcher";

interface Props {
  store: Store;
  onOpenPlanning?: () => void;
}

export function ChatPanel({ store, onOpenPlanning }: Props) {
  const { state, sendMessage } = store;
  const conversation = store.activeConversation;
  const messages = conversation?.messages ?? [];
  const [text, setText] = useState("");
  const [routingPolicy, setRoutingPolicy] = useState<AgentRoutingPolicy>(() => {
    const saved = window.localStorage.getItem("lifeos-agent-routing-policy");
    return saved === "force_self_plan" || saved === "force_agent" ? saved : "auto";
  });
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scroller.current) {
      scroller.current.scrollTop = scroller.current.scrollHeight;
    }
  }, [conversation?.id, messages.length]);

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
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const latestAssistant = [...messages].reverse().find((message) => message.role === "assistant" && message.decision);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <RoutingAwareness policy={routingPolicy} latest={latestAssistant} />
      <div ref={scroller} className="scroll chat-thread" style={{ flex: 1, padding: "12px 16px", display: "flex", flexDirection: "column", gap: 14 }}>
        {messages.map((m) => (
          <Bubble key={m.id} msg={m} store={store} onOpenPlanning={onOpenPlanning} />
        ))}
      </div>
      <Composer
        value={text}
        onChange={setText}
        onSubmit={submit}
        onKey={onKey}
        disabled={state.loading.chat}
        store={store}
        routingPolicy={routingPolicy}
        onRoutingPolicyChange={setRoutingPolicy}
      />
    </div>
  );
}

function RoutingAwareness({ policy, latest }: { policy: AgentRoutingPolicy; latest?: ChatMessage }) {
  const forced = policy !== "auto";
  const enabled = policy === "force_agent" || (!forced && latest?.decision === "agent");
  const pending = policy === "auto" && !latest;
  const stateLabel = forced ? "用户强制" : pending ? "等待判定" : enabled ? "已启用 Agent" : "未启用 Agent";
  const stateClass = enabled ? "enabled" : pending ? "pending" : "disabled";
  const policyLabel = policy === "force_agent" ? "强制 Agent" : policy === "force_self_plan" ? "强制自规划" : "自动判定";
  const sourceLabel = latest?.route_source === "rules" ? "规则护栏" : latest?.route_source === "external_plugin" ? "外部插件" : latest?.route_source === "model" ? "模型判断" : latest?.route_source === "user_override" ? "用户指定" : latest?.route_source === "fallback" ? "保守兜底" : "尚无结果";

  return (
    <div className={`routing-awareness ${stateClass}`} role="status" aria-live="polite">
      <span className="routing-orb" />
      <div className="routing-awareness-main">
        <strong>{stateLabel}</strong>
        <small>
          当前策略：{policyLabel}
          {latest?.decision ? ` · 来源：${sourceLabel} · 置信度 ${Math.round((latest.decision_confidence ?? 0) * 100)}%` : ""}
        </small>
      </div>
      {latest?.decision_reason ? <span className="routing-awareness-reason">{latest.decision_reason}</span> : null}
    </div>
  );
}

function AgentRouteResult({ message }: { message: ChatMessage }) {
  const confidence = Math.round((message.decision_confidence ?? 0) * 100);
  const source = message.route_source === "rules" ? "规则护栏" : message.route_source === "external_plugin" ? "外部插件" : message.route_source === "user_override" ? "用户指定" : "模型判断";
  return (
    <section className="agent-route-result" aria-label="Agent 已启用">
      <div>
        <span className="agent-route-mark">A</span>
        <div>
          <strong>Agent 已启用</strong>
          <small>{source}{confidence ? ` · 置信度 ${confidence}%` : ""}</small>
        </div>
        <span className="agent-route-badge">执行层</span>
      </div>
      <p>{message.decision_reason || "请求包含执行型操作，将进入 Agent 流程。"}</p>
      {message.route_signals?.length ? (
        <div className="route-signal-list">
          {message.route_signals.slice(0, 5).map((signal) => <span key={signal}>{signal}</span>)}
        </div>
      ) : null}
    </section>
  );
}

function Bubble({ msg, store, onOpenPlanning }: { msg: ChatMessage; store: Store; onOpenPlanning?: () => void }) {
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
          {msg.decision === "self_plan" ? <span className="pill done sm"><span className="dot" />无需 Agent</span> : null}
          {msg.decision === "agent" ? <span className="pill processing sm"><span className="dot" />需要 Agent</span> : null}
        </div>
        {msg.decision === "self_plan" && !pending ? (
          <SelfPlanResult message={msg} onOpenPlanning={onOpenPlanning} />
        ) : (
          <>
            {msg.decision === "agent" && !pending ? <AgentRouteResult message={msg} /> : null}
            <div
              style={{
                background: "var(--bg-2)",
                border: "1px solid var(--bd-2)",
                borderLeft: msg.decision === "agent" ? "2px solid #d97706" : "2px solid var(--accent)",
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
          </>
        )}
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
        {msg.provider || msg.model ? (
          <div className="row" style={{ marginTop: 5, color: "var(--fg-3)", flexWrap: "wrap" }}>
            <span className="mono" style={{ fontSize: 10 }}>model</span>
            <span className="model-response-chip">{msg.provider ?? "api"}{msg.model ? ` · ${msg.model}` : ""}</span>
          </div>
        ) : null}
        {msg.trace_id ? (
          <div className="row" style={{ marginTop: 4, color: "var(--fg-3)" }}>
            <span className="mono" style={{ fontSize: 11 }}>trace</span>
            <CopyId value={msg.trace_id} />
          </div>
        ) : null}
        {msg.trace_id && msg.execution === "succeeded" ? <FeedbackRow msg={msg} store={store} /> : null}
      </div>
    </div>
  );
}

function SelfPlanResult({ message, onOpenPlanning }: { message: ChatMessage; onOpenPlanning?: () => void }) {
  const confidence = Math.round((message.decision_confidence ?? 0) * 100);
  return (
    <section className="self-plan-result" aria-label="无需 Agent 的自规划建议">
      <div className="self-plan-result-head">
        <span className="self-plan-result-mark">✦</span>
        <div>
          <strong>无需 Agent，直接反馈给你自规划</strong>
          <small>长期规划已经完成任务复杂度判断</small>
        </div>
        <span className="self-plan-result-badge">自规划{confidence ? ` · ${confidence}%` : ""}</span>
      </div>
      <p className="self-plan-reason">{message.decision_reason || "这件事更适合由你掌握判断节奏。"}</p>
      {message.route_signals?.length ? (
        <div className="route-signal-list self-plan-signals">
          {message.route_signals.slice(0, 5).map((signal) => <span key={signal}>{signal}</span>)}
        </div>
      ) : null}
      {message.plan_steps?.length ? <SelfPlanSteps steps={message.plan_steps} /> : (
        <p className="self-plan-reason">{message.content}</p>
      )}
      <div className="self-plan-actions">
        <button type="button" className="green-button" onClick={onOpenPlanning}>加入阶段规划 <span>→</span></button>
        <span>不会调用工具，也不会产生外部操作。</span>
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
  store: Store;
  routingPolicy: AgentRoutingPolicy;
  onRoutingPolicyChange: (policy: AgentRoutingPolicy) => void;
}

const ROUTING_POLICY_LABELS: { value: AgentRoutingPolicy; label: string; hint: string }[] = [
  { value: "auto", label: "自动判定", hint: "由长期规划判断是否需要 Agent" },
  { value: "force_self_plan", label: "强制自规划", hint: "本次请求不会进入 Agent" },
  { value: "force_agent", label: "强制 Agent", hint: "本次请求直接进入 Agent" },
];

function Composer({ value, onChange, onSubmit, onKey, disabled, store, routingPolicy, onRoutingPolicyChange }: ComposerProps) {
  return (
    <div className="composer">
      <div className="composer-toolbar">
        <ModelSwitcher store={store} disabled={disabled} />
        <div className="routing-policy-control" role="group" aria-label="Agent 调用策略">
          {ROUTING_POLICY_LABELS.map((option) => (
            <button
              type="button"
              key={option.value}
              className={routingPolicy === option.value ? "active" : ""}
              aria-pressed={routingPolicy === option.value}
              title={option.hint}
              onClick={() => onRoutingPolicyChange(option.value)}
              disabled={disabled}
            >
              {option.label}
            </button>
          ))}
        </div>
        <span className="composer-hint">Shift + Enter 换行</span>
      </div>
      <div className="composer-row">
        <textarea
          rows={2}
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
