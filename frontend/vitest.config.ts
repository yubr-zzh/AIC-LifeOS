import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// 单独一个文件而不是塞进 vite.config.ts：那里的插件会去读 runtime.json 并
// 挂转发中间件，测试不需要它，也不想让测试因为本机 Bridge 的状态而失败。
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
