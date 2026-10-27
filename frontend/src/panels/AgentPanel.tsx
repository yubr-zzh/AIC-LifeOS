import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  CONNECTION_LABEL,
  STATE_LABEL,
  STATE_TONE,
  type AgentMessage,
  type AgentSession,
  type AgentToolCall,
} from "../api/agentTypes";
import type { AgentActions } from "../hooks/useAgentStream";
import type { AgentStore } from "../state/agentStore";
import { AgentApprovalCard } from "./AgentApprovalCard";
import { AgentComposer } from "./AgentComposer";
import { AgentQuestionCard } from "./AgentQuestionCard";
import { AgentMemoryCapture } from "./AgentMemoryCapture";
import { ToolGroup, ToolStep } from "./ToolStep";
import { groupLabel } from "./toolSummary";

interface Props {
  store: AgentStore;
  api: AgentActions;
  onCollapse: () => void;
  onCandidateCreated?: () => void;
}

function money(a: number): string {
  return a <= 0 ? "" : `¥${a.toFixed(4)}`;
}

function toolInputText(a: unknown): string {
  if (a === null || a === undefined) return "";
  if (typeof a === "string") return a;
  return JSON.stringify(a, null, 2);
}

type LiuItem =
  | { t: "msg"; m: AgentMessage }
  | { t: "tool"; call: AgentToolCall }
  | { t: "group"; calls: AgentToolCall[] };

/**
 * 把「消息流」与「工具调用表」合并成一条时间线。
 *
 * - 已被 toolCalls 吸收的 tool_use / tool_result / tool_cancelled 不再单独渲染
 *   （没有对应调用的保留，作为老 Bridge / 老历史的兜底）
 * - 按 seq 排序
 * - 相邻的、全部成功完成的调用合并成一组；等待审批 / 失败 / 执行中不合并
 */
function heBing(
  lie: AgentMessage[],
  calls: Record<string, AgentToolCall>,
  sid: string,
): LiuItem[] {
  const items: { seq: number; item: LiuItem }[] = [];

  for (const m of lie) {
    const chongfu =
      (m.kind === "tool_use" || m.kind === "tool_result" || m.kind === "tool_cancelled") &&
      Boolean(m.toolUseId && calls[m.toolUseId]);
    if (chongfu) continue;
    items.push({ seq: m.seq, item: { t: "msg", m } });
  }

  for (const tid in calls) {
    const c = calls[tid];
    if (c.sessionId !== sid) continue;
    items.push({ seq: c.seq, item: { t: "tool", call: c } });
  }

  items.sort((a, b) => a.seq - b.seq);

  const out: LiuItem[] = [];
  let buf: AgentToolCall[] = [];
  const flush = () => {
    if (buf.length >= 2) out.push({ t: "group", calls: buf });
    else for (const c of buf) out.push({ t: "tool", call: c });
    buf = [];
  };

  for (const { item } of items) {
    if (item.t === "tool") {
      const st = item.call.state;
      const heBingDe = st.type === "completed" && !st.isError;
      if (heBingDe) {
        buf.push(item.call);
        continue;
      }
    }
    flush();
    out.push(item);
  }
  flush();
  return out;
}

export function AgentPanel({ store, api, onCollapse, onCandidateCreated }: Props) {
  const { state, dispatch, active, streaming, todo } = store;
  const box = useRef<HTMLDivElement>(null);
  const [genzi, setGenzi] = useState(true);

  const lie = active ? state.messages[active.sessionId] ?? [] : [];
  const liu = useMemo(
    () => (active ? heBing(lie, state.toolCalls, active.sessionId) : []),
    [lie, state.toolCalls, active],
  );

  // 自动滚动。依赖是「正在流式输出的那条消息 + 它的长度」，
  // 不能用 messages.length —— chunk 帧不新增消息，照抄 ChatPanel 的依赖会永不触发。
  useLayoutEffect(() => {
    if (genzi && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lie.length, streaming?.len, streaming?.messageId, state.pending, state.questions, genzi]);

  const onScroll = () => {
    const el = box.current;
    if (!el) return;
    // 用户上滚就停跟随，回到底部再恢复。
    setGenzi(el.scrollHeight - el.scrollTop - el.clientHeight < 48);
    // 滚到顶部 → 向上翻更早的一批（带 before=<当前最早一条的 xuhao>）。
    // `hasMore=false` 时 store 那层直接短路，不会发空请求。
    // **别在首屏就把全部历史拉完**——那等于把总量无界换个地方搬回来。
    if (el.scrollTop < 24 && active) store.loadOlder(active.sessionId);
  };

  const dai = Object.values(state.pending).filter((p) => !state.resolved[p.requestId]);
  const wen = Object.values(state.questions).filter((q) => !state.questionClosed[q.questionId]);
  const kai = state.conn === "open";

  return (
    <section className="agp">
      <header className="agp-head">
        <div className="agp-title">
          <strong>Agent 交互</strong>
          {active ? <span className="agp-mode mono">{active.effectiveMode}</span> : null}
        </div>
        <div className="agp-head-btns">
          <button
            className="btn-ghost sm"
            onClick={() => active && void api.act.interrupt(active.sessionId)}
            disabled={!active || active.state === "idle" || active.state === "ended"}
            title="停止当前回合"
          >
            中断
          </button>
          <button className="btn-ghost sm" onClick={onCollapse} title="收起 Agent 面板" aria-label="收起 Agent 面板">
            ✕
          </button>
        </div>
      </header>

      <StatusBar session={active} store={store} />
      <DeviceBanner store={store} />
      {active ? <AgentMemoryCapture sessionId={active.sessionId}
        onCandidateCreated={onCandidateCreated} /> : null}

      {state.notices.length > 0 ? (
        <div className="agp-notices">
          {state.notices.map((n) => (
            <div key={n.id} className={`agp-notice ${n.recoverable ? "" : "hard"}`}>
              <span className="mono">{n.code}</span>
              <span>{n.message}</span>
              <button onClick={() => dispatch({ type: "DISMISS_NOTICE", id: n.id })} aria-label="关闭提示">✕</button>
            </div>
          ))}
        </div>
      ) : null}

      <div className="agp-body scroll" ref={box} onScroll={onScroll}>
        {!kai ? <Disconnected conn={state.conn} msg={state.connMsg} preview={api.preview} /> : null}

        {active && !lie.length && !streaming ? (
          <p className="agp-hint">还没有内容。从左侧的委派计划里勾选指令发过来，或直接在下面输入。</p>
        ) : null}

        {liu.map((item) => {
          if (item.t === "group") {
            return (
              <ToolGroup
                key={`g-${item.calls[0].toolUseId}`}
                calls={item.calls}
                label={groupLabel(item.calls.map((c) => c.name), item.calls.length)}
              />
            );
          }
          if (item.t === "tool") {
            return (
              <ToolStep
                key={item.call.toolUseId}
                call={item.call}
                onLocateApproval={(rid) => {
                  const el = document.getElementById(`apr-${rid}`);
                  el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
                  el?.focus?.();
                }}
              />
            );
          }
          // key 用 (sessionId, seq)：messageId 不唯一，一条 AssistantMessage
          // 的多个内容块共用它，拿它当 key React 会报 duplicate key，
          // 并且重渲染时会错认组件身份。
          return <Bubble key={`${item.m.sessionId}:${item.m.seq}`} m={item.m} />;
        })}

        {streaming && streaming.sessionId === active?.sessionId ? (
          streaming.kind === "tool_use" ? (
            // 工具参数还在流：不把 partial_json 当正文渲染（它是不可信片段）。
            <div className="agts agts-busy">
              <div className="agts-row" aria-hidden="true">
                <span className="agts-chevron" />
                <span className="agts-icon" />
                <span className="agts-text">生成工具参数中…</span>
              </div>
            </div>
          ) : (
            <div className={`agb agb-${streaming.kind}`}>
              <div className="agb-text">{streaming.text}</div>
            </div>
          )
        ) : null}

        {dai.length > 0 || wen.length > 0 ? (
          <div className="agp-decide">
            <div className="agp-decide-head">需要你决定 · {dai.length + wen.length}</div>
            {dai.map((p) => (
              <div key={p.requestId} id={`apr-${p.requestId}`} tabIndex={-1}>
              <AgentApprovalCard
                req={p}
                resolution={state.resolved[p.requestId]}
                onDecide={(fen, opts) => {
                  if (fen === "deny") {
                    void api.act.decide(p.requestId, { decision: "deny" }).catch(() => undefined);
                    return;
                  }
                  void api.act
                    .decide(p.requestId, {
                      decision: "allow",
                      ...(opts?.always
                        ? { updatedPermissions: [{ type: "addRules", behavior: "allow", destination: "session" }] }
                        : {}),
                    })
                    .catch(() => undefined);
                }}
              />
              </div>
            ))}
            {wen.map((q) => (
              <AgentQuestionCard
                key={q.questionId}
                wen={q}
                closed={state.questionClosed[q.questionId] ?? null}
                onAnswer={(answers) => void api.act.answer(q.questionId, { answers }).catch(() => undefined)}
              />
            ))}
          </div>
        ) : null}

        {active && active.state === "ended" && todo === 0 ? (
          <div className="agp-end">本次委派已结束</div>
        ) : null}
      </div>

      <AgentComposer
        disabled={!kai || !active}
        busy={api.busy}
        canInterrupt={Boolean(active) && !["idle", "ended", "attention", "waiting_input"].includes(active!.state)}
        onSend={(t) => active && void api.act.send(active.sessionId, { text: t }).catch(() => undefined)}
        onInterrupt={() => active && void api.act.interrupt(active.sessionId)}
      />
    </section>
  );
}

function StatusBar({ session, store }: { session: AgentSession | null; store: AgentStore }) {
  const { state } = store;
  const lei = state.lastResult[session?.sessionId ?? ""];
  const yong = session ? Math.max(0, Math.round((Date.now() - session.createdAt) / 1000)) : 0;
  return (
    <div className="agp-bar">
      <span className={`pill ${session ? STATE_TONE[session.state] : "idle"} sm`}>
        <span className="dot" />
        {session ? STATE_LABEL[session.state] : CONNECTION_LABEL[state.conn]}
      </span>
      {session && session.batchTotal > 0 ? (
        <span className="mono">第 {session.batchDone}/{session.batchTotal} 条指令</span>
      ) : null}
      {yong > 0 ? <span className="mono">已用 {yong}s</span> : null}
      {lei?.totalCostUsd ? <span className="mono">{money(lei.totalCostUsd)}</span> : null}
      {session && session.pendingPermissions.length + session.pendingQuestions.length > 0 ? (
        <span className="pill confirm sm"><span className="dot" />挂起 {session.pendingPermissions.length + session.pendingQuestions.length}</span>
      ) : null}
      {state.conn === "reconnecting" ? <span className="pill pending sm"><span className="dot" />重连中</span> : null}
    </div>
  );
}

/**
 * 设备离线提示（spec 9.4）。
 *
 * 服务端一切正常时界面「什么都不动」是最坏的失败形态：隧道断了、SSE 里没有任何
 * 帧、连不上也不报错，用户只会以为 Agent 卡住了。所以设备一不在位就主动说，
 * **并且把合成帧带回来的原因显示出来**——「隧道中断」和「设备离线」要能被区分开。
 *
 * `device === null` 是「还没收到过状态帧」（本机直连形态、或刚打开页面），
 * 不是离线，所以不铺。
 */
function DeviceBanner({ store }: { store: AgentStore }) {
  const d = store.state.device;
  if (!d || d.state === "connected") return null;
  // connecting 已经在连了，再说「正在重连」是同一件事说两遍。
  const shuo =
    d.state === "connecting" ? "设备连接中"
    : d.state === "error" ? "设备出错 · 正在重连"
    : "设备离线 · 正在重连";
  return (
    <div className="agp-off">
      <strong>{shuo}</strong>
      <p>
        {d.error ?? "Agent 暂时收不到这台设备的指令。隧道恢复后会自动接上，不用手动刷新。"}
      </p>
    </div>
  );
}

function Disconnected({ conn, msg, preview }: { conn: string; msg: string | null; preview: boolean }) {
  return (
    <div className="agp-off">
      <strong>{preview ? "预览模式" : CONNECTION_LABEL[conn as never] ?? "未连接"}</strong>
      {preview ? (
        <p>当前播放的是假数据。地址栏去掉 <code>?agentPreview=1</code> 即连接真实 Bridge。</p>
      ) : (
        <p>
          {msg ?? "没收到 Bridge 的心跳。"}
          <br />
          Bridge 没运行时，Agent 面板不会显示任何假数据——否则你会以为它在跑。
        </p>
      )}
    </div>
  );
}

export function Bubble({ m }: { m: AgentMessage }) {
  if (m.kind === "tool_use") {
    return (
      <div className="agb agb-tool">
        <div className="agb-role mono">
          tool_use · {m.toolName}
        </div>
        <pre className="agb-io mono">{toolInputText(m.toolInput)}</pre>
      </div>
    );
  }
  if (m.kind === "tool_result") {
    return (
      <div className={`agb agb-result ${m.isError ? "bad" : ""}`}>
        <div className="agb-role mono">tool_result{m.isError ? " · 失败" : ""}</div>
        <pre className="agb-io mono">{m.text}</pre>
      </div>
    );
  }
  if (m.kind === "thinking") {
    return (
      <div className="agb agb-thinking">
        <div className="agb-role mono">thinking</div>
        <div className="agb-text">{m.text}</div>
      </div>
    );
  }
  if (m.kind === "result") {
    return (
      <div className={`agb agb-sys ${m.isError ? "bad" : ""}`}>
        <div className="agb-role mono">result{m.isError ? " · 失败" : ""}</div>
        <div className="agb-text">{m.text}</div>
      </div>
    );
  }
  if (m.kind === "permission_resolved") {
    return (
      <div className="agb agb-sys">
        <div className="agb-role mono">permission_resolved</div>
        <div className="agb-text">{m.text}</div>
      </div>
    );
  }
  if (m.kind === "error" || m.kind === "rate_limit" || m.kind === "context_reset") {
    return (
      <div className="agb agb-sys">
        <div className="agb-role mono">{m.kind}</div>
        <div className="agb-text">{m.text}</div>
      </div>
    );
  }
  return (
    <div className={`agb agb-${m.role}`}>
      <div className="agb-role mono">{m.role}</div>
      <div className="agb-text">{m.text}</div>
    </div>
  );
}
