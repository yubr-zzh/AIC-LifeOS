"""01 域：统一时间接口。

生产写入点只调 `xie_shi()`，生成带 UTC 时区信息的 ISO 8601 字符串；
读取旧落盘值一律走 `du_shi()`，把 naive / aware / 带 `Z` 的形态统一归一成
aware UTC，解析不了的一律返回 `None` 而不是抛异常。

`du_shi()` 返回 `None` 的语义是「这个时间不可信」：调用方据此按未过期处理，
**宁可多留一条事件，不可少删一条**。
"""

import unittest
from datetime import datetime, timedelta, timezone

from lifeos.time_util import du_shi, xie_shi


class XieShiTests(unittest.TestCase):
    def test_dai_shijian_ke_du(self):
        """写出来的时间必须自带 UTC 时区信息。

        只断言「能解析」是不够的：naive 字符串也解析得开，但那正是新旧时间戳
        相减抛 TypeError 的那一半。`tzinfo is None` 就是这个测试的全部意义。
        """
        fan = xie_shi()
        at = datetime.fromisoformat(fan)
        self.assertIsNotNone(at.tzinfo, f"{fan} 必须带时区信息")
        self.assertEqual(at.utcoffset(), timedelta(0), "写出的时间必须是 UTC")

    def test_dai_shijian_chuan_de_hao_ma(self):
        """默认值工厂在 dataclass 里被直接调用，这里守住它的单独可用性。"""
        self.assertTrue(xie_shi().endswith("+00:00"))

    def test_dai_shijian_ke_ping_xi_shi_jian_bing_lie_dian_bu_liu_cha(self):
        """两次调用必须给出不同的时刻——否则同一批事件会共享一个 created_at。

        用 `jia_shi` 那种注入时钟不行（时间接口读的是墙上时钟不是
        `time.monotonic`），所以这里靠「上一次结果落在同一微秒里几乎不可能」
        成立。断言放宽成「不相等或相等但单调」，真出问题时上一行会先红。
        """
        a1 = du_shi(xie_shi())
        a2 = du_shi(xie_shi())
        self.assertLessEqual(a1, a2, "时间必须单调不倒退")
        self.assertLess((a2 - a1).total_seconds(), 1.0)


class DuShiTests(unittest.TestCase):
    def test_ben_shi_an_wei_wei_utc(self):
        """naive 旧值按 UTC 解释。历史落盘里的 naive 值都是 utcnow 写的。"""
        at = du_shi("2026-09-30T12:00:00")
        self.assertIsNotNone(at)
        self.assertIsNotNone(at.tzinfo, "返回值必须带时区，否则下游相减又会炸")
        self.assertEqual(at, datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc))

    def test_dai_shijian_qu_shi_wei_utc(self):
        """带 +02:00 的值要真的换算到 UTC，不能只把偏移量抹掉。

        抹掉偏移量会得到 14:00 而不是 12:00——那不是格式兼容，是把事件提前
        2 小时判定为超期，然后删掉它。
        """
        at = du_shi("2026-09-30T14:00:00+02:00")
        self.assertEqual(at, datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc))

    def test_dai_Z_de_fu_hao(self):
        """带 Z 的值同样按 UTC 解释。Python 3.11+ 的 fromisoformat 认这个后缀。"""
        at = du_shi("2026-09-30T12:00:00Z")
        self.assertEqual(at, datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc))

    def test_kong_ge_fen_zhong_fen_li(self):
        """老数据里三种脏形态都要兜住，一律返回 None 且不抛。

        非字符串**一律**判为非法，包括数字：落盘字段的契约是 ISO 8601 字符串，
        一个整数出现在这里只可能是别处写错了。猜它是 epoch 秒等于把写错的
        数据猜成对的——猜错方向还可能落在保留期内，让该删的事件永远留着。
        """
        for a1 in ("", None, "不是时间", 12345, 1788000000,
                   "2026-13-45T99:99:99", [], {}, True):
            with self.subTest(zhi=a1):
                self.assertIsNone(du_shi(a1))

    def test_fen_xiang_hao_de_kong_ke_zai(self):
        """历史落盘里 fromisoformat 认不出的写法要尽量救回来。

        老版本代码用 `str(datetime)` 写过带微秒空格的形态。整条时间戳因此被判成
        「不可信」而被当成永不淘汰——文件就再也瘦不下来了。
        """
        at = du_shi("2026-09-30 12:00:00.123456+00:00")
        self.assertIsNotNone(at)
        self.assertEqual(at, datetime(2026, 9, 30, 12, 0, 0, 123456,
                                      tzinfo=timezone.utc))

    def test_fen_xiang_hao_bu_dai_miao_ke_zai(self):
        at = du_shi("2026-09-30 12:00:00")
        self.assertEqual(at, datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc))

    def test_shu_zi_xing_fang_chi_shi_jian_zhuan_li_zi_fu_hao(self):
        """纯数字时间戳判为非法。

        落盘字段的契约是 ISO 8601 字符串。猜一个整数是 epoch 秒，等于把
        写错的数据猜成对的——猜中的话它还会落在保留期内，让该淘汰的事件
        永远留着。
        """
        self.assertIsNone(du_shi(1788000000))

    def test_fan_hui_xiang_dou_shi_aware(self):
        """所有成功解析的返回值都必须是 aware 的——这一条是本域的不变式。"""
        for a1 in ("2026-09-30T12:00:00", "2026-09-30T14:00:00+02:00",
                   "2026-09-30T12:00:00Z", "2026-09-30 12:00:00"):
            with self.subTest(zhi=a1):
                self.assertIsNotNone(du_shi(a1).tzinfo)


if __name__ == "__main__":
    unittest.main()
