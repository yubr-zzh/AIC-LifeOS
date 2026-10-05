"""v2.0 本地 Agent 桥接。

独立进程，绑定 127.0.0.1:8766-8770，浏览器通过 Vite proxy 访问。
启动：python -m lifeos.bridge.run
"""

__all__ = ["models", "auth", "events", "planner_guard", "session", "http", "run"]
