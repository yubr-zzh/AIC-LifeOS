// 登录体系的传输层（方案 6.2/6.4）。
//
// 会话凭据是 HttpOnly Cookie，前端拿不到也不需要拿；CSRF token 走响应体
// 下发，写端点再带回去（与服务端 `_fangxing` 对应）。
//
// 401 纪律：任何接口回 401 就广播 `lifeos:unauthorized`，由 AuthGate 收到后
// 切回登录页（方案 6.4 的「响应拦截器」）。登录/状态接口自己豁免——它们
// 401 没有意义，也不会造成死循环。

export interface AuthStatus {
  initialized: boolean;
  authenticated: boolean;
  username: string | null;
  avatar: string | null;
  csrf: string;
}

function cong401(res: Response): void {
  if (res.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("lifeos:unauthorized"));
  }
}

/** 登录/注册成功的响应体（服务端 `_handle_auth_setup` / `_handle_auth_login`）。 */
export interface DengLuHui {
  ok: boolean;
  username: string;
  csrf: string;
}

async function duHou(res: Response): Promise<Response> {
  cong401(res);
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as {
      error?: { message?: string };
    };
    throw new Error(body.error?.message ?? `HTTP ${res.status}`);
  }
  return res;
}

export async function authStatus(): Promise<AuthStatus> {
  const res = await fetch("/api/auth/status");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as AuthStatus;
}

export async function setupAccount(
  username: string,
  password: string,
): Promise<DengLuHui> {
  const res = await fetch("/api/auth/setup", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  await duHou(res);
  return (await res.json()) as DengLuHui;
}

export async function login(
  username: string,
  password: string,
  remember: boolean,
): Promise<DengLuHui> {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password, remember }),
  });
  await duHou(res);
  return (await res.json()) as DengLuHui;
}

export async function logout(): Promise<void> {
  const res = await fetch("/api/auth/logout", { method: "POST" });
  await duHou(res);
}

export async function saveAvatar(
  avatar: string | null,
  csrf: string,
): Promise<{ ok: boolean; avatar: string | null }> {
  const res = await fetch("/api/auth/profile", {
    method: "PUT",
    headers: { "content-type": "application/json", "X-LifeOS-CSRF": csrf },
    body: JSON.stringify({ avatar }),
  });
  await duHou(res);
  return (await res.json()) as { ok: boolean; avatar: string | null };
}

export async function changePassword(
  oldPassword: string,
  newPassword: string,
  csrf: string,
): Promise<{ ok: boolean; revoked: number }> {
  const res = await fetch("/api/auth/password", {
    method: "PUT",
    headers: { "content-type": "application/json", "X-LifeOS-CSRF": csrf },
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  });
  await duHou(res);
  return (await res.json()) as { ok: boolean; revoked: number };
}

export interface SessionRow {
  tokenHash: string;
  username: string | null;
  created_at: number;
  expires_at: number;
  current: boolean;
}

export async function listSessions(): Promise<SessionRow[]> {
  const res = await fetch("/api/auth/sessions");
  const data = (await duHou(res).then((r) => r.json())) as {
    sessions: SessionRow[];
  };
  return data.sessions;
}

export async function revokeSession(
  tokenHash: string,
  csrf: string,
): Promise<void> {
  const res = await fetch("/api/auth/sessions", {
    method: "DELETE",
    headers: { "content-type": "application/json", "X-LifeOS-CSRF": csrf },
    body: JSON.stringify({ tokenHash }),
  });
  await duHou(res);
}

/** 密码强度提示（方案 6.4）。0–3：弱/中/强。只提示，不拦提交（服务端是唯一裁判）。 */
export function kouLingQiangDu(a: string): number {
  if (a.length < 8) return 0;
  let fen = 1;
  if (/[A-Z]/.test(a) && /[a-z]/.test(a)) fen += 1;
  if (/\d/.test(a) && /[^A-Za-z0-9]/.test(a)) fen += 1;
  return Math.min(fen, 3);
}
