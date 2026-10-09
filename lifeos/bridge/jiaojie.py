"""Bridge 对外的「进入方式」（spec 7.3、7.4）。

本设计选的是**回环转发**：隧道模式下 Bridge 照常跑自己的 127.0.0.1 HTTP 服务，
`tunnel.py` 只做「WS 消息 ↔ 本地 HTTP」的搬运。所以这一层不是方案 9.5 画的那个
会拆开 handler 的 Transport，而是一个**极薄的注册点**——两个实现共享同一个
已经在跑的 `BridgeServer`，`localbus` 就是它本身。
"""

from __future__ import annotations

from typing import Any


class JiaoJie:
    """一条进入方式。实现只需三个方法。

    **构造契约是双参 `(已经在跑的 BridgeServer, 配置字典)`**，由 `xuan()` 统一调用。
    基类自己实现了它，实现可以不写 `__init__`。
    """

    def __init__(self, a1: Any = None, a2: Any = None) -> None:
        self.fu = a1
        self.cfg = a2

    def qi_dong(self) -> None:
        raise NotImplementedError

    def ting_zhi(self) -> None:
        raise NotImplementedError

    def zhuang_tai(self) -> str:
        """``"local"`` | ``"connecting"`` | ``"connected"`` | ``"error"``。"""
        raise NotImplementedError


class BenDi(JiaoJie):
    """localbus：Bridge 自己的 127.0.0.1 HTTP 服务（方案 9.5 的本地直连形态）。

    **空操作是刻意的**：这个服务由 `run.py` 的 `zhen_ben()` 起好了，构造参数
    （`self.fu`）就是它。启动/停止在这里再动一次会把它关掉或起第二遍。
    """

    def qi_dong(self) -> None:
        return

    def ting_zhi(self) -> None:
        return

    def zhuang_tai(self) -> str:
        return "local"


ZHU_CE: dict[str, type[JiaoJie]] = {"local": BenDi}


def zhu_ce(a1: str, a2: type[JiaoJie]) -> None:
    ZHU_CE[a1] = a2


def xuan(a1: str, a2: Any, a3: dict[str, Any]) -> JiaoJie:
    """按名字选实现。名字不认识抛 ValueError。

    **不静默降级成 local**：用户配了 `LIFEOS_JIAOJIE=tunnel` 而实现没注册时
    悄悄退回本机直连，症状是「配了隧道却在裸奔」——那比直接起不来更危险。
    """
    cls = ZHU_CE.get(a1)
    if cls is None:
        raise ValueError(f"未知的 JIAOJIE 类型：{a1!r}（可用：{sorted(ZHU_CE)}）")
    jie = cls(a2, a3)
    # 承重契约：xuan() 传进来的这两个对象，实现必须原样挂在 fu / cfg 上。
    # 不钉的话，实现改了属性名（或干脆忘了调 `super().__init__()`）整套件照样绿，
    # 只在真机上用到它的那个路径上炸成 None——那时已经晚了。
    # 用 getattr 而不是 jie.fu：属性根本不存在时要抛的是这一条 AssertionError，
    # 而不是更难读的 AttributeError。
    assert getattr(jie, "fu", None) is a2 and getattr(jie, "cfg", None) is a3, (
        f"{cls.__name__} 没有守住 JiaoJie 的 fu/cfg 契约")
    return jie
