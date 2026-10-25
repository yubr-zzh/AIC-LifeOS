import React, { useEffect, useState } from "react";
import {
  bridgeInfo,
  daKaiRiZhi,
  pickFolder,
  setDelegation,
  startBridge,
  stopBridge,
  trustFolder,
  zaiZhuoMian,
  type BridgeInfo,
} from "../api/agentClient";
import { PERMISSION_MODES, permissionModeLabel, tunnelLabel, type AgentDescriptor, type PermissionMode } from "../api/agentTypes";
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
      {/* ---- 设备 / 进程状态 ---- */}
      <section className="ags-card">
        <div className="ags-head">
          <div>
            <span className="card-kicker">本机 Bridge</span>
            <h2>启动桥接</h2>
          </div>
          <span className={`pill ${info?.running ? "done" : "idle"} sm`}>
            <span className="dot" />
            {info?.running ? "运行中" : "未运行"}
          </span>
        </div>
        <p className="ags-desc">
          LifeOS 负责规划，Bridge 在你选定的目录中执行。指令、审批和结果都留在当前设备。
        </p>
        <div className="ags-facts">
          <Fact k="端口" v={info?.port ? String(info.port) : "—"} />
          <Fact k="进程" v={info?.pid ? String(info.pid) : "—"} />
          <Fact k="CLI" v={info?.cliVersion ?? "—"} />
          <Fact k="通道" v={tunnelLabel(info?.tunnelState)} />
        </div>
        {info?.error ? <p className="ags-note">{info.error}</p> : null}
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
            <h2>连接本机 Agent</h2>
            <p className="ags-lead">选择 Agent，指定它工作的文件夹，然后开始对话。</p>
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
                value={cwd}
                placeholder="D:/Github本地/AIC-LifeOS"
                onChange={(e) => {
                  setCwd(e.target.value);
                  setWeiXin(null);
                }}
              />
              <button
                type="button"
                className="ags-browse-button btn-ghost sm"
                title="弹本机目录选择窗"
                onClick={liulan}
              >
                浏览…
              </button>
            </div>
            <small>
              用「浏览…」选择文件夹，或直接输入路径。不在信任范围内的目录需要先确认。
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
                  {permissionModeLabel(agentId, m.value)}
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

        <label className="ags-toggle" title="开启委派：命中任务关键词时，LifeOS 会给出可勾选的委派计划">
          <input type="checkbox" checked={cai} onChange={(e) => setCai(e.target.checked)} />
          <span>开启委派：命中任务时生成委派计划</span>
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
                  {permissionModeLabel(active.agentId, m.value)}
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

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div className="ags-fact">
      <span className="mono dim">{k}</span>
      <strong className="mono">{v}</strong>
    </div>
  );
}
