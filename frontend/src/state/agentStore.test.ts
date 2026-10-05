import { describe, expect, it } from "vitest";
import { agentReducer, daiJueDing, initialAgentState, type AgentStoreState } from "./agentStore";
import { TUNNEL_LABEL, tunnelLabel, type AgentMessage, type AgentSession, type DeviceStatusFrame, type DownFrame, type PermissionRequest } from "../api/agentTypes";

const S = "s-1";

const hui: AgentSession = {
  sessionId: S, agentId: "claude-code", agentLabel: "Claude Code", cwd: "D:/x",
  permissionMode: "manual", effectiveMode: "manual", state: "idle", title: "",
  claudeSessionId: null, ownerId: "local", deviceId: "local", planId: null, traceId: null,
  batchTotal: 0, batchDone: 0, createdAt: 0, updatedAt: 0, turnCount: 0,
  pendingPermissions: [], pendingQuestions: [], alive: true, streamEpoch: 0,
};

const shen: PermissionRequest = {
  requestId: "r-1", sessionId: S, toolName: "Bash", toolInput: { command: "ls" },
  title: "", displayName: "Bash", description: "", blockedPath: null, decisionReason: null,
  agentId: "claude-code", suggestions: [], inputTruncated: false, originalByteSize: 2,
  createdAt: 1000, expiresAt: 301_000,
};

const msg = (a: Partial<AgentMessage> & { messageId: string; seq: number }): AgentMessage => ({
  sessionId: S, role: "assistant", kind: "text", text: "", toolUseId: null, toolName: null,
  toolInput: null, isError: false, isPartial: false, createdAt: 0, ...a,
});

/** 走一遍 reducer，等价于把一串帧喂进去。 */
const run = (a: AgentStoreState, frames: DownFrame[]) =>
  frames.reduce((s, f) => agentReducer(s, { type: "FRAME", frame: f }), a); ;

/** 连发若干帧的 seq 从这里起。 */
const at = (a: number) => a;

describe("agentStore reducer", () => {
  it("snapshot 建立基线，并把 lastSeq 抬到快照自己的 seq", () => {
    const s = run(initialAgentState, [
      { type: "snapshot", sessionId: null, streamSeq: 50, instanceId: "i-1", streamEpoch: 0,
        sessions: [hui], messages: [msg({ messageId: "m-1", seq: 1, text: "旧" })],
        pending: [], questions: [] },
    ]);
    expect(s.lastSeq).toBe(50);
    expect(s.instanceId).toBe("i-1");
    expect(s.sessions[S].state).toBe("idle");
    expect(s.messages[S]).toHaveLength(1);
  });

  it("快照之后到达的补发帧被丢掉——否则同一条审批会渲染两次", () => {
    const s = run(initialAgentState, [
      { type: "snapshot", sessionId: null, streamSeq: 50, instanceId: "i-1", streamEpoch: 0,
        sessions: [hui], messages: [], pending: [shen], questions: [] },
      // 补发窗口是 (lastEventId, 50)，这些帧的 seq 都比基线小
      { type: "permission_resolved", sessionId: S, streamSeq: at(42), requestId: "r-1",
        decision: "auto_deny", autoDecided: true, autoReason: "timeout", replayed: true },
    ]);
    expect(s.resolved["r-1"]).toBeUndefined();
    expect(daiJueDing(s)).toBe(1);
  });

  it("过期快照也被丢掉——它是「那一刻」的全量，应用它等于用旧状态覆盖当前", () => {
    // 真机踩过：Bridge 把 snapshot 也存进了重放缓冲，重连时补发批次里混进一串
    // 旧快照。前端原本特意豁免 snapshot 的去重，于是早已收口的审批复活，
    // 每次重连都把界面掰回双栏。服务端已修，这一层是兜底。
    const s = run(initialAgentState, [
      { type: "snapshot", sessionId: null, streamSeq: 50, instanceId: "i-1", streamEpoch: 0,
        sessions: [hui], messages: [], pending: [], questions: [] },
      { type: "snapshot", sessionId: null, streamSeq: 42, instanceId: "i-0", streamEpoch: 0,
        sessions: [], messages: [], pending: [shen], questions: [] },
    ]);
    expect(s.instanceId).toBe("i-1");
    expect(s.lastSeq).toBe(50);
    expect(daiJueDing(s)).toBe(0);
  });

  it("快照的 seq 正好等于游标时也要应用——那是重连后的基线", () => {
    // 真机踩过：Bridge 让快照上报当前游标而不新占序号，重连时它常常正好等于
    // lastSeq。按 <= 一律丢的话基线没了，界面从此冻结：Agent 卡在审批上，
    // 界面上什么都没有。快照是全量幂等的，重复应用无副作用。
    const s = run(initialAgentState, [
      { type: "snapshot", sessionId: null, streamSeq: 16, instanceId: "i-1", streamEpoch: 0,
        sessions: [hui], messages: [], pending: [shen], questions: [] },
      // 又收到一份同游标的快照（reconnect），内容必须照样生效
      { type: "snapshot", sessionId: null, streamSeq: 16, instanceId: "i-1", streamEpoch: 0,
        sessions: [hui], messages: [], pending: [shen], questions: [] },
    ]);
    expect(daiJueDing(s)).toBe(1);
    expect(s.sessions[S]).toBeTruthy();
  });

  it("chunk 累积，完整帧到达后整段替换而不是追加两份", () => {
    let s = run(initialAgentState, [
      { type: "session_added", sessionId: S, streamSeq: 1, session: hui },
      { type: "chunk", sessionId: S, streamSeq: 2, messageId: "msg_sdk", delta: "你", messageKind: "text" },
      { type: "chunk", sessionId: S, streamSeq: 3, messageId: "msg_sdk", delta: "好", messageKind: "text" },
    ]);
    expect(s.partial["msg_sdk"].text).toBe("你好");

    s = run(s, [
      {
        type: "message", sessionId: S, streamSeq: 4,
        message: msg({ messageId: "msg_sdk", seq: 1, text: "你好，我在。" }),
      },
    ]);
    expect(s.partial["msg_sdk"]).toBeUndefined();
    expect(s.messages[S]).toHaveLength(1);
    expect(s.messages[S][0].text).toBe("你好，我在。");
  });

  it("完整帧已经落地时，后续 chunk 不再往尾巴上追加", () => {
    const s = run(initialAgentState, [
      { type: "session_added", sessionId: S, streamSeq: 1, session: hui },
      { type: "message", sessionId: S, streamSeq: 2, message: msg({ messageId: "m", seq: 1, text: "好了" }) },
      { type: "chunk", sessionId: S, streamSeq: 3, messageId: "m", delta: "又来", messageKind: "text" },
    ]);
    expect(s.partial["m"]).toBeUndefined();
  });

  it("一条 AssistantMessage 的多个内容块都留下，且各自可独立替换", () => {
    // SDK 的一条消息可以同时带 text 和 tool_use 两个块，它们共用同一个
    // message_id。按 messageId 定位替换会把它哥哥顶掉——症状是界面看不到工具调用。
    let s = run(initialAgentState, [
      { type: "session_added", sessionId: S, streamSeq: 1, session: hui },
      { type: "message", sessionId: S, streamSeq: 2,
        message: msg({ messageId: "msg_1", seq: 1, kind: "text", text: "我来查一下" }) },
      { type: "message", sessionId: S, streamSeq: 3,
        message: msg({ messageId: "msg_1", seq: 2, kind: "tool_use", toolName: "Bash" }) },
    ]);
    expect(s.messages[S].map((m) => m.kind)).toEqual(["text", "tool_use"]);

    // 重连补发同一条，就地替换而不是再追加一份
    s = run(s, [
      { type: "message", sessionId: S, streamSeq: 4,
        message: msg({ messageId: "msg_1", seq: 2, kind: "tool_use", toolName: "Bash" }) },
    ]);
    expect(s.messages[S]).toHaveLength(2);
  });

  it("每条 result 都留一份待回流的结果，供主 store 领走（7.7.1 / F4）", () => {
    const s = run(initialAgentState, [
      { type: "session_added", sessionId: S, streamSeq: 1, session: hui },
      { type: "result", sessionId: S, streamSeq: 9, subtype: "success", durationMs: 1234,
        numTurns: 3, totalCostUsd: 0, isError: false, resultText: "", batchDone: 1, batchTotal: 1 },
    ]);
    expect(s.report).toMatchObject({ seq: 9, sessionId: S });
    expect(s.report?.title).toContain("委派完成");
    expect(s.report?.title).toContain("第 1/1 条");
  });

  it("同一批只回流一次——反复收到覆盖它的快照也不会把左栏刷满", () => {
    const yuan: AgentStoreState = {
      ...initialAgentState,
      sessions: { [S]: { ...hui, batchTotal: 1, batchDone: 1 } },
      reported: { [S]: 1 },
    };
    const s = run(yuan, [
      { type: "snapshot", sessionId: null, streamSeq: 90, instanceId: "i-1", streamEpoch: 0,
        sessions: [{ ...hui, batchTotal: 1, batchDone: 1 }], messages: [], pending: [], questions: [] },
    ]);
    expect(s.report).toBeNull();
  });

  it("快照也要能推出回报——result 帧被去重挡掉时它是唯一来源", () => {
    const s = run(initialAgentState, [
      { type: "snapshot", sessionId: null, streamSeq: 90, instanceId: "i-1", streamEpoch: 0,
        sessions: [{ ...hui, batchTotal: 2, batchDone: 2, traceId: "t-1" }], messages: [], pending: [], questions: [] },
    ]);
    expect(s.report).toMatchObject({ seq: 90, sessionId: S, traceId: "t-1" });
    expect(s.report?.title).toContain("第 2/2 条");
  });

  it("出错的 result 也要回流，不然左栏一片安静像是还在跑", () => {
    const s = run(initialAgentState, [
      { type: "result", sessionId: S, streamSeq: 9, subtype: "error_max_turns", durationMs: 500,
        numTurns: 200, totalCostUsd: 0, isError: true, resultText: "", batchDone: 1, batchTotal: 1 },
    ]);
    expect(s.report?.title).toContain("委派中断");
    expect(s.report?.title).toContain("error_max_turns");
  });

  it("收到审批强制切到双栏——折叠态会把「同意」变成可遗忘", () => {
    const s = run({ ...initialAgentState, layout: "collapsed" }, [
      { type: "session_added", sessionId: S, streamSeq: 1, session: hui },
      { type: "permission", sessionId: S, streamSeq: 2, request: shen },
    ]);
    expect(s.layout).toBe("split");
    expect(s.sessions[S].state).toBe("attention");
    expect(daiJueDing(s)).toBe(1);
  });

  it("收口后不再计入待决定", () => {
    const s = run(initialAgentState, [
      { type: "permission", sessionId: S, streamSeq: 1, request: shen },
      { type: "permission_resolved", sessionId: S, streamSeq: 2, requestId: "r-1",
        decision: "user_allow", autoDecided: false, autoReason: null, replayed: false },
    ]);
    expect(daiJueDing(s)).toBe(0);
    expect(s.resolved["r-1"].decision).toBe("user_allow");
  });

  it("整批跑完且无待决定时自动收回折叠；用户手动切过就不动", () => {
    const yuan = { ...initialAgentState, sessions: { [S]: { ...hui, batchTotal: 2 } } };
    const zhen = (a: AgentStoreState) =>
      run(a, [
        {
          type: "result", sessionId: S, streamSeq: 9, subtype: "success", durationMs: 1, numTurns: 1,
          totalCostUsd: 0, isError: false, resultText: "", batchDone: 2, batchTotal: 2,
        },
      ]);

    expect(zhen({ ...yuan, layout: "split", manualLayout: false }).layout).toBe("collapsed");
    expect(zhen({ ...yuan, layout: "split", manualLayout: true }).layout).toBe("split");
  });

  it("还有待决定时不收回——收走了用户就没地方批准", () => {
    const yuan: AgentStoreState = {
      ...initialAgentState, layout: "split", manualLayout: false,
      sessions: { [S]: { ...hui, batchTotal: 1 } }, pending: { "r-1": shen },
    };
    const s = run(yuan, [
      {
        type: "result", sessionId: S, streamSeq: 9, subtype: "success", durationMs: 1, numTurns: 1,
        totalCostUsd: 0, isError: false, resultText: "", batchDone: 1, batchTotal: 1,
      },
    ]);
    expect(s.layout).toBe("split");
  });

  it("关掉会话时把它的消息一并清掉", () => {
    const s = run(initialAgentState, [
      { type: "session_added", sessionId: S, streamSeq: 1, session: hui },
      { type: "message", sessionId: S, streamSeq: 2, message: msg({ messageId: "m", seq: 1 }) },
      { type: "session_removed", sessionId: S, streamSeq: 3 },
    ]);
    expect(s.sessions[S]).toBeUndefined();
    expect(s.messages[S]).toBeUndefined();
  });

  it("前端自造的帧（seq 为 0）不参与去重", () => {
    const s = run(initialAgentState, [
      { type: "session_added", sessionId: S, streamSeq: 7, session: hui },
      { type: "error", sessionId: null, streamSeq: 0, code: "internal",
        message: "收到无法解析的帧", recoverable: true },
    ]);
    expect(s.notices).toHaveLength(1);
  });
});

/**
 * 设备状态帧。
 *
 * **唯一容易写错的地方**：`streamSeq === 0` 的帧是网关合成的，不在 Bridge 的
 * 序号空间里（spec 9.4）。它必须绕过「序号不增就丢弃」的单调规则，且**不动游标**。
 * 走单调规则的话它会被静默丢掉，界面永远显示不出「设备离线」——而服务端一切正常。
 */
describe("设备状态帧（spec 9.4）", () => {
  const heCheng = (a: Partial<DeviceStatusFrame> & { state: DeviceStatusFrame["state"] }): DeviceStatusFrame => ({
    type: "device_status", sessionId: null, streamSeq: 0,
    deviceId: "dev-1", since: 1, error: null, ...a,
  });

  it("streamSeq 为 0 的合成帧不被单调规则丢掉，也不更新游标", () => {
    const s0 = initialAgentState;
    const s1 = agentReducer(s0, { type: "FRAME", frame: heCheng({ state: "offline", error: "隧道中断" }) });
    expect(s1.device).toMatchObject({ deviceId: "dev-1", state: "offline", error: "隧道中断" });
    expect(s1.lastSeq).toBe(s0.lastSeq);

    // 正常帧仍然走单调规则
    const s2 = agentReducer(s1, {
      type: "FRAME",
      frame: { type: "state", sessionId: S, streamSeq: 5, state: "working", lastEvent: "x" },
    });
    expect(s2.lastSeq).toBe(5);
    const s3 = agentReducer(s2, {
      type: "FRAME",
      frame: { type: "state", sessionId: S, streamSeq: 5, state: "idle", lastEvent: "x" },
    });
    expect(s3).toBe(s2);
  });

  it("游标被真实帧抬到高位之后，合成帧照样进得来", () => {
    // 顺序反了也必须成立：合成帧先来、真实帧后来，界面照样要能显示离线。
    const s = run(initialAgentState, [
      { type: "session_added", sessionId: S, streamSeq: 40, session: hui },
      heCheng({ state: "error", error: "401" }),
    ]);
    expect(s.lastSeq).toBe(40);
    expect(s.device?.state).toBe("error");
  });

  it("Bridge 侧发来的真实序号帧（streamSeq > 0）走正常路径并推进游标", () => {
    const s = run(initialAgentState, [
      { type: "device_status", sessionId: null, streamSeq: 9, deviceId: "dev-1",
        state: "connected", since: 1, error: null },
    ]);
    expect(s.device?.state).toBe("connected");
    expect(s.lastSeq).toBe(9);
  });
});

describe("tunnelState 的中文映射", () => {
  it("五个取值都有中文说法——界面上不出现裸英文状态词", () => {
    expect(TUNNEL_LABEL.local).toBe("本机直连");
    expect(TUNNEL_LABEL.connected).toBe("隧道已连通");
    expect(TUNNEL_LABEL.connecting).toBe("隧道连接中");
    expect(TUNNEL_LABEL.offline).toBe("隧道未连通");
    expect(TUNNEL_LABEL.none).toBe("未配对");
  });

  it("未知取值降级成「未知（值）」而不是静默显示裸串", () => {
    expect(tunnelLabel("wat")).toBe("未知（wat）");
    expect(tunnelLabel(null)).toBe("—");
  });
});
