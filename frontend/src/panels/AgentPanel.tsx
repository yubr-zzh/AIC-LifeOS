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
import { CopyTextButton } from "../components/CopyTextButton";
import { ToolGroup, ToolStep } from "./ToolStep";
import { buildTurns, contextItems, type FlowItem, type Turn } from "./agentFlow";
import { Markdown } from "../components/Markdown";
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

export function AgentPanel({ store, api, onCollapse, onCandidateCreated }: Props) {
  const { state, dispatch, active, streaming, todo } = store;
  const box = useRef<HTMLDivElement>(null);
  const [genzi, setGenzi] = useState(true);
  const [memoryOpen, setMemoryOpen] = useState(true);

  useEffect(() => { setMemoryOpen(true); }, [active?.sessionId]);

  const lie = active ? state.messages[active.sessionId] ?? [] : [];
  const turns = useMemo(
    () => (active ? buildTurns(lie, state.toolCalls, active.sessionId) : []),
    [lie, state.toolCalls, active],
  );

  // ---- Steering 队列 ----
  // Agent 执行中 Enter 先排队，回到 idle/ended 再发。直接发会让 Bridge
  // 同时起两条 paichu，指令与工具调用交错。
  const [queue, setQueue] = useState<{ id: string; text: string }[]>([]);
  const steering = Boolean(active) && active!.state !== "idle" && active!.state !== "ended";
  const idleReady = Boolean(active) && (active!.state === "idle" || active!.state === "ended");
  // 一次只发一条：发出去的瞬间状态还没翻成 thinking，若不拦住，
  // 第二条会在同一帧被连带发出，两条 paichu 就在 Bridge 里撞车了。
  const flushing = useRef(false);

  useEffect(() => {
    if (!idleReady) {
      flushing.current = false;
      return;
    }
    if (flushing.current || !queue.length || !active) return;
    flushing.current = true;
    const [next, ...rest] = queue;
    setQueue(rest);
    void api.act.send(active.sessionId, { text: next.text }).catch(() => {
      // 失败就留在队里，等下一次状态变迁再试——不要吞掉。
      setQueue((q) => [next, ...q]);
    });
  }, [queue, idleReady, active, api.act]);

  const locateApproval = (rid: string) => {
    const el = document.getElementById(`apr-${rid}`);
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    el?.focus?.();
  };

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
  const working = Boolean(active && (active.state === "thinking" || active.state === "working" || active.state === "backoff"));

  return (
    <section className="agp">
      <header className="agp-head">
        <div className="agp-title">
          {working ? <span className="agent-spinner" aria-label="Agent 正在工作" /> : null}
          <strong>Agent 交互</strong>
          {active ? <span className="agp-mode mono">{active.effectiveMode}</span> : null}
        </div>
        <div className="agp-head-btns">
          {active ? <button className="btn-ghost sm" onClick={() => setMemoryOpen((value) => !value)} title={memoryOpen ? "收起记忆提炼" : "打开记忆提炼"}>{memoryOpen ? "收起记忆" : "记忆"}</button> : null}
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
      {active && memoryOpen ? <AgentMemoryCapture sessionId={active.sessionId}
        onCandidateCreated={onCandidateCreated} onClose={() => setMemoryOpen(false)} /> : null}

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

        {turns.map((turn, i) => (
          <TurnBlock
            key={turn.key}
            turn={turn}
            streaming={
              i === turns.length - 1 && streaming && streaming.sessionId === active?.sessionId
                ? streaming
                : null
            }
            canRetry={kai && active?.state !== "ended"}
            onRetry={(text) => active && void api.act.send(active.sessionId, { text }).catch(() => undefined)}
            onLocateApproval={locateApproval}
          />
        ))}

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

        {active &&
        active.state === "ended" &&
        active.batchTotal > 0 &&
        active.batchDone >= active.batchTotal &&
        todo === 0 ? (
          <div className="agp-end" aria-hidden="true" />
        ) : null}
      </div>

      <AgentComposer
        canSend={Boolean(kai && active)}
        busy={api.busy}
        canInterrupt={Boolean(active) && !["idle", "ended", "attention", "waiting_input"].includes(active!.state)}
        steering={steering}
        queued={queue}
        onSend={(t) => active && void api.act.send(active.sessionId, { text: t }).catch(() => undefined)}
        onQueue={(t) => setQueue((q) => [...q, { id: `q-${Date.now()}-${q.length}`, text: t }])}
        onUnqueue={(id) => setQueue((q) => q.filter((x) => x.id !== id))}
        onInterrupt={() => active && void api.act.interrupt(active.sessionId)}
      />
    </section>
  );
}

/**
 * 一轮对话的容器（对齐 VSCode 的 `.interactive-item-container`）。
 *
 * 用户消息有浅底，回答正文完全裸，工具调用折叠成行；hover 才出现
 * 「复制 / 重试」，避免每轮都挂一排按钮。
 */
function TurnBlock({
  turn,
  streaming,
  canRetry,
  onRetry,
  onLocateApproval,
}: {
  turn: Turn;
  streaming: { kind: string; text: string } | null;
  canRetry: boolean;
  onRetry: (text: string) => void;
  onLocateApproval: (requestId: string) => void;
}) {
  const [copied, setCopied] = useState(false);

  // 本轮碰过的文件 / 搜索模式，折叠在轮次底部。
  const ctx = contextItems(
    turn.items.flatMap((i) => (i.t === "tool" ? [i.call] : i.t === "group" ? i.calls : [])),
  );

  const copy = async () => {
    const parts: string[] = [];
    if (turn.user?.text) parts.push(turn.user.text);
    for (const item of turn.items) {
      if (item.t === "msg" && item.m.text) parts.push(item.m.text);
      else if (item.t === "tool") parts.push(item.call.summary);
      else if (item.t === "group") parts.push(groupLabel(item.calls.map((c) => c.name), item.calls.length));
    }
    try {
      await navigator.clipboard.writeText(parts.join("\n\n"));
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      // 剪贴板被拒（非安全上下文）：静默失败，不弹假成功。
    }
  };

  return (
    <section className="turn">
      {turn.user?.text ? (
        <div className="turn-ask">
          <div className="turn-ask-label">你</div>
          <div className="turn-ask-text">{turn.user.text}</div>
        </div>
      ) : null}

      <div className="turn-body">
        {turn.items.map((item) => (
          <FlowRow key={itemKey(item)} item={item} onLocateApproval={onLocateApproval} />
        ))}

        {streaming ? (
          streaming.kind === "tool_use" ? (
            <div className="agts agts-busy">
              <div className="agts-row agts-static" aria-hidden="true">
                <span className="agts-chevron" />
                <span className="agts-icon" />
                <span className="agts-text">生成工具参数中…</span>
              </div>
            </div>
          ) : streaming.kind === "text" ? (
            <div className="agb agb-text-stream">
              <Markdown text={streaming.text} />
            </div>
          ) : (
            <div className={`agb agb-${streaming.kind}`}>
              {streaming.text ? <CopyTextButton text={streaming.text} className="agb-copy" /> : null}
              <div className="agb-text">{streaming.text}</div>
            </div>
          )
        ) : null}
      </div>

      {ctx.length > 0 ? (
        <details className="turn-context">
          <summary>已使用的上下文 ({ctx.length})</summary>
          <ul>
            {ctx.map((c) => (
              <li key={`${c.kind}:${c.label}`} className={`turn-chip is-${c.kind}`} title={c.label}>
                <span className="turn-chip-kind">{c.kind === "read" ? "读" : c.kind === "write" ? "写" : "搜"}</span>
                <span className="turn-chip-label mono">{c.label}</span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      <div className="turn-foot">
        <button type="button" className="turn-act" onClick={() => void copy()}>
          {copied ? "已复制" : "复制"}
        </button>
        {canRetry && turn.user?.text ? (
          <button type="button" className="turn-act" onClick={() => onRetry(turn.user!.text)}>
            重试
          </button>
        ) : null}
      </div>
    </section>
  );
}

function itemKey(item: FlowItem): string {
  if (item.t === "msg") return `${item.m.sessionId}:${item.m.seq}`;
  if (item.t === "tool") return item.call.toolUseId;
  return `g-${item.calls[0].toolUseId}`;
}

function FlowRow({
  item,
  onLocateApproval,
}: {
  item: FlowItem;
  onLocateApproval: (requestId: string) => void;
}) {
  if (item.t === "group") {
    return (
      <ToolGroup
        calls={item.calls}
        label={groupLabel(item.calls.map((c) => c.name), item.calls.length)}
      />
    );
  }
  if (item.t === "tool") {
    return <ToolStep call={item.call} onLocateApproval={onLocateApproval} />;
  }
  // key 用 (sessionId, seq)：messageId 不唯一，一条 AssistantMessage
  // 的多个内容块共用它，拿它当 key React 会报 duplicate key。
  return <Bubble m={item.m} />;
}

/** 粗粒度时长：只到「秒 / 分钟 / 小时 / 天」，不显示 2600000s 这种数字。 */
function shiChang(s: number): string {
  if (s < 3600) return `${Math.floor(s / 60)} 分钟`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时`;
  return `${Math.floor(s / 86400)} 天`;
}

function StatusBar({ session, store }: { session: AgentSession | null; store: AgentStore }) {
  const { state } = store;
  const lei = state.lastResult[session?.sessionId ?? ""];
  const yong = session ? Math.max(0, Math.round((Date.now() - session.createdAt) / 1000)) : 0;
  return (
    <div className="agp-bar">
      <span className={`pill ${session ? STATE_TONE[session.state] : "idle"} sm`}>
        <span className="dot" />
        {session && (session.state === "thinking" || session.state === "working") ? <span className="agent-spinner small" aria-hidden="true" /> : null}
        {session ? STATE_LABEL[session.state] : CONNECTION_LABEL[state.conn]}
      </span>
      {session && session.batchTotal > 0 ? (
        <span className="mono">
          {session.batchDone}/{session.batchTotal} 条
        </span>
      ) : null}
      {/* 这里是**会话年龄**，不是「本轮耗时」。恢复出来的会话 createdAt 可能是
          几天前，直接打秒数会变成 2600000s 这种看着像坏掉的数字。 */}
      {yong >= 60 ? <span className="mono">会话 {shiChang(yong)}</span> : null}
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
        <CopyTextButton text={toolInputText(m.toolInput)} className="agb-copy" />
        <pre className="agb-io mono">{toolInputText(m.toolInput)}</pre>
      </div>
    );
  }
  if (m.kind === "tool_result") {
    return (
      <div className={`agb agb-result ${m.isError ? "bad" : ""}`}>
        <div className="agb-role mono">tool_result{m.isError ? " · 失败" : ""}</div>
        <CopyTextButton text={m.text} className="agb-copy" />
        <pre className="agb-io mono">{m.text}</pre>
      </div>
    );
  }
  if (m.kind === "thinking") {
    return (
      <div className="agb agb-thinking">
        <div className="agb-role mono">thinking</div>
        <CopyTextButton text={m.text} className="agb-copy" />
        <div className="agb-text">{m.text}</div>
      </div>
    );
  }
  if (m.kind === "result") {
    return (
      <div className={`agb agb-sys ${m.isError ? "bad" : ""}`}>
        <div className="agb-role mono">result{m.isError ? " · 失败" : ""}</div>
        <CopyTextButton text={m.text} className="agb-copy" />
        {m.text ? <Markdown text={m.text} /> : null}
      </div>
    );
  }
  if (m.kind === "permission_resolved") {
    return (
      <div className="agb agb-sys">
        <div className="agb-role mono">permission_resolved</div>
        <CopyTextButton text={m.text} className="agb-copy" />
        <div className="agb-text">{m.text}</div>
      </div>
    );
  }
  if (m.kind === "error" || m.kind === "rate_limit" || m.kind === "context_reset") {
    return (
      <div className="agb agb-sys">
        <div className="agb-role mono">{m.kind}</div>
        <CopyTextButton text={m.text} className="agb-copy" />
        <div className="agb-text">{m.text}</div>
      </div>
    );
  }
  // tool_use / tool_result 没有对应调用时的兜底：用系统行的左侧色条，
  // 不要 `agb-user`——tool_result 的 role 也是 user，给底色会看成一问一答。
  // 走到这里时 tool_use / tool_result 已被上面的分支处理，只剩 tool_cancelled
  // 这类系统事件，用左侧色条而不是用户气泡底色。
  const cls = m.kind === "tool_cancelled" ? "agb-sys" : `agb-${m.role}`;
  return (
    <div className={`agb ${cls}`}>
      <CopyTextButton text={m.text} className="agb-copy" />
      {m.role === "assistant" ? (
        <Markdown text={m.text} />
      ) : (
        <div className="agb-text">{m.text}</div>
      )}
    </div>
  );
}
