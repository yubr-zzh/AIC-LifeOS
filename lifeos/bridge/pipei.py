"""Bridge 侧的配对（方案 5.3 第 2–3 步；spec 8.1）。

**配对动作必须发生在本机页面。** 云端网页上的配对码任何登录用户都能看到；
如果 Bridge 自己去云端抓，就等于任何人都能把一个恶意 Bridge 挂到受害者账号下。
把粘贴动作留在本机，就把「谁在操作这台机器的 Bridge」这个判断留在了本机。

本模块不 import `run.py`：`run` 会 import `http`，`http` 要 import 本模块，
成环。runtime.json 的路径由调用方传进来（`BridgeServer.yun_wen`）。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from lifeos.api.dangqian import YongHuFeiFa, he_fa
from lifeos.bridge.cun import shou_quan
from lifeos.storage.atomic import write_json

CLOUD = (os.environ.get("LIFEOS_MAIN_URL") or "http://127.0.0.1:8765").rstrip("/")
SHI_XIAN = 10.0

RI = logging.getLogger("lifeos.bridge.pipei")

# runtime.json 的读-改-写锁。**整个进程只有这一把。**
# ponytail: 单锁天花板 = 落盘一次要起一个临时文件重命名（Windows 上还要走
# icacls），量级几毫秒；调用点只有配对 / spawn 子进程 / 隧道状态三处，
# 真成了瓶颈再按调用点分锁。
XIE_SUO = threading.RLock()


class PeiDuiShiBai(Exception):
    def __init__(self, a1: str, a2: str) -> None:
        super().__init__(a2)
        self.code = a1
        self.message = a2


def pai(a1: str, a2: str, a3: Path, a4: str) -> dict[str, Any]:
    """用配对码换凭据并落盘 runtime.json。失败抛 PeiDuiShiBai。

    **失败时绝不改动 runtime.json**：先拿到云端响应、确认成功，再动文件。
    半途失败留下一个「deviceId 有、deviceToken 没有」的 runtime 会让 Bridge
    以为已经配对过，从而再也不进配对流程。
    """
    shu = json.dumps({"code": a1, "label": a2, "instanceId": a4}).encode("utf-8")
    req = urllib.request.Request(
        f"{CLOUD}/api/bridge/pair", data=shu, method="POST",
        headers={"content-type": "application/json; charset=utf-8"})
    # 本机有系统代理，默认 opener 会走代理把回环请求变成 502（localbus.py 同款）。
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with op.open(req, timeout=SHI_XIAN) as r:
            xin = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            ti = json.loads(e.read().decode("utf-8"))
            ma = str(ti.get("error", {}).get("code") or "invalid_request")
            wen = str(ti.get("error", {}).get("message") or "配对失败")
        except Exception:  # noqa: BLE001
            ma, wen = "invalid_request", f"配对失败（HTTP {e.code}）"
        raise PeiDuiShiBai(ma, wen) from e
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as e:
        raise PeiDuiShiBai("agent_unavailable", f"连不上主服务：{type(e).__name__}") from e

    if not xin.get("deviceId") or not xin.get("deviceToken"):
        raise PeiDuiShiBai("invalid_request", "主服务没有返回设备凭据")

    # **主服务返回的 userId 必须过 `he_fa` 再落盘**（阶段 6 修复轮 2，承重 4）。
    # 它会成为凭据目录名的一部分（`pingju.mu_lu_ming`），而 11.1 明说接入登录后
    # 它来自 cookie——届时这就是外部输入。`../..` 能把凭据写到 `users/` 之外，
    # `alice.` 则是「两个 uid 折叠到同一目录」那个洞的引信。
    # 抛 `PeiDuiShiBai` 而不是静默丢弃：落一个非法值下去，Bridge 下次启动
    # 照样会去拼路径，而那时用户看到的是「Bridge 起不来」而不是「配对失败」。
    try:
        uid = he_fa(str(xin.get("userId") or "local"))
    except YongHuFeiFa:
        raise PeiDuiShiBai("invalid_request",
                           "主服务返回的 userId 不合法，配对已中止") from None

    yun = gai(a3, {
        "deviceId": xin["deviceId"],
        "deviceToken": xin["deviceToken"],
        "userId": uid,
        "tunnelState": "none",
        "schemaVersion": 2,
    })
    return {"deviceId": xin["deviceId"], "deviceToken": xin["deviceToken"],
            "userId": yun["userId"]}


def du(a1: Path) -> dict[str, Any]:
    """读 runtime.json。读坏一律按空对象——不能让一个坏文件挡住配对。

    **降级必须出声。** 静默降级的问题是：文件坏了之后所有写者都从空对象
    起步，于是配对凭据、pids、tunnelState 一路被写成「像第一次启动」的样子，
    而日志里一行都没有——用户看到的现象是「Bridge 突然又要重新配对了」，
    排查时完全无从下手。这里降级照做，但把原因记下来。
    """
    try:
        x = json.loads(a1.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}          # 第一次启动没有这个文件，是正常路径不是异常
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        RI.warning("runtime.json 读不出来，按空对象处理（%s：%s）。"
                   "这会让下一次写把它整个盖掉——凭据若已丢，需要重新配对。",
                   type(e).__name__, a1)
        return {}
    if not isinstance(x, dict):
        RI.warning("runtime.json 顶层不是对象，按空对象处理：%s", a1)
        return {}
    return x


def gai(a1: Path, a2: dict[str, Any]) -> dict[str, Any]:
    """读-改-写 runtime.json，返回落盘后的内容。`a2` 里的键赢。

    **整段在 `XIE_SUO` 里，这是全进程唯一的一把 runtime.json 锁。**
    不锁的症状是丢一次写：两个 HTTP 线程同时 spawn 不同会话，各读到同一份旧
    内容，后写的把先写的 pids 抹掉，留下一个下次启动也回收不掉的孤儿 `claude`。
    各模块自己上一把锁仍然是两个临界区，照样互相丢写——所以锁定义在这里，
    调用方一律走这个函数。
    """
    with XIE_SUO:
        xin = du(a1)
        xin.update(a2)
        _xie(a1, xin)
    return xin


def gai_quan(a1: Path, a2: dict[str, Any]) -> dict[str, Any]:
    """**整份**替换 runtime.json，返回落盘后的内容。`a2` 完全赢。

    与 `gai` 的区别只有一条：**不保留盘上已有的键**。它存在的唯一理由是
    启动初始化那一刻——那时盘上的内容就是要被 Bridge 的权威快照取代的
    （见 `run.zao_yun`）。其余场合一律用 `gai`：整份覆盖会把配对写下的
    `deviceId`/`deviceToken`/`userId` 和隧道写的 `tunnelState` 抹成启动值。

    锁、`write_json`、权限收紧三样都还在 `XIE_SUO` 里，与 `gai` 是同一段
    临界区——**这是它能存在的唯一理由**：多一个写函数不是问题，多一把
    锁或多个「读-改-写」实现才是。
    """
    with XIE_SUO:
        _xie(a1, dict(a2))
        return dict(a2)


def _xie(a1: Path, a2: dict[str, Any]) -> None:
    """原子写 + 权限收紧。**调用方必须已持 `XIE_SUO`**——这是全进程唯一的
    runtime 落盘实现，锁在这里就只一把。"""
    # **write_json 不建父目录**（计划复核确认：它直接 temporary.write_text）。
    # 少了这一行，全新机器上第一次配对就 FileNotFoundError。
    a1.parent.mkdir(parents=True, exist_ok=True)
    write_json(a1, a2)
    shou_quan(a1)  # deviceToken 是明文，与 runtime.json 里的 token 同级敏感
