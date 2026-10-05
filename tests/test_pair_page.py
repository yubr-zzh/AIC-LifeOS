"""Bridge 侧配对页与凭据落盘（spec 8.1、5.3 第 2–3 步）。"""

from __future__ import annotations

import io
import json
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from lifeos.bridge import auth, pipei, run
from lifeos.bridge.events import ZongXian
from lifeos.bridge.http import BridgeHandler, BridgeServer, HTML_PEI, YiWu
from lifeos.bridge.planner_guard import ShenKa
from lifeos.bridge.session import HuiHua


def _kong() -> int:
    """要一个空闲端口。绑了就听、拿到端口再关——只 bind 在 Windows 上测不出占用。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    p = s.getsockname()[1]
    s.close()
    return p


class JiaYun(BaseHTTPRequestHandler):
    """假云端：只实现 POST /api/bridge/pair。"""
    da = {"deviceId": "dev-0000000000ab", "deviceToken": "dt_dev-0000000000ab_" + "1" * 64,
          "userId": "local"}
    shou_dao: list[dict] = []
    zhuang = 200
    wen = "配对码无效或已过期"

    def do_POST(self):
        chang = int(self.headers.get("content-length", "0"))
        JiaYun.shou_dao.append(json.loads(self.rfile.read(chang).decode("utf-8")))
        if JiaYun.zhuang != 200:
            shu = json.dumps({"error": {"code": "invalid_request", "message": JiaYun.wen}}).encode()
            self.send_response(JiaYun.zhuang)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(shu)))
            self.end_headers()
            self.wfile.write(shu)
            return
        shu = json.dumps(JiaYun.da).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(shu)))
        self.end_headers()
        self.wfile.write(shu)

    def log_message(self, *a):
        pass


class PipeiTest(unittest.TestCase):
    #: 云端返回的响应体。**每个用例都要重置**——`test_yun_shi_hui_fei_fa_userId_bu_de_luo_pan`
    #: 会把它换成非法 userId，用例中途失败时不重置就会漏给下一个。
    YUN_HUI = {"deviceId": "dev-0000000000ab",
               "deviceToken": "dt_dev-0000000000ab_" + "1" * 64, "userId": "local"}

    def setUp(self):
        JiaYun.shou_dao = []
        JiaYun.zhuang = 200
        JiaYun.da = dict(PipeiTest.YUN_HUI)
        self.duan = _kong()
        self.fu = ThreadingHTTPServer(("127.0.0.1", self.duan), JiaYun)
        threading.Thread(target=self.fu.serve_forever, daemon=True).start()
        self.mu = tempfile.TemporaryDirectory()
        self.yun = Path(self.mu.name) / "runtime.json"
        self.yun.write_text(json.dumps({"schemaVersion": 2, "port": 8766,
                                        "token": "a" * 64, "deviceId": "local"}),
                            encoding="utf-8")

    def tearDown(self):
        self.fu.shutdown()
        self.mu.cleanup()

    def _pai(self):
        with mock.patch.object(pipei, "CLOUD", f"http://127.0.0.1:{self.duan}"):
            return pipei.pai("K4M-9QX", "本机", self.yun, "i-abc")

    def test_pai_cheng_gong_bing_luo_pan(self):
        r = self._pai()
        self.assertEqual(r["deviceId"], "dev-0000000000ab")
        yun = json.loads(self.yun.read_text(encoding="utf-8"))
        self.assertEqual(yun["deviceId"], "dev-0000000000ab")
        self.assertEqual(yun["deviceToken"], r["deviceToken"])
        self.assertEqual(yun["tunnelState"], "none")
        self.assertEqual(yun["userId"], r["userId"])   # 落盘的与返回的必须是同一个值
        # 必须保留既有字段：port/token 是本地直连形态在用的
        self.assertEqual(yun["port"], 8766)
        self.assertEqual(yun["token"], "a" * 64)

    def test_pai_ba_ma_he_biao_qian_chuan_gei_yun(self):
        self._pai()
        self.assertEqual(JiaYun.shou_dao[0]["code"], "K4M-9QX")
        self.assertEqual(JiaYun.shou_dao[0]["label"], "本机")
        self.assertEqual(JiaYun.shou_dao[0]["instanceId"], "i-abc")

    def test_ma_bu_dui_bao_pei_dui_shi_bai(self):
        JiaYun.zhuang = 400
        with self.assertRaises(pipei.PeiDuiShiBai) as c:
            self._pai()
        self.assertEqual(c.exception.code, "invalid_request")

    def test_yun_bu_ke_da_bao_pei_dui_shi_bai(self):
        with mock.patch.object(pipei, "CLOUD", f"http://127.0.0.1:{_kong()}"):
            with self.assertRaises(pipei.PeiDuiShiBai) as c:
                pipei.pai("K4M-9QX", "本机", self.yun, "i-abc")
        self.assertEqual(c.exception.code, "agent_unavailable")

    # ---------- 承重 4：主服务返回的 userId 必须过白名单 ----------
    def test_yun_shi_hui_fei_fa_userId_bu_de_luo_pan(self):
        """主服务返回的 `userId` 原样落盘，全程不过白名单。

        今天 uid 来自环境变量/本地文件（可信），但 11.1 明说接入登录后它来自
        cookie——那时主服务返回什么就是什么。`"../.."` 能让 `pingju` 把凭据目录
        落到 `~/.lifeos-bridge/` 之外；`"alice."` 则是承重 1 那个折叠的引信。

        **抛 `PeiDuiShiBai` 而不是静默丢弃**：`pai()` 的契约是「失败绝不改动
        runtime.json」（见上面 `test_shi_bai_shi_bu_dong_runtime`），uid 非法
        同样属于失败——落一个非法值下去，Bridge 下次启动照样会去拼路径。
        """
        yuan = self.yun.read_text(encoding="utf-8")
        for huai in ["../..", "..", "a/b", "a\\b", "x y", "用户", "x" * 65, "alice\n"]:
            with self.subTest(huai=repr(huai)):
                JiaYun.da = {"deviceId": "dev-0000000000ab",
                             "deviceToken": "dt_" + "1" * 64, "userId": huai}
                try:
                    with self.assertRaises(pipei.PeiDuiShiBai):
                        self._pai()
                    self.assertEqual(self.yun.read_text(encoding="utf-8"), yuan)
                finally:
                    JiaYun.da = dict(PipeiTest.YUN_HUI)

    def test_yun_bu_hui_userId_luo_local(self):
        """主服务没返回 userId 时仍落 "local"（旧行为不许被这次校验改掉）。"""
        JiaYun.da = {"deviceId": "dev-0000000000ab", "deviceToken": "dt_" + "1" * 64}
        try:
            r = self._pai()
        finally:
            JiaYun.da = dict(PipeiTest.YUN_HUI)
        self.assertEqual(r["userId"], "local")

    def test_shi_bai_shi_bu_dong_runtime(self):
        JiaYun.zhuang = 400
        yuan = self.yun.read_text(encoding="utf-8")
        with self.assertRaises(pipei.PeiDuiShiBai):
            self._pai()
        self.assertEqual(self.yun.read_text(encoding="utf-8"), yuan)

    def test_runtime_du_huai_ye_neng_pai(self):
        self.yun.write_text("{ 不是 JSON", encoding="utf-8")
        r = self._pai()
        yun = json.loads(self.yun.read_text(encoding="utf-8"))
        self.assertEqual(yun["deviceId"], r["deviceId"])


class PairPageTest(unittest.TestCase):
    """只验 GET 返回一个带表单的页面 + 非本机 403。**不启动完整 Bridge**——
    完整链路的验收在任务 10 的真机脚本里。"""

    def test_ye_mian_you_biao_dan(self):
        self.assertIn("<form", HTML_PEI)
        self.assertIn('method="post"', HTML_PEI)
        self.assertIn('name="code"', HTML_PEI)


class YunDuoXieZheTest(unittest.TestCase):
    """runtime.json 是多写者文件：配对写凭据，Bridge 进程写 pids/cleanExit/…，
    隧道路径写 tunnelState。**任何一方的整份覆盖都会抹掉别人的键。**"""

    def setUp(self):
        JiaYun.shou_dao = []
        JiaYun.zhuang = 200
        JiaYun.wen = "配对码无效或已过期"
        self.duan = _kong()
        self.fu = ThreadingHTTPServer(("127.0.0.1", self.duan), JiaYun)
        threading.Thread(target=self.fu.serve_forever, daemon=True).start()
        self.mu = tempfile.TemporaryDirectory()
        self.gen = Path(self.mu.name)
        self.yun_wen = run.wen_jia_ming(self.gen)
        self.yun = self._zhao_yun()
        run.xie_runtime(self.gen, self.yun)

    def tearDown(self):
        self.fu.shutdown()
        self.mu.cleanup()

    def _pai(self) -> dict:
        with mock.patch.object(pipei, "CLOUD", f"http://127.0.0.1:{self.duan}"):
            return pipei.pai("K4M-9QX", "本机", self.yun_wen, "i-abc")

    @staticmethod
    def _zhao_yun() -> dict:
        """用**真的**快照构造函数，不是手抄副本——手抄的那份和 run.py 里的
        真快照各走各的，改了真快照测试照样绿。"""
        return run.zao_yun({}, 8766, "a" * 64, "i-abc", 0, "0.2.160", "2.1.283")

    def _du(self) -> dict:
        return json.loads(self.yun_wen.read_text(encoding="utf-8"))

    def test_zhao_men_li_bu_you_ta_ta_ren_de_jian(self):
        """守卫：deviceId/deviceToken/userId/tunnelState 的权威在配对与隧道手里。
        有人把它们加回 zao_yun，就是让启动值每次回写都盖掉凭据——这条会红。"""
        zhao = self._zhao_yun()
        for k in ("deviceId", "deviceToken", "userId", "tunnelState"):
            self.assertNotIn(k, zhao)
        # 自己的键一个都不能少，少了就是「为了不踩别人而整个不写」
        for k in ("port", "token", "pid", "pids", "owner", "startedAt", "sdkVersion",
                  "cliVersion", "instanceId", "streamEpoch", "cleanExit", "orphans",
                  "schemaVersion"):
            self.assertIn(k, zhao)

    def test_pai_hou_bao_bu_hua_que_bing(self):
        r = self._pai()
        # 两条回写路径各走一次：ji_pids（spawn 子进程）与 guan_biao_hou（正常退出）
        for pids, clean in ([4242], False), (None, True):
            run.bao_xie(self.gen, self.yun, pids, clean)
            yun = self._du()
            self.assertEqual(yun["deviceId"], r["deviceId"])
            self.assertEqual(yun["deviceToken"], r["deviceToken"])
            self.assertEqual(yun["userId"], r["userId"])
        self.assertEqual(yun["pids"], [{"pid": 4242}])   # a3=None 时不该动 pids
        self.assertTrue(yun["cleanExit"])

    def test_bao_xie_ba_zi_ji_de_jian_hui_xie_shang_qu(self):
        """pids/cleanExit 这些自己权威的键必须真的写进去——不能为了不踩别人而整个不写。"""
        run.bao_xie(self.gen, self.yun, [7, 8], True)
        yun = self._du()
        self.assertEqual(yun["pids"], [{"pid": 7}, {"pid": 8}])
        self.assertTrue(yun["cleanExit"])
        self.assertEqual(yun["port"], 8766)
        self.assertEqual(yun["token"], "a" * 64)

    def test_qi_ta_xie_zhe_bao_de_jian_ye_neng_liu_xia_lai(self):
        """配对之后另一个写者（阶段 7 的隧道）改了 disk 上的键，下一次回写不能抹掉它。
        与设备无关——这就是「多写者」这条规则本身。"""
        self._pai()
        run.xie_runtime(self.gen, {**run.duan_runtime(self.gen), "tunnelState": "connected"})
        run.bao_xie(self.gen, self.yun, [9], False)
        self.assertEqual(self._du()["tunnelState"], "connected")


class HuiQuanMenTest(unittest.TestCase):
    """回环闸门是 `/pair` 上**唯一**的授权：这条路径刻意不带 Bridge token
    （1.3 铁律），而它会往磁盘写 deviceToken。把 client_address 检查删掉，下面三条就红。

    为什么用 `__new__` 而不是起真服务器：本机连自己永远是 127.0.0.1，
    造不出非回环的 client_address。
    """

    @staticmethod
    def _chu(a1: str) -> BridgeHandler:
        h = BridgeHandler.__new__(BridgeHandler)   # 不走 socket，只摆出要用到的字段
        h.client_address = (a1, 5555)
        h.request_version = "HTTP/1.1"
        h._headers_buffer = []
        h.wfile = io.BytesIO()
        return h

    def test_fei_hui_huan_de_get_pei_403(self):
        with self.assertRaises(YiWu) as c:
            self._chu("10.1.2.3")._pair()
        self.assertEqual(c.exception.status, 403)

    def test_fei_hui_huan_de_post_pei_403(self):
        with self.assertRaises(YiWu) as c:
            self._chu("10.1.2.3")._pei_dui()
        self.assertEqual(c.exception.status, 403)

    def test_hui_huan_de_pei_mian_ke_yong(self):
        """反向：回环必须放行。少了这条，把判断写反（回环 403、远程放行）也测不出来。"""
        h = self._chu("127.0.0.1")
        h._pair()
        self.assertIn(b"<form", h.wfile.getvalue())


class PaiLuYouTest(unittest.TestCase):
    """真起一个 BridgeServer，验 POST /pair 整条路径：绕过 _shou_quan、路由到 _pei_dui、
    以及云端返回的文案被转义。这一类盯的是「分支在 _shou_quan 之前」——
    挪到后面就会变成 401，浏览器里表现为「配对页能开、一点提交就 401」。"""

    @classmethod
    def setUpClass(cls):
        cls.z = ZongXian("test0001")
        cls.hua = HuiHua(cls.z)
        cls.z.zhan = cls.hua
        cls.g = ShenKa([str(Path(__file__).resolve().parent.parent)])
        cls.duan = _kong()
        cls.fu = BridgeServer(("127.0.0.1", cls.duan), cls.z, cls.hua, cls.g,
                              auth.shengcheng())
        cls.mu = tempfile.TemporaryDirectory()
        # run.py 注入的那两个属性，_pei_dui 里的 pipei.pai 要用 yun_wen
        cls.fu.gen = Path(cls.mu.name)
        cls.fu.yun_wen = run.wen_jia_ming(cls.fu.gen)
        threading.Thread(target=cls.fu.serve_forever, daemon=True).start()
        cls.yun_duan = _kong()
        cls.yun_fu = ThreadingHTTPServer(("127.0.0.1", cls.yun_duan), JiaYun)
        threading.Thread(target=cls.yun_fu.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.fu.shutdown()
        cls.fu.server_close()
        cls.yun_fu.shutdown()
        cls.mu.cleanup()

    def _post(self, a1: str) -> tuple[int, str]:
        return self._post_zi(f"code={a1}&label=%E6%9C%AC%E6%9C%BA".encode())

    def _post_zi(self, a1: bytes) -> tuple[int, str]:
        req = urllib.request.Request(f"http://127.0.0.1:{self.duan}/pair", data=a1,
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")

    def test_wu_token_neng_dao_pair_bu_shi_401(self):
        # CLOUD 指到一个确定没人听的端口 → pai() 必然失败 → 400 失败页。
        # 关键在状态码不是 401：那是「分支被挪到 _shou_quan 后面了」。
        with mock.patch.object(pipei, "CLOUD", f"http://127.0.0.1:{_kong()}"):
            code, body = self._post("K4M-9QX")
        self.assertEqual(code, 400)
        self.assertIn("配对失败", body)

    def test_ti_zi_zhen_de_dao_le_yun(self):
        """表单内容真的送到了云端。

        do_POST 入口统一读体之后，`_pei_dui` 若再读一次 rfile 只会拿到空串，
        配对码就丢了。上面那两条盯不到这一点：body 被读空时 `pai("")` 照样是
        400「配对失败」，状态码与文案一模一样。
        """
        JiaYun.shou_dao.clear()
        with mock.patch.object(pipei, "CLOUD", f"http://127.0.0.1:{self.yun_duan}"):
            code, body = self._post("K4M-9QX")
        self.assertEqual(code, 200)
        self.assertIn("dev-0000000000ab", body)
        self.assertEqual(len(JiaYun.shou_dao), 1)
        self.assertEqual(JiaYun.shou_dao[0]["code"], "K4M-9QX")
        self.assertEqual(JiaYun.shou_dao[0]["label"], "本机")

    def test_chao_xian_de_ti_zi_ren_neng_du_dao(self):
        """声明超 1 MiB 的表单，入口不读，`_pei_dui` 仍能读到完整 body。

        `/pair` 既绕过 `_shou_quan` 也绕过 `_du_json`，它自己 `parse_qs`。入口若
        把超限的体缓存成 `b""`，配对码就静默丢了——状态码与文案跟「码填错了」
        一模一样，从外面看不出来（对照上一条）。
        """
        JiaYun.shou_dao.clear()
        duan = (f"code=K4M-9QX&label=%E6%9C%AC%E6%9C%BA&pad={'y' * (1 << 20)}").encode()
        with mock.patch.object(pipei, "CLOUD", f"http://127.0.0.1:{self.yun_duan}"):
            code, body = self._post_zi(duan)
        self.assertEqual(code, 200)
        self.assertIn("dev-0000000000ab", body)
        self.assertEqual(len(JiaYun.shou_dao), 1)
        self.assertEqual(JiaYun.shou_dao[0]["code"], "K4M-9QX")
        self.assertEqual(JiaYun.shou_dao[0]["label"], "本机")

    def test_yun_wan_hou_de_wen_an_b_u_zhuan_yi(self):
        """云端返回的 message 是远端可控的字符串，直接拼进 HTML 等于
        在 127.0.0.1 源上执行脚本（LIFEOS_MAIN_URL 指向远端时）。"""
        JiaYun.zhuang = 400
        JiaYun.wen = "<script>alert(1)</script>"
        try:
            with mock.patch.object(pipei, "CLOUD", f"http://127.0.0.1:{self.yun_duan}"):
                code, body = self._post("K4M-9QX")
        finally:
            JiaYun.zhuang = 200
            JiaYun.wen = "配对码无效或已过期"
        self.assertEqual(code, 400)
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)

    def test_cheng_gong_hou_ti_xing_yao_chong_qi(self):
        """配对成功时必须提示「重启 Bridge 才生效」。

        `fu.env` 在 `run.zhen_ben` 启动时算好就固定了（`run.py:299`），
        配对后 runtime.json 里的 uid 变了、正在跑的 Bridge 还指着旧目录。
        这不是安全缺陷（代码与注释一致），但**不说出来就是可用性缺陷**：
        用户配对完立刻建会话，用的是 `local` 的空库，被迫重新登录，
        而页面上写的是「配对成功」。

        断言查的是「有没有重启提示」这个事实，**不钉具体文案**——
        文案会改，行为不会。
        """
        with mock.patch.object(pipei, "CLOUD", f"http://127.0.0.1:{self.yun_duan}"):
            code, body = self._post("K4M-9QX")
        self.assertEqual(code, 200)
        self.assertIn("重启", body)
