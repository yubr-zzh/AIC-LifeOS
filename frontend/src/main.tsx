import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/global.css";
import "./styles/agent.css";
import "katex/dist/katex.min.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// 全局崩溃兜底：以前任何未捕获异常都会留下一个纯白页面，用户既看不到
// 发生了什么，也没法把错误报给我们。这里把它显示出来。
function showCrash(text: string) {
  if (typeof document === "undefined") return;
  if (document.querySelector(".lifeos-crash")) return;
  const box = document.createElement("div");
  box.className = "lifeos-crash";
  box.textContent = `页面出错了：${text}`;
  document.body.appendChild(box);
}

if (typeof window !== "undefined") {
  window.addEventListener("error", (e) => showCrash(e.message || String(e.error)));
  window.addEventListener("unhandledrejection", (e) => showCrash(String((e as PromiseRejectionEvent).reason)));
}