"""数据根目录的唯一解析入口（方案 4.2.3「.lifeos 根显式化」）。

打包态主进程 CWD 不可控（可能是 Program Files 或任意目录），继续用
相对 CWD 的 `.lifeos` 会把数据写进安装目录——普通用户无写权限，直接翻车。
所以全仓的根解析收口到这里：

1. `LIFEOS_HOME` 环境变量优先（桌面壳启动时指向 `%LOCALAPPDATA%\\.lifeOS`，
   双栈并存时也可各自指一个根）；
2. 缺省回落 `./.lifeOS`（开发形态；Windows 大小写不敏感，与历史 `.lifeos`
   同一目录，行为不变）。

**新代码一律 import 这里，不许再写死 `.lifeos` 字面量**；旧代码里带参数
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
    return Path(".") / ".lifeOS"


def qiao_gen(a1: str | Path | None = None) -> Path:
    """在数据根下取一个子路径。`qiao_gen("bridge")` = <根>/bridge。"""
    return gen_mulu().joinpath(a1) if a1 else gen_mulu()
