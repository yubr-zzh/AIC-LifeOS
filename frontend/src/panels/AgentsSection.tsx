import React, { useEffect, useState } from "react";
import {
  bridgeInfo,
  pickFolder,
  setDelegation,
  startBridge,
  stopBridge,
  trustFolder,
  type BridgeInfo,
} from "../api/agentClient";
import { PERMISSION_MODES, permissionModeLabel, tunnelLabel, type AgentDescriptor, type PermissionMode } from "../api/agentTypes";
import type { AgentActions } from "../hooks/useAgentStream";
import type { AgentStore } from "../state/agentStore";
import { AgentActivityPanel } from "./AgentActivityPanel";
import { IconArrowRight, IconRefresh, IconCheck } from "../components/Icons";

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

/** 每个 Agent 的展示元信息。后端只返回 agentId/label/version，不返回描述，
 *  所以这里维护一份本地映射；未收录的走 fallback（不写死描述）。 */
const AGENT_META: Record<string, { desc: string; mono: string }> = {
  "claude-code": { desc: "代码生成、重构与开发协作", mono: "C" },
  codex: { desc: "代码分析与编程任务", mono: "X" },
  "codex-cli": { desc: "代码分析与编程任务", mono: "X" },
  pi: { desc: "轻量级本机编程智能体", mono: "π" },
  "pi-coding-agent": { desc: "轻量级本机编程智能体", mono: "π" },
  opencode: { desc: "终端编程与模型协作", mono: "O" },
  hermes: { desc: "任务型智能体", mono: "H" },
  "hermes-agent": { desc: "任务型智能体", mono: "H" },
  kimi: { desc: "长上下文代码助手", mono: "K" },
  "kimi-code": { desc: "长上下文代码助手", mono: "K" },
};

function agentMeta(a: AgentDescriptor) {
  return AGENT_META[a.agentId] ?? { desc: "本机可用的编程智能体", mono: (a.label || "?").slice(0, 1).toUpperCase() };
}

type Drawer =
  | { kind: "agent"; agent: AgentDescriptor }
  | { kind: "bridge" }
  | null;

export function AgentsSection({ store, api, onGoChat }: Props) {
  const { state, dispatch, setLayout } = store;
  const [info, setInfo] = useState<BridgeInfo | null>(null);
  const [tip, setTip] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [drawer, setDrawer] = useState<Drawer>(null);

  const [agentId, setAgentId] = useState("claude-code");
  const [cwd, setCwd] = useState("");
  const [mode, setMode] = useState<PermissionMode>("manual");
  const [cai, setCai] = useState(true);
  const [acknowledgeNoApproval, setAcknowledgeNoApproval] = useState(false);
  // 浏览选到信任根外的目录时记下路径，出黄字提示让用户确认。
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

  const portV = info && info.port != null ? String(info.port) : "—";
  const pidV = info && info.pid != null ? String(info.pid) : "—";
  const cliV = info?.cliVersion ?? "—";
  const tunnelV = tunnelLabel(info?.tunnelState);
  const errorV = info?.error;

  // 启动前准备：三项都在「连接」这件事上同步反映当前表单状态。
  const preflight = [
    { label: `选择 Agent${selectedAgent ? ` · ${selectedAgent.label}` : ""}`, done: Boolean(selectedAgent) },
    { label: "确认工作目录", done: Boolean(cwd.trim()) },
    {
      label: "确认执行权限",
      done: !requiresApprovalAcknowledgement || acknowledgeNoApproval,
    },
  ];

  const connect = () =>
    void tiao(async () => {
      await setDelegation(cai);
      const sid = await api.act.connect({
        agentId,
        cwd: cwd.trim(),
        permissionMode: mode,
        ...(acknowledgeNoApproval ? { acknowledgeNoApproval: true } : {}),
      });
      setDrawer(null);
      setLayout("split");
      if (sid !== "preview") onGoChat();
    });

  const canConnect =
    !busy &&
    Boolean(info?.running) &&
    Boolean(cwd.trim()) &&
    keYong.length > 0 &&
    (!requiresApprovalAcknowledgement || acknowledgeNoApproval);

  return (
    <div className="ags ags2">
      {/* ---- 凭据目录告警（spec 11.2）----
          排在**所有**卡之前、通栏，**不挂在「本机 Agent」那张卡里**：`credentialsReady`
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

      {/* ---- 标题行 ---- */}
      <header className="ags2-title">
        <div className="ags2-title-main">
          <div className="ags2-eyebrow">LOCAL AGENTS · 本机智能体</div>
          <h1>Agent 管理</h1>
          <p>发现并管理本机 Agent。Bridge 负责连接，关键操作由你确认。</p>
        </div>
        <div className="ags2-title-actions">
          <button
            className="ags2-btn"
            disabled={busy}
            onClick={() => void tiao(() => api.act.refreshAgents())}
          >
            <IconRefresh size={13} /> 重新检测
          </button>
          <button className="ags2-btn primary" onClick={() => setDrawer({ kind: "bridge" })}>
            查看 Bridge 详情
          </button>
        </div>
      </header>

      {/* ---- 统计 ---- */}
      <div className="ags2-stats">
        <Stat label="已检测 Agent" value={agents.length} hint="本机探测结果" />
        <Stat label="可用 Agent" value={keYong.length} hint="本机已发现" tone="ok" />
        <Stat label="需要关注" value={buKeYong.length} hint="安装或配置问题" tone={buKeYong.length ? "warn" : undefined} />
      </div>

      {/* ---- 主栅格：Agent 列表 + Bridge / 启动前准备 ---- */}
      <div className="ags2-grid">
        <section className="ags2-card ags2-list-card">
          <header className="ags2-card-head">
            <div>
              <h2>本机 Agent</h2>
              <p>按检测结果显示，不把「可用」误认为「正在运行」。</p>
            </div>
            <span className="ags2-badge gray">{agents.length} 个结果</span>
          </header>
          <div className="ags2-agent-list">
            {agents.length === 0 ? (
              <p className="ags2-empty">
                {state.conn === "open" ? "正在探测本机 Agent…" : "要先启动 Bridge 才能探测本机 Agent。"}
              </p>
            ) : (
              agents.map((a) => (
                <div className={`ags2-agent-row ${a.available ? "is-on" : "is-off"}`} key={a.agentId}>
                  <div className="ags2-agent-icon" aria-hidden="true">{agentMeta(a).mono}</div>
                  <div className="ags2-agent-copy">
                    <div className="ags2-agent-name">
                      <b>{a.label}</b>
                      <span className="ags2-agent-version">{a.version ?? "未检测到"}</span>
                    </div>
                    <p>{a.available ? agentMeta(a).desc : yuanYin(a)}</p>
                  </div>
                  <span className={`ags2-badge ${a.available ? "" : "warn"}`}>
                    {a.available ? "可用" : "需检查"}
                  </span>
                  <button className="ags2-btn sm" onClick={() => setDrawer({ kind: "agent", agent: a })}>
                    详情 <IconArrowRight size={12} />
                  </button>
                </div>
              ))
            )}
          </div>
        </section>

        <aside className="ags2-side">
          <section className="ags2-card">
            <header className="ags2-card-head">
              <h2>Bridge 服务</h2>
              <span className={`ags2-badge ${info?.running ? "" : "gray"}`}>
                {info?.running ? "运行中" : "未运行"}
              </span>
            </header>
            <p className="ags2-muted">连接本机 Agent 与 LifeOS 的服务。</p>
            <div className="ags2-sep" />
            <div className="ags2-kv">
              <span>执行环境</span>
              <b>{geli === undefined ? "本机" : geli ? "隔离凭据" : "本机配置"}</b>
            </div>
            <div className="ags2-kv">
              <span>权限策略</span>
              <b>{permissionModeLabel(agentId, mode)}</b>
            </div>
            <div className="ags2-sep" />
            <div className="ags2-facts">
              <Fact k="端口" v={portV} />
              <Fact k="进程" v={pidV} />
              <Fact k="CLI" v={cliV} />
              <Fact k="通道" v={tunnelV} />
            </div>
            {errorV ? <p className="ags2-note err">{errorV}</p> : null}
            <div className="ags2-btn-row">
              {info?.running ? (
                <button
                  className="ags2-btn"
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
                  className="ags2-btn primary"
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
              <button className="ags2-btn" onClick={() => setDrawer({ kind: "bridge" })}>
                查看服务信息
              </button>
            </div>
          </section>

          <section className="ags2-card">
            <header className="ags2-card-head">
              <h2>启动前准备</h2>
            </header>
            <ul className="ags2-checklist">
              {preflight.map((item) => (
                <li key={item.label} className={item.done ? "is-done" : ""}>
                  <span className="ags2-check" aria-hidden="true">
                    {item.done ? <IconCheck size={11} /> : null}
                  </span>
                  <span>{item.label}</span>
                </li>
              ))}
            </ul>
            <p className="ags2-muted small">
              启动与审批继续复用既有业务接口。本预览不进行真实操作。
            </p>
          </section>
        </aside>
      </div>

      {/* ---- 连接表单 ---- */}
      <section className="ags2-card ags2-connect">
        <header className="ags2-card-head">
          <div>
            <h2>连接 Agent</h2>
            <p>选一个 Agent 并给它一个目录，然后进入对话。</p>
          </div>
        </header>

        <div className="ags2-form">
          <label className="ags2-field">
            <span>Agent</span>
            <select
              value={agentId}
              onChange={(e) => {
                const nextId = e.target.value;
                const next = agents.find((a) => a.agentId === nextId);
                setAgentId(nextId);
                setAcknowledgeNoApproval(false);
                if (next?.moshi?.length && !next.moshi.includes(mode)) setMode(next.moshi[0]);
              }}
            >
              {agents.length === 0 ? <option value="claude-code">Claude Code</option> : null}
              {keYong.map((a) => (
                <option key={a.agentId} value={a.agentId}>
                  {a.label} {a.version ?? ""}
                </option>
              ))}
            </select>
          </label>

          <label className="ags2-field">
            <span>工作目录</span>
            <div className="ags2-cwd-row">
              <input
                list="ags2-dirs"
                value={cwd}
                placeholder="D:/Github本地/AIC-LifeOS"
                onChange={(e) => {
                  setCwd(e.target.value);
                  setWeiXin(null);
                }}
              />
              <button
                type="button"
                className="ags2-btn ags-browse-button"
                disabled={busy}
                title="弹本机目录选择窗"
                onClick={liulan}
              >
                浏览…
              </button>
            </div>
            <datalist id="ags2-dirs">
              {(state.catalog?.suggestedDirs ?? []).map((d) => (
                <option key={d} value={d} />
              ))}
            </datalist>
            <small>目录须落在信任根内；信任根外的先出黄字，确认后放行。</small>
            {weiXin ? (
              <p className="ags2-note warn">
                该目录在信任根外，现在连接会被 Bridge 拒绝。{" "}
                <button type="button" className="ags2-btn sm" disabled={busy} onClick={xinRen}>
                  信任此目录
                </button>
              </p>
            ) : null}
          </label>

          <label className="ags2-field">
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
          <label className="ags2-toggle">
            <input
              type="checkbox"
              checked={acknowledgeNoApproval}
              onChange={(e) => setAcknowledgeNoApproval(e.target.checked)}
            />
            <span>{selectedAgent?.label} 没有 LifeOS 可接管的审批回路；我知道它可能直接执行工具操作</span>
          </label>
        ) : null}

        <label className="ags2-toggle">
          <input type="checkbox" checked={cai} onChange={(e) => setCai(e.target.checked)} />
          <span>开启委派：命中任务关键词时，LifeOS 会给出可勾选的委派计划</span>
        </label>

        {tip ? <p className="ags2-note err">{tip}</p> : null}

        <div className="ags2-btn-row">
          <button className="ags2-btn primary" disabled={!canConnect} onClick={connect}>
            连接并打开对话
          </button>
          {keYong.length === 0 && info?.running ? (
            <span className="ags2-note err">没有可用的 Agent，先把列表里标「需检查」的那条解决掉。</span>
          ) : null}
        </div>
      </section>

      {/* ---- 会话卡 ---- */}
      {active ? (
        <section className="ags2-card">
          <header className="ags2-card-head">
            <div>
              <h2>当前会话</h2>
              <p className="mono">{active.sessionId}</p>
            </div>
            <span className="ags2-badge">{active.state}</span>
          </header>
          <div className="ags2-facts">
            <Fact k="指令" v={`${active.batchDone}/${active.batchTotal}`} />
            <Fact k="生效模式" v={permissionModeLabel(active.agentId, active.permissionMode)} />
            <Fact k="目录" v={active.cwd} />
          </div>
          <div className="ags2-btn-row">
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
            <button className="ags2-btn" onClick={() => void api.act.interrupt(active.sessionId)}>
              中断
            </button>
            <button className="ags2-btn" onClick={() => void api.act.close(active.sessionId)}>
              关闭会话
            </button>
          </div>
        </section>
      ) : null}

      <AgentActivityPanel />

      {/* ---- 详情抽屉 ---- */}
      {drawer ? (
        <>
          <div className="ags2-shade" onClick={() => setDrawer(null)} />
          <aside className="ags2-drawer" role="dialog" aria-label={drawer.kind === "bridge" ? "Bridge 详情" : "Agent 详情"}>
            <header className="ags2-drawer-head">
              <span className="ags2-eyebrow">
                {drawer.kind === "bridge" ? "BRIDGE · LOCAL SERVICE" : "AGENT DETAIL"}
              </span>
              <button className="ags2-btn sm" onClick={() => setDrawer(null)} aria-label="关闭">
                ×
              </button>
            </header>

            {drawer.kind === "bridge" ? (
              <>
                <h1>Bridge 服务详情</h1>
                <p className="ags2-muted">连接本机 Agent 与 LifeOS 的本地服务。</p>
                <div className="ags2-sep" />
                <Field label="运行状态" value={info?.running ? "运行中" : "未运行"} />
                <Field label="端口" value={portV} />
                <Field label="进程" value={pidV} />
                <Field label="CLI 版本" value={cliV} />
                <Field label="通道" value={tunnelV} />
                <Field label="执行环境" value={geli === undefined ? "本机" : geli ? "隔离凭据" : "本机配置"} />
                <Field label="权限策略" value={permissionModeLabel(agentId, mode)} />
                {errorV ? <p className="ags2-note err">{errorV}</p> : null}
                <div className="ags2-sep" />
                <p className="ags2-muted small">
                  浏览器拿不到 Bridge 的任何凭据；指令、审批和结果都留在本机。
                </p>
              </>
            ) : (
              <>
                <h1>{drawer.agent.label}</h1>
                <p className="ags2-muted">{agentMeta(drawer.agent).desc}</p>
                <div className="ags2-sep" />
                <Field label="检测状态" value={drawer.agent.available ? "可用" : "需要检查"} />
                <Field label="版本" value={drawer.agent.version ?? "未检测到"} />
                <Field label="SDK" value={drawer.agent.sdkVersion ?? "未检测到"} />
                <Field
                  label="权限模式"
                  value={(drawer.agent.moshi ?? []).map((m) => permissionModeLabel(drawer.agent.agentId, m)).join(" / ") || "跟随 LifeOS 默认"}
                />
                <Field label="工具审批" value={drawer.agent.canUseTool ? "可接管" : "不可接管"} />
                <Field label="提问能力" value={drawer.agent.canAskQuestion ? "支持" : "不支持"} />
                {!drawer.agent.available ? (
                  <p className="ags2-note warn">{yuanYin(drawer.agent)}</p>
                ) : null}
                <div className="ags2-sep" />
                <button
                  className="ags2-btn primary"
                  disabled={!drawer.agent.available}
                  onClick={() => {
                    setAgentId(drawer.agent.agentId);
                    setDrawer(null);
                  }}
                >
                  用它连接 <IconArrowRight size={12} />
                </button>
              </>
            )}
          </aside>
        </>
      ) : null}
    </div>
  );
}

function Stat({ label, value, hint, tone }: { label: string; value: number; hint: string; tone?: "ok" | "warn" }) {
  return (
    <div className="ags2-stat">
      <span className="ags2-stat-label">{label}</span>
      <strong className={`ags2-stat-value ${tone ?? ""}`}>{value}</strong>
      <span className="ags2-muted small">{hint}</span>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="ags2-field-row">
      <span className="ags2-muted small">{label}</span>
      <b>{value}</b>
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
