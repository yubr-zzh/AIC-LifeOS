"""阶段 1 的验收测试（方案 12.2 任务 1.3 / 1.5 / 1.8 / 1.9 / 1.10）。

最要紧的是 `TransportTests.test_xian_rong_hua_zhuan_xiang`：两个 SSE 长连接占住服务
线程的同时，POST 仍必须在 1 秒内返回。用单线程 HTTPServer 的话这条必然超时。
"""

import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from lifeos.bridge import auth
from lifeos.bridge.adapters import EchoAdapter
from lifeos.bridge.events import ZongXian
from lifeos.bridge.http import BridgeServer
from lifeos.bridge.models import AgentSession
from lifeos.bridge.planner_guard import JuDuan, ShenKa
from lifeos.bridge.session import HuiHua, InvalidTransition
from gong_ju import deng_dai, duan_ke

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class AuthTests(unittest.TestCase):
    def test_que_token_401(self):
        with self.assertRaises(auth.WeiQuan) as e:
            auth.duanren("abc", None)
        self.assertEqual(e.exception.code, "unauthorized")

    def test_cu_token_401(self):
        with self.assertRaises(auth.WeiQuan) as e:
            auth.duanren("abc", "def")
        self.assertEqual(e.exception.code, "unauthorized")

    def test_dui_token_tong_guo(self):
        t = auth.shengcheng()
        auth.duanren(t, t)  # 不抛异常即通过

    def test_token_shi_32_zifu(self):
        self.assertEqual(len(auth.shengcheng()), 64)  # 32 字节 hex

    def test_origin_que_fangxing(self):
        with self.assertRaises(auth.WeiQuan) as e:
            auth.yuanbai("http://evil.example.com")
        self.assertEqual(e.exception.code, "forbidden")

    def test_origin_que_4147_fangxing(self):
        auth.yuanbai("http://127.0.0.1:4173")  # Vite preview 必须在白名单内

    def test_origin_que_5173_fangxing(self):
        auth.yuanbai("http://localhost:5173")

    def test_origin_wei_que_fangxing(self):
        auth.yuanbai(None)  # 本地调用没有 Origin，放行


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.g = ShenKa(mizhu := [str(Path(__file__).resolve().parent.parent)])
        self.root = Path(mizhu[0])

    def test_moshi_bai_ming_kuan(self):
        for m in ("manual", "acceptEdits", "plan", "auto", "dontAsk"):
            self.assertEqual(self.g.fang(m), m)

    def test_bypass_bei_400_bu_qian_reng(self):
        with self.assertRaises(JuDuan) as e:
            self.g.fang("bypassPermissions")
        self.assertEqual(e.exception.code, "mode_forbidden")

    def test_bu_zhixiang_de_bu_jie_shi_wei_que_rong(self):
        self.assertEqual(self.g.fang(None), "manual")  # 缺省给 manual，不报错

    def test_hefa_cwd_tong_guo(self):
        self.assertEqual(self.g.cwd(str(self.root)), os.path.normcase(os.path.realpath(str(self.root))))

    def test_cwd_yue_jie_bei_400(self):
        with tempfile.TemporaryDirectory() as d:
            pass
        with self.assertRaises(JuDuan) as e:
            self.g.cwd(str(Path.home() / ".." / ".." / "Windows" / "System32"))
        self.assertEqual(e.exception.code, "cwd_forbidden")

    def test_cwd_kong_bei_400(self):
        with self.assertRaises(JuDuan) as e:
            self.g.cwd("")
        self.assertEqual(e.exception.code, "cwd_forbidden")

    def test_deny_dian_ji_shu_luo_di(self):
        self.assertIsNotNone(self.g.shibai("Bash", {"command": "format C:"}, str(self.root)))

    def test_deny_reg_delete(self):
        self.assertIsNotNone(self.g.shibai("Bash", {"command": "reg delete HKLM\\SOFTWARE"}, str(self.root)))

    def test_deny_chmod_777(self):
        self.assertIsNotNone(self.g.shibai("Bash", {"command": "chmod 777 /tmp/x"}, str(self.root)))

    def test_deny_xie_ssh(self):
        self.assertIsNotNone(
            self.g.shibai("Write", {"file_path": str(Path.home() / ".ssh" / "authorized_keys")}, str(self.root))
        )

    def test_deny_du_aws(self):
        self.assertIsNotNone(self.g.shibai("Read", {"path": str(Path.home() / ".aws" / "credentials")}, str(self.root)))

    def test_deny_mian_yi_ke_jia_ting(self):
        # 误报防线：命令里出现 format 字样但不是真的要格式化，不该拦
        self.assertIsNone(self.g.shibai("Bash", {"command": "echo format is a command"}, str(self.root)))

    def test_puti_jing_chang_ke_tong_guo(self):
        self.assertIsNone(self.g.shibai("Bash", {"command": "node -e \"console.log(1)\""}, str(self.root)))

    def test_deny_liu_cheng_yu_qie_yao_bu_ke_gao_chao(self):
        # 闸门 2 的独立性：即使调用方自称 manual，deny 基线依然生效
        self.assertIsNotNone(self.g.shibai("Bash", {"command": "diskpart"}, str(self.root)))


class EventBusTests(unittest.TestCase):
    def setUp(self):
        self.z = ZongXian("abc123")

    def test_liu_hao_quan_qiu_dan_diao(self):
        a = self.z.fa("state", "s-1", state="thinking")
        b = self.z.fa("state", "s-2", state="working")
        self.assertEqual(a["streamSeq"], 1)
        self.assertEqual(b["streamSeq"], 2)  # 跨会话仍然单调，s-2 不是从 1 开始

    def test_liu_hao_kua_hui_yi_liu(self):
        for i in range(5):
            self.z.fa("state", "s-1", state="thinking", i=i)
        self.assertEqual(self.z.xu_hao(), 5)

    def test_duo_ding_yue_shou_dao_yi_zhi(self):
        d1 = self.z.dingyue("d1")
        d2 = self.z.dingyue("d2")
        self.z.fa("state", "s-1", state="thinking")
        a = d1.que.get_nowait()
        b = d2.que.get_nowait()
        self.assertEqual(a["streamSeq"], b["streamSeq"])

    def test_guan_jian_zhen_que_di_diao(self):
        from lifeos.bridge.events import DingYue

        d = DingYue("d1")
        d.que = __import__("queue").Queue(maxsize=4)
        for i in range(4):
            d.ru({"type": "chunk", "streamSeq": i})
        d.ru({"type": "chunk", "streamSeq": 9})  # 满了，丢最旧
        self.assertFalse(d.chao)
        self.assertEqual(d.que.qsize(), 4)
        self.assertEqual(d.que.get_nowait()["streamSeq"], 1)  # 0 被丢了

    def test_guan_jian_zhen_dui_que_duan_kai(self):
        from lifeos.bridge.events import DingYue

        d = DingYue("d1")
        d.que = __import__("queue").Queue(maxsize=1)
        d.ru({"type": "chunk", "streamSeq": 0})
        d.ru({"type": "permission", "streamSeq": 1})  # 关键帧进不去
        self.assertTrue(d.chao)  # 标记写线程断开，让它走重连补齐

    def test_bu_di_xian_shao_zhong_bu_lian(self):
        for i in range(10):
            self.z.fa("state", "s-1", state="thinking", i=i)
        zhen = self.z.duibu(5)
        self.assertEqual(zhen[0]["type"], "snapshot")  # 永远先 snapshot
        self.assertTrue(all(z["streamSeq"] > 5 for z in zhen[1:]))

    def test_ke_ji_lian_bu_xu_fa(self):
        for i in range(3):
            self.z.fa("state", "s-1", state="thinking", i=i)
        self.assertEqual(len(self.z.duibu(3)), 1)  # 已是最新，只发 snapshot

    def test_chao_jie_401(self):
        self.z.fa("state", "s-1", state="thinking")
        self.assertFalse(self.z.chao_le(1))
        self.assertTrue(self.z.chao_le(99))  # Bridge 重启后旧游标 > 当前

    def test_zhao_pian_dai_instance_id(self):
        zha = self.z.zha_pian()
        self.assertEqual(zha["instanceId"], "i-abc123")
        self.assertIn("sessions", zha)
        self.assertIn("pending", zha)
        self.assertIn("questions", zha)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.z = ZongXian("t")
        self.h = HuiHua(self.z)
        self.z.zhan = self.h
        self.sid = "s-test"
        self.h.jian(AgentSession(sessionId=self.sid, agentId="echo", agentLabel="Echo", cwd=str(Path.cwd())))

    def test_hefa_yi_qian(self):
        self.h.geng(self.sid, "thinking")
        self.assertEqual(self.h.du(self.sid).state, "thinking")

    def test_fei_fa_yi_qian_bei_ju(self):
        with self.assertRaises(InvalidTransition):
            self.h.geng(self.sid, "working")  # idle → working 不在表里

    def test_wei_zhi_yi_qian_bei_ju(self):
        with self.assertRaises(InvalidTransition):
            self.h.geng(self.sid, "banana")

    # ---- 方案 C.1 点名的四条最容易漏的迁移 ----
    def test_bing_fang_shen_pi_zhi_huan(self):
        self.h.geng(self.sid, "attention")
        self.h.geng(self.sid, "attention")  # 同态自环：并发审批

    def test_bing_xing_gong_ju_zhi_huan(self):
        self.h.geng(self.sid, "thinking")
        self.h.geng(self.sid, "working")
        self.h.geng(self.sid, "working")  # 同态自环：并行工具

    def test_shen_pi_tong_guo_li_ke_shou_wan(self):
        self.h.geng(self.sid, "attention")
        self.h.geng(self.sid, "ended")  # 点允许后这一轮就跑完了

    def test_cuo_wu_neng_hui_dong(self):
        self.h.geng(self.sid, "error")
        self.h.geng(self.sid, "idle")  # error 不是死状态

    def test_zhong_zhi_hou_neng_za_qi(self):
        self.h.geng(self.sid, "thinking")
        self.h.geng(self.sid, "ended")
        self.h.geng(self.sid, "thinking")  # ended → thinking：新指令重新拉起

    def test_xin_xi_seq_session_nei_dan_diao(self):
        for _ in range(3):
            self.h.tian_jia(self.sid, "user", "text", text="x")
        self.assertEqual([m.seq for m in self.h.juan_biao(self.sid, 0)], [1, 2, 3])

    def test_tong_guo_wen_you_xu_hao(self):
        """传了 SDK 的 message_id 就用它，不另起一个。

        chunk 帧的 messageId 就是这个值。前端靠它把流式增量归并到最终消息上，
        对不上就只能把两条都渲染出来。
        """
        m = self.h.tian_jia(self.sid, "assistant", "text", "msg_sdk_1", text="你好")
        self.assertEqual(m.messageId, "msg_sdk_1")
        m2 = self.h.tian_jia(self.sid, "user", "text", text="没传 id 时才自造")
        self.assertTrue(m2.messageId.startswith("m-"))

    # ---- 1.9 回合编排器 ----
    def _pao(self, a1, a2=None):
        import asyncio

        tp = EchoAdapter(a2)
        return asyncio.run(self.h.paichu(self.sid, a1, tp))

    def test_duo_tiao_zhi_lian_xing(self):
        r = self._pao(["a", "b", "c"])
        self.assertTrue(r["ok"])
        self.assertEqual(r["batchDone"], 3)
        self.assertEqual(self.h.du(self.sid).state, "ended")

    def test_qi_zhong_yi_tiao_ting_lei_xia(self):
        class Shuai(EchoAdapter):
            async def fasong(self, a1):
                if a1 == "b":
                    raise RuntimeError("boom")
                return await super().fasong(a1)

        import asyncio

        r = asyncio.run(self.h.paichu(self.sid, ["a", "b", "c"], Shuai()))
        self.assertFalse(r["ok"])
        self.assertEqual(self.h.du(self.sid).state, "error")
        self.assertEqual(self.h.du(self.sid).batchDone, 1)  # a 成了，b 挂，c 没跑

    def test_zhong_duan_ting_lei_xia(self):
        import asyncio

        async def zhu():
            async def kuai():
                return await self.h.paichu(self.sid, ["a", "b", "c"], EchoAdapter())
            t = asyncio.create_task(kuai())
            await asyncio.sleep(0)
            self.h.zhong_duan(self.sid)
            return await t

        r = asyncio.run(zhu())
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "interrupted")


def _qi(a1: int = 0) -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", a1))
        return s.getsockname()[1]


class TransportTests(unittest.TestCase):
    """端到端起一个真 Bridge，验证认证、闸门与线程化。"""

    @classmethod
    def setUpClass(cls):
        cls.z = ZongXian(uuid.uuid4().hex[:8])
        cls.h = HuiHua(cls.z)
        cls.z.zhan = cls.h
        cls.g = ShenKa(mizhu := [str(Path(__file__).resolve().parent.parent)])
        cls.token = auth.shengcheng()
        cls.duan = _qi()
        cls.fu = BridgeServer(("127.0.0.1", cls.duan), cls.z, cls.h, cls.g, cls.token)
        cls.th = threading.Thread(target=cls.fu.serve_forever, daemon=True)
        cls.th.start()
        cls.root = mizhu[0]

    @classmethod
    def tearDownClass(cls):
        cls.fu.shutdown()
        cls.fu.server_close()

    def _url(self, a1: str) -> str:
        return f"http://127.0.0.1:{self.duan}{a1}"

    def _get(self, a1: str, a2: dict | None = None, a3: dict | None = None):
        u = self._url(a1)
        if a2:
            jie = "&" if "?" in u else "?"
            u += jie + "&".join(f"{k}={v}" for k, v in a2.items())
        req = urllib.request.Request(u, headers=a3 or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _post(self, a1: str, a2: dict | None = None, a3: dict | None = None):
        shu = json.dumps(a2 or {}).encode("utf-8")
        head = {"content-type": "application/json", **({"x-bridge-token": self.token} | (a3 or {}))}
        req = urllib.request.Request(self._url(a1), data=shu, headers=head, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_health_mian_ren(self):
        s, d = self._get("/health")
        self.assertEqual(s, 200)
        self.assertTrue(d["ok"])

    def test_agents_ya_token(self):
        s, d = self._get("/agents")
        self.assertEqual(s, 401)
        self.assertEqual(d["error"]["code"], "unauthorized")

    def test_liu_ya_token(self):
        s, d = self._get("/stream", {"session": "s-1"})
        self.assertEqual(s, 401)

    def test_wu_ce_dian_404(self):
        s, d = self._get("/nope", {"token": self.token})
        self.assertEqual(s, 404)
        self.assertEqual(d["error"]["code"], "not_found")

    def test_bypass_400_bu_jian_hui(self):
        s, d = self._post("/sessions", {"agentId": "echo", "cwd": self.root, "permissionMode": "bypassPermissions"})
        self.assertEqual(s, 400)
        self.assertEqual(d["error"]["code"], "mode_forbidden")
        self.assertEqual(len(self.h.kua()), 0)  # 会话根本没被创建

    def test_cwd_yue_jie_400(self):
        s, d = self._post("/sessions", {"agentId": "echo", "cwd": "C:/Windows/System32"})
        self.assertEqual(s, 400)
        self.assertEqual(d["error"]["code"], "cwd_forbidden")

    def test_jian_hui_cheng_gong(self):
        s, d = self._post("/sessions", {"agentId": "echo", "cwd": self.root, "title": "t"})
        self.assertEqual(s, 201)
        self.assertEqual(d["session"]["state"], "idle")
        self.assertEqual(d["session"]["effectiveMode"], "manual")

    def test_jian_hui_idempotent(self):
        a = self._post("/sessions", {"cwd": self.root, "clientIdempotencyKey": "k-1"})[1]
        b = self._post("/sessions", {"cwd": self.root, "clientIdempotencyKey": "k-1"})[1]
        self.assertEqual(a["session"]["sessionId"], b["session"]["sessionId"])

    def test_jue_ding_cong_lai_mei_you_guo_404(self):
        # 从未存在的 rid 是 404，不是 409——两者的 UI 含义不同：
        # 409 表示「你已经批过了，系统没忘」，404 表示「这压根不是一张卡」
        s, d = self._post("/permissions/p-nope", {"decision": "allow"})
        self.assertEqual(s, 404)
        self.assertEqual(d["error"]["code"], "not_found")

    def test_jue_ding_fen_lei_400(self):
        s, d = self._post("/permissions/p-1", {"decision": "maybe"})
        self.assertEqual(s, 400)

    def test_yuan_wen_chao_jie_409(self):
        s, h = self._post("/sessions", {"cwd": self.root, "clientIdempotencyKey": "k-2"})
        sid = h["session"]["sessionId"]
        s, d = self._get(f"/sessions/{sid}/transcript?from=99999", {"token": self.token})
        self.assertEqual(s, 409)
        self.assertEqual(d["error"]["code"], "reset_required")

    def test_xian_rong_hua_zhuan_xiang(self):
        """方案 12.2 任务 1.8：两个 SSE 长连接占住服务线程的同时，
        POST 仍必须在 1 秒内返回。"""
        ting = []
        # 订阅表是累积的（本类共用一条 `ZongXian`），所以比增量，不比绝对值。
        ji = len(self.z.lie_ding())
        for _ in range(2):
            t = threading.Thread(target=self._ting_liu, daemon=True)
            t.start()
            ting.append(t)
        # 等「两条 SSE 真的进了订阅表」：`dingyue` 在写线程起来**之前**，
        # 表里有了它，后面的 POST 才是真的在两条长连接占住线程时打进来的。
        # 原来是固定 sleep 1.0 猜——猜错了这条就测了个空。
        deng_dai(lambda: len(self.z.lie_ding()) >= ji + 2, chao=10.0,
                 msg=lambda: len(self.z.lie_ding()) - ji)

        t0 = time.monotonic()
        s, d = self._post("/sessions", {"cwd": self.root, "clientIdempotencyKey": "k-thread"})
        spent = time.monotonic() - t0

        self.assertEqual(s, 201)
        self.assertLess(spent, 1.0, f"SSE 占满时 POST 花了 {spent:.2f}s，说明服务器是单线程的")
        for t in ting:
            t.join(timeout=2)

    def _ting_liu(self):
        try:
            req = urllib.request.Request(
                self._url("/stream"), headers={"x-bridge-token": self.token}
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                r.read(64)  # 建立连接并读一点，保持挂起
                while True:
                    if not r.read(1):
                        break
        except Exception:  # noqa: BLE001
            pass

    def test_shi_zhen_yao_zhen_xie_chu_qu(self):
        """连上之后广播的帧必须真的落到 socket 上。

        队列断言（EventBusTests 那一批）只证明帧进了 DingYue 的队列，
        队列到 socket 之间还有写线程。写线程只 `get` 不写的话，订阅者拿到的
        只有连接那一刻的快照，此后所有实时帧被静默吞掉——界面永远停在
        打开页面时的样子，而服务端每一处都正常，最难查的一类。
        """
        shou: list[str] = []
        t = threading.Thread(
            target=self._du_liu,
            args=(self._url(f"/stream?lastEventId={self.z.xu_hao()}"), shou), daemon=True)
        t.start()
        # 等这条 SSE 进了订阅表再广播。同上：`dingyue` 在写线程之前，表里有了
        # 它，这一帧才写得进去。原来是固定 sleep 1.0 猜。
        deng_dai(lambda: len(self.z.lie_ding()) >= 1, chao=10.0,
                 msg=lambda: len(self.z.lie_ding()))
        self.z.fa("state", "s-1", state="working")
        deng_dai(lambda: '"type": "state"' in "".join(shou), chao=8.0,
                 msg=lambda: "".join(shou)[-120:])
        t.join(timeout=2)
        self.assertIn('"type": "state"', "".join(shou),
                      "连上之后广播的帧没写进 SSE 流")

    def _du_liu(self, a1: str, a2: list, a3: float = 8.0) -> None:
        """后台把 SSE 流原样读进 a2（只 decode，不解析）。"""
        try:
            req = urllib.request.Request(a1, headers={"x-bridge-token": self.token})
            with urllib.request.urlopen(req, timeout=a3) as r:
                jixu = time.monotonic() + a3
                while time.monotonic() < jixu:
                    kuai = r.read(1)
                    if not kuai:
                        break
                    a2.append(kuai.decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            pass


class KuaiZhaoTests(unittest.TestCase):
    """快照不许进重放缓冲。

    真机踩过的坑：`fa()` 里 `bu_guang_bo=False` 原本只跳过广播，快照仍然被 append
    进 `huan`。于是重连时 `duibu` 的补发批次里混进一串**过期快照**，客户端把它们
    当普通帧应用，用旧状态覆盖当前状态——症状是早已收口的审批突然复活，
    界面每次重连都被掰回双栏。
    """

    def setUp(self):
        self.z = ZongXian("t")
        self.h = HuiHua(self.z)

    def test_kuai_zhao_bu_jin_chong_fang(self):
        zha = self.z.fa("snapshot", None, bu_guang_bo=False, sessions=[])
        self.assertNotIn(zha["streamSeq"], [s for s, _ in self.z.huan])

    def test_guang_bo_zhen_jin_chong_fang(self):
        zhen = self.z.fa("state", "s-1", state="working")
        self.assertIn(zhen["streamSeq"], [s for s, _ in self.z.huan])

    def test_xu_hao_bu_shou_hui_zhuan_gao_duan(self):
        """调用方传进来的 streamSeq 一律不算数。

        dict 展开是后者覆盖前者。不挡掉的话快照对外宣布的序号比真实序号小 1，
        还会和上一帧撞号——duibu 的补发窗口因此窄一格，那一格里的审批帧被静默
        丢掉，用户看到的是「Agent 卡着不动但其实在等我批准」。
        """
        z = ZongXian("t2")
        z.fa("state", "s-1", state="working")
        zha = z.fa("snapshot", None, bu_guang_bo=False, streamSeq=1, sessions=[])
        self.assertEqual(zha["streamSeq"], 2)

    def test_kuai_zhao_bu_zhan_yong_xu_hao(self):
        """快照上报当前游标，不新分配序号。

        真机踩过：快照走 fa() 分配新 seq，于是它的序号比补发批次里每一帧都大，
        而客户端以快照的 seq 为去重基线 —— 整批补发帧（含还没送达的审批帧）
        被静默丢掉。症状是「Agent 卡着不动，其实在等我批准」。
        """
        z = ZongXian("t3")
        h = HuiHua(z)
        sid = "s-1"
        h.jian(AgentSession(sessionId=sid, agentId="echo", agentLabel="Echo", cwd="d:/x"))
        z.fa("state", sid, state="working")
        qian = z.seq
        zhen = z.duibu(0)
        self.assertEqual(zhen[0]["type"], "snapshot")
        self.assertEqual(zhen[0]["streamSeq"], qian)
        self.assertEqual(z.seq, qian, "快照不该消耗序号")

    def test_duibi_hou_bu_fa_ping_bu_shou_ying_xiang(self):
        z = ZongXian("t4")
        h = HuiHua(z)
        sid = "s-1"
        h.jian(AgentSession(sessionId=sid, agentId="echo", agentLabel="Echo", cwd="d:/x"))
        z.fa("state", sid, state="working")
        yong = z.duibu(5)   # 游标比当前还大
        self.assertEqual([x["type"] for x in yong], ["snapshot"])
        self.assertEqual(yong[0]["streamSeq"], z.seq)

    def test_duibu_mei_you_guo_qi_kuai_zhao(self):
        self.z.fa("state", "s-1", state="working")
        self.z.fa("snapshot", None, bu_guang_bo=False, sessions=[])  # 上一次连接的快照
        self.z.fa("permission", "s-1", request={"requestId": "r-1"})
        zhen = self.z.duibu(0)
        self.assertEqual([z["type"] for z in zhen], ["snapshot", "state", "permission"])


class HuiShangXianTest(unittest.TestCase):
    """并发会话上限（方案 9.4、spec 10.3）：每用户 5 个，超限 409。

    `ownerId` 由 `BridgeHandler._yong()` 在建会话时赋值（阶段 7 任务 1）。
    上限本来就按 `ownerId` 统计，这里测的是**它自己**的四条边界（并发、终态、
    懒恢复、提示语）；**多用户分开计量**在 `tests/test_duoyonghu.py::PeiETest`。
    """

    def _hua(self):
        h = HuiHua(ZongXian("t-sx"))
        h.zong.zhan = h
        return h

    def _hui(self, a1: str, a2: str = "s-x") -> AgentSession:
        return AgentSession(sessionId=a1, agentId="echo", agentLabel="e", cwd=".")

    def test_di_liu_ge_hui_hua_bao_chong_tu(self):
        h = self._hua()
        for i in range(5):
            h.jian(self._hui(f"s-{i}"))
        self.assertEqual(len(h.kua()), 5)
        with self.assertRaises(InvalidTransition):
            h.jian(self._hui("s-5"))
        # **被拒的那次不许留下半条记录。** 检查放在插入之后抛的话，拒掉的
        # 会话已经进了 `_map`，`shan()` 之类的清理也来不及——用户会看到
        # 6 个会话却只有 5 个能跑。
        self.assertEqual(len(h.kua()), 5, "被拒的会话还是插进去了")

    def test_guai_de_hui_hua_bu_suan_shu_mao(self):
        """`ended` 的会话不占名额。

        方案 9.4 的上限是**并发**，不是历史总数。关掉一个再来一个必须能过——
        不然用户跑完第 5 个任务之后就再也开不了新任务了（8.7 记的那个
        场景：「用户完全无法开始新任务，且界面上没有任何东西提示为什么」）
        换个原因又发生一遍。

        走 `idle → thinking → ended`：`idle → ended` 在 6.2 的迁移表里**不存在**
        （照抄那张表会让正常完成任务抛异常），`geng` 是唯一的状态写入口，
        所以不能直接改 `state` 字段来伪造终态。
        """
        h = self._hua()
        for i in range(5):
            h.jian(self._hui(f"s-{i}"))
        h.geng("s-0", "thinking")
        h.geng("s-0", "ended")
        self.assertEqual(h.du("s-0").state, "ended")
        h.jian(self._hui("s-5"))          # 不该抛
        # `kua()` 列出的是**全部**会话（含 ended），所以这里是 6。
        # 上限量的是「非 ended 的个数」，两者不是同一个数——这条断言顺带
        # 把这个区别钉住，免得有人以为上限是历史总数。
        self.assertEqual(len(h.kua()), 6)
        huo = [s for s in h.kua() if s["state"] != "ended"]
        self.assertEqual(len(huo), 5)

    def test_qing_diao_hou_de_hui_hua_bu_zhan_ming_e(self):
        """**懒恢复回来的会话（`alive=False`）不占并发名额。**

        评审指出的更要命的那条：重启后 `run.py:241` 把落盘会话全重置成
        `idle` + `alive=False`（没有活的 `claude` 子进程），于是一条也不该占
        名额。但原判据只看 `state != "ended"`，5 条恢复出来的会话照样占满 5 个
        名额，用户开第 6 个直接 409——而看门狗要等 1800 秒闲置超时才回收。

        症状正是 8.7 记过的那个：「用户完全无法开始新任务，且界面上没有任何
        东西提示为什么」。

        **模拟的是 `run.py` 的懒恢复，不是普通的新建。** 逐字段改 `state` 是
        必要的——`geng` 是唯一的状态写入口，而 `idle → idle` 是同态自环，
        用它改不出 `alive`。
        """
        h = self._hua()
        for i in range(5):
            h.jian(self._hui(f"s-{i}"))
        for s in h._map.values():      # 懒恢复做的事（run.py:240-241）
            s.state = "idle"
            s.alive = False
        h.jian(self._hui("s-5"))       # 不该抛
        # **占名额的只有新建的 s-5 一条**：5 条空壳被 run.py 置了 `alive=False`，
        # 一条都不该占。这里数 `_map` 而不是 `kua()`——后者是 `to_dict()` 之后的
        # dict，取不了 `.state`/`.alive` 属性；`_map` 里存的才是 `AgentSession`。
        huo = [s for s in h._map.values() if s.state != "ended" and s.alive]
        self.assertEqual(len(huo), 1)

    def test_kong_ke_hui_su_huo_hou_zhao_shi_chan_ming_e(self):
        """**空壳被唤醒、真起子进程后重新占名额**——上限不许靠懒恢复绕开。

        上一条证明「没有活进程的会话不占名额」；这一条钉住它的前提：一旦这条
        会话真的被唤醒（`geng()` 进 thinking/working 这类状态，底下起了 `claude`
        子进程），`alive` 必须置回 True，否则唤醒恢复会话就等于免费开进程，每用户
        5 个的上限被整条绕开。

        走 `idle → thinking`：它在 `models.py` 的 `YUNXU` 里，合法。
        """
        h = self._hua()
        for i in range(5):
            h.jian(self._hui(f"s-{i}"))
        for s in h._map.values():      # 懒恢复做的事（run.py:240-241）
            s.state = "idle"
            s.alive = False
        h.jian(self._hui("s-5"))       # 5 条空壳不占名额：放行
        h.jian(self._hui("s-6"))
        h.jian(self._hui("s-7"))
        h.jian(self._hui("s-8"))       # s-5..s-8 四条活的，占 4 个名额
        h.geng("s-0", "thinking")      # 唤醒一条空壳：它重新占名额，凑满 5 个
        with self.assertRaises(InvalidTransition):
            h.jian(self._hui("s-9"))

    def test_qing_diao_qian_de_hui_hua_xiang_bu_zhan_ming_e(self):
        """**活着的会话照旧占名额**——否则重启这条路把并发上限整个废掉了。

        与上一条成对：把判据写成 `state != "ended"` 的一部分就够错了，
        写成「不算 `alive=False`」这一条也不会错，但少一条断言的话，
        「全都不算」这种退化实现照样全绿。
        """
        h = self._hua()
        for i in range(5):
            h.jian(self._hui(f"s-{i}"))
        with self.assertRaises(InvalidTransition):
            h.jian(self._hui("s-5"))

    def test_deng_dai_shen_pi_de_ti_shi_yu_others_bie_ta_yang(self):
        """提示语按状态分支：`attention` 告诉用户「在等你审批」，其余说「先关掉一个」。

        评审实测四种状态都占名额。**`attention` 占名额是对的**（确实在等用户
        审批，Agent 还活着），但对它说「先关掉一个」是把用户引向错误动作：
        他要做的恰恰是**去批**。「先关掉一个」对 `error` / `backoff` 也不成立
        ——那些既没在跑也没在等审批，用户没有一个明确可关的对象。

        判据是**两种文案都在场**。只断言「出现了审批两个字」不够：一个
        把所有状态都改成同一句提示的实现也能过。
        """
        h = self._hua()
        for i in range(5):
            h.jian(self._hui(f"a-{i}"))
            h.geng(f"a-{i}", "attention")
        with self.assertRaises(InvalidTransition) as cm:
            h.jian(self._hui("a-5"))
        self.assertIn("审批", str(cm.exception))

        h2 = self._hua()
        for i in range(5):
            h2.jian(self._hui(f"e-{i}"))
            h2.geng(f"e-{i}", "error")
        with self.assertRaises(InvalidTransition) as cm2:
            h2.jian(self._hui("e-5"))
        self.assertIn("关掉一个", str(cm2.exception))

    def test_bu_tong_yong_hu_bu_xiang_hu_ying_xiang(self):
        """`ownerId` 不同就不算同一用户的并发。

        `ownerId` 已由 `_yong()` 赋值（阶段 7 任务 1）。这条守的是 `HuiHua.jian`
        的**统计口径**（按 ownerId 分桶）；HTTP 层的分桶在
        `tests/test_duoyonghu.py::PeiETest::test_wo_man_le_bie_ren_hai_neng_kai`。
        """
        h = self._hua()
        for i in range(5):
            h.jian(self._hui(f"s-{i}"))
        h.jian(AgentSession(sessionId="s-5", agentId="echo", agentLabel="e",
                            cwd=".", ownerId="u2"))
        self.assertEqual(len(h.kua()), 6)

    def test_bing_fa_jian_bu_neng_chao_shang(self):
        """并发建会话不许放行超过 5 个（锁在 `jian()` 里，不在调用方）。"""
        h = self._hua()
        cheng = []
        suo = threading.Lock()

        def zao(a1: int) -> None:
            try:
                h.jian(self._hui(f"p-{a1}"))
                with suo:
                    cheng.append(a1)
            except InvalidTransition:
                pass

        xian = [threading.Thread(target=zao, args=(i,)) for i in range(12)]
        for t in xian:
            t.start()
        for t in xian:
            t.join()
        self.assertEqual(len(cheng), 5, f"放行了 {len(cheng)} 个")
        self.assertEqual(len(h.kua()), 5)


class HuiShangXianHttpTest(unittest.TestCase):
    """超限在 HTTP 上是 **409**，不是 500（spec 10.3）。

    没有这条映射的话 `InvalidTransition` 掉进 `do_POST` 的裸
    `except Exception`，前端看到的是「服务器内部错误」而不是「会话太多了，
    先关一个」——用户完全不知道该做什么。
    """

    @classmethod
    def setUpClass(cls):
        cls.z = ZongXian(uuid.uuid4().hex[:8])
        cls.h = HuiHua(cls.z)
        cls.z.zhan = cls.h
        cls.g = ShenKa([str(Path(__file__).resolve().parent.parent)])
        cls.token = auth.shengcheng()
        cls.duan = _qi()
        cls.fu = BridgeServer(("127.0.0.1", cls.duan), cls.z, cls.h, cls.g, cls.token)
        threading.Thread(target=cls.fu.serve_forever, daemon=True).start()
        # 构造完就已经 bind+listen，等端口真的连得上，别按固定时长猜。
        deng_dai(lambda: duan_ke(cls.duan), chao=5.0,
                 msg=f"端口 {cls.duan} 连不上")
        cls.root = str(Path(__file__).resolve().parent.parent)

    @classmethod
    def tearDownClass(cls):
        cls.fu.shutdown()
        cls.fu.server_close()

    def _jian(self):
        shu = json.dumps({"agentId": "echo", "cwd": self.root,
                          "clientIdempotencyKey": uuid.uuid4().hex}).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.duan}/sessions", data=shu, method="POST",
            headers={"content-type": "application/json", "x-bridge-token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_chao_shang_409_bu_shi_500(self):
        for _ in range(5):
            s, d = self._jian()
            self.assertEqual(s, 201, d)
        s, d = self._jian()
        self.assertEqual(s, 409, f"超限回的不是 409：{d}")
        self.assertEqual(d["error"]["code"], "conflict")
        # 拒掉的那次不许建出会话
        self.assertEqual(len(self.h.kua()), 5)


class LiuLaiYuanTest(unittest.TestCase):
    """SSE 连接数按**来源**计（spec 10.1：Bridge 那一层，7.2.5 的每用户 8 条）。

    硬编码的 `"local"` 意味着不管谁连都算同一个来源，于是那条上限退化成
    「整台机器一共 8 条 SSE」。真公网形态下（同一条 Bridge 后面挂着多个
    userId 的浏览器）它会误踢别人的连接，而本机形态下又形同虚设。

    **这里验的是「来源真的被记进订阅表」，不是「上限会踢人」** —— 上限那条
    路径（`ZUI_DUO_LIU`）要开 8 条真连接才验得动，而它验的是 `ZUI_DUO_LIU`
    那个常量，不在本次改动范围内。记错来源这件事从表上一眼能看出来。
    """

    def _liu(self, a1: str | None):
        """建一条 SSE 连接，读到响应头就返回（不读完，流本来就挂着）。"""
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.duan}/stream",
            headers={"x-bridge-token": self.token,
                     **({"x-lifeos-source": a1} if a1 else {})})
        r = urllib.request.urlopen(req, timeout=5)
        self.addCleanup(lambda: (r.close(), r.fp and r.fp.close()))
        return r

    @classmethod
    def setUpClass(cls):
        cls.z = ZongXian(uuid.uuid4().hex[:8])
        cls.h = HuiHua(cls.z)
        cls.z.zhan = cls.h
        cls.g = ShenKa([str(Path(__file__).resolve().parent.parent)])
        cls.token = auth.shengcheng()
        cls.duan = _qi()
        cls.yuan = "u-ll"      # 本组用例专用的来源，不会撞上别的类
        cls.fu = BridgeServer(("127.0.0.1", cls.duan), cls.z, cls.h, cls.g, cls.token)
        cls.th = threading.Thread(target=cls.fu.serve_forever, daemon=True)
        cls.th.start()
        deng_dai(lambda: duan_ke(cls.duan), chao=5.0,
                 msg=f"端口 {cls.duan} 连不上")

    @classmethod
    def tearDownClass(cls):
        cls.fu.shutdown()
        cls.fu.server_close()

    def _deng_luo(self, a1: str, a2: int):
        try:
            deng_dai(lambda: self.z.shu_ling(a1) >= a2, chao=8.0,
                     msg=lambda: self.z.shu_ling(a1))
        except AssertionError as e:
            self.fail(f"来源 {a1} 的连接没落进订阅表：{e}")

    def setUp(self):
        # **这个类共用一个 `ZongXian`，订阅表是累积的。** 断言「某来源的连接数
        # 恰好是 0」会被上一条用例留下的连接顶掉——我第一版就那么写的，
        # 单跑绿、跟着另外两条一起跑就红。改成比增量。
        self.dian = {a: self.z.shu_ling(a) for a in ("local", self.yuan)}

    def test_lai_yuan_tou_ji_suan_zai_zhe_ge_yuan(self):
        self._liu(self.yuan)
        self._deng_luo(self.yuan, self.dian[self.yuan] + 1)
        self.assertEqual(self.z.shu_ling("local"), self.dian["local"],
                         "来源头没生效，连接算到了 local 上")

    def test_bu_dai_tou_luo_hui_local(self):
        """**不带头时必须落回 `local`。** 少这个 `or` 的话，本机形态
        （浏览器直连 / vite 代理，都不带这个头）会全部记成 `None`，
        于是「每用户 8 条」在开发机上永远数不到上限。"""
        self._liu(None)
        self._deng_luo("local", self.dian["local"] + 1)

    def test_bu_tong_lai_yuan_hu_bu_xiang_hu_ying_xiang(self):
        self._liu(self.yuan)
        self._deng_luo(self.yuan, self.dian[self.yuan] + 1)
        self.assertEqual(self.z.shu_ling("local"), self.dian["local"],
                         "两个来源被算成了同一个")


if __name__ == "__main__":
    unittest.main()
