"""凭据隔离（spec 11.2、风险 8）。

`~/.claude/credentials.json` 是**每个操作系统用户一份**。共用一份时，
任何人点一次「总是允许」会**永久扩大全局白名单**——白名单写在共用的
settings 里，撤不回来。所以每个 LifeOS 用户一个 `CLAUDE_CONFIG_DIR`。

三条不变量，缺一条就退化：
1. **不同 uid 必须拿到不同目录**（单射）。uid 白名单只挡得住字符集，挡不住
   Windows 的路径语义：末尾的点被剥、大小写不敏感，于是 `alice`/`Alice`/`alice.`
   会落到同一个目录，A 就读得到 B 的凭据。目录名因此带 uid 的哈希。
2. 目录按 uid 分，且 uid 进路径前必须过白名单（接入登录后 uid 就是外部输入）；
3. 权限收紧到只有本人（POSIX 700 / Windows icacls 给 M 不是 RW）；
4. **建不出来时只告警**——但不是「退回共用凭据」：mkdir 失败是换到一个
   **空的**凭据库（用户要重新登录），收紧失败才是真的还在共用。
"""

from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lifeos.api.dangqian import YongHuFeiFa
from lifeos.bridge import pingju
from lifeos.bridge.adapters.echo import EchoAdapter


class HuanJingTest(unittest.TestCase):
    def setUp(self):
        self.mu = tempfile.TemporaryDirectory()
        self.gen = Path(self.mu.name)

    def tearDown(self):
        self.mu.cleanup()

    def _an(self, a1: str) -> Path:
        with mock.patch.object(pingju, "PINGJU_GEN", self.gen):
            return Path(pingju.huan_jing(a1)["CLAUDE_CONFIG_DIR"])

    def _an_path(self, a1: str) -> Path:
        """不建目录也要知道「这个 uid 该落到哪」——降级分支下目录根本没建出来。"""
        with mock.patch.object(pingju, "PINGJU_GEN", self.gen):
            with mock.patch.object(Path, "mkdir"):
                return Path(pingju.huan_jing(a1)["CLAUDE_CONFIG_DIR"])

    def test_an_uid_fen_mu_lu(self):
        a = self._an("alice")
        b = self._an("bob")
        self.assertNotEqual(a, b)
        self.assertTrue(a.is_dir())
        self.assertTrue(b.is_dir())
        # 落在 spec 11.2 定的位置：~/.lifeos-bridge/users/
        self.assertEqual(a.parent, self.gen)
        # 目录名**保留 uid 的可读部分**——运维排障时要能一眼看出这是谁的目录
        # （与 clawd 保留原 id 只做展示是同一个取舍）。
        self.assertTrue(a.name.startswith("alice-"), a.name)

    # ---------- 承重 1：uid → 目录必须单射 ----------
    def test_b_tong_uid_bu_neng_dao_tong_yi_ge_mkdir_li(self):
        """**核心不变量**：不同 uid 必须拿到不同目录。

        Windows 的两条路径语义各自能把两个合法 uid 折叠到同一个目录：
        末尾的点被剥（`alice` / `alice.` / `alice..`），大小写不敏感
        （`alice` / `Alice`）。前者是构造出的「目录建在了 alice 上，文件却
        写不进去」（`alice..` 的目录 mkdir 成功，解析过去却是 `alice`——
        本机实测 `FileNotFoundError`）；后者更直接——两个 uid 真的读到同一份
        `credentials.json`。

        旧实现 `p = PINGJU_GEN / uid` 这一条全红。
        """
        uids = ["alice", "alice.", "alice..", "Alice"]
        mu_lu = {u: self._an(u) for u in uids}
        self.assertEqual(len(set(mu_lu.values())), len(uids),
                         f"uid → 目录不是单射：{mu_lu}")
        for u, p in mu_lu.items():
            self.assertTrue(p.is_dir(), f"{u!r} 的目录没建出来：{p}")

    def test_dai_kong_ge_de_uid_gen_bei_ju(self):
        """末尾空格是 Windows 第三条剥除规则，但**它进不到路径里**——白名单的
        字符集不含空格。所以保证它的方式不是「给个不同的目录」，而是**根本不给**
        （`tests/test_devices.py` 里 `"a b"` 被拒是同一条规则的既有断言）。

        写成「拒绝」而不是「另一个目录」不是偷懒：拒绝是更强的保证。
        混进来当第四个 uid 一起比，反而会让人以为空格是合法 uid。
        """
        for u in ["alice ", " alice", "alice\n", "alice\t"]:
            with self.subTest(u=repr(u)):
                with self.assertRaises(YongHuFeiFa):
                    self._an(u)

    def test_a_neng_du_dao_b_de_ping_gu(self):
        """单射的**后果**那一条：A 读得到 B 的凭据。全绿靠真读文件，不靠路径比较。"""
        a = self._an("Alice")
        (a / "credentials.json").write_text("ALICE-SECRET", encoding="utf-8")
        b = self._an("alice")
        self.assertFalse((b / "credentials.json").exists())
        # 反向也必须挡住：uid `Alice` 读不到 `alice` 写的。反了就只做了一半。
        c = self._an("alice")
        (c / "zhu_yao.json").write_text("X", encoding="utf-8")
        self.assertFalse((a / "zhu_yao.json").exists())

    def test_mu_lu_ming_shi_jing_ASCII_qie_bu_men_da_lian(self):
        """哈希后缀带来的三个性质：纯 ASCII、无大小写歧义、不含路径分隔符。

        「无大小写歧义」是必须的：目录名里带 uid 原文时 `Alice-xxx` 与
        `alice-yyy` 在 Windows 上仍然分不开，可读前缀只该是**装饰**。
        """
        p = self._an("alice")
        self.assertEqual(p.name, p.name.lower())   # 目录名全小写 → 无大小写歧义
        self.assertTrue(p.name.isascii(), p.name)
        for c in '/\\:*?"<>| \t\n':
            self.assertNotIn(c, p.name)

    def test_mu_lu_quan_xian_shou_jin(self):
        p = self._an("alice")
        if os.name == "nt":
            # Windows 上是 ACL，POSIX 位没有意义。**不整条跳过**——那会让
            # 真机上收紧逻辑一段都不执行也「通过」。断言的是**授权串本身**：
            # 少了 (OI)(CI) 子文件不受约束（凭据就写在子文件里），
            # 给了 RW 而不是 M 则日后覆盖会 WinError 5（阶段 5 的教训）。
            # (OI)(CI)(M) 的**括号是 icacls 自己加的**：传 `user:(OI)(CI)M`
            # 进去，读回来是 `user:(OI)(CI)(M)`。
            if not os.environ.get("USERNAME"):
                # 身份不明时实现是**跳过收紧**（与 `cun.shou_quan` 同款判断），
                # 这条另有测试钉住（`test_wei_shen_fen_shi_qiao_tuo_shou_jin`）。
                # 这里不能再断言授权串——`self.fail` 在没有 USERNAME 的服务
                # 账户 / CI 容器上是**假红**：与被测代码的对错无关。
                self.skipTest("本机没有 USERNAME，收紧的授权串无从断言"
                              "（跳过收紧这一行为由 test_wei_shen_fen_shi_qiao_tuo_shou_jin 钉住）")
            self.assertIn(f"{os.environ['USERNAME']}:(OI)(CI)(M)",
                          self._icacls(p))
        else:
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o700)

    def test_wei_shen_fen_shi_qiao_tuo_shou_jin(self):
        """没有 USERNAME 时收紧整段跳过，且**不炸**（跨机器稳定的那一条）。

        为什么单独一条而不是在上一条里 `fail`：某些服务账户 / CI 容器压根
        没有 USERNAME，`fail` 在那些机器上是假红。这里断言的是**被测行为**
        ——身份不明就不要去动 ACL（用空用户名跑 icacls 会把目录权限改坏）。
        """
        if os.name != "nt":
            self.skipTest("这是 Windows icacls 的行为")
        env = {k: v for k, v in os.environ.items() if k != "USERNAME"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(pingju.subprocess, "run") as ran:
            p = self._an("alice")
        self.assertTrue(p.is_dir())
        ran.assert_not_called()   # 身份不明时一条 icacls 都不该发

    @staticmethod
    def _icacls(a1: Path) -> str:
        import subprocess
        r = subprocess.run(["icacls", str(a1)], capture_output=True,
                           timeout=10, check=False)
        return (r.stdout or b"").decode("utf-8", "replace")

    def test_fei_fa_uid_bei_ju(self):
        """uid 拼进路径，所以必须是白名单校验而不是 basename 清洗。"""
        for huai in ["../..", "..", ".", "", "a/b", "a\\b", "x y", "用户", "x" * 65]:
            with self.subTest(huai=huai):
                with self.assertRaises(YongHuFeiFa):
                    self._an(huai)

    # ---------- 承重 2：白名单的 `$` 允许尾随换行 ----------
    def test_wei_zhu_shui_huan_xing_bei_ju(self):
        """`HE_FA` 用 `$` 而不是 `\\Z`，Python 允许它在**最后一个换行符之前**匹配——
        所以 `'alice\\n'`、`'..\\n'` 全都过白名单。Windows 上 mkdir 拒收带换行的
        路径（WinError 123），于是走到「只告警」的降级分支，返回一条**建不出来**
        的路径；POSIX 上 `'..\\n'` 则被内核归一化到父目录。

        这条测的是 `he_fa` 本身，不是 `pingju`——`he_fa` 是全项目唯一入口，
        `LIFEOS_USER` 也走它。旧正则下全红。
        """
        from lifeos.api import dangqian
        for huai in ["alice\n", "..\n", ".\n", "alice\n\n", "\nalice"]:
            with self.subTest(huai=repr(huai)):
                with self.assertRaises(YongHuFeiFa):
                    self._an(huai)
                # 直接钉 he_fa：pingju 侧的哈希目录名有可能把这个洞盖住，
                # 那样这条就会假绿。入口本身必须拒。
                with self.assertRaises(YongHuFeiFa):
                    dangqian.he_fa(huai)

    # ---------- 承重 3：告警可见 + /agents 报 credentialsReady ----------
    def test_jian_bing_quan_wen_lei_ba_zi_ji_biao_zhi(self):
        """建不出来时 `credentialsReady` 置 False（spec 11.2）。恢复后仍报 True——
        标志是**这次启动**的状态，不是「历史上失败过」的粘滞位。"""
        b = pingju.JIAN_BING_CHENG_GONG
        try:
            pingju.JIAN_BING_CHENG_GONG = True
            with mock.patch.object(pingju, "PINGJU_GEN", self.gen):
                with mock.patch.object(Path, "mkdir", side_effect=OSError("拒绝访问")):
                    pingju.huan_jing("alice")
            self.assertFalse(pingju.JIAN_BING_CHENG_GONG)
            with mock.patch.object(pingju, "PINGJU_GEN", self.gen):
                pingju.huan_jing("alice")
            self.assertTrue(pingju.JIAN_BING_CHENG_GONG)
        finally:
            pingju.JIAN_BING_CHENG_GONG = b

    def test_gao_jing_bu_shuo_qiao_kong_zhuan_xiang(self):
        """降级文案必须说清「空库」而不是「共用库」——两种失败的后果不同。

        mkdir 失败 = 换到一个**空的**凭据库（用户要重新登录）；
        收紧失败 = 目录在、只是 ACL 没收紧。前者说成后者会把排障带偏。
        """
        with mock.patch.object(pingju, "PINGJU_GEN", self.gen):
            with mock.patch.object(Path, "mkdir", side_effect=OSError("拒绝访问")):
                with self.assertLogs("bridge.pingju", level="WARNING") as cm:
                    pingju.huan_jing("alice")
        wen = "\n".join(cm.output)
        self.assertIn("空", wen)
        self.assertNotIn("共用凭据", wen)

    def test_mei_quan_shi_zhi_gao_jing_bu_duan(self):
        """目录建不了时只告警——不能让 Bridge 起不来（11.2）。"""
        b = pingju.JIAN_BING_CHENG_GONG
        try:
            with mock.patch.object(pingju, "PINGJU_GEN", self.gen):
                with mock.patch.object(Path, "mkdir", side_effect=OSError("拒绝访问")):
                    r = pingju.huan_jing("alice")
            self.assertIn("CLAUDE_CONFIG_DIR", r)  # 仍然给出路径
            # 且**仍然指向那个 uid 的目录**：SDK 会自己把这个目录建出来
            # （CLI 不会退回 ~/.claude），指向别的目录等于把 A 的凭据
            # 写进 B 的目录。
            self.assertEqual(Path(r["CLAUDE_CONFIG_DIR"]), self._an_path("alice"))
        finally:
            pingju.JIAN_BING_CHENG_GONG = b

    def test_tong_yi_uid_liang_ci_diao_de_dao_tong_yi_ge(self):
        self.assertEqual(self._an("alice"), self._an("alice"))

    # ---------- 必修 1：收紧失败 ≠ 建不出来 ----------
    def test_shou_quan_shi_bai_biao_zhi_cheng_gong(self):
        """**收紧失败时 `credentialsReady` 必须仍是 True**（阶段 6 必修 1）。

        POSIX 的 `chmod` 抛 `OSError`、icacls 返回非 0——两者都是
        「目录是好的、凭据仍隔离，只是没锁死」。标成 `False` 会让前端弹出
        「凭据目录建不出来，你需要重新登录一次 Claude…请检查磁盘空间」：
        三处都是假的（目录建出来了、不用重新登录、chmod 失败通常是文件系统
        不支持 POSIX 权限——NTFS-3g / FAT32 / 容器 volume / WSL 的 `/mnt/c`，
        与磁盘空间无关）。空库只可能由 mkdir 失败引起，所以只有它能置 False。
        """
        b = pingju.JIAN_BING_CHENG_GONG
        try:
            pingju.JIAN_BING_CHENG_GONG = True
            with mock.patch.object(pingju, "PINGJU_GEN", self.gen):
                with mock.patch.object(pingju, "_shou_quan",
                                       side_effect=OSError("不支持 POSIX 权限")):
                    pingju.huan_jing("alice")
            self.assertTrue(pingju.JIAN_BING_CHENG_GONG,
                            "收紧失败被当成了建不出来——前端会因此报假警")
        finally:
            pingju.JIAN_BING_CHENG_GONG = b

    def test_shou_quan_shi_bai_bu_dao_gao_jing_kong_ku_wen_an(self):
        """收紧失败的告警要说「没锁死」，不能说「空库 / 重新登录」。

        与 `test_gao_jing_bu_shuo_qiao_kong_zhuan_xiang` 是镜像的一对：
        那条钉 mkdir 失败时文案不许说「共用凭据」，这条钉收紧失败时文案
        不许说「空库」。文案混了会把排障带偏——两个方向的处置完全不同。
        """
        with mock.patch.object(pingju, "PINGJU_GEN", self.gen), \
                mock.patch.object(pingju, "_shou_quan", side_effect=OSError("boom")):
            with self.assertLogs("bridge.pingju", level="WARNING") as cm:
                pingju.huan_jing("alice")
        wen = "\n".join(cm.output)
        self.assertNotIn("空", wen)
        self.assertNotIn("重新登录", wen)


    def test_posix_chmod_700(self):
        """POSIX 分支真的调 `chmod(0o700)`——**在 Windows 上也要跑**（应修 4）。

        为什么要 mock `os.name`：`os.name` 读的是模块常量，不能 patch，
        但 `_shou_quan` 里是 `os.name == "posix"` 现读现比，
        所以 `mock.patch.object(pingju.os, "name", "posix")` 有效。

        不这么钉的话这条分支在 Windows 开发机上**一行都不执行**
        （`test_mu_lu_quan_xian_shou_jin` 的 else 在 nt 上永远走不到），
        POSIX 专属的 `chmod` 就能一路错下去而测试全绿——必修 1 的病正是
        从这里漏到前端的。
        """
        with mock.patch.object(pingju, "PINGJU_GEN", self.gen), \
                mock.patch.object(pingju.os, "name", "posix"), \
                mock.patch.object(Path, "chmod") as ch:
            result = pingju.huan_jing("alice")
        # Construct Path after restoring os.name; Windows cannot instantiate PosixPath.
        p = Path(result["CLAUDE_CONFIG_DIR"])
        self.assertTrue(p.is_dir(), "收紧前目录必须已经建出来")
        ch.assert_called_once_with(pingju.JIAO_SE)

    def test_posix_chmo_bu_hui_jiang_zhi_biao_zhi(self):
        """POSIX 的 `chmod` 失败**不许**把标志打成 False（必修 1 的根因行）。

        直接钉 `_shou_quan` 的 POSIX 分支而不是 mock 掉整个 `_shou_quan`：
        上一条 `test_shou_quan_shi_bai_biao_zhi_cheng_gong` mock 的是
        `_shou_quan` 这个符号，**它压根不执行**——chmod 抛不抛、抛的是什么，
        两条测试都答不了。这条让真的 chmod 抛，是唯一能把
        「`huan_jing` 的 try 包住了 chmod」这个形态钉住的那种。
        """
        b = pingju.JIAN_BING_CHENG_GONG
        try:
            pingju.JIAN_BING_CHENG_GONG = True
            with mock.patch.object(pingju, "PINGJU_GEN", self.gen), \
                    mock.patch.object(pingju.os, "name", "posix"), \
                    mock.patch.object(Path, "chmod", side_effect=OSError("EPERM")):
                r = pingju.huan_jing("alice")
            self.assertTrue(pingju.JIAN_BING_CHENG_GONG)
            # 目录**真的建出来了**——这正是「其实没事」的那一半
            self.assertTrue(Path(r["CLAUDE_CONFIG_DIR"]).is_dir())
        finally:
            pingju.JIAN_BING_CHENG_GONG = b


class ZhuangPeiTest(unittest.TestCase):
    """接线：env 真的传进 ClaudeAgentOptions 吗？

    只钉这一段是有理由的：`pingju.huan_jing` 上面已经全测过了，
    真正会悄悄断的是这一行——SDK 那一端 `env` 拼进 spawn 的
    `process_env`（`subprocess_cli.py`：inherited_env 之后展开 options.env），
    少传一行，测试全绿而两个用户继续共用 `~/.claude`。
    """

    def test_env_chuan_jin_qu_C(self):
        import asyncio

        from lifeos.bridge.adapters import claude_code as cc

        kan: dict = {}
        zhen_lei = cc.ClaudeAgentOptions   # 补丁前抓住真的那个

        async def _lian_ji(self):
            self.guan_le = False

        def _jia(o):
            kan.update(o.__dict__)
            return type("K", (), {"connect": _lian_ji})()

        def _zhen(**kw):
            kan.update(kw)
            return zhen_lei(**kw)

        async def _pao(a1: dict) -> None:
            with mock.patch.object(cc, "ClaudeAgentOptions", _zhen), \
                    mock.patch.object(cc, "ClaudeSDKClient", _jia):
                await cc.ClaudeCodeAdapter().kaishi(a1)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_pao({"cwd": ".", "env": {"CLAUDE_CONFIG_DIR": "X"}}))
        finally:
            loop.close()
        self.assertEqual(kan.get("env"), {"CLAUDE_CONFIG_DIR": "X"})

        kan.clear()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_pao({"cwd": "."}))
        finally:
            loop.close()
        # 不传时必须是 None 而不是 {}：{} 在 SDK 的 process_env 展开里
        # 与 None 等价，但 None 同时是「调用方没意见」的诚实表示。
        self.assertIsNone(kan.get("env"))


class RunTest(unittest.TestCase):
    """run.py 按 runtime.json 的 userId 算目录，并挂到 BridgeServer 上。"""

    def setUp(self):
        # **必须自己管这个目录，不能用 TemporaryDirectory 的自动清理。**
        # `zhen_ben` 会把 RotatingFileHandler 挂到 `<root>/.lifeos/bridge/bridge.log`
        # 上，而且是**进程级**地挂在 `bridge.access` logger 上（同一 handler 复用）。
        # 那个文件句柄在整个进程活着期间都不关，TemporaryDirectory 退出时
        # rmtree 撞上它 → WinError 32，报错点还落在 `TemporaryDirectory.__exit__`，
        # 与被测的那行毫无关系。
        self.gen = tempfile.mkdtemp()
        self.root = Path(self.gen)
        (self.root / ".lifeos" / "bridge").mkdir(parents=True)
        # **同一个原因的第二处污染**：`zhen_ben` 还会设 `BridgeHandler.ri`
        # （类属性，全进程共享）。不还原的话，后面跑到的
        # `test_pair_page` 就开始往我的临时 bridge.log 里记访问日志——
        # 那边有 `tearDown` 把 `ri` 置回 None，而我留了个 logger 在上面，
        # 于是 `log_request` 里 `self.ri.info("%s", self.requestline)` 拿到
        # 一个还没读到请求行的 handler → AttributeError，
        # 报错点离真凶（我的 setUp）隔着一个文件。
        from lifeos.bridge.http import BridgeHandler
        self._ri = BridgeHandler.ri
        BridgeHandler.ri = None

    def tearDown(self):
        import shutil
        from lifeos.bridge.http import BridgeHandler
        BridgeHandler.ri = self._ri
        shutil.rmtree(self.gen, ignore_errors=True)

    def _zhen(self):
        from lifeos.bridge import run
        with mock.patch.object(run, "DK", 0), \
                mock.patch.object(pingju, "PINGJU_GEN", Path(self.gen) / "users"):
            fu, _ = run.zhen_ben(self.root, 0)
        return fu

    def test_user_id_lai_zi_runtime(self):
        import json
        (self.root / ".lifeos" / "bridge" / "runtime.json").write_text(
            json.dumps({"userId": "alice"}), encoding="utf-8")
        fu = self._zhen()
        try:
            # 目录名带哈希（承重 1），所以这里**不能**断言目录名等于 uid——
            # 断言的是「确实落在 users/ 下、确实建出来了、且名字以 alice 开头」。
            # 路径等式本身由上面的 HuanJingTest 逐条钉住。
            p = Path(fu.env["CLAUDE_CONFIG_DIR"])
            self.assertEqual(p.parent, Path(self.gen) / "users")
            self.assertTrue(p.is_dir())
            self.assertTrue(p.name.startswith("alice-"), p.name)
        finally:
            # **不能调 `shutdown()`**：它等 `serve_forever()` 退出，而这里
            # 根本没起服务（那会在测试里开一个监听端口）。只关 socket。
            fu.server_close()

    def test_wei_pei_dui_luo_dao_local(self):
        """runtime.json 里没有 userId 时也要能用——未配对是默认开发形态。"""
        fu = self._zhen()
        try:
            p = Path(fu.env["CLAUDE_CONFIG_DIR"])
            self.assertEqual(p.parent, Path(self.gen) / "users")
            self.assertTrue(p.name.startswith("local-"), p.name)
        finally:
            fu.server_close()


class GaoJingKeJianXingTest(RunTest):
    """承重 3(a)：降级告警必须落在 `bridge.log` 里，不是 stderr。

    症状最隐蔽的一种：Bridge 由 `bridge_admin.qidong` 用
    `stdout=DEVNULL, stderr=DEVNULL` 拉起（DETACHED_PROCESS），
    而 `bridge.pingju` 原来**没有任何 handler**——这条唯一的告警被丢进
    DEVNULL，用户和运维谁都看不到，症状只是「怎么在共用凭据上跑」。

    **继承 `RunTest` 而不是自己拼 `zhu_ri()`**：要验的是生产上真正那条接线
    （`run.zhen_ben` → `zhu_ri` → `pingju.jie_shang`）。自己手动调这两个函数的话，
    把 `run.py` 里的 `pingju.jie_shang()` 删掉这条照样绿。
    父类的两条 `test_*` 在这里被重跑一遍是无害的（幂等、无副作用），
    换来的是不用再抄一遍那套 RotatingFileHandler / `BridgeHandler.ri` 的存还。

    **也不用 `assertLogs`**：它给自己装 handler 并把 `propagate` 设成 False，
    于是「record 被接住了」与「落盘了」无关。要的就是「文件里有那句话」。
    """
    def test_gao_jing_zhen_de_lai_dao_bridge_log(self):
        fu = self._zhen()          # 真跑一遍 zhen_ben，handler 与接线都装上
        try:
            with mock.patch.object(Path, "mkdir", side_effect=OSError("拒绝访问")):
                pingju.huan_jing("alice")
            wen = self.root / ".lifeos" / "bridge" / "bridge.log"
            for x in logging.getLogger("bridge.access").handlers:
                x.flush()
            self.assertTrue(wen.exists(), "bridge.log 没建出来")
            # 目录名带哈希，所以按 uid 片段找而不是按整条路径找
            self.assertIn("alice", wen.read_text(encoding="utf-8"))
        finally:
            fu.server_close()

    def test_yue_shou_ming_fen_qi_ye_you_miao_xin_deng_dai_biao_zhi(self):
        """`jie_shang` 幂等：重复调用不许把同一个 handler 挂两遍。

        挂两遍的后果不是「日志多两行」——是同一个文件开了两个句柄，
        轮转时互相覆盖，进程退出时句柄不释放，`RunTest` 那套
        `rmtree(ignore_errors=True)` 之后还可能 WinError 32。
        """
        zhu = logging.getLogger("bridge.access")
        yuan = len(zhu.handlers)
        pingju.jie_shang()
        pingju.jie_shang()
        self.assertEqual(len(zhu.handlers), yuan)
        self.assertEqual(len(set(map(id, logging.getLogger("bridge.pingju").handlers))),
                         len(logging.getLogger("bridge.pingju").handlers))


class ZhuRuDianTest(unittest.TestCase):
    """`xin_jian()` 是全进程唯一调 `kaishi()` 的地方，env 从这里进。

    上面两个类证明「目录算对了」「适配器认 env」，**这一条钉住中间那一段**。
    少传一行的话：单测全绿，两个用户继续共用 `~/.claude`——
    而症状是登录态串了，不是报错，最难查的一条。
    """

    def test_env_piao_dao_kaishi(self):
        import asyncio
        import uuid

        from lifeos.bridge.auth import shengcheng
        from lifeos.bridge.events import ZongXian
        from lifeos.bridge.http import BridgeServer
        from lifeos.bridge.models import AgentSession
        from lifeos.bridge.planner_guard import ShenKa
        from lifeos.bridge.session import HuiHua

        kan: dict = {}

        class Shou(EchoAdapter):
            async def kaishi(self, a1):
                kan.update(a1)

        z = ZongXian(uuid.uuid4().hex[:8])
        h = HuiHua(z)
        z.zhan = h
        g = ShenKa([str(Path(__file__).resolve().parent.parent)])
        fu = BridgeServer(("127.0.0.1", 0), z, h, g, shengcheng())
        # **必须先注册会话**：`xin_jian` 是 `ZHU_CE_QI.get(hui.agentId)`，
        # 会话不存在时 `hui` 是 None，agentId 取不到，注册表里换成什么都白测。
        h.jian(AgentSession(sessionId="s-1", agentId="echo", agentLabel="Echo",
                            cwd="."))
        fu.env = {"CLAUDE_CONFIG_DIR": "/tmp/alice"}
        try:
            with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI", {"echo": Shou},
                                 clear=False):
                asyncio.run(fu.xin_jian("s-1"))
            self.assertEqual(kan.get("env"), {"CLAUDE_CONFIG_DIR": "/tmp/alice"})
            # 没挂 env 的老路径（直接 new BridgeServer）不能炸
            fu.env = None
            kan.clear()
            with mock.patch.dict("lifeos.bridge.http.ZHU_CE_QI", {"echo": Shou},
                                 clear=False):
                asyncio.run(fu.xin_jian("s-1"))
            self.assertIsNone(kan.get("env"))
        finally:
            fu.server_close()


class AgentsBaoGaoTest(unittest.TestCase):
    """spec 11.2：建不出凭据目录时要在 `/agents` 里报出来。

    **为什么单开 `credentialsReady` 而不并进 `available`**：`available` 回答的是
    「本机装没装 claude CLI」（`cls().tanjian()` 的返回值）。并进去的话前端
    分不清「没装 claude」和「建不出凭据目录」——两者的处置完全不同（一个要
    装软件，一个要改磁盘权限），给错提示比不给提示更糟。

    **`PINGJU_GEN` 必须在类级别打补丁。** `/agents` 每次请求都现场重跑
    `huan_jing(self.server.yong_hu)`（`http.py:343`），而 `setUpClass` 里那个
    `BridgeServer` 的 `yong_hu` 还是默认的 `"local"` ⇒ 不打补丁时下面两条
    `_qu()` 直接在**真实凭据根** `~/.lifeos-bridge/users` 下建出
    `local-<哈希>` 并对它跑 `icacls`。后果是 (a) 污染用户真实状态、
    (b) 断言依赖宿主家目录可写（只读家目录的沙箱/CI 会挂）。
    另外两条 `test_qian_chang_zhong_can_*` 自己带了更窄的补丁，作用域内会
    覆盖类级别的那个——两层不冲突，`mock.patch.object` 是后进先出。
    """

    @classmethod
    def setUpClass(cls):
        import shutil
        import threading
        import tempfile
        import uuid
        from lifeos.bridge import auth
        from lifeos.bridge.events import ZongXian
        from lifeos.bridge.http import BridgeServer
        from lifeos.bridge.planner_guard import ShenKa
        from lifeos.bridge.session import HuiHua
        cls.gen = Path(tempfile.mkdtemp())
        # **补丁器存进 cls._ban，`.start()` 单独调一行。** `.start()` 的返回值
        # 是**被替换后的值**（这里就是 cls.gen 那个 WindowsPath），不是补丁器
        # ——写成 `cls._ban = mock.patch.object(...).start()` 时 `cls._ban` 拿到
        # 的是路径，`cls._ban.stop()` 会 AttributeError。之前 `stopall()` 正好
        # 把这个错误掩盖了：它根本没用 `cls._ban`，所以那个坏句柄一直没被碰到。
        cls._ban = mock.patch.object(pingju, "PINGJU_GEN", cls.gen)
        cls._ban.start()
        cls.z = ZongXian(uuid.uuid4().hex[:8])
        cls.h = HuiHua(cls.z)
        cls.z.zhan = cls.h
        cls.token = auth.shengcheng()
        cls.fu = BridgeServer(("127.0.0.1", 0), cls.z, cls.h,
                              ShenKa([str(Path(__file__).resolve().parent.parent)]),
                              cls.token)
        # **必须起 serve_forever**：只 new 不 listen 的话连接会被 accept 进
        #  backlog 再干等，超时而不是 404，症状与「端点没实现」一模一样。
        threading.Thread(target=cls.fu.serve_forever, daemon=True).start()
        cls.duan = cls.fu.server_address[1]
        cls._qing = [shutil.rmtree, cls.gen, True]

    @classmethod
    def tearDownClass(cls):
        cls.fu.shutdown()
        cls.fu.server_close()
        # **只摘自己挂的那一个，不用 `mock.patch.stopall()`。**
        # stopall 摘的是全局补丁栈——同进程里别的用例（以及 pytest-xdist 之外的
        # 同类测试）用 `.start()` 挂的长生命周期补丁会被这一行静默摘掉，
        # 它们后面读到的就是没打补丁的真实值，症状是「另一组测试忽然红了」，
        # 且与本组毫无关系。此刻全树只有 `cls._ban` 这一个 `.start()`，
        # 但那只是**今天**的事实；新增一个 `.start()` 就会变成跨组互相踩。
        cls._ban.stop()
        cls._qing[0](cls._qing[1], cls._qing[2])

    def _qu(self) -> dict:
        import urllib.request
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.duan}/agents",
            headers={"x-bridge-token": self.token})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    def test_zheng_chang_shi_credentialsReady_wei_deng_yu_True(self):
        b = pingju.JIAN_BING_CHENG_GONG
        try:
            pingju.JIAN_BING_CHENG_GONG = True
            d = self._qu()
        finally:
            pingju.JIAN_BING_CHENG_GONG = b
        self.assertIs(d["credentialsReady"], True)

    def test_jian_bing_quan_wen_lei_ba_credentialsReady_wei_deng_yu_False(self):
        """真降级时 `credentialsReady: false`，而 `available` **不动**。

        后半句同样重要：把 `available` 一起打成 false 是这条实现最容易犯的
        错——那会让前端以为「没装 claude」，给一个完全错误的提示。

        前置条件是这次请求**真的建不出目录**（mock 掉 `mkdir`），而不是手工把
        标志按成 false——见下一条：现场重试会把它自己修回来。
        """
        b = pingju.JIAN_BING_CHENG_GONG
        try:
            with mock.patch.object(Path, "mkdir", side_effect=OSError("拒绝访问")):
                d = self._qu()
            self.assertIs(d["credentialsReady"], False)
        finally:
            pingju.JIAN_BING_CHENG_GONG = b
        for x in d["agents"]:
            # available 是 tanjian() 的原样返回值，一个字节都不许被改
            self.assertIsInstance(x["available"], bool)

    def test_qian_chang_zhong_can_liu_chu_ba_jian_bing_quan_wen(self):
        """**现场重试**：`/agents` 每次都重跑一次 `huan_jing`（必修 3）。

        标志只在 `zhen_ben()` 启动时算一次，缺陷是双向的：
        启动时磁盘满 → `false` → 告警挂到天荒地老，用户腾完空间回到页面**还在**；
        反过来运行中目录被删 → 标志仍 `true` → 界面一声不吭，用户照样落到空库、
        重新登录，正是本任务要消灭的症状。`huan_jing` 幂等
        （`mkdir(exist_ok=True)` + 哈希目录名），所以重试没有代价。
        """
        b = pingju.JIAN_BING_CHENG_GONG
        gen = tempfile.mkdtemp()
        try:
            pingju.JIAN_BING_CHENG_GONG = True
            with mock.patch.object(pingju, "PINGJU_GEN", Path(gen)):
                with mock.patch.object(Path, "mkdir", side_effect=OSError("拒绝访问")):
                    d1 = self._qu()          # 磁盘满
                self.assertIs(d1["credentialsReady"], False)
                d2 = self._qu()              # 空间腾出来了，Bridge 并没有重启
            self.assertIs(d2["credentialsReady"], True,
                          "告警不会消失——用户腾完空间回到页面，它还挂着")
        finally:
            pingju.JIAN_BING_CHENG_GONG = b
            import shutil
            shutil.rmtree(gen, ignore_errors=True)

    def test_qian_chang_zhong_can_cha_chu_bei_ren_mo_diao_de_mu_lu(self):
        """反过来：运行中目录被删，`/agents` **要**从 true 翻成 false。

        与上一条是一对。上一条钉「不会粘住 false」，这条钉「也不会粘住 true」——
        后者更危险，因为它悄无声息：界面不响，用户直接落到空库重新登录。
        """
        b = pingju.JIAN_BING_CHENG_GONG
        gen = tempfile.mkdtemp()
        try:
            pingju.JIAN_BING_CHENG_GONG = True
            with mock.patch.object(pingju, "PINGJU_GEN", Path(gen)), \
                    mock.patch.object(Path, "mkdir", side_effect=OSError("拒绝访问")):
                d = self._qu()
            self.assertIs(d["credentialsReady"], False,
                          "目录建不出来却报 true——界面一声不吭")
        finally:
            pingju.JIAN_BING_CHENG_GONG = b
            import shutil
            shutil.rmtree(gen, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
