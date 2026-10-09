"""统一时间接口：写时带 UTC 时区，读时归一成 aware UTC。

这个模块只解决一件事——**落盘的时间戳不能有两种时区语义**。

历史事实：`lifeos/` 下所有写入点用的是 `datetime.utcnow().isoformat()`，写出
的是 **naive** 字符串（不带时区）。这样的值和有 `Z` 或 `+02:00` 的值混在
同一个文件里时，`datetime.now(timezone.utc) - fromisoformat(旧值)` 会抛
`TypeError: can't subtract offset-naive and offset-aware datetimes`。
**它不是 `ValueError`**，所以 `except ValueError` 接不住，整个事件总线在
读文件那一刻就炸。

于是定下两条纪律，生产写入点一处不留地遵守：

1. 写：一律 `xie_shi()`，产出带 `+00:00` 的 ISO 8601。
2. 读：一律 `du_shi()`，把 naive 当 UTC、aware 换算到 UTC，产出 aware 对象；
   解析不出来返回 `None`，由调用方按「不可信」处理。

**旧落盘值不批量改写。** 数据迁移是后续单独立项的事：批量重写用户数据而没有
备份，风险远大于收益。这里的做法是让读取侧长期兼容两种形态——兼容窗口持续
到迁移单独立项为止。

`du_shi()` 的返回类型是 `datetime | None`，**永远是 aware 的**。调用方拿它和
`xie_shi()` 或 `datetime.now(timezone.utc)` 相减才是安全的；`None` 必须单独
处理，不许直接参与减法。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

__all__ = ["xie_shi", "du_shi"]


def xie_shi() -> str:
    """当前 UTC 时刻的 ISO 8601 字符串，**带 `+00:00` 时区**。

    用 `datetime.now(timezone.utc)` 而不是 `utcnow()`：后者在 3.12 起被标记
    弃用，且返回 naive 对象——正是本模块要消灭的那种值。
    """
    return datetime.now(timezone.utc).isoformat()


def du_shi(a1: Any) -> Optional[datetime]:
    """任意落盘时间值 → aware UTC 的 `datetime`；解析不出来返回 `None`。

    三种输入形态各有各的处置：

    - **naive**（`2026-09-30T12:00:00`）——历史 `utcnow()` 写出来的就是它，
      按 UTC 解释。
    - **aware**（`...Z` / `...+02:00`）——换算到 UTC 存。
    - **其它**（空串、`None`、非字符串、非法字符串）——返回 `None`。

    **非字符串一律判非法，包括数字。** 落盘字段的契约是 ISO 8601 字符串，
    一个整数出现在这里只可能是别处写错了。猜它是 epoch 秒等于把写错的数据
    猜成对的，而猜中的话那个值还会落在保留期内，让该淘汰的事件永远留着。

    空格分隔（`2026-09-30 12:00:00`）不需要额外处理：Python 3.11 起的
    `fromisoformat` 已经接受它，3.13 连 `Z` 后缀也认。这里仍保留一次
    `str()` 归一，是为了让 `bytes` 也能进来——它同样是「不是字符串就判非法」
    之外唯一合理的形态。
    """
    if isinstance(a1, bytes):
        try:
            a1 = a1.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(a1, str):
        return None
    fan = a1.strip()
    if not fan:
        return None
    try:
        at = datetime.fromisoformat(fan)
    except ValueError:
        return None
    # naive 一律按 UTC 解释（历史值都是 utcnow 写的）；aware 换算到 UTC。
    # 换算不是抹掉偏移量：把 `14:00+02:00` 当成 `14:00Z` 会让它比真实时刻
    # 早 2 小时，那不是格式兼容，是提前两小时把事件判定为超期然后删掉。
    if at.tzinfo is None:
        return at.replace(tzinfo=timezone.utc)
    return at.astimezone(timezone.utc)
