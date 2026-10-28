import { describe, expect, it } from "vitest";
import { agentReducer, guiState, initialAgentState, type AgentStoreState } from "./agentStore";
import type {
  AgentMessage,
  AgentSession,
  DownFrame,
  PermissionRequest,
} from "../api/agentTypes";

const S = "s-1";

const hui = (a: Partial<AgentSession> = {}): AgentSession => ({
  sessionId: S, agentId: "claude-code", agentLabel: "Claude Code", cwd: "D:/x",
  permissionMode: "manual", effectiveMode: "manual", state: "working", title: "",
  claudeSessionId: null, ownerId: "local", deviceId: "local", planId: null, traceId: null,
  batchTotal: 0, batchDone: 0, createdAt: 0, updatedAt: 0, turnCount: 0,
  pendingPermissions: [], pendingQuestions: [], alive: true, streamEpoch: 0,
  ...a,
});

const msg = (a: Partial<AgentMessage> & { messageId: string; seq: number }): AgentMessage => ({
  sessionId: S, role: "assistant", kind: "text", text: "", toolUseId: null, toolName: null,
  toolInput: null, isError: false, isPartial: false, createdAt: 0, ...a,
});

const perm = (a: Partial<PermissionRequest> = {}): PermissionRequest => ({
  requestId: "r-1", sessionId: S, toolName: "Bash", toolInput: { command: "ls" },
  toolUseId: "", title: "", displayName: "Bash", description: "", blockedPath: null,
  decisionReason: null, agentId: "claude-code", suggestions: [], inputTruncated: false,
  originalByteSize: 2, createdAt: 1000, expiresAt: 301_000, ...a,
});

const run = (a: AgentStoreState, frames: DownFrame[]) =>
  frames.reduce((s, f) => agentReducer(s, { type: "FRAME", frame: f }), a);

const base = (): AgentStoreState => ({
  ...initialAgentState,
  conn: "open",
  sessions: { [S]: hui() },
  order: [S],
  activeSessionId: S,
  lastSeq: 100,
});

describe("toolCalls reducer", () => {
  it("tool_use 建表，tool_result 推进到 completed 并带耗时", () => {
    const s = run(base(), [
      { type: "message", streamSeq: 101, sessionId: S,
        message: msg({ messageId: "m1", seq: 1, kind: "tool_use", toolUseId: "t1",
          toolName: "Read", toolInput: { file_path: "D:/a/b.ts" }, state: "executing", createdAt: 1000 }) },
      { type: "message", streamSeq: 102, sessionId: S,
        message: msg({ messageId: "m2", seq: 2, kind: "tool_result", toolUseId: "t1",
          text: "ok", createdAt: 1320 }) },
    ]);
    const c = s.toolCalls.t1;
    expect(c).toBeTruthy();
    expect(c.name).toBe("Read");
    expect(c.summary).toBe("读取 b.ts");
    expect(c.state.type).toBe("completed");
    if (c.state.type === "completed") {
      expect(c.state.isError).toBe(false);
      expect(c.state.durationMs).toBe(320);
    }
    expect(c.resultText).toBe("ok");
  });

  it("重复的 tool_use（补拉历史）不覆盖已有状态", () => {
    const first = run(base(), [
      { type: "message", streamSeq: 101, sessionId: S,
        message: msg({ messageId: "m1", seq: 1, kind: "tool_use", toolUseId: "t1",
          toolName: "Read", toolInput: {}, state: "executing" }) },
      { type: "message", streamSeq: 102, sessionId: S,
        message: msg({ messageId: "m2", seq: 2, kind: "tool_result", toolUseId: "t1", text: "ok" }) },
    ]);
    const again = agentReducer(first, {
      type: "HISTORY", sid: S,
      messages: [msg({ messageId: "m1", seq: 1, kind: "tool_use", toolUseId: "t1",
        toolName: "Read", toolInput: {}, state: "streaming" })],
    });
    expect(again.toolCalls.t1.state.type).toBe("completed");
  });

  it("permission 帧推到 awaiting_confirmation 并带 requestId", () => {
    const s = run(base(), [
      { type: "message", streamSeq: 101, sessionId: S,
        message: msg({ messageId: "m1", seq: 1, kind: "tool_use", toolUseId: "t1",
          toolName: "Bash", toolInput: { command: "ls" }, state: "streaming" }) },
      { type: "permission", streamSeq: 102, sessionId: S,
        request: perm({ requestId: "r-1", toolUseId: "t1" }) },
    ]);
    const st = s.toolCalls.t1.state;
    expect(st.type).toBe("awaiting_confirmation");
    if (st.type === "awaiting_confirmation") expect(st.requestId).toBe("r-1");
  });

  it("permission_resolved(user_deny) → cancelled/denied", () => {
    const s = run(base(), [
      { type: "message", streamSeq: 101, sessionId: S,
        message: msg({ messageId: "m1", seq: 1, kind: "tool_use", toolUseId: "t1",
          toolName: "Bash", toolInput: {}, state: "streaming" }) },
      { type: "permission", streamSeq: 102, sessionId: S,
        request: perm({ requestId: "r-1", toolUseId: "t1" }) },
      { type: "permission_resolved", streamSeq: 103, sessionId: S,
        requestId: "r-1", decision: "user_deny", autoDecided: false, autoReason: null, replayed: false },
    ]);
    const st = s.toolCalls.t1.state;
    expect(st.type).toBe("cancelled");
    if (st.type === "cancelled") expect(st.reason).toBe("denied");
  });

  it("permission_resolved(user_allow) → executing（Bridge 的取值不是 allow）", () => {
    const s = run(base(), [
      { type: "message", streamSeq: 101, sessionId: S,
        message: msg({ messageId: "m1", seq: 1, kind: "tool_use", toolUseId: "t1",
          toolName: "Bash", toolInput: {}, state: "streaming" }) },
      { type: "permission", streamSeq: 102, sessionId: S,
        request: perm({ requestId: "r-1", toolUseId: "t1" }) },
      { type: "permission_resolved", streamSeq: 103, sessionId: S,
        requestId: "r-1", decision: "user_allow", autoDecided: false, autoReason: null, replayed: false },
    ]);
    expect(s.toolCalls.t1.state.type).toBe("executing");
  });

  it("snapshot 不整表清空：存活会话的调用仍在，pending 修正回 awaiting", () => {
    const seeded = run(base(), [
      { type: "message", streamSeq: 101, sessionId: S,
        message: msg({ messageId: "m1", seq: 1, kind: "tool_use", toolUseId: "t1",
          toolName: "Bash", toolInput: {}, state: "executing" }) },
    ]);
    const after = run(seeded, [
      { type: "snapshot", sessionId: null, streamSeq: 200, instanceId: "i-1", streamEpoch: 0,
        sessions: [hui({ state: "attention" })], messages: [],
        pending: [perm({ requestId: "r-9", toolUseId: "t1" })], questions: [] },
    ]);
    expect(after.toolCalls.t1).toBeTruthy();
    expect(after.toolCalls.t1.state.type).toBe("awaiting_confirmation");
  });

  it("snapshot 丢掉已移除会话的调用", () => {
    const seeded = run(base(), [
      { type: "message", streamSeq: 101, sessionId: S,
        message: msg({ messageId: "m1", seq: 1, kind: "tool_use", toolUseId: "t1",
          toolName: "Read", toolInput: {} }) },
    ]);
    const after = run(seeded, [
      { type: "snapshot", sessionId: null, streamSeq: 200, instanceId: "i-1", streamEpoch: 0,
        sessions: [], messages: [], pending: [], questions: [] },
    ]);
    expect(after.toolCalls.t1).toBeUndefined();
  });

  it("chunk(tool_use) 只写 partial，不动 toolCalls", () => {
    const s = run(base(), [
      { type: "chunk", streamSeq: 101, sessionId: S, messageId: "m1",
        delta: '{"file_path":"D:/a', messageKind: "tool_use" },
    ]);
    expect(Object.keys(s.toolCalls)).toHaveLength(0);
    expect(s.partial.m1.text).toBe('{"file_path":"D:/a');
  });

  it("完整 tool_use 到达时消费同 messageId 的 partial 作为 partialInput", () => {
    const s = run(base(), [
      { type: "chunk", streamSeq: 101, sessionId: S, messageId: "m1",
        delta: '{"file_path":"D:/a', messageKind: "tool_use" },
      { type: "message", streamSeq: 102, sessionId: S,
        message: msg({ messageId: "m1", seq: 1, kind: "tool_use", toolUseId: "t1",
          toolName: "Read", toolInput: {}, state: "streaming" }) },
    ]);
    const st = s.toolCalls.t1.state;
    expect(st.type).toBe("streaming");
    if (st.type === "streaming") expect(st.partialInput).toBe('{"file_path":"D:/a');
    expect(s.partial.m1).toBeUndefined();
  });

  it("tool_result 找不到对应 tool_use 时不崩溃、不新建调用", () => {
    const s = run(base(), [
      { type: "message", streamSeq: 101, sessionId: S,
        message: msg({ messageId: "m1", seq: 1, kind: "tool_result", toolUseId: "ghost", text: "x" }) },
    ]);
    expect(Object.keys(s.toolCalls)).toHaveLength(0);
  });

  it("tool_cancelled → cancelled/interrupted", () => {
    const s = run(base(), [
      { type: "message", streamSeq: 101, sessionId: S,
        message: msg({ messageId: "m1", seq: 1, kind: "tool_use", toolUseId: "t1",
          toolName: "Bash", toolInput: {}, state: "executing" }) },
      { type: "message", streamSeq: 102, sessionId: S,
        message: msg({ messageId: "m2", seq: 2, kind: "tool_cancelled", toolUseId: "t1",
          text: "用户已中断" }) },
    ]);
    const st = s.toolCalls.t1.state;
    expect(st.type).toBe("cancelled");
    if (st.type === "cancelled") expect(st.reason).toBe("interrupted");
  });

  it("question 帧把对应调用推到 awaiting_confirmation", () => {
    const s = run(base(), [
      { type: "message", streamSeq: 101, sessionId: S,
        message: msg({ messageId: "m1", seq: 1, kind: "tool_use", toolUseId: "t1",
          toolName: "AskUserQuestion", toolInput: {}, state: "executing" }) },
      { type: "question", streamSeq: 102, sessionId: S,
        question: { questionId: "q-1", sessionId: S, toolUseId: "t1", questions: [],
          state: "pending", answers: [], createdAt: 0, expiresAt: 0 } },
    ]);
    const st = s.toolCalls.t1.state;
    expect(st.type).toBe("awaiting_confirmation");
  });

  it("guiState 对未知状态降级为 completed", () => {
    expect(guiState(undefined).type).toBe("completed");
    expect(guiState("nonsense").type).toBe("completed");
    expect(guiState("executing").type).toBe("executing");
  });
});
