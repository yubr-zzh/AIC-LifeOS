"""会话级超时、版本门禁、进程回收（方案 8.7 第二三层、3.6、3.9）。

8.7 的第二三层是 v1.0 完全缺失的一章，而缺它的后果不是「慢」，
是「Bridge 崩过一次之后，用户再也开不了新任务且界面不提示为什么」。
"""

import socket
import sys
import time
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from unittest import mock

from lifeos.bridge import auth
from lifeos.bridge.events import ZongXian
from lifeos.bridge.http import BridgeServer
from lifeos.bridge.models import AgentSession
from lifeos.bridge.planner_guard import JuDuan, ShenKa
from lifeos.bridge.session import HuiHua
from gong_ju import deng_dai

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _duan() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TingGeTests(unittest.TestCase):
    """停滞超时：working/thinking 下无任何帧。"""

    def setUp(self):
        self.z = ZongXian(uuid.uuid4().hex[:8])
        self.h = HuiHua(self.z, a2=0.3)
        self.z.zhan = self.h
        self.zhong: list[str] = []
        self.h.ting_shi = self.zhong.append
        self.jian("s-1", "working")

    def tearDown(self):
        self.h.ting_zhi()

    def jian(self, a1: str, a2: str = "idle"):
        s = AgentSession(sessionId=a1, agentId="echo", agentLabel="echo", cwd=".", state=a2)
        return self.h.jian(s)

    def test_ting_zhuan_wei_error(self):
        self.h.kai_dog()
        # 等的是「转成 error」这个状态（`a2=0.3` 的停滞超时），不是等 3 秒。
        deng_dai(lambda: self.h.du("s-1").state == "error", chao=3.0,
                 msg=lambda: self.h.du("s-1").state)
        self.assertEqual(self.h.du("s-1").state, "error")
        zhen = [z for _, z in self.z.huan if z["type"] == "error"]
        self.assertEqual(zhen[-1]["code"], "stall_timeout")
        # 关键：光转状态不够，底下的 claude 进程还在烧 token，必须真的中断它
        self.assertEqual(self.zhong, ["s-1"])

    def test_attention_bu_qi_ting_zhuan(self):
        """等用户审批时是 attention，不该被当成停滞——那是正常等待，不是卡死。"""
        self.h.geng("s-1", "attention", "permission_requested")
        # 这句原来是无条件 sleep(1.2)：看门狗线程压根没起来时它也照样绿——
        # 「什么都没有发生」被当成了「等够了」。看门狗没有对外暴露「巡视过」
        # 这个状态，所以在**同一台 HuiHua 里**放一条同配置的哨兵会话：它停在
        # working 且不动，第一次巡视必然把它转成 error。它转了，就证明这一台
        # 看门狗真的巡视过一轮；那一刻 s-1 仍是 attention 才是有效证据。
        # 哨兵的中断不进 `self.zhong`（那条断言一个字没动）。
        self.jian("s-shao", "working")

        def zhong(a1: str) -> None:
            if a1 != "s-shao":
                self.zhong.append(a1)

        with mock.patch.object(self.h, "ting_shi", zhong):
            self.h.kai_dog()
            deng_dai(lambda: self.h.du("s-shao").state == "error", chao=8.0,
                     msg=lambda: self.h.du("s-shao").state)
        self.assertEqual(self.h.du("s-1").state, "attention")
        self.assertEqual(self.zhong, [])

    def test_you_帧_bu_qi_ting(self):
        self.h.kai_dog()
        for i in range(6):
            self.h.tian_jia("s-1", "assistant", "text", text=f"第{i}块")
            # 帧与帧之间的间隔是**刺激的节奏**，不是测试在等什么：停滞超时是
            # 0.3 秒，帧要一直落在窗口里才构得成「有帧就不停滞」。固定时长留着。
            time.sleep(0.1)
        self.assertEqual(self.h.du("s-1").state, "working")
        self.assertEqual(self.zhong, [])


class XianZhiTests(unittest.TestCase):
    """闲置超时：idle 会话自动关闭。"""

    def test_xian_zhi_zi_dong_guan_bi(self):
        z = ZongXian(uuid.uuid4().hex[:8])
        h = HuiHua(z, a3=0.3)
        z.zhan = h
        guan: list[str] = []
        h.guan_yong = lambda sid, ms=0.0: guan.append(sid)
        h.jian(AgentSession(sessionId="s-9", agentId="echo", agentLabel="e", cwd="."))
        h.kai_dog()
        try:
            # 等「会话被摘掉」这个状态，不是等 60 次轮询那么久。
            deng_dai(lambda: h.du("s-9") is None, chao=3.0,
                     msg=lambda: h.du("s-9"))
            self.assertIsNone(h.du("s-9"))
            self.assertEqual(guan, ["s-9"])
            # session_removed 由注入的回调发（生产里是 BridgeServer），
            # 本层再发一次就是重复帧
            self.assertFalse(any(z2["type"] == "session_removed" for _, z2 in z.huan))
        finally:
            h.ting_zhi()


class BanBenMenTests(unittest.TestCase):
    """3.9：CLI 版本对不上基准时强制降为 plan。"""

    def setUp(self):
        self.duan = _duan()
        self.root = str(Path(__file__).resolve().parent.parent)
        self.z = ZongXian(uuid.uuid4().hex[:8])
        self.h = HuiHua(self.z)
        self.z.zhan = self.h
        self.token = auth.shengcheng()
        self.fu = BridgeServer(("127.0.0.1", self.duan), self.z, self.h,
                               ShenKa([self.root]), self.token)
        import threading
        threading.Thread(target=self.fu.serve_forever, daemon=True).start()

    def tearDown(self):
        self.fu.shutdown()
        self.fu.server_close()
        self.h.ting_zhi()

    def _gai_moshi(self, a1: str, a2: dict):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.duan}/sessions/{a1}/mode",
            data=__import__("json").dumps(a2).encode(), method="POST",
            headers={"content-type": "application/json", "x-bridge-token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, __import__("json").loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, __import__("json").loads(e.read().decode())

    def test_qie_huan_mo_shi_cheng_gong(self):
        """切模式要真的落到适配器上（3.5）。"""
        s, d = self._jian({"agentId": "echo", "cwd": self.root, "permissionMode": "manual"})
        sid = d["session"]["sessionId"]
        self._qiao(f"/sessions/{sid}/messages", {"instructions": ["第一条指令"]})
        # 等「会话建好 + 适配器落上」这个状态；固定轮询次数是在猜它多久好。
        deng_dai(lambda: self.h.du(sid) is not None and bool(self.fu.shi_ying.get(sid)),
                 chao=3.0, msg=lambda: (self.h.du(sid), self.fu.shi_ying.get(sid)))
        code, r = self._gai_moshi(sid, {"permissionMode": "acceptEdits"})
        self.assertEqual(code, 200)
        self.assertEqual(r["effectiveMode"], "acceptEdits")
        self.assertEqual(self.fu.shi_ying[sid].moshi, "acceptEdits")
        self.assertEqual(self.h.du(sid).effectiveMode, "acceptEdits")

    def test_wei_kai_qi_agent_de_hui_hua_qie_huan_mo_shi_409(self):
        s, d = self._jian({"agentId": "echo", "cwd": self.root, "permissionMode": "manual"})
        code, r = self._gai_moshi(d["session"]["sessionId"], {"permissionMode": "plan"})
        self.assertEqual(code, 409)

    def _qiao(self, a1: str, a2: dict):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.duan}{a1}",
            data=__import__("json").dumps(a2).encode(), method="POST",
            headers={"content-type": "application/json", "x-bridge-token": self.token})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, __import__("json").loads(r.read().decode())

    def _jian(self, a1: dict):
        shu = __import__("json").dumps(a1).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.duan}/sessions", data=shu, method="POST",
            headers={"content-type": "application/json", "x-bridge-token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, __import__("json").loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, __import__("json").loads(e.read().decode())

    def test_pi_fen_hao_que_ren_mo_shi_bao_yuan_yang(self):
        self.fu.cli_ban_ben = self.fu.ji_zun_ban_ben
        s, d = self._jian({"agentId": "echo", "cwd": self.root,
                           "permissionMode": "acceptEdits"})
        self.assertEqual(s, 201)
        self.assertEqual(d["session"]["effectiveMode"], "acceptEdits")
        self.assertFalse(self.fu.ren_men()["mismatch"])

    def test_fou_ren_men_jiang_shou_qiang_zhi_plan(self):
        self.fu.cli_ban_ben = "0.0.1-fake"
        s, d = self._jian({"agentId": "echo", "cwd": self.root,
                           "permissionMode": "acceptEdits"})
        self.assertEqual(s, 201)
        self.assertEqual(d["session"]["permissionMode"], "plan")
        self.assertEqual(d["session"]["effectiveMode"], "plan")
        men = self.fu.ren_men()
        self.assertTrue(men["mismatch"])
        self.assertEqual(men["baseline"], self.fu.ji_zun_ban_ben)

    def test_qie_huan_mo_shi_ye_yao_guo_men_jian(self):
        """闸门 1 对切模式同样生效——非法模式不能借切换接口绕进去。"""
        import threading
        shu = __import__("json").dumps({"permissionMode": "bypassPermissions"}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.duan}/sessions/s-x/mode", data=shu, method="POST",
            headers={"content-type": "application/json", "x-bridge-token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
            body = __import__("json").loads(e.read().decode())
        self.assertEqual(code, 400)
        self.assertEqual(body["error"]["code"], "mode_forbidden")


class JinChengTests(unittest.TestCase):
    """3.6：子进程 pid 必须落盘，否则 Bridge 被强杀后收不回孤儿。"""

    def test_pid_qing_dian_biao_ming_hui_shu(self):
        """关会话要把这个会话名下的 pid 都从账上划掉（3.6）。

        真机实测 `client.disconnect()` 拦不住子进程，必须按 pid 兜底 kill；
        划掉账目同样重要——留着会让下次启动的孤儿清理去杀一个已经不存在的 pid。
        """
        luo: list[list[int]] = []
        z = ZongXian(uuid.uuid4().hex[:8])
        h = HuiHua(z)
        z.zhan = h
        fu = BridgeServer(("127.0.0.1", _duan()), z, h, ShenKa([str(Path.cwd())]),
                          auth.shengcheng())
        fu.ji_pids = luo.append
        sha: list[int] = []
        fu.sha_pid = lambda pid: (sha.append(pid), fu.pids.pop(pid, None))[1]
        try:
            fu.pids.update({111: "s-1", 222: "s-1", 333: "s-2"})
            fu.sha_qing_dian("s-1")
            self.assertEqual(sorted(sha), [111, 222])
            self.assertEqual(sorted(fu.pids), [333])  # 别的会话不动
            fu.guan_biao()
            self.assertEqual(fu.pids, {})
        finally:
            h.ting_zhi()
            fu.server_close()

    def test_pid_lu_pan_bing_hui_diao(self):
        luo: list[list[int]] = []
        z = ZongXian(uuid.uuid4().hex[:8])
        h = HuiHua(z)
        z.zhan = h
        fu = BridgeServer(("127.0.0.1", _duan()), z, h, ShenKa([str(Path.cwd())]),
                          auth.shengcheng())
        fu.ji_pids = luo.append
        try:
            fu.lu_pid(1234, "s-1")
            fu.lu_pid(5678, "s-2")
            self.assertEqual(luo[-1], [1234, 5678])
            self.assertEqual(fu.pids[1234], "s-1")
        finally:
            h.ting_zhi()
            fu.server_close()


if __name__ == "__main__":
    unittest.main()
