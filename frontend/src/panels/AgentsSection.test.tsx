import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { initialAgentState, type AgentStore } from "../state/agentStore";
import type { AgentActions } from "../hooks/useAgentStream";
import type { BridgeInfo } from "../api/agentClient";
import type { AgentsResponse } from "../api/agentTypes";

vi.mock("../api/agentClient", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api/agentClient")>();
  return {
    ...original,
    bridgeInfo: vi.fn(),
    startBridge: vi.fn(),
    stopBridge: vi.fn(),
    setDelegation: vi.fn(),
  };
});

const client = await import("../api/agentClient");
const { AgentsSection } = await import("./AgentsSection");

const bridge = (a: Partial<BridgeInfo> = {}): BridgeInfo => ({
  running: false, port: null, pid: null, instanceId: null, cliVersion: null,
  tunnelState: "none", deviceId: null, error: null, csrf: "tok-1",
  devices: [], paired: false, ...a,
});

const store = (catalog: AgentsResponse | null = null) => ({
  state: { ...initialAgentState, catalog },
  dispatch: () => undefined,
  setLayout: () => undefined,
  lastSeq: () => 0,
  active: null,
  todo: 0,
  streaming: null,
}) as unknown as AgentStore;

const api = () => ({
  preview: false,
  busy: null,
  act: { refreshAgents: async () => undefined, connect: async () => "s-1" },
}) as unknown as AgentActions;

function setup(catalog: AgentsResponse | null = null, info: Partial<BridgeInfo> = {}) {
  vi.mocked(client.bridgeInfo).mockResolvedValue(bridge(info));
  vi.mocked(client.startBridge).mockResolvedValue({ ok: true });
  vi.mocked(client.stopBridge).mockResolvedValue({ ok: true });
  vi.mocked(client.setDelegation).mockResolvedValue({ enabled: true });
  return render(<AgentsSection store={store(catalog)} api={api()} onGoChat={() => undefined} />);
}

afterEach(() => vi.restoreAllMocks());

describe("AgentsSection 页面结构", () => {
  it("不再渲染配对卡，Agent 活动面板位于页面最底部", async () => {
    const { container } = setup();
    await screen.findByText("启动桥接");
    expect(screen.queryByText("配对")).toBeNull();
    const root = container.querySelector(".ags");
    expect(root?.lastElementChild?.classList.contains("agent-activity-panel")).toBe(true);
  });

  it("显示最近 20 条的活动面板说明", async () => {
    setup();
    expect(await screen.findByText(/最近 20 条/)).toBeTruthy();
  });

  it("浏览按钮默认可用，委派提示压缩为单行", async () => {
    setup();
    const browse = await screen.findByRole("button", { name: "浏览…" });
    expect((browse as HTMLButtonElement).disabled).toBe(false);
    expect(browse.className).toContain("ags-browse-button");
    expect(screen.getByText("开启委派：命中任务时生成委派计划")).toBeTruthy();
  });
});

describe("AgentsSection 的凭据目录告警", () => {
  it("false 时提示重新登录，并保持通栏告警", async () => {
    setup({ agents: [], suggestedDirs: [], credentialsReady: false } as unknown as AgentsResponse);
    await screen.findByText(/重新登录一次/);
    const alert = screen.getByRole("alert");
    expect(alert.closest(".ags-card")).toBeNull();
    expect(alert.parentElement?.className).toBe("ags");
  });

  it("true 或字段缺失时不显示凭据告警", async () => {
    setup({ agents: [], suggestedDirs: [], credentialsReady: true } as unknown as AgentsResponse);
    await waitFor(() => expect(screen.getByText("启动桥接")).toBeTruthy());
    expect(screen.queryByText(/重新登录一次/)).toBeNull();
  });
});