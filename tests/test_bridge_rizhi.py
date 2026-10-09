"""10.7：日志与文件权限。

三件事：有可观测性（不再是整条禁掉）、没有 token、没有请求体。
请求体里有 toolInput 全文——那正是 8.8 防 prompt injection 要保护的输入。
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from lifeos.bridge.cun import Cun, shou_quan
from lifeos.bridge.events import ZongXian
from lifeos.bridge.http import BridgeHandler, BridgeServer
from lifeos.bridge.localbus import LuDao
from lifeos.bridge.planner_guard import ShenKa
from lifeos.bridge.run import SHI_JU, zhu_ri
from lifeos.bridge.session import HuiHua
from gong_ju import deng_dai

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class RiZhiTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.gen = Path(self.dir.name)
        self.root = str(Path(__file__).resolve().parent.parent)
        self.z = ZongXian(uuid.uuid4().hex[:8])
        self.h = HuiHua(self.z)
        self.z.zhan = self.h
        self.token = "t" * 64
        # 日志由 run.zhu_ri() 装配，再注入到 handler 上。**这里必须自己调一次**：
        # 直接 new 一个 BridgeServer 不会装日志，只有 run.zhen_ben() 会。
        self.ri = zhu_ri(self.gen)
        self.jiu = BridgeHandler.ri
        BridgeHandler.ri = self.ri
        self.ri_wen = self.gen / SHI_JU / "bridge" / "bridge.log"
        self.fu = BridgeServer(("127.0.0.1", 0), self.z, self.h,
                               ShenKa([self.root]), self.token, Cun(self.gen))
        self.duan = self.fu.server_address[1]
        threading.Thread(target=self.fu.serve_forever, daemon=True).start()

    def tearDown(self):
        self.fu.shutdown()
        self.fu.server_close()
        self.h.ting_zhi()
        BridgeHandler.ri = self.jiu
        # handler 不摘掉的话，同一个进程里第二个用例的 zhu_ri() 会因为
        # 「已经有 handler」直接返回旧的，日志继续写进已经删掉的临时目录，
        # 测试就会读到一个不存在的文件。
        for x in list(self.ri.handlers):
            self.ri.removeHandler(x)
            x.close()
        self.dir.cleanup()

    def _ri(self) -> str:
        for x in self.ri.handlers:
            x.flush()
        return self.ri_wen.read_text(encoding="utf-8")

    def _qing(self, a1, a2, a3=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.duan}{a1}", method=a2,
                                     headers={"x-bridge-token": self.token})
        if a3 is not None:
            req.data = json.dumps(a3).encode("utf-8")
            req.add_header("content-type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status

    def test_ri_zhi_you_nei_rong(self):
        """阶段 1 把访问日志整条禁掉了。10.7 要的是「能回答 Bridge 卡住了怎么排查」，
        所以日志里必须真的有内容。"""
        self._qing("/health", "GET")
        wen = self._ri()
        self.assertIn("/health", wen)
        self.assertIn("200", wen)

    def test_ri_zhi_mei_you_qing_qiu_ti(self):
        """请求体里有 toolInput 全文，那正是 8.8 防 prompt injection 要保护的输入。"""
        self._qing("/sessions", "POST", {"agentId": "echo", "cwd": self.root,
                                         "title": "secret-title-xyz"})
        self.assertNotIn("secret-title-xyz", self._ri())

    def test_ri_zhi_mei_you_token(self):
        """token 走 query string 才进得了请求行——那正是要抹掉的那一段。"""
        self._qing(f"/health?token={self.token}", "GET")
        wen = self._ri()
        self.assertIn("token=***", wen)
        self.assertNotIn(self.token, wen)

    def test_shou_quan_bu_bao_cuo(self):
        p = self.gen / "x.json"
        p.write_text("{}", encoding="utf-8")
        shou_quan(p)  # 不许抛异常；Windows Home 上可能失败，失败只告警
        self.assertTrue(p.exists())

    def test_shou_quan_hou_hai_neng_fu_gai(self):
        """收紧权限之后，原子替换还得能覆盖写。

        **这条必须在一个「父目录不给 FILE_DELETE_CHILD」的目录里跑**，
        否则测不出来：在 %TEMP% 那种用户有完全控制（含 DC 位）的目录下，
        删子文件靠的是目录的 DC，文件自己有没有 DELETE 都无所谓。
        生产目录 .lifeos/bridge 的 ACL 是 `user:M`（Modify，**不含** DC——
        icacls 的 M 含的是文件自身的 DELETE，不是 FILE_DELETE_CHILD），
        于是子文件必须自带 DELETE 才删得掉，而 os.replace 覆盖目标正是
        「删掉旧的、把临时的改过去」。

        只给 RW 的症状是「第一次启动正常，第二次启动 WinError 5」：
        runtime.json 每次启动都要重写，Bridge 从此再也起不来；
        而 sessions.json 走同一条路，那里被 Cun 的 except OSError 吞掉，
        变成「会话落盘静默失效」——比崩溃更难查。
        """
        if os.name != "nt":
            self.skipTest("这是 Windows ACL 的行为")
        from lifeos.storage.atomic import write_json
        d = self.gen / "shou"
        d.mkdir()
        subprocess.run(["icacls", str(d), "/inheritance:r",
                        "/grant:r", "%s:M" % os.environ.get("USERNAME", "")],
                       capture_output=True, timeout=10)
        p = d / "y.json"
        write_json(p, {"a": 1})
        shou_quan(p)
        write_json(p, {"a": 2})   # 覆盖写：这一步不许抛
        self.assertEqual(json.loads(p.read_text(encoding="utf-8")), {"a": 2})


class _Shou(BaseHTTPRequestHandler):
    shou: list = []

    def do_POST(self):
        chang = int(self.headers["content-length"])
        _Shou.shou.append(json.loads(self.rfile.read(chang).decode("utf-8")))
        self.send_response(200)
        self.send_header("content-length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a, **kw):
        pass


class LuDaoTests(unittest.TestCase):
    def test_liu_ge_yu_yi_tang(self):
        """7.1 的六个 kind 各有一个语义糖方法，调用点读起来像人话。"""
        _Shou.shou = []
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            duan = s.getsockname()[1]
        zhu = ThreadingHTTPServer(("127.0.0.1", duan), _Shou)
        zhu.daemon_threads = True
        threading.Thread(target=zhu.serve_forever, daemon=True).start()
        lu = LuDao(f"http://127.0.0.1:{duan}")
        try:
            lu.lian_jie({"instanceId": "i-1", "port": 8766})
            lu.duan_kai({"reason": "stop"})
            lu.jian_hui("s-1", {"sessionId": "s-1", "agentId": "claude-code"})
            lu.guan_hui("s-1", {"sessionId": "s-1", "reason": "idle"})
            lu.jue_guo("s-1", {"requestId": "toolu_1", "decision": "user_allow"})
            lu.beng_kui("s-1", {"sessionId": "s-1", "exitCode": 1})
            # **先等六条都到，再停 worker。** 反过来做的话 worker 会在队列还没
            # 排空时就退出，断言时少几条，看起来像方法没实现。
            deng_dai(lambda: len(_Shou.shou) >= 6, chao=5.0,
                     msg=lambda: [x["kind"] for x in _Shou.shou])
            self.assertEqual([x["kind"] for x in _Shou.shou],
                             ["bridge.connected", "bridge.disconnected", "session.created",
                              "session.closed", "permission.resolved", "agent.crashed"])
        finally:
            lu.ting_zhi()
            zhu.shutdown()
            zhu.server_close()


if __name__ == "__main__":
    unittest.main()
