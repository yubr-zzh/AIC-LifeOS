"""Agent 适配器层（方案 9）与注册表（9.1 的 adapters/registry.py）。

注册表就是一个 dict。加一个新 Agent = 写一个文件 + 在这里加一行。
"""

from lifeos.bridge.adapters.base import AgentAdapter
from lifeos.bridge.adapters.claude_code import ClaudeCodeAdapter
from lifeos.bridge.adapters.codex import CodexAdapter
from lifeos.bridge.adapters.echo import EchoAdapter
from lifeos.bridge.adapters.hermes import HermesAdapter
from lifeos.bridge.adapters.kimi import KimiAdapter
from lifeos.bridge.adapters.liu_xing import LiuXingAdapter
from lifeos.bridge.adapters.opencode import OpencodeAdapter
from lifeos.bridge.adapters.pi import PiAdapter

ZHU_CE_QI: dict[str, type[AgentAdapter]] = {
    ClaudeCodeAdapter.agentId: ClaudeCodeAdapter,
    CodexAdapter.agentId: CodexAdapter,
    PiAdapter.agentId: PiAdapter,
    KimiAdapter.agentId: KimiAdapter,
    OpencodeAdapter.agentId: OpencodeAdapter,
    HermesAdapter.agentId: HermesAdapter,
    EchoAdapter.agentId: EchoAdapter,
}

__all__ = ["AgentAdapter", "ClaudeCodeAdapter", "CodexAdapter", "PiAdapter",
           "LiuXingAdapter", "KimiAdapter", "OpencodeAdapter", "HermesAdapter",
           "EchoAdapter", "ZHU_CE_QI"]
