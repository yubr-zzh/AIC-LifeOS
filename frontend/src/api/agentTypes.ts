// Agent 域的全部 TS 类型。逐字对齐 lifeos/bridge/models.py 与 7.3 的下行帧。
//
// 契约纪律：这里出现的每个字段名都是跨进程线上的名字，Python 端改了这里必须跟着改。
// 症状是「后端发了帧但界面上什么都不动」，而单测全绿——所以真机联调是唯一验收手段。

export type AgentState =
  | "idle"
  | "thinking"
  | "working"
  | "attention"
  | "waiting_input"
  | "backoff"
  | "error"
  | "ended";

/** 会话状态 → 状态色。11.5 的状态条与折叠态细条共用这一张表。 */
export const STATE_TONE: Record<AgentState, string> = {
  idle: "idle",
  thinking: "processing",
  working: "processing",
  attention: "confirm",
  waiting_input: "confirm",
  backoff: "pending",
  error: "failed",
  ended: "done",
};

/** 状态 → 中文标签。界面上不出现裸英文状态词。 */
export const STATE_LABEL: Record<AgentState, string> = {
  idle: "空闲",
  thinking: "思考中",
  working: "执行中",
  attention: "等你决定",
  waiting_input: "等你回答",
  backoff: "退避等待",
  error: "出错",
  ended: "已结束",
};

/** 8.3 闸门 1 的白名单。bypassPermissions 不在列，后端会 400 硬拒。 */
export type PermissionMode = "manual" | "acceptEdits" | "plan" | "auto" | "dontAsk";

export const PERMISSION_MODES: { value: PermissionMode; label: string; hint: string }[] = [
  { value: "manual", label: "每件事都问", hint: "任何工具调用都先给你看，默认选项" },
  { value: "acceptEdits", label: "自动改文件", hint: "写文件直接放行，命令仍然问" },
  { value: "plan", label: "只读不改", hint: "Agent 只能读，不能动你的文件" },
  { value: "auto", label: "尽量自动", hint: "只在危险操作前停下来" },
  { value: "dontAsk", label: "尽量不问", hint: "只在规则明确禁止时停下，风险最高" },
];

export interface AgentSession {
  sessionId: string;
  agentId: string;
  agentLabel: string;
  cwd: string;
  permissionMode: PermissionMode;
  effectiveMode: PermissionMode;
  state: AgentState;
  title: string;
  claudeSessionId: string | null;
  ownerId: string;
  deviceId: string;
  planId: string | null;
  traceId: string | null;
  batchTotal: number;
  batchDone: number;
  createdAt: number;
  updatedAt: number;
  turnCount: number;
  pendingPermissions: string[];
  pendingQuestions: string[];
  alive: boolean;
  streamEpoch: number;
}

export type MessageKind =
  | "text"
  | "thinking"
  | "tool_use"
  | "tool_result"
  /** 用户中断 / 拒绝 / 超时导致调用没有结果。与 tool_result 区分开：
   *  result 是「真的跑完了」，cancelled 是「没跑」。 */
  | "tool_cancelled"
  | "rate_limit"
  | "context_reset"
  | "error"
  | "result"
  | "permission_resolved";

export interface AgentMessage {
  messageId: string;
  sessionId: string;
  seq: number;
  role: "user" | "assistant" | "system";
  kind: MessageKind;
  text: string;
  toolUseId: string | null;
  toolName: string | null;
  toolInput: unknown;
  isError: boolean;
  isPartial: boolean;
  createdAt: number;
  /** Bridge 级全局 streamSeq。可选：旧消息与测试夹具里没有这个字段。 */
  xuhao?: number;
  /** 仅 tool_use / tool_cancelled 有意义。前端不直接渲染它，
   *  只用它初始化 AgentToolCall.state，之后由帧推进。 */
  state?: string;
}

/**
 * 一次工具调用的生命周期。
 *
 * 用判别联合而不是 `state: string` + 一堆可选字段：后者会让
 * 「executing 但 completedAt 有值」这种非法组合变成可表达状态。
 *
 * 与 VSCode 的 IChatToolInvocation.StateKind 对齐，砍掉
 * WaitingForAuthentication（本项目没有 MCP OAuth 路径）。
 */
export type ToolCallState =
  | { type: "streaming"; partialInput: string }
  | { type: "awaiting_confirmation"; requestId: string | null }
  | { type: "executing"; startedAt: number }
  | { type: "awaiting_post_approval"; requestId: string | null }
  | { type: "completed"; isError: boolean; durationMs: number | null }
  | { type: "cancelled"; reason: "denied" | "skipped" | "interrupted" | "expired" };

/**
 * 一次工具调用。**键是 toolUseId，不是 messageId。**
 *
 * 一次调用可以产生多条消息（tool_use 一条、tool_result 一条），
 * 所以 messageId 不能当身份。
 */
export interface AgentToolCall {
  toolUseId: string;
  sessionId: string;
  /** 首次出现的消息 seq，用于在消息流里定位插入位置。 */
  seq: number;
  name: string;
  input: unknown;
  state: ToolCallState;
  /** tool_result 的文本。只在 completed / cancelled 时有意义。 */
  resultText: string;
  /** 渲染用的一行摘要，由前端从 name + input 推导。 */
  summary: string;
}

export interface PermissionRequest {
  requestId: string;
  sessionId: string;
  toolName: string;
  /** SDK 的 tool_use_id。**可选**：老 Bridge 的帧里根本没有这个键，
   *  此时降级为「独立卡片」，不能按空串强行关联。
   *
   *  Claude 路径下 `requestId` 目前恒等于它，但不要依赖这个隐式关系：
   *  其他 adapter 不保证，且缺 id 时后端会用 `t-unknown` 兜底。 */
  toolUseId?: string;
  /** 8.8 的可信字段：原样展示，不加工。 */
  toolInput: Record<string, unknown>;
  /** 8.8 的不可信字段：Agent 自撰，必须折叠并标注来源。 */
  title: string;
  displayName: string;
  description: string;
  blockedPath: string | null;
  decisionReason: string | null;
  agentId: string | null;
  suggestions: unknown[];
  /** 为 true 时禁用「允许」——你看到的命令是被截断过的。 */
  inputTruncated: boolean;
  originalByteSize: number;
  createdAt: number;
  expiresAt: number;
}

export interface PendingQuestion {
  questionId: string;
  sessionId: string;
  toolUseId: string;
  /** AskUserQuestion 的原始结构：[{header, question, multiSelect, options:[{label, description}]}] */
  questions: AgentQuestionItem[];
  state: "pending" | "answered" | "cancelled" | "expired";
  answers: { questionId: string; values: string[] }[];
  createdAt: number;
  expiresAt: number;
}

export interface AgentQuestionItem {
  questionId?: string;
  header?: string;
  question: string;
  multiSelect?: boolean;
  options: { label: string; description?: string }[];
}

export type Decision = "allow" | "deny";

/** permission_resolved 的三种来源要分别显示，11.5 明确要求。 */
export interface PermissionResolution {
  requestId: string;
  decision: Decision | string;
  autoDecided: boolean;
  autoReason: string | null;
  replayed: boolean;
  at: number;
}

// ---- 下行帧 ----
// 分成带会话与全局两种：带会话的帧 sessionId 必非空，reducer 可以直接拿它索引。
// 合成一个 `sessionId: string | null` 会让每个索引点都要先判空，那是类型在说谎。

export interface FrameBase {
  type: string;
  streamSeq: number;
}

export interface ScopedFrame extends FrameBase {
  sessionId: string;
}

export interface GlobalFrame extends FrameBase {
  sessionId: null;
}

export interface SnapshotFrame extends GlobalFrame {
  type: "snapshot";
  instanceId: string;
  streamEpoch: number;
  sessions: AgentSession[];
  /**
   * **阶段 7 域 E 起服务端不再下发这个字段**，历史走 transcript 按需拉。
   * 留着是可选项：预览模式的假帧源（`agentMock.ts`）仍然用它在首帧铺出对话，
   * 省得给假数据也接一套 HTTP。
   */
  messages?: AgentMessage[];
  pending: PermissionRequest[];
  questions: PendingQuestion[];
}

export interface ChunkFrame extends ScopedFrame {
  type: "chunk";
  messageId: string;
  delta: string;
  messageKind: "text" | "thinking" | "tool_use";
}

export interface MessageFrame extends ScopedFrame {
  type: "message";
  message: AgentMessage;
}

export interface StateFrame extends ScopedFrame {
  type: "state";
  state: AgentState;
  lastEvent: string;
  permissionMode?: PermissionMode;
  effectiveMode?: PermissionMode;
}

export interface PermissionFrame extends ScopedFrame {
  type: "permission";
  request: PermissionRequest;
}

export interface PermissionResolvedFrame extends ScopedFrame {
  type: "permission_resolved";
  requestId: string;
  decision: string;
  autoDecided: boolean;
  autoReason: string | null;
  replayed: boolean;
}

export interface QuestionFrame extends ScopedFrame {
  type: "question";
  question: PendingQuestion;
}

export interface QuestionResolvedFrame extends ScopedFrame {
  type: "question_resolved";
  questionId: string;
  state: string;
  replayed: boolean;
}

export interface ResultFrame extends ScopedFrame {
  type: "result";
  subtype: string;
  durationMs: number;
  numTurns: number;
  totalCostUsd: number;
  isError: boolean;
  resultText: string;
  batchDone: number;
  batchTotal: number;
}

export interface SessionAddedFrame extends ScopedFrame {
  type: "session_added";
  session: AgentSession;
}

export interface SessionRemovedFrame extends ScopedFrame {
  type: "session_removed";
}

export interface AgentStatusFrame extends GlobalFrame {
  type: "agent_status";
  agentId: string;
  available: boolean;
  error: string | null;
}

export interface ErrorFrame extends ScopedFrame {
  type: "error";
  code: string;
  message: string;
  recoverable: boolean;
}

/** 前端自己造的流级错误（收到无法解析的帧）。没有会话可言。 */
export interface StreamErrorFrame extends GlobalFrame {
  type: "error";
  code: string;
  message: string;
  recoverable: boolean;
}

/**
 * 网关合成的设备状态帧（spec 9.4）。
 *
 * **`streamSeq` 恒为 0**，且线上格式不带 `id:`：它不在 Bridge 的序号空间里
 * （`ZongXian.fa()` 先自增，首帧的 `streamSeq` 是 1，0 是空号）。reducer 必须让
 * `streamSeq === 0` 的帧绕过单调丢弃规则、也不更新游标。见 `agentStore.gen()`。
 *
 * `state` 之外还有 Bridge 自己发的一份同名帧（带真实序号，走正常路径），
 * 所以这个类型收窄不到 `streamSeq: 0`。
 */
export interface DeviceStatusFrame extends GlobalFrame {
  type: "device_status";
  deviceId: string;
  state: "connected" | "connecting" | "offline" | "error";
  since: number;
  error: string | null;
}

/** 隧道 / 通道形态 → 中文。**界面上不出现裸英文状态词**（照 STATE_LABEL 的纪律）。
 *
 * 取值集对着真实写盘点：默认是 `local`（没注册 runtime.json 的本机直连形态），
 * 隧道形态下由 `tunnel.py` 写 `connecting` / `connected` / `error`，
 * 配对后未建隧道是 `pipei.py` 写的 `none`。多认一个 `offline` 是白纸黑字的
 * 防御——网关的 `zhuang_tai()` 就用这个词，多写一行比读不出来便宜。 */
export const TUNNEL_LABEL: Record<string, string> = {
  local: "本机直连",
  connected: "隧道已连通",
  connecting: "隧道连接中",
  offline: "隧道未连通",
  error: "隧道出错",
  none: "未配对",
};

/** 未知取值要说「未知（值）」而不是把裸串印上去——那读起来像坏了。 */
export function tunnelLabel(a: string | null | undefined): string {
  if (!a) return "—";
  return TUNNEL_LABEL[a] ?? `未知（${a}）`;
}

export interface DelegationUpdateFrame extends ScopedFrame {
  type: "delegation_update";
  planId: string;
  status: string;
  itemStatuses: Record<string, string>;
}

export type DownFrame =
  | SnapshotFrame
  | ChunkFrame
  | MessageFrame
  | StateFrame
  | PermissionFrame
  | PermissionResolvedFrame
  | QuestionFrame
  | QuestionResolvedFrame
  | ResultFrame
  | SessionAddedFrame
  | SessionRemovedFrame
  | AgentStatusFrame
  | ErrorFrame
  | StreamErrorFrame
  | DeviceStatusFrame
  | DelegationUpdateFrame;

// ---- 上行请求体 ----

export interface AgentDescriptor {
  agentId: string;
  label: string;
  available: boolean;
  version: string | null;
  sdkVersion: string | null;
  error: string | null;
  canUseTool: boolean;
  canAskQuestion: boolean;
  moshi?: PermissionMode[];
  yi_ci_xing?: boolean;
  xu_pei_zhuang?: boolean;
  ce_shi?: { ok: boolean; probeMs: number; shuoming: string };
}

export interface VersionGate {
  baseline: string;
  sdkBaseline: string;
  cliVersion: string | null;
  sdkVersion: string | null;
  mismatch: boolean;
  reason?: string;
}

export interface AgentsResponse {
  agents: AgentDescriptor[];
  suggestedDirs: string[];
  /**
   * 这个 uid 的凭据目录（`~/.lifeos-bridge/users/<uid>-<hash>/`）建出来了吗（spec 11.2）。
   *
   * **刻意是可选的**。后端建不出目录时按 11.2「不让 Bridge 起不来」只告警继续跑，
   * 代价是用户落到一个空的凭据库、必须重新登录一次——所以界面上必须把这件事说出来。
   * 但写成必填会有个更坏的病态：**新前端连旧 Bridge 时这个键根本不存在**，
   * 运行时是 `undefined`，而 `!undefined === true` 会把「字段缺失」渲染成
   * 「凭据有问题」——一个凭空造出来的假警报，用户照着去清磁盘、清权限，
   * 查半天什么也没有。三态是唯一的诚实解：`false` 是真故障，`undefined` 是不知道。
   *
   * 与 `AgentDescriptor.available` **不可合并**：那个答的是「装没装 claude CLI」，
   * 处置是装软件；这个答的是「凭据目录建没建出来」，处置是清空间 / 改目录权限。
   * 混起来会把「建不出目录」显示成「没装 claude」——给错提示比不给提示更糟。
   */
  credentialsReady?: boolean;
  /**
   * Bridge 的凭据/配置隔离开着吗（改动三，2026-10-10，`LIFEOS_GELI` 开关）。
   *
   * 同样**刻意可选**：新前端连旧 Bridge 时是 `undefined` = 不知道，
   * 界面对它保持沉默（与 `credentialsReady` 同一个三态理由）。
   * `false`（默认形态）时 harness 直用本机配置——读得到本地 skills、
   * settings.json、CLAUDE.md——`credentialsReady` 对这种形态没有语义，
   * 前端**不许**再为它弹「重新登录」的警报；`true` 才回到隔离形态。
   */
  geli?: boolean;
  versionGate: VersionGate;
}

export interface CreateSessionRequest {
  agentId: string;
  cwd: string;
  title?: string;
  permissionMode?: PermissionMode;
  planId?: string;
  traceId?: string;
  clientIdempotencyKey?: string;
  acknowledgeNoApproval?: boolean;
}

/** 8.2.3：「总是允许」走 updatedPermissions，落点被服务端强制约束。 */
export interface PermissionUpdate {
  type: string;
  behavior?: string;
  mode?: string;
  directories?: string[];
  destination?: "session" | "localSettings" | "projectSettings" | "userSettings";
  rules?: { toolName?: string; ruleContent?: string }[];
}

export interface DecideRequest {
  decision: Decision;
  message?: string;
  updatedInput?: Record<string, unknown>;
  updatedPermissions?: PermissionUpdate[];
}

export interface AnswerRequest {
  answers: { questionId: string; values: string[] }[];
}

export type BridgeErrorCode =
  | "unauthorized"
  | "forbidden"
  | "not_found"
  | "invalid_request"
  | "conflict"
  | "already_resolved"
  | "reset_required"
  | "input_mismatch"
  | "mode_forbidden"
  | "cwd_forbidden"
  | "too_large"
  | "rate_limited"
  | "agent_unavailable"
  | "internal";

export class BridgeError extends Error {
  status: number;
  code: BridgeErrorCode | string;
  payload: Record<string, unknown>;

  constructor(status: number, code: string, message: string, payload: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.payload = payload;
    this.name = "BridgeError";
  }
}

// ---- 委派计划（6.5 / 10.1）----

/** 6.5.1 的生命周期。inflight 之后只能取消剩余的，已下发的不可撤回。 */
export type DelegationStatus =
  | "draft"
  | "approved"
  | "inflight"
  | "done"
  | "failed"
  | "abandoned";

export type DelegationItemStatus =
  | "pending"
  | "inflight"
  | "done"
  | "failed"
  | "skipped";

export interface DelegationItem {
  itemId: string;
  order: number;
  title: string;
  /** R-V1：单条上限 4000 字符，与 Bridge 的 6.5.2 校验同值。 */
  instruction: string;
  dependsOn: string[];
  editable: boolean;
  enabled: boolean;
  status: DelegationItemStatus;
  /** R-V3 连带取消时写在这里，卡上要显示给用户。 */
  note?: string;
}

export interface DelegationPlan {
  planId: string;
  traceId: string;
  ownerId: string;
  summary: string;
  /** null = 让用户在连接表单里选。 */
  targetAgent: string | null;
  /** R-V5：必须落在信任根内，否则建会话时 Bridge 400。 */
  workingDir: string;
  status: DelegationStatus;
  items: DelegationItem[];
  /** R-V2 降级标记：LLM 规划不可用时为 true，UI 必须显示「已降级」，不能静默。 */
  degraded?: boolean;
}

/** 8.2.1 的字节预算：toolInput 超过这个值时后端截断并置 inputTruncated。 */
export const INPUT_BYTE_BUDGET = 64 * 1024;

/** 单条指令 4000 字符上限（6.5.2 的 R-V1），前端先拦一道，省一次往返。 */
export const MAX_INSTRUCTION_CHARS = 4000;

export type ConnectionState =
  | "idle"
  | "connecting"
  | "open"
  | "reconnecting"
  | "offline"
  | "unauthorized";

export const CONNECTION_LABEL: Record<ConnectionState, string> = {
  idle: "未连接",
  connecting: "连接中",
  open: "已连接",
  reconnecting: "重连中",
  offline: "Bridge 未运行",
  unauthorized: "凭据失效",
};
