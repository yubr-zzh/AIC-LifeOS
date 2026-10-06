import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { IconBolt, IconClose, IconShield, IconSpark, IconUser } from "../components/Icons";

export interface LocalUser {
  name: string;
  email?: string;
  guest?: boolean;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onSignedIn: (user: LocalUser) => void;
}

export function LoginDialog({ open, onClose, onSignedIn }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setMessage(null);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, open]);

  if (!open) return null;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!email.trim() || password.length < 8) {
      setMessage("请输入邮箱和至少 8 位密码。");
      return;
    }
    onSignedIn({
      name: email.split("@")[0] || "LifeOS 用户",
      email: email.trim(),
    });
  };

  const browserLogin = () => {
    onSignedIn({ name: "Lin", email: "lin@lifeos.local" });
  };

  const guestLogin = () => {
    onSignedIn({ name: "访客", guest: true });
  };

  return (
    <div className="login-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="login-dialog" role="dialog" aria-modal="true" aria-labelledby="login-title">
        <button type="button" className="login-close" onClick={onClose} aria-label="关闭登录"><IconClose size={17} /></button>
        <div className="login-visual">
          <div className="login-brand-lockup">
            <span><IconBolt size={18} /></span>
            <div><strong>LifeOS</strong><small>PLAN · THINK · ACT</small></div>
          </div>
          <div className="login-visual-copy">
            <span className="card-kicker">本地优先账户</span>
            <h2>把规划留在自己手里。</h2>
            <p>登录用于同步账户与跨设备偏好。未登录时，对话、Memory 和执行记录仍完整保存在当前设备。</p>
          </div>
          <div className="login-trust-points">
            <span><IconShield size={15} /> 不自动上传历史</span>
            <span><IconSpark size={15} /> 保留长期规划偏好</span>
          </div>
        </div>
        <div className="login-form-panel">
          <div className="login-form-head">
            <span className="card-kicker">账户</span>
            <h2 id="login-title">登录 LifeOS</h2>
            <p>继续已有账户，或先以访客身份使用。</p>
          </div>
          <form onSubmit={submit}>
            <label>
              <span>邮箱</span>
              <input
                type="email"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="name@example.com"
              />
            </label>
            <label>
              <span>密码</span>
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="至少 8 位"
              />
            </label>
            <div className="login-options">
              <label><input type="checkbox" defaultChecked /> 在此设备保持登录</label>
              <button type="button" onClick={() => setMessage("正式版本会通过邮箱发送重置链接。")}>忘记密码</button>
            </div>
            {message ? <div className="login-message" role="status">{message}</div> : null}
            <button type="submit" className="green-button login-submit">登录并保留本地内容</button>
            <div className="login-divider"><span>或</span></div>
            <button type="button" className="ghost login-browser" onClick={browserLogin}>使用浏览器账户继续</button>
          </form>
          <button type="button" className="login-guest" onClick={guestLogin}>
            <IconUser size={15} />
            继续使用访客模式
          </button>
        </div>
      </section>
    </div>
  );
}
