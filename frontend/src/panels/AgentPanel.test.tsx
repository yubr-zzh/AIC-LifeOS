import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AgentPanel, Bubble } from "./AgentPanel";
import { initialAgentState, type AgentStore } from "../state/agentStore";
import type { AgentActions } from "../hooks/useAgentStream";
import type { AgentMessage, AgentSession, AgentToolCall, DeviceStatusFrame } from "../api/agentTypes";

const xiao = (a: Partial<AgentMessage> & { kind: AgentMessage["kind"] }): AgentMessage => ({
  messageId: "m", sessionId: "s-1", seq: 1, role: "system", text: "", toolUseId: null,
  toolName: null, toolInput: null, isError: false, isPartial: false, createdAt: 0, ...a,
});

describe("Bubble 的 result 与 permission_resolved 分支", () => {
  it("result 正文照常渲染，role 标注来源", () => {
    render(<Bubble m={xiao({ kind: "result", text: "算完了" })} />);
    expect(screen.getByText("result")).toBeTruthy();
    expect(screen.getByText("算完了")).toBeTruthy();
  });

  it("失败的 result 要看得出来是失败的", () => {
    render(<Bubble m={xiao({ kind: "result", text: "超了", isError: true })} />);
    expect(screen.getByText("result · 失败")).toBeTruthy();
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

  it("批次没跑完时不出结束占位", () => {
    const { container } = renderPanel(session({ batchDone: 1, batchTotal: 3 }), 0);
    expect(container.querySelector(".agp-end")).toBeNull();
  });

  it("全部指令与待办都结束后才出结束占位", () => {
    // 结束态不再写「本次委派已结束」——状态栏已经说了「已结束」，
    // 正文里再写一遍是噪音。这里只看那个占位元素在不在。
    const { container } = renderPanel(session({ batchDone: 3, batchTotal: 3 }), 0);
    expect(container.querySelector(".agp-end")).toBeTruthy();
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
 * 对话计时器：对话开始（Agent 进入运行态）起算；等待批准、等待回答算暂停，
 * 恢复执行后接着累计；整批结束冻结。旧口径把等待时间也算进去、且从
 * session.createdAt 起算，这两个行为都在这里钉死防止回退。
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

  it("对话开始计时，等待你决定时暂停，结束后冻结不动", () => {
    vi.useFakeTimers();
    vi.setSystemTime(10_000);
    const { rerender } = render(hua(session({ state: "idle" })));
    rerender(hua(session({ state: "working" })));
    act(() => { vi.advanceTimersByTime(5_000); });
    expect(screen.getByText("已用 5s")).toBeTruthy();
    // 等你决定是暂停：时间停住，不会把发呆时间算进对话。
    rerender(hua(session({ state: "attention" })));
    act(() => { vi.advanceTimersByTime(3_000); });
    expect(screen.getByText("已用 5s")).toBeTruthy();
    // 你决定后恢复执行：接着累计。
    rerender(hua(session({ state: "working" })));
    act(() => { vi.advanceTimersByTime(2_000); });
    expect(screen.getByText("已用 7s")).toBeTruthy();
    // 整批结束：冻结在最后一格，时间再久也不动。
    rerender(hua(session({ state: "ended" })));
    expect(screen.getByText("用时 7s")).toBeTruthy();
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(screen.queryByText("已用 67s")).toBeNull();
    expect(screen.getByText("用时 7s")).toBeTruthy();
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

/**
 * P0-A：消息流与工具调用表的合并。
 *
 * 这三条钉住的是「同一件事不要渲染两遍」和「成功调用折叠成一行」：
 * 之前 tool_use / tool_result 是两条独立 <pre>，一个 turn 12 次调用
 * 就是 12 个平铺块。
 */
describe("AgentPanel 的工具调用合并", () => {
  const sess = {
    sessionId: "s-1", agentId: "claude-code", agentLabel: "Claude Code", cwd: ".",
    permissionMode: "manual", effectiveMode: "manual", state: "working", title: "",
    claudeSessionId: null, ownerId: "local", deviceId: "local", planId: null, traceId: null,
    batchTotal: 0, batchDone: 0, createdAt: 0, updatedAt: 0, turnCount: 0,
    pendingPermissions: [], pendingQuestions: [], alive: true, streamEpoch: 0,
  } as unknown as AgentSession;

  const msg = (a: Partial<AgentMessage> & { messageId: string; seq: number }): AgentMessage => ({
    sessionId: "s-1", role: "assistant", kind: "text", text: "", toolUseId: null,
    toolName: null, toolInput: null, isError: false, isPartial: false, createdAt: 0, ...a,
  });

  const call = (a: Partial<AgentToolCall> & { toolUseId: string; seq: number }): AgentToolCall => ({
    sessionId: "s-1", name: "Read", input: {}, summary: "读取文件",
    state: { type: "completed", isError: false, durationMs: 10 }, resultText: "", ...a,
  });

  const zhuang = (messages: AgentMessage[], toolCalls: Record<string, AgentToolCall>) => {
    const store = {
      state: { ...initialAgentState, conn: "open", messages: { "s-1": messages }, toolCalls },
      dispatch: () => undefined,
      loadHistory: vi.fn(),
      active: sess,
      streaming: null,
      todo: 0,
    } as unknown as AgentStore;
    const api = { preview: false, busy: null, act: {} } as unknown as AgentActions;
    return render(<AgentPanel store={store} api={api} onCollapse={() => undefined} />);
  };
  it("tool_use 已经有对应调用时不再单独渲染", () => {
    zhuang(
      [msg({ messageId: "m1", seq: 1, kind: "tool_use", toolUseId: "t1", toolName: "Read" })],
      { t1: call({ toolUseId: "t1", seq: 1 }) },
    );
    // 旧样式会渲染 "tool_use · Read"；新样式应只有一行摘要
    expect(screen.queryByText(/tool_use ·/)).toBeNull();
    expect(screen.getByText("读取文件")).toBeTruthy();
  });

  it("没有对应调用的 tool_use 仍走旧样式兜底", () => {
    zhuang(
      [msg({ messageId: "m1", seq: 1, kind: "tool_use", toolUseId: "ghost", toolName: "Read" })],
      {},
    );
    expect(screen.getByText(/tool_use · Read/)).toBeTruthy();
  });

  it("连续 3 个已完成调用合并成一行", () => {
    zhuang(
      [],
      {
        a: call({ toolUseId: "a", seq: 1, summary: "读取 a.ts" }),
        b: call({ toolUseId: "b", seq: 2, summary: "读取 b.ts" }),
        c: call({ toolUseId: "c", seq: 3, summary: "读取 c.ts" }),
      },
    );
    expect(screen.getByText("读取了 3 个文件")).toBeTruthy();
    // 组内明细默认折叠
    expect(screen.queryByText("读取 a.ts")).toBeNull();
  });

  it("组里有一个等待审批就不合并，单独可见", () => {
    zhuang(
      [],
      {
        a: call({ toolUseId: "a", seq: 1, summary: "读取 a.ts" }),
        b: call({
          toolUseId: "b", seq: 2, summary: "运行 npm test", name: "Bash",
          state: { type: "awaiting_confirmation", requestId: "r-1" },
        }),
        c: call({ toolUseId: "c", seq: 3, summary: "读取 c.ts" }),
      },
    );
    expect(screen.queryByText(/读取了 3 个文件/)).toBeNull();
    expect(screen.getByText("运行 npm test")).toBeTruthy();
    expect(screen.getByText("等待你批准")).toBeTruthy();
  });

  it("轮次底部列出本轮碰过的文件，折叠起来不挡回答", () => {
    zhuang(
      [
        msg({ messageId: "u", seq: 1, role: "user", kind: "text", text: "看看这个文件" }),
        msg({ messageId: "a", seq: 2, kind: "text", text: "看完了" }),
      ],
      {
        a: call({ toolUseId: "a", seq: 2, name: "Read", input: { file_path: "src/App.tsx" }, summary: "读取 App.tsx" }),
      },
    );
    const summary = screen.getByText("已使用的上下文 (1)");
    expect(summary).toBeTruthy();
    // 默认折叠：chip 在 <details> 里，但没有 open
    expect(summary.closest("details")?.open).toBe(false);
    expect(screen.getByText("src/App.tsx")).toBeTruthy();
  });

  it("没有文件类工具调用时不渲染上下文条", () => {
    zhuang(
      [],
      { a: call({ toolUseId: "a", seq: 1, name: "Bash", input: { command: "npm test" }, summary: "运行测试" }) },
    );
    expect(screen.queryByText(/已使用的上下文/)).toBeNull();
  });

  it("助手正文走 Markdown 渲染，不是纯文本", () => {
    zhuang([msg({ messageId: "a", seq: 1, kind: "text", text: "**加粗** 与 `code`" })], {});
    expect(document.querySelector(".md strong")?.textContent).toBe("加粗");
    expect(document.querySelector(".md code")?.textContent).toBe("code");
  });

  it("工具产出仍是 <pre>，不被当成 Markdown 解释", () => {
    zhuang(
      [msg({ messageId: "t", seq: 1, kind: "tool_use", toolUseId: "ghost", toolName: "Read",
             toolInput: { file_path: "a.ts" } })],
      {},
    );
    const pre = document.querySelector(".agb-io");
    expect(pre?.tagName).toBe("PRE");
    expect(document.querySelector(".agb-io .md")).toBeNull();
  });
});

/**
 * Steering：Agent 执行中收到的指令先排队。
 *
 * 直接发会让 Bridge 同时起两条 `paichu`，两串工具调用交错，谁也说不清
 * 哪个结果属于哪条指令。
 */
describe("Steering 队列", () => {
  const sess = {
    sessionId: "s-1", agentId: "claude-code", agentLabel: "Claude Code", cwd: ".",
    permissionMode: "manual", effectiveMode: "manual", state: "working", title: "",
    claudeSessionId: null, ownerId: "local", deviceId: "local", planId: null, traceId: null,
    batchTotal: 0, batchDone: 0, createdAt: 0, updatedAt: 0, turnCount: 0,
    pendingPermissions: [], pendingQuestions: [], alive: true, streamEpoch: 0,
  } as unknown as AgentSession;

  const zhuang = (state: string, act: Partial<AgentActions["act"]>) => {
    const store = {
      state: { ...initialAgentState, conn: "open", messages: { "s-1": [] }, toolCalls: {} },
      dispatch: () => undefined,
      loadHistory: vi.fn(),
      active: { ...sess, state },
      streaming: null,
      todo: 0,
    } as unknown as AgentStore;
    const api = { preview: false, busy: null, act } as unknown as AgentActions;
    return render(<AgentPanel store={store} api={api} onCollapse={() => undefined} />);
  };

  it("执行中 Enter 入队，不发请求", () => {
    const send = vi.fn().mockResolvedValue(undefined);
    zhuang("working", { send, interrupt: vi.fn() });
    const box = screen.getByRole("textbox");
    fireEvent.change(box, { target: { value: "补充一条" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(send).not.toHaveBeenCalled();
    expect(screen.getByText("补充一条")).toBeTruthy();
  });

  it("排队项可以取消", () => {
    const send = vi.fn().mockResolvedValue(undefined);
    zhuang("working", { send, interrupt: vi.fn() });
    const box = screen.getByRole("textbox");
    fireEvent.change(box, { target: { value: "这条不要了" } });
    fireEvent.keyDown(box, { key: "Enter" });
    fireEvent.click(screen.getByLabelText("取消排队：这条不要了"));
    expect(screen.queryByText("这条不要了")).toBeNull();
    expect(send).not.toHaveBeenCalled();
  });

  it("回到 idle 后自动发出，且只发一次", async () => {
    const send = vi.fn().mockResolvedValue(undefined);
    const act = { send, interrupt: vi.fn() };
    const view = (state: string) => {
      const store = {
        state: { ...initialAgentState, conn: "open", messages: { "s-1": [] }, toolCalls: {} },
        dispatch: () => undefined,
        loadHistory: vi.fn(),
        active: { ...sess, state },
        streaming: null,
        todo: 0,
      } as unknown as AgentStore;
      const api = { preview: false, busy: null, act } as unknown as AgentActions;
      return <AgentPanel store={store} api={api} onCollapse={() => undefined} />;
    };

    const { rerender } = render(view("working"));
    const box = screen.getByRole("textbox");
    fireEvent.change(box, { target: { value: "补充一条" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(send).not.toHaveBeenCalled();

    rerender(view("idle"));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
    expect(send).toHaveBeenCalledWith("s-1", { text: "补充一条" });
  });

  it("排了多条时一次只发一条，等下一轮结束再发下一条", async () => {
    const send = vi.fn().mockResolvedValue(undefined);
    const act = { send, interrupt: vi.fn() };
    const view = (state: string) => {
      const store = {
        state: { ...initialAgentState, conn: "open", messages: { "s-1": [] }, toolCalls: {} },
        dispatch: () => undefined,
        loadHistory: vi.fn(),
        active: { ...sess, state },
        streaming: null,
        todo: 0,
      } as unknown as AgentStore;
      const api = { preview: false, busy: null, act } as unknown as AgentActions;
      return <AgentPanel store={store} api={api} onCollapse={() => undefined} />;
    };

    const { rerender } = render(view("working"));
    const box = screen.getByRole("textbox");
    for (const t of ["第一条", "第二条"]) {
      fireEvent.change(box, { target: { value: t } });
      fireEvent.keyDown(box, { key: "Enter" });
    }

    // 回到 idle：只放行第一条
    rerender(view("idle"));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
    expect(send).toHaveBeenCalledWith("s-1", { text: "第一条" });
    expect(screen.getByText("第二条")).toBeTruthy();

    // 第二轮跑完再放行第二条
    rerender(view("thinking"));
    rerender(view("idle"));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send).toHaveBeenLastCalledWith("s-1", { text: "第二条" });
  });
});
