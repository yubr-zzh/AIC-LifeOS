import React, { useState } from "react";

export interface QueuedMessage {
  id: string;
  text: string;
}

interface Props {
  /** 硬禁用仅用于面板本身不可用；普通“未连接”不要禁用输入框。 */
  disabled?: boolean;
  /** 当前是否可以发送。false 时仍允许输入并保留草稿。 */
  canSend?: boolean;
  /** 正在跑的上行动作名。null 表示空闲。 */
  busy?: string | null;
  canInterrupt?: boolean;
  placeholder?: string;
  /** Agent 正在执行：此时 Enter 进队列而不是直接发送。 */
  steering?: boolean;
  /** 已排队、等当前回合结束再发的消息。 */
  queued?: QueuedMessage[];
  onSend: (a: string) => Promise<void> | void;
  onQueue?: (a: string) => void;
  onUnqueue?: (id: string) => void;
  onInterrupt?: () => void;
}

export function AgentComposer({
  disabled,
  canSend = true,
  busy,
  canInterrupt,
  placeholder,
  steering,
  queued,
  onSend,
  onQueue,
  onUnqueue,
  onInterrupt,
}: Props) {
  const [text, setText] = useState("");
  const [sendError, setSendError] = useState("");
  const sendBlocked = Boolean(disabled || !canSend || busy === "send");

  const submit = async () => {
    const t = text.trim();
    if (!t || sendBlocked) return;
    setSendError("");
    // Steering：Agent 还在跑时先排队，等它回到 idle/ended 再发。
    // 直接发的话 Bridge 会同时起两条 paichu，指令和工具调用会交错。
    if (steering && onQueue) {
      onQueue(t);
      setText("");
      return;
    }
    try {
      await onSend(t);
      // 发送失败时保留原文，用户不用重打；发送成功后再清空。
      setText((current) => current === text ? "" : current);
    } catch (error) {
      setSendError(error instanceof Error ? error.message : String(error));
    }
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // 中文输入法选词按 Enter 会误发送——必须判 isComposing。
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && !sendBlocked) {
      e.preventDefault();
      void submit();
    }
  };

  const list = queued ?? [];

  return (
    <div className="agc">
      {list.length > 0 ? (
        <ul className="agc-queue" aria-label="待发送的指令">
          {list.map((q) => (
            <li key={q.id}>
              <span className="agc-queue-dot" aria-hidden="true" />
              <span className="agc-queue-text">{q.text}</span>
              <button
                type="button"
                className="agc-queue-x"
                onClick={() => onUnqueue?.(q.id)}
                aria-label={`取消排队：${q.text}`}
                title="取消这条"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <div className="agc-box">
        <textarea
          rows={2}
          aria-label="给 Agent 发送消息"
          value={text}
          placeholder={
            disabled
              ? "当前无法输入"
              : canSend === false
                ? "可以先输入内容；连接 Agent 后再发送"
                : placeholder ??
                  (steering ? "Agent 正在执行；Enter 排队，等这一轮结束后发送" : "给 Agent 发消息，Enter 发送")
          }
          onChange={(e) => { setSendError(""); setText(e.target.value); }}
          onKeyDown={onKey}
          disabled={disabled}
        />
        {sendError ? <p className="agc-error" role="alert">{sendError}</p> : null}
        <div className="agc-btns">
          {!canSend && !disabled ? <span className="agc-hint">先在「Agent」连接一个会话</span> : null}
          {canInterrupt ? (
            <button className="btn-ghost" onClick={onInterrupt} disabled={busy === "interrupt"} title="停止当前回合，剩余指令不再下发">
              中断
            </button>
          ) : null}
          <button className="btn-allow" onClick={() => void submit()} disabled={sendBlocked || !text.trim()}>
            {busy === "send" ? "发送中…" : steering ? "排队" : "发送"}
          </button>
        </div>
      </div>
    </div>
  );
}
