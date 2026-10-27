import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  CONNECTION_LABEL,
  STATE_LABEL,
  STATE_TONE,
  type AgentMessage,
  type AgentSession,
} from "../api/agentTypes";
import type { AgentActions } from "../hooks/useAgentStream";
import type { AgentStore } from "../state/agentStore";
import { AgentApprovalCard } from "./AgentApprovalCard";
import { AgentComposer } from "./AgentComposer";
import { AgentQuestionCard } from "./AgentQuestionCard";
import { AgentMemoryCapture } from "./AgentMemoryCapture";
import { CopyTextButton } from "../components/CopyTextButton";

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
  const [memoryOpen, setMemoryOpen] = useState(false);

  useEffect(() => { setMemoryOpen(false); }, [active?.sessionId]);

  const lie = active ? state.messages[active.sessionId] ?? [] : [];

  // 新会话只靠 session_added 进入前端时不会再有 snapshot。打开面板及每次
  // 状态推进都补拉一次 transcript，避免“执行证据有内容、对话正文为空”。
  useEffect(() => {
    if (active && !api.preview) void store.loadHistory(active.sessionId);
  }, [active?.sessionId, active?.state, api.preview, store.loadHistory]);


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
  const visibleLie = conversationMessages(lie);
  const lastAssistantText = [...visibleLie].reverse()
    .find((m) => m.role === "assistant" && m.kind === "text")?.text.trim() ?? "";
  const showStreaming = Boolean(streaming && streaming.sessionId === active?.sessionId
    && streaming.text.trim() !== lastAssistantText);

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

        {visibleLie.map((m) => (
          // key 用 (sessionId, seq)：messageId 不唯一，一条 AssistantMessage
          // 的多个内容块共用它，拿它当 key React 会报 duplicate key，
          // 并且重渲染时会错认组件身份。
          <Bubble key={`${m.sessionId}:${m.seq}`} m={m} />
        ))}

        {showStreaming && streaming ? (
          <StreamingBubble text={streaming.text} kind={streaming.kind} />
        ) : null}

        {dai.length > 0 || wen.length > 0 ? (
          <div className="agp-decide">
            <div className="agp-decide-head">需要你决定 · {dai.length + wen.length}</div>
            {dai.map((p) => (
              <AgentApprovalCard
                key={p.requestId}
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

        {active && active.state === "ended" && active.batchTotal > 0 && active.batchDone >= active.batchTotal && todo === 0 ? (
          <div className="agp-end">本次委派已结束</div>
        ) : null}
      </div>

      {active && memoryOpen ? <AgentMemoryCapture sessionId={active.sessionId}
        onCandidateCreated={onCandidateCreated} onClose={() => setMemoryOpen(false)} /> : null}

      <AgentComposer
        canSend={Boolean(kai && active)}
        busy={api.busy}
        canInterrupt={Boolean(active) && !["idle", "ended", "attention", "waiting_input"].includes(active!.state)}
        onSend={async (t) => {
          if (!active) throw new Error("还没有可用的 Agent 会话");
          await api.act.send(active.sessionId, { text: t });
        }}
        onInterrupt={() => active && void api.act.interrupt(active.sessionId)}
      />
    </section>
  );
}

function StatusBar({ session, store }: { session: AgentSession | null; store: AgentStore }) {
  const { state } = store;
  const lei = state.lastResult[session?.sessionId ?? ""];
  const st = session?.state ?? null;
  const sid = session?.sessionId ?? null;

  // 本次对话计时（整批口径）：第一批指令开始跑（进入运行态）起算，整批结束
  // （ended / error）或被中断才冻结；多条指令之间经过的瞬间 idle 按暂停处理，
  // 恢复后接着走；等审批、等回答也算对话进行中，照常计时。
  // 旧口径从 session.createdAt 起算——会话建好没发指令也在走，且结束后不停。
  const [, setXin] = useState(0);
  const ji = useRef({ sid: null as string | null, qi: 0, leiJi: 0, ticking: false, tingAt: 0, prev: null as string | null });
  const m = ji.current;
  const pao = st === "thinking" || st === "working" || st === "attention" || st === "waiting_input" || st === "backoff";

  if (sid !== m.sid) {
    // 换会话：计时清零重来。
    m.sid = sid; m.qi = 0; m.leiJi = 0; m.ticking = false; m.tingAt = 0; m.prev = null;
  }
  if (st !== m.prev) {
    const xianzai = Date.now();
    if (pao) {
      if (!m.ticking) {
        // 结束/出错之后、或停下来超过 3 秒之后再跑，算新一轮，归零重计；
        // 批内指令之间的 idle 只有几毫秒，不算新一轮。
        const xinYiLun = m.prev === null || m.prev === "ended" || m.prev === "error"
          || (m.prev === "idle" && m.tingAt > 0 && xianzai - m.tingAt > 3000);
        if (xinYiLun) m.leiJi = 0;
        m.qi = xianzai;
        m.ticking = true;
      }
    } else {
      if (m.ticking) {
        m.leiJi += xianzai - m.qi;
        m.ticking = false;
      }
      m.tingAt = xianzai;
    }
    m.prev = st;
  }

  // 对话进行中每秒走一格；停了就不刷，冻结在最后一格。
  const ticking = m.ticking;
  useEffect(() => {
    if (!ticking) return;
    const jia = setInterval(() => setXin((x) => x + 1), 1000);
    return () => clearInterval(jia);
  }, [ticking]);

  const yong = Math.max(0, Math.round((m.leiJi + (m.ticking ? Date.now() - m.qi : 0)) / 1000));
  return (
    <div className="agp-bar">
      <span className={`pill ${session ? STATE_TONE[session.state] : "idle"} sm`}>
        <span className="dot" />
        {session && (session.state === "thinking" || session.state === "working") ? <span className="agent-spinner small" aria-hidden="true" /> : null}
        {session ? STATE_LABEL[session.state] : CONNECTION_LABEL[state.conn]}
      </span>
      {session && session.batchTotal > 0 ? (
        <span className="mono">第 {session.batchDone}/{session.batchTotal} 条指令</span>
      ) : null}
      {yong > 0 ? <span className="mono">{m.ticking ? `已用 ${yong}s` : `用时 ${yong}s`}</span> : null}
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

function timeText(createdAt: number): string {
  if (!createdAt) return "";
  const date = new Date(createdAt);
  if (Number.isNaN(date.valueOf())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** 结果帧经常与最后一条 assistant 文本完全相同；只保留一条，避免正文重复。 */
export function conversationMessages(messages: AgentMessage[]): AgentMessage[] {
  const assistantTexts = new Set<string>();
  return messages.filter((m) => {
    const text = m.text.trim();
    if (m.role === "assistant" && m.kind === "text" && text) assistantTexts.add(text);
    if (m.kind === "result" && text && assistantTexts.has(text)) return false;
    return true;
  });
}

function MessageFooter({ text, createdAt }: { text: string; createdAt: number }) {
  return (
    <footer className="agent-exchange-footer">
      <time>{timeText(createdAt)}</time>
      {text ? <CopyTextButton text={text} /> : null}
    </footer>
  );
}

export function StreamingBubble({ text, kind }: { text: string; kind: "text" | "thinking" | "tool_use" }) {
  return (
    <article className="agent-exchange assistant streaming" aria-live="polite">
      <div className="agent-exchange-avatar" aria-hidden="true">A</div>
      <div className="agent-exchange-main">
        <div className="agent-exchange-meta">
          <strong>Agent</strong>
          <span>{kind === "thinking" ? "正在思考" : "正在回复"}</span>
          <span className="agent-typing-dot" aria-hidden="true" />
        </div>
        <div className="agent-exchange-bubble agent-streaming-bubble">
          <div className="agent-exchange-text">{text || "…"}</div>
        </div>
      </div>
    </article>
  );
}

export function Bubble({ m }: { m: AgentMessage }) {
  if (m.kind === "tool_use" || m.kind === "tool_result" || m.kind === "thinking" || m.kind === "permission_resolved") {
    const title = m.kind === "tool_use"
      ? `调用工具 · ${m.toolName ?? "工具"}`
      : m.kind === "tool_result"
        ? `工具返回${m.isError ? " · 失败" : ""}`
        : m.kind === "thinking"
          ? "思考过程"
          : "权限决定";
    const text = m.kind === "tool_use" ? toolInputText(m.toolInput) : m.text;
    return (
      <details className={`agent-execution-detail ${m.isError ? "bad" : ""}`}>
        <summary>
          <span>{title}</span>
          <span className="mono">{m.kind}</span>
        </summary>
        {text ? <CopyTextButton text={text} /> : null}
        <pre>{text || "无内容"}</pre>
      </details>
    );
  }

  if (m.kind === "error" || m.kind === "rate_limit" || m.kind === "context_reset") {
    return (
      <div className={`agent-system-note ${m.isError ? "bad" : ""}`} role="status">
        <strong>Agent 提醒</strong>
        <p>{m.text}</p>
      </div>
    );
  }

  if (!m.text.trim()) return null;
  const fromUser = m.role === "user";
  const label = fromUser ? "你" : m.kind === "result" && m.isError ? "执行失败" : "Agent";
  return (
    <article className={`agent-exchange ${fromUser ? "user" : "assistant"}`}>
      {!fromUser ? <div className="agent-exchange-avatar" aria-hidden="true">A</div> : null}
      <div className="agent-exchange-main">
        <div className="agent-exchange-meta">
          <strong>{label}</strong>
          {m.isError ? <span>出错</span> : null}
        </div>
        <div className="agent-exchange-bubble">
          <div className="agent-exchange-text">{m.text}</div>
          <MessageFooter text={m.text} createdAt={m.createdAt} />
        </div>
      </div>
    </article>
  );
}
