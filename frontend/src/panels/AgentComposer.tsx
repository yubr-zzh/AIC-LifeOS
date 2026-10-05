import React, { useState } from "react";

interface Props {
  disabled?: boolean;
  /** 正在跑的上行动作名。null 表示空闲。 */
  busy?: string | null;
  canInterrupt?: boolean;
  placeholder?: string;
  onSend: (a: string) => void;
  onInterrupt?: () => void;
}

export function AgentComposer({ disabled, busy, canInterrupt, placeholder, onSend, onInterrupt }: Props) {
  const [text, setText] = useState("");

  const submit = () => {
    const t = text.trim();
    if (!t || disabled || busy) return;
    setText("");
    onSend(t);
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // 中文输入法选词按 Enter 会误发送——必须判 isComposing。
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="agc">
      <textarea
        rows={2}
        value={text}
        placeholder={placeholder ?? "给 Agent 发一条指令，Enter 发送"}
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
          {busy === "send" ? "发送中…" : "发送"}
        </button>
      </div>
    </div>
  );
}
