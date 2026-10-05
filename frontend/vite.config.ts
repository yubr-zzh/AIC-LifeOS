import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { request as httpRequest, type IncomingMessage, type ServerResponse } from "node:http";
import { resolve } from "node:path";

const ROOT = resolve(__dirname, "..");
const RUNTIME = resolve(ROOT, ".lifeos/bridge/runtime.json");
const PREFIX = "/agent-api";

// 铁律（方案 5.1）：任何读取 Bridge 地址的一方都必须从 runtime.json 读端口，
// 禁止硬编码 8766。端口漂到 8767 时写死的 target 表现为「偶发连不上」。
// 注册 ≠ 已连接：读不到一律按 Bridge 离线处理。

function bridgeRuntime(): { port: number; token: string } {
  try {
    const data = JSON.parse(readFileSync(RUNTIME, "utf-8")) as { port?: number; token?: string };
    return {
      port: typeof data.port === "number" ? data.port : 8766,
      token: typeof data.token === "string" ? data.token : "",
    };
  } catch {
    return { port: 8766, token: "" };
  }
}

// Vite 自带的 proxy 选项在 5.x 里不接受函数式 target（http-proxy 需要在创建时
// 拿到字符串），所以这里自己转发。好处有两个：端口漂移不必重启 Vite，
// 以及 pipe 是流式的，SSE 不会被攒在缓冲区里。
function agentBridgeProxy(): Plugin {
  const handler = (req: IncomingMessage, res: ServerResponse, next: () => void): void => {
    if (!req.url || !req.url.startsWith(PREFIX)) {
      next();
      return;
    }
    // 隧道模式（LIFEOS_AGENT_VIA=tunnel）：/agent-api 一律走主服务，由它反代隧道。
    // 默认关，不破坏阶段 4 的本地直连验收路径。
    //
    // **分叉必须放在 bridgeRuntime() 之前**：这条分支压根不打本地 Bridge，
    // 提前读一次它的端口只会白读——读不到时还会让人误以为这条分支依赖它。
    //
    // **/stream 也走这里**：主服务的反代会把 SSE 逐帧转出来，`r.pipe(res)` 是流式的，
    // 不会攒在缓冲区里（与下面本地分支用 pipe 是同一条理由）。
    //
    // **浏览器自己的请求头原样转过去**：主服务那边靠 `Origin` / `Sec-Fetch-Site`
    // 判「是不是浏览器来源」来决定 /stream 放不放行（server.py 的 _pan_yuan），
    // 在这里把它们替换掉等于让 SSE 全被 403 挡掉。
    if (process.env.LIFEOS_AGENT_VIA === "tunnel") {
      // 主服务端口从环境变量读，8765 只作默认值（照 api/server.py:749 的口径）——
      // 写死的话，LIFEOS_PORT 一改这里就指着空端口，症状是「所有请求 502」而
      // 服务端看起来一切正常。
      const mainPort = Number(process.env.LIFEOS_PORT) || 8765;
      const upstream = httpRequest(
        {
          host: "127.0.0.1",
          port: mainPort,
          method: req.method,
          path: req.url,
          headers: req.headers,
        },
        (proxyRes) => {
          res.writeHead(proxyRes.statusCode ?? 502, proxyRes.headers);
          proxyRes.pipe(res);
        },
      );
      upstream.on("error", () => {
        if (!res.headersSent) {
          res.writeHead(502, { "content-type": "application/json; charset=utf-8" });
        }
        res.end(
          JSON.stringify({
            error: {
              code: "agent_unavailable",
              message: `主服务不可达（127.0.0.1:${mainPort}）`,
            },
          }),
        );
      });
      req.pipe(upstream);
      return;
    }
    const { port, token } = bridgeRuntime();
    let path = req.url.slice(PREFIX.length) || "/";

    // 凭据注入（方案 1.3 铁律）：**token 绝不进浏览器**。浏览器只请求
    // /agent-api/*，由这个本机可信进程读 runtime.json 补上凭据。
    // 公网形态换成主服务反代隧道后，前端代码一行不用改。
    // SSE 必须走 query —— EventSource 不能自定义 header，这是 7.2 唯一可行的位置。
    const headers: Record<string, string | string[] | undefined> = {
      ...req.headers,
      host: `127.0.0.1:${port}`,
    };
    if (token) {
      if (path.startsWith("/stream")) {
        path += (path.includes("?") ? "&" : "?") + `token=${encodeURIComponent(token)}`;
      } else {
        headers["x-bridge-token"] = token;
      }
    }

    const upstream = httpRequest(
      {
        host: "127.0.0.1",
        port,
        method: req.method,
        path,
        headers,
      },
      (proxyRes) => {
        res.writeHead(proxyRes.statusCode ?? 502, proxyRes.headers);
        proxyRes.pipe(res);
      },
    );
    upstream.on("error", () => {
      if (!res.headersSent) {
        res.writeHead(502, { "content-type": "application/json; charset=utf-8" });
      }
      res.end(
        JSON.stringify({
          error: {
            code: "agent_unavailable",
            message: `Bridge 未运行，或端口 ${port} 不可达`,
          },
        }),
      );
    });
    req.pipe(upstream);
  };

  return {
    name: "lifeos-agent-bridge-proxy",
    configureServer(server) {
      server.middlewares.use(handler);
    },
    configurePreviewServer(server) {
      server.middlewares.use(handler);
    },
  };
}

// LifeOS console: dev server listens on 127.0.0.1:5173 and proxies
// /api/* to the local Python backend at 127.0.0.1:8765,
// /agent-api/* to the Agent Bridge (port read from runtime.json).
export default defineConfig({
  plugins: [react(), agentBridgeProxy()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      // 主服务自己的业务路由（/chat、/entries、/feedback…）**不带** /api 前缀，
      // 而管控类端点（/api/bridge/*、/api/settings/*，方案 10.2）**带**。
      // 一律剥前缀会让管控类一进开发环境就 404，而且只在 dev 复现——
      // 生产是主服务直接托管 dist，不走这条链。所以这里按前缀分流。
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
        rewrite: (path) =>
          /^\/api\/(bridge|settings)(\/|$)/.test(path) ? path : path.replace(/^\/api/, ""),
      },
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
});
