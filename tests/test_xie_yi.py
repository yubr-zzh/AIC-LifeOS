"""契约层（`lifeos/api/xie_yi.py`）的纯函数测试——**不起端口、不碰隧道**。

判据只有一条：解析/校验/构造必须与 spec 6.2 一字对应。这里每个不合规的输入
都对应一次对端真的可能发出来的消息（阶段 6 实测「协议字段被信任」出了六次），
所以断言的是「抛 `XieYiCuoWu`」而不是「返回某个兜底值」——兜底就是静默丢帧：
`id` 兜底成空串后查表查不到，帧没了、日志没有、名额还占着。

`frame` 与 `close` 只验 `id` 形状与载荷类型（`he_hao` + 调用方的 isinstance），
载荷语义不归契约层管（15.3.2：网关不解析帧内容），所以这里不单列。
"""

from __future__ import annotations

import unittest

from lifeos.api.xie_yi import Qiu, XieYiCuoWu, Ying, he_hao, jie_qiu, jie_ying, zhi_qiu

# `id` 的形状照 `_song` 的生成方式：`"r-" + secrets.token_hex(4)`。
HAO = "r-1a2b3c4d"
# 哨兵：这个键要**整个去掉**。不能用 `None` 表示缺键——`body: null` 本身是合法值。
QUE = object()


def qiu(**a1) -> dict:
    """一条合法 request；`a1` 覆盖字段，值为 `QUE` 表示把该键删掉。"""
    wen: dict = {"t": "request", "id": HAO, "method": "GET", "path": "/health",
                 "query": "", "headers": {}, "body": None}
    for k, v in a1.items():
        if v is QUE:
            wen.pop(k, None)
        else:
            wen[k] = v
    return wen


def ying(**a1) -> dict:
    """一条合法 response；`a1` 同上。"""
    wen: dict = {"t": "response", "id": HAO, "status": 200,
                 "headers": {"content-type": "application/json"},
                 "body": '{"ok":true}', "b64": False}
    for k, v in a1.items():
        if v is QUE:
            wen.pop(k, None)
        else:
            wen[k] = v
    return wen


class QiuTest(unittest.TestCase):
    """「云端 → Bridge」的 request：六键齐全，各合其规。"""

    def test_he_fa_qing_quan_du_tong_guo(self):
        q = jie_qiu(qiu())
        self.assertIsInstance(q, Qiu)
        self.assertEqual(q.id, HAO)
        self.assertEqual(q.method, "GET")
        self.assertEqual(q.path, "/health")
        self.assertEqual(q.query, "")
        self.assertEqual(q.headers, {})
        self.assertIsNone(q.body)
        # 带体的也要原样过得去，一个字段都不能悄悄变形
        q = jie_qiu(qiu(method="POST", path="/permissions/p-1",
                        query="token=abc", headers={"x-bridge-token": "abc"},
                        body='{"decision":"allow"}'))
        self.assertEqual(q.method, "POST")
        self.assertEqual(q.headers, {"x-bridge-token": "abc"})
        self.assertEqual(q.body, '{"decision":"allow"}')

    def test_que_ren_yi_jian_ji_bao(self):
        """六键缺任何一个都不行。**没有「缺 query 就按空串」这条路。**"""
        for jian in ("id", "method", "path", "query", "headers", "body"):
            with self.subTest(jian=jian):
                with self.assertRaises(XieYiCuoWu) as c:
                    jie_qiu(qiu(**{jian: QUE}))
                self.assertTrue(c.exception.code)

    def test_id_ge_shi_cuo(self):
        """空串 / `r-` / 超长 / 非 hex / 大写 / 不是字符串，一律拒绝。

        这是本层最要紧的一条：现状是 `str(x.get("id") or "")`，**id 缺失就静默
        变成空串**，查表查不到就丢帧，无日志无报错（11.1 接入登录后 id 就是
        可被外部触发的路径）。
        """
        for huai in ("", "r-", "r-1", "r-1234567", "r-123456789", "r-1234567g",
                     "r-1234567G", "R-12345678", "r_12345678", "x-12345678",
                     "r-12345678 ", " r-12345678", None, 123, ["r-1a2b3c4d"]):
            with self.subTest(huai=huai):
                with self.assertRaises(XieYiCuoWu):
                    jie_qiu(qiu(id=huai))

    def test_lu_jing_bu_shi_xie_gang_kai_tou(self):
        """`path` 必须是 `/` 开头的字符串（`_da` 拿它拼回环 URL）。"""
        for huai in ("health", "", "agent-api/x", None, 0, ["/health"]):
            with self.subTest(huai=huai):
                with self.assertRaises(XieYiCuoWu):
                    jie_qiu(qiu(path=huai))

    def test_tou_shi_lie_biao(self):
        """`headers` 是个 list。对应既有的容错用例
        （`test_gw_route.py::test_ying_da_bu_he_fa_tou_shi_wu_dui`）：那边是
        response 的 headers 是 list，这边是 request 的同一条规则。"""
        with self.assertRaises(XieYiCuoWu):
            jie_qiu(qiu(headers=["x"]))

    def test_tou_bu_shi_zi_fu_chuan_dui_zi_fu_chuan(self):
        for huai in ({"a": 1}, {"a": None}, {1: "a"}, "x", None):
            with self.subTest(huai=huai):
                with self.assertRaises(XieYiCuoWu):
                    jie_qiu(qiu(headers=huai))

    def test_body_shi_int(self):
        for huai in (1, 0, [], {}, True):
            with self.subTest(huai=huai):
                with self.assertRaises(XieYiCuoWu):
                    jie_qiu(qiu(body=huai))

    def test_method_he_query_bu_shi_zi_fu_chuan(self):
        for jian in ("method", "query"):
            for huai in (None, 1, [], {}):
                with self.subTest(jian=jian, huai=huai):
                    with self.assertRaises(XieYiCuoWu):
                        jie_qiu(qiu(**{jian: huai}))

    def test_rong_ren_duo_jian(self):
        """多出来的键**容忍**：协议加字段时旧的一端不该因此全线断开，而本层
        只认 spec 6.2 列出的这几个。出口只发这六个由 `zhi_qiu` 保证。"""
        q = jie_qiu(qiu(wei_lai="随便"))
        self.assertEqual(q.path, "/health")
        self.assertFalse(hasattr(q, "wei_lai"))


class YingTest(unittest.TestCase):
    """「Bridge → 云端」的 response：五键齐全，`status` 可 `int()`。"""

    def test_he_fa_ying_quan_du_tong_guo(self):
        y = jie_ying(ying())
        self.assertIsInstance(y, Ying)
        self.assertEqual(y.id, HAO)
        self.assertEqual(y.status, 200)
        self.assertEqual(y.headers, {"content-type": "application/json"})
        self.assertEqual(y.body, '{"ok":true}')
        self.assertFalse(y.b64)

    def test_que_ren_yi_jian_ji_bao(self):
        for jian in ("id", "status", "headers", "body", "b64"):
            with self.subTest(jian=jian):
                with self.assertRaises(XieYiCuoWu):
                    jie_ying(ying(**{jian: QUE}))

    def test_status_shi_zi_fu_chu_shu_zi_ye_shou(self):
        """对端可能发 `"200"`（JSON 里没有整数类型的老消息），`int()` 过得去就要。"""
        self.assertEqual(jie_ying(ying(status="200")).status, 200)
        self.assertEqual(jie_ying(ying(status="404")).status, 404)
        self.assertEqual(jie_ying(ying(status=502)).status, 502)

    def test_status_bu_shi_shu_zi(self):
        """`"abc"` / 空串 / null / list 一律拒绝——不能兜底成 502 蒙混过关。"""
        for huai in ("abc", "", None, [], {}, True):
            with self.subTest(huai=huai):
                with self.assertRaises(XieYiCuoWu):
                    jie_ying(ying(status=huai))

    def test_tou_shi_lie_biao(self):
        """就是 `test_gw_route.py::test_ying_da_bu_he_fa_tou_shi_wu_dui` 那条；
        契约层必须把它变成 `XieYiCuoWu`，`_deng_hui` 再翻成 `WuDui` 并摘队列。"""
        with self.assertRaises(XieYiCuoWu):
            jie_ying(ying(headers=["x"]))

    def test_b64_bu_shi_bool(self):
        for huai in ("true", 1, 0, None, []):
            with self.subTest(huai=huai):
                with self.assertRaises(XieYiCuoWu):
                    jie_ying(ying(b64=huai))

    def test_body_bu_shi_zi_fu_chuan(self):
        for huai in (1, [], {}):
            with self.subTest(huai=huai):
                with self.assertRaises(XieYiCuoWu):
                    jie_ying(ying(body=huai))

    def test_body_wei_null_dang_kong_ti(self):
        """`body: null` 按空体收。

        **这是有意的守恒**：改前是 `str(x.get("body") or "")`，null → `""`。
        反代拿到 `body` 就 `len()` + `write()`，这里放行 null 会让那条路炸；
        收紧成「null 也拒绝」则是白改一处对外行为（Ruling 1）。
        """
        self.assertEqual(jie_ying(ying(body=None)).body, "")


class ZhiQiuTest(unittest.TestCase):
    """网关出口：`zhi_qiu` 造出来的东西 `jie_qiu` 必须吃得下（往返守恒）。"""

    def test_wang_fan_shou_heng(self):
        yuan = {"method": "POST", "path": "/permissions/p-1", "query": "token=abc",
                "headers": {"x-bridge-token": "abc"}, "body": '{"decision":"allow"}'}
        wen = zhi_qiu(HAO, yuan)
        self.assertEqual(wen["t"], "request")
        self.assertEqual(wen["id"], HAO)
        q = jie_qiu(wen)      # 不抛就是圆的
        self.assertEqual(q.method, "POST")
        self.assertEqual(q.path, "/permissions/p-1")
        self.assertEqual(q.query, "token=abc")
        self.assertEqual(q.headers, {"x-bridge-token": "abc"})
        self.assertEqual(q.body, '{"decision":"allow"}')

    def test_zhi_fa_liu_jian_shun_xu_bian_yi(self):
        """线上字节不变。改前是 `zhen("request", id=rid, **a2)`，键序
        `t, id, method, path, query, headers, body`——一个字节都不能挪。"""
        wen = zhi_qiu(HAO, {"method": "GET", "path": "/health", "query": "",
                            "headers": {}, "body": None})
        self.assertEqual(list(wen), ["t", "id", "method", "path", "query",
                                     "headers", "body"])

    def test_duo_dai_de_jian_pao_diao(self):
        wen = zhi_qiu(HAO, {"method": "GET", "path": "/health", "query": "",
                            "headers": {}, "body": None, "wei_lai": "x"})
        self.assertNotIn("wei_lai", wen)
        jie_qiu(wen)      # 少了它也要是圆的

    def test_diao_jian_chu_sheng(self):
        """I-3：丢键要出声。静默丢弃与本任务要消灭的失败模式同源（`id` 缺失静默
        变成空串那次），所以恒不触发的路径也要有一条把它钉住。"""
        with self.assertLogs("bridge.xie_yi", level="WARNING") as t:
            zhi_qiu(HAO, {"method": "GET", "path": "/health", "query": "",
                          "headers": {}, "body": None, "wei_lai": "x", "wai": 1})
        self.assertIn("wei_lai", t.output[0])
        self.assertIn("wai", t.output[0])
        # 一个都不多带时不叫，别让「每次都记」把这条 warning 变成噪音
        with self.assertNoLogs("bridge.xie_yi", level="WARNING"):
            zhi_qiu(HAO, {"method": "GET", "path": "/health", "query": "",
                          "headers": {}, "body": None})

    def test_tou_fan_hui_fu_ben(self):
        """M-1：`frozen` 只冻槽位，冻不住 dict 内容。交出去的是副本，
        谁在拿到之后改它都不会动到调用方的消息。"""
        yuan = {"x-bridge-token": "abc"}
        q = jie_qiu(qiu(headers=yuan))
        q.headers.pop("x-bridge-token")
        self.assertEqual(yuan, {"x-bridge-token": "abc"})

    def test_que_jian_jiu_bao(self):
        for jian in ("method", "path", "query", "headers", "body"):
            with self.subTest(jian=jian):
                yuan = {"method": "GET", "path": "/health", "query": "",
                        "headers": {}, "body": None}
                yuan.pop(jian)
                with self.assertRaises(XieYiCuoWu):
                    zhi_qiu(HAO, yuan)

    def test_id_bu_he_ge_ye_bao(self):
        """网关自己分配的 id 也要过同一道卡——两边用同一个 `he_hao`，
        不存在「出口特例」。"""
        with self.assertRaises(XieYiCuoWu):
            zhi_qiu("r-1", {"method": "GET", "path": "/", "query": "",
                            "headers": {}, "body": None})


class HeHaoTest(unittest.TestCase):
    """`he_hao` 是 `frame` / `close` / `response` 共用的那道 id 卡。"""

    def test_he_ge(self):
        for hao in ("r-00000000", "r-1a2b3c4d", "r-ffffffff", "r-abcdef01"):
            with self.subTest(hao=hao):
                self.assertTrue(he_hao(hao))

    def test_bu_he_ge(self):
        for huai in ("", "r-", "r-1", "r-1234567", "r-123456789", "r-1234567g",
                     "r-1234567G", "R-12345678", "r_12345678", "x-12345678",
                     " r-12345678", None, 123, ["r-1a2b3c4d"]):
            with self.subTest(huai=huai):
                self.assertFalse(he_hao(huai))


if __name__ == "__main__":
    unittest.main()
