// Agent 域的 mock 数据。
//
// 启用条件只有一个：URL 带 ?agentPreview=1。**Bridge 离线时不回落 mock** ——
// 回落 mock 会让用户看到一份假数据，以为 Agent 在跑而实际什么都没发生。
// 判定逻辑在 useAgentStream.ts。

import type {
  AgentMessage,
  AgentSession,
  AgentsResponse,
  DownFrame,
  PermissionRequest,
} from "./agentTypes";

const T0 = Date.parse("2026-09-27T09:00:00Z");

let seq = 0;
const nextSeq = () => ++seq;

const session: AgentSession = {
  sessionId: "s-mock01",
  agentId: "claude-code",
  agentLabel: "Claude Code",
  cwd: "D:/Github本地/AIC-LifeOS",
  permissionMode: "manual",
  effectiveMode: "manual",
  state: "working",
  title: "Agent 面板预览",
  claudeSessionId: "mock-session",
  ownerId: "local",
  deviceId: "local",
  planId: "plan-mock",
  traceId: "trace-mock",
  batchTotal: 3,
  batchDone: 0,
  createdAt: T0,
  updatedAt: T0,
  turnCount: 1,
  pendingPermissions: [],
  pendingQuestions: [],
  alive: true,
  streamEpoch: 0,
};

export const mockAgents: AgentsResponse = {
  agents: [
    {
      agentId: "claude-code",
      label: "Claude Code",
      available: true,
      version: "2.1.283",
      sdkVersion: "0.2.160",
      error: null,
      canUseTool: true,
      canAskQuestion: true,
    },
  ],
  suggestedDirs: ["D:/Github本地/AIC-LifeOS", "C:/Users/Liuxj/Desktop"],
  versionGate: {
    baseline: "2.1.283",
    sdkBaseline: "0.2.160",
    cliVersion: "2.1.283",
    sdkVersion: "0.2.160",
    mismatch: false,
  },
};

let msgSeq = 0;
const msg = (a: Partial<AgentMessage> & { role: AgentMessage["role"]; kind: AgentMessage["kind"] }): AgentMessage => ({
  messageId: `m-mock${++msgSeq}`,
  sessionId: session.sessionId,
  seq: msgSeq,
  text: "",
  toolUseId: null,
  toolName: null,
  toolInput: null,
  isError: false,
  isPartial: false,
  createdAt: T0 + msgSeq * 1000,
  ...a,
});

const frame = (a: Omit<DownFrame, "streamSeq" | "sessionId"> & { sessionId?: string | null }): DownFrame => {
  const { sessionId, ...rest } = a as { sessionId?: string | null };
  return { sessionId: sessionId ?? session.sessionId, streamSeq: nextSeq(), ...rest } as DownFrame;
};

const approval: PermissionRequest = {
  requestId: "r-mock01",
  sessionId: session.sessionId,
  toolName: "Bash",
  // 指向快照里那条 tool_use，预览模式才能看到审批卡与 ToolStep 互链
  toolUseId: "t-mock1",
  toolInput: { command: "pytest -q tests/", description: "跑一遍测试" },
  title: "运行测试",
  displayName: "Bash",
  description: "由 Agent 自撰，可能与上方命令无关",
  blockedPath: null,
  decisionReason: "工具不在允许列表",
  agentId: "claude-code",
  suggestions: [],
  inputTruncated: false,
  originalByteSize: 46,
  createdAt: T0 + 9000,
  expiresAt: T0 + 9000 + 300_000,
};

/** 脚本化的一整轮：逐条覆盖 11.5 线框里列出的每一种帧。 */
const script: DownFrame[] = [
  frame({
    type: "snapshot",
    sessionId: null,
    instanceId: "i-mock",
    streamEpoch: 0,
    sessions: [{ ...session, state: "idle", batchDone: 0 }],
    messages: [
      msg({ role: "user", kind: "text", text: "指令 1/3：跑一遍测试并修掉失败项" }),
      msg({ role: "assistant", kind: "thinking", text: "先看测试目录的结构，再决定跑哪一条。" }),
      msg({ role: "assistant", kind: "text", text: "我先跑一遍完整测试。" }),
      msg({ role: "assistant", kind: "text", text: [
        "按 **单元 / 集成** 分两批跑，避免一次失败掩盖另一处：",
        "",
        "| 批次 | 命令 | 用例数 |",
        "| --- | --- | --- |",
        "| 单元 | `pytest -q tests/unit` | 118 |",
        "| 集成 | `pytest -q tests/integration` | 14 |",
        "",
        "覆盖率 $\\text{cov} = \\frac{hit}{total}$，这一轮跑到：",
        "",
        "$$",
        "\\frac{132}{135} \\approx 97.8\\%",
        "$$",
        "",
        "```python",
        "def coverage(hit: int, total: int) -> float:",
        "    return hit / total",
        "```",
      ].join("\n") }),
      msg({ role: "assistant", kind: "tool_use", toolName: "Read", toolUseId: "t-mock0",
            toolInput: { file_path: "src/panels/AgentPanel.tsx" }, state: "executing" }),
      msg({ role: "assistant", kind: "tool_use", toolName: "Bash", toolUseId: "t-mock1",
            toolInput: { command: "pytest -q tests/" }, state: "executing" }),
    ],
    pending: [],
    questions: [],
  } as never),
  frame({ type: "state", state: "working", lastEvent: "turn_started" } as never),
  frame({ type: "chunk", messageId: "m-stream1", delta: "测试正在跑", messageKind: "text" } as never),
  frame({ type: "chunk", messageId: "m-stream1", delta: "…预计 40 秒。", messageKind: "text" } as never),
  frame({
    type: "message",
    message: msg({ role: "assistant", kind: "text", text: "测试正在跑…预计 40 秒。" }),
  } as never),
  frame({ type: "permission", request: approval } as never),
  frame({ type: "state", state: "attention", lastEvent: "permission_requested" } as never),
  frame({ type: "permission_resolved", requestId: approval.requestId, decision: "user_allow", autoDecided: false, autoReason: null, replayed: false } as never),
  frame({ type: "state", state: "working", lastEvent: "permission_resolved" } as never),
  frame({
    type: "message",
    message: msg({ role: "user", kind: "tool_result", toolName: "Read", toolUseId: "t-mock0",
                   text: "1.2 KB", state: "completed" }),
  } as never),
  frame({
    type: "message",
    message: msg({ role: "user", kind: "tool_result", toolName: "Bash", toolUseId: "t-mock1",
                   text: "132 passed in 38.21s", state: "completed" }),
  } as never),
  frame({
    type: "question",
    question: {
      questionId: "q-mock01",
      sessionId: session.sessionId,
      toolUseId: "t-mock2",
      questions: [
        {
          header: "修法",
          question: "有 2 个失败项，用哪种修法？",
          multiSelect: false,
          options: [
            { label: "改测试", description: "放宽断言" },
            { label: "改实现", description: "修生产代码" },
          ],
        },
      ],
      state: "pending",
      answers: [],
      createdAt: T0 + 20000,
      expiresAt: T0 + 20000 + 300_000,
    },
  } as never),
  frame({ type: "state", state: "waiting_input", lastEvent: "question_asked" } as never),
  frame({ type: "question_resolved", questionId: "q-mock01", state: "answered", replayed: false } as never),
  frame({ type: "state", state: "working", lastEvent: "question_answered" } as never),
  frame({
    type: "result",
    subtype: "success",
    durationMs: 41230,
    numTurns: 6,
    totalCostUsd: 0.0412,
    isError: false,
    resultText: "已修复 2 个失败项，测试全绿。",
    batchDone: 1,
    batchTotal: 3,
  } as never),
  frame({ type: "agent_status", sessionId: null, agentId: "claude-code", available: true, error: null } as never),
  frame({ type: "error", code: "idle_timeout", message: "会话闲置超时，已自动结束", recoverable: false } as never),
  frame({ type: "state", state: "ended", lastEvent: "idle_timeout" } as never),
];

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** 预览模式下当作 SSE 源用。节奏刻意放慢，好看清每种帧的视觉。 */
export async function* mockFrameStream(): AsyncGenerator<DownFrame> {
  for (const f of script) {
    await sleep(f.type === "chunk" ? 260 : 700);
    yield f;
  }
  // 停在脚本末尾，保持连接活着，让面板维持「已连接」的真实观感。
  while (true) {
    await sleep(30_000);
  }
}
