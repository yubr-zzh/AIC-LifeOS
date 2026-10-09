"""Bridge 侧唯一的脱敏实现（方案 10.7）。

Agent 的输出里可能混进 .env 内容、token、私钥。这些内容进日志、进 LifeOS
上下文 = 进 LLM token = 一次外泄。所以 Bridge 上所有要外吐字符串的地方
（出站事件、日志）都必须经过这里，且**先脱敏再截断**——先截断会让正则
看不到跨界的密钥。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# 单条摘要进上下文/日志的字符上限。
CHANG = 2000

_BAN = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "sk-***"),
    # 方案 10.7 列的四种里，本地实现原先漏了 GitHub token 与 AWS key id
    (re.compile(r"ghp_[A-Za-z0-9]{16,}"), "ghp_***"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AKIA***"),
    # [=:] 同时覆盖等号与冒号两种分隔，所以 token= / password: 都拦得住
    (re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd)\s*[=:]\s*\S+"),
     r"\1=***"),
    (re.compile(r"(?i)Bearer\s+[A-Za-z0-9._\-]{16,}"), "Bearer ***"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
                re.S), "***私钥已抹除***"),
]


def tuomi(a1: Any, a2: int = CHANG) -> str:
    """脱敏 + 截断。顺序不能反：先截断会让正则看不到跨界的密钥。"""
    if a1 is None:
        return ""
    wen = a1 if isinstance(a1, str) else json.dumps(a1, ensure_ascii=False, default=str)
    # 绝对家目录路径。只做字面替换、不写正则：路径里的反斜杠在正则里要转义，
    # 而 Windows 上同一个路径有 C:\ 与 C:/ 两种写法，逐一手写转义更容易漏。
    jia = str(Path.home())
    if jia and len(jia) > 3:
        wen = wen.replace(jia, "~").replace(jia.replace("\\", "/"), "~")
    for x, y in _BAN:
        wen = x.sub(y, wen)
    if len(wen) > a2:
        wen = wen[:a2] + "…（已截断）"
    return wen
