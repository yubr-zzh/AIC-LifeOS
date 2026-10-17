import React, { useState } from "react";

interface Props {
  /** 硬禁用仅用于面板本身不可用；普通“未连接”不要禁用输入框。 */
  disabled?: boolean;
  /** 当前是否可以发送。false 时仍允许输入并保留草稿。 */
  canSend?: boolean;
  /** 正在跑的上行动作名。null 表示空闲。 */
  busy?: string | null;
  canInterrupt?: boolean;
  placeholder?: string;
  onSend: (a: string) => void;
  onInterrupt?: () => void;
}

export function AgentComposer({ disabled, canSend = true, busy, canInterrupt, placeholder, onSend, onInterrupt }: Props) {
  const [text, setText] = useState("");
  const sendBlocked = Boolean(disabled || !canSend || busy === "send");

  const submit = () => {
    const t = text.trim();
    if (!t || sendBlocked) return;
    setText("");
    onSend(t);
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // 中文输入法选词按 Enter 会误发送——必须判 isComposing。
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && !sendBlocked) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="agc">
      <textarea
        rows={2}
        value={text}
        placeholder={disabled ? "当前无法输入" : canSend === false ? "可以先输入内容；连接 Agent 后再发送" : placeholder ?? "给 Agent 发一条指令，Enter 发送"}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKey}
        disabled={disabled}
      />
      <div className="agc-btns">
        {!canSend && !disabled ? <span className="agc-hint">先在「本地 Agent」连接一个会话</span> : null}
        {canInterrupt ? (
          <button className="btn-ghost" onClick={onInterrupt} disabled={busy === "interrupt"} title="停止当前回合，剩余指令不再下发">
            中断
          </button>
        ) : null}
        <button className="btn-allow" onClick={submit} disabled={sendBlocked || !text.trim()}>
          {busy === "send" ? "发送中…" : "发送"}
        </button>
      </div>
    </div>
  );
}