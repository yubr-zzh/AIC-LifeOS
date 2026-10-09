import asyncio
import base64
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from lifeos.agent.runtime import LifeOSAgent
from lifeos.api import bridge_admin
from lifeos.api.dangqian import dang_qian_yong_hu
from lifeos.api.devices import SheBiao
from lifeos.api.tunnel_gw import TunnelGw, WuDui, he_cheng_zhen, xie_zhen
from lifeos.llm.client import LLMClient, LLMRequestError
from lifeos.llm.profiles import ModelManager, ModelProfileStore
from lifeos.storage.sqlite import StructuredStore

# 7.7.2 展示旁路：这些 kind **只**写事件总线，绝不进 AgentContextStore。
# detail 的 key 全部枚举，禁止携带任何 Agent 文本（10.7）。
ZHUAN_LIU = {
    "bridge.connected": frozenset({"instanceId", "port", "cliVersion", "sdkVersion"}),
    "bridge.disconnected": frozenset({"reason", "uptimeSec"}),
    "session.created": frozenset({"sessionId", "agentId", "cwd", "permissionMode"}),
    "session.closed": frozenset({"sessionId", "reason", "turnCount", "batchDone"}),
    "permission.resolved": frozenset({"requestId", "decision", "autoReason", "replayed"}),
    "agent.crashed": frozenset({"sessionId", "exitCode", "signal"}),
}

# 7.7.1 决策回路：这些 kind 进 LLM 上下文。
JUE_LU = ("agent.result", "agent.failed", "agent.ended", "plan.updated")

# 无来源头（= 非浏览器）请求共用的限流主体。`*` 进不了真实 id
# （uid 只允许 `[A-Za-z0-9_.-]`，deviceId 形如 `dev-<hex>`），所以两套窗口
# 不可能撞。匿名请求**另有一套窗口、限额与浏览器相同**：否则 20 个无凭据 GET
# 就能把 `d:` 打满，接下来 60 秒内合法用户的 GET 与 POST 全部 429。
NI_MING = "*anon*"

# 主服务代理层每条可信来源的 SSE 上限（阶段六收口 06 域）。
# **与 Bridge 那层的 8 条是两道独立的闸，不是一道。** Bridge 数的是「到达
# Bridge 的连接」，主服务这边每条代理流自己占一个 ThreadingHTTPServer 线程：
# 开满 Bridge 的额度之前，主服务已经先被线程数拖住了。而 Bridge 那层按
# `x-lifeos-source` 计数——那个头是浏览器自报的数据，伪造一个就换一个桶。
# 所以主服务这一层必须按**可信来源**独立计数。
ZUI_DAI_LIU = 8

# 429 的 Retry-After。SSE 被限后客户端（EventSource）会自己重连，
# 给一个「多久之后可以再试」比让它立刻重试打满窗口好。
DAI_LIU_CHONG_LIAN = 5

# `Origin` 白名单（10.2 的四个同源端口）。**`_fangxing()` 与 `_pan_yuan()` 共用**
# ——同一个服务器上两套分叉的同源判据、其中一套更弱，正是日后变成漏洞的形状。
YUAN_BAI = ("http://127.0.0.1:5173", "http://localhost:5173",
            "http://127.0.0.1:4173", "http://localhost:4173")

# 可信的 `Sec-Fetch-Site` 取值。`none` 是用户直接敲地址/书签，同样是浏览器；
# `cross-site` 是唯一不可信的——它意味着发起请求的页面在别的源上（CSRF 的形状）。
KE_XIN = ("same-origin", "same-site", "none")


def guo_lu2(a1: str, a2: dict) -> tuple[dict, int]:
    """只保留该 kind 白名单内的 key。返回 (过滤后的, 丢弃条数)。

    不信任 Bridge：它写错时这一层要能挡住。纵深防御，不是多余的重复校验。
    """
    xu = ZHUAN_LIU.get(a1, frozenset())
    shou = {k: v for k, v in a2.items() if k in xu}
    return shou, len(a2) - len(shou)


def create_agent():
    # 10.1：环境变量是服务端硬关，用于线上应急。默认开着。
    model_store = ModelProfileStore(".lifeos/models.json")
    agent = LifeOSAgent(
        ModelManager(model_store, fallback=LLMClient()),
        delegation_enabled=os.environ.get("LIFEOS_DELEGATION", "on") != "off",
    )
    agent.model_store = model_store
    return agent


class LiAnHTTPServer(ThreadingHTTPServer):
    """线程化 + 允许复用端口（10.4 的第 1 条）。

    单线程 HTTPServer 上一条 SSE 长连接会把整个 LifeOS（含 `/chat`）冻住。
    `daemon_threads` 让主进程退出时不被长连接吊住。
    """
    daemon_threads = True
    allow_reuse_address = True


class LifeOSRequestHandler(BaseHTTPRequestHandler):
    agent = create_agent()
    structured_store = StructuredStore()

    # **不要在类上写 protocol_version。** 全局 HTTP/1.1 会打断
    # test_pipei::DuanDianTest::test_pai_code_dai_body_bu_duan_lian_jie 守的 RST 回归：
    # 那条测试守的是「请求体没读干净就关连接 ⇒ Windows 发 RST ⇒ 客户端拿到
    # 10053/10054」，这本质是 HTTP/1.0 的行为（响应完就断）。一旦全局开 keep-alive，
    # 服务端不再立刻关连接，那个 bug 不复现，断言从此什么都不证明。
    # 逐连接的版本切换见 `parse_request`——**只对 `/agent-api/*` 生效**。


    def handle(self) -> None:
        """**对端在等响应时断开不是缺陷，是收尾。**

        Windows 上它表现为 `ConnectionAbortedError: [WinError 10053]`，从
        `handle_one_request` 的 socket 读里穿出来。`socketserver` 把任何从
        `handle()` 穿出的异常当「未处理」打整段 traceback 到 stderr——一条正常
        的关闭在测试输出里长得像崩溃，而真失败就埋在这一片噪声底下。

        捕的是「连接没了」这一类，不是 `except Exception`：handler 内部真正的
        缺陷仍然要照原样冒出来。
        """
        try:
            super().handle()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def parse_request(self):
        # **必须早于 super()**：`BaseHTTPRequestHandler` 写响应行用的就是
        # `self.protocol_version`，放晚了响应行已经写成 HTTP/1.0。设为**实例属性**，
        # 只对本连接生效，类本身不动。
        #
        # 为什么 keep-alive 只需要给 `/agent-api/*`：不是「SSE 需要 keep-alive」
        # （HTTP/1.0 下 SSE 一样逐帧收得到），而是**同一条连接能挂几条流**——
        # 浏览器对同源只开 6 条 SSE，spec 9.4 的常驻合成流会占死名额。
        if self.raw_requestline:
            # 请求行此时还没解析（`self.path` 是 `super().parse_request()` 内部填的），
            # 所以按空白切第 2 段。`[1:2]` 切片而不是 `[1]`：畸形请求行（`b"\r\n"`）
            # 切出来只有一个元素，直接下标会 IndexError 打断 parse_request。
            duan = self.raw_requestline.split(b" ")[1:2]
            # **带尾随 `/` 的前缀匹配。** 只比 `/agent-api` 会把
            # `/agent-apping` 这类走 404 的老端点也提上版本。
            if duan and (duan[0].startswith(b"/agent-api/")
                         or duan[0].rstrip(b"\r\n") == b"/agent-api"):
                self.protocol_version = "HTTP/1.1"
        return super().parse_request()

    def do_GET(self):
        # 与 do_POST / do_PUT 同一条纪律：请求体先读干净，再进任何分支。
        # 少了这一行，带体的 GET 走 `_ti_zi()` 的 rfile 回退分支，而无网关
        # / 无设备 / 限流这几条拒绝路径都在 `_ti_zi()` 之前就 return 了——
        # body 还在收缓冲里就关连接，Windows 上发的是 RST，同一 keep-alive
        # 连接上的下一条请求把 body 当请求行解析（实测 501
        # `'{"x":1}GET /agent-api/agents'`）。读在入口之后，所有取用点
        # 都只消费缓存，不会重读 rfile。
        self._du_wan()
        parsed = urlparse(self.path)
        if self._shi_fou_dai_li(parsed):
            self._dai_li(parsed, "GET")
            return
        if parsed.path == "/models":
            self._send_json(self.agent.model_store.catalog())
            return
        if parsed.path == "/events":
            self._send_json({"events": [vars(event) for event in self.agent.event_bus.all_events()]})
            return
        if parsed.path == "/memory":
            self._send_json(self.agent.memory._read())
            return
        if parsed.path == "/memory/profile":
            self._send_json(self.agent.memory.profile_view())
            return
        if parsed.path == "/agent/evidence":
            self._send_json({"items": self.agent.agent_evidence.list(
                owner_id=dang_qian_yong_hu(),
                session_id=parse_qs(parsed.query).get("session_id", [None])[0],
            )})
            return
        if parsed.path == "/skills":
            self._send_json(self.agent.skills._read())
            return
        if parsed.path == "/permissions":
            self._send_json({"requests": []})
            return
        if parsed.path.startswith("/traces/"):
            trace = self.agent.trace.get(unquote(parsed.path.rsplit("/", 1)[-1]))
            if trace is None:
                self.send_error(404, "trace not found")
            else:
                self._send_json({"trace_id": unquote(parsed.path.rsplit("/", 1)[-1]), **trace})
            return
        if parsed.path == "/entries":
            self._handle_list_entries(parse_qs(parsed.query))
            return
        if parsed.path.startswith("/entries/"):
            self._handle_get_entry(unquote(parsed.path.rsplit("/", 1)[-1]))
            return
        if parsed.path == "/memory/markdown":
            self._handle_export_markdown()
            return
        if parsed.path == "/api/bridge/info":
            self._send_json({**bridge_admin.xinxi(), "csrf": bridge_admin.qu_ma()})
            return
        if parsed.path == "/api/bridge/devices":
            self._handle_bridge_devices()
            return
        if parsed.path == "/api/settings/delegation":
            self._send_json({"enabled": self.agent.chat.delegation_enabled})
            return
        self.send_error(404, "not found")

    def do_POST(self):
        # 请求体先读干净，再进任何分支与任何闸门。Windows 上带着未读的 body
        # 字节关连接发的是 RST 不是 FIN，客户端拿到 10054 而不是那个响应。
        # 纪律照参考实现（server-route-state.js:214-231）：任何路径都在请求体
        # 被读完之后才回响应，所以读在入口、分支各自再读就多余了。
        self._du_wan()
        parsed = urlparse(self.path)
        if self._shi_fou_dai_li(parsed):
            self._dai_li(parsed, "POST")
            return
        parts = parsed.path.strip("/").split("/")
        if parsed.path == "/models/discover":
            if self._fangxing():
                self._handle_model_discovery()
            return
        if parsed.path == "/models/profiles":
            if self._fangxing():
                self._handle_create_model_profile()
            return
        if parsed.path == "/models/test":
            if self._fangxing():
                self._handle_model_test_payload()
            return
        if len(parts) == 4 and parts[:2] == ["models", "profiles"] and parts[3] == "activate":
            if self._fangxing():
                self._handle_model_activate(unquote(parts[2]))
            return
        if len(parts) == 4 and parts[:2] == ["models", "profiles"] and parts[3] == "test":
            if self._fangxing():
                self._handle_model_test(unquote(parts[2]))
            return
        if len(parts) == 4 and parts[:2] == ["memory", "candidates"] and parts[3] in {"commit", "reject"}:
            self._handle_memory_candidate(unquote(parts[2]), parts[3])
            return
        if parsed.path == "/memory/providers/tencentdb/sync-pending":
            self._handle_tencentdb_sync_pending()
            return
        if len(parts) == 3 and parts[0] == "memory" and parts[2] in {"correct", "retract"}:
            self._handle_memory_mutation(unquote(parts[1]), parts[2])
            return
        if len(parts) == 3 and parts[0] == "entries" and parts[2] == "memory-candidates":
            self._handle_structured_entry_memory_candidate(unquote(parts[1]))
            return
        if len(parts) == 3 and parts[0] == "traces" and parts[2] == "memory-candidates":
            self._handle_trace_memory_candidate(unquote(parts[1]))
            return
        if len(parts) == 4 and parts[:2] == ["agent", "evidence"] and parts[3] == "memory-candidates":
            self._handle_agent_memory_candidate(unquote(parts[2]))
            return
        if len(parts) == 4 and parts[:2] == ["skills", "pending"] and parts[3] in {"approve", "reject"}:
            self._handle_skill_candidate(unquote(parts[2]), parts[3])
            return
        if self.path == "/chat":
            self._handle_chat()
            return
        if self.path == "/api/agent-events":
            self._handle_agent_event()
            return
        if self.path == "/background/run-once":
            self._handle_background_once()
            return
        if self.path == "/entries":
            self._handle_create_entry()
            return
        if self.path == "/feedback":
            self._handle_feedback()
            return
        if self.path == "/memory/markdown":
            self._handle_import_markdown()
            return
        if self.path == "/api/bridge/start":
            self._handle_bridge_start()
            return
        if self.path == "/api/bridge/stop":
            self._handle_bridge_stop()
            return
        if self.path == "/api/bridge/pair-code":
            self._handle_pair_code()
            return
        if self.path == "/api/bridge/pair":
            self._handle_pair()
            return
        if self.path == "/api/bridge/unpair":
            self._handle_unpair()
            return
        if self.path == "/api/settings/delegation":
            self._handle_delegation_setting()
            return
        self.send_error(404, "not found")

    def do_PUT(self):
        # 与 `do_POST` 同一条纪律：请求体先读干净，再进任何分支与任何闸门。
        # **PUT 少这一行的后果正是 429 那条用例的形状**——`_dai_li` 的每一个拒绝
        # 分支（非 GET 无 CSRF 的 403、无网关/无设备的 502、429）都会带着没读的
        # body 回响应，keep-alive 下同一条连接上的下一条请求把 body 当成请求行
        # 来解析，拿到 400。PUT 与 POST 的差别只是入口没抄这一行，不是它不需要。
        # 读在入口之后，`_read_json`（/entries/*）与 `_ti_zi()` 都走缓存，不会重读。
        self._du_wan()
        parsed = urlparse(self.path)
        if self._shi_fou_dai_li(parsed):
            self._dai_li(parsed, "PUT")
            return
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["models", "profiles"]:
            if self._fangxing():
                self._handle_update_model_profile(unquote(parts[2]))
            return
        if parsed.path.startswith("/entries/"):
            self._handle_update_entry(unquote(parsed.path.rsplit("/", 1)[-1]))
            return
        self.send_error(404, "not found")

    def do_DELETE(self):
        self._du_wan()
        parsed = urlparse(self.path)
        if self._shi_fou_dai_li(parsed):
            self._dai_li(parsed, "DELETE")
            return
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["models", "profiles"]:
            if self._fangxing():
                self._handle_delete_model_profile(unquote(parts[2]))
            return
        self.send_error(404, "not found")

    # ---- `/agent-api/*` 的反向代理（spec 9.1、9.3、9.4）----

    def _shi_fou_dai_li(self, a1) -> bool:
        """这条路径是不是要反代。**必须最先匹配**，否则会掉进各自的 404。"""
        return a1.path == "/agent-api" or a1.path.startswith("/agent-api/")

    def _pan_yuan(self) -> bool:
        """这个请求像不像浏览器发的（戴着可信的 `Origin` / `Sec-Fetch-Site` 来）。

        **这不是鉴权。** 请求头不是浏览器专属财产，脚本想发就发——伪造一个来源头
        就回到「占窗口」的原状。占位 `userId` 的威胁模型内（主服务只绑回环、接入
        登录前不得公网暴露，spec 9.3/11.4），这个判据只用来把**非预期**流量
        （curl、探针、健康检查）挡在浏览器用户的窗口之外，防的是「误打满别人的
        窗口」，不防主动攻击者。

        两个头各判各的，谁在就查谁：`Sec-Fetch-Site` 的值必须在 `KE_XIN` 里，
        `Origin` 必须在 `YUAN_BAI` 里。**缺 `Origin` 不算非浏览器**（同源 fetch
        与 EventSource 都不发它），两个头都缺才算。

        比对用白名单而**不是**「`Origin` 的 host 等于请求 `Host`」：前端跑 5173、
        主服务跑 8765，两者的端口永远不同，照那样判会把所有合法浏览器判成非浏览器，
        SSE 全挂。
        """
        zhi = self.headers.get("Sec-Fetch-Site")
        yuan = self.headers.get("Origin")
        if zhi is None and yuan is None:
            return False
        if zhi is not None and zhi not in KE_XIN:
            return False
        if yuan is not None and yuan not in YUAN_BAI:
            return False
        return True

    def _dai_li(self, a1, a2: str) -> None:
        """反代的一次请求。延迟 import `bridge_admin` 是为了避开循环依赖。"""
        from lifeos.api import bridge_admin
        if a2 != "GET" and not self._shou_quan_guan():
            return
        gw = bridge_admin.GW
        if gw is None:
            self._song_dai_li_wu(502, "agent_unavailable", "隧道网关未启动")
            return
        she = bridge_admin.du_she()
        if not she:
            self._song_dai_li_wu(
                502, "agent_unavailable",
                "还没有配对的设备，请先在「本地 Agent」页添加设备")
            return
        rest = a1.path[len("/agent-api"):] or "/"
        # 来源判定（已裁定）：带了 `Origin` 或 `Sec-Fetch-Site` = 浏览器来源；
        # 两者都缺 = 非浏览器。非浏览器不占浏览器用户的窗口，另走上面那套匿名
        # 窗口。判据**不是 CSRF**——`_fangxing()` 对所有方法都强制 CSRF，而
        # 浏览器端的 EventSource 发不出自定义头，把鉴权无条件提到限流之前会让
        # 合法 GET 一起被 403 挡掉。
        you = self._pan_yuan()
        yong = dang_qian_yong_hu() if you else NI_MING
        she_id = she["deviceId"] if you else NI_MING
        # **限流必须在 `rest` 算出来之后、`qing` 组装之前。** 顺序是承重的：
        # 限流要拿 `rest` 判是不是审批类（15.4 的 `p:` 窗口只对 /permissions*
        # 与 /questions* 计），放前面就没有 `rest` 可用；放 `gw.qing` 之后则
        # 请求已经下过隧道了——被限的请求也占掉了设备的一次在途名额。
        #
        # **`/stream` 明确放行。** 它是一条长连接，客户端建一次就挂着收帧，
        # 按速率限它等于「每分钟只准重连 60 次」；而 spec 10.1 把 SSE 的配额
        # 划给了 Bridge 那边的连接数上限（`http.py` 的 `ZUI_DUO_LIU`），
        # 速率这一层不归它管。EventSource 还会自动重连，被 429 挡掉就黑屏。
        # **这个豁免必须排在来源判定之后**，见下面 /stream 那道闸。
        if rest != "/stream" or a2 != "GET":
            chi = gw.xian_liu(yong, she_id, rest)
            if chi is not None:
                # 429 之前必须把请求体读干净。keep-alive 下留着它就串响应：
                # 同一条连接上的下一条请求把上一条的 body 当成请求行来解析，
                # 拿到的是 400（评审真机日志 `('{"text": "xxx"}GET /agent-api/…')`）。
                # PUT 没有 `_du_wan()` 预读，所以这里得自己读——`_ti_zi()` 有
                # 预读缓存时走缓存，不会把已经读过的体再读一次。
                self._ti_zi()
                self._song_dai_li_wu(429, "rate_limited", "请求过于频繁",
                                      {"retry-after": str(int(chi))})
                return
        # **只能调一次。** GET 没有 `_du_wan` 预读，回退分支每次都去读 `rfile`；
        # 写成 `if self._ti_zi() else None` 会在同一个请求里读两次，第二次
        # 阻塞到超时（没有 body 的 GET 永远等不到 `content-length` 个字节）。
        fan = self._ti_zi()
        try:
            shen = fan.decode("utf-8") if fan else None
        except UnicodeDecodeError:
            # **协议边界，不是可以顺手兜住的异常。** 当前协议的 request body
            # 定义为「UTF-8 字符串或 null」，没有 base64 字段（6.x 的契约层
            # `xie_yi.py` 就是这么定的），所以非 UTF-8 字节在主服务边界就是
            # 一个畸形请求，必须 400。放任它穿出去的话 handler 抛异常、
            # 连接被重置，客户端拿到的是 10054 而不是那个错误码。
            #
            # 将来真要支持二进制请求体，得**先升协议版本**并同时更新两端契约、
            # 大小限制、测试与文档——不是在这里加个 `bodyB64` 字段的事。
            self._song_dai_li_wu(400, "invalid_request",
                                  "请求体不是合法的 UTF-8 文本")
            return
        tou = {k.lower(): v for k, v in self.headers.items()
               if k.lower() not in {"host", "content-length", "origin", "referer",
                                    "x-lifeos-csrf", "connection", "accept-encoding"}}
        qing = {"method": a2, "path": rest, "query": a1.query,
                "headers": tou, "body": shen}
        # **流式端点写死在这里。** 桥接只有一个（7.4 的 /stream）。
        # 将来加流式端点必须同时改这一行。
        if rest == "/stream" and a2 == "GET":
            if not you:
                # 无来源头的 `/stream` 不许开。它同时免了「速率」与「鉴权」两个
                # 闸（上面的闸门只管非 GET），叠在一起就是任何人都能开无限条，
                # 每条占一个线程（ThreadingHTTPServer）——最便宜的一种拒绝服务。
                # 判据是来源而不是 CSRF：EventSource 发不出 CSRF 头，按它拦会把
                # 浏览器的 SSE 一起挡掉、界面全黑。
                self._song_dai_li_wu(403, "forbidden", "SSE 长连接只接受浏览器来源")
                return
            # **token 必须传到 `finally` 里释放。** 名额按连接发，释放时靠这枚
            # token 定位本条；只传来源键的话分不清同来源的 8 条，释放任意一条
            # 都会连带清掉其余 7 条。
            ling_piao = self._zhao_ming_e(a1, gw, you, she_id)
            if ling_piao is None:
                return
            try:
                self._dai_liu(gw, she["deviceId"], qing)
            finally:
                # **释放放在调用点，不放在 `_dai_liu` 里面。** 那里有四条
                # 退出路径（合成流、真隧道正常结束、隧道断、写失败），再加
                # 一次异常，漏掉任何一条都是永久泄漏一个名额。放在这里，
                # 「每条被放行的流恰好释放一次」由语法保证而不是靠记性。
                self._fang_ming_e(gw, you, she_id, ling_piao)
            return
        try:
            r = gw.qing(she["deviceId"], qing)
        except WuDui as e:
            self._song_dai_li_wu(502, e.code, e.message)
            return
        self._song_dai_li(r)

    def _song_dai_li_wu(self, a1: int, a2: str, a3: str,
                        a4: dict[str, str] | None = None) -> None:
        """反代的错误响应。a4 是额外响应头（429 要带 Retry-After）。"""
        self._send_json({"error": {"code": a2, "message": a3}}, status=a1, extra=a4)

    def _ti_zi(self) -> bytes:
        """请求体字节。**入口 `_du_wan()` 已预读的用缓存**——再读一次 `rfile`
        只会拿到空串，转发出去的 body 永远是空的。`do_GET` 没有预读，
        回退到直接读（`/agent-api/stream` 那类无体请求压根不进这里）。"""
        raw = getattr(self, "_body", None)
        if raw is not None:
            return raw
        try:
            n = int(self.headers.get("content-length", "0"))
        except ValueError:
            n = 0
        return self.rfile.read(n) if n else b""

    def _song_dai_li(self, a1: dict) -> None:
        shen = (base64.b64decode(a1["body"]) if a1.get("b64")
                else a1["body"].encode("utf-8"))
        self.send_response(int(a1["status"]))
        for k, v in (a1["headers"] or {}).items():
            # **content-length 必须丢掉重算。** 照抄上游的会在 base64 或编码
            # 差异下写成错的长度，keep-alive 下直接串响应；hop-by-hop 头
            # （transfer-encoding / connection / content-encoding）照抄则是
            # 把上游的连接语义漏到下游，下游读到的字节数从此对不上。
            if k.lower() in {"content-length", "transfer-encoding", "connection",
                             "content-encoding"}:
                continue
            self.send_header(k, v)
        self.send_header("content-length", str(len(shen)))
        self.end_headers()
        self.wfile.write(shen)

    def _zhao_ming_e(self, a1, a2, a3: bool, a4: str):
        """给这条代理流占一个 SSE 名额。

        **返回本连接的那枚 token；返回 None 表示已超限（响应已发出）。**
        释放必须拿这枚 token 回来定位——只给「来源键」的话无法区分同来源的
        8 条流，释放任意一条都会连带清掉其余 7 条（漏释放与多释放同样致命：
        前者额度越用越少，后者上限形同虚设）。

        **按可信来源计数，不按浏览器自报的头。** `x-lifeos-source` 是请求
        头里的数据，谁都能写；拿它当身份等于没上限——攻击者每次换一个值就
        得到一个全新的计数桶。可信来源取自 `_pan_yuan()`（来源判据）加设备
        归属，接入登录之后换成真正的 userId。

        **名额按「每条连接」发，桶按来源分。** 表是 `{来源键: {token…}}`：
        同一个来源的第 9 条才会被拒，而同来源的 8 条各自持有独立名额。表要是
        「一来源一元素」，同来源的 8 条会挤成 1 个——上限数不到，429 永不触发，
        合成流顶掉旧流时还会顺手删掉整桶（见 `bridge_admin.zhuang` 的注释）。

        **token 用 `object()`，每条连接一个独立对象。** 换成字符串或连接 id
        的话一旦重复，集合会去重，两条流共用一枚名义上的名额，计数立刻失真。

        后连不踢先连：与 Bridge 层（`http.py:_liu`）不同，主服务这一层踢人
        会把浏览器正在用的那条流掐掉，而这里已经有 `Retry-After` 让它自己
        退避了。
        """
        key = (a3, a4)
        with a2._dl_suo:
            huo = a2._dai_liu_biao.setdefault(key, set())
            if len(huo) >= ZUI_DAI_LIU:
                chao = DAI_LIU_CHONG_LIAN
                token = None
            else:
                token = object()
                huo.add(token)
                chao = None
        if chao is None:
            return token
        self._song_dai_li_wu(429, "rate_limited",
                              f"同一来源的 SSE 连接数已达上限（{ZUI_DAI_LIU}）",
                              {"retry-after": str(chao)})
        return None

    def _fang_ming_e(self, a1, a2: bool, a3: str, a4) -> None:
        """释放代理流占的那一个名额。**幂等**——重复释放不会误伤同来源的别人。

        只删本连接那枚 token；桶空了才把桶本身摘掉，摘桶用 `pop(key, None)`
        而不是「先判断再删」——同一把锁内两步是原子的，但 `pop` 的默认参数
        让它天生不怕「桶已经没了」。
        """
        with a1._dl_suo:
            huo = a1._dai_liu_biao.get((a2, a3))
            if huo is None:
                return
            huo.discard(a4)
            if not huo:
                a1._dai_liu_biao.pop((a2, a3), None)

    def _dai_liu(self, a1, a2: str, a3: dict) -> None:
        """代理 SSE。**绝不缓冲**：写完头就 flush，逐帧写逐帧 flush。。

        名额的释放在**最外层**的 `finally` 里：这条函数有四条退出路径
        （正常结束、隧道断、浏览器走、写失败），任何一条漏掉都是永久泄漏
        一个名额——开够次数之后主服务对谁都返回 429，且再也回不来。
        """
        self.send_response(200)
        self.send_header("content-type", "text/event-stream; charset=utf-8")
        self.send_header("cache-control", "no-cache, no-transform")
        self.send_header("x-accel-buffering", "no")   # 10.4 第 4 条
        # 帧长未知，必须声明 chunked。少了这一行客户端会按「读到连接关闭为止」
        # 解析，浏览器的 EventSource 行为就不对了（`http.py:_liu` 同一条）。
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()
        self.wfile.flush()

        def xie(a1: str) -> bool:
            """写一条 chunk。返回 False 表示对端走了，后续都不必再试。"""
            shu = a1.encode("utf-8")
            try:
                self.wfile.write(f"{len(shu):X}\r\n".encode("ascii") + shu + b"\r\n")
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                return False

        if a1.zhuang_tai(a2) != "connected":
            # 设备离线：给一条**合成流**，首帧 device_status + 每 15 秒一个心跳，
            # 一直挂着（不返回 503 —— EventSource 对 503 的重试节奏各浏览器不同，
            # 握着真实流行为统一，也天然算进「每用户 8 条」的连接计数）。
            self._he_cheng_liu(a1, a2, xie)
            return
        try:
            _tou, liu = a1.kai_liu(a2, a3)
        except WuDui as e:
            if not xie(xie_zhen(he_cheng_zhen(a2, "offline", e.message))):
                return
            self._he_cheng_liu(a1, a2, xie, False)
            return
        try:
            while True:
                f = liu.zhen()
                if f is None:
                    # `None` 既可能是流正常结束，也可能是隧道断了。**要分开**：
                    # 断线时给前端一条 offline 帧，界面才显示得出「设备离线」。
                    if a1.zhuang_tai(a2) != "connected":
                        xie(xie_zhen(he_cheng_zhen(a2, "offline", "隧道中断")))
                    return
                if not xie(xie_zhen(f)):
                    return
        finally:
            liu.guan()

    def _he_cheng_liu(self, a1, a2: str, a3, a4: bool = True) -> None:
        """合成流：一条 offline 帧 + 心跳，挂到设备回来或浏览器走掉为止。"""
        if a4 and not a3(xie_zhen(he_cheng_zhen(a2, "offline", None))):
            return
        # 同一设备只保留最新一条合成流：隧道长时间离线时浏览器会反复重连，
        # 不收拾的话它们会攒到 8 条上限，真隧道回来时反而连不上（风险 3）。
        # **锁与表在 `bridge_admin.zhuang` 装配网关时就建好**，不 `getattr` 兜底：
        # 兜底里的 `threading.Lock()` 每次求值都是一把新锁，两处各拿一把，
        # `finally` 那把就不是 `try` 这边释放的那把，表会被并发写坏（修订 3）。
        ting = threading.Event()
        with a1._hc_suo:
            lao = a1._hc_biao.get(a2)
            if lao is not None:
                lao.set()
            a1._hc_biao[a2] = ting
        try:
            while not ting.is_set():
                if a1.zhuang_tai(a2) == "connected":
                    return
                if ting.wait(15.0):
                    return
                if not a3(": ping\n\n"):
                    return
        finally:
            with a1._hc_suo:
                if a1._hc_biao.get(a2) is ting:
                    a1._hc_biao.pop(a2, None)

    def _handle_chat(self):
        body = self._read_json()
        try:
            routing_policy = body.get("routing_policy", "auto")
            if routing_policy not in {"auto", "force_self_plan", "force_agent"}:
                raise ValueError("routing_policy must be auto, force_self_plan, or force_agent")
            scope = body.get("memory_scope")
            if isinstance(scope, dict):
                owner_id = dang_qian_yong_hu()
                if scope.get("user_id") not in (None, owner_id):
                    raise ValueError("memory scope user_id does not match the current user")
                scope = {**scope, "user_id": owner_id}
            result = asyncio.run(self.agent.run(
                body.get("message", ""),
                session_id=body.get("session_id"),
                memory_scope=scope,
                model_profile_id=body.get("profile_id"),
                routing_policy=routing_policy,
            ))
        except (ValueError, KeyError) as exc:
            self._send_json({"error": {"code": "invalid_request", "message": str(exc)}}, status=400)
            return
        except LLMRequestError as exc:
            self._send_json({"error": {"code": "model_provider_error", "message": str(exc), "status": exc.status}}, status=502)
            return
        self._send_json(result)

    def _handle_agent_event(self):
        """Bridge 的决策回路回调（7.7.1）。

        认证：本地形态只接受回环来源，公网形态改走隧道校验（阶段 6）。
        这里的检查不能省——省掉的话，页面上任何一段脚本都能往 LifeOS 的
        上下文里塞字，让大模型把伪造的「Agent 执行结果」当成事实。
        """
        host = self.client_address[0] if self.client_address else ""
        if host not in ("127.0.0.1", "::1"):
            self._send_json({"error": {"code": "forbidden", "message": "仅接受本机 Bridge 回调"}}, status=403)
            return
        try:
            body = self._read_json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json({"error": {"code": "invalid_request", "message": "body must be JSON"}}, status=400)
            return
        kind = body.get("kind")
        detail = body.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        if kind in JUE_LU:
            try:
                text = self.agent.agent_event(
                    kind, body.get("sessionId"), detail,
                    event_id=body.get("eventId"), owner_id=dang_qian_yong_hu(),
                )
            except ValueError as exc:
                self._send_json({"error": {"code": "conflict", "message": str(exc)}}, status=409)
                return
            self._send_json({"ok": True, "contextText": text})
            return
        if kind not in ZHUAN_LIU:
            self._send_json({"error": {"code": "invalid_request",
                                       "message": f"unknown kind: {kind}"}}, status=400)
            return
        shou, diu = guo_lu2(kind, detail)
        if diu:
            print(f"[lifeos] {kind} 的 detail 有 {diu} 个字段不在白名单内，已丢弃",
                  file=sys.stderr, flush=True)
        # 只写事件总线。不产生任何指向 Bridge 的出站调用（7.7.1 第 1 条）。
        asyncio.run(self.agent.event_bus.publish(kind, shou))
        self._send_json({"ok": True, "dropped": diu})

    def _handle_background_once(self):
        result = asyncio.run(self.agent.run_background_once())
        self._send_json({"processed": result})

    # ---- 状态改变型端点的两道闸（10.2）----
    #
    # 页面里一个第三方广告 iframe 执行
    #   fetch("http://127.0.0.1:8765/api/bridge/stop", {method:"POST", mode:"no-cors"})
    # 是简单请求，不触发预检。没有这两道校验主服务就直接执行 → Bridge 退出 →
    # 连带杀掉 agent 子进程 → 用户正在做的任务和待审批的请求一起消失，界面上还没有任何解释。

    def _fangxing(self) -> bool:
        host = self.client_address[0] if self.client_address else ""
        if host not in ("127.0.0.1", "::1"):
            self._send_json({"error": {"code": "forbidden", "message": "仅限本机"}}, status=403)
            return False
        yuan = self.headers.get("Origin")
        # 缺 Origin 放行：本地 curl 与服务端自调没有 Origin，
        # 而那条路径上 CSRF token 仍然要过。
        if yuan and yuan not in YUAN_BAI:
            self._send_json({"error": {"code": "forbidden", "message": f"Origin 不在白名单：{yuan}"}}, status=403)
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self._send_json({"error": {"code": "forbidden", "message": "跨站请求"}}, status=403)
            return False
        if not bridge_admin.yong_ma(self.headers.get("X-LifeOS-CSRF")):
            self._send_json({"error": {"code": "forbidden", "message": "CSRF token 无效或已用过"}}, status=403)
            return False
        return True

    def _handle_bridge_start(self):
        if not self._fangxing():
            return
        self._send_json(bridge_admin.qidong())

    def _handle_bridge_stop(self):
        if not self._fangxing():
            return
        self._send_json(bridge_admin.tingzhi())

    def _handle_pair_code(self):
        """生成配对码。状态改变型端点，要过 CSRF（10.2）。"""
        if not self._shou_quan_guan():
            return
        self._send_json(bridge_admin.sheng_ma())

    def _handle_pair(self):
        """Bridge 用配对码换凭据（5.3 第 3 步）。

        **鉴权与其余三个端点不同**：调用方是本机 Bridge，不是浏览器，没有 CSRF
        token；凭据是配对码本身。追加约束是只接受回环来源——公网形态下这条
        要改成「隧道内来源」（spec 9.3）。
        """
        host = self.client_address[0] if self.client_address else ""
        if host not in ("127.0.0.1", "::1"):
            self._send_json({"error": {"code": "forbidden",
                                       "message": "配对只接受本机来源"}}, status=403)
            return
        # 畸形 / 非对象 body 回 400（照 _handle_agent_event）。不包的话异常冒出
        # do_POST，客户端看到的是连接被丢而不是 400，服务端再吐一堆 traceback。
        try:
            body = self._read_json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = None
        if not isinstance(body, dict):
            self._send_json({"error": {"code": "invalid_request",
                                       "message": "body must be JSON"}}, status=400)
            return
        try:
            r = bridge_admin.pai_dui(str(body.get("code") or ""),
                                     str(body.get("label") or ""),
                                     str(body.get("instanceId") or ""))
        except ValueError as exc:
            self._send_json({"error": {"code": "invalid_request",
                                       "message": str(exc)}}, status=400)
            return
        self._send_json(r)

    def _handle_unpair(self):
        if not self._shou_quan_guan():
            return
        try:
            body = self._read_json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = None
        if not isinstance(body, dict):
            self._send_json({"error": {"code": "invalid_request",
                                       "message": "body must be JSON"}}, status=400)
            return
        self._send_json(bridge_admin.jie_bang(str(body.get("deviceId") or "")))

    def _handle_bridge_devices(self):
        if not self._shou_quan_guan():
            return
        self._send_json({"devices": bridge_admin.she_lie(
            dang_qian_yong_hu())})

    def _shou_quan_guan(self) -> bool:
        """管控端点的同源 + CSRF 校验。返回 False 表示已经回过错误了。

        与 10.2 对 /api/bridge/start|stop 的要求完全一致——**直接复用 `_fangxing()`，
        不另写一套**。这里曾经是它的一个更弱的分叉副本（丢掉回环来源与
        Sec-Fetch-Site 两道检查，Origin 白名单放宽成「hostname 是 127.0.0.1/localhost
        的任意端口与 scheme」）。同一个服务器上两套分叉的闸、其中一套更弱，
        正是日后变成漏洞的形状。
        """
        return self._fangxing()

    def _handle_delegation_setting(self):
        if not self._fangxing():
            return
        try:
            body = self._read_json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json({"error": {"code": "invalid_request", "message": "body must be JSON"}}, status=400)
            return
        kai = bool(body.get("enabled"))
        self.agent.chat.delegation_enabled = kai
        self._send_json({"enabled": kai})

    def _handle_create_model_profile(self):
        try:
            profile = self.agent.model_store.create(self._read_json())
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            self._send_json({"error": {"code": "invalid_request", "message": str(exc)}}, status=400)
            return
        self._send_json({"profile": profile}, status=201)

    def _handle_model_discovery(self):
        try:
            models = self.agent.model_store.discover_models(self._read_json())
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            self._send_json({"error": {"code": "invalid_request", "message": str(exc)}}, status=400)
            return
        except LLMRequestError as exc:
            self._send_json({"error": {"code": "model_provider_error", "message": str(exc), "status": exc.status}}, status=502)
            return
        self._send_json({"models": models})

    def _handle_update_model_profile(self, profile_id):
        try:
            profile = self.agent.model_store.update(profile_id, self._read_json())
        except KeyError as exc:
            self._send_json({"error": {"code": "not_found", "message": str(exc)}}, status=404)
            return
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": {"code": "invalid_request", "message": str(exc)}}, status=400)
            return
        self._send_json({"profile": profile})

    def _handle_model_activate(self, profile_id):
        try:
            profile = self.agent.model_store.activate(profile_id)
        except KeyError as exc:
            self._send_json({"error": {"code": "not_found", "message": str(exc)}}, status=404)
            return
        self._send_json({"active_profile_id": profile["id"], "profile": profile})

    def _handle_delete_model_profile(self, profile_id):
        try:
            profile = self.agent.model_store.delete(profile_id)
        except KeyError as exc:
            self._send_json({"error": {"code": "not_found", "message": str(exc)}}, status=404)
            return
        except ValueError as exc:
            self._send_json({"error": {"code": "conflict", "message": str(exc)}}, status=409)
            return
        self._send_json({"deleted": True, "profile": profile})

    def _handle_model_test(self, profile_id):
        try:
            result = self.agent.model_store.test(profile_id)
        except KeyError as exc:
            self._send_json({"error": {"code": "not_found", "message": str(exc)}}, status=404)
            return
        except LLMRequestError as exc:
            self._send_json({"error": {"code": "model_provider_error", "message": str(exc), "status": exc.status}}, status=502)
            return
        self._send_json(result)

    def _handle_model_test_payload(self):
        try:
            result = self.agent.model_store.test(self._read_json())
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            self._send_json({"error": {"code": "invalid_request", "message": str(exc)}}, status=400)
            return
        except LLMRequestError as exc:
            self._send_json({"error": {"code": "model_provider_error", "message": str(exc), "status": exc.status}}, status=502)
            return
        self._send_json(result)

    def _handle_list_entries(self, query):
        kind = query.get("kind", [None])[0]
        entry_date = query.get("date", [None])[0]
        try:
            entries = self.structured_store.list_entries(kind=kind, entry_date=entry_date)
        except (TypeError, ValueError) as exc:
            self._send_json({"error": {"code": "invalid_request", "message": str(exc)}}, status=400)
            return
        self._send_json({"entries": entries})

    def _handle_get_entry(self, entry_id):
        entry = self.structured_store.get(entry_id)
        if entry is None:
            self.send_error(404, "entry not found")
            return
        self._send_json({"entry": entry})

    def _handle_create_entry(self):
        self._save_entry()

    def _handle_update_entry(self, entry_id):
        if self.structured_store.get(entry_id) is None:
            self.send_error(404, "entry not found")
            return
        self._save_entry(entry_id)

    def _save_entry(self, entry_id=None):
        try:
            entry = self.structured_store.upsert(self._read_json(), entry_id=entry_id)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            self._send_json({"error": {"code": "invalid_request", "message": str(exc)}}, status=400)
            return
        self._send_json({"entry": entry}, status=201 if entry_id is None else 200)

    def _handle_feedback(self):
        body = self._read_json()
        rating = body.get("rating")
        trace_id = body.get("trace_id")
        note = body.get("note", "")
        valid = {"plan_too_heavy", "just_right", "helpful", "not_helpful"}
        if rating not in valid:
            self._send_json(
                {"error": {"code": "invalid_request", "message": f"rating must be one of {sorted(valid)}"}},
                status=400,
            )
            return
        asyncio.run(self.agent.submit_feedback(rating=rating, trace_id=trace_id, note=note))
        self._send_json({"ok": True})

    def _handle_export_markdown(self):
        md = self.agent.memory.export_markdown()
        self._send_json({"markdown": md, "source": "backend"})

    def _handle_import_markdown(self):
        body = self._read_json()
        text = body.get("markdown", "")
        if not isinstance(text, str) or not text.strip():
            self._send_json(
                {"error": {"code": "invalid_request", "message": "markdown body is required"}},
                status=400,
            )
            return
        try:
            store = self.agent.memory.import_markdown(text)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": {"code": "invalid_request", "message": str(exc)}}, status=400)
            return
        counts = {
            key: len(value)
            for key, value in store.items()
            if isinstance(value, list)
        }
        self._send_json({"ok": True, "categories": counts})

    def _handle_agent_memory_candidate(self, evidence_id):
        owner_id = dang_qian_yong_hu()
        evidence = self.agent.agent_evidence.get(evidence_id, owner_id=owner_id)
        if evidence is None:
            self._send_json({"error": {"code": "not_found"}}, status=404)
            return
        body = self._read_json()
        claim = body.get("claim")
        project_id = body.get("project_id")
        if (not isinstance(claim, str) or not claim.strip()
                or not isinstance(project_id, str) or not project_id.strip()):
            self._send_json({"error": {"code": "invalid_request",
                                       "message": "claim and project_id are required"}}, status=400)
            return
        try:
            candidate = asyncio.run(self.agent.memory.propose_update(
                source="agent_execution",
                content={"claim": claim.strip()},
                category="project",
                scope={"kind": "project", "project_id": project_id.strip(),
                       "user_id": owner_id},
                source_ref={"kind": "agent_result", "record_id": evidence["id"],
                            "session_id": evidence["session_id"],
                            "agent_id": evidence["agent_id"],
                            "owner_id": owner_id},
                occurred_at=evidence["occurred_at"],
            ))
        except ValueError as exc:
            self._send_json({"error": {"code": "invalid_request", "message": str(exc)}}, status=400)
            return
        self._send_json({"status": candidate["status"], "candidate": candidate},
                        status=201 if candidate["status"] == "candidate" else 200)

    def _handle_memory_candidate(self, candidate_id, action):
        try:
            if action == "commit":
                item = asyncio.run(self.agent.memory.commit_candidate(candidate_id))
                item = self._sync_approved_memory(item)
            else:
                item = asyncio.run(self.agent.memory.reject_candidate(candidate_id))
        except KeyError as exc:
            self._send_json({"error": {"code": "not_found", "message": str(exc)}}, status=404)
            return
        except ValueError as exc:
            self._send_json({"error": {"code": "conflict", "message": str(exc)}}, status=409)
            return
        self._send_json({"status": "committed" if action == "commit" else "rejected", "item": item})

    def _sync_approved_memory(self, item):
        """Sync only after the existing LifeOS approval/commit gate."""
        provider = getattr(self.agent, "external_memory", None)
        if provider is None:
            return item
        try:
            provider.write_approved_memory(item)
            return self.agent.memory.set_provider_sync(
                item["id"], "synced", remote_id=f"lifeos-{item['id']}"
            )
        except Exception as exc:
            # The local approval is durable; deterministic remote IDs make a
            # repeated commit request a safe retry without resending raw source.
            return self.agent.memory.set_provider_sync(
                item["id"], "pending", error=type(exc).__name__
            )

    def _handle_tencentdb_sync_pending(self):
        provider = getattr(self.agent, "external_memory", None)
        if provider is None:
            self._send_json({"error": {"code": "provider_disabled"}}, status=409)
            return
        outcomes = []
        for item in self.agent.memory.memory_records():
            sync = item.get("provider_sync") or {}
            if sync.get("status") != "pending":
                continue
            try:
                if item.get("status", "active") == "active":
                    provider.write_approved_memory(item)
                    updated = self.agent.memory.set_provider_sync(
                        item["id"], "synced", remote_id=f"lifeos-{item['id']}"
                    )
                else:
                    provider.delete_approved_memory(item["id"])
                    updated = self.agent.memory.set_provider_sync(item["id"], "deleted")
                outcomes.append({"memory_id": item["id"], "status": updated["provider_sync"]["status"]})
            except Exception as exc:
                updated = self.agent.memory.set_provider_sync(
                    item["id"], "pending", error=type(exc).__name__
                )
                outcomes.append({"memory_id": item["id"], "status": "pending", "error": type(exc).__name__})
        self._send_json({"results": outcomes})

    def _handle_memory_mutation(self, memory_id, action):
        body = self._read_json()
        previous = None
        try:
            previous = self.agent.memory._find_memory(self.agent.memory._read(), memory_id)
        except KeyError:
            pass
        try:
            if action == "correct":
                item = asyncio.run(
                    self.agent.memory.correct_memory(
                        memory_id, body.get("content"), reason=body.get("reason")
                    )
                )
            else:
                item = asyncio.run(
                    self.agent.memory.retract_memory(memory_id, reason=body.get("reason"))
                )
        except KeyError as exc:
            self._send_json({"error": {"code": "not_found", "message": str(exc)}}, status=404)
            return
        except ValueError as exc:
            self._send_json({"error": {"code": "conflict", "message": str(exc)}}, status=409)
            return
        provider = getattr(self.agent, "external_memory", None)
        previous_sync = (previous or {}).get("provider_sync", {}).get("status")
        if provider is not None and previous and previous_sync in {"synced", "pending"}:
            remote_deleted = False
            try:
                provider.delete_approved_memory(memory_id)
                self.agent.memory.set_provider_sync(memory_id, "deleted")
                remote_deleted = True
                if action == "correct":
                    provider.write_approved_memory(item)
                    item = self.agent.memory.set_provider_sync(
                        item["id"], "synced", remote_id=f"lifeos-{item['id']}"
                    )
                else:
                    item = self.agent.memory.set_provider_sync(memory_id, "deleted")
            except Exception as exc:
                # Local lifecycle state remains authoritative for the read
                # filter, so stale remote results are discarded on recall.
                target_id = item["id"] if action == "correct" else memory_id
                item = self.agent.memory.set_provider_sync(
                    target_id, "pending", error=type(exc).__name__
                )
                if action == "correct" and not remote_deleted:
                    self.agent.memory.set_provider_sync(
                        memory_id, "pending", error=type(exc).__name__
                    )
        self._send_json({"status": item.get("status"), "memory": item})

    def _handle_trace_memory_candidate(self, trace_id):
        trace = self.agent.trace.get(trace_id)
        if trace is None:
            self._send_json(
                {"error": {"code": "not_found", "message": "conversation trace not found"}},
                status=404,
            )
            return
        body = self._read_json()
        content = body.get("content") if isinstance(body, dict) else None
        claim = content.get("claim") if isinstance(content, dict) else None
        category = body.get("category") if isinstance(body, dict) else None
        scope = body.get("scope") if isinstance(body, dict) else None
        if not isinstance(claim, str) or not claim.strip() or len(claim) > 2000:
            self._send_json(
                {"error": {"code": "invalid_request", "message": "a distilled claim of 1-2000 characters is required"}},
                status=400,
            )
            return
        if not isinstance(scope, dict) or scope.get("kind") not in {"global", "scenario", "project"}:
            self._send_json(
                {"error": {"code": "invalid_request", "message": "an explicit global, scenario, or project scope is required"}},
                status=400,
            )
            return
        expected_category = "project" if scope["kind"] == "project" else "user"
        if category != expected_category:
            self._send_json(
                {"error": {"code": "invalid_request", "message": f"category must be {expected_category} for this scope"}},
                status=400,
            )
            return
        try:
            candidate = asyncio.run(
                self.agent.memory.propose_update(
                    source="direct",
                    content={"claim": claim.strip()},
                    trace_id=trace_id,
                    source_ref={"kind": "conversation", "record_id": trace_id},
                    scope=scope,
                    category=category,
                    confidence=1.0,
                    confidence_method="user_confirmed",
                    occurred_at=trace.get("created"),
                )
            )
        except ValueError as exc:
            self._send_json(
                {"error": {"code": "invalid_request", "message": str(exc)}},
                status=400,
            )
            return
        self._send_json(
            {"status": candidate.get("status"), "candidate": candidate},
            status=201 if candidate.get("status") == "candidate" else 200,
        )

    def _handle_structured_entry_memory_candidate(self, entry_id):
        entry = self.structured_store.get(entry_id)
        if entry is None:
            self._send_json(
                {"error": {"code": "not_found", "message": "structured entry not found"}},
                status=404,
            )
            return
        if entry["kind"] not in {"daily_plan", "daily_review", "phase_plan", "phase_review"}:
            self._send_json(
                {"error": {"code": "invalid_request", "message": "entry kind is not enabled for memory capture"}},
                status=400,
            )
            return
        body = self._read_json()
        content = body.get("content")
        category = body.get("category")
        scope = body.get("scope")
        if not isinstance(content, dict) or not content:
            self._send_json(
                {"error": {"code": "invalid_request", "message": "non-empty distilled content is required"}},
                status=400,
            )
            return
        if not category or not isinstance(scope, dict):
            self._send_json(
                {"error": {"code": "invalid_request", "message": "category and scope are required"}},
                status=400,
            )
            return
        try:
            candidate = asyncio.run(
                self.agent.memory.propose_update(
                    source="structured_entry",
                    content=content,
                    source_ref={
                        "kind": "structured_entry",
                        "record_id": entry["id"],
                        "record_kind": entry["kind"],
                        "revision": entry["updated_at"],
                    },
                    scope=scope,
                    category=category,
                    confidence=body.get("confidence"),
                    confidence_method=body.get("confidence_method"),
                    occurred_at=entry["entry_date"],
                )
            )
        except ValueError as exc:
            self._send_json(
                {"error": {"code": "invalid_request", "message": str(exc)}},
                status=400,
            )
            return
        response_status = 201 if candidate.get("status") == "candidate" else 200
        self._send_json(
            {"status": candidate.get("status"), "candidate": candidate},
            status=response_status,
        )


    def _handle_skill_candidate(self, skill_id, action):
        try:
            if action == "approve":
                item = asyncio.run(self.agent.skills.approve_by_id(skill_id))
            else:
                item = asyncio.run(self.agent.skills.reject_by_id(skill_id))
        except KeyError as exc:
            self._send_json({"error": {"code": "not_found", "message": str(exc)}}, status=404)
            return
        self._send_json({"status": "approved" if action == "approve" else "rejected", "skill": item})

    def _du_wan(self):
        """整个请求体读出来缓存到 `self._body`。POST 只有 do_POST 一个入口，
        所以读一次就够；没有它，pair-code 这类从不碰 rfile 的端点会在 body
        还躺在收缓冲里时就关连接。

        content-length 畸形按 0 算：读体被挪到入口之后，一个坏头不该让原本
        不读体的端点从「回响应」变成「吐 traceback 再断连接」。
        """
        try:
            n = int(self.headers.get("content-length", "0"))
        except ValueError:
            n = 0
        self._body_shu = n
        self._body = self.rfile.read(n)

    def _read_json(self):
        # 缓存是 do_POST 预读好的那份；do_PUT 是另一条入口，没有预读，回退到
        # 直接从 rfile 读。
        #
        # 真值判据是**声明的 content-length**，不是读到的字节数：声明了 20 字节
        # 却一个字节都没发的请求，读回来是空串。判成 `{}` 的话端点照常执行——
        # /api/settings/delegation 会静默写入 delegation_enabled=False 并回 200。
        # 读到的字节数只能证明「没读着」，证不了「没打算读」。
        if getattr(self, "_body", None) is None:
            length = int(self.headers.get("content-length", "0"))
            return json.loads(self.rfile.read(length).decode("utf-8") if length else "{}")
        return json.loads(self._body.decode("utf-8") if self._body_shu else "{}")

    def _send_json(self, payload, status=200, extra=None):
        """`extra` 是额外响应头（429 的 `Retry-After`）。

        `content-length` 量的是 body 的字节数，与响应头无关，所以它的位置
        挪到 `extra` 之后或之前都一样——放在 `end_headers()` 之前即可。
        """
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)


def run(host="127.0.0.1", port=None):
    """起主服务。**端口可用 LIFEOS_PORT 覆盖**（阶段 7 要在同一台机器上跑两套栈）。"""
    if port is None:
        port = int(os.environ.get("LIFEOS_PORT") or 8765)
    # 设备表与隧道网关（公网形态的入口）。与 runtime.json 同级（spec 8.2）。
    # `LIFEOS_ROOT` 给了别的根就跟着走——两套栈共用 `.lifeos/` 会撞车。
    gen = Path(os.environ.get("LIFEOS_ROOT") or ".") / ".lifeos" / "bridge"
    biao = SheBiao(gen / "devices.json")
    gw = TunnelGw(biao, "127.0.0.1", int(os.environ.get("LIFEOS_GW_PORT") or 8771))
    try:
        gw.qi_dong()
    except OSError as e:
        # **端口被占就报错退出，不静默漂移。** 漂移会让反代配置指向空端口，
        # 症状是「所有用户 502」而本机看起来一切正常（spec 风险 6）。
        raise SystemExit(f"隧道网关起不来（端口 {gw.port}）：{e}") from e
    bridge_admin.zhuang(biao, gw)
    fu = LiAnHTTPServer((host, port), LifeOSRequestHandler)
    print(f"LifeOS API listening on http://{host}:{port}；隧道网关 :{gw.duan_kou()}")
    try:
        fu.serve_forever()
    finally:
        gw.ting_zhi()


if __name__ == "__main__":
    run()
