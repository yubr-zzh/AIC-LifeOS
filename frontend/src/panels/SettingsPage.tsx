import { useEffect, useState } from "react";
import { ModelProviderSettings } from "./ModelProviderSettings";
import type { AgentRoutingPolicy } from "../api/types";
import { IconContrast } from "../components/Icons";

type Section = "models" | "appearance" | "agent";
const ROUTING_POLICY_KEY = "lifeos-agent-routing-policy";

function initialRoutingPolicy(): AgentRoutingPolicy {
  try {
    const value = localStorage.getItem(ROUTING_POLICY_KEY);
    return value === "force_agent" || value === "force_self_plan" ? value : "auto";
  } catch { return "auto"; }
}

interface Props {
  dark: boolean;
  onDarkChange: (dark: boolean) => void;
}

export function SettingsPage({ dark, onDarkChange }: Props) {
  const [section, setSection] = useState<Section>("models");
  const [routingPolicy, setRoutingPolicy] = useState<AgentRoutingPolicy>(initialRoutingPolicy);

  useEffect(() => {
    try { localStorage.setItem(ROUTING_POLICY_KEY, routingPolicy); } catch { /* preference is best-effort */ }
  }, [routingPolicy]);

  return (
    <div className="settings-layout">
      <aside className="settings-sidebar content-card" aria-label="设置分类">
        <div className="settings-sidebar-heading">
          <span className="card-kicker">PREFERENCES</span>
          <h2>设置</h2>
          <p>把 LifeOS 调整成适合你的工作方式。</p>
        </div>
        <button className={section === "models" ? "active" : ""} onClick={() => setSection("models")}>
          <span className="settings-nav-mark">AI</span>
          <span><strong>模型与 API</strong><small>Provider、密钥与默认模型</small></span>
        </button>
        <button className={section === "appearance" ? "active" : ""} onClick={() => setSection("appearance")}>
          <span className="settings-nav-mark"><IconContrast size={16} /></span>
          <span><strong>外观</strong><small>主题与显示偏好</small></span>
        </button>
        <button className={section === "agent" ? "active" : ""} onClick={() => setSection("agent")}>
          <span className="settings-nav-mark">AG</span>
          <span><strong>Agent 路由</strong><small>设置聊天请求的默认处理方式</small></span>
        </button>
        <div className="settings-sidebar-foot"><span className="status-orb" />设置保存在本机 LifeOS</div>
      </aside>

      <section className="settings-content content-card">
        {section === "models" ? <ModelProviderSettings /> : section === "appearance" ? (
          <div className="settings-section">
            <div className="settings-section-heading">
              <span className="card-kicker">APPEARANCE</span>
              <h2>让界面更适合你</h2>
              <p>主题偏好只影响当前浏览器，不会改变你的记录或模型配置。</p>
            </div>
            <div className="settings-option-row">
              <div><strong>界面主题</strong><small>选择更舒适的工作区配色。</small></div>
              <div className="settings-segmented">
                <button className={!dark ? "active" : ""} onClick={() => onDarkChange(false)}>浅色</button>
                <button className={dark ? "active" : ""} onClick={() => onDarkChange(true)}>夜间</button>
              </div>
            </div>
          </div>
        ) : (
          <div className="settings-section">
            <div className="settings-section-heading">
              <span className="card-kicker">AGENT ROUTING</span>
              <h2>谁来处理你的请求</h2>
              <p>此偏好会同步到聊天输入框。它只选择处理路径，不会绕过工具权限审查。</p>
            </div>
            <div className="settings-option-row">
              <div><strong>默认处理方式</strong><small>自动模式下，明确的内容请求不会进入执行型 Agent。</small></div>
              <select aria-label="默认 Agent 路由" value={routingPolicy} onChange={(event) => setRoutingPolicy(event.target.value as AgentRoutingPolicy)}>
                <option value="auto">自动判断</option>
                <option value="force_self_plan">只给文本建议</option>
                <option value="force_agent">使用执行型 Agent</option>
              </select>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
