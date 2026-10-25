import { afterEach, describe, expect, it, vi } from "vitest";
import {
  authStatus,
  changePassword,
  kouLingQiangDu,
  login,
  logout,
  saveAvatar,
  setupAccount,
} from "./authClient";

function okRes(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.removeEventListener("lifeos:unauthorized", () => {});
});

describe("authClient", () => {
  it("authStatus parses the backend shape", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => okRes({
      initialized: true, authenticated: false, username: null, avatar: null, csrf: "tok-1",
    })));
    const s = await authStatus();
    expect(s.initialized).toBe(true);
    expect(s.authenticated).toBe(false);
    expect(s.csrf).toBe("tok-1");
  });

  it("login sends username, password and remember flag", async () => {
    let body: unknown;
    vi.stubGlobal("fetch", vi.fn(async (_u, init) => {
      body = JSON.parse(String(init?.body));
      return okRes({ ok: true, username: "admin", csrf: "c" });
    }));
    await login("admin", "pw123456", true);
    expect(body).toEqual({ username: "admin", password: "pw123456", remember: true });
  });

  it("surfaces the backend error message on login failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ error: { code: "unauthorized", message: "用户名或密码不正确" } }),
      { status: 401, headers: { "content-type": "application/json" } },
    )));
    await expect(login("admin", "wrong", false)).rejects.toThrow("用户名或密码不正确");
  });

  it("broadcasts lifeos:unauthorized on any 401", async () => {
    const ting = vi.fn();
    window.addEventListener("lifeos:unauthorized", ting);
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })));
    await expect(changePassword("a", "b", "c")).rejects.toThrow();
    expect(ting).toHaveBeenCalledTimes(1);
  });

  it("never broadcasts 401 from logout (exempt path)", async () => {
    const ting = vi.fn();
    window.addEventListener("lifeos:unauthorized", ting);
    vi.stubGlobal("fetch", vi.fn(async () => okRes({ ok: true })));
    await logout();
    expect(ting).not.toHaveBeenCalled();
  });

  it("setupAccount posts username and password", async () => {
    let body: unknown;
    let url = "";
    vi.stubGlobal("fetch", vi.fn(async (u, init) => {
      url = String(u);
      body = JSON.parse(String(init?.body));
      return okRes({ ok: true, username: "admin", csrf: "c" });
    }));
    await setupAccount("admin", "password123");
    expect(url).toBe("/api/auth/setup");
    expect(body).toEqual({ username: "admin", password: "password123" });
  });

  it("saveAvatar sends the data URL with the CSRF header", async () => {
    let body: unknown;
    let initSeen: RequestInit | undefined;
    vi.stubGlobal("fetch", vi.fn(async (_u, init) => {
      initSeen = init;
      body = JSON.parse(String(init?.body));
      return okRes({ ok: true, avatar: "data:image/jpeg;base64,AAAA" });
    }));
    await saveAvatar("data:image/jpeg;base64,AAAA", "csrf-1");
    expect(body).toEqual({ avatar: "data:image/jpeg;base64,AAAA" });
    expect((initSeen?.headers as Record<string, string>)["X-LifeOS-CSRF"]).toBe("csrf-1");
  });

  it("kouLingQiangDu grades by length and character classes", () => {
    expect(kouLingQiangDu("short")).toBe(0);
    expect(kouLingQiangDu("alllowercase1")).toBe(1);
    expect(kouLingQiangDu("Lower1234")).toBe(2);
    expect(kouLingQiangDu("Lower1234!")).toBe(3);
  });
});
