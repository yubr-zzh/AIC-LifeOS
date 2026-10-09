"""限流与配额（spec 10.1、10.2、10.3；方案 15.4、9.4）。

**这里最要紧的是「窗口」这件事的形状。** 三条滑窗各自独立，同一个请求同时
落在 `u:` / `d:` / `p:` 三个键上，所以任何一条测试只要改掉「返回 None 表示放行」
这个契约，或者把 `biao` 的值类型从 deque 换成别的，下面两条就会当场红。

**内部结构（`x.biao` / `x.suo`）被测试直接读**，这是故意的：`zhi_dian` / `hui_dong`
两条要靠「把窗口起点往前推」把 60 秒的滑窗变成不等待的时间旅行，只有控制内部
结构才做得到。改这两个字段名时这两条测试必须一起改。
"""

from __future__ import annotations

import heapq
import http.client
import json
import logging
import socket
import tempfile
import threading
import time
import unittest
from collections import deque
from pathlib import Path

from lifeos.api import bridge_admin, tunnel_gw
from lifeos.api.devices import SheBiao
from lifeos.api.server import LiAnHTTPServer, LifeOSRequestHandler
from lifeos.api.tunnel_gw import (
    CHUANG_KOU,
    MEI_SHEN_PI,
    MEI_SHE_BEI,
    MEI_YONG_HU,
    TunnelGw,
    WuDui,
    XianLiu,
)
from gong_ju import deng_dai, duan_ke, jia_shi

# 浏览器发、脚本通常不发的那一个头。**只有这一个就够**：同源 fetch 与 EventSource
# 都带 `Sec-Fetch-Site: same-origin`，而 `Origin` 恰好相反——它们都不发它，所以
# `Origin` 只能用来「附加判据」不能用来「要求」。
# **两个头都挡不住主动伪造**：脚本照发就行。判据的真实作用是「把非预期流量（curl、
# 探针、健康检查）隔离在浏览器用户的窗口之外」，防误打满别人的窗口，**不是鉴权**。
TOU = {"Sec-Fetch-Site": "same-origin"}


def _kong() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    p = s.getsockname()[1]
    s.close()
    return p


class JiaMen:
    """假网关。**只实现反代真正调得到的那几个方法。**

    刻意不整体复用 `TunnelGw`：这里要验的是「主服务怎么搬上游的响应」，
    让真网关参与会把隧道协议的问题带进同一个断言里（同 `tests/test_server_threading.py`）。
    `xian` 是**真的 `XianLiu`**，但调用直接走 `TunnelGw.xian_liu`（未绑定方法），
    免得这里再抄一份转发逻辑——抄的那份就成了被测代码的替身。
    """

    def __init__(self) -> None:
        self.xian = XianLiu()
        self.shou_dao: list[dict] = []

    def zhuang_tai(self, a1):
        return "connected"

    def qing(self, a1, a2, a3=30.0):
        self.shou_dao.append(a2)
        return {"status": 200, "headers": {"content-type": "application/json"},
                "body": json.dumps({"ok": True, "path": a2["path"]}), "b64": False}

    def kai_liu(self, a1, a2, a3=30.0):
        """给一条**会结束的**流。返回 `None` 之后 `_dai_liu` 就 return 了。

        不能抛 `WuDui`：那条路进的是 `_he_cheng_liu`，它挂着心跳永远不返回，
        测试会挂在 socket 读上直到超时（我第一版就写了抛异常，症状是
        `TimeoutError` 而不是断言失败，看起来像被测代码坏了）。
        """
        return ({"status": 200, "headers": {"content-type": "text/event-stream"}},
                _Liu())

    def xian_liu(self, a1, a2, a3):
        return TunnelGw.xian_liu(self, a1, a2, a3)


class _Liu:
    """一条只吐一帧就结束的流。"""

    def __init__(self) -> None:
        self.guo = False

    def zhen(self, a1: float = 60.0):
        if self.guo:
            return None
        self.guo = True
        return {"type": "state", "sessionId": "s-1", "streamSeq": 1, "state": "idle"}

    def guan(self) -> None:
        pass


class _Qiao:
    """一个能连着发多条请求的连接。**不复用 fixture**，每条用例自己 close。"""

    def __init__(self, a1: int) -> None:
        self.c = http.client.HTTPConnection("127.0.0.1", a1, timeout=5)

    def fa(self, a1: str, a2: str = "GET", a3: dict | None = None, a4: dict | None = None):
        self.c.request(a2, a1, body=None if a3 is None else json.dumps(a3),
                       headers=a4 or {})
        r = self.c.getresponse()
        return r, r.read()

    def close(self) -> None:
        self.c.close()


class XianLiuTest(unittest.TestCase):
    def test_mei_yong_hu_60_mei_fen_zhong(self):
        """每用户 60/分钟。

        **每条换一个 deviceId。** 少了这一步这条就测不到用户窗口：单台设备
        20/分钟会先满，第 21 条就被 `d:` 挡掉，`u:` 永远数不到 60。
        （这正是任务书原文栽的地方，见报告第 1 节。）
        """
        x = XianLiu()
        for i in range(60):
            self.assertIsNone(x.guo("u1", f"d{i}", f"/agents?i={i}"), f"第 {i+1} 个就限了")
        r = x.guo("u1", "d-x", "/agents")
        self.assertIsNotNone(r, "第 61 条必须被用户窗口挡住")
        self.assertGreater(r, 0.0)
        self.assertLessEqual(r, 60.0)

    def test_mei_she_bei_20_fen_zhong(self):
        x = XianLiu()
        # 换个 user 绕开用户级窗口，专测设备级
        for i in range(20):
            self.assertIsNone(x.guo(f"u{i}", "d1", "/agents"), f"第 {i+1} 个就限了")
        self.assertIsNotNone(x.guo("u9", "d1", "/agents"))

    def test_shen_pi_lei_du_li_chuan_kou(self):
        """审批类单独 30/分钟，不与总量共用。

        同样**每条换一个 deviceId**，否则设备窗口在第 21 条就满了，
        第 31 条被 `d:` 挡住而不是被 `p:` 挡住——断言照样绿，但它证明的
        是「设备限流」而不是「审批窗口独立」，正是任务书原文的第二个坑。
        """
        x = XianLiu()
        for i in range(30):
            self.assertIsNone(x.guo("u1", f"d{i}", "/permissions/p-1"))
        self.assertIsNotNone(x.guo("u1", "d-x", "/permissions/p-1"))
        # **这条断言是整条测试存在的理由。** 它证明「不共用」：用户窗口已被
        # 30 个审批类请求吃了 30 个位置，还剩 30 个。换成共用窗口的话这里
        # 就该是 NotNone 了——那时第 31 个审批之后连普通请求都发不出去。
        self.assertIsNone(x.guo("u1", "d-y", "/agents"))

    def test_wen_zi_chu_fa_ye_suan_shen_pi_lei(self):
        """/questions* 与 /permissions* 同属审批类（方案 15.4 的两个前缀）。"""
        x = XianLiu()
        for i in range(30):
            x.guo("u1", f"d{i}", "/questions/q-1")
        self.assertIsNotNone(x.guo("u1", "d-x", "/questions/q-2"))

    def test_bu_tong_yong_hu_hu_bu_ying_xiang(self):
        x = XianLiu()
        for i in range(60):
            x.guo("u1", f"d{i}", "/agents")
        self.assertIsNone(x.guo("u2", "d2", "/agents"))

    def test_chuang_kou_hua_dong(self):
        """把窗口起点往前推 61 秒，不真 sleep。"""
        x = XianLiu()
        for i in range(60):
            x.guo("u1", f"d{i}", "/agents")
        self.assertIsNotNone(x.guo("u1", "d-x", "/agents"))
        with x.suo:
            for k in list(x.biao):
                x.biao[k] = type(x.biao[k])(t - 61.0 for t in x.biao[k])
        self.assertIsNone(x.guo("u1", "d-y", "/agents"))

    def test_bing_fa_ji_shu_zhun(self):
        """并发下名额既不能多放也不能少放。

        60 次调用**每条一个不同的 deviceId**，把 `d:` 全部摊薄，于是 6 个线程
        抢的只有 `u:u1` 这一条窗口——60 个名额，多一个少一个都算错。
        """
        x = XianLiu()
        ci = []
        suo = threading.Lock()

        def chong(a1: int) -> None:
            for j in range(10):
                r = x.guo("u1", f"d-{a1}-{j}", "/agents")
                with suo:
                    ci.append(r)

        xian = [threading.Thread(target=chong, args=(i,)) for i in range(6)]
        for t in xian:
            t.start()
        for t in xian:
            t.join()
        # 60 个名额恰好用完：放行 60 个，拒绝 0 个（并发下不能少放也不得多放）
        self.assertEqual(len([c for c in ci if c is None]), 60)

    def test_shen_pi_bu_suan_zai_she_bei_chuang_kou_li(self):
        """审批类在 `d:` 里也计数（它对所有请求生效），但**不多出一条别的键**。

        这条是纯结构断言：它不依赖任何限额，只钉住「审批类命中哪几个键」。
        """
        x = XianLiu()
        x.guo("u1", "d1", "/permissions/p-1")
        self.assertEqual(sorted(x.biao), ["d:d1", "p:u1", "u:u1"])
        self.assertEqual(len(x.biao["d:d1"]), 1)
        self.assertEqual(len(x.biao["p:u1"]), 1)

    def test_fei_shen_pi_lei_bu_sheng_cheng_p_chuang_kou(self):
        """普通请求**不**碰 `p:` 窗口。

        任务书原文的 `test_wen_zi_chu_fa_ye_suan_shen_pi_lei` 栽在这里：
        它用同一个 deviceId 连打 30 条 `/questions`，第 21 条就被设备窗口
        挡了，所以**即便 `/questions` 根本没被当成审批类，那条测试照样绿**。
        这里的断言从结构上排除这种假绿。
        """
        x = XianLiu()
        x.guo("u1", "d1", "/agents")
        self.assertNotIn("p:u1", x.biao)
        self.assertNotIn("p:u2", x.biao)

    def test_liu_cheng_lu_jing_kan_da_zhai_query(self):
        """带查询串的审批路径仍算审批类。"""
        x = XianLiu()
        x.guo("u1", "d1", "/permissions/p-1?x=1")
        self.assertIn("p:u1", x.biao)

    def test_kong_chuang_kou_de_yao_cha_di(self):
        """窗口空了就回收键。**只增不删的表是阶段 7 接上登录后的定时炸弹。**

        评审实测：20 万个随机 uid 打进去，`biao` 剩 40 万个键、约 90 MB、
        1.05 秒。今天还不是漏洞——`dang_qian_yong_hu()` 只从环境变量取值，
        攻击者造不出随机 uid；但 11.1 明写接入登录后 uid 来自 cookie，
        那时它就是外部输入。

        **「只在访问时清理」不够，这条构造就是防那个。** 第一轮用 uid 0–19，
        推进时间后**换一批全新 uid** 再打：uid 0–19 再也不会被访问到，
        只在访问时清理的实现永远碰不到它们的键。判据是「旧 uid 的键没了」，
        不是「键总数是 40」——后者在同一批 uid 上恒等于 40，是条假绿。
        """
        x = XianLiu()
        for i in range(20):
            x.guo(f"u{i}", f"d{i}", "/agents")
        # **推进时间戳后必须重算索引项的到期时刻。** 原来这行只改 `biao` 里的
        # deque，而索引项记的 `guo_qi` 是当初建索引时算出来的 `队首 + 60`——
        # deque 被整体前移 61 秒，索引项却还指着原来的时刻，回收于是认为这些
        # 键「还没到期」。手改 `biao` 等于绕过索引造出一个生产里不存在的状态，
        # 而本用例要验的正是「自然演进到过期之后会被回收掉」。
        with jia_shi(tunnel_gw) as tui_jin:
            tui_jin(61.0)
            for k in list(x.biao):
                x.biao[k] = type(x.biao[k])(t - 61.0 for t in x.biao[k])
            # 换一批**从没出现过的** uid。多打几轮是为了跨过清扫的触发间隔。
            # 每次 `guo()` 都会给新键挂索引项，`sao()` 看到旧键的索引项已到期
            # 就把它们弹掉——走的是生产里那条真实路径。
            for i in range(200):
                x.guo(f"xin{i}", f"dxin{i}", "/agents")
        with x.suo:
            # **精确集合，不是前缀匹配。** 前缀 `("u:u0","u:u1",...)` 只覆盖 40 个
            # 旧键里的 23 个，`u:u2`–`u:u9`、`d:d2`–`d:d9` 全在断言之外——一个只漏扫
            # 中段的退化实现能过。新 uid 的键形如 `u:xin0`，与 `u:u0`–`u:u19`
            # 不会误配，所以集合比较是安全的。
            jiu = {f"u:u{i}" for i in range(20)} | {f"d:d{i}" for i in range(20)}
            lao = [k for k in x.biao if k in jiu]
        self.assertEqual(lao, [], f"早就没人访问的 uid 的键留在表里：{lao[:4]}")

    def test_zou_chuang_kou_de_bu_liu_xia_ke(self):
        """**被限的请求也不许留下空键。**

        这是上面那条的另一半，也是真正会漏的那条路径。超限时 `guo()` 提前
        return，而**它已经把前面的键裁剪过了**：`u:u1` 恰好在这条请求之前
        过期，于是被清成空 deque，却因为提前 return 没走到回收那一行。
        表只增不删的话，这种「被限 + 窗口刚好空了」的组合每次漏一个键。

        **构造是承重的**：必须让**先检查的那个键**（`u:`）已过期、
        **后检查的那个键**（`d:`）正在满——顺序反了就不会漏（`u:` 满就提前
        return，`u:` 本身不空，没有空键可漏）。
        """
        x = XianLiu()
        x.biao["u:u1"] = deque(t - 61.0 for t in [time.monotonic()] * 3)  # 刚过期
        x.biao["d:d1"] = deque([time.monotonic()] * 20)                   # 正在满
        self.assertIsNotNone(x.guo("u1", "d1", "/agents"), "d: 满了就该被限")
        with x.suo:
            self.assertNotIn("u:u1", x.biao, "被裁剪成空的键留在表里没人回收")

    def test_xian_liu_fang_fa_ba_shou_bing_bu_da_guan_bu_luo_diao(self):
        """超限时**不占名额**：一条被打回的请求不能把窗口推得更满。

        少写这个语义的话，攻击者只要不停打被限的请求，自己的窗口就永远不恢复，
        自己把自己永久锁死（真实的拒绝服务，而不只是被限流）。

        **每条换一个 deviceId**，让被测的窗口确实是 `u:u1`（满在 60）而不是
        `d:d1`（满在 20）。我第一版用同一个 deviceId，结果 60 次调用只推进
        `d:` 到 20、`u:` 也只到 20——变异「超限也占名额」照样全绿，
        断言量的压根不是它以为的那个窗口。
        """
        x = XianLiu()
        for i in range(60):
            x.guo("u1", f"d{i}", "/agents")
        self.assertIsNotNone(x.guo("u1", "d-x", "/agents"))
        with x.suo:
            n = len(x.biao["u:u1"])
        self.assertEqual(n, 60, "u: 窗口本来就该是满的 60")
        for j in range(50):
            self.assertIsNotNone(x.guo("u1", "d-y", f"/agents?j={j}"))
        with x.suo:
            self.assertEqual(len(x.biao["u:u1"]), n, "被打回的请求占了名额")

    def test_fen_zhou_que_ding_liang_bu_yao_tui_cheng_jia_zhuan_shu(self):
        """限额与滑窗宽度就是方案 15.4 的四个数，写死断言。

        改常量时这条会红——那时是「有意的」改动，别当 bug 改回来。

        **`CHUANG_KOU` 必须与三个限额一起钉。** 上一版只钉了三个限额，
        评审的变异验证结果是：把 `CHUANG_KOU` 改成 5.0（窄 12 倍）与
        0.5（窄 120 倍）都**全绿**。原因在下面那条 `test_chuang_kou_hua_dong`：
        它把窗口整体前移 61 秒，于是**任何大于 1 的 `CHUANG_KOU` 都能通过**——
        一条叫「窗口会动」的测试，实际什么都没证明。
        """
        self.assertEqual((MEI_YONG_HU, MEI_SHE_BEI, MEI_SHEN_PI), (60.0, 20.0, 30.0))
        self.assertEqual(CHUANG_KOU, 60.0, "滑窗宽度变了（15.4 是 60 秒/分钟）")

    def test_retry_after_sui_shi_jian_jian_xiao(self):
        """`Retry-After` 必须随窗口推进**递减**——这是它唯一的意义。

        只断言「1 <= r <= 60」的话，把返回值写死 `60.0` 也照样过（评审实测
        全绿）。而写死 60 的后果是：客户端每次被限都等满一分钟，窗口其实
        早就空了。

        **推进一只假时钟 1.1 秒，不真睡，也不改 `x.biao`。** 改 `biao` 里的
        时间戳是时间旅行，验不了这个：它把窗口整体前移，`Retry-After` 的算式
        整体平移，差值仍在，一条写死常量的退化实现照样通过。而注入假时钟是另
        一回事——`biao` 一个字节都没动，只是「现在几点」往前走了 1.1 秒，
        与真睡 1.1 秒在算术上完全等价，只是没有 Windows 上那毫秒级抖动
        （`assertLess(r2, r1)` 与下面那条区间，原来就是为这个抖动留的余量）。
        """
        x = XianLiu()
        for i in range(60):
            x.guo("u1", f"d{i}", "/agents")
        r1 = x.guo("u1", "d-x", "/agents")
        self.assertIsNotNone(r1, "窗口已满，第 61 条必须被限")
        self.assertAlmostEqual(r1, CHUANG_KOU, delta=1.0,
                               msg="刚打满时 Retry-After 应当≈整个窗口宽度")
        with jia_shi(tunnel_gw) as tui_jin:
            tui_jin(1.1)
            r2 = x.guo("u1", "d-y", "/agents")
        self.assertIsNotNone(r2)
        self.assertLess(r2, r1, "过了一秒，Retry-After 必须变小（写死常量会栽在这）")
        # **区间而不是 `assertAlmostEqual(delta=0.5)`**：Windows 上一次 1.1 秒的
        # sleep 偏差就能越过那条窄带，症状是随机 flake。区间放宽到 [r1-1.6, r1-0.9]
        # 仍抓住要防的东西——写死常量的退化实现会让 r2 == r1，落在上界之外。
        self.assertGreaterEqual(r2, r1 - 1.6, "退得比窗口宽度还多")
        self.assertLessEqual(r2, r1 - 0.9, "几乎没退：写死了常量")


class _ShuBiao(dict):
    """数 `items()` 被迭代出多少条目的字典。

    **为什么量「迭代次数」而不是「表多大」或「扫完剩多少」：** 三个量里只有它
    能在两种实现上分出高下。全表扫描会迭代整张表（计数 = 表大小），堆方案只
    弹已到期的键（计数 = 已到期键数，与表大小无关）。第一版记的是
    `len(x.biao)`——可 `sao()` 扫完键就全删了，之后再拿「剩多少」去比，
    两种实现都得到「什么都没剩」，于是全表扫描照样通过。

    `__len__` / `__contains__` / `get` 都不计数：判窗口满用的 `len(q)` 是 O(1)
    的一次调用，把它算进去会让 1 次调用看着像 1 个键，量出来的东西没有意义。
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fang = 0

    def items(self):
        for k, v in super().items():
            self.fang += 1
            yield k, v


class HuiShouDaiCeTest(unittest.TestCase):
    """回收路径的代价与正确性（阶段六收口 07 域）。

    **这一组是 07 域的核心：证明回收不再随历史 uid 数量线性阻塞。**
    原实现每 `SAO_JIAN` 次请求持全表锁做一次 O(表大小) 扫描。实测基线
    （`.scratch/liang_sao.py`，40 万键，2026-10-02）：**中位 237.61 ms**，
    而同期一次正常请求的锁持有时间是 **0.001 ms**——相差五个数量级。
    也就是说那个 40 万键的表里，**随便一条请求都有约四分之一秒进不去**，
    而它扫出来的键已经全部过期、回收它们对当次请求毫无帮助。

    ⇒ 走规格 §4.7 的方案 A：按过期时间建索引，只处理已到期的键。
    """

    # **规模按「能在 CI 上稳定跑完」定，不是按「越大越能证明」。** 40 万键要
    # 造 1 秒多、扫 0.24 秒；而判据是「扫的键数不随表大小线性涨」，10 万键
    # 已经足够把「O(表大小)」与「O(已到期键数)」的差距拉开三个数量级。
    # 真要复原 40 万那个数，去跑 `.scratch/liang_sao.py`，别把 40 万写进用例。
    JIAN = 100_000

    def _zao_lao_jian(self, x: XianLiu, n: int) -> None:
        """直插 n 个**已过期**的键。造键不走 `guo()`——那会把造键自己的开销
        混进要测的东西里。

        **必须连索引项一起造。** 直插 `biao` 而不挂 `_dui` 项的话，回收压根
        不知道这些键存在——那条实现会「一个都不删」而本用例照样通过，
        于是判据反过来帮了倒忙。用 `x.sao()` 建它们也不行（那是真去回收）。
        这里按 `_suan_lei_suo` 的算法自己算一遍到期时刻再压堆。
        """
        now = time.monotonic()
        with x.suo:
            for i in range(n):
                for p in ("u", "d"):
                    k = f"{p}:lao{i}"
                    x.biao[k] = deque([now - CHUANG_KOU - 1.0])
                    x._xu_hao += 1
                    x._hao[k] = x._xu_hao
                    heapq.heappush(x._dui, (now - 1.0, x._xu_hao, k))

    def _zao_huo_jian(self, x: XianLiu, n: int) -> None:
        """直插 n 个**未到期**的键，同样带索引项（见 `_zao_lao_jian`）。"""
        now = time.monotonic()
        with x.suo:
            for i in range(n):
                for p in ("u", "d"):
                    k = f"{p}:huo{i}"
                    x.biao[k] = deque([now - 1.0])
                    x._xu_hao += 1
                    x._hao[k] = x._xu_hao
                    heapq.heappush(x._dui, (now - 1.0 + CHUANG_KOU, x._xu_hao, k))

    def _sao_ci_shu(self, x: XianLiu, a1: float) -> int:
        """跑一次 `sao()`，返回它**迭代访问了多少个键**。

        **直接换掉 `x.biao` 的类型，不包 `sao`。** 包 `sao` 的话新旧实现得分
        两套写法（递归调用、收尾时机各不相同），而换掉 dict 类型对两者是
        同一段代码。

        **`finally` 里换回原字典会弄丢回收结果。** `sao()` 删的是 `_ShuBiao`
        这个副本里的键；退出时把 `x.biao` 指回原字典，等于把「回收前」的状态
        整个还原——于是后面那条「未到期的键保住了」的断言在**一张从没被回收过
        的表**上数，怎么数都不对。第一版正是这么写的，报的是
        `400000 != 200000`。

        所以这里**不还原**：`x.biao` 就让它是 `_ShuBiao`，回收结果留在上面，
        调用方接着数的正是回收之后那张表。
        """
        shu = _ShuBiao(x.biao)
        x.biao = shu                                  # type: ignore[assignment]
        x.sao(a1)
        return shu.fang

    def test_da_lao_jian_sao_de_bu_hua_fei_shen_me(self):
        """**大表回收不许做全表扫描**——这条是本域存在的理由。

        判据是「扫过的键数与**已到期**的键数成正比」，不是「扫过的键数 <
        表大小」这种半吊子断言：后者容不下「只扫一半」这种部分优化的退化实现，
        也说明不了代价跟着什么走。

        **表里必须混进未到期的键。** 纯过期键那张表在旧实现下扫完就空了，
        两种实现都「成功回收」，差别只落在迭代量上——而迭代量正是这条的判据。
        混进一批未到期的键、并要求它们活着之后，「扫了多少」这条曲线在两种
        实现上才真正分得开。

        **阈值 `JIAN * 3` 而非 `2 * JIAN`：** 堆的调整与「陈旧项跳过」会让它
        多弹几条（同一键的多条索引项都得跳过），而**关键是它不随表大小涨**：
        把 `JIAN` 放大十倍这个数不动，全表扫描则直接变十倍。
        """
        x = XianLiu()
        self._zao_lao_jian(x, self.JIAN)
        now = time.monotonic()
        # 一批**未到期**的键放在表里。堆方案不该碰它们，全表扫描则会。
        self._zao_huo_jian(x, self.JIAN)
        fang = self._sao_ci_shu(x, now)
        self.assertLessEqual(fang, self.JIAN * 3,
                             f"回收扫了 {fang} 个键（表大小 {len(x.biao)}）"
                             "——它还在随表大小线性增长")
        with x.suo:
            # 未到期的是 2 * JIAN（u:huo 与 d:huo 各一），剩下的都该被回收掉。
            self.assertEqual(len(x.biao), self.JIAN * 2,
                             "未到期的键没保住，或已到期的键没被回收")

    def test_da_lao_jian_sao_de_bu_hua_fei_qing_qiu(self):
        """**大表在回收时，正常请求不该被整条挡住。**

        这条与上一条量的是同一件事，但判据落在**调用方能观察到的行为**上。

        **表里必须是「未到期的大头 + 已到期的一小撮」。** 第一版造的是 20 万个
        已过期键，于是回收**本来就该**逐个弹掉它们——287 ms 是必要代价，
        不是缺陷，拿它当判据等于要求「回收不许回收」。而真正要防的场景是：
        表很大是因为**大量键还没到期**（活跃用户多），这时回收不该为它们付
        一分代价。这一版的构造与那个场景一致：未到期 20 万、已到期 3 个。

        **阈值 50 ms：** 原实现在同类构造下是 237 ms 量级；堆方案只看堆顶那
        三个已到期项，其余一条不碰。
        """
        x = XianLiu()
        self._zao_huo_jian(x, self.JIAN)      # 20 万个未到期的键 = 活跃用户多
        self._zao_lao_jian(x, 3)              # 已过期的只有 3 个
        # 跨过 `SAO_JIAN` 次触发线，让这次 `guo()` 真的触发一次回收。
        for i in range(tunnel_gw.SAO_JIAN - 1):
            x.guo("u:xu", f"d:xu{i}", "/agents")
        t0 = time.perf_counter()
        x.guo("u:huo-nei", "d:huo-nei", "/agents")
        hua = (time.perf_counter() - t0) * 1000.0
        self.assertLess(hua, 50.0,
                        f"一次普通请求被回收拖了 {hua:.1f} ms（基线是 237.61 ms）")

    def test_hui_shou_bie_sha_di_jian(self):
        """回收只删**已到期**的键，没到期的原样留着。

        **走 `guo()` 建键，不直插 `biao`。** 直插的键没有索引项，回收压根
        不知道它存在——那条实现会一个都不删而本用例照样红，测的就不是
        「回收只删该删的」而是「回收认不认得手工塞进来的键」。
        """
        x = XianLiu()
        x.guo("guo", "d-guo", "/agents")      # 一条请求 ⇒ 键活着、索引项已挂
        x.guo("huo", "d-huo", "/agents")
        now = time.monotonic()
        with x.suo:
            # 把 `u:guo` 的窗口推到过期，`u:huo` 留着；同时重算两者的索引项，
            # 让 `u:guo` 的到期时刻落在 now 之前——这才是「已到期」在索引里的
            # 真正含义（队首 + CHUANG_KOU <= now）。
            for k in ("u:guo", "u:huo"):
                yi = now - CHUANG_KOU - 1.0 if k == "u:guo" else now - 1.0
                x.biao[k] = deque([yi])
            x._hao.clear()
            x._dui.clear()
            for k in ("u:guo", "u:huo"):
                x._xu_hao += 1
                x._hao[k] = x._xu_hao
                heapq.heappush(x._dui, (x.biao[k][0] + CHUANG_KOU, x._xu_hao, k))
        x.sao(now)
        with x.suo:
            self.assertNotIn("u:guo", x.biao, "已到期的键没被回收")
            self.assertIn("u:huo", x.biao, "还没到期的键被误删了")
            self.assertEqual(len(x.biao["u:huo"]), 1, "活着的键内容被动过")

    def test_luo_lei_bu_hai_zai_cha_kan_li_bie_xiang_key(self):
        """**陈旧的索引项不许删掉刚被重新使用的键。**

        这是索引方案最容易出的错，也是**版本号存在的全部理由**：键被回收之后
        同一主体又回来了，堆里若还留着上一代那条项，它的到期时刻比新窗口
        **更早**（它记的是上一代队首 + 60）。按时间弹堆就会在新窗口刚建立的
        那一刻把它连根拔掉——于是「刚被限流过的 uid」立刻获得一份空窗口，
        反复重连即绕过限流。

        **必须手工塞那条陈旧项，靠时间自然演进造不出来。** `_suan_lei_suo`
        在每次追加请求时会把旧项**撤销**掉，所以堆里不会自然攒下陈旧项。
        第一版试图用假时钟走一遍真实路径造它，结果造不出来——那条测试在
        「去掉版本号核对」的变异下**照样全绿**，护栏等于没被守住。这里直接
        构造那个时序错位状态，钉的正是版本号核对这一行。

        **变异证据：** 去掉 `if self._hao.get(k, -1) != hao: continue` 之后，
        本条立刻红。
        """
        x = XianLiu()
        x.guo("huai", "d-huai", "/agents")
        now = time.monotonic()
        # 回收掉这个键，并挂一条**上一代**的索引项（到期时刻早于新窗口）。
        with x.suo:
            x.biao.pop("u:huai")
            x._hao.pop("u:huai", None)
            x._dui = [e for e in x._dui if e[2] != "u:huai"]
            x._dui.append((now - 1.0, 999, "u:huai"))     # 陈旧项：版本号 999
            heapq.heapify(x._dui)
        # 同一主体回来了：新窗口活着，索引项指向新的到期时刻。
        x.guo("huai", "d-huai", "/agents")
        with x.suo:
            self.assertNotEqual(x._hao["u:huai"], 999, "前提不成立：新项没建起来")
        # 回收跑到陈旧项那里（时刻已过），它必须被**跳过**，而不是被当成
        # 「这个键该回收了」。
        #
        # **判据是「回收之后堆里只剩一条 `u:huai` 项」，不是「键还在」。**
        # 键两种实现下都在：陈旧项的时刻虽已过，可它指向的那个键的窗口
        # 装着**新时间戳**，裁剪循环一条也弹不掉，于是走到「窗口还剩东西」
        # 那条路——第一版把新项又挂了一遍，`break` 收工。
        # 结果是堆里同一个键攒了 **2 条**有效项（还有一条版本号对不上的
        # 陈旧项）。索引长度 = 活跃键数这个性质被破坏，而它正是本域要的：
        # 每次回收都往堆里多塞一条，回收越勤索引越胖，与「回收是为了减轻负担」
        # 正好相反。键本身完好，所以只看键的断言在两种实现下都绿。
        x.sao(now + 0.5)
        with x.suo:
            self.assertIn("u:huai", x.biao, "键不该被删——它装着新窗口")
            self.assertEqual(len(x.biao["u:huai"]), 1,
                             "刚被重新使用的键内容被动过——等于白送一份空窗口")
            xiang_u = [e for e in x._dui if e[2] == "u:huai"]
            self.assertEqual(len(xiang_u), 1,
                             f"回收往堆里塞了 {len(xiang_u)} 条 u:huai 项，"
                             "陈旧项被当成了有效项")
        # 再扫一次：那条陈旧项这回该已被弹走，新窗口不受影响。
        x.sao(now + 1.0)
        with x.suo:
            self.assertIn("u:huai", x.biao, "陈旧索引项第二次又动了这个键")
            self.assertEqual(len(x.biao["u:huai"]), 1)
            self.assertEqual(len([e for e in x._dui if e[2] == "u:huai"]), 1)

    def test_lao_dao_de_key_bu_chong_dian_wen(self):
        """重连同一主体不该在索引里堆出无限多条。

        一个 uid 每来一次请求就往索引里塞一条的话，索引自己就变成了第二个
        只增不删的表——把原来的问题搬了个地方。判据是**键数**而不是
        「索引里没有重复项」：索引允许重复（陈旧项要能被跳过而不是立即删），
        要求它不重复等于要求每次来都清空，那要么 O(n) 要么堵死。
        """
        x = XianLiu()
        for _ in range(50):
            x.guo("u1", "d1", "/agents")
        # 索引按过期时间排，**同一个键的多次请求必须合并成一条**。
        # 判据是键数而非「没有重复项」：陈旧项允许留在堆里（回收时跳过而不是
        # 立即删），要求堆里绝不重复等于要求每次请求都重排一次索引。
        with x.suo:
            names = [e[0] for e in x._dui]
        # 50 次请求、3 把键（u:u1 / d:d1 两条 + 不生成 p:）。索引条数必须
        # 远小于「每请求一条」：给一个宽松但确实排除「每请求一条」的界。
        self.assertLessEqual(len(names), 3,
                             f"50 次请求在索引里堆了 {len(names)} 条——"
                             "索引自己变成了只增不删的表")

    def test_hui_shou_hou_xin_jian_zheng_chang_gong_zuo(self):
        """回收之后新请求照常计数与限流（回收不许把功能改坏）。"""
        x = XianLiu()
        self._zao_lao_jian(x, 1000)
        x.sao(time.monotonic())
        for i in range(60):
            self.assertIsNone(x.guo("u1", f"d{i}", "/agents"), f"第 {i+1} 个就限了")
        self.assertIsNotNone(x.guo("u1", "d-x", "/agents"),
                             "回收之后限流没生效")


class XianLiuJieFaTest(unittest.TestCase):
    """`TunnelGw.xian_liu` 只是薄薄一层转发，但它是 `server.py` 唯一的入口，
    名字或签名对不上时 `server.py` 会在**运行时**才炸（AttributeError → 500）。"""

    def test_gw_shang_de_fang_fa_cun_zai(self):
        from lifeos.api.tunnel_gw import TunnelGw
        self.assertTrue(hasattr(TunnelGw, "xian_liu"))
        gw = TunnelGw.__new__(TunnelGw)   # 不跑 __init__（那要一张真设备表）
        gw.xian = XianLiu()
        self.assertIsNone(gw.xian_liu("u1", "d1", "/agents"))


class FanDaiCeShi(unittest.TestCase):
    """`server.py` 的 `_dai_li` 真的过了限流：429 + Retry-After + rate_limited。

    **限流表用真 `XianLiu`，但网关是替身。** 任务 8 的账本里记着一次假绿：
    假对象自带了判据要用的属性，于是判据走了短路分支。这里若让替身自己
    实现 `xian_liu`，测的就是我造的桩；所以替身只做「把请求搬给上游」，
    限流那部分挂**真的** `XianLiu`，链路是 `server._dai_li` → `gw.xian_liu`
    → `XianLiu.guo`，中间没有一行是测试自己写的判断。
    """

    @classmethod
    def setUpClass(cls):
        cls.mu = tempfile.TemporaryDirectory()
        cls.yuan = (bridge_admin.SHE, bridge_admin.GW, bridge_admin.MA)
        cls.biao = SheBiao(Path(cls.mu.name) / "d.json", logging.getLogger("test.ll"))
        cls.biao.jia("local", "测试机", "i-ll")
        cls.gw = JiaMen()
        bridge_admin.zhuang(cls.biao, cls.gw, bridge_admin.MA)
        cls.duan = _kong()
        cls.fu = LiAnHTTPServer(("127.0.0.1", cls.duan), LifeOSRequestHandler)
        threading.Thread(target=cls.fu.serve_forever, daemon=True).start()
        # 构造完就已经 bind+listen，等端口真的连得上，别按固定时长猜。
        deng_dai(lambda: duan_ke(cls.duan), chao=5.0,
                 msg=f"端口 {cls.duan} 连不上")

    @classmethod
    def tearDownClass(cls):
        cls.fu.shutdown()
        cls.fu.server_close()
        bridge_admin.zhuang(*cls.yuan)
        cls.mu.cleanup()

    def setUp(self):
        self.gw.xian = XianLiu()   # 每条用例一张干净的窗口表

    def _ma(self):
        k = _Qiao(self.duan)
        try:
            return json.loads(k.fa("/api/bridge/info")[1])["csrf"]
        finally:
            k.close()

    def _fa(self, a1: str, a2: str = "GET", a3: dict | None = None,
            a4: dict | None = None):
        k = _Qiao(self.duan)
        try:
            return k.fa(a1, a2, a3, a4)
        finally:
            k.close()

    def test_chao_xian_hui_429_dai_retry_after(self):
        for i in range(20):
            r, _ = self._fa("/agent-api/agents")
            self.assertEqual(r.status, 200, f"第 {i+1} 条不该被限")
        r, b = self._fa("/agent-api/agents")
        self.assertEqual(r.status, 429)
        self.assertEqual(json.loads(b)["error"]["code"], "rate_limited")
        # **Retry-After 是这条限流的核心产出之一。** 少了它，客户端（以及
        # 任何在扫 429 的脚本）无从知道该等多久，只能疯狂重试把窗口压得更死。
        self.assertIsNotNone(r.getheader("retry-after"))
        self.assertGreaterEqual(int(r.getheader("retry-after")), 1)
        self.assertLessEqual(int(r.getheader("retry-after")), 60)

    def test_429_ye_yao_you_content_length(self):
        """`_send_json` 加了额外响应头，content-length 仍必须重算。

        keep-alive 下写错长度就是串响应——下一个请求的解析整体错位。
        """
        for _ in range(20):
            self._fa("/agent-api/agents")
        k = _Qiao(self.duan)
        try:
            r, b = k.fa("/agent-api/agents")
            self.assertEqual(r.status, 429)
            self.assertEqual(int(r.getheader("content-length")), len(b))
            r2, _ = k.fa("/agent-api/agents")
            self.assertEqual(r2.status, 429, "同一条连接上第二条仍然解析正确")
        finally:
            k.close()

    def test_bei_lim_de_qing_qiu_bu_dao_da_she_bei(self):
        """被限的请求**不能**转进隧道。POST 必须带 CSRF（9.3），否则先被
        `_fangxing` 挡成 403，压根走不到限流——那条断言就白写了。"""
        ma = self._ma()
        for _ in range(20):
            self._fa("/agent-api/agents")
        n = len(self.gw.shou_dao)
        r, _ = self._fa("/agent-api/permissions/p-1", "POST", {},
                        {"content-type": "application/json", "x-lifeos-csrf": ma})
        self.assertEqual(r.status, 429)
        self.assertEqual(len(self.gw.shou_dao), n, "被限的请求漏进了隧道")

    def test_wei_sui_yuan_bu_de_da_xian_liu_chuang_kou(self):
        """**没有浏览器来源头的请求不许占限流窗口的名额。**

        这是评审复现的拒绝服务：`_dai_li` 原先对 GET 完全不鉴权，于是 20 个
        无凭据的 `GET /agent-api/agents` 就把 `d:` 窗口打满，接下来 60 秒内
        **合法用户**的 POST 与 GET 全部 429。攻击成本 20 个无凭据 GET。

        **这一条只挡住了「没带来源头」的流量。** 请求头不是浏览器专属财产，
        攻击者伪造一个 `Sec-Fetch-Site: same-origin` 即可回到原状——判据的真实
        作用是把**非预期**流量（curl、探针、健康检查）隔离在浏览器窗口之外，
        防的是误打满别人的窗口，**不是鉴权**。真正的鉴权在接入登录之后
        （spec 9.3/11.4：占位 userId 期间主服务不得公网暴露）。

        判据是「合法请求仍然通」而不是「攻击请求被拒」——后者太弱：一个
        把 `_shou_quan_guan()` 提到限流之前的实现也能让它过，而那正是
        任务书提醒会让 SSE 全挂的那条路。
        """
        for _ in range(60):            # 远超 d: 的 20 条
            self._fa("/agent-api/agents")     # 无任何来源头 = 攻击者
        r, _ = self._fa("/agent-api/agents", "GET", None, TOU)
        self.assertEqual(r.status, 200, "无凭据请求把合法用户锁死了")
        ma = self._ma()
        r, _ = self._fa("/agent-api/sessions", "POST", {},
                        {**TOU, "content-type": "application/json", "x-lifeos-csrf": ma})
        self.assertEqual(r.status, 200, "合法用户的 POST 也被无凭据 GET 锁死了")

    def test_jia_lai_yuan_bu_zhan_chuang_kou(self):
        """伪造的 `Sec-Fetch-Site: cross-site` 不算浏览器来源（判据要校值）。

        只判「头存在」的话，脚本带上 `cross-site` 就能占用浏览器用户的窗口——
        判据形同虚设。这条与 `test_liu_liu_ke_yi_chi_you_yuan_chuang_kou`
        是一对：真浏览器来源照旧占名额，不可信的值不占。
        """
        for i in range(20):
            r, _ = self._fa("/agent-api/agents", "GET", None,
                            {"Sec-Fetch-Site": "cross-site"})
            self.assertEqual(r.status, 200, f"第 {i+1} 条不该被限")
        r, _ = self._fa("/agent-api/agents", "GET", None, TOU)
        self.assertEqual(r.status, 200, "伪造的 cross-site 把浏览器窗口打满了吗")

    def test_liu_liu_ke_yi_chi_you_yuan_chuang_kou(self):
        """浏览器来源的请求**照旧占名额**——否则限流形同虚设。

        这条与上一条是一对：把「所有人都豁免」当成修法，上面 60 条带头的
        攻击请求照样打满窗口，合法用户照样被锁死。
        """
        for i in range(20):
            r, _ = self._fa("/agent-api/agents", "GET", None, TOU)
            self.assertEqual(r.status, 200, f"第 {i+1} 条不该被限")
        r, _ = self._fa("/agent-api/agents", "GET", None, TOU)
        self.assertEqual(r.status, 429, "带来源头的请求不占名额 ⇒ 限流没生效")

    def test_429_de_chi_qiu_qi_dai_dian_bu_ke_yi_luo_diao(self):
        """**429 分支必须先读掉请求体。** keep-alive 下留着它就串响应。

        评审真机复现的形状：窗口打满 → 发一个带 212 字节 body 的 PUT
        （HTTP/1.1 keep-alive）→ 第一次读 429，**同一条连接上第二条请求
        拿到 400**，日志里是 `('{"text": "xxx..."}GET /agent-api/agents HTTP/1.1')`：
        上一条的 body 被当成了下一个请求行。

        判据是**同一条连接上的第二条仍然是 429**（解析没错位）。只看第一条
        是 429 的话，什么都不证明——原实现的第一个响应本来就是对的。
        """
        for _ in range(20):
            self._fa("/agent-api/agents", "GET", None, TOU)
        shen = json.dumps({"text": "x" * 200})
        ma = self._ma()      # PUT 也要过 CSRF（9.3），否则先被 403 挡掉，压根走不到限流
        k = _Qiao(self.duan)
        try:
            k.c.request("PUT", "/agent-api/sessions/s-1/mode", body=shen,
                        headers={"content-type": "application/json",
                                 "x-lifeos-csrf": ma, **TOU,
                                 "content-length": str(len(shen))})
            r = k.c.getresponse()
            r.read()
            self.assertEqual(r.status, 429, "带体的 PUT 也该被限")
            r2, _ = k.fa("/agent-api/agents", "GET", None, TOU)
            self.assertEqual(r2.status, 429,
                             "同一条连接上第二条解析错位了（body 没读干净）")
        finally:
            k.close()

    def test_wu_liu_liu_de_zhu_bu_chuan_bu_ke_yi_shu_yong_wu_xian(self):
        """无凭据的 `/stream` **不能开成无界流**（评审第 8 条）。

        `/stream` 长期豁免限流（长连接不占速率，10.1 的分层），而它原先
        **也不做任何鉴权**——`_dai_li` 的闸门只管非 GET。两个豁免叠在一起
        就是：任何人可以开无限条 `/agent-api/stream`，评审实测 66 条全放行。
        每条占一个线程（`ThreadingHTTPServer`），这是最便宜的一种拒绝服务。

        判据是**响应状态**：无来源头的 `/stream` 不得回 200。**只读头不读
        body**——真放行了的话 body 是永不结束的 SSE，`read()` 会挂到超时，
        症状是 `TimeoutError` 而不是断言失败，看着像被测代码坏了。
        """
        k = _Qiao(self.duan)
        try:
            k.c.request("GET", "/agent-api/stream")
            r = k.c.getresponse()
            self.assertEqual(r.status, 403, "无凭据的 /stream 被放行 ⇒ 无界流")
            self.assertEqual(r.version, 11, "拒绝也要是完整的 HTTP/1.1 响应")
        finally:
            k.close()

    def test_dai_yuan_de_liu_cheng_hao_ha_bu_shou_lim(self):
        """带来源头的 `/stream` 仍然 200 —— 收口不许把 SSE 一起收掉。

        这是上面那条的另一半：把 `/stream` 也按 CSRF 拦掉（任务书点名要
        避免的那条路）会让 `EventSource` 100% 连不上、界面全黑。
        """
        for _ in range(20):
            self._fa("/agent-api/agents", "GET", None, TOU)   # 先把速率窗口打满
        k = _Qiao(self.duan)
        try:
            k.c.request("GET", "/agent-api/stream", headers=TOU)
            r = k.c.getresponse()          # 只取响应头
            self.assertEqual(r.status, 200, "浏览器发起的 /stream 被拒了")
        finally:
            k.close()

    def test_liu_cheng_bu_shou_lim(self):
        """SSE 不走限流——它占的是连接数不是速率（spec 10.1 的分层）。

        **先把速率窗口打满，再连 `/stream`：仍然 200。** 只连一次证明不了
        什么——限流没接线时它也是 200。顺序反过来才是判据。

        **20 条打窗口的请求与 `/stream` 都必须带 `TOU`。** 无来源头的请求另走
        一套匿名窗口（评审第 7 条的修法），不带 `TOU` 这 20 条压根打不满
        `d:`——`/stream` 拿到 200 就与限流毫无关系，这条从「守顺序」退化成
        永远绿。带 `TOU` 之后它证明的仍是同一件事：窗口真满时 `/stream` 照旧放行。

        **只读响应头不读 body。** `_dai_liu` 故意不写 chunked 的结束块
        （SSE 本来就该一直挂着），`http.client` 的 `read()` 会一直等那个
        结束块，于是这条测试会挂在 socket 上到超时——症状是 `TimeoutError`
        而不是断言失败，看着像被测代码坏了。
        """
        for i in range(20):
            r, _ = self._fa("/agent-api/agents", "GET", None, TOU)
            self.assertEqual(r.status, 200, f"第 {i+1} 条不该被限")
        k = _Qiao(self.duan)
        try:
            k.c.request("GET", "/agent-api/stream", headers=TOU)
            r = k.c.getresponse()          # 只取响应头
            self.assertEqual(r.status, 200,
                             "窗口已满时 /stream 仍应放行（长连接不占速率）")
        finally:
            k.close()

    def test_mei_tiao_fen_zhou_hui_yong_jin_dui(self):
        """两台设备各自 20 条，**不是**合起来 20 条（15.4 的 d: 窗口是每设备）。

        顺带钉住主键是 deviceId 而非 userId：反代走 `du_she()` 拿到的
        是当前用户那台设备，所以同一个 userId 下的不同 deviceId 才是
        真正能同时存在的两条限额。
        """
        x = XianLiu()
        for i in range(20):
            self.assertIsNone(x.guo("u1", "dA", "/agents"))
        # 换设备：用户窗口才用了 20/60，还很空
        self.assertIsNone(x.guo("u1", "dB", "/agents"))
        self.assertIsNotNone(x.guo("u2", "dA", "/agents"))


if __name__ == "__main__":
    unittest.main()
