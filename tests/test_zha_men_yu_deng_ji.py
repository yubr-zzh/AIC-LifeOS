"""闸门 0（知情同意）、pid 登记、pi 环境净化——v3.0 补漏的三个承重锁定。

## 闸门 0：`acknowledgeNoApproval`

kimi / opencode / hermes 在非交互模式下**没有 Bridge 能接管的审批回路**
（`fangquan() == False`），指令会不经审批直接在本机执行。旧代码建会话时
对这件事一声不吭——用户从 LifeOS 点出去，还以为跟 claude 一样步步有审批。
`http._jian_hui` 现在要求请求体带 `acknowledgeNoApproval: true`，否则
400 `agent_unavailable` 并说明原因。

⚠ 判定是严格的 `is not True`：字符串 `"true"`、数字 `1` 都不算数。
知情同意是布尔承诺，不能被 JS 的真值语义冒充——否则前端随手塞个
`"false"` 字符串都会被当成同意。

## pid 登记

一次性进程每条指令 spawn 一个新进程，`kaishi()` 里不 spawn（`chuan_shu.py`
的 `if not self.yi_ci_xing`）⇒ `xin_jian` 那次 `qu_pid()` 采样对它们恒为
None ⇒ 旧代码里它们的 pid 从不进 runtime.json，Bridge 被强杀时正在跑回合
的子进程变孤儿。修复分三截，各有各的锁：

1. `LiuXingAdapter._bao_pid`：spawn **成功后**才回调——spawn 抛异常那行
   走不到，runtime.json 里不会有幽灵 pid；
2. `http.xin_jian` 给带 `pid_hui` 槽位的适配器注入回调（默认参数绑死
   会话 id），`LiuXingAdapter.__init__` 的 `pid_hui = None` 就是槽位信号；
3. `http.lu_pid` 同会话换 pid 时**替换**旧条目——旧进程此刻已退出，
   条目留着只会让 `sao_bing` 空转、runtime.json 越攒越长。

## pi 的环境净化

pi 复用宿主 shell 里的 `ANTHROPIC_*`（代理/token）时会被带进子进程，
pi 按它找端点 ⇒ L-C 概率红的根因。`pi._huan_jing` 把**非显式给的**
`ANTHROPIC_*` 全部摘除；显式经 `env` 传的键说了算，照常保留。
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import threading
import unittest
import urllib.request
import uuid
from pathlib import Path
from unittest import mock

from lifeos.bridge import auth
from lifeos.bridge.adapters import AgentAdapter
from lifeos.bridge.adapters.liu_xing import LiuXingAdapter
from lifeos.bridge.adapters.pi import PiAdapter
from lifeos.bridge.events import ZongXian
from lifeos.bridge.http import BridgeServer
from lifeos.bridge.planner_guard import ShenKa
from lifeos.bridge.session import HuiHua

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _duan_kou() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class MeiHuiLu(AgentAdapter):
    """**没有审批回路**的假适配器：kimi/opencode/hermes 在 `-p` 模式下的形状。

    闸门 0 的承重样本。echo 是模拟 claude-code 的**带回路**替身
    （`fangquan() == True`），走不到闸门 0——所以这条 400 路径必须
    用一个真没有回路的假适配器来测。
    """

    agentId = "meiHuiLu"
    label = "无回路假适配器"
    MOSHI_ZI = frozenset({"manual"})
    dui_hui_id = "huiId"
    yi_ci_xing = False

    @staticmethod
    def fangquan() -> bool:
        return False

    @staticmethod
    def wenti2() -> bool:
        return False

    async def kaishi(self, a1):
        self.moshi = a1.get("permissionMode", "manual")

    async def fasong(self, a1):
        return {"resultText": f"ok:{a1}", "isError": False}

    async def zhong_duan(self):
        pass

    async def guan_bi(self):
        pass


class JiaYiCi(LiuXingAdapter):
    """一次性进程假适配器：验「spawn 后回调 → lu_pid」这条链。

    `LiuXingAdapter.__init__` 自带 `pid_hui = None` 槽位，`yi_ci_xing = True`
    ⇒ `kaishi()` 不 spawn ⇒ `xin_jian` 的 `qu_pid()` 采样拿不到 pid——
    唯一的登记路径就是注入的回调，正是要锁的东西。
    """

    agentId = "jiaYiCi"
    label = "一次性假适配器"
    MOSHI_ZI = frozenset({"manual"})
    ZHI_LING = ["jia-yi-ci-cli"]

    @staticmethod
    def fangquan() -> bool:
        return False


def _jia_jin(pid: int) -> mock.Mock:
    """造一个 `create_subprocess_exec` 会返回的假进程。

    `chuan_shu._qi_chi_cheng` spawn 后立刻起两个读任务（stdout/stderr），
    它们 `await readline()`——返回 `b""` 即 EOF，读循环自然收尾，
    不会有东西真的去等一个不存在的进程。
    """
    jin = mock.Mock()
    jin.pid = pid
    jin.returncode = 0
    for liu in ("stdout", "stderr"):
        mo = mock.Mock()
        mo.readline = mock.AsyncMock(return_value=b"")
        mo.read = mock.AsyncMock(return_value=b"")
        setattr(jin, liu, mo)
    jin.wait = mock.AsyncMock(return_value=0)
    return jin


class ZhaMen0Tests(unittest.TestCase):
    """闸门 0：无审批回路的 harness，建会话必须先拿到知情同意。"""

    def setUp(self):
        self.duan = _duan_kou()
        self.root = str(Path(__file__).resolve().parent.parent)
        self.z = ZongXian(uuid.uuid4().hex[:8])
        self.h = HuiHua(self.z)
        self.z.zhan = self.h
        self.token = auth.shengcheng()
        self.fu = BridgeServer(("127.0.0.1", self.duan), self.z, self.h,
                               ShenKa([self.root]), self.token)
        threading.Thread(target=self.fu.serve_forever, daemon=True).start()
        # MeiHuiLu 必须在注册表里，否则 400 是「没有这个 agentId」，
        # 闸门 0 根本走不到。
        zhu = mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI", {"meiHuiLu": MeiHuiLu})
        zhu.start()
        self.addCleanup(zhu.stop)

    def tearDown(self):
        self.fu.shutdown()
        self.fu.server_close()
        self.h.ting_zhi()

    def _jian(self, a1: dict, agent: str = "meiHuiLu"):
        shu = json.dumps({**a1, "agentId": agent}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.duan}/sessions", data=shu, method="POST",
            headers={"content-type": "application/json", "x-bridge-token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_bu_dai_ack_400_qie_bu_liu_hui(self):
        """不带 ack ⇒ 400 `agent_unavailable`，且**会话没被建出来**。

        分岔：只检查键存在（`"acknowledgeNoApproval" in body`）的实现这里
        会 201——所以拒绝体里的 message 必须把补救办法说出口。
        """
        s, d = self._jian({"cwd": self.root, "permissionMode": "manual"})
        self.assertEqual(s, 400)
        self.assertEqual(d["error"]["code"], "agent_unavailable")
        self.assertIn("acknowledgeNoApproval", d["error"]["message"],
                      "拒绝说明里必须告诉用户补救办法")
        self.assertEqual(self.h.kua(), [], "400 之后不该留下任何会话")

    def test_zi_fu_chuan_de_true_bu_suan_tong_yi(self):
        s, d = self._jian({"cwd": self.root, "permissionMode": "manual",
                           "acknowledgeNoApproval": "true"})
        self.assertEqual(s, 400)
        self.assertEqual(d["error"]["code"], "agent_unavailable")

    def test_shu_zi_de_1_ye_bu_suan_tong_yi(self):
        """`1 == True` 但 `1 is not True`——判定必须用 `is not True`。

        分岔：写成 `if not body.get(...)` 或 `!= True` 的实现，`1` 会被
        当成同意放行（JS 传上来的 `1` 恰好长这样）。
        """
        s, d = self._jian({"cwd": self.root, "permissionMode": "manual",
                           "acknowledgeNoApproval": 1})
        self.assertEqual(s, 400)

    def test_dai_ack_201(self):
        s, d = self._jian({"cwd": self.root, "permissionMode": "manual",
                           "acknowledgeNoApproval": True})
        self.assertEqual(s, 201, d)
        self.assertEqual(len(self.h.kua()), 1)

    def test_fangquan_wei_zhen_de_agent_bu_yao_ack(self):
        """有回路的 harness（echo 的形状）建会话照旧，不被闸门 0 烦。"""
        s, d = self._jian({"cwd": self.root, "permissionMode": "manual"},
                          agent="echo")
        self.assertEqual(s, 201, d)


class DengJiTests(unittest.TestCase):
    """pid 登记链：注入（xin_jian）→ 回调（_bao_pid）→ 替换（lu_pid）。"""

    def setUp(self):
        self.duan = _duan_kou()
        self.root = str(Path(__file__).resolve().parent.parent)
        self.z = ZongXian(uuid.uuid4().hex[:8])
        self.h = HuiHua(self.z)
        self.z.zhan = self.h
        self.token = auth.shengcheng()
        self.fu = BridgeServer(("127.0.0.1", self.duan), self.z, self.h,
                               ShenKa([self.root]), self.token)
        threading.Thread(target=self.fu.serve_forever, daemon=True).start()
        zhu = mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI", {"jiaYiCi": JiaYiCi})
        zhu.start()
        self.addCleanup(zhu.stop)

    def tearDown(self):
        self.fu.shutdown()
        self.fu.server_close()
        self.h.ting_zhi()

    def _jian(self, a1: dict, agent: str):
        shu = json.dumps({**a1, "agentId": agent}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.duan}/sessions", data=shu, method="POST",
            headers={"content-type": "application/json", "x-bridge-token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def _qi_dong(self, agent: str = "jiaYiCi") -> tuple[str, LiuXingAdapter]:
        """建会话并**手动走一遍 `xin_jian`**，拿回真注入过的适配器。

        生产里 `xin_jian` 由消息线程 `_pao` 调（`shi_ying` 也是在那里才挂上），
        建会话本身不建适配器——所以这里不能查 `shi_ying`，直接调它本尊。
        注册表 patch 必须罩住 `xin_jian`，否则它会按兜底取到 EchoAdapter。
        """
        s, d = self._jian({"cwd": self.root, "permissionMode": "manual",
                           "acknowledgeNoApproval": True}, agent=agent)
        self.assertEqual(s, 201, d)
        sid = d["session"]["sessionId"]
        with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI", {agent: JiaYiCi}):
            ad = asyncio.run(self.fu.xin_jian(sid))
        return sid, ad

    def test_lu_pid_tong_hui_huan_pid_bu_liu_jiu_tiao_mu(self):
        """同一会话先后报两个 pid ⇒ 字典里只剩新的，`ji_pids` 收到全量。

        分岔：只增不删的实现，runtime.json 里会攒下一串已退出的旧 pid，
        `sao_bing` 每次启动都去查一遍死进程。
        """
        ji: list[list[int]] = []
        self.fu.ji_pids = ji.append
        self.fu.lu_pid(111, "s1")
        self.fu.lu_pid(222, "s1")
        self.assertEqual(self.fu.pids, {222: "s1"})
        self.assertEqual(ji[-1], [222])
        # 不同会话互不误伤
        self.fu.lu_pid(333, "s2")
        self.assertEqual(self.fu.pids, {222: "s1", 333: "s2"})
        # 同会话重复报同一个 pid：幂等，不重复不误删
        self.fu.lu_pid(333, "s2")
        self.assertEqual(self.fu.pids, {222: "s1", 333: "s2"})

    def test_xin_jian_gei_yi_ci_xing_zhu_ru_hui_diao_qie_hui_luo_dao_lu_pid(self):
        """建会话 ⇒ 适配器带上回调 ⇒ spawn 成功后 pid 记到**本会话**名下。

        这是 二.1 的端到端锁：注入的回调、`_bao_pid` 的触发时机、
        `lu_pid` 的落点，三截断任何一截这条就红。
        """
        sid, ad = self._qi_dong()
        self.assertTrue(callable(ad.pid_hui), "xin_jian 没给一次性适配器注入回调")

        wei = _jia_jin(4242)
        with mock.patch("asyncio.create_subprocess_exec",
                        new=mock.AsyncMock(return_value=wei)):
            asyncio.run(ad._qi_chi_cheng({"cwd": self.root}))
        self.assertEqual(self.fu.pids.get(4242), sid,
                         "spawn 成功后回调链没把 pid 记到会话名下")

    def test_spawn_shi_bai_bu_hui_liu_you_ling_pid(self):
        """第二次 spawn 抛 `FileNotFoundError` ⇒ 回调根本不触发。

        分岔：把 `_bao_pid()` 放在 `super()._qi_chi_cheng()` **之前**的
        实现，这里会把 `jin` 上挂着的**上一回合旧进程**的 pid 报上去——
        spawn 都失败了，runtime.json 里却多了一个查无此人的条目。
        所以必须先成功 spawn 一回合、再手动把 `jin` 换成旧进程来造场景；
        首回合 `jin` 是 None，`_bao_pid` 早退，什么也分辨不出来。
        """
        sid, ad = self._qi_dong()

        wei = _jia_jin(4242)
        with mock.patch("asyncio.create_subprocess_exec",
                        new=mock.AsyncMock(return_value=wei)):
            asyncio.run(ad._qi_chi_cheng({"cwd": self.root}))
        self.assertEqual(self.fu.pids.get(4242), sid)

        # 上一回合的旧进程还挂在实例上（一次性进程跑完自己退出，
        # 适配器不会主动清 `jin`），这时第二条指令 spawn 失败：
        ad.jin = _jia_jin(9999)
        with mock.patch("asyncio.create_subprocess_exec",
                        new=mock.AsyncMock(side_effect=FileNotFoundError("jia-yi-ci-cli.cmd"))):
            with self.assertRaises(FileNotFoundError):
                asyncio.run(ad._qi_chi_cheng({"cwd": self.root}))
        self.assertEqual(self.fu.pids, {4242: sid},
                         "spawn 失败却把旧进程的 pid 报了上去")

    def test_hui_diao_pao_yi_chang_bu_ying_xiang_spawn(self):
        """回调抛异常必须被 `_bao_pid` 吞掉——pid 登记是 best effort，
        不能把一次正常拉起的回合搞挂。"""
        sid, ad = self._qi_dong()

        def _gua(pid: int) -> None:
            raise RuntimeError("落盘挂了")

        ad.pid_hui = _gua
        wei = _jia_jin(5150)
        with mock.patch("asyncio.create_subprocess_exec",
                        new=mock.AsyncMock(return_value=wei)):
            asyncio.run(ad._qi_chi_cheng({"cwd": self.root}))  # 不抛即过
        self.assertEqual(ad.jin, wei, "回调挂了不该影响进程本身")


class PiHuanJingTests(unittest.TestCase):
    """`pi._huan_jing`：非显式给的 `ANTHROPIC_*` 一律摘除。"""

    def test_ji_cheng_shi_zhai_chu_anthropic_liu_xia_qi_yu(self):
        """宿主 shell 里的 ANTHROPIC_* 不许漏进 pi 子进程。

        分岔：直接 `{**os.environ, **zeng}` 的实现（chuan_shu 基类的形状）
        这里会把 token/代理带进去——真机上表现是 pi 概率性连到别人的端点。
        """
        a = PiAdapter()
        with mock.patch.dict(os.environ, {"ANTHROPIC_AUTH_TOKEN": "x",
                                          "ANTHROPIC_BASE_URL": "http://wuliao"}):
            h = a._huan_jing({})
        self.assertIsNotNone(h, "有东西要摘时必须返回真字典（整体替换语义）")
        self.assertFalse(any(k.upper().startswith("ANTHROPIC_") for k in h),
                         f"ANTHROPIC_* 漏进了子进程环境：{[k for k in h if 'ANTHROPIC' in k.upper()]}")
        self.assertIn("PATH", h, "只许摘 ANTHROPIC_*，其余环境必须真合并保留")

    def test_xian_shi_gei_de_anthropic_shuo_le_suan(self):
        """显式经请求 `env` 传的 ANTHROPIC_* 键保留，未给的仍摘。"""
        a = PiAdapter()
        with mock.patch.dict(os.environ, {"ANTHROPIC_AUTH_TOKEN": "wuliao"}):
            h = a._huan_jing({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:9"}})
        self.assertEqual(h["ANTHROPIC_BASE_URL"], "http://127.0.0.1:9")
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", h)

    def test_gan_jing_huan_jing_qie_mei_zeng_liang_fan_none(self):
        """没有要摘的、也没有增量 ⇒ 返回 None（完全继承，不覆盖）。

        `create_subprocess_exec(env=None)` 才是真继承；
        给一个拼出来的全量字典会把运行中的环境快照住。
        """
        a = PiAdapter()
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(a._huan_jing({}))

    def test_pi_yi_ci_xing_wei_False_cai_yang_lu_jing_cai_you_xiao(self):
        """一.2 的锁定：pi 是常驻形态 ⇒ `kaishi()` 就 spawn ⇒ `xin_jian`
        的 `qu_pid()` 采样对它有效（2026-10-06 按代码路径核实的结论）。

        若有人把它改成 True，采样路径对 pi 失效，pid 只能靠回调——
        那是一次契约变更，必须在这里现形。
        """
        self.assertFalse(PiAdapter.yi_ci_xing)


if __name__ == "__main__":
    unittest.main()
