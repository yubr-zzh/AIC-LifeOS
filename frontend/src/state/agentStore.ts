// Agent 域的 reducer + 订阅 hook。与现有 store.ts 平行，不混进去。
//
// 依赖方向是单向的 agentStore → store（只读 dataMode），反向不��许。
// 委派结果回流走主 store 的 APPEND_AGENT_SUMMARY。

import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";
import {
  BridgeError,
  type AgentMessage,
  type AgentSession,
  type AgentsResponse,
  type ConnectionState,
  type DelegationPlan,
  type DeviceStatusFrame,
  type DownFrame,
  type PendingQuestion,
  type PermissionRequest,
  type PermissionResolution,
  type ResultFrame,
} from "../api/agentTypes";
import { transcript } from "../api/agentClient";

export interface Notice {
  id: string;
  code: string;
  message: string;
  at: number;
  recoverable: boolean;
}

export interface Partial1 {
  text: string;
  kind: "text" | "thinking" | "tool_use";
  sessionId: string;
}

/** 折叠 / 双栏。overlay 是 CSS 在窄屏下的呈现，不是 JS 状态（11.3 规则 2）。 */
export type AgentLayout = "collapsed" | "split";

/**
 * 一条等着回流到 LifeOS 对话的结果。
 *
 * 7.7.1 要求「Agent 每条指令的结果以独立一条消息回到左侧对话」，
 * 但 agentStore 不能反向 import 主 store（单向依赖）。所以结果先落在
 * 这儿，由同时持有两者的那一层取走。seq 单调递增，供消费方判断有没有新的。
 */
export interface AgentReport {
  seq: number;
  sessionId: string;
  title: string;
  traceId: string | null;
}

export interface AgentStoreState {
  conn: ConnectionState;
  connMsg: string | null;
  instanceId: string | null;
  lastSeq: number;
  sessions: Record<string, AgentSession>;
  order: string[];
  messages: Record<string, AgentMessage[]>;
  partial: Record<string, Partial1>;
  pending: Record<string, PermissionRequest>;
  resolved: Record<string, PermissionResolution>;
  questions: Record<string, PendingQuestion>;
  questionClosed: Record<string, { state: string; at: number }>;
  lastResult: Record<string, ResultFrame>;
  /** 7.7.1：已经产出过回报的 (sessionId → batchDone)。防止同一批回流两次。 */
  reported: Record<string, number>;
  /** 7.7.1：等主 store 领走的结果。agentStore 不认识主 store，只能放在这儿等人取。 */
  report: AgentReport | null;
  agentStatus: Record<string, { available: boolean; error: string | null }>;
  notices: Notice[];
  /**
   * 当前设备的隧道状态。`state` 引用 `DeviceStatusFrame` 的取值集，
   * **不是 `string`**——写成 `string` 的话，往 `DeviceStatusFrame` 加第五个值
   * 编译器不会提醒 `DeviceBanner` 漏了分支（`AgentPanel` 用的是相等比较）。
   */
  device: { deviceId: string; state: DeviceStatusFrame["state"]; since: number; error: string | null } | null;
  catalog: AgentsResponse | null;
  layout: AgentLayout;
  /** 用户手动切过布局就别再自动收回——11.7 的自动收回只对没动过的人生效。 */
  manualLayout: boolean;
  activeSessionId: string | null;
  /**
   * 最后一次**快照**的 streamSeq（域 E）。补拉历史的触发源是它，**不是 `lastSeq`**：
   * `lastSeq` 每一帧都推进（chunk 也占号），挂在它上面等于长答案流式输出期间
   * 每帧对每个 sid 重拉一次全量历史，而且那次请求的 `from` 读的是还没渲染的
   * `stateRef.current`，会重复请求刚消费过的游标。
   */
  lastSnapshotSeq: number;
}

export const initialAgentState: AgentStoreState = {
  conn: "idle",
  connMsg: null,
  instanceId: null,
  lastSeq: 0,
  sessions: {},
  order: [],
  messages: {},
  partial: {},
  pending: {},
  resolved: {},
  questions: {},
  questionClosed: {},
  lastResult: {},
  agentStatus: {},
  notices: [],
  device: null,
  catalog: null,
  reported: {},
  report: null,
  layout: "collapsed",
  manualLayout: false,
  activeSessionId: null,
  lastSnapshotSeq: 0,
};

export type AgentAction =
  | { type: "CONN"; conn: ConnectionState; msg?: string | null }
  | { type: "CATALOG"; catalog: AgentsResponse | null }
  | { type: "LAYOUT"; layout: AgentLayout; manual?: boolean }
  | { type: "ACTIVE"; sessionId: string | null }
  | { type: "DISMISS_NOTICE"; id: string }
  | { type: "SESSION"; session: AgentSession }
  | { type: "FRAME"; frame: DownFrame }
  /** 历史补齐（阶段 7 域 E）：transcript 拉回来的一批并进 messages。 */
  | { type: "HISTORY"; sid: string; messages: AgentMessage[] }
  /** 游标作废（Bridge 重启过）：清掉该会话的 messages，等重拉。 */
  | { type: "HISTORY_RESET"; sid: string };

function setZhan(a: AgentStoreState, hui: AgentSession): AgentStoreState {
  const dui = a.sessions[hui.sessionId];
  return {
    ...a,
    sessions: { ...a.sessions, [hui.sessionId]: hui },
    order: dui ? a.order : [hui.sessionId, ...a.order],
    activeSessionId: a.activeSessionId ?? hui.sessionId,
  };
}

/** 还有多少件事在等用户决定。这是折叠态红点与审批条的唯一判据。 */
export function daiJueDing(a: AgentStoreState): number {
  let n = 0;
  for (const k in a.pending) if (!a.resolved[k]) n += 1;
  for (const k in a.questions) if (!a.questionClosed[k]) n += 1;
  return n;
}

/**
 * 这一批跑完了没有。
 *
 * 7.7.1 要求每条指令的结果都回流到左栏。**完成数推进了才算新结果**——
 * 客户端重连时会反复收到覆盖同一批的快照，不卡这个门槛的话左栏会被同一批
 * 结果刷满。`batchDone` 为 0 的回合（还没下发）不产生回报。
 */
function chong(a: AgentStoreState, sid: string, done: number): boolean {
  return done >= 1 && done > (a.reported[sid] ?? 0);
}

function gen(a: AgentStoreState, f: DownFrame): AgentStoreState {
  // **合成帧（streamSeq === 0）短路。** 它是网关造的传输层状态，不在 Bridge 的
  // 序号空间里（spec 9.4：`ZongXian.fa()` 先自增，首帧是 1，0 是空号）。走下面的
  // 单调规则的话它会被「序号不增」静默丢掉，界面永远显示不出「设备离线」，
  // 而服务端一切正常；更新游标的话会把真实序号踩坏（把 40 压回 0，
  // 于是重连时 lastEventId 退到 0，Bridge 整段重放）。
  if (f.type === "device_status" && f.streamSeq === 0) {
    return { ...a, device: { deviceId: f.deviceId, state: f.state, since: f.since, error: f.error } };
  }
  // 去重：snapshot 是全量基线，它之后到达的补发帧 seq 更小，必须丢掉，
  // 否则同一条审批会渲染两次。streamSeq <= 0 的是前端自己造的帧（解析失败之类），
  // 不参与去重。
  //
  // **snapshot 只在严格旧于游标时才丢。** Bridge 的 duibi 让快照上报当前游标而不
  // 新占序号（它是一次全量报告，不是事件），于是重连时快照的 seq 常常正好等于
  // 客户端的 lastSeq。用 `<=` 一律丢的话基线就没了，界面从此冻结——
  // 症状是「Agent 明明卡在审批上，界面上什么都没有」。快照是幂等的，
  // 重复应用同一份全量状态没有副作用。
  const guoqi = f.type === "snapshot" ? f.streamSeq > 0 && f.streamSeq < a.lastSeq
                                      : f.streamSeq > 0 && f.streamSeq <= a.lastSeq;
  if (guoqi) return a;
  const base = f.streamSeq > a.lastSeq ? { ...a, lastSeq: f.streamSeq } : a;

  switch (f.type) {
    case "snapshot": {
      const sessions: Record<string, AgentSession> = {};
      for (const s of f.sessions) sessions[s.sessionId] = s;
      const pending: Record<string, PermissionRequest> = {};
      for (const p of f.pending) pending[p.requestId] = p;
      const questions: Record<string, PendingQuestion> = {};
      for (const q of f.questions) questions[q.questionId] = q;
      // 快照只说「此刻有哪些会话、哪些待处理」——**它不带消息了**（阶段 7 域 E）。
      // 历史走 transcript 按需拉（见 `useAgentStore` 的 `loadHistory`），所以这里
      // **不整份替换 messages**：照旧整份替换会把正在流式输出的会话清空，而拉回来
      // 要等一个网络往返——症状是刷新一下，正在跑的那段对话就没了。
      // 已有的一条全留（随后按 sid 并进 transcript 拉回来的），帧里真带了消息
      // （预览模式的假帧源走的就是这条路）则并进来。
      // 会话表被快照换掉了，某个 sid 不在了，它的 messages 一起清掉（不留孤儿）。
      const messages: Record<string, AgentMessage[]> = {};
      for (const k in a.messages) if (sessions[k]) messages[k] = a.messages[k];
      for (const m of f.messages ?? []) (messages[m.sessionId] ??= []).push(m);
      for (const k in messages) {
        const biao = new Map<string, AgentMessage>();
        for (const m of messages[k]) biao.set(`${m.seq}:${m.messageId}`, m);
        messages[k] = [...biao.values()].sort((x, y) => x.seq - y.seq);
      }
      let reported = base.reported;
      let report = base.report;
      for (const s of f.sessions) {
        if (!chong({ ...base, reported }, s.sessionId, s.batchDone)) continue;
        reported = { ...reported, [s.sessionId]: s.batchDone };
        report = {
          seq: f.streamSeq,
          sessionId: s.sessionId,
          traceId: s.traceId,
          title: `委派完成 · 第 ${s.batchDone}/${s.batchTotal || "?"} 条`,
        };
      }
      return {
        ...base,
        instanceId: f.instanceId,
        sessions,
        order: f.sessions.map((s) => s.sessionId),
        messages,
        partial: {},
        pending,
        questions,
        reported,
        report,
        // 补拉历史的触发标记。**必须写在这个分支里、`guoqi` 那道 guard 之后**：
        // 写在 guard 之前会被去重挡掉，等序的重连快照（streamSeq === lastSeq，
        // 见上面）就不再触发补拉，断线期间漏掉的历史永远补不回来。快照是幂等的，
        // 同一个 seq 重复写同一个值不会引发第二次 effect。
        lastSnapshotSeq: f.streamSeq,
        layout: daiJueDing({ ...base, pending, questions }) > 0 ? "split" : a.layout,
        activeSessionId: a.activeSessionId ?? f.sessions[0]?.sessionId ?? null,
      };
    }

    case "chunk": {
      const dui = base.partial[f.messageId];
      const duiLie = base.messages[f.sessionId]?.find((m) => m.messageId === f.messageId);
      // 完整帧已经到了就别再往尾巴上追加（重连补发时会发生）。
      if (duiLie) return base;
      return {
        ...base,
        partial: {
          ...base.partial,
          [f.messageId]: {
            sessionId: f.sessionId,
            kind: f.messageKind,
            text: (dui?.text ?? "") + f.delta,
          },
        },
      };
    }

    case "message": {
      const m = f.message;
      const lie = base.messages[m.sessionId] ?? [];
      // 按会话内 seq 定位，**不能按 messageId**：SDK 的一条 AssistantMessage
      // 可以带多个内容块（thinking + text，或 text + tool_use），它们共用同一个
      // message_id。按 messageId 替换会把同一消息的另一个块整体顶掉，症状是
      // 「Agent 明明调了工具，界面上看不到 tool_use」。seq 由 tian_jia 在锁内
      // 单调分配，一条记录一个，重连补发时也保持原值。
      const yi = lie.some((x) => x.seq === m.seq && x.messageId === m.messageId);
      const partial = { ...base.partial };
      delete partial[m.messageId];
      const hui = base.sessions[m.sessionId];
      return {
        ...base,
        partial,
        messages: {
          ...base.messages,
          [m.sessionId]: yi
            ? lie.map((x) => (x.seq === m.seq && x.messageId === m.messageId ? m : x))
            : [...lie, m],
        },
        sessions: hui ? { ...base.sessions, [m.sessionId]: { ...hui, updatedAt: m.createdAt } } : base.sessions,
      };
    }

    case "state": {
      const hui = base.sessions[f.sessionId];
      if (!hui) return base;
      return {
        ...base,
        sessions: {
          ...base.sessions,
          [f.sessionId]: {
            ...hui,
            state: f.state,
            permissionMode: f.permissionMode ?? hui.permissionMode,
            effectiveMode: f.effectiveMode ?? hui.effectiveMode,
            updatedAt: Date.now(),
          },
        },
      };
    }

    case "session_added":
      return setZhan(base, f.session);

    case "session_removed": {
      const messages = { ...base.messages };
      const sessions = { ...base.sessions };
      delete messages[f.sessionId];
      delete sessions[f.sessionId];
      return {
        ...base,
        sessions,
        messages,
        order: base.order.filter((x) => x !== f.sessionId),
        activeSessionId: base.activeSessionId === f.sessionId ? null : base.activeSessionId,
      };
    }

    case "permission":
      // 审批会阻塞 Agent。折叠态下把它藏起来等于把「同意」变成「可遗忘」，
      // 所以这一帧强制把面板推到双栏（11.7）。
      return {
        ...base,
        layout: "split",
        pending: { ...base.pending, [f.request.requestId]: f.request },
        sessions: base.sessions[f.sessionId]
          ? { ...base.sessions, [f.sessionId]: { ...base.sessions[f.sessionId], state: "attention" } }
          : base.sessions,
      };

    case "permission_resolved":
      return {
        ...base,
        resolved: {
          ...base.resolved,
          [f.requestId]: {
            requestId: f.requestId,
            decision: f.decision,
            autoDecided: f.autoDecided,
            autoReason: f.autoReason,
            replayed: f.replayed,
            at: Date.now(),
          },
        },
      };

    case "question":
      return {
        ...base,
        layout: "split",
        questions: { ...base.questions, [f.question.questionId]: f.question },
        sessions: base.sessions[f.sessionId]
          ? { ...base.sessions, [f.sessionId]: { ...base.sessions[f.sessionId], state: "waiting_input" } }
          : base.sessions,
      };

    case "question_resolved":
      return { ...base, questionClosed: { ...base.questionClosed, [f.questionId]: { state: f.state, at: Date.now() } } };

    case "result": {
      const next: AgentStoreState = { ...base, lastResult: { ...base.lastResult, [f.sessionId]: f } };
      const hui = next.sessions[f.sessionId];
      if (hui) {
        next.sessions = {
          ...next.sessions,
          [f.sessionId]: { ...hui, batchDone: f.batchDone, batchTotal: f.batchTotal || hui.batchTotal },
        };
      }
      // 7.7.1 的左侧回报。只带结构化字段——Agent 的正文在右栏，搬过来就是重复，
      // 而且 8.8 的可信字段也不该由 Agent 自己书写。seq 用帧序号，天然唯一且递增。
      if (chong(base, f.sessionId, f.batchDone)) {
        next.reported = { ...base.reported, [f.sessionId]: f.batchDone };
        next.report = {
          seq: f.streamSeq,
          sessionId: f.sessionId,
          traceId: hui?.traceId ?? null,
          title: f.isError
            ? `委派中断 · ${f.subtype} · 第 ${f.batchDone}/${f.batchTotal || "?"} 条 · 耗时 ${Math.round(f.durationMs / 100) / 10}s`
            : `委派完成 · 第 ${f.batchDone}/${f.batchTotal || "?"} 条 · ${f.numTurns} 回合 · 耗时 ${Math.round(f.durationMs / 100) / 10}s`,
        };
      }
      // 整批跑完且没有待决定 → 自动收回折叠。用户手动切过就不动。
      if (f.batchTotal > 0 && f.batchDone >= f.batchTotal && !next.manualLayout && daiJueDing(next) === 0) {
        next.layout = "collapsed";
      }
      return next;
    }

    case "agent_status":
      return { ...base, agentStatus: { ...base.agentStatus, [f.agentId]: { available: f.available, error: f.error } } };

    case "device_status":
      return {
        ...base,
        device: { deviceId: f.deviceId, state: f.state, since: f.since, error: f.error },
      };

    case "error": {
      const notice: Notice = {
        id: `n-${f.streamSeq}-${f.code}`,
        code: f.code,
        message: f.message,
        at: Date.now(),
        recoverable: f.recoverable,
      };
      return { ...base, notices: [...base.notices.filter((n) => n.id !== notice.id), notice].slice(-6) };
    }

    default:
      return base;
  }
}

export function agentReducer(a: AgentStoreState, action: AgentAction): AgentStoreState {
  switch (action.type) {
    case "CONN":
      return { ...a, conn: action.conn, connMsg: action.msg ?? null };
    case "CATALOG":
      return { ...a, catalog: action.catalog };
    case "LAYOUT":
      return { ...a, layout: action.layout, manualLayout: action.manual ?? a.manualLayout };
    case "ACTIVE":
      return { ...a, activeSessionId: action.sessionId };
    case "DISMISS_NOTICE":
      return { ...a, notices: a.notices.filter((n) => n.id !== action.id) };
    case "SESSION":
      // 建会话的响应先于 session_added 帧到达，用它把卡片立刻铺上。
      return setZhan(a, action.session);
    case "FRAME":
      return gen(a, action.frame);
    case "HISTORY": {
      const lie = a.messages[action.sid] ?? [];
      // 按 (seq, messageId) 去重再按 seq 排序。
      // **两条消息可以共用 messageId**（SDK 的一条 AssistantMessage 带多个内容块），
      // 只按 messageId 去重会把另一块顶掉；按 seq 去重则会把同一 seq 的两个块
      // 合成一个。用 (seq, messageId) 两者都对，且和 `message` 帧的定位口径一致。
      const biao = new Map<string, AgentMessage>();
      for (const m of lie) biao.set(`${m.seq}:${m.messageId}`, m);
      for (const m of action.messages) biao.set(`${m.seq}:${m.messageId}`, m);
      const he = [...biao.values()].sort((x, y) => x.seq - y.seq || (x.messageId < y.messageId ? -1 : 1));
      return { ...a, messages: { ...a.messages, [action.sid]: he } };
    }
    case "HISTORY_RESET": {
      // Bridge 重启过，旧游标作废。**清空等重拉，不能静默吞掉 409。**
      // 留着旧 messages 等于让界面显示一份根本不属于当前进程的历史，而 Agent
      // 还在继续跑——用户看到的对话与实际状态对不上。
      const messages = { ...a.messages };
      delete messages[action.sid];
      return { ...a, messages };
    }
    default:
      return a;
  }
}

// ---- 布局持久化（11.3 规则 3：主 store 刷新即丢，agentLayout 单独存）----

const LAYOUT_KEY = "lifeos.agentLayout";

export function duquLayout(): AgentLayout {
  try {
    return localStorage.getItem(LAYOUT_KEY) === "split" ? "split" : "collapsed";
  } catch {
    return "collapsed";
  }
}

export function cunLayout(a: AgentLayout): void {
  try {
    localStorage.setItem(LAYOUT_KEY, a);
  } catch {
    /* 隐私模式下写不了，布局退回不持久化，不影响功能 */
  }
}

/**
 * 拉一批历史并并进 messages。**游标由调用方算好传进来**（服务端给的 `xuhao`，
 * 前端不猜——猜错了就是重复渲染或漏消息）。
 *
 * `opt.from` 缺省即首屏（取末尾 N 条，看的是最近在说什么）；给了 `before` 就是
 * 向上翻（取该窗口末尾 N 条，插到前面）；给了 `from` 就是增量追赶（取该窗口
 * **最早** N 条——断线一次可能进来 200 条，取末尾会把中间 150 条静默跳过去）。
 * **limit 不在前端定死**，服务端钳（默认 50，上限 50）。
 *
 * **失败绝不清空已有 messages。** 网络抖动不该让对话消失——这是最容易被顺手写成
 * 「catch 里重置 store」的一处。
 *
 * **409 `reset_required` 是唯一的例外，也是唯一不能静默吞掉的。** Bridge 重启过，
 * 旧 xuhao 全部作废：那份历史根本不属于当前进程，留着就是让界面显示一份对不上
 * 实际状态的内容，而 Agent 还在继续跑。所以清空该 sid 并**从 from=0 重拉一次**。
 * 重拉写成显式的一次重试而不是递归回去重走 `loadHistory`——那里读的是
 * `stateRef.current`，而 dispatch 之后 React 还没重渲染，读到的仍是刚被清掉的
 * 那份旧值，于是又用旧游标发一次、再拿回一个 409，无限循环。
 *
 * **不阻塞 SSE。** 这是异步补齐，流式帧照常上屏。
 *
 * 返回游标（`prevBefore === null` 表示这一批是空的，没有可翻的更早消息），
 * 失败时返回 null。
 */
export async function laPi(
  sid: string,
  opt: { from?: number; before?: number; limit?: number },
  dispatch: (a: AgentAction) => void,
): Promise<{ prevBefore: number | null; hasMore: boolean } | null> {
  try {
    const r = await transcript(sid, opt.from ?? 0, {
      limit: opt.limit,
      before: opt.before,
    });
    dispatch({ type: "HISTORY", sid, messages: r.messages });
    return { prevBefore: r.prevBefore, hasMore: r.hasMore };
  } catch (e) {
    if (e instanceof BridgeError && e.code === "reset_required") {
      dispatch({ type: "HISTORY_RESET", sid });
      // 重拉这一次也可能失败（Bridge 刚起来还没就绪）。**吞掉它**：
      // messages 已经清空了，下一个快照会重来一遍；让异常从这里抛出去的话，
      // 调用点 `void loadHistory(...)` 会变成一条没人接的 promise 拒绝。
      try {
        const r2 = await transcript(sid, 0);
        dispatch({ type: "HISTORY", sid, messages: r2.messages });
        return { prevBefore: r2.prevBefore, hasMore: r2.hasMore };
      } catch {
        return null;
      }
    }
    return null;
  }
}

/**
 * 补拉一条会话的历史。`before: true` 是向上翻。
 *
 * `lao` 记着「这条会话已经翻到顶了没有」：服务端 `hasMore=false` 之后前端就不再
 * 发向上翻的请求，否则每滚一次就多一次空往返。
 */
export function useAgentStore() {
  const [state, dispatch] = useReducer(agentReducer, initialAgentState);
  const stateRef = useRef(state);
  stateRef.current = state;

  const lastSeq = useCallback(() => stateRef.current.lastSeq, []);

  const laiZhong = useRef<Record<string, boolean>>({});
  const lao = useRef<Record<string, boolean>>({});

  const loadHistory = useCallback(
    async (sid: string, opt?: { before?: boolean }): Promise<void> => {
      if (!sid || laiZhong.current[sid]) return;
      // 闸门只认「确实到顶了」（false），**不认「还不知道」**（undefined）。
      // 写成 `!lao.current[sid]` 的话 undefined 与 false 同义——首屏那次拉取失败
      // （返回 null，不写 lao）之后，向上翻就被永久关掉，症状同样是「往上滚没反应」。
      // 多发的那一次请求由它自己的响应收口：空批次 ⇒ hasMore=false ⇒ 门关上。
      if (opt?.before && lao.current[sid] === false) return; // 翻到顶了，不发空请求
      const lie = stateRef.current.messages[sid] ?? [];
      // `xuhao` 在类型上是可选的（帧里没带的那些消息），缺了就当 0——首屏语义。
      const before = opt?.before && lie.length > 0 ? lie[0].xuhao : undefined;
      const from = opt?.before ? 0 : (lie.length > 0 ? lie[lie.length - 1].xuhao ?? 0 : 0);
      // **服务端只在「from>0 且没给 before」时把 hasMore 算成「后面还有」**，
      // 其余（首屏 from=0、向上翻）都是「前面还有」。`from` 在向上翻时恒为 0，
      // 所以判据落在 from 上就够了：增量追赶的 hasMore 语义与向上翻**相反**，
      // 写进 lao 就是把向上翻永久短路——一次追干净的增量（hasMore=false）会让
      // lao[sid]=false，此后每次上滚都被第二行挡掉，症状是「往上滚没反应」，
      // 直到刷新页面。首屏（from=0）必须写：那正是「前面还有」语义，它让短会话
      // 在首屏就翻到顶。
      const zhui = from > 0;
      laiZhong.current[sid] = true;
      try {
        const r = await laPi(sid, { from, before }, dispatch);
        // **不看 prevBefore**：空批次照样写。空批次的 hasMore 本身就是「前面没有
        // 了」，写进去让「lao[sid] === false ⇒ 确实到顶了」由构造保证，而不是
        // 靠论证——旧代码在空批次时保持旧值，那条不变式只是碰巧成立。
        if (r && !zhui) lao.current[sid] = r.hasMore;
      } finally {
        laiZhong.current[sid] = false;
      }
    },
    [dispatch],
  );

  /**
   * 快照到达时补一次历史。**触发源是快照标记 `lastSnapshotSeq`，不是 `lastSeq`。**
   *
   * `lastSeq` 每一帧都推进——`gen()` 在 switch 之前就更新它，而服务端对**每一个**
   * 帧（含按 delta 逐条发出的 chunk）都自增 streamSeq。挂在它上面等于长答案流式
   * 输出期间每来一个 chunk 就对每个 sid 重发一次 transcript，而且每次都从**还没
   * 渲染的** `stateRef.current` 算 `from`，那个 HISTORY dispatch 尚未生效 ⇒
   * 重复请求刚消费过的游标。
   *
   * 依赖里也**不能带 `state.sessions`**：它是个每帧新建的对象（message 帧会
   * `sessions: { ...base.sessions }`），带上去是同一个 bug 的另一条路。
   * 读 `stateRef.current.sessions` 就够了——effect 只在快照标记推进时跑，那一刻
   * `state` 与 `stateRef.current` 是同一个对象；快照是整张会话表全量替换，
   * 所以读到的一定是那一刻的全量 sid 集合。
   *
   * 快照是 SSE 的第一帧（首次连接与每次重连都是它），所以它同时覆盖三件事：
   * 首屏、刷新后重连、以及断线期间漏掉的帧（那批由 `from` 增量追）。
   */
  useEffect(() => {
    if (state.lastSnapshotSeq === 0) return;
    for (const sid in stateRef.current.sessions) void loadHistory(sid);
  }, [state.lastSnapshotSeq, loadHistory]);

  /**
   * 新会话的补拉触发点。
   *
   * `session_added` 会先把会话放进 state.order，但不会触发 snapshot——如果只在
   * snapshot 上补 history，从当前页面新建的会话正文会一直是空的，而执行证据
   * 接口却能返回内容，看起来就像“所有输出都跑进了提炼记忆”。这里按会话集合
   * 识别首次出现，立即拉一次 transcript；同一 sid 后续的状态推进不重复触发。
   */
  const seenSessions = useRef<Set<string>>(new Set());
  useEffect(() => {
    const current = new Set(state.order);
    for (const sid of current) {
      if (!seenSessions.current.has(sid)) void loadHistory(sid);
    }
    seenSessions.current = current;
  }, [state.order, loadHistory]);

  /** 向上翻：拿更早的一批插到前面。`hasMore=false` 时上面那层直接短路。 */
  const loadOlder = useCallback((sid: string) => loadHistory(sid, { before: true }), [loadHistory]);

  const setLayout = useCallback((a: AgentLayout, manual = true) => {
    if (manual) cunLayout(a);
    dispatch({ type: "LAYOUT", layout: a, manual });
  }, []);

  const active = state.activeSessionId ? state.sessions[state.activeSessionId] ?? null : null;

  const todo = useMemo(() => daiJueDing(state), [state]);

  /** 流式中的那条消息，用于自动滚动跟随（不能用 messages.length 做依赖）。 */
  const streaming = useMemo(() => {
    const lie = Object.entries(state.partial);
    if (lie.length === 0) return null;
    const [id, p] = lie[lie.length - 1];
    return { messageId: id, len: p.text.length, sessionId: p.sessionId, text: p.text, kind: p.kind };
  }, [state.partial]);

  return { state, dispatch, lastSeq, loadHistory, loadOlder, setLayout, active, todo, streaming };
}

export type AgentStore = ReturnType<typeof useAgentStore>;

/** 委派计划挂在主 store 的 ChatMessage 上，这里是它与 Agent 域之间的桥。 */
export type DelegationBridge = (a: DelegationPlan, b: string) => void;
