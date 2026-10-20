// Agent 域的传输层：SSE 订阅 + 全部 Bridge POST。
//
// 凭据纪律（方案 1.3 铁律）：**token 绝不进浏览器**。本模块只请求 `/agent-api/*`，
// 由 vite 的代理进程读 runtime.json 注入 X-Bridge-Token 与 ?token=。
// 公网形态下换成主服务反代隧道，前端代码一行不用改。

import {
  AgentsResponse,
  AgentSession,
  AnswerRequest,
  BridgeError,
  CreateSessionRequest,
  DecideRequest,
  DownFrame,
  PermissionMode,
  ResultFrame,
} from "./agentTypes";

const BASE = "/agent-api";
const STREAM = `${BASE}/stream`;

async function duError(res: Response): Promise<BridgeError> {
  // 401 拦截（方案 6.4）：会话失效时广播，AuthGate 收到后切登录页。
  if (res.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("lifeos:unauthorized"));
  }
  let code = "internal";
  let message = `HTTP ${res.status}`;
  let payload: Record<string, unknown> = {};
  try {
    const body = (await res.json()) as {
      error?: { code?: string; message?: string };
      code?: string;
      message?: string;
    };
    payload = body as Record<string, unknown>;
    code = body.error?.code ?? body.code ?? code;
    message = body.error?.message ?? body.message ?? message;
  } catch {
    /* 响应体不是 JSON，用状态码兜底 */
  }
  return new BridgeError(res.status, code, message, payload);
}

async function post<T>(a: string, b?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${a}`, {
    method: "POST",
    headers: b === undefined ? undefined : { "content-type": "application/json" },
    body: b === undefined ? undefined : JSON.stringify(b),
  });
  if (!res.ok) throw await duError(res);
  return (await res.json()) as T;
}

async function get<T>(a: string): Promise<T> {
  const res = await fetch(`${BASE}${a}`);
  if (!res.ok) throw await duError(res);
  return (await res.json()) as T;
}

/** 主服务（不是 Bridge）的 GET。两者基址不同，token 也不共用。 */
async function get2<T>(a: string, c?: string): Promise<T> {
  const res = await fetch(a, c ? { headers: { "X-LifeOS-CSRF": c } } : undefined);
  if (!res.ok) throw await duError(res);
  return (await res.json()) as T;
}

export const listAgents = () => get<AgentsResponse>("/agents");

/** 主服务侧的 Bridge 状态。**注意这里没有 token**——10.2 刻意不往下发。 */
export interface BridgeInfo {
  running: boolean;
  port: number | null;
  pid: number | null;
  instanceId: string | null;
  cliVersion: string | null;
  tunnelState: string;
  deviceId: string | null;
  error: string | null;
  csrf: string;
  /** `bridge_admin.xinxi()` 顺带回来的设备表。**注意它没有 `online`**（见 `DeviceRecord`）——
   *  真要用在线状态做首屏，请调 `devices()` 现问，别在这里拿。 */
  devices: DeviceRecord[];
  paired: boolean;
}

export const bridgeInfo = () => get2<BridgeInfo>("/api/bridge/info");

/**
 * **CSRF 是一次性的，用掉即作废**（`bridge_admin.yong_ma` 校验通过就换新 token）。
 *
 * 所以**所有**管控端点都**不收** csrf 参数，而是自己现取一枚。传进来是历史包袱：
 * 调用方手上那枚几乎肯定已经被上一个端点消费掉了——界面那份 `info.csrf`
 * 是挂载时取的一次、此后不再刷新，于是「启动 Bridge」一成功，「停止 Bridge」
 * 与「连接并打开对话」必然 403，且除了重载页面没有任何恢复手段。
 */
async function xinMa(): Promise<string> {
  return (await bridgeInfo()).csrf;
}

/**
 * 状态改变型端点要带一次性 CSRF token（10.2）。
 *
 * **入参是完整路径，已经含 `/api` 前缀。** 服务端的路由就是 `/api/bridge/start`，
 * 这里再拼一次前缀会变成 `/api/api/...`——真实 bug，阶段 4 起就在：
 * `startBridge` / `stopBridge` / `setDelegation` 在生产形态（主服务直接托管 dist）
 * 下一直 404，开发环境是被 vite 的 proxy 重写规则顺手救回来的。
 */
async function post2<T>(a: string, b: unknown, c: string): Promise<T> {
  const res = await fetch(a, {
    method: "POST",
    headers: { "content-type": "application/json", "X-LifeOS-CSRF": c },
    body: JSON.stringify(b ?? {}),
  });
  if (!res.ok) throw await duError(res);
  return (await res.json()) as T;
}

export const startBridge = () =>
  xinMa().then((c) => post2<{ ok: boolean; port?: number; error?: string }>("/api/bridge/start", {}, c));
export const stopBridge = () =>
  xinMa().then((c) => post2<{ ok: boolean; closed?: number; error?: string }>("/api/bridge/stop", {}, c));
export const setDelegation = (enabled: boolean) =>
  xinMa().then((c) => post2<{ enabled: boolean }>("/api/settings/delegation", { enabled }, c));

// ---- 阶段 6：配对与设备表（spec 8.3）----

/**
 * `devices.json` 里的一条记录，**去掉 tokenHash**（`SheBiao.lie()` 的返回形状）。
 *
 * `online` 不在这里：它来自网关的路由表，**只有 `she_lie()` 加**，
 * `xinxi()` 走的是 `SHE.lie()`、从不加。给 `BridgeInfo.devices` 挂一个必填
 * `online` 会让下一个按注释用法接上首屏的人把每台在线设备显示成「离线」。
 */
export interface DeviceRecord {
  deviceId: string;
  userId: string;
  label: string;
  pairedAt: number;
  lastSeenAt: number;
  instanceId: string;
  revoked: boolean;
}

/** `she_lie()` 的返回 = 记录 + 现问现填的 `online`（`/api/bridge/devices`）。 */
export interface DeviceRow extends DeviceRecord {
  /** 现问现填，来自网关的路由表，不在 devices.json 里（`bridge_admin.she_lie`）。 */
  online: boolean;
}

export const pairCode = () =>
  xinMa().then((c) => post2<{ code: string; expiresAt: number }>("/api/bridge/pair-code", {}, c));

export const unpair = (deviceId: string) =>
  xinMa().then((c) => post2<{ ok: boolean; tunnelClosed: boolean }>("/api/bridge/unpair", { deviceId }, c));

/** 设备列表。它也是管控端点（`_shou_quan_guan`），同样要一枚现取的 token。
 *  方法是 GET（`server.do_GET`），但闸门与 POST 那三个完全同源复用。 */
export const devices = () =>
  xinMa().then((c) => get2<{ devices: DeviceRow[] }>("/api/bridge/devices", c));

// ---- 改动二（2026-10-10）：原生目录选择 + 信任根确认 ----

export interface PickFolderResult {
  /** 所选目录；null = 用户取消了对话框（此时输入框不动）。 */
  path: string | null;
  /** 只在 path 非 null 时有意义：所选目录是否已落在信任根内。 */
  inTrustRoot: boolean;
}

/** 弹本机原生「选择文件夹」对话框（方案 7.1 双形态）。
 *
 * 桌面壳（pywebview）在 → 走 `pywebview.api.select_folder()`（对话框模态于
 * 应用窗口）；浏览器 → 走 bridge 的 `/pick-folder`。两条通道同一契约
 * `{path: string|null}`；桌面壳选完路径后补一次 `/trust-check` 拿
 * inTrustRoot——信任根判定唯一实现在 planner_guard，桌面壳不复制。
 * 之后的信任确认流程（黄字提示 → /trust-folder）两种形态完全一致。
 */
export const pickFolder = async (startIn?: string): Promise<PickFolderResult> => {
  const api = (window as unknown as { pywebview?: { api?: { select_folder?: () => Promise<string | null> } } })
    .pywebview?.api;
  if (api?.select_folder) {
    const lu = await api.select_folder();
    if (lu === null || lu === undefined) return { path: null, inTrustRoot: false };
    const zhi = await get<{ path: string; inTrustRoot: boolean }>(
      `/trust-check?path=${encodeURIComponent(lu)}`);
    return { path: zhi.path, inTrustRoot: zhi.inTrustRoot };
  }
  return post<PickFolderResult>("/pick-folder", { startIn: startIn || undefined });
};

/** 用户确认后，把信任根外的目录追加进 Bridge 的信任根（闸门 3 的白名单）。 */
export const trustFolder = (path: string) =>
  post<{ ok: boolean; path: string }>("/trust-folder", { path });

export const health = () =>
  get<{ ok: boolean; pid: number; uptimeSec: number; version: string; instanceId: string }>("/health");

/** 桌面壳形态判定（方案 4.4/7.1）：pywebview 存在即 exe 壳。 */
export const zaiZhuoMian = (): boolean =>
  typeof window !== "undefined" &&
  Boolean((window as unknown as { pywebview?: unknown }).pywebview);

/** 打开数据/日志目录（方案 4.4）。仅桌面壳有实现；浏览器形态不显示入口。 */
export function daKaiRiZhi(): void {
  const api = (window as unknown as { pywebview?: { api?: { open_logs?: () => void } } })
    .pywebview?.api;
  void api?.open_logs?.();
}

export const createSession = (a: CreateSessionRequest) =>
  post<{ session: AgentSession }>("/sessions", a).then((r) => r.session);

export const sendInstructions = (a: string, b: { text?: string; instructions?: string[] }) =>
  post<{ messageId: string; seq: number }>(`/sessions/${a}/messages`, b);

export const interruptSession = (a: string) => post<{ ok: boolean; resolved: number }>(`/sessions/${a}/interrupt`);

export const closeSession = (a: string) => post<{ ok: boolean }>(`/sessions/${a}/close`);

export const setPermissionMode = (a: string, b: PermissionMode) =>
  post<{ ok: boolean; permissionMode: PermissionMode; effectiveMode: PermissionMode }>(
    `/sessions/${a}/mode`,
    { permissionMode: b },
  );

export const decidePermission = (a: string, b: DecideRequest) =>
  post<{ ok: boolean; decision: string; autoDecided: boolean; autoReason: string | null }>(
    `/permissions/${a}`,
    b,
  );

export const answerQuestion = (a: string, b: AnswerRequest) =>
  post<{ ok: boolean; state: string }>(`/questions/${a}`, b);

export interface TranscriptResponse {
  messages: import("./agentTypes").AgentMessage[];
  /** 末条消息的 xuhao。增量追赶时拿它当下一次的 `from`。空批次时回请求的 from。 */
  nextFrom: number;
  /** 首条消息的 xuhao。向上翻时拿它当 `before`。空批次时是 null。 */
  prevBefore: number | null;
  /** 翻页方向上还有没给的。false 时前端不要再发向上翻的请求。 */
  hasMore: boolean;
}

/**
 * 补拉一条会话的消息。
 *
 * **三种取法靠参数区分，`limit` 不在前端定死——默认 50 与钳到 [1,50] 都在服务端，
 * 单一事实源在那里。**
 *
 * | 调用目的 | 参数 | 取到的是 |
 * |---|---|---|
 * | 首屏 | `from = 0` | 末尾 limit 条 |
 * | 向上翻 | `before = 最早一条的 xuhao` | 该窗口末尾 limit 条 |
 * | 增量追赶 | `from = 已收到的最大 xuhao` | 该窗口最早 limit 条 |
 *
 * 增量必须取最早：一次断线进来 200 条而 limit 是 50，取末尾会把中间 150 条
 * 静默跳过去，界面上凭空少一大段对话。
 */
export async function transcript(a: string, b: number, c?: { limit?: number; before?: number }): Promise<TranscriptResponse> {
  const q = new URLSearchParams({ from: String(b) });
  if (c?.limit !== undefined) q.set("limit", String(c.limit));
  if (c?.before !== undefined) q.set("before", String(c.before));
  try {
    return await get<TranscriptResponse>(`/sessions/${a}/transcript?${q}`);
  } catch (e) {
    // 409 reset_required：Bridge 重启过，旧游标作废。必须让调用方知道要全量重置，
    // 静默返回空数组会让界面空白而 Agent 还在跑。
    if (e instanceof BridgeError && e.code === "reset_required") throw e;
    throw e;
  }
}

// ---- SSE ----

export type StreamState = "connecting" | "open" | "reconnecting" | "offline" | "unauthorized";

export interface StreamHandle {
  close(): void;
}

export interface StreamOptions {
  onFrame: (a: DownFrame) => void;
  onState: (a: StreamState, a2?: string) => void;
  /** 读当前已处理的最大 streamSeq，重连时作为 lastEventId 送回。 */
  lastSeq: () => number;
  /** 预览模式下换成假帧源。 */
  fake?: AsyncGenerator<DownFrame>;
}

const ZUI_DI = [1000, 2000, 4000, 8000, 15000, 30_000];

/**
 * 建立 SSE 连接并自行管理重连。
 *
 * 不用 EventSource 自带重连：它不会带我们自定义的 `lastEventId` 查询参数，
 * 而 7.2 的断点续传依赖它——重连后不补发就等于丢帧。所以 onerror 时关掉自己、
 * 按指数退避重新 new 一个。
 */
export function openAgentStream(a: StreamOptions): StreamHandle {
  let shut = false;
  let zhao = 0; // 世代号：僵尸连接的回调靠它识别并丢弃
  let src: EventSource | null = null;
  let xu: AsyncGenerator<DownFrame> | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const closeAll = () => {
    if (timer) clearTimeout(timer);
    timer = null;
    if (src) {
      src.close();
      src = null;
    }
    if (xu) {
      void xu.return(undefined);
      xu = null;
    }
  };

  const kai = async () => {
    if (shut) return;
    const dai = ++zhao;

    if (a.fake) {
      a.onState("open");
      xu = a.fake;
      void (async () => {
        try {
          for await (const zhen of xu) {
            if (shut || dai !== zhao) return;
            a.onFrame(zhen);
          }
        } catch (e) {
          if (!shut && dai === zhao) a.onState("offline", String(e));
        }
      })();
      return;
    }

    a.onState(zhao === 1 ? "connecting" : "reconnecting");
    const url = `${STREAM}?lastEventId=${a.lastSeq()}`;
    src = new EventSource(url);

    src.onopen = () => {
      if (dai !== zhao) return;
      a.onState("open");
    };

    // 每种帧都显式 addEventListener：后端写了 event: 字段，
    // 只挂 onmessage 的话 addEventListener("message") 收不到。
    const MING = [
      "snapshot", "chunk", "message", "state", "permission", "permission_resolved",
      "question", "question_resolved", "result", "session_added", "session_removed",
      "agent_status", "device_status", "delegation_update", "error",
    ] as const;
    for (const lei of MING) {
      src.addEventListener(lei, (ev) => {
        if (dai !== zhao) return;
        // EventSource 把**传输层错误**也派发成 "error" 事件，它与后端
        // `event: error` 的正常消息帧同名。传输错误没有 data 字段，先挡掉；
        // 否则 JSON.parse(undefined) 会被误报成「收到无法解析的帧」。
        const data = (ev as MessageEvent<unknown>).data;
        if (typeof data !== "string" || data.length === 0) return;

        let zhen: DownFrame;
        try {
          zhen = JSON.parse(data) as DownFrame;
        } catch {
          // 坏帧不进入业务状态，也不弹不可行动的用户提示；主动走一次重连，
          // 让新连接的 snapshot 把状态补齐。持续坏帧由指数退避兜住。
          src?.close();
          src = null;
          chonglian(dai);
          return;
        }
        if (zhen === null || typeof zhen !== "object" || typeof zhen.type !== "string") return;

        // **不要把这个调用放进上面的 try。** reducer 抛错时若被同一层 catch
        // 接住，会再次被伪装成 JSON 解析失败，掩盖真正的页面异常。
        a.onFrame(zhen);
      });
    }

    src.onerror = (ev) => {
      if (shut || dai !== zhao) return;
      // 后端也可以发 `event: error` 的**业务错误帧**，浏览器会用同一个事件名
      // 派发 MessageEvent。它由上面的类型监听器处理，不是传输层断开——这里
      // 若再走重连路径，会把一条可恢复的业务错误升级成一次无谓的重连风暴。
      if (typeof (ev as MessageEvent<unknown> | undefined)?.data === "string") return;
      src?.close();
      src = null;
      // EventSource 不区分 401 与网络抖动，readyState 也分不出来。
      // 401 时浏览器会一直重连，所以先探一次 /health 决定是「重连」还是「凭据失效」。
      void health()
        .then(() => chonglian(dai))
        .catch(() => {
          a.onState("unauthorized", "Bridge 未运行或凭据无效");
          chonglian(dai);
        });
    };
  };

  const chonglian = (dai: number) => {
    if (shut || dai !== zhao) return;
    const wait = ZUI_DI[Math.min(zhao - 1, ZUI_DI.length - 1)];
    timer = setTimeout(() => void kai(), wait);
  };

  void kai();

  return {
    close() {
      shut = true;
      // 世代号也要推进：光看 shut 不够，close 之后仍可能有已排队的回调跑进来。
      zhao += 1;
      closeAll();
    },
  };
}
