"""隧道协议的可执行契约（spec 6.2）。

六种消息、五条规则原先只活在 spec 6.2 的散文和代码里的长注释中，实现侧唯一的
校验是 `tunnel_gw.jie()`——只查「是不是合法 JSON、是不是 dict、`t` 是不是 str」。
字段全靠调用方各自防御：`_deng_hui` 四个字段四套 `int()/dict()/str()/bool()`，
三处 `id` 读成 `str(x.get("id") or "")`。**后者是安静的那一种坏**——id 缺失就
静默变成空串，查表查不到就丢帧，无日志、无报错、在途名额还占着。同一个形状
在阶段 6 出了六次，每次都要靠一次修复轮加一次人工变异验证才堵住。

本层把字段的解析与校验集中到一处，对外只四个入口：

| 入口 | 管什么 |
|---|---|
| `jie_qiu` | 解「云端 → Bridge」的 `request`，六键全验 |
| `jie_ying` | 解「Bridge → 云端」的 `response`，五键全验 |
| `zhi_qiu` | 构造一个**必然合法**的 `request`（网关出口唯一一条路） |
| `he_hao` | `requestId` 形状。`frame` / `close` 只过这一道 + 调用方判载荷类型 |

**`id` 为什么卡正则**：今天 id 只由网关生成，攻击者造不出；但 11.1 明写接入
登录后它就是可被外部触发的路径。未知/畸形 id 一律拒绝、不降级——这是参考实现
（clawd-on-desk）复盘 11.2 的纪律，而「静默按空串查表后丢弃」正是它的反面。

**边界两条，别越界**：

1. `tunnel_gw.jie()` 保留不动，它管「是不是合法 JSON dict、`t` 是不是 str」
   这一层；本层只管字段。
2. `Dui.deng` 队列里流转的 `{"t": "frame"}` / `{"t": "__end__"}` 是**进程内
   私有协议**，由 `_fen_fa` 自己 `put_nowait`、`Liu.zhen` 自己取，从不跨网络。
   它不过本层——为「统一」把它塞进来只会把隧道协议和队列协议混成一个概念。

线格式仍是 JSON dict（用户 2026-09-29 裁定）：本层只解析/校验/构造，不做序列化
替换。`Qiu` / `Ying` 是校验后的**视图**，不是新的线格式。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

# spec 6.2：`id` 由网关分配（`"r-" + secrets.token_hex(4)`），一条隧道内唯一。
HAO = re.compile(r"^r-[0-9a-f]{8}$")
# `request` 除 `id` 外的五个键，也是 `zhi_qiu` 出口认的全部字段（spec 6.2）。
ZHU = ("method", "path", "query", "headers", "body")
_LOG = logging.getLogger("bridge.xie_yi")


class XieYiCuoWu(Exception):
    """契约违背。带 `code` / `message`，供调用方记日志或映射成对外的错误。"""

    def __init__(self, a1: str, a2: str) -> None:
        super().__init__(a2)
        self.code = a1
        self.message = a2


@dataclass(frozen=True)
class Qiu:
    """一条 `request`（云端 → Bridge）。字段与 spec 6.2 一字对应。"""

    id: str
    method: str
    path: str
    query: str
    headers: dict[str, str]
    body: str | None


@dataclass(frozen=True)
class Ying:
    """一条 `response`（Bridge → 云端）。"""

    id: str
    status: int
    headers: dict[str, str]
    body: str
    b64: bool


def he_hao(a1: Any) -> bool:
    """`requestId` 形状。非字符串、空串、多一位少一位、非 hex 一律 False。"""
    return isinstance(a1, str) and HAO.match(a1) is not None


def jie_qiu(a1: dict[str, Any]) -> Qiu:
    """解一条 `request`。六键齐全、各合其规，任何不合即抛 `XieYiCuoWu`。

    **多出来的键容忍**（不认也不用）：协议加字段时旧的一端不该因此全线断开，
    本层只认 spec 6.2 列出的这几个；出口只发这六个由 `zhi_qiu` 保证。
    """
    rid = _yao(a1, "id")
    if not he_hao(rid):
        raise XieYiCuoWu("bad_id", "id 不是 r- 加 8 位 hex")
    return Qiu(id=rid,
               method=_zi(_yao(a1, "method"), "method"),
               path=_lu(_yao(a1, "path"), "path"),
               query=_zi(_yao(a1, "query"), "query"),
               headers=_tou(_yao(a1, "headers"), "headers"),
               body=_kong(_yao(a1, "body"), "body"))


def jie_ying(a1: dict[str, Any]) -> Ying:
    """解一条 `response`。`status` 可 `int()`——对端可能发 `"200"`。

    **`body: null` 是守恒，其余四个键是有意收紧。** 改前缺键与假值会被
    `x.get(k) or 默认`、`str()`、`bool()` 兜底照走（缺 `b64` 就当成 False、
    `headers` 是二元组 list 就 `dict()` 硬转），现在缺一即拒、形状不对即拒。
    收紧是对外行为变更——`tunnel.py` 三条 response 构造路径五个键恒在，故实际
    无回归；由 `tests/test_gw_route.py` 的缺键用例**显式钉住**，否则将来谁嫌
    严把它放宽，没有任何测试会发现。
    """
    rid = _yao(a1, "id")
    if not he_hao(rid):
        raise XieYiCuoWu("bad_id", "id 不是 r- 加 8 位 hex")
    return Ying(id=rid,
                status=_shu(_yao(a1, "status"), "status"),
                headers=_tou(_yao(a1, "headers"), "headers"),
                # `body: null` 按空体收：改前是 `str(x.get("body") or "")`，
                # 反代拿到 body 就 `len()` + `write()`，给它 None 会让那条路炸。
                body=_kong(_yao(a1, "body"), "body") or "",
                b64=_bu(_yao(a1, "b64"), "b64"))


def zhi_qiu(a1: str, a2: dict[str, Any]) -> dict[str, Any]:
    """构造一条 `request`（网关出口）。造完回头用自己的 `jie_qiu` 验一遍，
    所以**出口不可能发出不合法的东西**（往返守恒）。

    调用方多带的键一律丢掉：带上隧道就是给协议加字段，那要两端一起改
    （6.2 的五条规则），不能由一端单方面塞。键序与改前的
    `zhen("request", id=rid, **a2)` 一致——线上字节不变（Ruling 1）。

    **丢键要出声。** 静默丢弃与本任务要消灭的失败模式同源（`id` 缺失静默变成
    空串那次），所以丢几个就 warning 记下哪几个。今天恒不触发（反代两个调用点
    传的都是同一个模板 dict），明天有人踩了有日志可查。
    """
    if not he_hao(a1):
        raise XieYiCuoWu("bad_id", "网关分配的 id 不合格式")
    wen: dict[str, Any] = {"t": "request", "id": a1}
    wen.update({k: a2[k] for k in ZHU if k in a2})
    diao = [k for k in a2 if k not in ZHU]
    if diao:
        _LOG.warning("request 丢掉不在 spec 6.2 里的键：%s", sorted(diao))
    jie_qiu(wen)      # 自检。过不去就直接抛，别造出一条半边消息
    return wen


# ---------- 字段判据（ spec 6.2 的规则逐条落成代码 ） ----------

def _yao(a1: dict[str, Any], a2: str) -> Any:
    """取一个必须存在的键。缺键即违背——**没有「缺了按空串」这条路**。"""
    if a2 not in a1:
        raise XieYiCuoWu("missing_field", f"缺少字段 {a2}")
    return a1[a2]


def _zi(a1: Any, a2: str) -> str:
    if not isinstance(a1, str):
        raise XieYiCuoWu("bad_type", f"{a2} 不是字符串")
    return a1


def _kong(a1: Any, a2: str) -> str | None:
    """字符串或 null。`GET` 的 `body` 就是 null（`_da` 照这个分支不发体）。"""
    if a1 is None or isinstance(a1, str):
        return a1
    raise XieYiCuoWu("bad_type", f"{a2} 既不是字符串也不是 null")


def _lu(a1: Any, a2: str) -> str:
    x = _zi(a1, a2)
    if not x.startswith("/"):
        raise XieYiCuoWu("bad_path", f"{a2} 不是以 / 开头的路径")
    return x


def _tou(a1: Any, a2: str) -> dict[str, str]:
    """6.2 第 4 条：`headers` 是字符串到字符串的字典。list / 值不是字符串都拒。

    **返回副本，不是输入本身**：`@dataclass(frozen=True)` 只冻槽位，冻不住 dict
    内容。把调用方的映射原样交出去，谁在拿到之后 `pop` 一下就改掉了别人的消息。
    """
    if not isinstance(a1, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in a1.items()):
        raise XieYiCuoWu("bad_headers", f"{a2} 不是 dict[str, str]")
    return dict(a1)


def _shu(a1: Any, a2: str) -> int:
    """可 `int()`。字符串数字照收（对端可能发 `"200"`），其余一律拒。

    **`bool` 单独拒**：`isinstance(True, int)` 在 Python 里成立，`int(True)`
    就成了 1，于是一个 `status: true` 会被当成「201 Created」原样搬给浏览器。
    """
    if isinstance(a1, bool):
        raise XieYiCuoWu("bad_status", f"{a2} 不是数字")
    try:
        return int(a1)
    except (TypeError, ValueError):
        raise XieYiCuoWu("bad_status", f"{a2} 不是数字") from None


def _bu(a1: Any, a2: str) -> bool:
    if not isinstance(a1, bool):
        raise XieYiCuoWu("bad_type", f"{a2} 不是布尔")
    return a1
