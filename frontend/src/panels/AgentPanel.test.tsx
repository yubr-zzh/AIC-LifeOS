import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { AgentPanel, Bubble } from "./AgentPanel";
import { initialAgentState, type AgentStore } from "../state/agentStore";
import type { AgentActions } from "../hooks/useAgentStream";
import type { AgentMessage, AgentSession, DeviceStatusFrame } from "../api/agentTypes";

const xiao = (a: Partial<AgentMessage> & { kind: AgentMessage["kind"] }): AgentMessage => ({
  messageId: "m", sessionId: "s-1", seq: 1, role: "system", text: "", toolUseId: null,
  toolName: null, toolInput: null, isError: false, isPartial: false, createdAt: 0, ...a,
});

describe("Bubble 的两个新分支", () => {
  it("result 用正常 Agent 消息样式显示，而不是裸 result 标签", () => {
    render(<Bubble m={xiao({ kind: "result", text: "算完了" })} />);
    expect(screen.getByText("Agent")).toBeTruthy();
    expect(screen.getByText("算完了")).toBeTruthy();
    expect(screen.queryByText(/^result$/)).toBeNull();
  });

  it("失败的 result 要看得出来是失败的", () => {
    render(<Bubble m={xiao({ kind: "result", text: "超了", isError: true })} />);
    expect(screen.getByText("执行失败")).toBeTruthy();
  });

  it("permission_resolved 显示是谁决定的、为什么", () => {
    render(<Bubble m={xiao({ kind: "permission_resolved",
                             text: "用户手动批准：Bash" })} />);
    expect(screen.getByText("permission_resolved")).toBeTruthy();
    expect(screen.getByText("用户手动批准：Bash")).toBeTruthy();
  });
});

/**
 * 设备离线提示。
 *
 * 服务端一切正常时界面看起来「什么都不动」是最坏的失败形态——所以隧道一断
 * 必须主动说出来，并且**说出原因**（合成帧带回来的 error），不能只写「离线」。
 */
describe("AgentPanel 的设备离线提示", () => {
  // 入参跟着 `AgentStoreState["device"]["state"]` 走。写成 `string` 会把
  // `DeviceStatusFrame` 的收窄在测试里抹掉——评审发现 5 说的就是这个。
  const zhuang = (a: { state: DeviceStatusFrame["state"]; error?: string | null; conn?: string }) => {
    const store = {
      state: {
        ...initialAgentState,
        conn: a.conn ?? "open",
        device: a.state === "connected" ? null
          : { deviceId: "dev-1", state: a.state, since: 1, error: a.error ?? null },
      },
      dispatch: () => undefined,
      loadHistory: vi.fn(),
      active: null,
      streaming: null,
      todo: 0,
    } as unknown as AgentStore;
    const api = { preview: false, busy: null, act: {} } as unknown as AgentActions;
    return render(<AgentPanel store={store} api={api} onCollapse={() => undefined} />);
  };

  it("设备不在位时说出「离线 · 正在重连」", () => {
    zhuang({ state: "offline" });
    expect(screen.getByText(/设备离线 · 正在重连/)).toBeTruthy();
  });

  it("把合成帧带回来的原因显示出来", () => {
    zhuang({ state: "offline", error: "隧道中断" });
    expect(screen.getByText("隧道中断")).toBeTruthy();
  });

  it("connecting 说「连接中」而不是谎称离线", () => {
    zhuang({ state: "connecting" });
    expect(screen.getByText(/连接中/)).toBeTruthy();
    expect(screen.queryByText(/设备离线/)).toBeNull();
  });

  it("设备在位就不出现任何离线提示", () => {
    zhuang({ state: "connected" });
    expect(screen.queryByText(/设备离线/)).toBeNull();
    expect(screen.queryByText(/正在重连/)).toBeNull();
  });
});

describe("AgentPanel 的结束态与工作指示", () => {
  const session = (a: Partial<AgentSession> = {}): AgentSession => ({
    sessionId: "s-1", agentId: "claude-code", agentLabel: "Claude Code", cwd: "/tmp",
    permissionMode: "manual", effectiveMode: "manual", state: "ended", title: "任务",
    claudeSessionId: null, ownerId: "local", deviceId: "dev-1", planId: null, traceId: null,
    batchTotal: 3, batchDone: 3, createdAt: 1, updatedAt: 2, turnCount: 1,
    pendingPermissions: [], pendingQuestions: [], alive: false, streamEpoch: 1,
    ...a,
  });

  const renderPanel = (current: AgentSession, todo = 0, messages: AgentMessage[] = []) => {
    const loadHistory = vi.fn();
    const store = {
      state: {
        ...initialAgentState,
        sessions: { [current.sessionId]: current },
        messages: { [current.sessionId]: messages },
        activeSessionId: current.sessionId,
      },
      dispatch: () => undefined,
      loadHistory,
      active: current,
      streaming: null,
      todo,
    } as unknown as AgentStore;
    const api = { preview: false, busy: null, act: { interrupt: async () => undefined } } as unknown as AgentActions;
    return { ...render(<AgentPanel store={store} api={api} onCollapse={() => undefined} />), loadHistory };
  };

  it("批次没跑完时不显示“本次委派已结束”", () => {
    renderPanel(session({ batchDone: 1, batchTotal: 3 }), 0);
    expect(screen.queryByText("本次委派已结束")).toBeNull();
  });

  it("全部指令与待办都结束后才显示“本次委派已结束”", () => {
    renderPanel(session({ batchDone: 3, batchTotal: 3 }), 0);
    expect(screen.getByText("本次委派已结束")).toBeTruthy();
  });

  it("Agent 工作时显示转圈指示", () => {
    renderPanel(session({ state: "working", batchDone: 1, batchTotal: 3, alive: true }), 0);
    expect(screen.getByLabelText("Agent 正在工作")).toBeTruthy();
  });

  it("默认展示对话正文，记忆提炼不抢占主区域，并会补拉历史", async () => {
    const messages = [
      xiao({ messageId: "u-1", seq: 1, role: "user", kind: "text", text: "用户输入" }),
      xiao({ messageId: "a-1", seq: 2, role: "assistant", kind: "text", text: "Agent 回复" }),
    ];
    const { loadHistory } = renderPanel(session({ state: "idle" }), 0, messages);
    expect(screen.getByText("用户输入")).toBeTruthy();
    expect(screen.getByText("Agent 回复")).toBeTruthy();
    expect(screen.queryByText("从执行结果提炼记忆")).toBeNull();
    await waitFor(() => expect(loadHistory).toHaveBeenCalledWith("s-1"));
  });
});

/**
 * 对话计时器（整批口径）：第一批指令开始跑起算，整批结束（ended/error/中断）
 * 冻结；等审批、等回答算对话进行中，照常走。旧口径从 session.createdAt 起算、
 * 结束后也不停，这两个行为都在这里钉死防止回退。
 */
describe("AgentPanel 的对话计时器", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  const session = (a: Partial<AgentSession> = {}): AgentSession => ({
    sessionId: "s-1", agentId: "claude-code", agentLabel: "Claude Code", cwd: "/tmp",
    permissionMode: "manual", effectiveMode: "manual", state: "idle", title: "任务",
    claudeSessionId: null, ownerId: "local", deviceId: "dev-1", planId: null, traceId: null,
    batchTotal: 0, batchDone: 0, createdAt: 1, updatedAt: 2, turnCount: 0,
    pendingPermissions: [], pendingQuestions: [], alive: false, streamEpoch: 1,
    ...a,
  });

  const hua = (current: AgentSession) => {
    const store = {
      state: {
        ...initialAgentState,
        sessions: { [current.sessionId]: current },
        messages: {},
        activeSessionId: current.sessionId,
      },
      dispatch: () => undefined,
      loadHistory: vi.fn(),
      active: current,
      streaming: null,
      todo: 0,
    } as unknown as AgentStore;
    const api = { preview: false, busy: null, act: {} } as unknown as AgentActions;
    return <AgentPanel store={store} api={api} onCollapse={() => undefined} />;
  };

  it("空闲时（还没开始对话）不计时", () => {
    vi.useFakeTimers();
    render(hua(session({ state: "idle" })));
    expect(screen.queryByText(/已用|用时/)).toBeNull();
  });

  it("对话开始计时，等审批接着走，结束后冻结不动", () => {
    vi.useFakeTimers();
    vi.setSystemTime(10_000);
    const { rerender } = render(hua(session({ state: "idle" })));
    rerender(hua(session({ state: "working" })));
    act(() => { vi.advanceTimersByTime(5_000); });
    expect(screen.getByText("已用 5s")).toBeTruthy();
    // 等你决定也是对话进行中，继续走。
    rerender(hua(session({ state: "attention" })));
    act(() => { vi.advanceTimersByTime(3_000); });
    expect(screen.getByText("已用 8s")).toBeTruthy();
    // 整批结束：冻结在最后一格，时间再久也不动。
    rerender(hua(session({ state: "ended" })));
    expect(screen.getByText("用时 8s")).toBeTruthy();
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(screen.queryByText("已用 68s")).toBeNull();
    expect(screen.getByText("用时 8s")).toBeTruthy();
  });

  it("结束后再发新指令，计时归零重计", () => {
    vi.useFakeTimers();
    vi.setSystemTime(10_000);
    const { rerender } = render(hua(session({ state: "ended" })));
    rerender(hua(session({ state: "working" })));
    act(() => { vi.advanceTimersByTime(2_000); });
    expect(screen.getByText("已用 2s")).toBeTruthy();
  });
});
