import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { agentReducer, initialAgentState, laPi, useAgentStore, type AgentStoreState } from "./agentStore";
import * as agentClient from "../api/agentClient";
import { BridgeError, type AgentMessage, type AgentSession, type DownFrame } from "../api/agentTypes";

/**
 * 阶段 7 域 E：snapshot 不再带消息，历史全走 transcript 按需拉。
 *
 * **判据落在「两种实现真的会分岔的那个量」上。**
 * 「刷新后右栏非空」不足以证明接上了——一个首屏取最早 N 条的实现也满足它，
 * 而那正是被砍掉的那条能力（打开 500 条的长会话看到的是会话开头）。
 * 所以这里直接断言**请求里带了什么游标**与**并进来之后是哪几条**。
 */

const S = "s-1";

const hui: AgentSession = {
  sessionId: S, agentId: "claude-code", agentLabel: "Claude Code", cwd: "D:/x",
  permissionMode: "manual", effectiveMode: "manual", state: "idle", title: "",
  claudeSessionId: null, ownerId: "local", deviceId: "local", planId: null, traceId: null,
  batchTotal: 0, batchDone: 0, createdAt: 0, updatedAt: 0, turnCount: 0,
  pendingPermissions: [], pendingQuestions: [], alive: true, streamEpoch: 0,
};

const msg = (a: Partial<AgentMessage> & { messageId: string; seq: number }): AgentMessage => ({
  sessionId: S, role: "assistant", kind: "text", text: "", toolUseId: null, toolName: null,
  toolInput: null, isError: false, isPartial: false, createdAt: 0, ...a,
});

/** 走真 reducer：dispatch 什么就真算出下一个 state。 */
const zhenStore = () => {
  let state: AgentStoreState = { ...initialAgentState };
  return {
    get state() { return state; },
    dispatch: (x: Parameters<typeof agentReducer>[1]) => { state = agentReducer(state, x); },
  };
};

describe("snapshot 不带消息，历史走 transcript（域 E）", () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it("快照里没有 messages，reducer 也不再拿它建 messages", () => {
    // 服务端已经不发这个字段了——帧的类型里它是可选的。少给一个必填字段就能
    // 保证这一条测的是真实现：真机上根本不会有 messages。
    const s = agentReducer(initialAgentState, {
      type: "FRAME",
      frame: { type: "snapshot", sessionId: null, streamSeq: 50, instanceId: "i-1",
               streamEpoch: 0, sessions: [hui], pending: [], questions: [] },
    });
    expect(s.messages[S]).toBeUndefined();
    expect(s.sessions[S]).toBeTruthy();
  });

  it("补拉回来的一批能建出 messages（首屏取到的是它给的那些）", async () => {
    const two = [msg({ messageId: "m-1", seq: 1, text: "一", xuhao: 10 }),
                 msg({ messageId: "m-2", seq: 2, text: "二", xuhao: 11 })];
    vi.spyOn(agentClient, "transcript").mockResolvedValue({
      messages: two, nextFrom: 11, prevBefore: 10, hasMore: false,
    });
    const st = zhenStore();
    agentReducer(st.state, {
      type: "FRAME",
      frame: { type: "snapshot", sessionId: null, streamSeq: 50, instanceId: "i-1",
               streamEpoch: 0, sessions: [hui], pending: [], questions: [] },
    });
    await laPi(S, { from: 0 }, st.dispatch);
    expect(st.state.messages[S]).toHaveLength(2);
    expect(st.state.messages[S].map((m) => m.text)).toEqual(["一", "二"]);
  });

  it("首屏不带 before，也不带 from——取末尾是服务端的事", async () => {
    const spy = vi.spyOn(agentClient, "transcript").mockResolvedValue({
      messages: [], nextFrom: 0, prevBefore: null, hasMore: false,
    });
    const st = zhenStore();
    await laPi(S, {}, st.dispatch);
    expect(spy).toHaveBeenCalledWith(S, 0, expect.objectContaining({ before: undefined }));
  });

  it("增量追赶带 from=<已收到的最大 xuhao>", async () => {
    const spy = vi.spyOn(agentClient, "transcript").mockResolvedValue({
      messages: [], nextFrom: 30, prevBefore: 20, hasMore: false,
    });
    const st = zhenStore();
    await laPi(S, { from: 20 }, st.dispatch);
    expect(spy).toHaveBeenCalledWith(S, 20, expect.objectContaining({ before: undefined }));
  });

  it("向上翻带 before=<最早一条的 xuhao>，且并进来之后排在前面", async () => {
    const old = msg({ messageId: "m-0", seq: 1, text: "更早", xuhao: 5 });
    vi.spyOn(agentClient, "transcript").mockResolvedValue({
      messages: [old], nextFrom: 5, prevBefore: 5, hasMore: false,
    });
    const st = zhenStore();
    // 已有第 2 条
    st.dispatch({ type: "HISTORY", sid: S, messages: [msg({ messageId: "m-1", seq: 2, text: "已有", xuhao: 9 })] });
    await laPi(S, { before: 9 }, st.dispatch);
    expect(st.state.messages[S].map((m) => m.text)).toEqual(["更早", "已有"]);
  });

  it("补拉回来的消息里与已有重复的按 (seq, messageId) 去重，不翻倍", async () => {
    vi.spyOn(agentClient, "transcript").mockResolvedValue({
      messages: [msg({ messageId: "m-1", seq: 2, text: "已有", xuhao: 9 }),
                 msg({ messageId: "m-2", seq: 3, text: "新", xuhao: 10 })],
      nextFrom: 10, prevBefore: 9, hasMore: false,
    });
    const st = zhenStore();
    st.dispatch({ type: "HISTORY", sid: S, messages: [msg({ messageId: "m-1", seq: 2, text: "已有", xuhao: 9 })] });
    await laPi(S, { from: 9 }, st.dispatch);
    expect(st.state.messages[S]).toHaveLength(2);
    expect(st.state.messages[S].map((m) => m.text)).toEqual(["已有", "新"]);
  });

  it("同一 seq 的两个内容块都留着——只按 messageId 去重会顶掉一块", async () => {
    vi.spyOn(agentClient, "transcript").mockResolvedValue({
      messages: [msg({ messageId: "msg_1", seq: 1, kind: "text", text: "文本", xuhao: 5 }),
                 msg({ messageId: "msg_1", seq: 2, kind: "tool_use", text: "工具", xuhao: 6 })],
      nextFrom: 6, prevBefore: 5, hasMore: false,
    });
    const st = zhenStore();
    await laPi(S, { from: 0 }, st.dispatch);
    expect(st.state.messages[S].map((m) => m.kind)).toEqual(["text", "tool_use"]);
  });
});

describe("拉失败与 reset_required（域 E）", () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it("拉取失败不清空已有 messages——网络抖动不该让对话消失", async () => {
    vi.spyOn(agentClient, "transcript").mockRejectedValue(new BridgeError(503, "unavailable", "网络抖动"));
    const st = zhenStore();
    st.dispatch({ type: "HISTORY", sid: S, messages: [msg({ messageId: "m-1", seq: 1, text: "已有", xuhao: 9 })] });
    const r = await laPi(S, { from: 9 }, st.dispatch);
    expect(r).toBeNull();
    expect(st.state.messages[S]).toHaveLength(1);
    expect(st.state.messages[S][0].text).toBe("已有");
  });

  it("409 reset_required 时清空该 sid 并从 from=0 重拉，界面不空白", async () => {
    const spy = vi.spyOn(agentClient, "transcript")
      .mockRejectedValueOnce(new BridgeError(409, "reset_required", "游标越界，需要重置"))
      .mockResolvedValueOnce({
        messages: [msg({ messageId: "m-new", seq: 1, text: "重启后的", xuhao: 1 })],
        nextFrom: 1, prevBefore: 1, hasMore: false,
      });
    const st = zhenStore();
    st.dispatch({ type: "HISTORY", sid: S, messages: [msg({ messageId: "m-old", seq: 1, text: "重启前的", xuhao: 999 })] });

    await laPi(S, { from: 999 }, st.dispatch);

    expect(spy).toHaveBeenCalledTimes(2);
    // 第二次必须 from=0（拿回旧的游标会再吃一个 409，无限循环）
    expect(spy.mock.calls[1][1]).toBe(0);
    // 旧的那条被清掉，界面上只剩重拉回来的
    expect(st.state.messages[S]).toHaveLength(1);
    expect(st.state.messages[S][0].text).toBe("重启后的");
  });

  it("reset 之后重拉再失败就停在那儿，不抛也不无限重试", async () => {
    // 第一次 409（触发清空），重拉那一次 503。
    const spy = vi.spyOn(agentClient, "transcript")
      .mockRejectedValueOnce(new BridgeError(409, "reset_required", "游标越界，需要重置"))
      .mockRejectedValueOnce(new BridgeError(503, "unavailable", "还是不通"));
    const st = zhenStore();
    st.dispatch({ type: "HISTORY", sid: S, messages: [msg({ messageId: "m-old", seq: 1, text: "旧", xuhao: 9 })] });
    // 不抛：调用点是 `void loadHistory(...)`，抛出去就是一条没人接的 promise 拒绝。
    const r = await laPi(S, { from: 9 }, st.dispatch);
    expect(r).toBeNull();
    expect(spy).toHaveBeenCalledTimes(2);
    // 已经清空了：那份旧历史不属于当前进程，留着就是显示一份对不上的内容。
    // 下一个快照会重来一遍（那时 `messages` 为空 → from=0 重拉）。
    expect(st.state.messages[S]).toBeUndefined();
  });
});

describe("messages 的基线换成了 transcript（域 E）", () => {
  it("收到快照时 messages 不被整份替换", () => {
    // 先有两条，再来一个**不带 messages** 的快照。
    let s: AgentStoreState = initialAgentState;
    s = agentReducer(s, {
      type: "FRAME",
      frame: { type: "session_added", sessionId: S, streamSeq: 1, session: hui },
    });
    s = agentReducer(s, {
      type: "FRAME",
      frame: { type: "message", sessionId: S, streamSeq: 2,
               message: msg({ messageId: "m-1", seq: 1, text: "一", xuhao: 2 }) },
    });
    expect(s.messages[S]).toHaveLength(1);

    s = agentReducer(s, {
      type: "FRAME",
      frame: { type: "snapshot", sessionId: null, streamSeq: 50, instanceId: "i-1",
               streamEpoch: 0, sessions: [hui], pending: [], questions: [] },
    });

    // 会话表换了，pending/questions 换了，**messages 一条都不能少**
    expect(s.messages[S]).toHaveLength(1);
    expect(s.messages[S][0].text).toBe("一");
    expect(s.lastSeq).toBe(50);
  });

  it("快照换掉了会话表，不在表里的 sid 的历史一起清掉", () => {
    let s: AgentStoreState = initialAgentState;
    s = agentReducer(s, {
      type: "FRAME",
      frame: { type: "snapshot", sessionId: null, streamSeq: 50, instanceId: "i-1",
               streamEpoch: 0, sessions: [hui], pending: [], questions: [] },
    });
    s = agentReducer(s, { type: "HISTORY", sid: S, messages: [msg({ messageId: "m", seq: 1, xuhao: 5 })] });
    s = agentReducer(s, {
      type: "FRAME",
      frame: { type: "snapshot", sessionId: null, streamSeq: 80, instanceId: "i-1",
               streamEpoch: 0, sessions: [], pending: [], questions: [] },
    });
    expect(s.sessions[S]).toBeUndefined();
    expect(s.messages[S]).toBeUndefined();
  });
});

/**
 * 触发源必须是**快照**，不是 `lastSeq`（域 E 修复轮）。
 *
 * `lastSeq` 每一帧都推进：`gen()` 在 switch 之前就更新它，而服务端对每个帧
 * （**含按 delta 逐条发出的 chunk**）都自增 streamSeq。所以挂在 `lastSeq`
 * 上等于长答案流式输出期间每来一个 chunk 就对每个 sid 重发一次 transcript。
 *
 * **判据是「拉过之后再来帧，还发不发请求」**——不是「快照有没有触发拉」，
 * 后者两种实现都满足。
 */
describe("补拉的触发源是快照，不是 lastSeq（域 E 修复轮）", () => {
  const kua = (seq: number): DownFrame => ({
    type: "chunk", sessionId: S, streamSeq: seq, messageId: "m-1",
    delta: "字", messageKind: "text",
  });
  const zha = (seq: number): DownFrame => ({
    type: "snapshot", sessionId: null, streamSeq: seq, instanceId: "i-1",
    streamEpoch: 0, sessions: [hui], pending: [], questions: [],
  });

  afterEach(() => { vi.restoreAllMocks(); });

  it("chunk 帧不再触发补拉——流式输出期间不重发 transcript", async () => {
    const spy = vi.spyOn(agentClient, "transcript").mockResolvedValue({
      messages: [msg({ messageId: "m-1", seq: 1, text: "答", xuhao: 10 })],
      nextFrom: 10, prevBefore: 10, hasMore: false,
    });
    const { result } = renderHook(() => useAgentStore());

    await act(async () => { result.current.dispatch({ type: "FRAME", frame: zha(50) }); });
    await act(async () => { await Promise.resolve(); });
    expect(spy).toHaveBeenCalledTimes(1); // 快照那一次

    // 同一段回答的 5 个 chunk——服务端每片都占一个 streamSeq。
    for (let i = 1; i <= 5; i += 1) {
      await act(async () => { result.current.dispatch({ type: "FRAME", frame: kua(50 + i) }); });
    }
    await act(async () => { await Promise.resolve(); });

    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("重连快照照旧补拉——streamSeq 等于 lastSeq 的那一种（回归护栏）", async () => {
    const spy = vi.spyOn(agentClient, "transcript").mockResolvedValue({
      messages: [], nextFrom: 0, prevBefore: null, hasMore: false,
    });
    const { result } = renderHook(() => useAgentStore());

    await act(async () => { result.current.dispatch({ type: "FRAME", frame: zha(50) }); });
    await act(async () => { await Promise.resolve(); });
    await act(async () => { result.current.dispatch({ type: "FRAME", frame: kua(51) }); });
    await act(async () => { await Promise.resolve(); });
    // 重连：Bridge 的 duibu 让快照上报当前游标，streamSeq 常常正好等于 lastSeq。
    await act(async () => { result.current.dispatch({ type: "FRAME", frame: zha(51) }); });
    await act(async () => { await Promise.resolve(); });

    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("lastSnapshotSeq 只在快照分支推进，chunk/message 帧推不动它", () => {
    let s = agentReducer(initialAgentState, { type: "FRAME", frame: zha(50) });
    expect(s.lastSnapshotSeq).toBe(50);
    s = agentReducer(s, { type: "FRAME", frame: kua(51) });
    s = agentReducer(s, {
      type: "FRAME",
      frame: { type: "message", sessionId: S, streamSeq: 52,
               message: msg({ messageId: "m-1", seq: 1, text: "一", xuhao: 52 }) },
    });
    // lastSeq 在动（这是旧实现挂的那个依赖），快照标记不动。
    expect(s.lastSeq).toBe(52);
    expect(s.lastSnapshotSeq).toBe(50);
  });
});

/**
 * `lao`（「翻到顶了没」）只能由**向前翻**的结果写入。
 *
 * 服务端 `http.py:637` 只在「from>0 且没给 before」时把 hasMore 算成
 * 「后面还有」，其余（首屏 from=0、向上翻）都是「前面还有」——两个方向的
 * hasMore 语义相反。写混了就是：一次追干净的增量（hasMore=false）让
 * `lao[sid]=false`，此后每次上滚都被闸门挡掉，症状是「往上滚没反应」，
 * 直到刷新页面。
 */
describe("lao 只由向前翻的方向写（域 E 修复轮）", () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it("增量追赶追干净（hasMore=false）之后，向上翻仍然发得出去请求", async () => {
    const spy = vi.spyOn(agentClient, "transcript").mockResolvedValue({
      messages: [msg({ messageId: "m-2", seq: 2, text: "追回来的", xuhao: 30 })],
      nextFrom: 30, prevBefore: 20, hasMore: false, // **后面没有了**
    });
    const { result } = renderHook(() => useAgentStore());

    // 先有一条，于是增量追赶的 from > 0（服务端只在这个分支报「后面还有」）。
    await act(async () => {
      result.current.dispatch({ type: "HISTORY", sid: S, messages: [msg({ messageId: "m-1", seq: 1, text: "已有", xuhao: 20 })] });
    });
    await act(async () => { await result.current.loadHistory(S); });
    expect(spy).toHaveBeenCalledTimes(1);

    // 增量那次的 hasMore=false 绝不能把向上翻的闸门关上。
    await act(async () => { await result.current.loadOlder(S); });
    expect(spy).toHaveBeenCalledTimes(2);
    expect(spy.mock.calls[1][2]).toMatchObject({ before: 20 });
  });

  it("首屏拉到的就是全部时，向上翻被闸门关上——不重发空请求", async () => {
    const spy = vi.spyOn(agentClient, "transcript").mockResolvedValue({
      messages: [msg({ messageId: "m-1", seq: 1, text: "唯一一条", xuhao: 7 })],
      nextFrom: 7, prevBefore: 7, hasMore: false,
    });
    const { result } = renderHook(() => useAgentStore());

    // 首屏 from=0 ⇒ 服务端报的是「前面还有」=false ⇒ 确实到顶。
    await act(async () => { result.current.dispatch({ type: "FRAME", frame: {
      type: "snapshot", sessionId: null, streamSeq: 50, instanceId: "i-1",
      streamEpoch: 0, sessions: [hui], pending: [], questions: [] } }); });
    await act(async () => { await Promise.resolve(); });
    expect(spy).toHaveBeenCalledTimes(1);

    await act(async () => { await result.current.loadOlder(S); });
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("向上翻翻到顶（空批次）之后闸门关上——空批次也写 lao", async () => {
    const spy = vi.spyOn(agentClient, "transcript").mockResolvedValue({
      messages: [], nextFrom: 7, prevBefore: null, hasMore: false,
    });
    const { result } = renderHook(() => useAgentStore());
    await act(async () => {
      result.current.dispatch({ type: "HISTORY", sid: S, messages: [msg({ messageId: "m-1", seq: 1, text: "一", xuhao: 7 })] });
    });
    // messages 非空 ⇒ 门是开的（初始 lao 未定义），于是真的发一次
    await act(async () => { await result.current.loadOlder(S); });
    expect(spy).toHaveBeenCalledTimes(1);
    // 空批次 ⇒ lao=false ⇒ 之后不再发
    await act(async () => { await result.current.loadOlder(S); });
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("向上翻还有得翻时闸门保持开着（hasMore=true 不误关）", async () => {
    const spy = vi.spyOn(agentClient, "transcript").mockResolvedValue({
      messages: [msg({ messageId: "m-0", seq: 0, text: "更早", xuhao: 3 })],
      nextFrom: 3, prevBefore: 3, hasMore: true,
    });
    const { result } = renderHook(() => useAgentStore());
    await act(async () => {
      result.current.dispatch({ type: "HISTORY", sid: S, messages: [msg({ messageId: "m-1", seq: 1, text: "一", xuhao: 7 })] });
    });
    await act(async () => { await result.current.loadOlder(S); });
    await act(async () => { await result.current.loadOlder(S); });
    expect(spy).toHaveBeenCalledTimes(2);
  });
});
