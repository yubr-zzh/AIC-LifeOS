import type { AgentMessage, AgentToolCall } from "../api/agentTypes";

/**
 * 工具调用的可见度档位（对齐 VSCode 侧栏的三档设计）。
 *
 * - `progress`：成功时只占一行、**不可交互**。用户不关心读了什么，只关心
 *   「读过了」。一屏 20 个可点的箭头是噪音。
 * - `expandable`：命令/写入这类偶尔需要看细节的调用，可展开输入与结果。
 *
 * 失败 / 等待审批的调用**无视档位**，一律可见且可展开——那是必须处理的信息。
 */
export type ToolTier = "progress" | "expandable";

const PROGRESS_TOOLS = new Set([
  "Read",
  "Grep",
  "Glob",
  "WebFetch",
  "WebSearch",
  "TodoWrite",
  "BashOutput",
]);

export function toolTier(name: string): ToolTier {
  return PROGRESS_TOOLS.has(name) ? "progress" : "expandable";
}

export type FlowItem =
  | { t: "msg"; m: AgentMessage }
  | { t: "tool"; call: AgentToolCall }
  | { t: "group"; calls: AgentToolCall[] };

/** 本轮碰过的上下文（文件 / 搜索模式），用于轮次底部的折叠条。 */
export interface ContextItem {
  label: string;
  kind: "read" | "write" | "search";
}

function str(v: unknown, key: string): string {
  if (!v || typeof v !== "object") return "";
  const x = (v as Record<string, unknown>)[key];
  return typeof x === "string" ? x : "";
}

/**
 * 汇总一轮里用到的上下文。
 *
 * 只取工具输入里的路径/模式，不拼任何 Agent 文本；同名去重后按首次出现排序。
 */
export function contextItems(calls: AgentToolCall[]): ContextItem[] {
  const out: ContextItem[] = [];
  const seen = new Set<string>();
  const push = (label: string, kind: ContextItem["kind"]) => {
    const key = `${kind}:${label}`;
    if (!label || seen.has(key)) return;
    seen.add(key);
    out.push({ label, kind });
  };

  for (const c of calls) {
    const p = str(c.input, "file_path") || str(c.input, "notebook_path");
    if (c.name === "Read" && p) push(p, "read");
    else if ((c.name === "Write" || c.name === "Edit" || c.name === "MultiEdit") && p) push(p, "write");
    else if (c.name === "Glob" || c.name === "Grep") {
      const q = str(c.input, "pattern");
      if (q) push(q, "search");
    }
  }
  return out;
}

/**
 * 一轮对话 = 一次用户输入 + 它触发的全部 assistant / tool / 系统消息。
 *
 * 为什么需要 turn 容器：平铺消息流里找不到「这一轮从哪开始、到哪结束」，
 * 于是没法做「重试这一轮」「复制这一轮」，长会话也失去边界感。
 */
export interface Turn {
  /** 稳定 key：首条消息的 (sessionId, seq)。 */
  key: string;
  /** 触发这一轮的用户消息。老历史可能没有（开头就是 assistant），此时为 null。 */
  user: AgentMessage | null;
  items: FlowItem[];
  startedAt: number;
}

/** 用户消息的判定：**role=user 不够**——tool_result 的 role 也是 user。 */
export function isTurnStart(m: AgentMessage): boolean {
  return m.role === "user" && m.kind === "text";
}

/** 已被 toolCalls 吸收的 tool 消息不再单独渲染。 */
function absorbed(m: AgentMessage, calls: Record<string, AgentToolCall>): boolean {
  return (
    (m.kind === "tool_use" || m.kind === "tool_result" || m.kind === "tool_cancelled") &&
    Boolean(m.toolUseId && calls[m.toolUseId])
  );
}

/**
 * 把「消息流」与「工具调用表」合并成一条时间线。
 *
 * - 丢弃已被调用表吸收的 tool 消息（没有对应调用的保留，兜底老 Bridge）
 * - 按 seq 排序
 * - 相邻的、全部成功完成的调用合并成一组；等待审批 / 失败 / 执行中不合并
 */
export function flowItems(messages: AgentMessage[], calls: AgentToolCall[]): FlowItem[] {
  const items: { seq: number; item: FlowItem }[] = [];
  for (const m of messages) items.push({ seq: m.seq, item: { t: "msg", m } });
  for (const c of calls) items.push({ seq: c.seq, item: { t: "tool", call: c } });
  items.sort((a, b) => a.seq - b.seq);

  const out: FlowItem[] = [];
  let buf: AgentToolCall[] = [];
  const flush = () => {
    if (buf.length >= 2) out.push({ t: "group", calls: buf });
    else for (const c of buf) out.push({ t: "tool", call: c });
    buf = [];
  };

  for (const { item } of items) {
    if (item.t === "tool") {
      const st = item.call.state;
      if (st.type === "completed" && !st.isError) {
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

interface DraftTurn {
  key: string;
  user: AgentMessage | null;
  start: number;
  msgs: AgentMessage[];
  calls: AgentToolCall[];
}

/**
 * 从平铺消息里切出 turn。
 *
 * 纯函数：turns 是 messages 的派生视图，不放进 reducer。放进去就要在
 * 每种帧里同步维护两套结构，容易漂移（快照、补拉、去重三条路径都得记得改）。
 */
export function buildTurns(
  lie: AgentMessage[],
  toolCalls: Record<string, AgentToolCall>,
  sid: string,
): Turn[] {
  const sorted = [...lie].sort((a, b) => a.seq - b.seq);
  const drafts: DraftTurn[] = [];
  let cur: DraftTurn | null = null;

  const open = (user: AgentMessage | null, start: number) => {
    cur = { key: `${sid}:${start}`, user, start, msgs: [], calls: [] };
    drafts.push(cur);
  };

  for (const m of sorted) {
    if (absorbed(m, toolCalls)) continue;
    if (isTurnStart(m)) {
      open(m, m.seq);
      continue;
    }
    if (!cur) open(null, m.seq);
    cur!.msgs.push(m);
  }

  // 只有工具调用、没有任何消息（理论上不该有）：补一个空 turn 兜底。
  const allCalls = Object.values(toolCalls)
    .filter((c) => c.sessionId === sid)
    .sort((a, b) => a.seq - b.seq);
  if (!drafts.length && allCalls.length) open(null, allCalls[0].seq);

  // 调用按 seq 落到「最后一个 start <= call.seq」的 turn 里。
  for (const c of allCalls) {
    let target = drafts[0];
    for (const d of drafts) {
      if (d.start <= c.seq) target = d;
      else break;
    }
    target.calls.push(c);
  }

  return drafts.map((d) => ({
    key: d.key,
    user: d.user,
    startedAt: d.start,
    items: flowItems(d.msgs, d.calls),
  }));
}
