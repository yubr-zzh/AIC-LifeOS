import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  INPUT_BYTE_BUDGET,
  type PermissionRequest,
  type PermissionResolution,
} from "../api/agentTypes";

/** 8.8 的信息分层：可信字段是系统给的，Agent 自撰的一律降级并标注来源。 */
const WEIXIAN = [
  /rm\s+(-[a-z]*\s+)*-?[rf]/i,
  /\bsudo\b/i,
  /\bmkfs\b/i,
  /\bdd\s+if=/i,
  /\bformat\b/i,
  /\bdiskpart\b/i,
  /\bshutdown\b/i,
  /\bchmod\s+777\b/i,
  /\bcurl\b[^|]*\|\s*(ba)?sh/i,
  /\bgit\s+push\s+--force/i,
  /\bDROP\s+(TABLE|DATABASE)\b/i,
  /\bformat\s+[a-z]:/i,
];

/** 把 toolInput 压成一行人能读的「这条到底要干什么」。 */
function yaoDian(a: PermissionRequest): { ming: string; can: string } {
  const t = a.toolInput ?? {};
  const v = t as Record<string, unknown>;
  if (a.toolName === "Bash" && typeof v.command === "string") return { ming: "命令", can: v.command };
  if (typeof v.file_path === "string") return { ming: "文件", can: v.file_path };
  if (typeof v.path === "string") return { ming: "路径", can: v.path };
  if (typeof v.pattern === "string") return { ming: "匹配", can: v.pattern };
  if (typeof v.url === "string") return { ming: "地址", can: v.url };
  if (typeof v.query === "string") return { ming: "查询", can: v.query };
  return { ming: "参数", can: JSON.stringify(t, null, 2) };
}

/** 危险词高亮。用切片 + <mark>，不拼 HTML——Agent 输出里可能有 Bidi 伪装字符。 */
function gaoLiang(a: string, b: RegExp | null): React.ReactNode {
  if (!b) return a;
  const parts = a.split(new RegExp(b.source, b.flags.replace("g", "")));
  if (parts.length === 1) return a;
  return parts.map((p, i) => (b.test(p) && p ? <mark key={i}>{p}</mark> : <span key={i}>{p}</span>));
}

function formatMs(a: number): string {
  if (a < 1000) return `${Math.max(0, Math.round(a))} ms`;
  if (a < 60_000) return `${(a / 1000).toFixed(1)} s`;
  return `${Math.floor(a / 60_000)} 分 ${Math.round((a % 60_000) / 1000)} 秒`;
}

const DECISION_TEXT: Record<string, string> = {
  user_allow: "允许",
  user_deny: "拒绝",
  auto_deny: "自动拒绝",
  auto_allow: "自动允许",
  interrupt: "已取消（中断）",
  timeout: "自动拒绝（超时）",
  shutdown: "自动拒绝（Bridge 关闭）",
};

export function jueDingWen(a: string | null, b: string | null): string {
  if (!b) return a ?? "已决定";
  if (b === "timeout") return "自动拒绝（超时）";
  if (b === "interrupt") return "已取消（中断）";
  return a ?? b;
}

interface Props {
  req: PermissionRequest;
  resolution?: PermissionResolution;
  onDecide: (a: "allow" | "deny", a2?: { always?: boolean }) => void;
  onDismiss?: () => void;
  /** 409 already_resolved：服务端说这条早就收口了，把历史决定显示出来。 */
  conflict?: string | null;
}

export function AgentApprovalCard({ req, resolution, onDecide, conflict }: Props) {
  const [now, setNow] = useState(() => Date.now());
  const [confirm, setConfirm] = useState(false);
  const [focused, setFocused] = useState(false);
  const card = useRef<HTMLDivElement>(null);

  const done = Boolean(resolution);
  const span = Math.max(1, req.expiresAt - req.createdAt);
  const left = Math.max(0, req.expiresAt - now);

  // 只在还没收口时跑秒表。收口后停掉，避免整面板每秒重渲染。
  useEffect(() => {
    if (done || !req.expiresAt) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [done, req.expiresAt]);

  const { ming, can } = useMemo(() => yaoDian(req), [req]);
  const wei = useMemo(() => WEIXIAN.find((r) => r.test(can)) ?? null, [can]);

  // 危险命令：第一次点「允许」只进入确认态，第二次才真发出去。
  const onAllow = () => {
    if (wei && !confirm) {
      setConfirm(true);
      return;
    }
    onDecide("allow");
  };

  const onKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    // 快捷键只在卡片拿到焦点时生效，否则会把整页的 y/n 吃掉。
    if (!focused || done) return;
    if (e.key === "y" || e.key === "Y") {
      e.preventDefault();
      onAllow();
    }
    if (e.key === "n" || e.key === "N") {
      e.preventDefault();
      onDecide("deny");
    }
  };

  const pct = Math.max(0, Math.min(100, (left / span) * 100));
  const tone = left <= 10_000 ? "st-failed" : left <= 30_000 ? "st-pending" : "st-processing";

  return (
    <div
      ref={card}
      className={`apr ${done ? "apr-done" : ""}`}
      tabIndex={done ? -1 : 0}
      onKeyDown={onKey}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      role="group"
      aria-label={`${req.toolName} 审批`}
    >
      <div className="apr-rail" aria-hidden="true">
        <span className={`apr-rail-fill ${tone}`} style={{ height: `${pct}%` }} />
      </div>

      <div className="apr-body">
        <header className="apr-head">
          <span className="apr-tool mono">{req.toolName}</span>
          {req.displayName && req.displayName !== req.toolName ? (
            <span className="apr-tool-alt mono">{req.displayName}</span>
          ) : null}
          {wei ? <span className="pill failed sm"><span className="dot" />危险命令</span> : null}
          {req.inputTruncated ? <span className="pill pending sm"><span className="dot" />已截断</span> : null}
          <span className="apr-spacer" />
          {done ? null : (
            <span className={`apr-count mono ${tone}`} title="超时后会自动拒绝">
              {formatMs(left)}
            </span>
          )}
        </header>

        {/* —— 可信区：系统给的原文，占最大面积 —— */}
        <div className="apr-trust">
          <div className="apr-trust-tag mono">可信 · {ming}</div>
          <pre className="apr-cmd mono">{gaoLiang(can, wei)}</pre>
          {req.inputTruncated ? (
            <p className="apr-note">
              原始内容 {formatMs(req.originalByteSize)}，超过 {formatMs(INPUT_BYTE_BUDGET)} 预算已被截断。
              你看到的不等于将执行的，所以「允许」不可用——请让 Agent 缩短命令后重发。
            </p>
          ) : null}
          {req.blockedPath ? <p className="apr-note">受限路径：<span className="mono">{req.blockedPath}</span></p> : null}
        </div>

        {/* —— 不可信区：Agent 自撰，折叠并标注 —— */}
        {req.title || req.description || req.decisionReason ? (
          <details className="apr-untrust">
            <summary>由 Agent 生成，非系统信息</summary>
            {req.title ? <p className="apr-agent-title">{req.title}</p> : null}
            {req.description ? <p className="apr-agent-desc">{req.description}</p> : null}
            {req.decisionReason ? <p className="apr-agent-reason">触发原因：{req.decisionReason}</p> : null}
          </details>
        ) : null}

        {conflict ? <p className="apr-conflict">{conflict}</p> : null}

        {done && resolution ? (
          <div className="apr-final">
            <span className={`pill ${resolution.decision.includes("deny") ? "failed" : "done"} sm`}>
              <span className="dot" />
              {jueDingWen(DECISION_TEXT[resolution.decision] ?? resolution.decision, resolution.autoReason)}
            </span>
            <span className="mono dim">已于 {new Date(resolution.at).toLocaleTimeString()} 决定</span>
          </div>
        ) : (
          <div className="apr-actions">
            <button className="btn-reject" onClick={() => onDecide("deny")} title="快捷键 n">
              拒绝
            </button>
            <button
              className="btn-allow"
              onClick={onAllow}
              disabled={req.inputTruncated}
              title={
                req.inputTruncated
                  ? "命令被截断过，不能放行"
                  : wei && !confirm
                    ? "再点一次确认放行危险命令"
                    : "快捷键 y"
              }
            >
              {wei && confirm ? "确认放行这条危险命令" : "允许"}
            </button>
            <button
              className="btn-ghost"
              onClick={() => onDecide("allow", { always: true })}
              disabled={req.inputTruncated}
              title="只在本会话内记住这条放行规则"
            >
              本会话内总是允许
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
