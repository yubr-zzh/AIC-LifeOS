"""数据根目录的唯一解析入口。

用户数据默认落在工作目录下的 `./lifeOS`。桌面壳会把工作目录固定为用户
工作目录，并通过 `LIFEOS_HOME` 传入完整根路径；开发和测试形态则直接
回落到当前工作目录。

1. `LIFEOS_HOME` 环境变量优先（桌面壳与测试的显式根）；
2. 缺省回落 `./lifeOS`。

**新代码一律 import 这里，不许再写死旧数据目录名**；旧代码里带参数
默认值的（memory/sqlite/skills 等）在打包装配点显式传参，不在各默认值处
分叉第二套解析。
"""

from __future__ import annotations

import os
from pathlib import Path


def gen_mulu() -> Path:
    """LifeOS 数据根。见模块 docstring。"""
    home = os.environ.get("LIFEOS_HOME")
    if home:
        return Path(home)
    xin = Path(".") / "lifeOS"
    jiu = Path(".") / ".lifeOS"
    return jiu if jiu.exists() and not xin.exists() else xin


def qiao_gen(a1: str | Path | None = None) -> Path:
    """在数据根下取一个子路径。`qiao_gen("bridge")` = <根>/bridge。"""
    return gen_mulu().joinpath(a1) if a1 else gen_mulu()
