import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import type { AgentRoutingPolicy, Store } from "../state/store";
import { ModelSwitcher } from "./ModelSwitcher";
import { configureVault, getVaultStatus, importVaultFile, listVaultFiles } from "../api/client";
import type { StructuredEntryKind, VaultFile, VaultStatus } from "../api/types";
import {
  IconBell,
  IconBook,
  IconCpu,
  IconDatabase,
  IconPalette,
  IconShield,
  IconSpark,
} from "../components/Icons";

interface Props {
  store: Store;
  dark: boolean;
  onDarkChange: (value: boolean) => void;
  onOpenDiagnostics: () => void;
}

type SettingsSection = "general" | "agent" | "memory" | "vault" | "notifications" | "data";

const settingsNav: { id: SettingsSection; label: string; icon: ReactNode }[] = [
  { id: "general", label: "一般", icon: <IconPalette size={16} /> },
  { id: "agent", label: "AI 模型与偏好", icon: <IconCpu size={16} /> },
  { id: "memory", label: "记忆", icon: <IconDatabase size={16} /> },
  { id: "vault", label: "Obsidian Vault", icon: <IconBook size={16} /> },
  { id: "notifications", label: "通知", icon: <IconBell size={16} /> },
  { id: "data", label: "数据与隐私", icon: <IconShield size={16} /> },
];

function storedBoolean(key: string, fallback: boolean): boolean {
  try {
    const value = window.localStorage.getItem(key);
    return value === null ? fallback : value === "true";
  } catch {
    return fallback;
  }
}

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
}) {
  return (
    <label className={`settings-switch ${checked ? "on" : ""}`}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        aria-label={label}
      />
      <span />
    </label>
  );
}

export function SettingsPage({ store, dark, onDarkChange, onOpenDiagnostics }: Props) {
  const [section, setSection] = useState<SettingsSection>(() => {
    const requested = new URLSearchParams(window.location.search).get("settings");
    return settingsNav.some((item) => item.id === requested) ? requested as SettingsSection : "general";
  });
  const [defaultRoutingPolicy, setDefaultRoutingPolicy] = useState<AgentRoutingPolicy>(() => {
    const saved = window.localStorage.getItem("lifeos-agent-routing-policy");
    return saved === "force_self_plan" || saved === "force_agent" ? saved : "auto";
  });
  const [autoSelfPlan, setAutoSelfPlan] = useState(() => storedBoolean("lifeos-auto-self-plan", true));
  const [confirmAgent, setConfirmAgent] = useState(() => storedBoolean("lifeos-confirm-agent", true));
  const [dailySummary, setDailySummary] = useState(() => storedBoolean("lifeos-daily-summary", false));
  const [permissionAlerts, setPermissionAlerts] = useState(() => storedBoolean("lifeos-permission-alerts", true));
  const [vaultStatus, setVaultStatus] = useState<VaultStatus | null>(null);
  const [vaultPath, setVaultPath] = useState("");
  const [vaultFolder, setVaultFolder] = useState("LifeOS");
  const [vaultFiles, setVaultFiles] = useState<VaultFile[]>([]);
  const [vaultBusy, setVaultBusy] = useState(false);
  const [vaultMessage, setVaultMessage] = useState("");
  const [vaultImportKind, setVaultImportKind] = useState<StructuredEntryKind>("insight");

  useEffect(() => {
    try {
      window.localStorage.setItem("lifeos-agent-routing-policy", defaultRoutingPolicy);
      window.localStorage.setItem("lifeos-auto-self-plan", String(autoSelfPlan));
      window.localStorage.setItem("lifeos-confirm-agent", String(confirmAgent));
      window.localStorage.setItem("lifeos-daily-summary", String(dailySummary));
      window.localStorage.setItem("lifeos-permission-alerts", String(permissionAlerts));
    } catch {
      // Preferences are optional and remain in memory if storage is blocked.
    }
  }, [autoSelfPlan, confirmAgent, dailySummary, defaultRoutingPolicy, permissionAlerts]);

  const loadVault = async () => {
    setVaultBusy(true);
    setVaultMessage("");
    try {
      const status = await getVaultStatus();
      setVaultStatus(status);
      setVaultPath(status.path);
      setVaultFolder(status.folder || "LifeOS");
      if (status.configured && status.exists) {
        const result = await listVaultFiles("", 50);
        setVaultFiles(result.files);
      } else {
        setVaultFiles([]);
      }
    } catch (reason) {
      setVaultMessage(reason instanceof Error ? reason.message : "无法读取 Vault 状态");
    } finally {
      setVaultBusy(false);
    }
  };

  const saveVault = async () => {
    setVaultBusy(true);
    setVaultMessage("");
    try {
      const status = await configureVault(vaultPath, vaultFolder);
      setVaultStatus(status);
      const result = await listVaultFiles("", 50);
      setVaultFiles(result.files);
      setVaultMessage(`已连接 Vault：${status.path}`);
    } catch (reason) {
      setVaultMessage(reason instanceof Error ? reason.message : "Vault 配置失败");
    } finally {
      setVaultBusy(false);
    }
  };

  const importFile = async (file: VaultFile) => {
    setVaultBusy(true);
    setVaultMessage("");
    try {
      const result = await importVaultFile(file.path, vaultImportKind);
      setVaultMessage(`已导入「${result.entry.title}」到 ${result.entry.kind}`);
    } catch (reason) {
      setVaultMessage(reason instanceof Error ? reason.message : "Markdown 导入失败");
    } finally {
      setVaultBusy(false);
    }
  };

  useEffect(() => {
    if (section === "vault") void loadVault();
  }, [section]);

  const memoryCount =
    store.state.memory.user.length +
    store.state.memory.project.length +
    store.state.memory.feedback.length +
    (store.state.memory.reference?.length ?? 0);

  return (
    <div className="settings-page">
      <aside className="settings-page-nav content-card" aria-label="设置分类">
        <div className="settings-page-title">
          <span className="card-kicker">工作区设置</span>
          <h2>让 LifeOS 按你的方式工作</h2>
        </div>
        {settingsNav.map((item) => (
          <button
            type="button"
            key={item.id}
            className={section === item.id ? "active" : ""}
            onClick={() => setSection(item.id)}
            aria-current={section === item.id ? "page" : undefined}
          >
            {item.icon}
            <span>{item.label}</span>
          </button>
        ))}
        <div className="settings-page-status">
          <span className="status-orb" />
          <div>
            <strong>{store.state.ui.dataMode === "backend" ? "实时后端" : "本地预览"}</strong>
            <small>127.0.0.1:8765</small>
          </div>
        </div>
      </aside>

      <section className="settings-page-content content-card">
        {section === "general" ? (
          <>
            <div className="settings-section-heading">
              <span className="card-kicker">一般</span>
              <h2>显示与默认行为</h2>
              <p>这些偏好只保存在当前浏览器，不影响已保存的对话和记忆。</p>
            </div>
            <div className="settings-row-card">
              <div>
                <strong>界面主题</strong>
                <small>浅色薄荷适合白天，夜间模式适合长时间对话。</small>
              </div>
              <div className="settings-segmented">
                <button type="button" className={!dark ? "active" : ""} onClick={() => onDarkChange(false)}>浅色</button>
                <button type="button" className={dark ? "active" : ""} onClick={() => onDarkChange(true)}>夜间</button>
              </div>
            </div>
            <div className="settings-row-card">
              <div>
                <strong>界面语言</strong>
                <small>菜单与规划结果默认使用简体中文。</small>
              </div>
              <select defaultValue="zh-CN" aria-label="界面语言">
                <option value="zh-CN">简体中文</option>
                <option value="en">English</option>
              </select>
            </div>
            <div className="settings-row-card">
              <div>
                <strong>启动页面</strong>
                <small>打开 LifeOS 时进入上次使用的位置。</small>
              </div>
              <select defaultValue="home" aria-label="启动页面">
                <option value="home">今日概览</option>
                <option value="chat">对话</option>
              </select>
            </div>
          </>
        ) : null}

        {section === "agent" ? (
          <>
            <div className="settings-section-heading">
              <span className="card-kicker">AI 模型与偏好</span>
              <h2>选择 LifeOS 如何帮助你</h2>
              <p>连接常用模型，并选择 LifeOS 回应简单问题或整理多步计划的方式。</p>
            </div>
            <div className="settings-model-card">
              <div>
                <strong>当前对话模型</strong>
                <small>这里的切换会立即影响后续对话。</small>
              </div>
              <ModelSwitcher store={store} />
            </div>
            <div className="settings-row-card">
              <div>
                <strong>默认路由策略</strong>
                <small>LifeOS 会结合你的请求，选择直接回复或整理成步骤。</small>
              </div>
              <select
                value={defaultRoutingPolicy}
                onChange={(event) => setDefaultRoutingPolicy(event.target.value as AgentRoutingPolicy)}
                aria-label="默认处理方式"
              >
                <option value="auto">自动决定</option>
                <option value="force_self_plan">优先直接给建议</option>
                <option value="force_agent">优先整理步骤</option>
              </select>
            </div>
            <div className="settings-row-card">
              <div>
                <strong>简单的事直接给建议</strong>
                <small>较复杂的请求会先整理出计划，供你确认。</small>
              </div>
              <Toggle checked={autoSelfPlan} onChange={setAutoSelfPlan} label="简单的事直接给建议" />
            </div>
            <div className="settings-row-card">
              <div>
                <strong>开始操作前先询问我</strong>
                <small>可能改变内容或影响其他应用的操作，需要你确认。</small>
              </div>
              <Toggle checked={confirmAgent} onChange={setConfirmAgent} label="开始操作前先询问我" />
            </div>
            <div className="settings-policy-note">
              <IconSpark size={15} />
              <p><strong>当前方式：</strong>简单问题直接回复；需要多步处理时，LifeOS 会先展示计划，等待你确认。</p>
            </div>
          </>
        ) : null}

        {section === "memory" ? (
          <>
            <div className="settings-section-heading">
              <span className="card-kicker">我的记忆</span>
              <h2>LifeOS 会怎样参考你的记忆</h2>
              <p>在对话和规划中，LifeOS 会优先参考与你当前任务相关的偏好、项目和过往记录。</p>
            </div>
            <div className="settings-metrics">
              <div><strong>{memoryCount}</strong><span>已保存的记忆</span></div>
              <div><strong>{store.state.memory.candidates.length}</strong><span>待确认</span></div>
              <div><strong>{store.state.memory.backups.length}</strong><span>备份记录</span></div>
            </div>
            <div className="settings-row-card">
              <div><strong>记忆保存位置</strong><small>你的记忆保存在 LifeOS 的本地数据目录中。</small></div>
              <span className="settings-state-pill">已启用</span>
            </div>
            <div className="settings-row-card">
              <div><strong>默认引用范围</strong><small>自动带入任务相关的偏好、项目和历史记录。</small></div>
              <select defaultValue="relevant" aria-label="记忆引用范围">
                <option value="relevant">相关项目 + 偏好</option>
                <option value="all">全部记录</option>
                <option value="project">仅当前项目</option>
              </select>
            </div>
          </>
        ) : null}

        {section === "vault" ? (
          <>
            <div className="settings-section-heading">
              <span className="card-kicker">Obsidian Vault</span>
              <h2>把 LifeOS 记录同步到你自己的 Markdown 仓库</h2>
              <p>选择本地 Vault 后，六类计划与复盘记录可以导出为带 frontmatter 的 Markdown。</p>
            </div>
            <div className="settings-row-card">
              <div><strong>Vault 路径</strong><small>例如 C:\Users\你的名字\Documents\ObsidianVault</small></div>
              <input value={vaultPath} onChange={(event) => setVaultPath(event.target.value)} placeholder="本地 Vault 的绝对路径" aria-label="Vault 路径" />
            </div>
            <div className="settings-row-card">
              <div><strong>导出子目录</strong><small>LifeOS 导出文件会放在该目录下，不建议填写已有的系统目录。</small></div>
              <input value={vaultFolder} onChange={(event) => setVaultFolder(event.target.value)} placeholder="LifeOS" aria-label="导出子目录" />
            </div>
            <div className="vault-actions">
              <button type="button" className="primary" onClick={() => void saveVault()} disabled={vaultBusy}>
                {vaultBusy ? "处理中…" : "连接并扫描"}
              </button>
              <button type="button" className="ghost" onClick={() => void loadVault()} disabled={vaultBusy}>
                重新扫描
              </button>
              {vaultStatus ? (
                <span className={`settings-state-pill ${vaultStatus.exists ? "ok" : "warn"}`}>
                  {vaultStatus.exists ? `${vaultStatus.file_count} 个 Markdown` : "路径不可用"}
                </span>
              ) : null}
            </div>
            {vaultMessage ? <div className="vault-message">{vaultMessage}</div> : null}
            <div className="settings-section-heading compact-heading vault-file-heading">
              <div>
                <span className="card-kicker">Vault 文件</span>
                <h3>最近 Markdown</h3>
              </div>
              <label className="vault-import-kind">
                <span>导入为</span>
                <select
                  value={vaultImportKind}
                  onChange={(event) => setVaultImportKind(event.target.value as StructuredEntryKind)}
                  aria-label="导入为记录类型"
                >
                  <option value="insight">心得 / 体验</option>
                  <option value="daily_plan">每日规划</option>
                  <option value="daily_review">每日复盘</option>
                  <option value="phase_plan">阶段性规划</option>
                  <option value="phase_review">阶段性复盘</option>
                  <option value="diary">日记</option>
                </select>
              </label>
            </div>
            <div className="vault-file-list">
              {vaultFiles.length ? vaultFiles.map((file) => (
                <div className="vault-file-row" key={file.path}>
                  <div>
                    <strong>{file.name}</strong>
                    <small>{file.path}</small>
                  </div>
                  <button type="button" className="ghost compact" onClick={() => void importFile(file)} disabled={vaultBusy}>
                    导入
                  </button>
                </div>
              )) : (
                <div className="state-empty">连接 Vault 后，这里会显示最近修改的 Markdown 文件。</div>
              )}
            </div>
          </>
        ) : null}

        {section === "notifications" ? (
          <>
            <div className="settings-section-heading">
              <span className="card-kicker">通知</span>
              <h2>只在需要你决定时提醒</h2>
              <p>减少无关打断，保留 Agent 权限与任务完成通知。</p>
            </div>
            <div className="settings-row-card">
              <div><strong>Agent 权限请求</strong><small>执行层需要权限时立即提醒。</small></div>
              <Toggle checked={permissionAlerts} onChange={setPermissionAlerts} label="Agent 权限请求" />
            </div>
            <div className="settings-row-card">
              <div><strong>每日规划摘要</strong><small>每天晚上汇总当天进展和明日建议。</small></div>
              <Toggle checked={dailySummary} onChange={setDailySummary} label="每日规划摘要" />
            </div>
          </>
        ) : null}

        {section === "data" ? (
          <>
            <div className="settings-section-heading">
              <span className="card-kicker">数据与隐私</span>
              <h2>本地优先，登录不自动上传历史</h2>
              <p>对话历史保存在浏览器本地，Memory 与 trace 由当前项目目录和后端管理。</p>
            </div>
            <div className="settings-row-card">
              <div><strong>数据模式</strong><small>{store.state.ui.dataMode === "backend" ? "已连接本机 LifeOS API。" : "部分接口不可用，正在使用预览数据。"}</small></div>
              <span className="settings-state-pill">{store.state.ui.dataMode === "backend" ? "实时" : "预览"}</span>
            </div>
            <div className="settings-row-card">
              <div><strong>对话历史存储</strong><small>保存在当前浏览器的 localStorage，可在对话页按时间查找。</small></div>
              <button
                type="button"
                className="ghost"
                onClick={() => {
                  if (window.confirm("清除当前浏览器中的对话历史？")) {
                    window.localStorage.removeItem("lifeos-chat-history");
                    window.location.reload();
                  }
                }}
              >
                清除历史
              </button>
            </div>
            <div className="settings-policy-note">
              <IconShield size={15} />
              <p><strong>隐私边界：</strong>后端地址和模型 Key 不会显示在对话历史里；API Key 继续只保存在本机后端配置中。</p>
            </div>
            <div className="settings-row-card">
              <div><strong>运行信息与排障</strong><small>查看处理记录和内部状态，通常不需要进入这里。</small></div>
              <button type="button" className="ghost" onClick={onOpenDiagnostics}>查看详情</button>
            </div>
          </>
        ) : null}
      </section>
    </div>
  );
}
