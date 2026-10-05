import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { AgentPanel, Bubble } from "./AgentPanel";
import { initialAgentState, type AgentStore } from "../state/agentStore";
import type { AgentActions } from "../hooks/useAgentStream";
import type { AgentMessage, DeviceStatusFrame } from "../api/agentTypes";

const xiao = (a: Partial<AgentMessage> & { kind: AgentMessage["kind"] }): AgentMessage => ({
  messageId: "m", sessionId: "s-1", seq: 1, role: "system", text: "", toolUseId: null,
  toolName: null, toolInput: null, isError: false, isPartial: false, createdAt: 0, ...a,
});

describe("Bubble 的两个新分支", () => {
  it("result 显示成败——不然用户不知道这一轮到底跑完没有", () => {
    render(<Bubble m={xiao({ kind: "result", text: "算完了" })} />);
    expect(screen.getByText(/result/)).toBeTruthy();
    expect(screen.getByText("算完了")).toBeTruthy();
  });

  it("失败的 result 要看得出来是失败的", () => {
    render(<Bubble m={xiao({ kind: "result", text: "超了", isError: true })} />);
    expect(screen.getByText(/失败/)).toBeTruthy();
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
