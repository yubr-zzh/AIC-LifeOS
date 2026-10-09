"""设备注册表与配对码（方案 15.3.1、5.3；spec 8.1、8.2）。

两条纪律，动之前先读懂：

1. **只存 tokenHash，不存明文 deviceToken。** 明文只在 `jia()` 的返回里出现一次。
   `runtime.json` 存明文 Bridge token 是因为它只在本机使用（本机 Agent 本来就读得到它，
   5.3 的诚实陈述）；而 deviceToken 能连公网网关，落明文等于给云端留一份
   可被拖库利用的凭据。
2. **读失败一律降级为空表**，绝不让主服务起不来（与 `cun.py` 同一条纪律）。
   多设备共存时，一个坏文件不能让所有用户都连不上。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from lifeos.bridge.cun import shou_quan

# 配对码字符集：去掉 O/0/I/1/L 这些手抄会错的
ZI = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
MA_CHANG = 6
PIAN = 300.0  # 配对码有效期 5 分钟（spec 8.1）

# deviceId 与 tokenHash 的形状。写死正则，读盘时用它挡掉被手改过的记录：
# `self.she` 的外部入口只有读盘这一条（`jia()` 写入的是 `_ha()` 的结果，天然合法），
# 所以畸形数据在这里挡掉就够，`ren()` 不必再加防御。
JIA = re.compile(r"^dev-[0-9a-f]{12}$")
ZHAI = re.compile(r"^[0-9a-f]{64}$")


def _ha(a1: str) -> str:
    """deviceToken 的摘要。用 sha256 不用 hmac：token 本身是 32 字节随机，
    没有「弱口令」可猜，不需要加盐或慢哈希。"""
    return hashlib.sha256(a1.encode("utf-8")).hexdigest()


class SheBiao:
    """设备表。落盘 devices.json，原子重写（同 `cun.Cun.xie_hui` 的套路）。"""

    def __init__(self, a1: Path, a2: logging.Logger | None = None) -> None:
        self.wen = Path(a1)
        self.ri = a2 or logging.getLogger("bridge.devices")
        self.suo = threading.RLock()
        self.she: dict[str, dict[str, Any]] = {}
        self._du()

    def _du(self) -> None:
        try:
            yuan = json.loads(self.wen.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            self.ri.warning("devices.json 读失败，按空表启动：%s", e)
            return
        if not isinstance(yuan, dict):
            self.ri.warning("devices.json 顶层不是对象，按空表启动")
            return
        huai = 0
        for x in yuan.get("devices") or []:
            ji_id = x.get("deviceId") if isinstance(x, dict) else None
            zhai = x.get("tokenHash") if isinstance(x, dict) else None
            # 类型检查要在正则之前，且必须查原值：`str()` 只喂给正则，存进
            # `self.she` 的仍是原值。只做正则的话「恰好 64 位的整数」能过筛，
            # 随后 `hmac.compare_digest(int, str)` 抛 TypeError——又是 500 而不是 401
            # （`ren()` 只承诺 ok/bad/revoked，不承诺不抛）。
            # 用 `fullmatch` 不用 `match`：后者配 `$` 会放过末尾的单换行。
            if (isinstance(ji_id, str) and JIA.fullmatch(ji_id)
                    and isinstance(zhai, str) and ZHAI.fullmatch(zhai)):
                self.she[ji_id] = x
            else:
                huai += 1
        if huai:
            # 降级要留痕。「静默 continue」在出问题时等于没有线索：设备连不上，
            # 日志里一个字都没有，只能靠猜。
            self.ri.warning("devices.json 有 %d 条记录形状不对，已跳过（这些设备要重新配对）",
                            huai)

    def _xie(self) -> None:
        """原子重写。临时文件 + `os.replace`。

        权限收紧要给 icacls 的 `M` 而不是 `RW` —— 阶段 5 的教训：
        `os.replace` 覆盖目标需要文件自身的 DELETE 位，只给 RW 会 WinError 5，
        而这不是崩溃而是静默失效（被上层的 except OSError 吞掉）。
        """
        tmp = self.wen.with_name(self.wen.name + ".tmp")
        try:
            self.wen.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps({"schemaVersion": 1, "devices": list(self.she.values())},
                           ensure_ascii=False, indent=2),
                encoding="utf-8")
            shou_quan(tmp)
            os.replace(tmp, self.wen)
        except OSError as e:
            self.ri.warning("devices.json 写失败：%s", e)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def jia(self, a1: str, a2: str, a3: str) -> dict[str, Any]:
        """配对一台设备。返回含明文 deviceToken 的记录——**这是它唯一一次出现**。

        deviceToken 内嵌 deviceId（`dt_<deviceId>_<hex>`），握手时 O(1) 查表。
        """
        with self.suo:
            ji_id = "dev-" + secrets.token_hex(6)
            ma = f"dt_{ji_id}_{secrets.token_hex(32)}"
            ji = {
                "deviceId": ji_id,
                "userId": a1,
                "label": a2,
                "tokenHash": _ha(ma),
                "pairedAt": int(time.time() * 1000),
                "lastSeenAt": 0,
                "instanceId": a3,
                "revoked": False,
            }
            self.she[ji_id] = ji
            self._xie()
            return {**ji, "deviceToken": ma}

    def zhao(self, a1: str) -> dict[str, Any] | None:
        with self.suo:
            return self.she.get(a1)

    def ren(self, a1: str) -> tuple[dict[str, Any] | None, str]:
        """按 deviceToken 认设备。返回 (记录, 原因)，原因 ∈ "ok"/"bad"/"revoked"。

        网关要按 401 与 403 分开回（401 = 令牌不对，403 = 设备已解绑）；但对
        客户端是同一件事——**都停止重连**（spec 6.5）。文案不区分失败细节，
        与 8.1 的防预言机精神一致。

        **先验 token 再判 revoked**，与 spec 6.1 的握手校验顺序（token→401、
        已解绑→403）一致。反过来写的话，知道 deviceId 的人拿任何垃圾 token
        都能问出「这台已解绑」——deviceId 不是秘密，它内嵌在 token 里。
        """
        bu = a1.split("_") if a1 else []
        if len(bu) != 3 or bu[0] != "dt":
            return None, "bad"
        ji = self.zhao(bu[1])
        if ji is None:
            return None, "bad"
        if not hmac.compare_digest(ji["tokenHash"], _ha(a1)):
            return None, "bad"
        if ji.get("revoked"):
            return None, "revoked"
        return ji, "ok"

    def jie(self, a1: str) -> bool:
        """解绑（15.5）：令牌立即失效。**不删记录**——前端要看得到「已解绑」。"""
        with self.suo:
            ji = self.she.get(a1)
            if ji is None or ji.get("revoked"):
                return False
            ji["revoked"] = True
            self._xie()
            return True

    def lie(self, a1: str | None = None) -> list[dict[str, Any]]:
        """设备列表。**绝不返回 tokenHash**（它等价于凭据本身）。"""
        with self.suo:
            return [
                {k: v for k, v in x.items() if k != "tokenHash"}
                for x in self.she.values()
                if a1 is None or x.get("userId") == a1
            ]

    def jian_shi(self, a1: str) -> None:
        with self.suo:
            ji = self.she.get(a1)
            if ji is not None:
                ji["lastSeenAt"] = int(time.time() * 1000)
                self._xie()


class PeiMa:
    """配对码表。**只存内存**——进程重启即全部作废，这是安全的默认（spec 8.1）。

    落盘的唯一收益是「重启后那 4 分钟还能用」，代价是多一个明文凭据文件。
    不值得。
    """

    def __init__(self, a1: float = PIAN) -> None:
        self.pian = a1
        self.suo = threading.RLock()
        self.biao: dict[str, dict[str, Any]] = {}

    def sheng(self, a1: str) -> dict[str, Any]:
        """生成一个一次性码，形如 `K4M-9QX`（两段，每段 MA_CHANG//2 位）。"""
        with self.suo:
            self.sao()
            ma = "-".join(
                "".join(secrets.choice(ZI) for _ in range(MA_CHANG // 2))
                for _ in range(2))
            dao = int(time.time() * 1000) + int(self.pian * 1000)
            self.biao[ma] = {"userId": a1, "expiresAt": dao, "used": False}
            return {"code": ma, "expiresAt": dao}

    def dui(self, a1: str) -> str | None:
        """用码换 userId。**命中即作废**——在返回之前标记，防重放竞态。"""
        with self.suo:
            self.sao()
            ma = (a1 or "").strip().upper()
            ji = self.biao.get(ma)
            if ji is None or ji["used"]:
                return None
            ji["used"] = True
            return str(ji["userId"])

    def sao(self) -> None:
        xian = int(time.time() * 1000)
        for k in [k for k, v in self.biao.items() if v["expiresAt"] <= xian]:
            self.biao.pop(k, None)
