import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AgentsSection } from "./AgentsSection";
import { agentReducer, initialAgentState, type AgentAction, type AgentStore, type AgentStoreState } from "../state/agentStore";
import type { AgentActions } from "../hooks/useAgentStream";
import { listAgents } from "../api/agentClient";
import type { AgentDescriptor } from "../api/agentTypes";

/**
 * 评审发现 1 的**真点按钮**版本。
 *
 * 本文件刻意**不 mock `agentClient`** —— 那个文件的测试全在 fetch 层验，
 * 而评审第 66-70 行的原话是「从来没有点击过这三个按钮」。所以这里让组件跑真的
 * 传输层，只把 `fetch` 换成一台**忠实模拟 `bridge_admin.yong_ma` 的假服务端**：
 * 每枚 token 只能用一次，用掉立刻换新。
 *
 * 这台假服务端才是关键：旧代码把 `info.csrf`（挂载时取的那一枚）连点两次，
 * 第二次必然 403 —— 与真机症状完全一致。
 */

const hui200 = (a: unknown) => ({ ok: true, status: 200, json: async () => a }) as Response;
const hui403 = () =>
  ({ ok: false, status: 403, json: async () => ({ code: "forbidden", message: "CSRF token 无效或已用过" }) }) as Response;

const KE_DONG: AgentDescriptor = {
  agentId: "claude-code", label: "Claude Code", available: true,
  version: "2.0.0", sdkVersion: null, error: null, canUseTool: true, canAskQuestion: true,
};

/**
 * 一台忠实模拟 `yong_ma`（校验通过即换新）的假服务端。
 * 返回 `fetch` mock 与「送出过的 token 序列」，供断言。
 * `zaiYun` 跟着 start/stop 变，界面上的按钮才会正确地切「启动 / 停止」。
 */
const jiaShei = () => {
  let hao = 0;
  const cur = () => `tok-${++hao}`;
  let weiZhi = cur(); // 服务端当前那一枚
  let zaiYun = false; // Bridge 起没起
  const songChu: string[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/api/bridge/info")) {
      return hui200({
        running: zaiYun, port: 8766, pid: 42, instanceId: "i-1",
        cliVersion: "2.0.0", tunnelState: "none", deviceId: "dev-1", error: null,
        csrf: weiZhi, devices: [], paired: false,
      });
    }
    // 挂载时那趟 tiao 会现问设备表；这条也要一枚新 token。
    if (url.endsWith("/api/bridge/devices")) {
      const song = (init?.headers as Record<string, string>)["X-LifeOS-CSRF"];
      songChu.push(song);
      if (song !== weiZhi) return hui403();
      weiZhi = cur();
      return hui200({ devices: [] });
    }
    const song = (init?.headers as Record<string, string>)["X-LifeOS-CSRF"];
    songChu.push(song);
    if (song !== weiZhi) return hui403(); // 过期 / 用过 —— 真后端就是 403
    weiZhi = cur(); // yong_ma：校验通过即换新
    if (url.endsWith("/api/bridge/start")) zaiYun = true;
    if (url.endsWith("/api/bridge/stop")) zaiYun = false;
    return hui200({ ok: true, port: 8766, closed: 1, enabled: true });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, songChu };
};

const store = (): AgentStore => ({
  ...({} as AgentStore),
  state: { ...initialAgentState, catalog: { agents: [KE_DONG], suggestedDirs: [], versionGate: {} as never } },
  dispatch: () => undefined,
  setLayout: () => undefined,
  lastSeq: () => 0,
  active: null,
  todo: 0,
  streaming: null,
}) as unknown as AgentStore;

/**
 * 走**真 reducer** 的 store：组件 `dispatch` 什么就真的算出下一个 state。
 *
 * 上面那个 `store()` 是把 catalog 写死的替身，只能证明「给了 true/false 会怎样」，
 * 证不了**字段真的从线上走到了界面上**。这个才是：真 `listAgents()` → 真 fetch →
 * 真 `CATALOG` 动作 → 真 reducer → 组件重渲染。
 *
 * **初值 `catalog: null`** 是承重的：Agent 列表只能由那一趟 `refreshAgents`
 * 送来。预先塞好 catalog 的话，fetch 那一环断掉测试照样绿。
 */
function zhenStore(): AgentStore {
  let state: AgentStoreState = { ...initialAgentState, catalog: null };
  return {
    ...({} as AgentStore),
    get state() { return state; },
    dispatch: (x: AgentAction) => { state = agentReducer(state, x); },
    setLayout: () => undefined,
    lastSeq: () => 0,
    get active() { return state.activeSessionId ? state.sessions[state.activeSessionId] ?? null : null; },
    todo: 0,
    streaming: null,
  } as unknown as AgentStore;
}

const api = (): AgentActions => ({
  preview: false, busy: null,
  act: {
    refreshAgents: async () => undefined,
    connect: async () => "s-1",
  },
} as unknown as AgentActions);

const dengDai = () => waitFor(() => expect(screen.getByRole("button", { name: /启动 Bridge|停止 Bridge/ })).toBeTruthy());

/** 填工作目录并点「连接并打开对话」——它会先走 setDelegation。 */
const lianJie = async () => {
  fireEvent.change(screen.getByPlaceholderText(/AIC-LifeOS/), { target: { value: "/tmp/x" } });
  fireEvent.click(screen.getByRole("button", { name: /连接并打开对话/ }));
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("三个 Bridge 按钮连点（真点，真传输层）", () => {
  it("启动 → 停止 → 连接 三连点全部成功，每一枚 token 都是现取的新鲜的", async () => {
    const { songChu } = jiaShei();
    render(<AgentsSection store={store()} api={api()} onGoChat={() => undefined} />);
    await dengDai();

    // 1. 启动 Bridge
    fireEvent.click(screen.getByRole("button", { name: /启动 Bridge/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /停止 Bridge/ })).toBeTruthy());

    // 2. 停止 Bridge —— 旧代码在这里 403：它复用了已被 1 消费掉的那枚
    fireEvent.click(screen.getByRole("button", { name: /停止 Bridge/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /启动 Bridge/ })).toBeTruthy());

    // 3. 连接并打开对话 —— setDelegation 也是消费型端点
    await lianJie();
    await waitFor(() => expect(songChu).toHaveLength(3));

    // 三枚互不相同：真后端上一枚用掉即作废，复用必 403
    expect(new Set(songChu).size).toBe(3);
    // 界面上不能出现 CSRF 错误
    expect(screen.queryByText(/CSRF/)).toBeNull();
  });

  it("服务端回 403 时界面如实报错，不假装成功", async () => {
    // 复刻旧 bug 的**确切形状**：`/api/bridge/info` 永远报同一枚陈旧 token，
    // 而服务端那边早就换新了。于是第一次成功、之后每次都 403。
    const CHEN_LAO = "tok-A";
    let weiZhi = CHEN_LAO; // 服务端当前那一枚
    let zaiYun = false;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/api/bridge/info")) {
        return hui200({
          running: zaiYun, port: 8766, pid: 42, instanceId: "i-1", cliVersion: "2.0.0",
          tunnelState: "none", deviceId: "dev-1", error: null,
          csrf: CHEN_LAO, // ← 陈旧：info 这条路不换新，正是旧代码的病根
          devices: [], paired: false,
        });
      }
      if (url.endsWith("/api/bridge/devices")) return hui200({ devices: [] });
      const song = (init?.headers as Record<string, string>)["X-LifeOS-CSRF"];
      if (song !== weiZhi) return hui403();
      weiZhi = "tok-B";
      if (url.endsWith("/api/bridge/start")) zaiYun = true;
      if (url.endsWith("/api/bridge/stop")) zaiYun = false;
      return hui200({ ok: true, port: 8766, closed: 1, enabled: true });
    }));
    render(<AgentsSection store={store()} api={api()} onGoChat={() => undefined} />);
    await dengDai();
    fireEvent.click(screen.getByRole("button", { name: /启动 Bridge/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /停止 Bridge/ })).toBeTruthy());
    // 第二枚必然失配 → 403 → 界面必须显示错误，而不是假装已停止
    fireEvent.click(screen.getByRole("button", { name: /停止 Bridge/ }));
    expect(await screen.findByText(/CSRF token 无效或已用过/)).toBeTruthy();
    // 按钮仍是「停止」——没假装停止成功
    expect(screen.getByRole("button", { name: /停止 Bridge/ })).toBeTruthy();
  });
});

/**
 * `credentialsReady` 走一遍真链路：真 fetch → 真 `listAgents()` → 真
 * `CATALOG` 动作 → 真 reducer → 组件重渲染。
 *
 * 上一组是替身 store（catalog 写死），只能证明「给 false 会渲染出那句话」，
 * 证不了**这个字段真的能从线上走到界面上**。而这一段路的每一环都可能悄悄吞掉
 * 一个字段——`/agents` 的 JSON 少一个 key、reducer 浅拷贝丢字段，
 * 这两种缺陷在只测替身 store 时都是隐形的。
 */
describe("credentialsReady 的真链路（真 fetch + 真 reducer）", () => {
  /** 一台只回三样东西的假服务端。`credentialsReady` 传 `undefined` = 那个键不写。 */
  const fuWuDuan = (credentialsReady?: boolean) => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith("/api/bridge/info")) {
        return hui200({
          running: true, port: 8766, pid: 42, instanceId: "i-1", cliVersion: "2.0.0",
          tunnelState: "none", deviceId: "dev-1", error: null,
          csrf: "tok-1", devices: [], paired: false,
        });
      }
      if (url.endsWith("/api/bridge/devices")) return hui200({ devices: [] });
      // 注意这里**不**给 CSRF 校验：`/agent-api/*` 走的是 Bridge token，不是 CSRF。
      return hui200({
        agents: [KE_DONG],
        suggestedDirs: [],
        ...(credentialsReady === undefined ? {} : { credentialsReady }),
        versionGate: {},
      });
    });
    vi.stubGlobal("fetch", fetchMock);
  };

  /**
   * `refreshAgents` 的真身只有两步：`listAgents()`（真 fetch）+
   * `dispatch({type:"CATALOG", ...})`。这里两步都借真的，只把 `preview` 判为 false，
   * 所以「线上那一步有没有把字段带过来」是真的被测到了——手写替身测不到那一段。
   */
  const zhenApi = (st: AgentStore): AgentActions => ({
    preview: false,
    busy: null,
    act: {
      refreshAgents: async () => {
        st.dispatch({ type: "CATALOG", catalog: await listAgents() });
      },
      connect: async () => "s-1",
    },
  } as unknown as AgentActions);

  const dengTai = (st: AgentStore) =>
    render(<AgentsSection store={st} api={zhenApi(st)} onGoChat={() => undefined} />);

  it("线上回 credentialsReady:false 时界面出现告警", async () => {
    fuWuDuan(false);
    dengTai(zhenStore());
    const alarm = await screen.findByText(/重新登录一次/);
    // 位置同样是承重的，且这一条比替身 store 那条更强：它证明**真链路**
    // 走完之后告警仍落在 `.ags` 顶部通栏，不在任何 `.ags-card` 里。
    //
    // **从 `role="alert"` 那个根元素出发**：`findByText` 命中的是内部 `<strong>`，
    // 从它往上 `closest(".ags")` 无论告警被挪进哪张卡都成立（控制器 2026-09-29
    // 实测：挪进去之后 20 条全绿）。真链路的价值在数据来源，不在位置判据。
    const gen = screen.getByRole("alert");
    expect(gen.closest(".ags-card")).toBeNull();
    expect(gen.parentElement?.className).toBe("ags");
  });

  it("线上回 credentialsReady:true 时没有告警", async () => {
    fuWuDuan(true);
    dengTai(zhenStore());
    // 等真的把 Agent 列表铺出来（证明这一趟 refreshAgents 走完了）再断言「没有」。
    expect(await screen.findByText("Claude Code")).toBeTruthy();
    expect(screen.queryByText(/重新登录一次/)).toBeNull();
  });

  it("旧 Bridge 不回这个键时**不**报警报——缺字段是「不知道」，不是「有问题」", async () => {
    fuWuDuan(undefined);
    dengTai(zhenStore());
    expect(await screen.findByText("Claude Code")).toBeTruthy();
    expect(screen.queryByText(/重新登录一次/)).toBeNull();
  });
});
