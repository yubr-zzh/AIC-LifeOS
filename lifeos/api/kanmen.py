"""Bridge 看护自愈（方案 5.2）。

每 10 秒探一次 bridge `/health`；**懒启动不陪跑**——`runtime.json` 不存在
（用户从没启动过 bridge）时看护线程什么都不做，不替用户拉起 bridge。
连续 3 次失败才重启（单次探测抖动不算死），重启之间指数退避、每小时
最多 5 次——防抖动循环（bridge 端口被别的程序占住时，无限重启只会
每 10 秒白杀一次孤儿进程）。
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from typing import Callable

from lifeos.api import bridge_admin

JIAN_GE = 10.0        # 探测间隔（秒）
LIAN_XU = 3           # 连续失败多少次才认定死了
HOU_TUI = (10.0, 20.0, 40.0, 80.0, 160.0)   # 重启之间的指数退避
MEI_XIAO_SHI = 5      # 每小时重启上限


def _jian_kang(a1: int) -> bool:
    """/health 探测。任何异常都算「不健康」——bridge 半死（端口在但不回
    JSON）比彻底死了更该重启。"""
    try:
        with urllib.request.urlopen(  # noqa: S310 - 固定回环地址
                f"http://127.0.0.1:{a1}/health", timeout=3.0) as resp:
            return bool(json.loads(resp.read().decode("utf-8")).get("ok"))
    except Exception:
        return False


def _yi_bu(a1: int, a2: list[float]) -> tuple[str, int]:
    """看护的一步决策。返回 ("skip"|"restart", 新的连续失败计数)。

    **独立成纯函数是为了测试**——`_xun` 的循环本身没什么可验的，承重的是
    这套阈值：3 次失败、5 次/小时、退避序列。
    """
    yun = bridge_admin.du_yunxing()
    duan = yun.get("port")
    if not duan:
        return "skip", a1   # 懒启动：用户没启过 bridge，看护不代劳
    if _jian_kang(int(duan)):
        return "skip", 0
    a1 += 1
    if a1 < LIAN_XU:
        return "skip", a1
    xian = time.time()
    while a2 and xian - a2[0] > 3600:
        a2.pop(0)
    if len(a2) >= MEI_XIAO_SHI:
        return "skip", a1   # 本小时额度用完：宁可让它死着，也不无限白杀
    return "restart", 0


def _xun(a1: Callable[[], None] | None) -> None:
    shi_bai = 0
    chong_qi: list[float] = []
    while True:
        time.sleep(JIAN_GE)
        dong, shi_bai = _yi_bu(shi_bai, chong_qi)
        if dong != "restart":
            continue
        # 重启之间的指数退避：额度按「次」计，退避按「上一次重启的时间远近」取档。
        time.sleep(HOU_TUI[min(len(chong_qi), len(HOU_TUI) - 1)])
        hui = bridge_admin.qidong()
        chong_qi.append(time.time())
        if hui.get("ok") and a1 is not None:
            try:
                a1()
            except Exception:
                pass   # 发布失败不连累看护（见 server._fa_bridge_shi_jian）


def qi_dong(a1: Callable[[], None] | None = None) -> threading.Thread:
    """起看护线程。daemon——主进程退出它自然死，不吊住关闭流程。"""
    xian = threading.Thread(target=_xun, args=(a1,), daemon=True)
    xian.start()
    return xian
