import { useState } from "react";
import { ModelProviderSettings } from "./ModelProviderSettings";

type Section = "models" | "appearance";

interface Props {
  dark: boolean;
  onDarkChange: (dark: boolean) => void;
}

export function SettingsPage({ dark, onDarkChange }: Props) {
  const [section, setSection] = useState<Section>("models");

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
          <span className="settings-nav-mark">◐</span>
          <span><strong>外观</strong><small>主题与显示偏好</small></span>
        </button>
        <div className="settings-sidebar-foot"><span className="status-orb" />设置保存在本机 LifeOS</div>
      </aside>

      <section className="settings-content content-card">
        {section === "models" ? <ModelProviderSettings /> : (
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
        )}
      </section>
    </div>
  );
}
