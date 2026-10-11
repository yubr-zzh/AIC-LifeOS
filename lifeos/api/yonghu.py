"""账户与会话（方案 6.1：本地单管理员 + PBKDF2 + 服务端会话）。

**两层信任边界（方案 5.2 的表述）**：登录体系管「键盘前的人」（用户层）；
bridge token 仍是设备级凭据（设备层），不因登录体系升级。本机其他进程
仍靠 CSRF + Origin 白名单约束——本模块不夸大威胁模型。

存储纪律：
- `accounts.json` 存 PBKDF2 哈希，绝不存口令本身；
- `sessions/<token_sha256>.json` **只存 token 的哈希**——盘上拿到文件也偷不走
  可用的会话（方案 6.1「存哈希不存原文」）；
- 全部走标准库（hashlib/secrets/hmac），零第三方依赖哲学不变。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from lifeos.api.dangqian import YongHuFeiFa, he_fa
from lifeos.storage.atomic import write_json

# PBKDF2 轮次。本地单机场景（攻击者需先拿到磁盘）下安全性足够（方案 6.1）。
PEI_ZHEN = 600_000
# 「记住我」会话有效期：30 天。不勾选则是会话 Cookie，关浏览器即失效。
JI_ZHU_MIAO = 30 * 24 * 3600
# 登录失败限速：连续 5 次失败锁 60 秒（方案 6.2，内存计数即可）。
CUO_SHANG_XIAN = 5
SUO_MIAO = 60

COOKIES_MING = "lifeos_session"

# 账户名允许的形态：与 dangqian.he_fa 同一套白名单——用户名将来要进路径
# 与日志，宁可开账时挡掉，不留「登录成功了才发现写不了盘」的形状。
ZI_FU = he_fa


class ZhangHuBiao:
    """accounts.json 的门面。线程安全：登录与改口令可能并发。"""

    def __init__(self, a1: str | Path):
        self.path = Path(a1)
        self._suo = threading.Lock()

    def _du(self) -> list[dict[str, Any]]:
        try:
            shu = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return shu if isinstance(shu, list) else []

    def _xie(self, a1: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.path, a1)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def kong(self) -> bool:
        """没有任何账户 = 未初始化（首启向导还没跑）。"""
        return len(self._du()) == 0

    @staticmethod
    def _ha_xi(a1: str, a2: bytes) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256", a1.encode("utf-8"), a2, PEI_ZHEN).hex()

    def _zhao(self, a1: str) -> dict[str, Any] | None:
        return next((x for x in self._du() if x.get("username") == a1), None)

    def chuang(self, a1: str, a2: str, a3: str = "admin") -> dict[str, Any]:
        """建账户。**首启幂等保护**：已有任何账户即拒绝（方案 6.2 setup 403）。"""
        try:
            he_fa(a1)
        except YongHuFeiFa as exc:
            # 模块边界统一成 ValueError：调用方（HTTP 端点）只捕这一种。
            raise ValueError(f"用户名不合法：{exc}") from exc
        if len(a2) < 8:
            raise ValueError("口令至少 8 位")
        with self._suo:
            if not self.kong():
                raise ValueError("已存在账户，不能重复初始化")
            yan = secrets.token_bytes(16)
            hu = {
                "username": a1,
                "pw_salt": yan.hex(),
                "pw_hash": self._ha_xi(a2, yan),
                "created_at": int(time.time()),
                "role": a3,
            }
            self._xie([hu])
            return {k: hu[k] for k in ("username", "created_at", "role")}

    def yan_zheng(self, a1: str, a2: str) -> bool:
        """口令校验。**统一失败语义**：用户不存在与口令不对都做一次哈希，
        耗时对齐，不给「用户名是否存在」留时间侧信道。"""
        with self._suo:
            hu = self._zhao(a1)
            if hu is None:
                self._ha_xi(a2, b"lifeos-decoy-salt")
                return False
            yan = bytes.fromhex(hu["pw_salt"])
            return hmac.compare_digest(hu["pw_hash"], self._ha_xi(a2, yan))

    def gai_kou_ling(self, a1: str, a2: str, a3: str) -> None:
        """改口令。验旧 → 写新。调用方负责吊销旧会话。"""
        if len(a3) < 8:
            raise ValueError("口令至少 8 位")
        with self._suo:
            hu = self._zhao(a1)
            if hu is None:
                raise KeyError(f"账户不存在：{a1}")
            yan = bytes.fromhex(hu["pw_salt"])
            if not hmac.compare_digest(hu["pw_hash"], self._ha_xi(a2, yan)):
                raise ValueError("旧口令不正确")
            hu["pw_salt"] = secrets.token_bytes(16).hex()
            hu["pw_hash"] = self._ha_xi(a3, bytes.fromhex(hu["pw_salt"]))
            self._xie(self._du())


class HuiHuaBiao:
    """服务端会话。文件名 = token 的 SHA-256，盘上无明文 token。"""

    def __init__(self, a1: str | Path):
        self.dir = Path(a1)
        self._suo = threading.Lock()

    @staticmethod
    def _zhi_wen(a1: str) -> str:
        return hashlib.sha256(a1.encode("utf-8")).hexdigest()

    def chuang(self, a1: str, a2: bool) -> str:
        """发新会话。**明文 token 只在这里返回一次**，此后只存哈希。"""
        ling = secrets.token_hex(32)
        hu = {
            "token_hash": self._zhi_wen(ling),
            "username": a1,
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + (JI_ZHU_MIAO if a2 else 12 * 3600),
            "remember": bool(a2),
        }
        with self._suo:
            self.dir.mkdir(parents=True, exist_ok=True)
            write_json(self.dir / f"{hu['token_hash']}.json", hu)
        return ling

    def zhao(self, a1: str | None) -> dict[str, Any] | None:
        """查会话。过期即删即 None——过期文件不清也会越攒越多。"""
        if not a1:
            return None
        wen = self.dir / f"{self._zhi_wen(a1)}.json"
        try:
            hu = json.loads(wen.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(hu, dict) or hu.get("expires_at", 0) < time.time():
            try:
                wen.unlink()
            except OSError:
                pass
            return None
        return hu

    def xiao(self, a1: str | None) -> bool:
        if not a1:
            return False
        with self._suo:
            wen = self.dir / f"{self._zhi_wen(a1)}.json"
            try:
                wen.unlink()
                return True
            except OSError:
                return False

    def xiao_qian_zhui(self, a1: str, a2: str) -> int:
        """按哈希前缀吊销本用户的会话（列表只展示前缀，吊销只能按前缀定位）。

        12 个 hex 字符做本机会话指纹足够；真撞上了就一起吊销——多吊一个
        会话无害，少吊一个才是事故。
        """
        n = 0
        with self._suo:
            for wen in self._huo_yue():
                if not wen.stem.startswith(a1):
                    continue
                try:
                    hu = json.loads(wen.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if hu.get("username") == a2:
                    wen.unlink(missing_ok=True)
                    n += 1
        return n

    def chu_yong_hu_wai(self, a1: str, a2: str) -> int:
        """吊销某用户除当前会话外的全部会话（改口令时用，方案 6.2）。"""
        dang = self._zhi_wen(a2) if a2 else None
        n = 0
        with self._suo:
            for wen in self._huo_yue():
                try:
                    hu = json.loads(wen.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if hu.get("username") == a1 and hu.get("token_hash") != dang:
                    wen.unlink(missing_ok=True)
                    n += 1
        return n

    def lie_chu(self, a1: str | None = None) -> list[dict[str, Any]]:
        """活跃会话列表。**不含任何 token 形态**，只给可展示字段。"""
        with self._suo:
            out = []
            for wen in self._huo_yue():
                try:
                    hu = json.loads(wen.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                out.append({
                    "tokenHash": hu.get("token_hash", "")[:12],
                    "username": hu.get("username"),
                    "created_at": hu.get("created_at"),
                    "expires_at": hu.get("expires_at"),
                    "current": a1 is not None and hu.get("token_hash") == self._zhi_wen(a1),
                })
            return out

    def _huo_yue(self) -> list[Path]:
        self.dir.mkdir(parents=True, exist_ok=True)
        return sorted(self.dir.glob("*.json"))


# ---- 登录失败限速（方案 6.2：连续 5 次失败锁定 60 秒，内存计数）----

_CUO: dict[str, list] = {}
_CUO_SUO = threading.Lock()


def suo_yu(a1: str) -> float:
    """该用户名还剩多少秒解禁。0 = 未锁。

    **只在锁已真的设置过（xiang[1] > 0）且过期时才清条目。** 未触锁时的
    条目是「失败计数进行中」——每次登录尝试都先来这里查，查一次就清一次
    的话，计数永远到不了 5，锁定形同虚设。
    """
    with _CUO_SUO:
        xiang = _CUO.get(a1)
        if not xiang:
            return 0.0
        yu = xiang[1] - time.monotonic()
        if yu <= 0:
            if xiang[1] > 0:
                _CUO.pop(a1, None)
            return 0.0
        return yu


def ji_cuo(a1: str) -> bool:
    """记一次失败。返回 True 表示刚刚触发了锁定。"""
    with _CUO_SUO:
        xiang = _CUO.setdefault(a1, [0, 0.0])
        xiang[0] += 1
        if xiang[0] >= CUO_SHANG_XIAN:
            xiang[1] = time.monotonic() + SUO_MIAO
            xiang[0] = 0
            return True
        return False


def ji_dui(a1: str) -> None:
    """登录成功清零。"""
    with _CUO_SUO:
        _CUO.pop(a1, None)


# ---- 装配（照 bridge_admin.zhuang 的模式：测试与 server.run() 都从这里进）----

ZH: ZhangHuBiao | None = None
HH: HuiHuaBiao | None = None


def zhuang(a1: ZhangHuBiao, a2: HuiHuaBiao) -> None:
    global ZH, HH
    ZH = a1
    HH = a2


def yi_qi_yong() -> bool:
    """登录闸是否生效。**未初始化不设闸**——本地开发形态与既有测试一行不改；
    首启向导建了账户，闸自动落下（方案 6.2 中间件收口规则）。"""
    return ZH is not None and HH is not None and not ZH.kong()


def _zhang() -> ZhangHuBiao:
    if ZH is None:
        raise RuntimeError("账户表尚未装配（yonghu.zhuang）")
    return ZH


def _hui() -> HuiHuaBiao:
    if HH is None:
        raise RuntimeError("会话表尚未装配（yonghu.zhuang）")
    return HH
