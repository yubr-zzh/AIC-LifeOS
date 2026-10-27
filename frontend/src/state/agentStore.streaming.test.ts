import { describe, expect, it } from "vitest";
import { agentReducer, initialAgentState, type AgentStoreState } from "./agentStore";
import type { AgentMessage, AgentSession, DownFrame } from "../api/agentTypes";

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

const base = (): AgentStoreState => ({
  ...initialAgentState,
  conn: "open",
  sessions: { [S]: hui() },
  order: [S],
});

const run = (frames: DownFrame[], a: AgentStoreState = base()) =>
  frames.reduce((s, f) => agentReducer(s, { type: "FRAME", frame: f }), a);

const chunk = (messageId: string, delta: string, kind = "text"): DownFrame =>
  ({ type: "chunk", sessionId: S, streamSeq: 1, messageId, delta, messageKind: kind } as DownFrame);

const message = (m: AgentMessage): DownFrame =>
  ({ type: "message", sessionId: S, streamSeq: 2, message: m } as DownFrame);

/**
 * 「同一段答案出现三份」的回归测试。
 *
 * 三个来源：
 * 1. assistant 正文消息
 * 2. Bridge 把 result 帧也落成一条消息（文本与 1 相同）
 * 3. chunk 的 messageId 与最终 messageId 不一致时，partial 永远清不掉，
 *    界面上会多一条永远「正在输出」的正文
 */
describe("流式缓冲的清理", () => {
  it("message 到达时，若某条 partial 的内容已被它覆盖，就丢掉那条 partial", () => {
    const st = run([
      chunk("stream-uuid", "答案是 42。"),
      message(msg({ messageId: "msg-real", seq: 1, text: "答案是 42。" })),
    ]);
    expect(st.partial).toEqual({});
  });

  it("message 的 messageId 与 chunk 一致时也清", () => {
    const st = run([
      chunk("same", "答案是 42。"),
      message(msg({ messageId: "same", seq: 1, text: "答案是 42。" })),
    ]);
    expect(st.partial).toEqual({});
  });

  it("内容不相干的 partial 不能被误删（那是另一条还在流的消息）", () => {
    const st = run([
      chunk("a", "第一段正在写"),
      message(msg({ messageId: "b", seq: 1, text: "另一段完全不同的文字" })),
    ]);
    expect(st.partial.a?.text).toBe("第一段正在写");
  });

  it("tool_use 的 partial_json 缓冲不受影响", () => {
    const st = run([
      chunk("t1", '{"command":"ls"}', "tool_use"),
      message(msg({ messageId: "m", seq: 1, text: "好的" })),
    ]);
    expect(st.partial.t1?.kind).toBe("tool_use");
  });

  it("result 帧到达时清空该会话的正文缓冲", () => {
    const st = run([
      chunk("x", "半截正文"),
      { type: "result", sessionId: S, streamSeq: 3, subtype: "success", durationMs: 1,
        numTurns: 1, totalCostUsd: 0, isError: false, resultText: "",
        batchDone: 1, batchTotal: 1 } as DownFrame,
    ]);
    expect(st.partial).toEqual({});
  });

  it("会话回到 idle 时清空正文缓冲", () => {
    const st = run([
      chunk("x", "半截正文"),
      { type: "state", sessionId: S, streamSeq: 3, state: "idle", lastEvent: "batch_done" } as DownFrame,
    ]);
    expect(st.partial).toEqual({});
  });
});
