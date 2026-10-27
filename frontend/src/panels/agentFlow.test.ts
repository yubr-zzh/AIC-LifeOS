import { describe, expect, it } from "vitest";
import { buildTurns, flowItems, isTurnStart, toolTier } from "./agentFlow";
import type { AgentMessage, AgentToolCall } from "../api/agentTypes";

const m = (a: Partial<AgentMessage> & { messageId: string; seq: number }): AgentMessage => ({
  sessionId: "s-1", role: "assistant", kind: "text", text: "",
  toolUseId: null, toolName: null, toolInput: null,
  isError: false, isPartial: false, createdAt: 0, ...a,
});

const call = (a: Partial<AgentToolCall> & { toolUseId: string; seq: number }): AgentToolCall => ({
  sessionId: "s-1", name: "Read", input: {}, summary: "读取文件",
  state: { type: "completed", isError: false, durationMs: 10 }, resultText: "", ...a,
});

describe("agentFlow", () => {
  it("tool_result 的 role 也是 user，不能当成新一轮", () => {
    expect(isTurnStart(m({ messageId: "a", seq: 1, role: "user", kind: "text" }))).toBe(true);
    expect(isTurnStart(m({ messageId: "b", seq: 2, role: "user", kind: "tool_result" }))).toBe(false);
  });

  it("按用户输入切轮，assistant / 工具归入当前轮", () => {
    const turns = buildTurns(
      [
        m({ messageId: "u1", seq: 1, role: "user", kind: "text", text: "第一问" }),
        m({ messageId: "a1", seq: 2, role: "assistant", kind: "text", text: "第一答" }),
        m({ messageId: "u2", seq: 3, role: "user", kind: "text", text: "第二问" }),
        m({ messageId: "a2", seq: 4, role: "assistant", kind: "text", text: "第二答" }),
      ],
      {},
      "s-1",
    );
    expect(turns).toHaveLength(2);
    expect(turns[0].user?.text).toBe("第一问");
    expect(turns[0].items.map((i) => (i.t === "msg" ? i.m.text : ""))).toEqual(["第一答"]);
    expect(turns[1].user?.text).toBe("第二问");
  });

  it("工具调用落到 seq 所在的那一轮", () => {
    const turns = buildTurns(
      [
        m({ messageId: "u1", seq: 1, role: "user", kind: "text", text: "第一问" }),
        m({ messageId: "u2", seq: 5, role: "user", kind: "text", text: "第二问" }),
      ],
      {
        t1: call({ toolUseId: "t1", seq: 2 }),
        t2: call({ toolUseId: "t2", seq: 7 }),
      },
      "s-1",
    );
    const ids = (i: number) =>
      turns[i].items.flatMap((x) => (x.t === "tool" ? [x.call.toolUseId] : x.t === "group" ? x.calls.map((c) => c.toolUseId) : []));
    expect(ids(0)).toEqual(["t1"]);
    expect(ids(1)).toEqual(["t2"]);
  });

  it("被调用表吸收的 tool 消息不再出现在 items 里", () => {
    const turns = buildTurns(
      [
        m({ messageId: "u1", seq: 1, role: "user", kind: "text", text: "问" }),
        m({ messageId: "t", seq: 2, kind: "tool_use", toolUseId: "t1", toolName: "Read" }),
        m({ messageId: "r", seq: 3, role: "user", kind: "tool_result", toolUseId: "t1", text: "ok" }),
      ],
      { t1: call({ toolUseId: "t1", seq: 2 }) },
      "s-1",
    );
    const kinds = turns[0].items.map((i) => (i.t === "msg" ? i.m.kind : i.t));
    expect(kinds).toEqual(["tool"]);
  });

  it("连续 2 个成功调用合并成组，失败的不合并", () => {
    const items = flowItems([], [
      call({ toolUseId: "a", seq: 1 }),
      call({ toolUseId: "b", seq: 2 }),
      call({ toolUseId: "c", seq: 3, state: { type: "completed", isError: true, durationMs: 1 } }),
    ]);
    expect(items).toHaveLength(2);
    expect(items[0].t).toBe("group");
    expect(items[1].t).toBe("tool");
  });

  it("只读类工具走 progress 档，其余可展开", () => {
    expect(toolTier("Read")).toBe("progress");
    expect(toolTier("Grep")).toBe("progress");
    expect(toolTier("Bash")).toBe("expandable");
    expect(toolTier("Write")).toBe("expandable");
    expect(toolTier("UnknownThing")).toBe("expandable");
  });

  it("没有用户消息的历史也能成轮（user 为 null）", () => {
    const turns = buildTurns(
      [m({ messageId: "a", seq: 1, kind: "text", text: "续写的回答" })],
      {},
      "s-1",
    );
    expect(turns).toHaveLength(1);
    expect(turns[0].user).toBeNull();
  });
});
