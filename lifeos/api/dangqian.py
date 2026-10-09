"""当前用户是谁 —— 全项目唯一入口（spec 11.1 的占位实现）。

**这个文件是「占位 userId」方案的落点。** 现在没有登录体系，uid 从环境变量来；
接入登录后只改 `dang_qian_yong_hu()` 一个函数，其余调用点一行不动。

uid 会拼进 CLAUDE_CONFIG_DIR 的路径（11.2），**所以它必须校验**：今天是环境变量
（不是外部输入），但接入登录后它来自 cookie——那时它就是外部输入，
这条校验必须在接入之前就位（spec 11.4、风险 8）。
"""

from __future__ import annotations

import os
import re

# 与 bridge/cun.py 的 sid 校验同一个形状：只允许能安全进路径的字符。
#
# **`\A...\Z` 而不是 `^...$`**（阶段 6 修复轮 2，承重 2）：Python 的 `$` 在
# `re.MULTILINE` 关闭时**仍允许匹配最后一个换行符之前的位置**，于是
# `"alice\n"`、`"..\n"`、`".\n"` 全都判为合法——本机真机验证过。
# 后果不是路径穿越（Windows 上 mkdir 拒收带换行的路径，WinError 123），
# 而是**白名单的第一道形变失效**：任何后续依赖「uid 里不可能有换行」的推理
# 都不成立，且 `"..\n"` 在 POSIX 上会被内核归一化到父目录。
# 锚点从 `^…$` 换成 `\A…\Z` 是唯一的修法，`strip()` 之类的补丁挡不住
# 中间位置的换行。
HE_FA = re.compile(r"\A[A-Za-z0-9_.-]{1,64}\Z")


class YongHuFeiFa(Exception):
    """userId 不能安全地拼进路径。"""


def he_fa(a1: str) -> str:
    """校验 userId。不合法抛 YongHuFeiFa。

    `.` 与 `..` 单独挡掉：正则本身不允许它们单独成立以外的形态
    （`.` 匹配得上 `^[A-Za-z0-9_.-]{1,64}$`），但拼路径时它们指向父目录。
    """
    if not a1 or a1 in (".", "..") or not HE_FA.match(a1):
        raise YongHuFeiFa(f"非法 userId：{a1!r}")
    return a1


def dang_qian_yong_hu() -> str:
    """当前用户 id。占位实现：读 LIFEOS_USER，默认 "local"。

    默认值是「变量缺席」才给，**不是**「值为空也给」：`or "local"` 会把显式设成
    空串的 LIFEOS_USER 静默当成 local（配置写错却当成正常启动），而空串正是
    `he_fa` 明确要挡的非法值。设了就给 `he_fa`，让它自己拒。
    """
    return he_fa(os.environ.get("LIFEOS_USER", "local"))
