import React, { useCallback, useEffect, useState } from "react";
import {
  bridgeInfo,
  devices,
  pairCode,
  pickFolder,
  setDelegation,
  startBridge,
  stopBridge,
  trustFolder,
  unpair,
  type BridgeInfo,
  type DeviceRow,
} from "../api/agentClient";
import { PERMISSION_MODES, tunnelLabel, type AgentDescriptor, type PermissionMode } from "../api/agentTypes";
import type { AgentActions } from "../hooks/useAgentStream";
import type { AgentStore } from "../state/agentStore";
import { AgentActivityPanel } from "./AgentActivityPanel";

interface Props {
  store: AgentStore;
  api: AgentActions;
  onGoChat: () => void;
}

/** Bridge 不可用时必须说出**具体原因**，不能只写「不可用」。 */
function yuanYin(a: AgentDescriptor): string {
  if (a.available) return "";
  const e = a.error ?? "";
  if (/not found|no such file|FileNotFound/i.test(e)) return "没找到 claude 可执行文件，确认它已安装并在 PATH 里";
  if (/version/i.test(e)) return e;
  return e || "探测没有通过";
}

export function AgentsSection({ store, api, onGoChat }: Props) {
  const { state, dispatch, setLayout } = store;
  const [info, setInfo] = useState<BridgeInfo | null>(null);
  const [tip, setTip] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [agentId, setAgentId] = useState("claude-code");
  const [cwd, setCwd] = useState("");
  const [mode, setMode] = useState<PermissionMode>("manual");
  const [cai, setCai] = useState(true);
  const [acknowledgeNoApproval, setAcknowledgeNoApproval] = useState(false);
  // 改动二：浏览选到信任根外的目录时记下路径，出黄字提示让用户确认。
  // 手动改输入框就清掉——那条提示只对刚选的目录负责，不能追着用户的新输入瞎报警。
  const [weiXin, setWeiXin] = useState<string | null>(null);

  // ---- 配对（spec 8.1 四步里的第 1 步，剩下三步在用户本机的 Bridge 上做）----
  const [sheBei, setSheBei] = useState<DeviceRow[]>([]);
  const [ma, setMa] = useState<{ code: string; expiresAt: number } | null>(null);
  const [gao, setGao] = useState("");
  const [jieMa, setJieMa] = useState<Record<string, boolean>>({});

  /** 设备列表现问现填（`online` 来自网关路由表，不在 devices.json 里）。 */
  const shuaSheBei = useCallback(async () => {
    try {
      setSheBei((await devices()).devices);
    } catch (e) {
      setTip(e instanceof Error ? e.message : String(e));
    }
  }, []);

  // 剩余有效期倒计时。配对码 5 分钟过期（spec 8.1），给一个会走的数字比
  // 「5 分钟内有效」有用——用户能看着它决定要不要现在去本机粘贴。
  useEffect(() => {
    if (!ma) return;
    const t = setInterval(() => setGao(shengYu(ma.expiresAt)), 1000);
    setGao(shengYu(ma.expiresAt));
    return () => clearInterval(t);
  }, [ma]);

  const tiao = async (fn: () => Promise<void>) => {
    setBusy(true);
    setTip(null);
    try {
      await fn();
    } catch (e) {
      setTip(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  // ---- 改动二：原生目录选择 + 信任根确认 ----
  const liulan = () =>
    void tiao(async () => {
      const r = await pickFolder(cwd.trim() || undefined);
      if (r.path) {
        setCwd(r.path);
        setWeiXin(r.inTrustRoot ? null : r.path);
      }
    });

  const xinRen = () =>
    void tiao(async () => {
      if (!weiXin) return;
      await trustFolder(weiXin);
      setWeiXin(null);
    });

  useEffect(() => {
    void tiao(async () => {
      try {
        const i = await bridgeInfo();
        setInfo(i);
        await shuaSheBei();
        if (!i.running) {
          dispatch({ type: "CONN", conn: "offline", msg: i.error ?? "Bridge 未运行" });
        } else {
          await api.act.refreshAgents();
        }
      } catch (e) {
        setInfo(null);
        setTip(e instanceof Error ? e.message : String(e));
      }
    });
    // 只在挂载时探一次；后续由 SSE 的连接状态显示真实在线情况。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const agents = state.catalog?.agents ?? [];
  const keYong = agents.filter((a) => a.available);
  const buKeYong = agents.filter((a) => !a.available);
  const selectedAgent = agents.find((a) => a.agentId === agentId);
  const modeOptions = (selectedAgent?.moshi?.length
    ? PERMISSION_MODES.filter((m) => selectedAgent.moshi?.includes(m.value))
    : PERMISSION_MODES);
  const requiresApprovalAcknowledgement = Boolean(selectedAgent && !selectedAgent.canUseTool);
  const active = store.active;
  // 判据是 `=== false` 而不是 `!`：新前端连旧 Bridge 时这个键是 `undefined`，
  // `!undefined` 会凭空造出一次「凭据坏了」的假警报（`AgentsResponse` 的注释里
  // 有完整理由）。`undefined` = 不知道，就不响。
  const geli = state.catalog?.geli;
  // 改动三：隔离关着（默认形态）时 `credentialsReady` 没有语义——harness
  // 直用 `~/.claude`，根本没有凭据目录这回事。旧 Bridge（`geli === undefined`）
  // 维持原判：三态诚实，不知道就不响，但知道要隔离就照旧管。
  const credentialsBad = geli !== false && state.catalog?.credentialsReady === false;

  const portV = info && info.port != null ? String(info.port) : "—";
  const pidV = info && info.pid != null ? String(info.pid) : "—";
  const cliV = info?.cliVersion ?? "—";
  const tunnelV = tunnelLabel(info?.tunnelState);
  const errorV = info?.error;
  return (
    <div className="ags">
      {/* ---- 凭据目录告警（spec 11.2）----
          排在**所有**卡之前、通栏，**不挂在「发现」那张卡里**：`credentialsReady`
          与 `available` 是两件事，挂进去就等于把它并进「Agent 不可用」那一堆，
          用户会去装 claude——而问题在磁盘上。这条要单独占一行，跨整屏宽度。 */}
      {credentialsBad ? (
        <div className="ags-alarm" role="alert">
          <strong>凭据目录建不出来，你需要重新登录一次 Claude。</strong>
          <span>
            这个账号的凭据文件夹没建成，Bridge 按设计继续跑（宁可少功能也不起不来），
            代价是它落到了一个<strong>空的</strong>凭据库。请检查磁盘空间，以及{" "}
            <code className="mono">~/.lifeos-bridge/users/</code> 目录是否可写。
          </span>
        </div>
      ) : null}
      <section className="ags-card">
        <div className="ags-head">
          <div>
            <span className="card-kicker">本机 Bridge</span>
            <h2>Agent 在你的电脑上执行</h2>
          </div>
          <span className={`pill ${info?.running ? "done" : "idle"} sm`}>
            <span className="dot" />
            {info?.running ? "运行中" : "未运行"}
          </span>
        </div>
        <p className="ags-desc">
          LifeOS 负责规划，Bridge 负责在你选定的目录里执行。指令、审批和结果都留在本机，
          浏览器拿不到 Bridge 的任何凭据。
        </p>
        {geli !== undefined ? (
          <p className="ags-note">
            运行形态：
            {geli
              ? "凭据隔离（每个 LifeOS 用户独立 CLAUDE_CONFIG_DIR，不加载本机配置）"
              : "直用本机配置（与你手动开终端一致，读得到本地 skills、settings.json、CLAUDE.md）"}
          </p>
        ) : null}
        <div className="ags-facts">
          <Fact k="端口" v={portV} />
          <Fact k="进程" v={pidV} />
          <Fact k="CLI" v={cliV} />
          <Fact k="通道" v={tunnelV} />
        </div>
        {errorV ? <p className="ags-note">{errorV}</p> : null}
        <div className="ags-btns">
          {info?.running ? (
            <button
              className="btn-ghost"
              disabled={busy}
              onClick={() =>
                void tiao(async () => {
                  await stopBridge();
                  const i = await bridgeInfo();
                  setInfo(i);
                  dispatch({ type: "CONN", conn: "offline", msg: "Bridge 已停止" });
                })
              }
            >
              停止 Bridge
            </button>
          ) : (
            <button
              className="btn-allow"
              disabled={busy}
              onClick={() =>
                void tiao(async () => {
                  const r = await startBridge();
                  if (!r.ok) throw new Error(r.error ?? "启动失败");
                  setInfo(await bridgeInfo());
                  await api.act.refreshAgents();
                })
              }
            >
              启动 Bridge
            </button>
          )}
        </div>
      </section>

      {/* 配对卡在 spec 变更后从 UI 拿掉：保留代码，下面用 {false && ...} 一键恢复。
          设备列表仍在本节里出现（CLI 列表是设备/进程信息，与配对流程不重叠）。 */}
      {false && (<>
      <section className="ags-card">
        <div className="ags-head">
          <div>
            <span className="card-kicker">配对</span>
            <h2>把这一台设备加进来</h2>          </div>
        </div>
        <p className="ags-desc">
          配对码在这台机器上生成，你把它粘到用户自己那台机器的浏览器里。
          凭据只在换的那一次出现，之后走隧道，不经过浏览器。
        </p>
        <div className="ags-btns">
          <button
            className="btn-allow"
            disabled={busy}
            onClick={() => void tiao(async () => setMa(await pairCode()))}
          >
            添加设备
          </button>
          <button className="btn-ghost" disabled={busy} onClick={() => void tiao(shuaSheBei)}>
            刷新
          </button>
        </div>
        {ma ? (
          <div className="ags-note" aria-live="polite">
            <strong className="mono" style={{ fontSize: 18, letterSpacing: ".1em" }}>{ma?.code}</strong>
            <br />
            <PeiDuiRuKou info={info} />
            {gao ? <> 剩余 {gao}。</> : null}
          </div>
        ) : null}
        <SheBeiList
          sheBei={sheBei}
          jieMa={jieMa}
          onUnpair={(id) =>
            void tiao(async () => {
              // **必须看 `ok`**：后端对不存在的 / 已解绑的 deviceId 回
              // `{ok:false}` 而 HTTP 仍是 200，不看的话失败会被显示成成功。
              const r = await unpair(id);
              if (!r.ok) throw new Error("解绑没有生效：这台设备不存在，或已经被解绑过了。");
              setJieMa((m) => ({ ...m, [id]: true }));
              await shuaSheBei();
            })
          }
        />
      </section>
      </>)}

      {/* ---- Agent 发现 ---- */}
      <section className="ags-card">
        <div className="ags-head">
          <div>
            <span className="card-kicker">发现</span>
            <h2>本机可用的 Agent</h2>
          </div>
          <button className="btn-ghost sm" disabled={busy} onClick={() => void api.act.refreshAgents()}>
            重新探测
          </button>
        </div>
        {agents.length === 0 ? (
          <p className="ags-note">
            {state.conn === "open" ? "正在探测…" : "要先启动 Bridge 才能探测本机 Agent。"}
          </p>
        ) : null}
        {keYong.map((a) => (
          <div className="ags-agent on" key={a.agentId}>
            <div className="ags-agent-main">
              <strong>{a.label}</strong>
              <span className="mono dim">{a.version ?? "版本未知"}</span>
            </div>
            <span className="pill done sm"><span className="dot" />可用</span>
          </div>
        ))}
        {buKeYong.map((a) => (
          <div className="ags-agent off" key={a.agentId}>
            <div className="ags-agent-main">
              <strong>{a.label}</strong>
              <span className="ags-why">{yuanYin(a)}</span>
            </div>
            <span className="pill failed sm"><span className="dot" />不可用</span>
          </div>
        ))}
      </section>

      {/* ---- 连接表单 ---- */}
      <section className="ags-card">
        <div className="ags-head">
          <div>
            <span className="card-kicker">连接</span>
            <h2>选一个 Agent 并给它一个目录</h2>
          </div>
        </div>
        <div className="ags-form">
          <label className="ags-field">
            <span>Agent</span>
            <select value={agentId} onChange={(e) => {
              const nextId = e.target.value;
              const next = agents.find((a) => a.agentId === nextId);
              setAgentId(nextId);
              setAcknowledgeNoApproval(false);
              if (next?.moshi?.length && !next.moshi.includes(mode)) setMode(next.moshi[0]);
            }}>
              {agents.length === 0 ? <option value="claude-code">Claude Code</option> : null}
              {keYong.map((a) => (
                <option key={a.agentId} value={a.agentId}>
                  {a.label} {a.version ?? ""}
                </option>
              ))}
            </select>
          </label>

          <label className="ags-field">
            <span>工作目录</span>
            <div className="ags-cwd-row">
              <input
                list="ags-dirs"
                value={cwd}
                placeholder="D:/Github本地/AIC-LifeOS"
                onChange={(e) => {
                  setCwd(e.target.value);
                  setWeiXin(null);
                }}
              />
              <button
                type="button"
                className="btn-ghost sm"
                disabled={busy}
                title="弹本机目录选择窗"
                onClick={liulan}
              >
                浏览…
              </button>
            </div>
            <datalist id="ags-dirs">
              {(state.catalog?.suggestedDirs ?? []).map((d) => (
                <option key={d} value={d} />
              ))}
            </datalist>
            <small>
              点「浏览…」弹本机目录选择窗，也可以手动输入。目录须落在信任根内；信任根外的先出黄字，确认后放行。
            </small>
            {weiXin ? (
              <p className="ags-note warn">
                该目录在信任根外，现在连接会被 Bridge 拒绝。{" "}
                <button type="button" className="btn-ghost sm" disabled={busy} onClick={xinRen}>
                  信任此目录
                </button>
              </p>
            ) : null}
          </label>

          <label className="ags-field">
            <span>权限模式</span>
            <select value={mode} onChange={(e) => setMode(e.target.value as PermissionMode)}>
              {modeOptions.map((m) => (
                <option key={m.value} value={m.value} title={m.hint}>
                  {m.label}
                </option>
              ))}
            </select>
            <small>{PERMISSION_MODES.find((m) => m.value === mode)?.hint}</small>
          </label>
        </div>

        {requiresApprovalAcknowledgement ? (
          <label className="ags-toggle">
            <input
              type="checkbox"
              checked={acknowledgeNoApproval}
              onChange={(e) => setAcknowledgeNoApproval(e.target.checked)}
            />
            <span>{selectedAgent?.label} 没有 LifeOS 可接管的审批回路；我知道它可能直接执行工具操作</span>
          </label>
        ) : null}

        <label className="ags-toggle">
          <input type="checkbox" checked={cai} onChange={(e) => setCai(e.target.checked)} />
          <span>开启委派：命中任务关键词时，LifeOS 会给出可勾选的委派计划</span>
        </label>

        {tip ? <p className="ags-note err">{tip}</p> : null}

        <div className="ags-btns">
          <button
            className="btn-allow"
            disabled={busy || !info?.running || !cwd.trim() || keYong.length === 0 || (requiresApprovalAcknowledgement && !acknowledgeNoApproval)}
            onClick={() =>
              void tiao(async () => {
                await setDelegation(cai);
                const sid = await api.act.connect({
                  agentId,
                  cwd: cwd.trim(),
                  permissionMode: mode,
                  ...(acknowledgeNoApproval ? { acknowledgeNoApproval: true } : {}),
                });
                setLayout("split");
                if (sid !== "preview") onGoChat();
              })
            }
          >
            连接并打开对话
          </button>
          {keYong.length === 0 && info?.running ? (
            <span className="ags-note err">没有可用的 Agent，先把上面标红的那条解决掉。</span>
          ) : null}
        </div>
      </section>

      {/* ---- 会话卡 ---- */}
      {active ? (
        <section className="ags-card">
          <div className="ags-head">
            <div>
              <span className="card-kicker">当前会话</span>
              <h2 className="mono">{active.sessionId}</h2>
            </div>
          </div>
          <div className="ags-facts">
            <Fact k="状态" v={active.state} />
            <Fact k="指令" v={`${active.batchDone}/${active.batchTotal}`} />
            <Fact k="生效模式" v={active.effectiveMode} />
            <Fact k="目录" v={active.cwd} />
          </div>
          <div className="ags-btns">
            <select
              value={active.permissionMode}
              onChange={(e) => void api.act.setMode(active.sessionId, e.target.value as PermissionMode).catch(() => undefined)}
            >
              {(agents.find((a) => a.agentId === active.agentId)?.moshi?.length
                ? PERMISSION_MODES.filter((m) => agents.find((a) => a.agentId === active.agentId)?.moshi?.includes(m.value))
                : PERMISSION_MODES).map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
            <button className="btn-ghost" onClick={() => void api.act.interrupt(active.sessionId)}>
              中断
            </button>
            <button className="btn-ghost" onClick={() => void api.act.close(active.sessionId)}>
              关闭会话
            </button>
          </div>
        </section>
      ) : null}
      <AgentActivityPanel />
    </div>
  );
}

/** 配对码剩余时间。过期后归零——码是一次性的，秒表停住比继续走诚实。 */
function shengYu(expiresAt: number): string {
  const miao = Math.max(0, Math.floor((expiresAt - Date.now()) / 1000));
  return `${Math.floor(miao / 60)}:${String(miao % 60).padStart(2, "0")}`;
}

/**
 * 配对页入口。**分形态**给，因为 `/pair` 是 **Bridge 自己**（8766–8770 上那个
 * HTTP 服务，`bridge/http.py`）的路由，而这里显示给用户的是**那台要接进来的
 * 设备**要打开的地址。
 *
 * 判据是 **`info.port` 在不在**，不是 `tunnelState`：`xinxi()` 的
 * `tunnelState` 默认值 `"local"` 出现在**读不到 runtime.json** 时，而那一路
 * 在给 `port` 赋值**之前**就 return 了（`bridge_admin.xinxi`）。所以
 * `tunnelState === "local"` 与「有端口」永远互斥，拿它当判据等于永远走不到
 * 给地址那一支。
 *
 * - `port != null`：云端这台机器上注册过 Bridge ⇒ 本机直连形态，用户人就坐在这台
 *   机器上，回环地址是对的。
 * - `port == null`：这台机器上没有 Bridge，要接进来的那台 Bridge 在别处
 *   （隧道形态）⇒ **不给一个打不开的回环地址**，也不猜端口——那个端口是 Bridge
 *   自己启动时在自己那一侧显示的，云端这一侧根本不知道。
 *
 * 端口一律取 `info.port`，**没有兜底常量**（spec 5.1：禁止硬编码 8766，
 * 端口会漂到 8767–8770）。
 */
function PeiDuiRuKou({ info }: { info: BridgeInfo | null }) {
  if (info?.port) {
    return (
      <>
        在这台机器的浏览器里打开{" "}
        <code className="mono"> http://127.0.0.1:{info.port}/pair </code> 粘贴。
      </>
    );
  }
  return (
    <>
      目标设备上跑着 Bridge 的那台机器里，用它浏览器打开{" "}
      <code className="mono">/pair</code> 页面，粘贴这个码——那是 Bridge
      自己启动时显示的地址，云端这一侧看不到它，所以这里不写死一个端口。
    </>
  );
}

/** 设备表。已解绑的不删——`devices()` 会照实把它列成 revoked，
 *  删掉的话用户会以为那台设备从没存在过。 */
function SheBeiList({
  sheBei,
  jieMa,
  onUnpair,
}: {
  sheBei: DeviceRow[];
  jieMa: Record<string, boolean>;
  onUnpair: (a: string) => void;
}) {
  // **解绑是不可逆的凭据吊销**（`SheBiao.jie` 把 revoked 落盘，`ren` 之后对
  // revoked 直接停止重连），而且一行一个按钮、彼此紧挨着。单击即生效的话，
  // 点错相邻行就吊销了那台设备的凭据，只能重新配对。所以走仓库里已有的
  // 两步确认（`AgentApprovalCard` 的危险命令同一套做法）。
  const [queRen, setQueRen] = useState<string | null>(null);
  if (sheBei.length === 0) return <p className="ags-note">还没有配对过任何设备。</p>;
  return (
    <div className="ags-btns" style={{ flexDirection: "column", alignItems: "stretch" }}>
      {sheBei.map((d) => {
        const jie = d.revoked || jieMa[d.deviceId];
        const wen = d.label || d.deviceId;
        return (
          <div className="ags-agent" key={d.deviceId}>
            <div className="ags-agent-main">
              <strong>{wen}</strong>
              <span className="mono dim">
                {d.deviceId} · {d.online ? "在线" : "离线"}
                {d.lastSeenAt ? ` · 最近 ${new Date(d.lastSeenAt).toLocaleString()}` : ""}
              </span>
              {jie ? <span className="ags-why">设备已被解绑，停止重连</span> : null}
              {queRen === d.deviceId ? (
                <span className="ags-why">
                  解绑「{wen}」会吊销它的凭据、踢掉隧道，之后只能重新配对。
                </span>
              ) : null}
            </div>
            {jie ? null : queRen === d.deviceId ? (
              <>
                <button
                  className="btn-allow sm"
                  onClick={() => {
                    setQueRen(null);
                    onUnpair(d.deviceId);
                  }}
                >
                  确定解绑
                </button>
                <button className="btn-ghost sm" onClick={() => setQueRen(null)}>
                  取消解绑
                </button>
              </>
            ) : (
              <button className="btn-ghost sm" onClick={() => setQueRen(d.deviceId)}>
                解绑
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div className="ags-fact">
      <span className="mono dim">{k}</span>
      <strong className="mono">{v}</strong>
    </div>
  );
}
