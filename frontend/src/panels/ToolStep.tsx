import { useEffect, useRef, useState } from "react";
import type { AgentToolCall } from "../api/agentTypes";
import { toolTier } from "./agentFlow";
import {
  IconCheck,
  IconChevron,
  IconCircleDot,
  IconPause,
  IconRefresh,
  IconReject,
  IconSlash,
} from "../components/Icons";

interface Props {
  call: AgentToolCall;
  /** 强制展开。审批中 / 失败由调用方传 true。 */
  forceOpen?: boolean;
  /** 点击「等待批准」行时把审批卡滚到视口内。 */
  onLocateApproval?: (requestId: string) => void;
}

function ms(n: number | null): string {
  if (n === null) return "";
  if (n < 1000) return `${Math.round(n)}ms`;
  return `${(n / 1000).toFixed(1)}s`;
}

function inputText(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

function cancelLabel(reason: "denied" | "skipped" | "interrupted" | "expired"): string {
  if (reason === "denied") return "已拒绝";
  if (reason === "skipped") return "已跳过";
  if (reason === "expired") return "已超时";
  return "已中断";
}

/**
 * 一次工具调用的折叠行。
 *
 * 视觉参照 VSCode 的 `.progress-container` / `.tool-input-output-part`：
 * 成功完成的调用只占一行；需要操作或失败时才展开/加边框。
 */
export function ToolStep({ call, forceOpen, onLocateApproval }: Props) {
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const rowRef = useRef<HTMLButtonElement>(null);

  const { state } = call;
  const isAwaiting = state.type === "awaiting_confirmation" || state.type === "awaiting_post_approval";
  const isFailed = state.type === "completed" && state.isError;
  // 等待用户决定 / 失败必须可见，不允许折叠。
  const locked = isAwaiting || isFailed;
  const expanded = locked || open;
  // 第一档：成功完成的「只读类」调用只占一行，且**不可交互**。
  const progressOnly =
    !locked && state.type === "completed" && toolTier(call.name) === "progress";

  // 「执行中 3s」的秒表。**离开 executing 必须清掉**，否则每个调用都会留下
  // 一个永不停止的 interval。
  useEffect(() => {
    if (state.type !== "executing") return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [state.type]);

  let icon = <IconCircleDot size={12} />;
  let tone = "agts-idle";
  let text = call.summary;
  let meta = "";

  if (state.type === "streaming") {
    meta = "生成参数中";
  } else if (state.type === "awaiting_confirmation" || state.type === "awaiting_post_approval") {
    icon = <IconPause size={12} />;
    tone = "agts-confirm";
    meta = state.type === "awaiting_confirmation" ? "等待你批准" : "等待确认结果";
  } else if (state.type === "executing") {
    icon = <IconRefresh size={12} />;
    tone = "agts-busy";
    const s = Math.max(0, Math.round((now - state.startedAt) / 1000));
    meta = `${s}s`;
  } else if (state.type === "completed") {
    if (state.isError) {
      icon = <IconReject size={12} />;
      tone = "agts-bad";
      meta = "失败";
    } else {
      icon = <IconCheck size={12} />;
      tone = "agts-done";
      meta = ms(state.durationMs);
    }
  } else {
    icon = <IconSlash size={12} />;
    tone = "agts-idle";
    meta = cancelLabel(state.reason);
  }

  const onRow = () => {
    if (locked) {
      if (state.type === "awaiting_confirmation" && state.requestId && onLocateApproval) {
        onLocateApproval(state.requestId);
      }
      return;
    }
    setOpen((v) => !v);
  };

  if (progressOnly) {
    // 不可交互的一行：没有 chevron、不是 button、不进入 Tab 序。
    return (
      <div className={`agts agts-progress ${tone}`} data-tool={call.name}>
        <div className="agts-row agts-static">
          <span className="agts-chevron" aria-hidden="true" />
          <span className="agts-icon" aria-hidden="true">{icon}</span>
          <span className="agts-text">{text}</span>
          {meta ? <span className="agts-meta mono">{meta}</span> : null}
        </div>
      </div>
    );
  }

  return (
    <div className={`agts ${tone} ${expanded ? "expanded" : ""}`} data-tool={call.name}>
      <button
        ref={rowRef}
        type="button"
        className="agts-row"
        onClick={onRow}
        aria-expanded={expanded}
        aria-disabled={locked ? true : undefined}
        title={locked ? "需要你处理，无法折叠" : "展开输入与结果"}
      >
        <span className="agts-chevron" aria-hidden="true">
          {locked ? null : <IconChevron size={11} />}
        </span>
        <span className="agts-icon" aria-hidden="true">{icon}</span>
        <span className="agts-text">{text}</span>
        {meta ? <span className="agts-meta mono">{meta}</span> : null}
      </button>

      {expanded ? (
        <div className="agts-io">
          {state.type === "streaming" ? (
            <p className="agts-warn">参数未生成完，以下为原始片段，不是最终要执行的内容。</p>
          ) : null}
          {state.type === "streaming" && state.partialInput ? (
            <pre>{state.partialInput}</pre>
          ) : null}
          {call.input !== null && call.input !== undefined ? (
            <pre>{inputText(call.input)}</pre>
          ) : null}
          {call.resultText ? <pre>{call.resultText}</pre> : null}
        </div>
      ) : null}
    </div>
  );
}

/** 连续多个已完成调用的合并行。 */
export function ToolGroup({
  calls,
  label,
}: {
  calls: AgentToolCall[];
  label: string;
}) {
  const [open, setOpen] = useState(false);
  const total = calls.reduce((n, c) => {
    const d = c.state.type === "completed" ? c.state.durationMs : null;
    return n + (d ?? 0);
  }, 0);
  const failed = calls.some((c) => c.state.type === "completed" && c.state.isError);
  return (
    <div className={`agts agts-group ${failed ? "agts-bad" : "agts-done"} ${open ? "expanded" : ""}`}>
      <button
        type="button"
        className="agts-row"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="agts-chevron" aria-hidden="true"><IconChevron size={11} /></span>
        <span className="agts-icon" aria-hidden="true">
          {failed ? <IconReject size={12} /> : <IconCheck size={12} />}
        </span>
        <span className="agts-text">{label}</span>
        {total > 0 ? <span className="agts-meta mono">{ms(total)}</span> : null}
      </button>
      {open ? (
        <div className="agts-group-body">
          {calls.map((c) => <ToolStep key={c.toolUseId} call={c} />)}
        </div>
      ) : null}
    </div>
  );
}
