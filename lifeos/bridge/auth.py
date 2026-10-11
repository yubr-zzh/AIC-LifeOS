"""Bridge 的認證：token 校驗 + Origin 白名單（方案 5.3、7.4）。

token 是 32 位元組 hex，明文存在 runtime.json。泄漏它等同于「任何人都能在這台機器上
指揮 Agent」，所以校驗走常量時間比較，且 /health 之外的每個端點都要過這裡。
"""

from __future__ import annotations

import hmac
import secrets
from urllib.parse import urlparse

# 開發期可能出現的來源：Vite dev(5173) 與 Vite preview(4173)。
# 4173 必須在列——preview 模式的前端就是從 4173 發的，漏了它 SSE 會被 403 擋掉，
# 症狀是「開發時好好的、preview 時一直連不上」。
YUANDI = {
    "http://127.0.0.1:5173", "http://localhost:5173",
    "http://127.0.0.1:4173", "http://localhost:4173",
}

# 運行時注入的額外來源（方案 4.2.4）。打包態前端與主服務同源，Origin 是
# `http://127.0.0.1:<port>`——端口動態，模組常量表達不了，必須在裝配點
# （server.run / 桌面殼）調 `zhu_yuan()` 加進來。模組級集合而非換新表：
# `yuanbai()` 的既有調用點（http.py、測試）一行不用改。
E_WAI: set[str] = set()


def zhu_yuan(a1: str) -> None:
    """追加一條可信 Origin。打包態同源注入的唯一入口。"""
    if a1:
        E_WAI.add(a1)


def huo_yuan_bai() -> set[str]:
    """當前生效的白名單：開發期常量 + 運行時注入。"""
    return YUANDI | E_WAI


class WeiQuan(Exception):
    """認證失敗。code 區分 401 與 403。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def shengcheng() -> str:
    """生成一個新的 Bridge token（32 位元組 hex）。"""
    return secrets.token_hex(32)


def duanren(a1: str, a2: str | None) -> None:
    """校驗 token。無 token 或不匹配一律 401。用常量時間比較防時序側信道。"""
    if not a2:
        raise WeiQuan("unauthorized", "缺少 token")
    if not a1 or not hmac.compare_digest(a1, a2):
        raise WeiQuan("unauthorized", "token 不正確")


def yuanbai(a1: str | None, a2: set[str] | None = None) -> None:
    """校驗 Origin。缺失 Origin 放行（本地 curl 與服務端調用沒有 Origin）；
    有 Origin 卻不在白名單裡一律 403。"""
    if not a1:
        return
    bai = a2 if a2 is not None else huo_yuan_bai()
    if a1 not in bai:
        raise WeiQuan("forbidden", f"Origin 不在白名單內：{a1}")


def zhuanshi(a1: str) -> tuple[str, str]:
    """把可能帶路徑的 URL 還原成 scheme://host:port，用於 Origin 比較。"""
    jie = urlparse(a1)
    if not jie.scheme or not jie.netloc:
        return a1, a1
    return f"{jie.scheme}://{jie.netloc}", jie.path
