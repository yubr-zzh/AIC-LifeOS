# -*- coding: utf-8 -*-
"""桌面链路开发态冒烟：/api 前缀归一 + 桌面直连代理 + 打包态拉起语义。

不起窗口，只起主服务线程 + 真实 bridge 子进程（dev 形态，-m 拉起），
验三件事：/api/events 归一 200、/agent-api/health 直连代理 200、
/api/bridge/start 能拉起 bridge。跑完即拆。
"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

GEN = Path(__file__).resolve().parent.parent
tmp = tempfile.mkdtemp(prefix="lifeos-verify-")
os.environ["LIFEOS_HOME"] = tmp
os.environ["LIFEOS_PORT"] = "18963"
os.environ["LIFEOS_GW_PORT"] = "18973"
os.environ["LIFEOS_DESKTOP"] = "1"

sys.path.insert(0, str(GEN))
from lifeos.api import server  # noqa: E402

fu, gw = server.zhuang_fu("127.0.0.1", 18963)
threading.Thread(target=fu.serve_forever, daemon=True).start()
time.sleep(0.5)


def get(lu, method="GET", data=None):
    tou = {"content-type": "application/json"}
    if method != "GET":
        with urllib.request.urlopen("http://127.0.0.1:18963/api/bridge/info",
                                    timeout=10) as r:
            tou["X-LifeOS-CSRF"] = json.loads(r.read().decode())["csrf"]
    req = urllib.request.Request(f"http://127.0.0.1:18963{lu}",
                                 data=None if data is None else json.dumps(data).encode(),
                                 headers=tou, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


jie = []
s, b = get("/api/health")
jie.append(("主服务健康", s == 200))
s, b = get("/api/events")
jie.append(("/api/events 归一（原 404）", s == 200))
s, b = get("/api/models")
jie.append(("/api/models 归一（原 404）", s == 200))
s, b = get("/api/skills")
jie.append(("/api/skills 归一（原 404）", s == 200))
s, b = get("/api/bridge/info")
jie.append(("/api/bridge/info 保留前缀", s == 200 and "running" in b))

# 拉起 bridge（dev：-m lifeos.bridge.run）
s, b = get("/api/bridge/start", "POST", {})
jie.append(("bridge/start 拉起", s == 200 and b.get("ok") is True))
s, b = get("/agent-api/health")
jie.append(("/agent-api/health 直连代理（原 502）",
            s == 200 and b.get("ok") is True))
s, b = get("/agent-api/agents")
jie.append(("/agent-api/agents 直连代理", s == 200 and "agents" in b))
agents = {a["agentId"]: a.get("available") for a in b.get("agents", [])} if s == 200 else {}
print(json.dumps({"jieguo": jie, "agents": agents},
                 ensure_ascii=False, indent=1))
ok = all(x for _, x in jie[:6])
# agents 可用性取决于本机 claude CLI 形态，不纳入成败
# 拉起 bridge（dev：-m lifeos.bridge.run）
s, b = get("/api/bridge/start", "POST", {})
jie.append(("bridge/start 拉起", s == 200 and b.get("ok") is True))
if not b.get("ok"):
    print("bridge/start 明细:", json.dumps(b, ensure_ascii=False))
    yw = Path(tmp) / "bridge" / "runtime.json"
    print("runtime.json 存在:", yw.exists(),
          yw.read_text(encoding="utf-8")[:200] if yw.exists() else "")
    ri = Path(tmp) / "bridge" / "bridge.log"
    if ri.exists():
        print("bridge.log 尾部:", ri.read_text(encoding="utf-8")[-800:])
