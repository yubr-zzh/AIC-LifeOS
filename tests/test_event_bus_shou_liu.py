"""10.7 对 LifeOS 事件总线的两条要求：保留期 7 天、总量上限。

pending 一律不淘汰——它们是待处理的业务事件，删了会丢功能。
"""

import asyncio
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lifeos.event.bus import ReliableEventBus

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _lao(a1: int) -> str:
    """造一条 `a1` 天前的 **naive** 时间戳。

    刻意不带时区：那是老代码 `utcnow().isoformat()` 写出来的形态，正是本域要
    保证能读的那种。写成 `datetime.now(timezone.utc)` 就变成造新格式了，
    这两条老用例从此不再守任何东西。
    """
    return (datetime.now(timezone.utc) - timedelta(days=a1)).replace(
        tzinfo=None).isoformat()


class ShouLiuTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.p = Path(self.dir.name) / "events.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_chao_qi_bei_tao_tai(self):
        """超期淘汰。**必须先把那条 mark_done 再老化。**

        直接老化一条 pending 的话，测出来的结果是「pending 被留住了」——
        和这条用例想验的事正好相反，而且它还会以一条永远为真的断言收场。
        """
        b = ReliableEventBus(self.p)
        asyncio.run(b.publish("chat.turn", {"a": 1}))
        asyncio.run(b.mark_done(b.all_events()[0].id))
        # 先把这份列表接住再改。写成 b._write_events(b._read_events()) 是不行的：
        # 那会重新从磁盘读一份没改过的数据写回去，老化等于没做，
        # 而失败信息只会说「第 1 条还在」，看不出是老化没生效。
        jiu = b._read_events()
        for e in jiu:
            e["created_at"] = _lao(8)
        b._write_events(jiu)
        # 再发一条，发之前会淘汰。all_events() 返回的是 Event 对象，走属性不走下标。
        asyncio.run(b.publish("chat.turn", {"a": 2}))
        self.assertEqual([e.payload["a"] for e in b.all_events()], [2])

    def test_pending_chao_qi_ye_bao_liu(self):
        b = ReliableEventBus(self.p)
        asyncio.run(b.publish("chat.turn", {"a": 1}))          # pending
        # 先把这份列表接住再改。写成 b._write_events(b._read_events()) 是不行的：
        # 那会重新从磁盘读一份没改过的数据写回去，老化等于没做，
        # 而失败信息只会说「第 1 条还在」，看不出是老化没生效。
        jiu = b._read_events()
        for e in jiu:
            e["created_at"] = _lao(30)
        b._write_events(jiu)
        asyncio.run(b.publish("chat.turn", {"a": 2}))
        self.assertEqual([e.payload["a"] for e in b.all_events()], [1, 2])

    def test_chao_liang_xian_tao_tai_fei_pending(self):
        """总量超限：done 全淘汰，pending 一条不动；只剩 pending 时告警但不删。

        上限取 **100**：它比一条事件本身还小，于是每一轮都会走到
        「淘汰完所有可淘汰的仍超限」那个分支。取 600 是不行的——一条 300 字符
        payload 的事件约 480 字节，淘汰掉 done 之后总量已经降回上限内，
        告警分支根本不会执行，那条断言就成了摆设。
        """
        with self.assertLogs("lifeos.event", level="WARNING") as ji:
            b = ReliableEventBus(self.p, feng_ding=100)
            asyncio.run(b.publish("chat.turn", {"pad": "x" * 300}))     # pending
            for _ in range(3):
                asyncio.run(b.publish("chat.turn", {"pad": "y" * 300}))
                asyncio.run(b.mark_done(b._read_events()[-1]["id"]))
            asyncio.run(b.publish("chat.turn", {"pad": "z" * 300}))     # pending
        shou = b._read_events()
        self.assertEqual([e["payload"]["pad"] for e in shou],
                         ["x" * 300, "z" * 300],
                         "三条 done 全被淘汰，两条 pending 一条不动")
        self.assertTrue(any("pending" in x for x in ji.output),
                        f"只剩 pending 仍超限时必须告警，实际日志：{ji.output}")

    def test_zheng_chang_liu_cheng_bu_shou_ying_xiang(self):
        """加了淘汰不能把既有的轮询语义改坏。"""
        b = ReliableEventBus(self.p)
        asyncio.run(b.publish("chat.turn", {"a": 1}))
        self.assertEqual(len(asyncio.run(b.poll())), 1)
        eid = asyncio.run(b.poll())[0].id
        asyncio.run(b.mark_done(eid))
        self.assertEqual(asyncio.run(b.poll()), [])
        self.assertEqual(len(b.all_events()), 1)


def _ben(a1: datetime) -> str:
    """naive 形态。历史落盘里的老值都是 `utcnow().isoformat()` 写出来的。"""
    return a1.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def _Z(a1: datetime) -> str:
    """带 Z 的形态。"""
    return a1.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _shi(a1: datetime) -> str:
    """带非零偏移的形态。"""
    return a1.astimezone(timezone(timedelta(hours=2))).isoformat()


class HunHeShiJianTests(unittest.TestCase):
    """同一份 events.json 里可以混着放四种时间戳形态。

    这是本域不变式的正题：`_chao_qi()` 原先用 `datetime.utcnow()` 减一个
    `fromisoformat` 的结果，遇到带时区的旧值时抛的是 `TypeError: can't
    subtract offset-naive and offset-aware datetimes`——**不是** `ValueError`，
    所以原来那个 `except ValueError` 根本接不住，整个事件总线在启动那一刻
    就炸了。这组用例把四种形态放在同一个文件里，逼那两条路径真的跑一遍。
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.p = Path(self.dir.name) / "events.json"
        self.jin = datetime.now(timezone.utc)
        self.bao = self.jin - timedelta(days=1)      # 保留期内
        self.chao = self.jin - timedelta(days=8)      # 超期

    def tearDown(self):
        self.dir.cleanup()

    def _hun_he(self) -> list:
        """三种时间形态 × 保留/超期，各一条。全是 done，超期那条才该被删。"""
        jiu = []
        for ming, xie in (("ben", _ben), ("Z", _Z), ("shi", _shi)):
            for biao, yi in (("chao", self.chao), ("bao", self.bao)):
                e = {"id": f"{ming}-{biao}", "type": "chat.turn",
                     "payload": {"n": f"{ming}-{biao}"}, "status": "done",
                     "attempts": 1, "created_at": xie(yi), "updated_at": "",
                     "error": None}
                jiu.append(e)
        self.p.write_text(json.dumps(jiu, ensure_ascii=False), encoding="utf-8")
        return jiu

    def test_qi_dong_bu_bao_tao_tai_bu_bao(self):
        """构造器启动的淘汰与 publish 触发的淘汰，两条路径都不抛。"""
        self._hun_he()
        b = ReliableEventBus(self.p)          # 启动时那一趟淘汰
        self.assertEqual(sorted(e.id for e in b.all_events()),
                         ["Z-bao", "ben-bao", "shi-bao"])
        asyncio.run(b.publish("chat.turn", {"a": 2}))   # 再触发一趟
        lai = [e.id for e in b.all_events()]
        self.assertEqual(len(lai), 4, f"三条保留的加新发的一条，实际 {lai}")
        for a1 in ("ben-bao", "Z-bao", "shi-bao"):
            self.assertIn(a1, lai)

    def test_feifa_chuang_jian_an_bao_liu(self):
        """created_at 解析不出来的事件按未过期处理，且不抛。"""
        for a1 in ("", "不是时间", None, 12345):
            with self.subTest(zhi=a1):
                self.p.unlink(missing_ok=True)
                e = {"id": "feifa", "type": "chat.turn", "payload": {},
                     "status": "done", "attempts": 1, "created_at": a1,
                     "updated_at": "", "error": None}
                self.p.write_text(json.dumps([e], ensure_ascii=False),
                                  encoding="utf-8")
                b = ReliableEventBus(self.p)
                asyncio.run(b.publish("chat.turn", {"a": 2}))
                ids = [x.id for x in b.all_events()]
                self.assertEqual(len(ids), 2, "解析不了的那条必须按未过期处理")
                self.assertIn("feifa", ids)

    def test_tao_tai_bu_gai_xie_chuang_jian(self):
        """淘汰不许顺手把旧落盘的时间值改写成新格式。

        数据迁移是后续单独立项的事。这一轮只保证读得动；谁在淘汰里改写
        `created_at`，就是在没有备份的情况下批量重写用户数据。
        """
        yuan = _ben(self.bao)
        e = {"id": "bao", "type": "chat.turn", "payload": {}, "status": "done",
             "attempts": 1, "created_at": yuan, "updated_at": "", "error": None}
        g = dict(e, id="chao", created_at=_ben(self.chao))
        self.p.write_text(json.dumps([e, g], ensure_ascii=False),
                          encoding="utf-8")
        b = ReliableEventBus(self.p)
        asyncio.run(b.publish("chat.turn", {"a": 2}))
        shou = [x for x in b._read_events() if x["id"] == "bao"]
        self.assertEqual(len(shou), 1)
        self.assertEqual(shou[0]["created_at"], yuan,
                         "旧值必须逐字保留——迁移是后续单独立项的事")


if __name__ == "__main__":
    unittest.main()
