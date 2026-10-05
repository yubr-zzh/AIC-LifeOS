import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { initialAgentState, type AgentStore } from "../state/agentStore";
import type { AgentActions } from "../hooks/useAgentStream";
import type { BridgeInfo, DeviceRow } from "../api/agentClient";
import type { AgentsResponse } from "../api/agentTypes";

// `vi.spyOn(module, fn)` 拦不住组件里那个 import 绑定（ESM 命名空间是只读的，
// 组件拿到的是 live binding 而不是 spy 的替身）。所以整模块替掉。
vi.mock("../api/agentClient", async (importOriginal) => {
  const yuan = await importOriginal<typeof import("../api/agentClient")>();
  return {
    ...yuan,
    bridgeInfo: vi.fn(),
    devices: vi.fn(),
    pairCode: vi.fn(),
    unpair: vi.fn(),
    startBridge: vi.fn(),
    stopBridge: vi.fn(),
    setDelegation: vi.fn(),
  };
});

const client = await import("../api/agentClient");
const { AgentsSection } = await import("./AgentsSection");

/**
 * 配对与解绑（spec 8.1 / 8.3）。
 *
 * 这三条端点全部是一次性 CSRF，所以测的不只是「点了按钮调了接口」，
 * 还要验**每次调之前都现取了一枚新 token**——用旧的那枚必 403，
 * 症状是用户点一下「添加设备」什么都没发生。
 */

const sheBei = (a: Partial<DeviceRow> & { deviceId: string }): DeviceRow => ({
  userId: "local", label: "本机", pairedAt: 1, lastSeenAt: 2,
  instanceId: "i-1", revoked: false, online: false, ...a,
});

const xinXi = (a: Partial<BridgeInfo> = {}): BridgeInfo => ({
  running: false, port: null, pid: null, instanceId: null, cliVersion: null,
  tunnelState: "local", deviceId: null, error: null, csrf: "tok-1",
  devices: [], paired: false, ...a,
});

const dummyStore = () => ({
  state: initialAgentState, dispatch: () => undefined, setLayout: () => undefined,
  lastSeq: () => 0, active: null, todo: 0, streaming: null,
}) as unknown as AgentStore;

const dummyApi = () => ({
  preview: false, busy: null,
  act: { refreshAgents: async () => undefined, connect: async () => "s-1" },
}) as unknown as AgentActions;

/**
 * `credentialsReady` 是**可选字段**，所以造 catalog 时默认不写它——
 * 那样造出来的就是「字段缺失」那一路（= 旧 Bridge 连新前端），不能被默认值偷偷放过。
 */
const catalog = (a: Partial<AgentsResponse> = {}) =>
  ({ agents: [], suggestedDirs: [], ...a }) as unknown as AgentsResponse;

function zhuangCatalog(bei: DeviceRow[] = [], xin: Partial<BridgeInfo> = {}, cat: AgentsResponse | null = null) {
  vi.mocked(client.bridgeInfo).mockResolvedValue(xinXi({ ...xin, devices: bei }));
  vi.mocked(client.devices).mockResolvedValue({ devices: bei });
  vi.mocked(client.pairCode).mockResolvedValue({ code: "K4M-9QX", expiresAt: Date.now() + 300_000 });
  vi.mocked(client.unpair).mockResolvedValue({ ok: true, tunnelClosed: true });
  vi.mocked(client.startBridge).mockResolvedValue({ ok: true });
  vi.mocked(client.stopBridge).mockResolvedValue({ ok: true });
  vi.mocked(client.setDelegation).mockResolvedValue({ enabled: true });
  render(
    <AgentsSection
      store={{ ...dummyStore(), state: { ...initialAgentState, catalog: cat } } as unknown as AgentStore}
      api={dummyApi()}
      onGoChat={() => undefined}
    />,
  );
}

function zhuang(bei: DeviceRow[] = [], xin: Partial<BridgeInfo> = {}) {
  vi.mocked(client.bridgeInfo).mockResolvedValue(xinXi({ ...xin, devices: bei }));
  vi.mocked(client.devices).mockResolvedValue({ devices: bei });
  const ma = vi.mocked(client.pairCode);
  ma.mockResolvedValue({ code: "K4M-9QX", expiresAt: Date.now() + 300_000 });
  const jie = vi.mocked(client.unpair);
  jie.mockResolvedValue({ ok: true, tunnelClosed: true });
  vi.mocked(client.startBridge).mockResolvedValue({ ok: true });
  vi.mocked(client.stopBridge).mockResolvedValue({ ok: true });
  vi.mocked(client.setDelegation).mockResolvedValue({ enabled: true });
  render(<AgentsSection store={dummyStore()} api={dummyApi()} onGoChat={() => undefined} />);
  return { ma, jie };
}

afterEach(() => vi.restoreAllMocks());

describe("AgentsSection 的配对与设备列表", () => {
  it("tunnelState 的中文映射在界面上真的生效——隧道形态下不能显示裸的 none", async () => {
    vi.mocked(client.bridgeInfo).mockResolvedValue(xinXi({ tunnelState: "none" }));
    render(<AgentsSection store={dummyStore()} api={dummyApi()} onGoChat={() => undefined} />);
    await waitFor(() => expect(screen.getByText("未配对")).toBeTruthy());
    expect(screen.queryByText("none")).toBeNull();
  });

  it("「添加设备」换出配对码，并把码和本机地址一起显示出来", async () => {
    // CSRF 的「每次现取」由 agentClient.test.ts 在 fetch 层验；这里只管界面。
    // 挂载时那趟 tiao 持着 busy，按钮要等它落地才点得动。
    zhuang([sheBei({ deviceId: "dev-1", label: "笔记本" })], { port: 8767 });
    await screen.findByText("笔记本");
    fireEvent.click(screen.getByRole("button", { name: /添加设备/ }));
    // 断言的是**码真的显示出来了**，不只是 pairCode 被调过。
    expect(await screen.findByText("K4M-9QX")).toBeTruthy();
    // 端口取 `info.port`，不是写死的 8766（spec 5.1 的明文铁律）。
    expect(screen.getByText(/127\.0\.0\.1:8767\/pair/)).toBeTruthy();
  });

  it("设备列表来自 devices()，每行一个解绑按钮", async () => {
    zhuang([sheBei({ deviceId: "dev-1", label: "笔记本" })]);
    expect(await screen.findByText("笔记本")).toBeTruthy();
    expect(screen.getByRole("button", { name: /解绑/ })).toBeTruthy();
  });

  it("解绑走的是那一行自己的 deviceId", async () => {
    const { jie } = zhuang([sheBei({ deviceId: "dev-9", label: "笔记本" })]);
    fireEvent.click(await screen.findByRole("button", { name: /解绑/ }));
    fireEvent.click(await screen.findByRole("button", { name: /^确定解绑/ }));
    await waitFor(() => expect(jie).toHaveBeenCalledWith("dev-9"));
  });

  it("解绑之后明说「已被解绑」——不删行是刻意的：删掉像那台设备从没存在过", async () => {
    const { jie } = zhuang([sheBei({ deviceId: "dev-9" })]);
    fireEvent.click(await screen.findByRole("button", { name: /解绑/ }));
    fireEvent.click(await screen.findByRole("button", { name: /^确定解绑/ }));
    await waitFor(() => expect(jie).toHaveBeenCalled());
    expect(await screen.findByText(/已被解绑/)).toBeTruthy();
  });
});

/**
 * 评审发现 4：解绑是不可逆的凭据吊销 + 一次线上连接的切断，原来单击即生效、
 * 没有确认；而且调用处不看 `ok`，后端回 `{ok:false}`（HTTP 200）时界面照样显示
 * 「设备已被解绑」——失败被显示成了成功。
 */
describe("AgentsSection 的解绑确认与 ok", () => {
  it("单击「解绑」不发请求，只进入确认态——吊销凭据不可逆，不能单击即生效", async () => {
    const { jie } = zhuang([sheBei({ deviceId: "dev-9", label: "笔记本" })]);
    fireEvent.click(await screen.findByRole("button", { name: /解绑/ }));
    // 第一次点击只应该出现确认按钮，不该发出任何请求。
    expect(await screen.findByRole("button", { name: /^确定解绑/ })).toBeTruthy();
    expect(jie).not.toHaveBeenCalled();
  });

  it("点「取消」不发请求，回到原样", async () => {
    const { jie } = zhuang([sheBei({ deviceId: "dev-9", label: "笔记本" })]);
    fireEvent.click(await screen.findByRole("button", { name: /解绑/ }));
    fireEvent.click(await screen.findByRole("button", { name: /^取消解绑/ }));
    expect(jie).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /^确定解绑/ })).toBeNull();
    expect(screen.getByRole("button", { name: /^解绑$/ })).toBeTruthy();
  });

  it("后端回 ok:false 时界面不能显示「已被解绑」——失败被显示成成功是最坏的失败形态", async () => {
    const { jie } = zhuang([sheBei({ deviceId: "dev-9", label: "笔记本" })]);
    jie.mockResolvedValue({ ok: false, tunnelClosed: false });
    fireEvent.click(await screen.findByRole("button", { name: /解绑/ }));
    fireEvent.click(await screen.findByRole("button", { name: /^确定解绑/ }));
    await waitFor(() => expect(jie).toHaveBeenCalled());
    expect(screen.queryByText(/已被解绑/)).toBeNull();
    // 解绑按钮还在，说明没有假装成功
    expect(screen.getByRole("button", { name: /^解绑$/ })).toBeTruthy();
  });
});

/**
 * 评审发现 3：`/pair` 是 **Bridge 自己**在 8766–8770 上的路由（`http.py:187`），
 * 界面上显示的却是**远端设备**要打开的入口。原来写死 `127.0.0.1:{info?.port ?? 8766}`，
 * 在隧道形态下这个地址对用户那台机器毫无意义。
 *
 * 判据是 `info.port` 在不在，不是 `tunnelState`：见 `PeiDuiRuKou` 的注释
 * ——`tunnelState` 的默认值 `"local"` 出现在读不到 runtime.json 时，而那一路
 * 在给 port 赋值之前就 return 了，两者永远互斥。
 */
describe("AgentsSection 的配对入口地址", () => {
  const tianMa = async (xin: Partial<BridgeInfo>) => {
    zhuang([], xin);
    fireEvent.click(await screen.findByRole("button", { name: /添加设备/ }));
    await screen.findByText("K4M-9QX");
  };

  it("本机直连形态（本机有 Bridge、有端口）下给出的是本机回环地址", async () => {
    // 本机直连时 Bridge 刚启动、`zao_yun` 刻意不写 tunnelState，`xinxi()`
    // 于是报 `none`。这一条顺带钉住：判据不是 tunnelState。
    await tianMa({ tunnelState: "none", port: 8766 });
    expect(screen.getByText(/127\.0\.0\.1:8766\/pair/)).toBeTruthy();
  });

  it("端口漂到 8770 时地址跟着漂——spec 5.1 禁止硬编码 8766", async () => {
    await tianMa({ tunnelState: "connected", port: 8770 });
    expect(screen.getByText(/127\.0\.0\.1:8770\/pair/)).toBeTruthy();
  });

  it("隧道形态（云端这台机器上没有 Bridge）下不给一个打不开的回环地址", async () => {
    // `port` 为 null 就是判据：tunnelState 此时恰恰是 "local"（默认值），
    // 拿 tunnelState 判形态的写法会误以为这是本机直连。
    await tianMa({ tunnelState: "local", port: null });
    expect(screen.queryByText(/127\.0\.0\.1/)).toBeNull();
    expect(screen.getByText(/目标设备/)).toBeTruthy();
  });

  it("取不到端口时不给兜底的 8766", async () => {
    await tianMa({ tunnelState: "connected", port: null });
    expect(screen.queryByText(/8766/)).toBeNull();
  });
});

/**
 * 阶段 6-10 的 `credentialsReady`（spec 11.2 明文，承重 3）。
 *
 * 后端给不出这个 uid 的凭据目录时按 11.2「不让 Bridge 起不来」只告警继续跑，
 * 代价是用户落到一个**空的**凭据库、必须重新登录一次。界面上没有出口的话，
 * 症状就只剩「怎么又要登录一次」——用户完全不知道有地方要修。
 *
 * 断言的是**提示真的出现在 DOM 里**，不是「渲染没崩」：后者在没接这个字段的
 * 代码上同样成立，证明不了任何东西。
 */
describe("AgentsSection 的凭据目录告警（credentialsReady）", () => {
  it("false 时明说「重新登录一次」，并给出下一步要查的两件事", async () => {
    zhuangCatalog([], {}, catalog({ credentialsReady: false }));
    const alarm = await screen.findByText(/重新登录一次/);
    // 下一步必须具体到能照着做：磁盘 + 那个目录可不可写
    expect(screen.getByText(/lifeos-bridge/)).toBeTruthy();

    // 告警必须是 `.ags` 的**直接**子元素（通栏），不是任何 `.ags-card` 的后代。
    // 判据用 `closest`：`credentialsReady` 与 `available` 是两件事，用户处置路径
    // 不同（一个要装 claude，一个要清磁盘/改目录权限），并进「Agent 不可用」那张卡
    // 等于把它并进那一堆。上一行只钉了「有这句话」，把它挪进卡里照样全绿。
    //
    // **必须从告警根元素出发，不能从匹配到的文本出发。** `findByText` 命中的是
    // 内部那个 `<strong>`，从它 `closest(".ags")` 一路上来无论告警被挪进哪张卡
    // 都成立——判据选错元素，这条断言就成了摆设（控制器 2026-09-29 实测：
    // 告警挪进卡片后 20 条测试全绿）。
    const gen = screen.getByRole("alert");
    expect(gen.closest(".ags-card")).toBeNull();
    expect(gen.parentElement?.className).toBe("ags");
  });

  it("true 时不显示任何凭据告警——正常情况是常态，不该天天占屏", async () => {
    zhuangCatalog([], {}, catalog({ credentialsReady: true }));
    await screen.findByText("还没有配对过任何设备。");
    expect(screen.queryByText(/重新登录一次/)).toBeNull();
  });

  it("字段缺失（旧 Bridge）时**不**报警报——`!undefined` 是 true，把它显示成故障就是假警报", async () => {
    zhuangCatalog([], {}, catalog());
    await screen.findByText("还没有配对过任何设备。");
    expect(screen.queryByText(/重新登录一次/)).toBeNull();
  });
});
