"""AgentAdapter 抽象接口（方案 9.1/9.2）。

适配器只负责「把一条指令变成 Agent 的一轮执行，并把过程事件交给回调」。
它不碰会话状态、不做权限判定——那些是 session.py 与 planner_guard.py 的事。

生命周期与 chat 无关，只有三件事因 Agent 而异：**怎么跑、怎么问权限、怎么问问题。**
"""


class AgentAdapter:
    """所有 Agent 适配器的基类。加一个新 Agent 只需要继承并实现 fasong。"""

    agentId = "base"
    label = "Base"
    # 适配器所在的 event loop。Bridge 要靠它把 interrupt() 调度回正确的循环，
    # 在别的 loop 上调用等于对一条已经关闭的流写入。
    loop = None

    @staticmethod
    def fangquan() -> bool:
        """能否接管权限。False 时 Bridge 必须拒绝创建会话并说明原因。"""
        return False

    @staticmethod
    def wenti2() -> bool:
        """能否接管提问。False 时 AskUserQuestion 降级为纯文本（并在 UI 标注）。"""
        return False

    async def tanjian(self) -> dict:
        """探测本机是否可用，返回 {available, version, sdkVersion, error}。

        **绝不能抛异常**：探测失败本身就是要报告给用户的数据。
        """
        return {"available": False, "version": None, "sdkVersion": None,
                "error": "该适配器没有实现可用性探测"}

    async def kaishi(self, a1: dict) -> None:
        """建立底层连接。a1 含 cwd、permissionMode、settingSources 等。"""
        raise NotImplementedError

    async def fasong(self, a1: str) -> dict:
        """执行一条指令，等这一轮跑完。返回本轮结果摘要。"""
        raise NotImplementedError

    async def zhong_duan(self) -> None:
        """中断当前执行。"""
        raise NotImplementedError

    async def guan_bi(self) -> None:
        """关闭连接并回收子进程。"""
        raise NotImplementedError
