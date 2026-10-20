// 登录体系的前端落点（方案 6.4）。
//
// AuthGate：首启检测 /api/auth/status —— 未初始化渲染「创建管理员账户」
// 向导，已初始化渲染登录表单，已登录渲染 children。任何接口回 401
// （client.ts / agentClient.ts / authClient.ts 三处广播）都把界面切回登录页。
//
// AccountMenu：右上角账户菜单——改头像、改密码、登出、活跃会话管理。
// CSRF 是一次性的：每次写操作前都现取一枚，不缓存。

import { useCallback, useEffect, useRef, useState } from "react";
import {
  authStatus,
  changePassword,
  kouLingQiangDu,
  listSessions,
  login,
  logout,
  revokeSession,
  saveAvatar,
  setupAccount,
  type AuthStatus,
  type SessionRow,
} from "../api/authClient";

const QIANG_DU = ["太短（至少 8 位）", "弱", "中", "强"];

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [zhuang, setZhuang] = useState<"checking" | "setup" | "login" | "ok">("checking");

  const shua = useCallback(async () => {
    try {
      const s = await authStatus();
      if (s.authenticated) setZhuang("ok");
      else setZhuang(s.initialized ? "login" : "setup");
    } catch {
      // 后端没起/接口异常：停在登录页比白屏好，用户重试即可。
      setZhuang("login");
    }
  }, []);

  useEffect(() => { void shua(); }, [shua]);

  useEffect(() => {
    const ting = () => setZhuang("login");
    window.addEventListener("lifeos:unauthorized", ting);
    return () => window.removeEventListener("lifeos:unauthorized", ting);
  }, []);

  if (zhuang === "checking") {
    return <div className="auth-screen"><div className="auth-card"><p className="muted">正在检查登录状态…</p></div></div>;
  }
  if (zhuang === "setup") return <SetupView onDone={() => setZhuang("ok")} />;
  if (zhuang === "login") return <LoginView onDone={() => setZhuang("ok")} />;
  return <>{children}</>;
}

function SetupView({ onDone }: { onDone: () => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [queRen, setQueRen] = useState("");
  const [cuo, setCuo] = useState("");
  const [mang, setMang] = useState(false);

  const qiang = kouLingQiangDu(password);
  const keTiJiao = password.length >= 8 && password === queRen && username.trim().length > 0;

  const tiJiao = async () => {
    setMang(true); setCuo("");
    try {
      await setupAccount(username.trim(), password);
      onDone();
    } catch (e) {
      setCuo(e instanceof Error ? e.message : String(e));
    } finally { setMang(false); }
  };

  return (
    <div className="auth-screen">
      <form className="auth-card" onSubmit={(e) => { e.preventDefault(); if (keTiJiao) void tiJiao(); }}>
        <div className="auth-brand">LifeOS</div>
        <h1>创建管理员账户</h1>
        <p className="auth-sub">第一次使用 LifeOS，先给自己一个本地管理员账户。账户与密码只存在这台机器上。</p>
        <label className="auth-field">用户名
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus />
        </label>
        <label className="auth-field">密码
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
        </label>
        {password ? <span className={`auth-strength s${qiang}`}>密码强度：{QIANG_DU[qiang]}</span> : null}
        <label className="auth-field">再输一遍密码
          <input type="password" value={queRen} onChange={(e) => setQueRen(e.target.value)} autoComplete="new-password" />
        </label>
        {queRen && password !== queRen ? <span className="auth-error">两次输入的密码不一致</span> : null}
        {cuo ? <div role="alert" className="auth-error">{cuo}</div> : null}
        <button className="green-button" type="submit" disabled={!keTiJiao || mang}>
          {mang ? "创建中…" : "创建账户并进入"}
        </button>
      </form>
    </div>
  );
}

function LoginView({ onDone }: { onDone: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [cuo, setCuo] = useState("");
  const [mang, setMang] = useState(false);

  const tiJiao = async () => {
    setMang(true); setCuo("");
    try {
      await login(username.trim(), password, remember);
      onDone();
    } catch (e) {
      setCuo(e instanceof Error ? e.message : String(e));
    } finally { setMang(false); }
  };

  return (
    <div className="auth-screen">
      <form className="auth-card" onSubmit={(e) => { e.preventDefault(); if (username.trim() && password) void tiJiao(); }}>
        <div className="auth-brand">LifeOS</div>
        <h1>登录</h1>
        <p className="auth-sub">输入本机账户密码，进入你的个人操作系统。</p>
        <label className="auth-field">用户名
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus />
        </label>
        <label className="auth-field">密码
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </label>
        <label className="auth-remember">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          记住我（30 天内免登录）
        </label>
        {cuo ? <div role="alert" className="auth-error">{cuo}</div> : null}
        <button className="green-button" type="submit" disabled={!username.trim() || !password || mang}>
          {mang ? "登录中…" : "登录"}
        </button>
      </form>
    </div>
  );
}

/** 右上角账户菜单（方案 6.4）：改头像、改密码、登出、活跃会话管理。 */
function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("读取头像失败"));
    reader.readAsDataURL(file);
  });
}

async function resizeAvatar(file: File): Promise<string> {
  if (!file.type.startsWith("image/")) throw new Error("请选择图片文件");
  const source = await fileToDataUrl(file);
  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("头像图片无法解析"));
    img.src = source;
  });
  const width = image.naturalWidth || image.width;
  const height = image.naturalHeight || image.height;
  const side = Math.min(width, height);
  if (!side) throw new Error("头像图片尺寸无效");
  const canvas = document.createElement("canvas");
  canvas.width = 192;
  canvas.height = 192;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("当前环境无法处理头像图片");
  ctx.drawImage(image, (width - side) / 2, (height - side) / 2, side, side, 0, 0, 192, 192);
  return canvas.toDataURL("image/jpeg", 0.86);
}

export function AccountMenu() {
  const [kai, setKai] = useState(false);
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [huiHua, setHuiHua] = useState<SessionRow[]>([]);
  const [gaiKai, setGaiKai] = useState(false);
  const [avatarBusy, setAvatarBusy] = useState(false);
  const [avatarError, setAvatarError] = useState("");
  const avatarInput = useRef<HTMLInputElement>(null);

  const shua = useCallback(async () => {
    try {
      const s = await authStatus();
      setStatus(s);
      if (s.authenticated) setHuiHua(await listSessions());
    } catch { /* 未登录时菜单不渲染内容 */ }
  }, []);

  // status 必须挂载即拉取：只在 kai 时拉，会卡死在「?」div 上——那个 div 没有
  // onClick，头像永远点不开，也就永远触发不了 kai。
  useEffect(() => { void shua(); }, [shua]);
  useEffect(() => { if (kai) void shua(); }, [kai, shua]);

  if (!status) return <div className="avatar">…</div>;
  if (!status.authenticated) return <div className="avatar">?</div>;

  const shouZi = (status.username ?? "?").charAt(0).toUpperCase();

  const uploadAvatar = async (file: File | undefined) => {
    if (!file) return;
    setAvatarBusy(true);
    setAvatarError("");
    try {
      const avatar = await resizeAvatar(file);
      await saveAvatar(avatar, status.csrf);
      setStatus((current) => current ? { ...current, avatar } : current);
      await shua();
    } catch (error) {
      setAvatarError(error instanceof Error ? error.message : String(error));
    } finally {
      setAvatarBusy(false);
      if (avatarInput.current) avatarInput.current.value = "";
    }
  };

  const removeAvatar = async () => {
    setAvatarBusy(true);
    setAvatarError("");
    try {
      await saveAvatar(null, status.csrf);
      setStatus((current) => current ? { ...current, avatar: null } : current);
      await shua();
    } catch (error) {
      setAvatarError(error instanceof Error ? error.message : String(error));
    } finally {
      setAvatarBusy(false);
    }
  };

  return (
    <div className="account-menu">
      <button className="avatar avatar-button" onClick={() => setKai(!kai)} aria-expanded={kai} title="账户" aria-label="打开账户菜单">
        {status.avatar ? <img src={status.avatar} alt="" /> : shouZi}
      </button>
      {kai ? (
        <div className="account-popover">
          <div className="account-profile">
            <span className="account-profile-avatar">{status.avatar ? <img src={status.avatar} alt="" /> : shouZi}</span>
            <div><strong>{status.username}</strong><small>本地管理员</small></div>
          </div>
          <input ref={avatarInput} type="file" accept="image/png,image/jpeg,image/webp" hidden
            onChange={(event) => void uploadAvatar(event.target.files?.[0])} />
          <div className="account-avatar-actions">
            <button className="text-button" onClick={() => avatarInput.current?.click()} disabled={avatarBusy}>
              {avatarBusy ? "处理中…" : "修改头像"}
            </button>
            {status.avatar ? <button className="text-button" onClick={() => void removeAvatar()} disabled={avatarBusy}>移除头像</button> : null}
          </div>
          {avatarError ? <span className="auth-error">{avatarError}</span> : null}
          <button className="text-button" onClick={() => setGaiKai(!gaiKai)}>修改密码</button>
          {gaiKai ? <GaiKouLingForm csrf={status.csrf} onDone={() => { setGaiKai(false); void shua(); }} /> : null}
          <div className="session-list">
            <span className="card-kicker">活跃会话</span>
            {huiHua.map((x) => (
              <div className="session-row" key={x.tokenHash}>
                <span className="mono">{x.current ? "本设备" : x.tokenHash}</span>
                {!x.current ? (
                  <button
                    className="text-button"
                    onClick={async () => {
                      await revokeSession(x.tokenHash, status.csrf).catch(() => {});
                      void shua();
                    }}
                  >吊销</button>
                ) : null}
              </div>
            ))}
          </div>
          <button
            className="green-button"
            onClick={async () => {
              await logout().catch(() => {});
              window.dispatchEvent(new CustomEvent("lifeos:unauthorized"));
            }}
          >退出登录</button>
        </div>
      ) : null}
    </div>
  );
}

function GaiKouLingForm({ csrf, onDone }: { csrf: string; onDone: () => void }) {
  const [jiu, setJiu] = useState("");
  const [xin, setXin] = useState("");
  const [cuo, setCuo] = useState("");
  const [mang, setMang] = useState(false);
  const qiang = kouLingQiangDu(xin);

  return (
    <form
      className="auth-field-group"
      onSubmit={async (e) => {
        e.preventDefault();
        setMang(true); setCuo("");
        try {
          await changePassword(jiu, xin, csrf);
          onDone();
        } catch (err) {
          setCuo(err instanceof Error ? err.message : String(err));
        } finally { setMang(false); }
      }}
    >
      <input type="password" placeholder="旧密码" value={jiu} onChange={(e) => setJiu(e.target.value)} autoComplete="current-password" />
      <input type="password" placeholder="新密码（至少 8 位）" value={xin} onChange={(e) => setXin(e.target.value)} autoComplete="new-password" />
      {xin ? <span className={`auth-strength s${qiang}`}>密码强度：{QIANG_DU[qiang]}</span> : null}
      {cuo ? <span className="auth-error">{cuo}</span> : null}
      <button className="green-button" type="submit" disabled={!jiu || xin.length < 8 || mang}>{mang ? "提交中…" : "确认修改"}</button>
    </form>
  );
}
