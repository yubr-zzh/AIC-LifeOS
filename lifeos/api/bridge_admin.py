"""主服务侧的 Bridge 管理（方案 10.2 的本地形态部分）。

**这里持有 Bridge token，但绝不把它发给浏览器**（10.2 的硬规定：任何登录用户
都能取到一个能批准任意工具调用的 token，公网形态下更不成立）。浏览器只拿到
显示用的状态。启动与停止由主服务代为发起，token 留在这一侧。

配对 / 解绑 / 设备列表三个端点属于阶段 6（公网形态 + 出站隧道）：配对码在云端生成，
Bridge 拿码换 `deviceToken`（明文只在换的那一次出现），此后 Bridge 用它出站建隧道。
本机 Bridge 的管理（启动 / 停止 / 状态）仍是上面那套。
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from lifeos.api.dangqian import dang_qian_yong_hu
from lifeos.api.devices import PeiMa, SheBiao

XIANG = Path(__file__).resolve().parent.parent.parent
WEN_JIA = XIANG / ".lifeos" / "bridge" / "runtime.json"

# 设备表与隧道网关由主服务在 run() 时注入。没有网关（本地直连形态）时
# 隧道相关端点仍可用，只是 unpair 断不开任何东西。
SHE: SheBiao | None = None
GW: Any = None
MA: PeiMa = PeiMa()


def zhuang(a1: SheBiao, a2: Any, a3: PeiMa | None = None) -> None:
    """装配。测试与 server.run() 都从这里进。"""
    global SHE, GW, MA
    SHE = a1
    GW = a2
    if a3 is not None:
        MA = a3
    # 合成流的互斥量与表**在这里一次性建好**，不给 `_he_cheng_liu` 用
    # `getattr(gw, "_hc_suo", threading.Lock())` 兜底：兜底里的默认值每次
    # 求值都是一把新锁，`try` 与 `finally` 拿到的不是同一把，表会被并发写坏。
    if a2 is not None and not hasattr(a2, "_hc_suo"):
        a2._hc_suo = threading.Lock()
        a2._hc_biao = {}
    # 主服务侧代理 SSE 的活跃连接登记。**同样一次性建好，不 getattr 兜底**——
    # 理由与上面那两行相同：兜底里的 `threading.Lock()` 每次求值都是一把新锁，
    # 登记与释放会落在不同的临界区里，名额永久泄漏。
    #
    # **值必须是「每条连接一个集合」，不能是「每个来源一个元素」。** 同来源的
    # 8 条连接若共用一个 key，装进 `set` 只剩 1 个元素：上限数不到，429 永不
    # 触发；而合成流「同设备只留最新一条」唤醒旧流后，旧流一退出就把那个
    # 共享 key 删掉，计数归零——名额不但没限住，还会凭空多出额度。
    # 计数与释放都按 key 定位到集合里精确增删，于是释放天然幂等。
    if a2 is not None and not hasattr(a2, "_dl_suo"):
        a2._dl_suo = threading.Lock()
        a2._dai_liu_biao = {}


def _biao() -> SheBiao:
    if SHE is None:
        raise RuntimeError("设备表尚未装配（bridge_admin.zhuang）")
    return SHE


def sheng_ma() -> dict[str, Any]:
    """生成配对码（8.1 第 1 步）。"""
    return MA.sheng(dang_qian_yong_hu())


def pai_dui(a1: str, a2: str, a3: str) -> dict[str, Any]:
    """用配对码换 deviceId + deviceToken（8.1 第 3 步）。

    **明文 deviceToken 只在这里出现一次**，此后任何端点都不返回它。
    """
    uid = MA.dui(a1)
    if uid is None:
        # 不存在 / 过期 / 已用过，返回同一句话——不做探测预言机（8.1）
        raise ValueError("配对码无效或已过期")
    # 一台设备对一个账号（`du_she()` 的 docstring，1.4）。**新配对必须顶掉旧的**，
    # 否则旧设备永远占据 `/agent-api/*` 的代理目标，而新 Bridge 带的是新 token
    # ⇒ 网关按旧 deviceId 查不到在途连接 ⇒ 全线 502「设备不在线」。
    # 症状会伪装成「隧道明明 connected 却全部 502」，极难归因。
    # 用户 2026-09-29 裁定：新配对顶掉旧设备。
    # 先取旧表再 jia()：这样不必把刚配的这台排除掉。
    jiu = [x["deviceId"] for x in _biao().lie(uid) if not x.get("revoked")]
    ji = _biao().jia(uid, a2 or "未命名设备", a3 or "")
    for did in jiu:
        # 与 jie_bang() 同一套动作：令牌失效 + 隧道立即断开（15.5、7.4）。
        if _biao().jie(did) and GW is not None:
            GW.duan(did)
    return {"deviceId": ji["deviceId"], "deviceToken": ji["deviceToken"], "userId": uid}


def jie_bang(a1: str) -> dict[str, Any]:
    """解绑。令牌立即失效，隧道立即断开（15.5、7.4）。"""
    ok = _biao().jie(a1)
    duan_le = False
    if ok and GW is not None:
        GW.duan(a1)
        duan_le = True
    return {"ok": ok, "tunnelClosed": duan_le}


def she_lie(a1: str | None = None) -> list[dict[str, Any]]:
    """设备列表（8.3）。`online` 来自网关，不在 devices.json 里，现问现填。"""
    return [
        {**x, "online": GW is not None and GW.zhuang_tai(x["deviceId"]) == "connected"}
        for x in _biao().lie(a1)
    ]


def du_she() -> dict[str, Any] | None:
    """当前用户的第一台未解绑设备（`/agent-api/*` 反代的目标，1.4 一台设备对一个账号）。

    **是模块级函数而不是 handler 的方法**：它要读 `SHE` 这份模块状态，
    放在 handler 里拿不到。已解绑的设备要跳过——隧道确实断了，但设备列表里
    还要显示它（15.5 不删记录），拿它当代理目标只会稳定回 502。
    """
    for x in _biao().lie(dang_qian_yong_hu()):
        if not x.get("revoked"):
            return x
    return None


def du_yunxing() -> dict[str, Any]:
    """读 runtime.json。读不到就是「没注册」，一律按离线处理。"""
    try:
        return json.loads(WEN_JIA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _tiao(a1: str, a2: str, a3: dict | None = None, a4: float = 2.0) -> dict[str, Any]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{a1}{a2}",
        data=None if a3 is None else json.dumps(a3).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="GET" if a3 is None else "POST",
    )
    tok = du_yunxing().get("token", "")
    if tok:
        # EventSource 之外的请求走 header；query 里出现 token 会被 HTTP 日志记下来。
        req.add_header("X-Bridge-Token", tok)
    with urllib.request.urlopen(req, timeout=a4) as resp:  # noqa: S310 - 固定回环地址
        return json.loads(resp.read().decode("utf-8"))


def xinxi() -> dict[str, Any]:
    """GET /api/bridge/info 的载荷。**没有 token 字段**，这是刻意的。

    公网形态下浏览器只拿到显示用的状态；凭据全在 Bridge 与云端之间（5.3）。
    """
    yun = du_yunxing()
    out: dict[str, Any] = {
        "running": False, "port": None, "pid": None, "instanceId": None,
        "cliVersion": None, "tunnelState": "local", "deviceId": None,
        "error": None, "devices": [], "paired": False,
    }
    if SHE is not None:
        she = SHE.lie(dang_qian_yong_hu())
        out["devices"] = she
        out["paired"] = len([x for x in she if not x.get("revoked")]) > 0
    if not yun:
        out["error"] = "Bridge 未在本机注册（runtime.json 不存在）"
        return out
    out["port"] = yun.get("port")
    out["pid"] = yun.get("pid")
    out["deviceId"] = yun.get("deviceId") or out["deviceId"]
    out["tunnelState"] = yun.get("tunnelState") or "none"
    try:
        jian = _tiao(yun["port"], "/health")
        out["running"] = bool(jian.get("ok"))
        out["instanceId"] = jian.get("instanceId")
        out["cliVersion"] = yun.get("cliVersion")
    except (urllib.error.URLError, OSError, KeyError, ValueError, json.JSONDecodeError) as e:
        out["error"] = f"Bridge 未响应：{type(e).__name__}"
    return out


def qidong(a4: float = 8.0) -> dict[str, Any]:
    """拉起 Bridge 子进程。**仅本地开发形态**：公网下云端拉不起用户机器上的进程。"""
    yun = du_yunxing()
    if yun:
        try:
            if _tiao(yun["port"], "/health", a4=1.0).get("ok"):
                return {"ok": True, "port": yun["port"], "alreadyRunning": True}
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
            pass  # 端口在但没响应，当作没跑

    kw: dict[str, Any] = {}
    if os.name == "nt":
        # start_new_session 是 POSIX 语义，Windows 上会被静默忽略（5.4）。
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kw["start_new_session"] = True
    subprocess.Popen(
        [sys.executable, "-m", "lifeos.bridge.run"],
        cwd=str(XIANG),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **kw,
    )
    # 端口发现 + 写盘要时间，轮询而不是 sleep 一次。
    end = time.monotonic() + a4
    while time.monotonic() < end:
        time.sleep(0.25)
        yun = du_yunxing()
        if not yun:
            continue
        try:
            if _tiao(yun["port"], "/health", a4=1.0).get("ok"):
                return {"ok": True, "port": yun["port"], "alreadyRunning": False}
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
            continue
    return {"ok": False, "error": "Bridge 启动超时，看它的 stderr"}


def tingzhi() -> dict[str, Any]:
    """请求 Bridge 走 9.4 的两段式关闭：先收干净子进程，再自己退出。"""
    yun = du_yunxing()
    if not yun:
        return {"ok": True, "closed": 0, "note": "Bridge 本来就没在跑"}
    try:
        return _tiao(yun["port"], "/bridge/stop", {}, a4=5.0)
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ---- 状态改变型端点的 CSRF（10.2）----
#
# 只靠 Origin 校验已经能挡住「页面里第三方 iframe 发 no-cors 简单请求」这一招，
# 但 10.2 要求再加一枚一次性 token。两道都留着：任一失效都不放行，
# 攻击者要同时拿到同源 Origin 与本机可读响应才可能绕过。

_MA: dict[str, str] = {"token": secrets.token_hex(16)}


def qu_ma() -> str:
    return _MA["token"]


def yong_ma(a1: str | None) -> bool:
    """校验并轮换。一次性：用过即作废。"""
    if not a1 or not secrets.compare_digest(a1, _MA["token"]):
        return False
    _MA["token"] = secrets.token_hex(16)
    return True
