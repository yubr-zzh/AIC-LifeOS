"""Claude Code 适配器的消息翻译与回调分流（方案 12.4 任务 3.2、3.3、3.4）。

翻译测试用的是**实测记录下来的真实消息结构**（`docs/bridge-spike-report.md` 附录），
不是照着类型注解编的假对象。差别很大：实测的内容块上根本没有 `type` 字段，
照注解写出来的测试会通过，真机上却一条都翻译不出来。
"""

import asyncio
import json
import os
import sys
import unittest
from unittest import mock

from claude_agent_sdk import (
    AssistantMessage,
    ConversationResetMessage,
    PermissionResultAllow,
    PermissionResultDeny,
    RateLimitEvent,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    ToolPermissionContext,
    UserMessage,
)
from claude_agent_sdk.types import (RateLimitInfo, TextBlock, ThinkingBlock,
                                     ToolResultBlock, ToolUseBlock)

from lifeos.bridge.adapters.claude_code import ClaudeCodeAdapter, shi_ren

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _quan(a1: str) -> ToolPermissionContext:
    return ToolPermissionContext(
        signal=None, suggestions=None, tool_use_id=a1, agent_id=None,
        blocked_path=None, decision_reason="tool not in allow list",
        title="Claude 想执行一条命令", display_name="Run shell command",
        description="",
    )


class FanYiTests(unittest.TestCase):
    """3.2：SDK 消息 → 统一模型。"""

    def she_ben(self, a1=None, a2=None):
        self.dai = []
        self.ad = ClaudeCodeAdapter(lambda k, p: self.dai.append((k, p)), a2)
        return self.ad

    def test_kuai_bu_fen_pai(self):
        """内容块上没有 type 字段，只能按字段存在性分派。"""
        self.assertEqual(shi_ren({"text": "答案"})["kind"], "text")
        self.assertEqual(shi_ren({"thinking": "在想", "signature": "s"})["kind"], "thinking")
        kuai = shi_ren({"id": "toolu_1", "name": "Bash", "input": {"command": "ls"}})
        self.assertEqual(kuai["kind"], "tool_use")
        self.assertEqual(kuai["toolName"], "Bash")
        self.assertEqual(shi_ren({"nothing": 1}), {})

    def test_xin_xi_tiao_chu_shi_chu_zi_rong_qing(self):
        ad = self.she_ben()
        ad._fan(SystemMessage(subtype="init", data={"session_id": "sess-abc", "cwd": "C:/x"}))
        self.assertEqual(ad.kehu_hui, "sess-abc")
        self.assertEqual(self.dai[-1], ("session", {"claudeSessionId": "sess-abc"}))

    def test_wen_zi_he_si_wei_kuai(self):
        ad = self.she_ben()
        ad._fan(AssistantMessage(content=[{"text": "这是答案"}], model="m",
                                parent_tool_use_id=None, usage={}, message_id="msg_1",
                                stop_reason=None, session_id="s", uuid="u"))
        # messageId 必须与 chunk 帧的同源，否则前端无法把流式增量归并到这条消息上，
        # 只能把两条都显示出来。
        self.assertEqual(
            self.dai[-1],
            ("text", {"kind": "text", "text": "这是答案", "messageId": "msg_1"}),
        )

    def test_gong_ju_hai_ling_bu_ming_de_yao_cong_zi_ji_li_bao_chu_lai(self):
        """UserMessage 的工具结果块里没有工具名，名字得从 tool_use 块记住。"""
        ad = self.she_ben()
        ad._fan(AssistantMessage(content=[{"id": "t1", "name": "Bash", "input": {"command": "ls"}}],
                                model="m", parent_tool_use_id=None, usage={}, message_id="m2",
                                stop_reason=None, session_id="s", uuid="u"))
        ad._fan(UserMessage(content=[{"tool_use_id": "t1", "content": "a.txt", "is_error": False}],
                            uuid="u2", parent_tool_use_id=None, tool_use_result=None,
                            origin=None))
        lei = dict(self.dai)["tool_result"]
        self.assertEqual(lei["toolName"], "Bash")
        self.assertEqual(lei["text"], "a.txt")
        self.assertFalse(lei["isError"])

    def test_jie_guo_xiao_xi(self):
        ad = self.she_ben()
        ad._fan(ResultMessage(subtype="success", duration_ms=1234, duration_api_ms=1,
                              is_error=False, num_turns=2, session_id="s", stop_reason="end_turn",
                              total_cost_usd=0.02, usage={}, result="干完了", structured_output=None,
                              model_usage=None, permission_denials=None, deferred_tool_use=None,
                              errors=None, api_error_status=None, uuid="u", terminal_reason=None,
                              origin=None))
        self.assertEqual(self.dai[-1][0], "result")
        self.assertEqual(self.dai[-1][1]["resultText"], "干完了")
        self.assertEqual(self.dai[-1][1]["totalCostUsd"], 0.02)

    def test_jie_guo_shibai_yao_fa_yi_pian_error(self):
        ad = self.she_ben()
        ad._fan(ResultMessage(subtype="error_during_execution", duration_ms=10, duration_api_ms=0,
                              is_error=True, num_turns=1, session_id="s", stop_reason=None,
                              total_cost_usd=0.0, usage={}, result=None, structured_output=None,
                              model_usage=None, permission_denials=None, deferred_tool_use=None,
                              errors=None, api_error_status=None, uuid="u", terminal_reason=None,
                              origin=None))
        lei = [k for k, _ in self.dai]
        self.assertIn("result", lei)
        self.assertIn("error", lei)
        # 用户主动中断是终态，不可重试
        self.assertEqual(dict(self.dai)["error"]["recoverable"], False)

    def test_liu_shi_pin_mei_you_zhen_xi(self):
        ad = self.she_ben()
        ad._liu(StreamEvent(uuid="u1", session_id="s", event={"type": "message_start",
                                                              "message": {"id": "msg_42"}},
                            parent_tool_use_id=None))
        ad._liu(StreamEvent(uuid="u2", session_id="s",
                            event={"type": "content_block_delta",
                                   "delta": {"type": "text_delta", "text": "半句"}},
                            parent_tool_use_id=None))
        # messageId 必须等于最终 AssistantMessage 的 message_id，前端才能整段替换
        self.assertEqual(self.dai[-1], ("chunk", {"messageId": "msg_42", "delta": "半句",
                                                  "messageKind": "text"}))

    def test_liu_shi_gong_ju_sui_ye(self):
        ad = self.she_ben()
        ad.xiang_id = "msg_9"
        ad._liu(StreamEvent(uuid="u", session_id="s",
                            event={"type": "content_block_delta",
                                   "delta": {"type": "input_json_delta", "partial_json": '{"a":'}},
                            parent_tool_use_id=None))
        self.assertEqual(self.dai[-1][1]["messageKind"], "tool_use")

    def test_xian_lv_liu_shi_quan_bu_yao_sheng_shi(self):
        ad = self.she_ben()
        ad._fan(RateLimitEvent(rate_limit_info=RateLimitInfo(status="allowed_warning",
                                                             resets_at=9999999999,
                                                             rate_limit_type="five_hour"),
                               uuid="u", session_id="s"))
        self.assertEqual(self.dai[-1][0], "rate_limit")
        ad._fan(ConversationResetMessage(new_conversation_id="sess-new", uuid="u", session_id="s"))
        self.assertEqual(self.dai[-1][0], "session")
        self.assertEqual(ad.kehu_hui, "sess-new")

    def test_zhen_ji_qiao_de_nei_rong_kuai(self):
        """真机上给的是 dataclass 实例，不是 dict。

        这一条是从真机验收里补的：按 dict 写的翻译器在单测里全绿，
        真机上一条 tool_use / tool_result 都翻译不出来——spike 报告里记的是
        渲染后的 dict 形态，不是 SDK 的实际类型。
        """
        ad = self.she_ben()
        ad._fan(AssistantMessage(
            content=[ToolUseBlock(id="t9", name="Bash", input={"command": "ls"}),
                     ThinkingBlock(thinking="先看看目录", signature="sig"),
                     TextBlock(text="好的")],
            model="m", parent_tool_use_id=None, usage={}, message_id="m3",
            stop_reason=None, session_id="s", uuid="u"))
        lei = dict(self.dai)
        self.assertEqual(lei["tool_use"]["toolName"], "Bash")
        self.assertEqual(lei["thinking"]["text"], "先看看目录")
        self.assertEqual(lei["text"]["text"], "好的")

        ad._fan(UserMessage(content=[ToolResultBlock(tool_use_id="t9", content="a.txt",
                                                     is_error=False)],
                            uuid="u3", parent_tool_use_id=None,
                            tool_use_result=None, origin=None))
        self.assertEqual(self.dai[-1][0], "tool_result")
        self.assertEqual(self.dai[-1][1]["toolName"], "Bash")
        self.assertEqual(self.dai[-1][1]["text"], "a.txt")

    def test_shu_ju_de_kuai_mo_yao_sha_si(self):
        """不认识的块跳过即可，不该把整个回合带崩。"""
        ad = self.she_ben()
        ad._fan(AssistantMessage(content=[object()], model="m", parent_tool_use_id=None,
                                usage={}, message_id="m", stop_reason=None,
                                session_id="s", uuid="u"))
        self.assertEqual(self.dai, [])

    def test_field_chu_yi_chang_biao_mian_cheng_error(self):
        """SDK 字段漂移（这里是 total_cost_usd 变成字符串）不能打断回合。"""
        ad = self.she_ben()
        ad._fan(ResultMessage(subtype="success", duration_ms=1, duration_api_ms=0,
                              is_error=False, num_turns=1, session_id="s", stop_reason=None,
                              total_cost_usd="not-a-number", usage={}, result="ok",
                              structured_output=None, model_usage=None, permission_denials=None,
                              deferred_tool_use=None, errors=None, api_error_status=None,
                              uuid="u", terminal_reason=None, origin=None))
        self.assertTrue(any(k == "error" and p["code"] == "translate_failed"
                            for k, p in self.dai))


class HuiLiuTests(unittest.TestCase):
    """3.3 / 3.4：权限与提问怎么分流。"""

    def test_que_wei_id_ji_jue(self):
        dai = []
        ad = ClaudeCodeAdapter(lambda k, p: dai.append((k, p)), None)
        r = asyncio.run(ad._deng("Bash", {"command": "ls"}, _quan("")))
        self.assertIsInstance(r, PermissionResultDeny)
        # 关键：没有 tool_use_id 的请求绝不能进 pending 集合
        self.assertTrue(any(p["code"] == "missing_tool_use_id" for _, p in dai))

    def test_ti_wen_fen_liu(self):
        got = []

        async def cheng(kind, payload):
            got.append((kind, payload))
            return PermissionResultDeny(message="用户选了 B")

        ad = ClaudeCodeAdapter(None, cheng)
        r = asyncio.run(ad._deng("AskUserQuestion",
                                 {"questions": [{"question": "接下来做什么？", "options": []}]},
                                 _quan("toolq1")))
        self.assertEqual(got[0][0], "question")
        self.assertEqual(got[0][1]["toolUseId"], "toolq1")
        # title 在这个场景恒为 null，标题必须自己从 input 里取
        self.assertEqual(got[0][1]["title"], "接下来做什么？")
        self.assertIsInstance(r, PermissionResultDeny)

    def test_gong_ju_fen_liu(self):
        got = []

        async def cheng(kind, payload):
            got.append((kind, payload))
            return PermissionResultAllow()

        ad = ClaudeCodeAdapter(None, cheng)
        ctx = _quan("toolb1")
        r = asyncio.run(ad._deng("Bash", {"command": "node -e 'x'"}, ctx))
        self.assertEqual(got[0][0], "permission")
        self.assertEqual(got[0][1]["toolName"], "Bash")
        self.assertIsInstance(r, PermissionResultAllow)

    def test_ju_yong_qu_diao_bao_chu_lai_bu_li_zhong_fan_hang(self):
        """用户中断时协程被取消，必须原样抛出而不是吞掉转成拒绝。"""
        async def cheng(kind, payload):
            raise asyncio.CancelledError()

        ad = ClaudeCodeAdapter(None, cheng)
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(ad._deng("Bash", {"command": "ls"}, _quan("t1")))

    def test_bao_yi_que_ding_shi_bai_mo_you_tong_dao_yi_lü_jue(self):
        """没有挂起通道时安全侧默认：拒绝。"""
        ad = ClaudeCodeAdapter(None, None)
        r = asyncio.run(ad._deng("Bash", {"command": "ls"}, _quan("t1")))
        self.assertIsInstance(r, PermissionResultDeny)


class KaiShiGeLiTests(unittest.TestCase):
    """改动三（2026-10-10）：`kaishi()` 的 `setting_sources` 随隔离开关分流。

    两个形态都要钉死：关（默认）→ `["user", "project"]`，harness 读用户的
    CLAUDE.md / skills / settings.json；开（`LIFEOS_GELI` 关名单外的值）→
    `[]`，退回改动三之前的干净委派。断言打在**传给 `ClaudeSDKClient` 的
    options 实参**上——自己 new 一个 options 再断言，生产代码怎么写都绿。
    """

    def _zhen(self, geli_zhi: str):
        import lifeos.bridge.adapters.claude_code as cc
        zhuo = []

        class JiaKeHu:
            def __init__(self, xz):
                zhuo.append(xz)

            async def connect(self):
                pass

        ad = ClaudeCodeAdapter(None, None)
        with mock.patch.object(cc, "ClaudeSDKClient", JiaKeHu), \
                mock.patch.dict(os.environ, {"LIFEOS_GELI": geli_zhi}):
            asyncio.run(ad.kaishi({"cwd": "C:/x"}))
        return zhuo[0]

    def test_guan_ge_li_jia_zai_user_project(self):
        """隔离关（默认形态）：加载 user + project 两级本机配置。"""
        xz = self._zhen("")
        self.assertEqual(xz.setting_sources, ["user", "project"])

    def test_kai_ge_li_hui_dao_kong_lie_biao(self):
        """隔离开：`LIFEOS_GELI=1` 退回空列表，不加载任何本机配置。"""
        xz = self._zhen("1")
        self.assertEqual(xz.setting_sources, [])


class MoShiTests(unittest.TestCase):
    """3.5：模式映射与白名单。"""

    def test_que_ren_bei_huan_cheng_default(self):
        ad = ClaudeCodeAdapter()
        ad.kehu = None
        asyncio.run(ad.gai_moshi("manual"))
        self.assertEqual(ad.moshi, "manual")

    def test_fei_fa_mo_shi_zhi_jue(self):
        ad = ClaudeCodeAdapter()
        with self.assertRaises(ValueError):
            asyncio.run(ad.gai_moshi("bypassPermissions"))


class TanJianTests(unittest.TestCase):
    def test_tan_jian_bu_hui_peng_zhe(self):
        r = asyncio.run(ClaudeCodeAdapter().tanjian())
        self.assertIn("available", r)
        self.assertIsInstance(r["available"], bool)
        if r["available"]:
            self.assertRegex(r["version"], r"^\d+\.\d+\.\d+$")


class ShouYiTests(unittest.TestCase):
    """3.8 出站侧：脱敏必须真的挡住密钥。"""

    def test_yao_yao_mo_dong_yao_zhi(self):
        from lifeos.bridge.localbus import tui_mian
        wen = tui_mian('key=sk-abcdefghij0123456789 and token: hunter2secret')
        self.assertNotIn("abcdefghij0123456789", wen)
        self.assertIn("sk-***", wen)

    def test_chang_du_yue_xian_zhan_du(self):
        from lifeos.bridge.localbus import tui_mian
        self.assertIn("已截断", tui_mian("x" * 5000))

    def test_bian_hu_shi_rong_qi_ben_qu(self):
        from lifeos.bridge.localbus import tui_mian
        wen = tui_mian({"k": "v"}, 100)
        self.assertEqual(json.loads(wen), {"k": "v"})


if __name__ == "__main__":
    unittest.main()
