"""Agent 适配器层（方案 9）与注册表（9.1 的 adapters/registry.py）。

注册表就是一个 dict。加一个新 Agent = 写一个文件 + 在这里加一行。
"""

from lifeos.bridge.adapters.base import AgentAdapter
from lifeos.bridge.adapters.claude_code import ClaudeCodeAdapter
from lifeos.bridge.adapters.echo import EchoAdapter

ZHU_CE_QI: dict[str, type[AgentAdapter]] = {
    ClaudeCodeAdapter.agentId: ClaudeCodeAdapter,
    EchoAdapter.agentId: EchoAdapter,
}

__all__ = ["AgentAdapter", "ClaudeCodeAdapter", "EchoAdapter", "ZHU_CE_QI"]
