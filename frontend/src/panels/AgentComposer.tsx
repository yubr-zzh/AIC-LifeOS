import React, { useState } from "react";

export interface QueuedMessage {
  id: string;
  text: string;
}

interface Props {
  disabled?: boolean;
  /** 正在跑的上行动作名。null 表示空闲。 */
  busy?: string | null;
  canInterrupt?: boolean;
  placeholder?: string;
  /** Agent 正在执行：此时 Enter 进队列而不是直接发送。 */
  steering?: boolean;
  /** 已排队、等当前回合结束再发的消息。 */
  queued?: QueuedMessage[];
  onSend: (a: string) => void;
  onQueue?: (a: string) => void;
  onUnqueue?: (id: string) => void;
  onInterrupt?: () => void;
}

export function AgentComposer({
  disabled,
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

  const submit = () => {
    const t = text.trim();
    if (!t || disabled || busy) return;
    setText("");
    // Steering：Agent 还在跑时先排队，等它回到 idle/ended 再发。
    // 直接发的话 Bridge 会同时起两条 paichu，指令和工具调用会交错。
    if (steering && onQueue) onQueue(t);
    else onSend(t);
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // 中文输入法选词按 Enter 会误发送——必须判 isComposing。
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
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

      <textarea
        rows={2}
        value={text}
        placeholder={
          placeholder ??
          (steering ? "Agent 正在执行；Enter 排队，等这一轮结束后发送" : "给 Agent 发一条指令，Enter 发送")
        }
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKey}
        disabled={disabled}
      />
      <div className="agc-btns">
        {canInterrupt ? (
          <button className="btn-ghost" onClick={onInterrupt} disabled={busy === "interrupt"} title="停止当前回合，剩余指令不再下发">
            中断
          </button>
        ) : null}
        <button className="btn-allow" onClick={submit} disabled={disabled || busy === "send" || !text.trim()}>
          {busy === "send" ? "发送中…" : steering ? "排队" : "发送"}
        </button>
      </div>
    </div>
  );
}
