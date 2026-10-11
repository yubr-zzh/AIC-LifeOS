// 登录体系的前端落点（方案 6.4）。
//
// AuthGate：首启检测 /api/auth/status —— 未初始化渲染「创建管理员账户」
// 向导，已初始化渲染登录表单，已登录渲染 children。任何接口回 401
// （client.ts / agentClient.ts / authClient.ts 三处广播）都把界面切回登录页。
//
// AccountMenu：右上角账户菜单——改口令、登出、活跃会话管理。
// CSRF 是一次性的：每次写操作前都现取一枚，不缓存。

import { useCallback, useEffect, useState } from "react";
import {
  authStatus,
  changePassword,
  kouLingQiangDu,
  listSessions,
  login,
  logout,
  revokeSession,
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
        <p className="auth-sub">第一次使用 LifeOS，先给自己一个本地管理员账户。账户与口令只存在这台机器上。</p>
        <label className="auth-field">用户名
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus />
        </label>
        <label className="auth-field">口令
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
        </label>
        {password ? <span className={`auth-strength s${qiang}`}>口令强度：{QIANG_DU[qiang]}</span> : null}
        <label className="auth-field">再输一遍口令
          <input type="password" value={queRen} onChange={(e) => setQueRen(e.target.value)} autoComplete="new-password" />
        </label>
        {queRen && password !== queRen ? <span className="auth-error">两次输入的口令不一致</span> : null}
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
        <p className="auth-sub">输入本机账户口令，进入你的个人操作系统。</p>
        <label className="auth-field">用户名
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus />
        </label>
        <label className="auth-field">口令
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

/** 右上角账户菜单（方案 6.4）：改口令、登出、活跃会话管理。 */
export function AccountMenu() {
  const [kai, setKai] = useState(false);
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [huiHua, setHuiHua] = useState<SessionRow[]>([]);
  const [gaiKai, setGaiKai] = useState(false);

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

  return (
    <div className="account-menu">
      <button className="avatar avatar-button" onClick={() => setKai(!kai)} aria-expanded={kai} title="账户">{shouZi}</button>
      {kai ? (
        <div className="account-popover">
          <strong>{status.username}</strong>
          <button className="text-button" onClick={() => setGaiKai(!gaiKai)}>修改口令</button>
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
      <input type="password" placeholder="旧口令" value={jiu} onChange={(e) => setJiu(e.target.value)} autoComplete="current-password" />
      <input type="password" placeholder="新口令（至少 8 位）" value={xin} onChange={(e) => setXin(e.target.value)} autoComplete="new-password" />
      {xin ? <span className={`auth-strength s${qiang}`}>口令强度：{QIANG_DU[qiang]}</span> : null}
      {cuo ? <span className="auth-error">{cuo}</span> : null}
      <button className="green-button" type="submit" disabled={!jiu || xin.length < 8 || mang}>{mang ? "提交中…" : "确认修改"}</button>
    </form>
  );
}
