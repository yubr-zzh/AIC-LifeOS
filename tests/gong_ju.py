"""测试等待助手：把「等多久」换成「等什么状态成立」。

存在的理由：本项目实测「`sleep(2.0)` 在 Windows 上必然 flake」——本机连一个
已关闭的回环端口要 2.05 秒才 refused。而死等固定时长还有另一半代价，方向相反
但要命得多：**窗口开始之后、睡满之前发生的什么都不会被发现**，于是用例从
「守行为」悄悄退化成「永远绿」——没有任何报错，没有任何红。

所以这里的原语全部锚在可观察状态上：

- `deng_dai`：轮询等条件成立；超时抛 `AssertionError`，并把「等到超时时条件
  是什么」带进消息，不静默通过。
- `wei_bian`：在一段时间里反复确认某个可观察值没变。测「做了 X 之后不该发生
  Y」用它——值一变立刻炸，不等满窗口，消息里带上变化前后的两个值。这比
  「睡满再断言一次」严：原来那种写法只看得见窗口末端那一个时刻。
- `duan_ke`：端口能不能连上。给「服务起来了吗」用，别再 sleep 猜。
- `jia_shi`：往被测模块注入一根可推进的假 `time.monotonic`。等「限流窗口过去
  多少秒」用这个——比真睡准（没有 Windows 上的毫秒级抖动），也比改被测对象
  内部时间戳可靠（那是把窗口整体平移，一条写死常量的退化实现照样能过）。

轮询间隔默认 10ms 量级：原来各处手写的 50ms / 200ms 轮询纯浪费墙钟时间。
只依赖标准库，没有引入 pytest 之外的东西。
"""

from __future__ import annotations

import contextlib
import socket
import time
from typing import Any, Callable

# **导入时就把真时钟抓住。** `jia_shi` 会临时改掉 `time.monotonic`，
# 本文件自己的等待不能被它一起冻住。
REAL = time.monotonic


def _miao_shu(msg: Any, val: Any) -> str:
    """把「等到超时时条件是什么」说出来。`msg` 收字符串或可调用对象。"""
    if callable(msg):
        return str(msg())
    if msg is not None:
        return str(msg)
    return repr(val)


def deng_dai(a1: Callable[[], Any], chao: float = 2.0, jian_ge: float = 0.01,
             msg: Any = None) -> None:
    """轮询等 `a1()` 返回真值；超时抛 `AssertionError`。

    `a1` 直接返回它等的那个对象（列表、状态值）时，默认消息就已经是有效信息；
    返回裸 bool 时用 `msg` 补一句状态（字符串或可调用对象）。
    """
    dead = REAL() + chao
    val: Any = None
    while True:
        val = a1()
        if val:
            return
        if REAL() >= dead:
            raise AssertionError(f"等了 {chao:g}s 条件仍未成立：{_miao_shu(msg, val)}")
        time.sleep(jian_ge)


def wei_bian(a1: Callable[[], Any], chao: float, jian_ge: float = 0.01,
             msg: Any = None) -> None:
    """在 `chao` 秒里反复确认 `a1()` 一直给出入口时那个值（「期间什么都没发生」）。

    一有变化立刻抛 `AssertionError`，不等满窗口。测不该发生的事就用它，
    别用 sleep 睡满再断言一次。
    """
    base = a1()
    dead = REAL() + chao
    while True:
        now = a1()
        if now != base:
            head = f"{chao:g}s 内可观察值变了：{base!r} → {now!r}"
            miao = _miao_shu(msg, now)
            raise AssertionError(f"{head}；{miao}" if miao else head)
        if REAL() >= dead:
            return
        time.sleep(jian_ge)


def duan_ke(a1: int) -> bool:
    """端口能不能连上。"""
    try:
        with socket.create_connection(("127.0.0.1", a1), timeout=0.5):
            return True
    except OSError:
        return False


@contextlib.contextmanager
def jia_shi(bu: Any):
    """往 `bu` 模块注入一根假 `time.monotonic`，yield 出的 `tui_jin` 负责推进。

    退出时恢复真时钟。等「限流窗口过去多少秒」这类等待用它：推进多少就是多少，
    没有 Windows 上 1.1 秒 sleep 的毫秒级抖动。
    """
    real = bu.time.monotonic
    tick = [REAL()]

    def tui_jin(a1: float) -> float:
        tick[0] += a1
        return tick[0]

    bu.time.monotonic = lambda: tick[0]
    try:
        yield tui_jin
    finally:
        bu.time.monotonic = real
