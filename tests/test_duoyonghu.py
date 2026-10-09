"""多用户硬化（阶段 7，spec 11.1–11.4、10.3）。

四条不变式，一个域一条（spec 19.1）：

  A. 每条 **HTTP 会话资源**路径都先过归属：每个会话属于且只属于一个 `ownerId`，
     跨 owner 访问一律 **404**，不是 403。**SSE 与 snapshot 不在本不变式内**
     （见总览 §3.1：一台设备对一个账号，接入登录前不按多租户部署）。
  B. 每个 uid 一个凭据目录；目录名单射；建不出只告警不崩。
  C. 每个 `ownerId` 的会话数与请求速率**独立计量**，超限 409 / 429+Retry-After。
  D. 解绑后旧 `deviceToken` 立即不可用、隧道立即断、Bridge 停止重连。

**本文件怎么模拟「两个用户」。** 生产里一个 Bridge 进程只有一个 uid
（`run.py:330` 从 `runtime.json` 的 `userId` 注入）。要在同一个进程里把
「同一条 Bridge、两个人」这条形状测出来，只能在两次请求之间改
`BridgeServer.yong_hu`——`_yong()` 每次请求现取它，所以这等于换了个人。

**别把这条当权宜之计。** 接入登录后 uid 来自 cookie，按请求变；这里改字段
正是在测那条路径的形状。
"""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from unittest import mock

from claude_agent_sdk import ClaudeAgentOptions

from lifeos.api.dangqian import YongHuFeiFa
from lifeos.bridge import auth, pingju
from lifeos.bridge.events import ZongXian
from lifeos.bridge.http import BridgeServer, YiWu
from lifeos.bridge.models import AgentSession, guo_lu1
from lifeos.bridge.planner_guard import ShenKa
from lifeos.bridge.session import ZUI_DUO_HUI, HuiHua
from gong_ju import deng_dai, duan_ke

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _qi(a1: int = 0) -> int:
    """占一个空闲端口再放开。照抄 `tests/test_bridge_transport.py` 的同名函数。"""
    with socket.socket() as s:
        s.bind(("127.0.0.1", a1))
        return s.getsockname()[1]


class HuiGuiShuTest(unittest.TestCase):
    """域 A：会话归属。跨 owner 一律 404（spec 10.3、11.3）。"""

    @classmethod
    def setUpClass(cls):
        cls.z = ZongXian(uuid.uuid4().hex[:8])
        cls.h = HuiHua(cls.z)
        cls.z.zhan = cls.h
        cls.g = ShenKa([str(Path(__file__).resolve().parent.parent)])
        cls.token = auth.shengcheng()
        cls.duan = _qi()
        cls.fu = BridgeServer(("127.0.0.1", cls.duan), cls.z, cls.h, cls.g, cls.token)
        cls.fu.yong_hu = "alice"
        threading.Thread(target=cls.fu.serve_forever, daemon=True).start()
        deng_dai(lambda: duan_ke(cls.duan), chao=5.0, msg=f"端口 {cls.duan} 连不上")
        cls.root = str(Path(__file__).resolve().parent.parent)

    @classmethod
    def tearDownClass(cls):
        cls.fu.shutdown()
        cls.fu.server_close()

    # ---- 两个真 HTTP 辅助（形状照抄 test_bridge_transport.TransportTests） ----
    def _url(self, a1: str) -> str:
        return f"http://127.0.0.1:{self.duan}{a1}"

    def _get(self, a1: str, a2: dict | None = None):
        u = self._url(a1)
        if a2:
            jie = "&" if "?" in u else "?"
            u += jie + "&".join(f"{k}={v}" for k, v in a2.items())
        req = urllib.request.Request(u)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _post(self, a1: str, a2: dict | None = None):
        shu = json.dumps(a2 or {}).encode("utf-8")
        req = urllib.request.Request(
            self._url(a1), data=shu, method="POST",
            headers={"content-type": "application/json", "x-bridge-token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def setUp(self):
        # **每条用例开始时把人换回 alice、清掉会话表。** 这个类共用一个
        # BridgeServer，上一条用例建的会话会留在 `_map` 里——不清的话
        # 「alice 有 1 个会话」这种断言会被前一条顶掉（单跑绿、连跑红）。
        self.fu.yong_hu = "alice"
        for s in list(self.h.kua()):
            self.h.shan(s["sessionId"])

    def _jian(self, a1: str | None = None, a2: str | None = None):
        """建一个会话。a1 是 clientIdempotencyKey，a2 是 agentId。"""
        body = {"agentId": a2 or "echo", "cwd": self.root}
        if a1:
            body["clientIdempotencyKey"] = a1
        return self._post("/sessions", body)

    def _zhuai(self, a1: str) -> str:
        """取 transcript 的状态码。这条路径**自己查 hua.du，绕过收口**，
        是最容易漏的一条，所以单独拎出来反复用。"""
        s, _ = self._get(f"/sessions/{a1}/transcript", {"token": self.token})
        return s

    # ---- 建会话就要带对 ownerId ----
    def test_jian_hui_shu_yu_dang_qian_ren(self):
        s, d = self._jian()
        self.assertEqual(s, 201, d)
        self.assertEqual(d["session"]["ownerId"], "alice")

    def test_huan_le_ren_jian_de_hui_hua_shu_yu_ta(self):
        self.fu.yong_hu = "bob"
        s, d = self._jian()
        self.assertEqual(s, 201, d)
        self.assertEqual(d["session"]["ownerId"], "bob")

    # ---- 跨 owner 访问：四条资源入口，全是 404 ----
    def test_kua_ren_quan_wen_404(self):
        s, d = self._jian()
        sid = d["session"]["sessionId"]
        self.assertEqual(self._zhuai(sid), 200, "本人读自己的全文被挡了")
        self.fu.yong_hu = "bob"
        code, chu = self._get(f"/sessions/{sid}/transcript", {"token": self.token})
        self.assertEqual(code, 404, f"跨用户读到了全文：{chu}")
        self.assertEqual(chu["error"]["code"], "not_found")

    def test_kua_ren_fa_xiao_xi_404(self):
        s, d = self._jian()
        sid = d["session"]["sessionId"]
        self.fu.yong_hu = "bob"
        code, chu = self._post(f"/sessions/{sid}/messages", {"text": "hi"})
        self.assertEqual(code, 404, f"跨用户发到了消息：{chu}")
        self.assertEqual(chu["error"]["code"], "not_found")

    def test_kua_ren_guan_bi_404(self):
        s, d = self._jian()
        sid = d["session"]["sessionId"]
        self.fu.yong_hu = "bob"
        code, chu = self._post(f"/sessions/{sid}/close")
        self.assertEqual(code, 404, f"跨用户关掉了别人的会话：{chu}")

    def test_kua_ren_gai_mo_shi_404(self):
        s, d = self._jian()
        sid = d["session"]["sessionId"]
        self.fu.yong_hu = "bob"
        code, chu = self._post(f"/sessions/{sid}/mode", {"permissionMode": "auto"})
        self.assertEqual(code, 404, f"跨用户改掉了别人的模式：{chu}")

    def test_kua_ren_duan_404(self):
        s, d = self._jian()
        sid = d["session"]["sessionId"]
        self.fu.yong_hu = "bob"
        code, chu = self._post(f"/sessions/{sid}/interrupt")
        self.assertEqual(code, 404, f"跨用户打断了别人的会话：{chu}")

    # ---- 判据落在分岔量上：404 不是 403 ----
    def test_kua_ren_bu_shi_403(self):
        """spec 10.3：不泄露资源是否存在。

        判据是**状态码本身**。只断言「请求失败」不够——一个返回 403 的实现
        也满足「失败」，而 403 恰恰泄露了「这个 sid 是存在的」。
        """
        s, d = self._jian()
        sid = d["session"]["sessionId"]
        self.fu.yong_hu = "bob"
        code, chu = self._get(f"/sessions/{sid}/transcript", {"token": self.token})
        self.assertEqual(code, 404)
        self.assertNotEqual(code, 403)
        self.assertNotEqual(chu["error"]["code"], "forbidden")

    # ---- 过滤不许写过头 ----
    def test_ben_ren_du_de_dao(self):
        s, d = self._jian()
        sid = d["session"]["sessionId"]
        self.fu.yong_hu = "alice"
        self.assertEqual(self._zhuai(sid), 200, "过滤把自己也挡了")

    def test_wen_ben_de_hui_hua_huan_ge_ren_hai_neng_du(self):
        """uid 只换大小写/末尾点也不算同一个人？

        **算不同的人**：`dangqian.he_fa` 挡的是字符集，`pingju.mu_lu_ming` 用哈希
        挡的是 Windows 路径折叠。归属比较是**字符串全等**，`alice` 与 `Alice`
        是两个 ownerId——这条把「有人拿大小写当同一人」的退化实现钉住。
        """
        s, d = self._jian()
        sid = d["session"]["sessionId"]
        self.fu.yong_hu = "Alice"
        self.assertEqual(self._zhuai(sid), 404, "大小写不同的 uid 被当成同一个人")

    # ---- 幂等键：按人分命名空间 ----
    def test_ming_deng_jian_an_ren_fen_kai(self):
        """**Review Focus #1。** B 复用 A 的 `clientIdempotencyKey` 时必须拿到
        自己的新会话，绝不拿到 A 的会话对象（里面有 A 的 `cwd` 与 `title`）。

        判据是**两边的 sessionId 不同**。只断言「B 的请求成功了」不够——
        一个把 A 的会话原样吐回来的实现也回 200。
        """
        k = uuid.uuid4().hex
        s, a = self._jian(k)
        self.assertEqual(s, 201, a)
        self.fu.yong_hu = "bob"
        s2, b = self._jian(k)
        self.assertEqual(s2, 201, b)
        self.assertNotEqual(a["session"]["sessionId"], b["session"]["sessionId"],
                           "幂等键跨用户命中了别人的会话")
        self.assertEqual(b["session"]["ownerId"], "bob")

    def test_ming_deng_jian_tong_yi_ren_reng_ling(self):
        """同一个人重放同一个键，**必须拿回同一个会话**——这是幂等键的本职。

        与上一条成对：只写「按人分命名空间」而不验「同人仍幂等」，
        一个每次都新建会话的实现也全绿，幂等键就白做了。
        """
        k = uuid.uuid4().hex
        s, a = self._jian(k)
        s2, b = self._jian(k)
        self.assertEqual(s, 201)
        # **重放是 200 不是 201。** 第一次建会话才创建（201），命中缓存的那次
        # 没有创建任何东西——回 201 等于告诉客户端「又建了一个」。
        self.assertEqual(s2, 200, b)
        self.assertEqual(a["session"]["sessionId"], b["session"]["sessionId"])
        self.assertEqual(len(self.h.kua()), 1, "同人重放又建了一个会话")

    # ---- ownerId 落盘 + 恢复（guo_lu1 全字段） ----
    def test_bei_shu_luo_pan_hui_fu(self):
        """`ownerId` 必须跟着落盘走，恢复回来还在。

        这条是**真机第 1 步的前提**：`run.hui_fu` 恢复出来的会话带着原主人的
        ownerId，跨用户 404 才有东西可判。字段丢了一切过滤都退化成「全都放行」。
        """
        s, d = self._jian()
        hui = self.h.du(d["session"]["sessionId"])
        hui.ownerId = "carol"          # 手上这份是「落盘前」的内存对象
        pan = hui.to_dict()            # 落盘写的就是 to_dict()
        hui2 = AgentSession(**guo_lu1(AgentSession, pan))
        self.assertEqual(hui2.ownerId, "carol", "ownerId 没跟着落盘恢复")
        self.assertEqual(hui2.sessionId, hui.sessionId)

    def test_bei_shu_bu_zai_shi_jiu_mo_ren_local(self):
        """`guo_lu1` 只留 dataclass 声明过的字段；`ownerId` 在里面。

        退化实现是「恢复时给 ownerId 一个默认值」——那样跨用户 404 会退化成
        「全都判给 local」，两个人看到的是同一份。判据是恢复后的值**等于
        落盘的值**，不是等于某个默认值。
        """
        pan = AgentSession(sessionId="s-t", agentId="echo", agentLabel="e",
                           cwd=".", ownerId="dave").to_dict()
        hui = AgentSession(**guo_lu1(AgentSession, pan))
        self.assertEqual(hui.ownerId, "dave")
        self.assertNotEqual(hui.ownerId, "local")


class ShenPiGuiShuTest(unittest.TestCase):
    """域 A 下半：审批与提问挂在会话上，归属经 `sessionId` 回溯。

    审批卡与提问卡是**跨用户最危险的两个入口**：它们不带 sid，只带
    `requestId` / `questionId`，而这两个 id 是客户端拿着就能猜的短串。
    猜中就能替别人批准工具调用——那是一次「写」，比读全文更重。
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
        cls.fu.yong_hu = "alice"
        threading.Thread(target=cls.fu.serve_forever, daemon=True).start()
        deng_dai(lambda: duan_ke(cls.duan), chao=5.0, msg=f"端口 {cls.duan} 连不上")
        cls.root = str(Path(__file__).resolve().parent.parent)

    @classmethod
    def tearDownClass(cls):
        cls.fu.shutdown()
        cls.fu.server_close()

    def _post(self, a1: str, a2: dict | None = None):
        shu = json.dumps(a2 or {}).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.duan}{a1}", data=shu, method="POST",
            headers={"content-type": "application/json", "x-bridge-token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def setUp(self):
        # 与 `HuiGuiShuTest` 同一条纪律：共用一个 BridgeServer，每条用例开始时
        # 把人换回 alice、清掉会话表与挂起表。否则「本人能批」这类断言会被前一条
        # 用例留下的挂起项顶掉（单跑绿、连跑红）。
        self.fu.yong_hu = "alice"
        for s in list(self.h.kua()):
            self.h.shan(s["sessionId"])
        self.fu.shen_qing._pending.clear()
        self.fu.shen_qing._wenti.clear()
        self.fu.shen_qing.jue_chao.clear()
        # `wen_chao` 在实现落地前还不存在，这里放过它。setUp 的清理是卫生，
        # 不是被测行为——真正盯着这个字段的是 `test_wen_chao_dai_hui_hua_bian_shi`。
        # 不放过的话实现前这 12 条会全死在 setUp 里：红是红了，但红的原因是
        # AttributeError 而不是「跨用户批掉了别人的审批」，那样 RED 与变异
        # 验证都失去意义（护栏永远红，改坏改好都一样）。
        wen = getattr(self.fu.shen_qing, "wen_chao", None)
        if wen is not None:
            wen.clear()

    def _hui(self, a1: str, a2: str = "alice") -> str:
        """直接在会话表里放一个会话。这里测的是归属，不必走 HTTP 建会话。"""
        self.h.jian(AgentSession(sessionId=a1, agentId="echo", agentLabel="e",
                                 cwd=self.root, ownerId=a2))
        return a1

    def _dai_jue(self, a1: str, a2: str) -> str:
        """登记一条挂起审批，返回 requestId。"""
        from lifeos.bridge.arbiter import DaiJue
        d = DaiJue(requestId=a1, sessionId=a2, agentId="echo",
                   toolName="Bash", toolInput={"command": "echo hi"})
        self.fu.shen_qing._pending[a1] = d
        return a1

    def _dai_wen(self, a1: str, a2: str) -> str:
        """登记一条挂起提问，返回 questionId。"""
        from lifeos.bridge.arbiter import DaiWen
        q = DaiWen(questionId=a1, sessionId=a2, toolUseId="t-1",
                   questions=[{"type": "text", "label": "?", "key": "k"}])
        self.fu.shen_qing._wenti[a1] = q
        return a1

    # ---- 审批 ----
    def test_kua_ren_shen_pi_404(self):
        self._hui("s-a", "alice")
        self._dai_jue("p-1", "s-a")
        self.fu.yong_hu = "bob"
        code, chu = self._post("/permissions/p-1", {"decision": "deny"})
        self.assertEqual(code, 404, f"跨用户批掉了别人的审批：{chu}")
        self.assertEqual(chu["error"]["code"], "not_found")

    def test_kua_ren_shen_pi_bu_shi_403(self):
        self._hui("s-a", "alice")
        self._dai_jue("p-2", "s-a")
        self.fu.yong_hu = "bob"
        code, chu = self._post("/permissions/p-2", {"decision": "deny"})
        self.assertEqual(code, 404)
        self.assertNotEqual(chu["error"]["code"], "forbidden")

    def test_ben_ren_shen_pi_tong_guo(self):
        self._hui("s-a", "alice")
        self._dai_jue("p-3", "s-a")
        code, chu = self._post("/permissions/p-3", {"decision": "deny"})
        self.assertEqual(code, 200, chu)
        self.assertTrue(chu["ok"])

    def test_yi_shou_de_shen_pi_bu_xie_lu(self):
        """**Review Focus #2。** B 猜对一个 A **已经批过**的 requestId 时，
        必须回 404，不能回 409 `already_resolved`。

        409 会告诉 B「这个 id 存在，只是批过了」——spec 10.3 要的是不泄露
        资源是否存在。判据是**状态码**，不是「请求失败了」。
        """
        self._hui("s-a", "alice")
        self._dai_jue("p-4", "s-a")
        code, _ = self._post("/permissions/p-4", {"decision": "deny"})
        self.assertEqual(code, 200)          # A 自己批掉
        self.fu.yong_hu = "bob"
        code2, chu = self._post("/permissions/p-4", {"decision": "deny"})
        self.assertEqual(code2, 404, f"泄露了「已收口」：{chu}")
        self.assertNotEqual(code2, 409)

    def test_ben_ren_yi_shou_de_shen_pi_shi_409(self):
        """本人重复批同一条 → **409**，不是 404。

        与上一条成对：只写「已收口回 404」会把本人的诊断也弄丢——
        前端会把卡片关掉，用户以为批准了、Agent 实际收到的是拒绝。
        """
        self._hui("s-a", "alice")
        self._dai_jue("p-5", "s-a")
        self._post("/permissions/p-5", {"decision": "deny"})
        code, chu = self._post("/permissions/p-5", {"decision": "deny"})
        self.assertEqual(code, 409, chu)
        self.assertEqual(chu["error"]["code"], "already_resolved")

    def test_bu_cun_zai_de_shen_pi_shi_404(self):
        code, chu = self._post("/permissions/p-bu-cun-zai", {"decision": "deny"})
        self.assertEqual(code, 404)
        self.assertEqual(chu["error"]["code"], "not_found")

    # ---- 提问 ----
    def test_kua_ren_ti_wen_404(self):
        self._hui("s-a", "alice")
        self._dai_wen("q-1", "s-a")
        self.fu.yong_hu = "bob"
        code, chu = self._post("/questions/q-1", {"answers": [{"key": "k",
                                                              "values": ["v"]}]})
        self.assertEqual(code, 404, f"跨用户答掉了别人的提问：{chu}")
        self.assertEqual(chu["error"]["code"], "not_found")

    def test_ben_ren_ti_wen_tong_guo(self):
        self._hui("s-a", "alice")
        self._dai_wen("q-2", "s-a")
        code, chu = self._post("/questions/q-2", {"answers": [{"key": "k",
                                                              "values": ["v"]}]})
        self.assertEqual(code, 200, chu)
        self.assertTrue(chu["ok"])

    def test_bu_cun_zai_de_ti_wen_shi_404_bu_shi_409(self):
        """**`_da_wen` 原来一律回 409。** 拿一个错的 `questionId` 会被告知
        「已被收口」，而用户从来没见过这个提问——提示语把人引向错误结论。

        判据是 404 **且** code 是 `not_found`。只断言「不是 200」不够：
        一个永远回 409 的实现也满足。
        """
        code, chu = self._post("/questions/q-bu-cun-zai",
                               {"answers": [{"key": "k", "values": ["v"]}]})
        self.assertEqual(code, 404, f"不存在的提问回了：{chu}")
        self.assertEqual(chu["error"]["code"], "not_found")

    def test_ben_ren_yi_shou_de_ti_wen_shi_409(self):
        self._hui("s-a", "alice")
        self._dai_wen("q-3", "s-a")
        body = {"answers": [{"key": "k", "values": ["v"]}]}
        self._post("/questions/q-3", body)
        code, chu = self._post("/questions/q-3", body)
        self.assertEqual(code, 409, chu)
        self.assertEqual(chu["error"]["code"], "already_resolved")

    def test_yi_shou_de_ti_wen_bu_xie_lu(self):
        self._hui("s-a", "alice")
        self._dai_wen("q-4", "s-a")
        self._post("/questions/q-4", {"answers": [{"key": "k", "values": ["v"]}]})
        self.fu.yong_hu = "bob"
        code, chu = self._post("/questions/q-4",
                               {"answers": [{"key": "k", "values": ["v"]}]})
        self.assertEqual(code, 404, f"泄露了「已收口」：{chu}")
        self.assertNotEqual(code, 409)

    # ---- wen_chao 形状 ----
    def test_wen_chao_dai_hui_hua_bian_shi(self):
        """`wen_chao` 每条都必须带 `sessionId`——已收口分支靠它做归属校验。

        少了这个字段，跨用户「已收口」那条分支就没法判归属，只能放行 409，
        Review Focus #2 的护栏就守不住。
        """
        self._hui("s-a", "alice")
        self._dai_wen("q-5", "s-a")
        self._post("/questions/q-5", {"answers": [{"key": "k", "values": ["v"]}]})
        ji = [x for x in self.fu.shen_qing.wen_chao if x.get("questionId") == "q-5"]
        self.assertTrue(ji, "wen_chao 里没有 q-5")
        self.assertEqual(ji[-1].get("sessionId"), "s-a")
        self.assertIn(ji[-1].get("state"), ("answered", "expired", "cancelled"))


class PeiETest(unittest.TestCase):
    """域 C：每个 `ownerId` 的会话数**独立计量**（spec 10.3）。

    任务 1 之前 `ownerId` 恒为 `"local"`，于是 `ZUI_DUO_HUI` 是**全局**上限
    ——A 开满 5 个，B 一个都开不了。这条上限写得没错，缺的是让它分开的那个值。

    **限流的三条窗口不在这里测**（每用户 60/60s、每设备 20/60s、审批类 30/60s
    独立窗口）。它们的 key 是 `(userId, deviceId, path)`，`userId` 来自隧道握手，
    天然是真值；这里守的是**会话数**这一条，它的 key 是 `AgentSession.ownerId`。
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
        cls.fu.yong_hu = "alice"
        threading.Thread(target=cls.fu.serve_forever, daemon=True).start()
        deng_dai(lambda: duan_ke(cls.duan), chao=5.0, msg=f"端口 {cls.duan} 连不上")
        cls.root = str(Path(__file__).resolve().parent.parent)

    @classmethod
    def tearDownClass(cls):
        cls.fu.shutdown()
        cls.fu.server_close()

    def setUp(self):
        self.fu.yong_hu = "alice"
        for s in list(self.h.kua()):
            self.h.shan(s["sessionId"])

    def _post(self, a1: str, a2: dict | None = None):
        shu = json.dumps(a2 or {}).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.duan}{a1}", data=shu, method="POST",
            headers={"content-type": "application/json", "x-bridge-token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _jian(self):
        return self._post("/sessions", {"agentId": "echo", "cwd": self.root,
                                        "clientIdempotencyKey": uuid.uuid4().hex})

    def test_di_liu_ge_409(self):
        """第 6 个必须 409，且被拒的那次不许留下半条记录。"""
        for i in range(5):
            s, d = self._jian()
            self.assertEqual(s, 201, d)
        s, d = self._jian()
        self.assertEqual(s, 409, f"超限回的不是 409：{d}")
        self.assertEqual(d["error"]["code"], "conflict")
        self.assertEqual(len(self.h.kua()), 5, "被拒的会话还是插进去了")

    def test_wo_man_le_bie_ren_hai_neng_kai(self):
        """**本任务唯一的真分岔判据。** A 开满 5 个之后，B 必须还能开第 1 个。

        `ownerId` 不赋值时 `ZUI_DUO_HUI` 是全局上限，B 的第 1 个直接 409；
        赋了值才分开。

        只断言「B 的请求成功了」不够——一个把上限写成 10 的实现也让两边都成功。
        判据是 **A 满 + B 前后各 5 个都 201、B 第 6 个 409** 这几件事**同时
        成立**：少了后半段，B 那边其实没在计量；少了前半段，A 那边没在封顶。
        """
        for i in range(5):
            s, _ = self._jian()
            self.assertEqual(s, 201)
        self.fu.yong_hu = "bob"
        s, d = self._jian()
        self.assertEqual(s, 201, f"B 的第 1 个被 A 的上限挡了：{d}")
        self.assertEqual(d["session"]["ownerId"], "bob")
        # 各自 5 条，互不越界
        s2, d2 = self._jian()
        s3, d3 = self._jian()
        s4, d4 = self._jian()
        s5, d5 = self._jian()
        for x in (s2, s3, s4, s5):
            self.assertEqual(x, 201, "B 自己还没满就被拒了")
        s6, d6 = self._jian()
        self.assertEqual(s6, 409, f"B 也不该超过 5：{d6}")
        self.assertEqual(len(self.h.kua()), 10, "两人各 5 条，总数不是 10")

    def test_hui_fu_de_bu_zhan_wo_de_ming_e(self):
        """别人的**正在跑**的会话不占我的并发名额。

        背景是懒恢复（`run.py:246`）**不按 uid 过滤**——它把 `--root` 下所有
        会话灌回内存。这是刻意的：过滤发生在访问时（`_dui_hui`），
        恢复时过滤会让「跨用户 404」在真机上退化成「表里根本没这条」，
        于是那条断言成了假绿。

        但代价必须钉住：灌进来的 5 条别人的会话不许占掉我的 5 个名额。

        **2026-10-02 修正：那 5 条必须是「占名额」的形态。** 原稿把它们设成
        `state="idle"; alive=False`，而 `HuiHua.jian` 只数 `state != "ended" and
        alive`（`session.py:93-95`）——空壳对任何人都不占名额，owner 过滤写没写
        都放行，判据落在另一件事上（那是
        `test_qing_diao_hou_de_hui_hua_bu_zhan_ming_e` 守的）。改成
        `state="working"; alive=True` 之后，去掉 owner 过滤这条必红：
        bob 的 5 条会把 alice 的第 1 个挡成 409。
        """
        for i in range(5):
            self.h.jian(AgentSession(sessionId=f"s-b-{i}", agentId="echo",
                                     agentLabel="e", cwd=self.root, ownerId="bob"))
        # 这 5 条模拟「bob 正在跑的会话」：占 bob 的名额，不占 alice 的。
        for s in self.h._map.values():
            s.state = "working"
            s.alive = True
        self.fu.yong_hu = "alice"
        s, d = self._jian()
        self.assertEqual(s, 201, f"别人的会话占了我的名额：{d}")
        self.assertEqual(d["session"]["ownerId"], "alice")
        # **分岔判据的另一半**：bob 自己这 5 条确实占着名额。少了这条，上面那个
        # 201 也可能只是因为「谁的都不算」——又是一种假绿。
        self.fu.yong_hu = "bob"
        s2, d2 = self._jian()
        self.assertEqual(s2, 409, f"bob 自己的 5 条没占名额：{d2}")

    def test_hui_fu_de_ye_bu_neng_kua_ren_du(self):
        """恢复出来的会话照样受归属过滤——它只是换了地方存，规则没变。"""
        self.h.jian(AgentSession(sessionId="s-b-0", agentId="echo",
                                 agentLabel="e", cwd=self.root, ownerId="bob"))
        self.fu.yong_hu = "alice"
        code, chu = self._get(f"/sessions/s-b-0/transcript", {"token": self.token})
        self.assertEqual(code, 404, f"读到了别人的恢复会话：{chu}")
        self.fu.yong_hu = "bob"
        code2, _ = self._get(f"/sessions/s-b-0/transcript", {"token": self.token})
        self.assertEqual(code2, 200, "本人读自己的恢复会话被挡了")

    def _get(self, a1: str, a2: dict | None = None):
        u = f"http://127.0.0.1:{self.duan}{a1}"
        if a2:
            jie = "&" if "?" in u else "?"
            u += jie + "&".join(f"{k}={v}" for k, v in a2.items())
        try:
            with urllib.request.urlopen(urllib.request.Request(u), timeout=5) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_tong_yi_ren_de_ming_deng_bu_zhan_ming_e(self):
        """同一个人重放 `clientIdempotencyKey` 不占第二个名额。

        **判据是会话表里只有一条**，不是状态码：第一次 201（真建了），
        后两次 200（命中缓存，没建任何东西——回 201 等于告诉客户端「又建了
        一个」，见 `test_ming_dang_jian_tong_yi_ren_reng_ling`）。
        """
        k = uuid.uuid4().hex
        s, _ = self._post("/sessions", {"agentId": "echo", "cwd": self.root,
                                        "clientIdempotencyKey": k})
        self.assertEqual(s, 201)
        for _ in range(2):
            s2, _ = self._post("/sessions", {"agentId": "echo", "cwd": self.root,
                                             "clientIdempotencyKey": k})
            self.assertEqual(s2, 200, "幂等重放回的不是 200")
        self.assertEqual(len(self.h.kua()), 1, "幂等重放建出了第二个会话")


class YuSuanTest(unittest.TestCase):
    """**取消单会话预算上限**（用户 2026-10-02 裁定）。

    `ClaudeAgentOptions.max_budget_usd` 必须是 `None`——这不是「默认恰好是
    None」，而是**根本不下发**：SDK 的
    `_internal/transport/subprocess_cli.py:613` 只在 `is not None` 时才
    `cmd.extend(["--max-budget-usd", ...])`，所以 `None` 表示压根不给这个 flag，
    传 `-1` 会被原样交给 CLI。**每用户 5 并发会话的上限与此无关，保留。**
    """

    def _xuan_ze(self, a1: dict) -> ClaudeAgentOptions:
        """跑一遍 `kaishi`，拿回它真传给 SDK 的那组 options（含默认值）。"""
        import asyncio
        from unittest import mock

        from lifeos.bridge.adapters import claude_code as cc

        kan: dict = {}

        async def _lian_ji(self):
            self.guan_le = False

        def _jia(a2):
            return type("K", (), {"connect": _lian_ji})()

        def _zhen(**kw):
            kan.update(kw)
            return ClaudeAgentOptions(**kw)     # 真类，保留默认值

        async def _pao():
            with mock.patch.object(cc, "ClaudeAgentOptions", _zhen), \
                    mock.patch.object(cc, "ClaudeSDKClient", _jia):
                await cc.ClaudeCodeAdapter().kaishi(a1)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_pao())
        finally:
            loop.close()
        return ClaudeAgentOptions(**kan)

    def test_mo_ren_qing_xiang_biao_mian_shi_bu_xia_fa(self):
        """不传 `maxBudgetUsd` 时就**不下发**这个参数。

        判据是取回的真 options 上的值，不是源码里有没有那一行。
        """
        xuan = self._xuan_ze({"cwd": "."})
        self.assertIsNone(xuan.max_budget_usd,
                          "单会话预算没取消：请求体里没传也设了一个上限")

    def test_qing_qiu_ti_ming_chuan_le_ye_bu_zhao_chi(self):
        """**请求体里显式传 `maxBudgetUsd` 也一律忽略。**

        「取消单会话预算」= 服务端不设，也不接受调用方设。留着
        `a1.get("maxBudgetUsd")` 这个入口等于换个名字把单会话预算留着，
        而一条只断言默认路径的护栏看不见它——只断言默认路径的话，
        一个「保留 `a1.get` 入口」的实现也全绿。

        字段本身保留在前端契约里（不删），只是不再读。删字段是破坏性变更，
        而忽略它已经达到了「不设预算」的全部效果。
        """
        xuan = self._xuan_ze({"cwd": ".", "maxBudgetUsd": 3.0})
        self.assertIsNone(xuan.max_budget_usd,
                          "请求体里的 maxBudgetUsd 仍然生效")

    def test_mei_yong_hu_wu_ge_bing_fa_hui_hua_ren_shang_xian_ren_ran_zai(self):
        """取消预算是**只**取消预算——每用户 5 并发会话的上限一个字都没动。

        与上两条成对：只钉「预算没了」的话，一个把
        `ZUI_DUO_HUI` 一起删掉的实现也全绿，而那个上限是本任务另一半的全部内容。
        """
        self.assertEqual(ZUI_DUO_HUI, 5)


class GeLiTest(unittest.TestCase):
    """域 B：逐用户凭据隔离的**衔接**层。

    `tests/test_pingju.py` 已经把 `pingju` 自己验得很全（见本任务的对照表）：
    单射、权限收紧、降级只告警、`credentialsReady` 全都在那边逐条钉过。
    这里只补它测不到的那层——**`pingju` 是自己验自己**，`run.py` 怎么注入、
    `BridgeServer` 上那两个字段同不同源、HTTP 层看到的 `ownerId` 指向谁，
    它一条都碰不到。

    **本类最重要的护栏是「同源」，不是「隔离」。**
    凭据目录按 `pingju.huan_jing(uid)` 建，归属按 `_yong()` 读
    `BridgeServer.yong_hu` 判。两者是**两个独立字段**，分叉了不会有人报错：
    现象是「alice 的会话用 bob 的凭据跑」，而隔离与归属**各自都绿**。
    """

    @classmethod
    def setUpClass(cls):
        cls.z = ZongXian(uuid.uuid4().hex[:8])
        cls.h = HuiHua(cls.z)
        cls.z.zhan = cls.h
        cls.gen0 = str(Path(__file__).resolve().parent.parent)
        cls.g = ShenKa([cls.gen0])
        cls.token = auth.shengcheng()
        cls.duan = _qi()
        cls.fu = BridgeServer(("127.0.0.1", cls.duan), cls.z, cls.h, cls.g, cls.token)
        cls.fu.yong_hu = "alice"
        threading.Thread(target=cls.fu.serve_forever, daemon=True).start()
        deng_dai(lambda: duan_ke(cls.duan), chao=5.0, msg=f"端口 {cls.duan} 连不上")

    @classmethod
    def tearDownClass(cls):
        cls.fu.shutdown()
        cls.fu.server_close()

    def setUp(self):
        # **全局状态必须自己存还。** `pingju.PINGJU_GEN` 与
        # `JIAN_BING_CHENG_GONG` 都是模块级变量，整个 pytest 进程共享一个
        # 模块实例：不还原的话，同进程里后面跑到的 `test_pingju.py`
        # 会被我留下的临时目录 / 假标志污染（阶段 6 记过同源事故）。
        self.mu = tempfile.TemporaryDirectory()
        self.addCleanup(self.mu.cleanup)
        self.addCleanup(setattr, pingju, "PINGJU_GEN", pingju.PINGJU_GEN)
        self.addCleanup(setattr, pingju, "JIAN_BING_CHENG_GONG",
                         pingju.JIAN_BING_CHENG_GONG)
        # 这个类共用一个 BridgeServer，把人换回 alice 并清掉上一条留下的会话
        # （`HuiGuiShuTest` 记过：不清的话「alice 有 1 个会话」会被前一条顶掉）。
        self.fu.yong_hu = "alice"
        for s in list(self.h.kua()):
            self.h.shan(s["sessionId"])

    def _post(self, a1: str, a2: dict | None = None):
        shu = json.dumps(a2 or {}).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.duan}{a1}", data=shu, method="POST",
            headers={"content-type": "application/json", "x-bridge-token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _get(self, a1: str, a2: dict | None = None):
        u = f"http://127.0.0.1:{self.duan}{a1}"
        if a2:
            jie = "&" if "?" in u else "?"
            u += jie + "&".join(f"{k}={v}" for k, v in a2.items())
        try:
            with urllib.request.urlopen(urllib.request.Request(u), timeout=5) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _zhen(self, a1: dict):
        """真跑一遍 `run.zhen_ben`，返回它建出来的 BridgeServer。

        **要真跑而不是自己拼一个 server 赋值**：这层护栏守的正是
        `run.py:327-330` 那两行。手工 new 一个 server、把同一个字面量赋给
        `env` 与 `yong_hu`，无论生产代码把那两行写成什么不同的表达式都绿——
        那是护栏写了个寂寞（计划文档里的示例代码正是这个形状）。

        三个坑，每一个都在别的测试文件里被记过：
        1. 不用 `TemporaryDirectory`——`zhen_ben` 往 `<root>/.lifeos/bridge/`
           挂 RotatingFileHandler，句柄整个进程都不关，退出时 rmtree 撞上它
           会 WinError 32，报错点还落在 `__exit__` 上（`test_pingju.RunTest`）。
        2. `zhen_ben` 改 `BridgeHandler` 的**类属性**（`token`/`zong`/`hua`/
           `shen_qing`/`ri`），而 handler 通过类属性取这些单例。它一改，
           本类那个已经起好的 server 就开始认新 token，于是后面每条 HTTP
           用例全 401。所以这里逐个存还。
        3. 只 `server_close()`，**不调 `shutdown()`**——后者等
           `serve_forever()` 退出，而这里压根没起服务。
        """
        import shutil

        from lifeos.bridge import run
        from lifeos.bridge.http import BridgeHandler

        gen = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, gen, True)
        (gen / ".lifeos" / "bridge").mkdir(parents=True)
        (gen / ".lifeos" / "bridge" / "runtime.json").write_text(
            json.dumps(a1), encoding="utf-8")

        # 第 2 条：存还 zhen_ben 会覆盖的每一个类属性。
        for n in ("zong", "hua", "shen", "token", "shen_qing", "ri"):
            self.addCleanup(setattr, BridgeHandler, n, getattr(BridgeHandler, n))
            setattr(BridgeHandler, n, None)
        with mock.patch.object(run, "DK", 0), \
                mock.patch.object(pingju, "PINGJU_GEN", gen / "users"):
            fu, _ = run.zhen_ben(gen, 0)
        self.addCleanup(fu.server_close)
        return fu, gen / "users"

    # ---- 衔接 1：run.py 注入的两个字段必须同源 ----
    def test_liang_ge_zi_duan_tong_yi_ge_uid(self):
        """**真跑一遍 `run.zhen_ben`，钉住 `env` 与 `yong_hu` 同源。**

        `run.py:327-330` 两行各算一次 uid：`:327` 拿它建凭据目录，`:330`
        拿它给 `/agents` 现场重试。**分叉了没有任何报错**——凭据是 alice 的、
        归属是 bob 的，两条护栏各自都绿，用户拿 alice 的凭据以 bob 的身份建会话。

        判据是**从 `runtime.json` 走到 `BridgeServer` 上那两个字段**。
        目录名带哈希后缀，所以不能断言目录名 == uid；断言的是「`env` 建出来的
        那个目录」与「`yong_hu` 该落到的那个」是同一个——这正是两条注入线
        汇合的地方，分叉时这里立刻红。
        """
        fu, gen = self._zhen({"userId": "alice"})
        self.assertEqual(fu.yong_hu, "alice", "runtime.json 的 userId 没注入进来")
        self.assertEqual(
            Path(fu.env["CLAUDE_CONFIG_DIR"]), gen / pingju.mu_lu_ming(fu.yong_hu),
            "env 与 yong_hu 不是同一个 uid 建出来的：会话归属与凭据目录指向了两个人")

    def test_wei_pei_dui_liang_ge_zi_duan_ye_tong_yuan(self):
        """未配对时两个字段仍然同源，都落 `local`。**两种「假值」形态都要跑。**

        与上一条成对：只钉配对形态的话，一个把 `run.py` 的 uid 写成
        `str(jiu.get("userId", "local"))`（**没有 `or`**）的实现全绿。

        **必须把「键缺失」与「键在但值假」分开跑。** `get(k, 默认)` 只在键
        **不存在**时用默认值，键在而值为 `None`/`""` 时它照样把那个值取出来——
        所以只有跑 `{"userId": None}` 才真的能分岔。只跑 `{}` 的话，
        `or` 去掉后 `get` 返回默认值 `"local"`，与 `or` 还在时**完全一样**，
        那条 `or` 就是没人守的死代码（变异实测：只改这一处，80 条全绿）。

        现实依据：`runtime.json` 是**多写者文件**，而 `jiu.get("userId", ...)`
        读的是整个 json，任何一个写入者把 `userId` 落成 `null` 都会走到这条。

        **失效模式照实写（评审已实跑证伪过旧说法）：那个 `or` 去掉后 uid
        不会变成 `None`。** `str()` 包装先把它变成字符串 `"None"`，而
        `he_fa` 的白名单是 `[A-Za-z0-9_.-]{1,64}`——`"None"` **合法通过**，
        `_yong()` 不抛，HTTP 层也不会 500。真危害是 uid **静默变成字面量
        `"None"`**：凭据目录建成 `none-dc937b59892604f5`，归属校验拿
        `"None"` 去比，恢复出来的旧会话照样 404，而日志与响应里没有一处
        出现异常。

        所以判据是「拿到的是一个真 uid」，不是「抛没抛异常」——按旧说法写
        `assertRaises` 的话，一条**真的会崩**的实现反而能过。
        """
        for xian in ({}, {"userId": None}, {"userId": ""}):
            with self.subTest(runtime=xian):
                fu, gen = self._zhen(xian)
                self.assertEqual(fu.yong_hu, "local",
                                 f"runtime.json={xian} 时 uid 没落回 local")
                # 这两条点名真实危害（uid 静默变成 str(None) / None），
                # 留着是为了让下一个改这里的人不必重新推一遍上面那段。
                self.assertNotEqual(fu.yong_hu, "None",
                                    "uid 变成了 str(None)：不抛异常，但归属永远对不上")
                self.assertNotEqual(fu.yong_hu, None,
                                    "uid 是 None：he_fa 会抛，HTTP 层 500")
                self.assertNotEqual(
                    Path(fu.env["CLAUDE_CONFIG_DIR"]), gen / pingju.mu_lu_ming("None"),
                    "凭据目录建到了 none- 前缀下：这个目录与真用户无关")
                self.assertEqual(
                    Path(fu.env["CLAUDE_CONFIG_DIR"]),
                    gen / pingju.mu_lu_ming(fu.yong_hu),
                    f"runtime.json={xian} 时 env 与 yong_hu 不同源")
                fu.server_close()

    # ---- 衔接 2：Bridge 侧身份来自 runtime.json，不是 LIFEOS_USER ----
    def test_shen_fen_lai_zi_yun_xing_shi_bu_shi_huan_jing(self):
        """**`_yong()` 不许改成 `dang_qian_yong_hu()`。**

        `BridgeServer.yong_hu` 与 `_yong()` 上各有一段注释解释了为什么：
        `dang_qian_yong_hu()` 读 `LIFEOS_USER`，而生产里**没有任何地方设它**
        （配对的 uid 走 `runtime.json`），拿它当身份会去认一个与真实凭据无关
        的用户——而凭据目录是按 `runtime.json` 的 `bob` 建的。

        判据落在**两个来源给出不同值时听谁的**：这里 `LIFEOS_USER=alice`、
        `fu.yong_hu="bob"`，建出来的会话归属必须是 `bob`。改回
        `dang_qian_yong_hu()` 的实现会判给 `alice`。

        `cwd` 用项目根：`ShenKa` 的信任根就是它。用临时目录会 400
        `cwd_forbidden`，那条路径压根走不到归属——**判据落不到分岔量上**。
        """
        self.fu.yong_hu = "bob"
        with mock.patch.dict(os.environ, {"LIFEOS_USER": "alice"}):
            s, d = self._post("/sessions", {"agentId": "echo", "cwd": self.gen0})
        self.assertEqual(s, 201, d)
        self.assertEqual(d["session"]["ownerId"], "bob",
                         "归属听的是 LIFEOS_USER，不是 runtime.json 的 uid")

    def test_fei_fa_de_yong_hu_bi_lai_xun_ha_rang_dao_LHS(self):
        """LIFEOS_USER 设成非法值时**不许**让归属取到它（11.4、风险 8）。

        与上一条成对：上一条钉「两个来源不同时听 `yong_hu`」，这条钉
        **「`yong_hu` 自己是非法值时怎么办」**。一个直接
        `return dang_qian_yong_hu()` 的实现上一条红；一个把 `he_fa` 摘掉的
        实现这条红——它会让 `userId` 直接成为目录名的一部分，而 uid 在接入
        登录后**来自 cookie**，那是外部输入。

        判据是**状态码**而不是「没建成功」：`he_fa` 抛的 `YongHuFeiFa` 没有
        专门的映射，落进 `do_POST` 的兜底分支回 500。只断言「不是 201」的
        实现也满足，但那和「网关超时」没法区分。
        """
        self.fu.yong_hu = "../../etc"
        with mock.patch.dict(os.environ, {"LIFEOS_USER": "alice"}):
            s, d = self._post("/sessions", {"agentId": "echo", "cwd": self.gen0})
        self.assertEqual(s, 500, f"非法的 yong_hu 被放行了：{d}")
        self.assertIn("YongHuFeiFa", json.dumps(d, ensure_ascii=False))

    # ---- 衔接 3：HTTP 层看到的 ownerId 与凭据目录指向同一个人 ----
    def test_ownerId_he_mu_lu_ming_tong_yi_ge_ren(self):
        """**归属判给谁，Agent 就用谁的凭据目录**——这条接缝上不能有缝。

        `test_pingju.py` 测的是「uid → 目录」这个纯函数；它不知道 HTTP 层
        把会话判给了谁。这里把两边接起来：把 `BridgeServer.yong_hu` 换成 bob，
        建出来的会话 `ownerId` 必须是 bob，而 `yong_hu` 反推出的凭据目录
        必须就是 bob 那一个。

        判据落在**跨过接缝的那个量**上。只断言「`ownerId == yong_hu`」太弱
        ——那正是 `_yong()` 的定义，改动前后都一样；加上目录那一半，这条才
        真的在守「归属与凭据同源」，而这正是 `run.py:327-330` 两行注释
        承诺的事。
        """
        self.fu.yong_hu = "bob"
        s, d = self._post("/sessions", {"agentId": "echo", "cwd": self.gen0})
        self.assertEqual(s, 201, d)
        self.assertEqual(d["session"]["ownerId"], "bob")
        gen = Path(self.mu.name)
        with mock.patch.object(pingju, "PINGJU_GEN", gen):
            env = pingju.huan_jing(self.fu.yong_hu)
        self.assertEqual(
            Path(env["CLAUDE_CONFIG_DIR"]),
            gen / pingju.mu_lu_ming(d["session"]["ownerId"]),
            "会话归属与凭据目录不是同一个人：拿 A 的身份建会话、用 B 的凭据跑")

    # ---- 衔接 4：两个 uid 的凭据目录互不可见（真写文件） ----
    def test_liang_ge_uid_de_wen_jian_hu_bu_ke_jian(self):
        """`Alice` 与 `alice` 的凭据文件**真的互相看不见**（承接单射的后果）。

        与 `test_pingju.py::test_a_neng_du_dao_b_de_ping_gu` 不同的角度：
        那边测的是 `mu_lu_ming` 这个纯函数，这边测的是**目录建出来之后、
        真往里写文件**的形状。

        判据是**文件内容**不是路径：一个「用 uid 直接拼目录名」的实现也能让
        不同 uid 拿到不同路径，但它在 Windows 上会把 `Alice` 与 `alice` 折叠到
        同一个目录（大小写不敏感），于是两边读到同一份凭据。只有真读文件
        才分得开。
        """
        gen = Path(self.mu.name)
        with mock.patch.object(pingju, "PINGJU_GEN", gen):
            a = Path(pingju.huan_jing("Alice")["CLAUDE_CONFIG_DIR"])
            b = Path(pingju.huan_jing("alice")["CLAUDE_CONFIG_DIR"])
        (a / "credentials.json").write_text("ALICE-SECRET", encoding="utf-8")
        (b / "credentials.json").write_text("ALICE-LIKE-SECRET", encoding="utf-8")
        self.assertNotEqual(a, b, "两个 uid 折叠到了同一个目录")
        self.assertNotEqual(
            (a / "credentials.json").read_text(encoding="utf-8"),
            (b / "credentials.json").read_text(encoding="utf-8"),
            "两个 uid 读到同一份凭据——Windows 路径折叠把单射破了")
        # 目录名都带 `-` 后的哈希段（形如 `alice-2bd806c97f0e00af`）。
        # 断言的是**长度与全小写**：`Alice-xxx` 与 `alice-yyy` 只差大小写时
        # Windows 仍然分不开，可读前缀只该是装饰。
        for p in (a, b):
            self.assertEqual(len(p.name.split("-")[-1]), 16, p.name)
            self.assertEqual(p.name, p.name.lower(), p.name)

    # ---- 衔接 5：建不出目录只告警，且不退回共用凭据 ----
    def test_jian_bu_chu_lai_bu_tui_hui_gong_yong(self):
        """mkdir 失败时是换到一个**空的**凭据库，绝不是退回共用凭据。

        「退回共用」比「建不出来」危险得多：用户会以为隔离生效了，
        实际上「总是允许」写在共用 settings 里，撤不回来。

        logger 名是 `bridge.pingju` 不是 `bridge.access`——后者是 handler
        挂载的**宿主** logger，告警发在自己的 `_LOG` 上（承重 3）。
        """
        gen = Path(self.mu.name)
        with mock.patch.object(pingju, "PINGJU_GEN", gen), \
                mock.patch.object(Path, "mkdir", side_effect=OSError("磁盘满")), \
                self.assertLogs("bridge.pingju", level="WARNING") as cm:
            env = pingju.huan_jing("alice")
        self.assertIn("CLAUDE_CONFIG_DIR", env, "失败时连环境变量都不给了")
        self.assertFalse(pingju.JIAN_BING_CHENG_GONG, "失败却报了成功")
        # 且**仍然指向那个 uid 自己的目录**：指向共用目录等于把 alice 的
        # 凭据写进所有人的目录，那比建不出来糟得多。
        self.assertEqual(Path(env["CLAUDE_CONFIG_DIR"]), gen / pingju.mu_lu_ming("alice"),
                         "降级时指向的不是这个 uid 自己的目录")
        self.assertTrue(any("alice" in x or "凭据" in x for x in cm.output),
                        f"告警里没说清是谁的目录：{cm.output}")

    def test_shou_quan_shi_bai_bu_dong_biao_zhi(self):
        """收紧失败**不许**动 `credentialsReady`（阶段 6 必修 1）。

        与上一条成对，且是**反方向**的分岔：收紧失败是「目录是好的、凭据仍
        隔离，只是没锁死」；标成 `false` 会让前端弹出「凭据目录建不出来，
        你需要重新登录一次 Claude…请检查磁盘空间」——三处全假。空库只可能
        由 mkdir 失败引起，所以只有它能置 `false`。
        """
        with mock.patch.object(pingju, "PINGJU_GEN", Path(self.mu.name)), \
                mock.patch.object(pingju, "_shou_quan", side_effect=OSError("boom")):
            pingju.huan_jing("alice")
        self.assertTrue(pingju.JIAN_BING_CHENG_GONG,
                        "收紧失败被当成了建不出来——前端会因此报假警")

    # ---- 衔接 6：HTTP 层的 credentialsReady 与 /agents 现场重试 ----
    def test_agents_ba_deng_chu_lai_de_ren(self):
        """`/agents` 报的 `credentialsReady` 说的是**当前这个人**的目录。

        `/agents` 每次请求现场重跑 `huan_jing(self.server.yong_hu)`
        （`http.py:343`）。这里让 `mkdir` 失败，接口必须回
        `credentialsReady: false`——这条判据横跨**归属字段 → 凭据目录 →
        HTTP 响应**三段，`test_pingju.py` 与 `HuiGuiShuTest` 都只覆盖其中一段。

        **三次 `_get` 都要在补丁作用域内**：`/agents` 每次请求都现场重跑
        `huan_jing(self.server.yong_hu)`，补丁只包住中间那一次的话，第一次
        就在**真实凭据根** `~/.lifeos-bridge/users` 下建目录（还跟它跑
        `icacls`）——那既污染用户真实状态，又让这条断言依赖宿主家目录可写，
        只读家目录的沙箱/CI 会挂。末尾那一次同理，它验的正是「现场重试把
        标志修回来」，补丁不包住它就验不到重试。
        """
        gen = Path(self.mu.name)
        with mock.patch.object(pingju, "PINGJU_GEN", gen):
            s, d = self._get("/agents", {"token": self.token})
            self.assertEqual(s, 200, d)
            self.assertIs(d["credentialsReady"], True, d)
            # 真降级：mock 掉 mkdir。手工把标志按成 false 不行——现场重试会
            # 把它自己修回来（阶段 6 必修 3），那样测的就不是降级路径了。
            with mock.patch.object(Path, "mkdir", side_effect=OSError("拒绝访问")):
                s, d = self._get("/agents", {"token": self.token})
            self.assertEqual(s, 200, d)
            self.assertIs(d["credentialsReady"], False,
                          "建不出目录却报 credentialsReady: true——用户会无声地落到空库")
            s, d = self._get("/agents", {"token": self.token})
            self.assertIs(d["credentialsReady"], True,
                          "目录建得出来了却还挂着 false——告警是启动那一刻的快照")

    def test_agents_ba_deng_chu_lai_de_ping_gu_ming_zi(self):
        """`/agents` 重试建的目录，必须是 `yong_hu` 那一个而不是 `local-`。

        这条钉的是**重试路径的 uid 来源**。`/agents` 拿不到 `runtime.json`，
        只能用 `BridgeServer.yong_hu`——若它改成 `dang_qian_yong_hu()`
        （生产里 `LIFEOS_USER` 没人设，落到 `local`），这里建出来的就是
        `local-<哈希>` 目录：给用户报一个**与真实凭据无关**的状态，
        而 bob 的目录压根没被碰过。

        判据是**目录真的建没建出来**：一个「照样建 alice 的目录、只是
        `yong_hu` 字段留着 bob」的半吊子实现也躲不过——alice 那条根本没被调用。
        """
        self.fu.yong_hu = "bob"
        gen = Path(self.mu.name)
        with mock.patch.object(pingju, "PINGJU_GEN", gen):
            s, d = self._get("/agents", {"token": self.token})
        self.assertEqual(s, 200, d)
        self.assertTrue((gen / pingju.mu_lu_ming("bob")).is_dir(),
                        f"bob 的凭据目录没建出来：{sorted(p.name for p in gen.iterdir())}")
        self.assertFalse((gen / pingju.mu_lu_ming("local")).exists(),
                         "建出了 local- 目录：重试用的不是 yong_hu 的 uid")


class QianHuiQianYiTest(unittest.TestCase):
    """旧会话 ownerId 迁移：先未配对跑过、后来配对的用户，恢复出来的会话
    不该一律 404。

    **为什么这条域此前是空的。** `ownerId` 字段自阶段 1 就在 `models.py`，
    `to_dict()` 是全字段 ⇒ 阶段 1–5 落盘的会话全部带 `ownerId="local"`；
    而 `runtime.json` 的 `userId` 是阶段 6 才引入的。于是「先没配对用了一阵、
    后来配对」的用户，`run.hui_fu` 恢复出来的 ownerId 仍是 `"local"`，
    与运行时 uid 不匹配 ⇒ `http._dui_hui` 一律 404，**连 `close` 都不给**，
    用户只能干等 1800 秒闲置看门狗。未配对装机不受影响（`"local" == "local"`）。
    """

    def _cun(self, a1: str):
        """建一个只含一条落盘会话的存储，返回它。`a1` 就是那条会话的 ownerId。"""
        import logging
        import shutil

        from lifeos.bridge.cun import Cun
        gen = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, gen, True)
        (gen / "bridge").mkdir()
        cun = Cun(gen / "bridge", logging.getLogger("bridge.cun"))
        # 手写落盘文件而不是先 jian() 再改字段：迁移的输入必须是
        # **阶段 1–5 真的写出来的那种记录**，经 jian() 的会多带一轮
        # `_cun_hui` 的格式化，跟真实历史不是一个形状。
        cun.hui_wen.write_text(json.dumps([
            AgentSession(sessionId="s-qian", agentId="echo", agentLabel="echo",
                         cwd=str(gen), ownerId=a1).to_dict(),
        ]), encoding="utf-8")
        return cun

    def _hui(self, a1, a2: str | None) -> str | None:
        """真跑一遍 `run.hui_fu`，返回恢复出来的 ownerId。"""
        from lifeos.bridge.run import hui_fu
        z = ZongXian(uuid.uuid4().hex[:8])
        hua = HuiHua(z)
        hui_fu(Path(tempfile.mkdtemp()), hua, a1, a2)
        self.addCleanup(hua.ting_zhi)
        s = hua.du("s-qian")
        return None if s is None else s.ownerId

    def _cun_hui(self, a1) -> dict[str, str]:
        """落盘 `sessions.json` 里的 sessionId → ownerId。"""
        return {x["sessionId"]: x["ownerId"] for x in a1.du_hui()}

    def test_qian_yi_hui_xie_hui_dao_pan_shang(self):
        """**迁移必须回写 `sessions.json`**，不是只改内存。

        上面三条钉的是「恢复出来的 ownerId」，全在内存里。判据落在**盘上那份**
        ——那才是下一次启动读的东西。不回写的话磁盘上仍是 `"local"`，
        于是同一批会话在两个地方有两个答案：内存说 alice、盘上说 local。
        换绑到 bob 之后 bob 起来会把这批全迁给自己，**alice 的会话出现在
        bob 的列表里**，跨用户隔离从磁盘这一侧整个漏掉。

        判据是「盘上那份 `ownerId` 变成了 alice」而不是「跑完没报错」——
        不回写的实现同样不报错。
        """
        cun = self._cun("local")
        self._hui(cun, "alice")
        self.assertEqual(self._cun_hui(cun)["s-qian"], "alice",
                         "迁移只改了内存没回写 sessions.json：磁盘上还是 local，"
                         "下次启动再迁一遍，而换绑后这批会话会被新主人认领")

    def test_qian_yi_ke_yi_chong_dian_bu_pa(self):
        """重迁第二次一条都不匹配 ⇒ `migrated` 归零、回写不再发生。

        「回写只发生一次」是上面那条的**幂等判据**：无条件回写的坏实现
        每次启动都重写一遍 sessions.json（KB 级全量重写），而判据只钉
        ownerId 的坏实现钉不住它。
        """
        from lifeos.bridge.run import hui_fu
        cun = self._cun("local")
        z = ZongXian(uuid.uuid4().hex[:8])
        hua = HuiHua(z)
        self.addCleanup(hua.ting_zhi)
        gen = Path(tempfile.mkdtemp())
        self.assertEqual(hui_fu(gen, hua, cun, "alice")["migrated"], 1)
        hua2 = HuiHua(ZongXian(uuid.uuid4().hex[:8]))
        self.addCleanup(hua2.ting_zhi)
        self.assertEqual(hui_fu(gen, hua2, cun, "alice")["migrated"], 0,
                         "第二次启动又把已经迁过的会话迁了一遍")

    def test_qian_hui_ben_lai_de_hui_hua_gai_pan_gei_xin_zhu_ren(self):
        """`ownerId == "local"` 的落盘会话，配对后恢复出来归新主人。

        **判据落在「恢复出来的 ownerId」这个量上**——它正是 `_dui_hui`
        拿来和运行时 uid 比的东西。判据写成 `is None` 的坏实现（"local"
        不是 `None`）或写成 `== "local"` 之外的判据，都躲不过。
        """
        self.assertEqual(self._hui(self._cun("local"), "alice"), "alice",
                         "旧会话没被改判给配对后的 uid——它对 alice 一律 404")

    def test_yi_gou_pai_deng_guo_de_bie_ren_hui_hua_bun_neng_ben_gai_pan(self):
        """落盘 `ownerId == "carol"` 的会话，传 alice 也**保持 carol**。

        这是上一条的**分岔判据**：只钉迁移本身的话，「无条件覆盖」这个坏实现
        全绿——而它会把已配对用户的会话在换 uid 时误判给新主人，等于把
        跨用户 404 这条护栏自己拆了。
        """
        self.assertEqual(self._hui(self._cun("carol"), "alice"), "carol",
                         "别人的会话被改判了：跨用户隔离在恢复这一步就漏了")

    def test_wei_qi_dong_qi_ben_lai_de_hui_hua_bu_qian_yi(self):
        """uid 传 `None` ⇒ 一条都不迁（阶段 5 的既有行为原样保留）。

        `hui_fu` 的 uid 是**可选形参**而不是必填，正是为了让「不迁移」这个
        形状可以表达——`tests/test_bridge_huifu.py` 的 4 处调用一个字没改就过。
        所以「不迁」这条也是被用着的行为，不迁就得被钉住。
        """
        self.assertEqual(self._hui(self._cun("local"), None), "local",
                         "没给 uid 就把会话改判了——那等于无条件覆盖")

    def test_zhen_ben_qi_lai_de_shou_ji_que_shi_qian_yi_lei_fen_pei(self):
        """**真跑 `run.zhen_ben`**：落盘 `local` 的会话起来后归 runtime.json
        的 uid，而不是仍留在 `local` 一律 404。

        上面三条钉的是 `hui_fu` 这个函数本身；uid 是**可选形参**，所以
        `zhen_ben` 漏传时迁移静默失效，而上面三条照样全绿。这条是那个缺口
        唯一的护栏。

        **必须真跑 `zhen_ben`，不能手工给 `fu.yong_hu` 赋值**——手工赋值
        分不开「`zhen_ben` 传了 uid」与「测试自己填的」，那是 Task 3 已经
        栽过的同义反复（brief 里的示例代码正是这个形状，生产代码分叉了
        它照样绿）。判据落在**迁移有没有发生**这个量上：落盘值 `local`、
        运行时 uid `alice`，恢复出来是 `alice` ⇒ 迁移发生了；若 `zhen_ben`
        没传，恢复出来就是 `local`，与 uid 字段被没被赋值毫无关系。
        """
        import shutil

        gen = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, gen, True)
        (gen / ".lifeos" / "bridge").mkdir(parents=True)
        (gen / ".lifeos" / "bridge" / "runtime.json").write_text(
            json.dumps({"userId": "alice"}), encoding="utf-8")
        # **sessions.json 必须在 `zhen_ben` 之前落好**：恢复是它起手就做的事，
        # 起来之后再补一条只会躺在磁盘上等下一次重启。
        (gen / ".lifeos" / "bridge" / "sessions.json").write_text(
            json.dumps([AgentSession(sessionId="s-qian", agentId="echo",
                                     agentLabel="echo", cwd=str(gen),
                                     ownerId="local").to_dict()]),
            encoding="utf-8")

        from lifeos.bridge import run
        from lifeos.bridge.http import BridgeHandler
        # `zhen_ben` 改 BridgeHandler 的类属性，见 GeLiTest._zhen 的坑 2。
        # 默认值取 None：跑在 GeLiTest 之前时那些属性还不存在，
        # 直接 `getattr` 会 AttributeError（类属性是 zhen_ben 首次挂上去的）。
        for n in ("zong", "hua", "shen", "token", "shen_qing", "ri"):
            self.addCleanup(setattr, BridgeHandler, n, getattr(BridgeHandler, n, None))
            setattr(BridgeHandler, n, None)
        with mock.patch.object(run, "DK", 0), \
                mock.patch.object(pingju, "PINGJU_GEN", gen / "users"):
            fu, _ = run.zhen_ben(gen, 0)
        self.addCleanup(fu.server_close)
        self.assertEqual(fu.yong_hu, "alice", "runtime.json 的 userId 没注入")
        s = fu.hua.du("s-qian")
        self.assertIsNotNone(s, "zhen_ben 没恢复出这条落盘会话")
        self.assertEqual(s.ownerId, "alice",
                         "落盘的 local 会话没归给 alice——它对 alice 一律 404，"
                         "连 close 都不给")


class JieBangTest(unittest.TestCase):
    """域 D：解绑后旧 `deviceToken` 立即不可用、隧道立即断、Bridge 停止重连。

    实现阶段 6 已落地，这里补两条缺口 + 变异验证。
    """

    def setUp(self):
        self.mu = tempfile.TemporaryDirectory()
        self.gen = Path(self.mu.name)
        self.addCleanup(self.mu.cleanup)

    def _biao(self):
        """一张真设备表，落在临时目录里。**测试自己建，别用 `_biao()` 的全局表。**"""
        from lifeos.api import devices
        return devices.SheBiao(self.gen / "devices.json")

    def test_jie_bang_bu_shan_ping_ju_mu_lu(self):
        """**解绑不删凭据目录。**

        目录里是登录态。删了它等于让这个 uid 的所有会话当场掉登录——
        而解绑的语义是「这台设备不再被信任」，不是「这个人被注销」。
        用户 2026-09-29 裁定的是顶掉旧设备，不是清空他的一切。

        判据是**目录还在、文件还在、内容一字不差**。只断言「路径没报错」不够。

        ⚠ **`PINGJU_GEN` 补丁必须包住「建目录」与「解绑」两步**，不能只包 `huan_jing`。
        控制器实跑过：只包 `huan_jing` 时，给 `jie_bang` 加一行删目录的变异
        **不会让本条变红**——变异在补丁作用域外读到的 `PINGJU_GEN` 是真实的
        `~/.lifeos-bridge/users`，算出的路径在本机并不存在，`rmtree(ignore_errors=True)`
        静默删了个空气。**补丁出作用域 = 这条护栏是假绿。**
        """
        from lifeos.api import bridge_admin
        biao = self._biao()
        with mock.patch.object(pingju, "PINGJU_GEN", self.gen):
            env = pingju.huan_jing("alice")
            mu = Path(env["CLAUDE_CONFIG_DIR"])
            (mu / "credentials.json").write_text('{"k": 1}', encoding="utf-8")
            ji = biao.jia("alice", "测试设备", "")
            # **必须注入 `SHE`**：`_biao()` 在 `SHE is None` 时直接 RuntimeError
            # （`bridge_admin.py:66-68`），只 patch `GW` 这条会炸在调用之前。
            with mock.patch.object(bridge_admin, "SHE", biao), \
                    mock.patch.object(bridge_admin, "GW", None):
                bridge_admin.jie_bang(ji["deviceId"])
        self.assertTrue(mu.is_dir(), "解绑把凭据目录删了")
        self.assertTrue((mu / "credentials.json").exists(),
                        "解绑把凭据文件删了")
        self.assertEqual((mu / "credentials.json").read_text(encoding="utf-8"),
                         '{"k": 1}')

    def test_jie_bang_hui_bao_you_mei_you_duan_kai(self):
        """`jie_bang` 的返回值必须如实说清隧道断没断。

        `tunnelClosed` 是给调用方（主服务）看的诊断：它决定界面要不要提示
        「设备已断开」。谎报会让用户以为设备还连着。

        **判据是正反两面。** 只断言「真设备解绑时 tunnelClosed 为真」不够——
        一个无条件置 True 的实现也过（`test_jie_bang_hui_duan_diao_sui_dao`
        只断言 `duan` 被调，同样抓不住它）；反过来只断言不存在的设备为假也不够。
        """
        from lifeos.api import bridge_admin

        class _Jia:
            def __init__(self):
                self.duan_le = []

            def duan(self, a1):
                self.duan_le.append(a1)

        biao = self._biao()
        ji = biao.jia("alice", "测试设备", "")
        jia = _Jia()
        with mock.patch.object(bridge_admin, "SHE", biao), \
                mock.patch.object(bridge_admin, "GW", jia):
            r = bridge_admin.jie_bang(ji["deviceId"])
        self.assertIn("ok", r)
        self.assertIn("tunnelClosed", r)
        self.assertTrue(r["ok"], "设备在表里，jie 却说没解掉")
        self.assertTrue(r["tunnelClosed"], "有网关却报了没断开")
        self.assertEqual(jia.duan_le, [ji["deviceId"]],
                         "GW.duan 没被调到，或调错了设备")
        # 反面：表里没有这台设备时 `jie()` 回 False，`GW.duan` 不该被调，
        # `tunnelClosed` 必须是 False——否则界面会对一台不存在的设备提示「已断开」。
        jia2 = _Jia()
        with mock.patch.object(bridge_admin, "SHE", biao), \
                mock.patch.object(bridge_admin, "GW", jia2):
            r2 = bridge_admin.jie_bang("dev-bu-cun-zai")
        self.assertFalse(r2["ok"])
        self.assertFalse(r2["tunnelClosed"], "不存在的设备也报了断开")
        self.assertEqual(jia2.duan_le, [], "没解成却去断了隧道")

    def test_jie_bang_hou_jiu_token_ren_bu_chu_lai(self):
        """解绑之后旧 token 认不出来（域 D 的核心，端到端一条）。

        **`ren(a1)` 只收 deviceToken 一个参数，返回 `(记录, 原因)` 元组。**
        对元组做 `assertTrue`/`assertFalse` 恒为真、断言形同虚设（原稿两处都这么写），
        判据必须落在**原因字符串**上：`ok` → `revoked` 或 `bad`。
        """
        from lifeos.api import devices
        biao = devices.SheBiao(self.gen / "devices.json")
        ji = biao.jia("alice", "测试设备", "")
        _, yin1 = biao.ren(ji["deviceToken"])
        self.assertEqual(yin1, "ok", "刚配对的 token 认不出来")
        self.assertTrue(biao.jie(ji["deviceId"]))
        _, yin2 = biao.ren(ji["deviceToken"])
        self.assertIn(yin2, ("revoked", "bad"),
                      f"解绑之后旧 token 还认得出来：{yin2}")