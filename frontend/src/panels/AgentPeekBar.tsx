import React from "react";
import type { PermissionRequest } from "../api/agentTypes";
import type { AgentActions } from "../hooks/useAgentStream";
import type { AgentStore } from "../state/agentStore";

interface Props {
  store: AgentStore;
  api: AgentActions;
  onOpen: () => void;
}

function yaoDian(a: PermissionRequest): string {
  const v = (a.toolInput ?? {}) as Record<string, unknown>;
  const s = typeof v.command === "string" ? v.command
    : typeof v.file_path === "string" ? v.file_path
    : JSON.stringify(a.toolInput ?? {});
  return s.length > 120 ? `${s.slice(0, 120)}…` : s;
}

/**
 * 折叠态的审批落点（11.7）。
 *
 * 存在的理由：审批会阻塞 Agent。折叠态下若没有任何落点，用户收不到 `attention`
 * 就无从得知——审批不是可以稍后处理的通知。收到时面板会自动切到双栏，
 * 但用户随后手动收起时，这条就是唯一入口。
 */
export function AgentPeekBar({ store, api, onOpen }: Props) {
  const { state, todo, active } = store;
  const working = Boolean(active && (active.state === "thinking" || active.state === "working" || active.state === "backoff"));
  if (state.layout !== "collapsed" || (todo === 0 && !working)) return null;

  const shen = Object.values(state.pending).find((p) => !state.resolved[p.requestId]);
  const wen = Object.values(state.questions).find((q) => !state.questionClosed[q.questionId]);

  return (
    <div className="apb" role="status">
      {working ? <span className="agent-spinner small" aria-hidden="true" /> : null}
      {todo > 0 ? <span className="apb-tag mono">需要你决定 · {todo}</span> : <span className="apb-tool">Agent 正在工作</span>}
      {shen ? (
        <>
          <span className="apb-tool mono">{shen.toolName}</span>
          <code className="apb-cmd mono">{yaoDian(shen)}</code>
          <button
            className="btn-allow sm"
            disabled={shen.inputTruncated}
            title={shen.inputTruncated ? "命令被截断过，不能放行" : "允许"}
            onClick={() => void api.act.decide(shen.requestId, { decision: "allow" }).catch(() => undefined)}
          >
            允许
          </button>
          <button
            className="btn-reject sm"
            onClick={() => void api.act.decide(shen.requestId, { decision: "deny" }).catch(() => undefined)}
          >
            拒绝
          </button>
        </>
      ) : wen ? (
        <>
          <span className="apb-tool">Agent 有 {wen.questions.length} 个问题等你回答</span>
          <button className="btn-allow sm" onClick={onOpen}>
            去回答
          </button>
        </>
      ) : null}
      <button className="apb-more" onClick={onOpen}>
        打开 Agent 面板 →
      </button>
    </div>
  );
}
