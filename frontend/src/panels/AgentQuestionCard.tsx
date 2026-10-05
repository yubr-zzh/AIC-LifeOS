import React, { useMemo, useState } from "react";
import type { AgentQuestionItem, PendingQuestion } from "../api/agentTypes";

interface Props {
  wen: PendingQuestion;
  closed?: { state: string; at: number } | null;
  onAnswer: (a: { questionId: string; values: string[] }[]) => void;
  conflict?: string | null;
}

const CLOSED_TEXT: Record<string, string> = {
  answered: "已作答",
  cancelled: "已取消",
  expired: "超时未答",
};

export function AgentQuestionCard({ wen, closed, onAnswer, conflict }: Props) {
  // 单选存字符串，多选存数组。统一在提交时转成 values[]。
  const [xuan, setXuan] = useState<Record<string, string | string[] | undefined>>({});

  const done = Boolean(closed);
  const key = (item: AgentQuestionItem, i: number) => item.questionId ?? String(i);

  const submit = () => {
    const answers = wen.questions.map((item, i) => {
      const v = xuan[key(item, i)];
      return { questionId: key(item, i), values: v === undefined ? [] : Array.isArray(v) ? v : [v] };
    });
    if (answers.some((a) => a.values.length === 0)) return;
    onAnswer(answers);
  };

  const ready = useMemo(
    () => wen.questions.every((item, i) => {
      const v = xuan[key(item, i)];
      return v !== undefined && (Array.isArray(v) ? v.length > 0 : true);
    }),
    [wen.questions, xuan],
  );

  const toggle = (item: AgentQuestionItem, i: number, label: string) => {
    const k = key(item, i);
    setXuan((cur) => {
      if (item.multiSelect) {
        const arr = Array.isArray(cur[k]) ? (cur[k] as string[]) : [];
        return { ...cur, [k]: arr.includes(label) ? arr.filter((x) => x !== label) : [...arr, label] };
      }
      return { ...cur, [k]: cur[k] === label ? undefined : label };
    });
  };

  return (
    <div className={`qst ${done ? "qst-done" : ""}`} role="group" aria-label="Agent 提问">
      <header className="qst-head">
        <span className="qst-badge mono">需要你回答</span>
        {done ? (
          <span className="pill idle sm"><span className="dot" />{CLOSED_TEXT[closed!.state] ?? closed!.state}</span>
        ) : (
          <span className="qst-timer mono">
            {Math.max(0, Math.round((wen.expiresAt - Date.now()) / 1000))}s 后自动跳过
          </span>
        )}
      </header>

      {wen.questions.map((item, i) => (
        <div className="qst-item" key={key(item, i)}>
          {item.header ? <div className="qst-header mono">{item.header}</div> : null}
          <p className="qst-text">{item.question}</p>
          <div className="qst-opts" role={item.multiSelect ? "group" : "radiogroup"}>
            {item.options.map((opt) => {
              const v = xuan[key(item, i)];
              const on = Array.isArray(v) ? v.includes(opt.label) : v === opt.label;
              return (
                <button
                  key={opt.label}
                  type="button"
                  role={item.multiSelect ? "checkbox" : "radio"}
                  aria-checked={on}
                  className={`qst-opt ${on ? "on" : ""}`}
                  disabled={done}
                  onClick={() => toggle(item, i, opt.label)}
                >
                  <span className="qst-box" aria-hidden="true">{on ? "✓" : ""}</span>
                  <span className="qst-opt-main">
                    <strong>{opt.label}</strong>
                    {opt.description ? <small>{opt.description}</small> : null}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      ))}

      {conflict ? <p className="apr-conflict">{conflict}</p> : null}

      {done ? null : (
        <div className="qst-actions">
          <button className="btn-ghost" onClick={() => onAnswer([])}>
            跳过，让 Agent 自己决定
          </button>
          <button className="btn-allow" onClick={submit} disabled={!ready}>
            提交回答
          </button>
        </div>
      )}
    </div>
  );
}
