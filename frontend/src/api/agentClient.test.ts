import { afterEach, describe, expect, it, vi } from "vitest";
import {
  bridgeInfo,
  devices,
  openAgentStream,
  pairCode,
  setDelegation,
  startBridge,
  stopBridge,
  unpair,
} from "./agentClient";
import type { DownFrame } from "./agentTypes";

/**
 * SSE 重连。
 *
 * 要验的是三件容易错的事：
 * 1. 重连必须带 lastEventId（EventSource 自带重连带不了自定义 query，
 *    不补发就等于丢帧）
 * 2. 指数退避要真的退避
 * 3. 僵尸连接（被 close 掉的那条）的回调不许再改状态
 */

const kai: {
  url: string;
  close: () => void;
  fire: (a: string, b: unknown) => void;
  raw: (a: string, b: string) => void;
  onerror?: () => void;
}[] = [];

class FakeEventSource {
  close = vi.fn();
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, ((e: MessageEvent<string>) => void)[]>();

  constructor(public url: string) {
    const raw = (lei: string, data: string) => {
      for (const fn of this.listeners.get(lei) ?? []) fn({ data } as MessageEvent<string>);
    };
    kai.push({
      url,
      close: () => this.close(),
      raw,
      fire: (lei, data) => raw(lei, JSON.stringify(data)),
      onerror: () => this.onerror?.(),
    });
  }

  addEventListener(lei: string, fn: (e: MessageEvent<string>) => void) {
    this.listeners.set(lei, [...(this.listeners.get(lei) ?? []), fn]);
  }
}

const kaiFake = () => {
  kai.length = 0;
  vi.stubGlobal("EventSource", FakeEventSource);
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("openAgentStream", () => {
  it("首次连接带上当前游标", () => {
    kaiFake();
    const h = openAgentStream({ onFrame: () => undefined, onState: () => undefined, lastSeq: () => 17 });
    expect(kai[0].url).toContain("lastEventId=17");
    h.close();
  });

  it("重连时用更大的游标，并按指数退避", async () => {
    kaiFake();
    // onerror 会先探一次 /health 区分「凭据失效」和「网络抖动」，
    // 那一步是异步的，所以这里要让 fetch 立刻失败并等一拍。
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    vi.useFakeTimers();
    let cur = 17;
    const states: string[] = [];
    const h = openAgentStream({
      onFrame: () => undefined,
      onState: (s) => states.push(s),
      lastSeq: () => cur,
    });

    cur = 30;
    kai[0].onerror?.();
    await vi.advanceTimersByTimeAsync(0);
    expect(kai).toHaveLength(1); // 还没退避完，不急着重连

    await vi.advanceTimersByTimeAsync(1000);
    expect(kai).toHaveLength(2);
    expect(kai[1].url).toContain("lastEventId=30");
    expect(states).toContain("reconnecting");
    h.close();
  });

  it("close 之后旧连接再触发回调也不改状态（僵尸连接防护）", () => {
    kaiFake();
    const states: string[] = [];
    const frames: DownFrame[] = [];
    const h = openAgentStream({
      onFrame: (f) => frames.push(f),
      onState: (s) => states.push(s),
      lastSeq: () => 0,
    });
    const before = states.length;
    h.close();
    kai[0].fire("state", { type: "state", sessionId: "s", streamSeq: 1, state: "working", lastEvent: "x" });
    expect(frames).toHaveLength(0);
    expect(states).toHaveLength(before);
  });

  it("按类型派发——只挂 onmessage 的话 addEventListener('message') 收不到", () => {
    kaiFake();
    const frames: DownFrame[] = [];
    const h = openAgentStream({ onFrame: (f) => frames.push(f), onState: () => undefined, lastSeq: () => 0 });
    kai[0].fire("chunk", { type: "chunk", sessionId: "s", streamSeq: 1, messageId: "m", delta: "a", messageKind: "text" });
    kai[0].fire("result", { type: "result", sessionId: "s", streamSeq: 2, batchDone: 1, batchTotal: 1 });
    expect(frames.map((f) => f.type)).toEqual(["chunk", "result"]);
    h.close();
  });

  it("坏 JSON 变成一条可恢复的 error 帧，不抛", () => {
    kaiFake();
    const frames: DownFrame[] = [];
    const h = openAgentStream({ onFrame: (f) => frames.push(f), onState: () => undefined, lastSeq: () => 0 });
    // 直接把坏数据塞进监听器，绕开序列化
    kai[0].raw("state", "{不是 JSON");
    expect(frames).toHaveLength(1);
    expect(frames[0].type).toBe("error");
    expect(frames[0]).toMatchObject({ code: "internal", recoverable: true });
    h.close();
  });
});

/**
 * 管控端点的 CSRF 是一次性的。
 *
 * `bridge_admin.yong_ma` 校验通过就把 `_MA["token"]` 换掉，所以**拿一枚用两次必然 403**。
 * 界面上「启动 Bridge」「停止 Bridge」「添加设备」「解绑」各自都会消费掉一枚，
 * 共用同一枚的结果就是随机失败——所以每次调用都现取。
 */

const hui200 = (a: unknown) => ({ ok: true, status: 200, json: async () => a }) as Response;

/** 每次 `info()` 返回一枚**不同**的 token——真后端就是这么轮换的。 */
const tuiFetch = () => {
  let hao = 0;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/api/bridge/info")) return hui200({ csrf: `tok-${++hao}` });
    return hui200({ devices: [], code: "K4M-9QX", expiresAt: Date.now() + 300_000, ok: true, tunnelClosed: true });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
};

describe("管控端点的 CSRF", () => {
  it("devices 每次都现取一枚新 token，并用 X-LifeOS-CSRF 送出去", async () => {
    const f = tuiFetch();
    await devices();
    await devices();
    // 两次 devices 必须是「取 token → 查列表」两轮，不能第二轮直接复用第一轮的
    expect(f.mock.calls.map((c) => String(c[0]))).toEqual([
      "/api/bridge/info", "/api/bridge/devices",
      "/api/bridge/info", "/api/bridge/devices",
    ]);
    const ma = f.mock.calls
      .filter((c) => String(c[0]).endsWith("/devices"))
      .map((c) => (c[1]?.headers as Record<string, string>)["X-LifeOS-CSRF"]);
    // 两枚必须是不同的——用同一枚发第二次必然 403
    expect(ma).toHaveLength(2);
    expect(ma[0]).not.toBe(ma[1]);
  });

  it("pairCode 与 unpair 也各自现取——它们同样是消费型端点", async () => {
    const f = tuiFetch();
    await pairCode();
    await unpair("dev-1");
    expect(f.mock.calls.map((c) => String(c[0]))).toEqual([
      "/api/bridge/info", "/api/bridge/pair-code",
      "/api/bridge/info", "/api/bridge/unpair",
    ]);
    const fu = f.mock.calls.find((c) => String(c[0]).endsWith("/unpair"));
    expect(JSON.parse(String(fu?.[1]?.body))).toEqual({ deviceId: "dev-1" });
  });

  /**
   * 评审发现 1：startBridge / stopBridge / setDelegation 原来收调用方传进来的 csrf，
   * 而界面那枚 `info.csrf` 是挂载时取的一次、之后不再刷新。于是「启动 Bridge」
   * 一成功就把它消费掉，「停止 Bridge」与「连接并打开对话」必然 403，
   * 而且除了重载页面没有任何恢复手段。
   *
   * 修法是这三个也零参数、内部现取。测法与 devices 一样：断言请求序列，
   * 并断言两次拿到的是**不同的** token（`tuiFetch` 每次 `info()` 换一枚）。
   */
  it("startBridge / stopBridge / setDelegation 每次都现取一枚新 token", async () => {
    const f = tuiFetch();
    await startBridge();
    await stopBridge();
    await setDelegation(true);
    expect(f.mock.calls.map((c) => String(c[0]))).toEqual([
      "/api/bridge/info", "/api/bridge/start",
      "/api/bridge/info", "/api/bridge/stop",
      "/api/bridge/info", "/api/settings/delegation",
    ]);
    const ma = f.mock.calls
      .filter((c) => String(c[0]) !== "/api/bridge/info")
      .map((c) => (c[1]?.headers as Record<string, string>)["X-LifeOS-CSRF"]);
    expect(ma).toHaveLength(3);
    expect(new Set(ma).size).toBe(3);
  });

  /**
   * 评审发现 2：`BridgeInfo.devices` 的元素类型声明了必填 `online: boolean`，
   * 但后端 `xinxi()` 走的是 `SHE.lie()`，**不加** `online`（只有 `she_lie()` 加）。
   * 谁按注释用法接上首屏，谁就会把每台在线设备显示成「离线」。
   *
   * 修法是让类型与真实返回一致——`online` 去掉。`info.devices` 在生产代码里
   * 零读者，给它补齐字段是给一个没人用的类型加字段，划不来。
   */
  it("info 的设备表与 devices() 的设备表不是同一份形状", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.endsWith("/api/bridge/info")) {
        return hui200({ csrf: "tok-1", devices: [{ deviceId: "dev-1", userId: "local" }] });
      }
      return hui200({ devices: [{ deviceId: "dev-1", userId: "local", online: true }] });
    }));
    // `xinxi()` 的 `devices[]` 每条只有 7 个字段，没有 `online`。
    const xin = (await bridgeInfo()).devices[0];
    expect(Object.keys(xin)).toEqual(["deviceId", "userId"]);
    expect("online" in xin).toBe(false);
    // 而 `devices()` 走 `she_lie()`，带 `online`。
    expect((await devices()).devices[0].online).toBe(true);
  });
});

/**
 * 发现 2 的类型层守卫，`npm run typecheck` 会验。
 *
 * 运行时那条测试管的是「后端真的给了什么」，这条管的是「类型不许承诺什么」——
 * 两者是同一件事的两面：类型撒了谎而 `tsc` 不报错，正是这条发现承重的地方。
 */
type XinSheBei = Awaited<ReturnType<typeof bridgeInfo>>["devices"][number];
// @ts-expect-error `xinxi()` 不返回 `online`（只有 `she_lie()` 加）。一旦有人给
// 这张表加回 `online`（或任何 `she_lie()` 专属字段），这行就不再报错，
// `@ts-expect-error` 变成多余的，typecheck 直接红。
const _xinOnline: boolean = {} as XinSheBei["online"];
