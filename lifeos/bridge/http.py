"""Bridge 的 HTTP/SSE 传输层（方案 7.2、7.4、4.4）。

**这个文件里最重要的一行是 `ThreadingHTTPServer`。** 用单线程 `HTTPServer` 的话，
一条 SSE 长连接就占死唯一的服务线程，用户的 `POST /permissions/{rid}` 永远排队不被
accept——现象是「每次审批卡都超时自动拒绝，看起来像网络抖动」。方案 12.2 任务 1.8
就是专门验收这一条。

另一个不能错的细节：`protocol_version = "HTTP/1.1"`。默认是 HTTP/1.0，不改的话
SSE 的连接行为会异常。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import threading
import time
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from claude_agent_sdk import PermissionUpdate
from claude_agent_sdk.types import PermissionRuleValue

from lifeos.api.dangqian import he_fa
from lifeos.bridge import auth
from lifeos.bridge import pingju, pipei
from lifeos.bridge.adapters import ZHU_CE_QI, ClaudeCodeAdapter, EchoAdapter
from lifeos.bridge.arbiter import SHEN_HE, ShenQing
from lifeos.bridge.events import DingYue, ZongXian
from lifeos.bridge.localbus import LuDao, tui_mian
from lifeos.bridge.models import MOSHI, AgentSession, lingshou, xianzai
from lifeos.bridge.planner_guard import JuDuan, ShenKa
from lifeos.bridge.session import HuiHua, InvalidTransition
from lifeos.bridge.tuomi import tuomi

XIN_ZHI = 15.0  # 心跳秒数，必须小于云平台单响应时长上限（方案 15.4）
# 3.9 版本门禁基准。**不是照抄方案 2.4 的 2.1.258**——那台机器上装的不是这个版本，
# 拿它当基准会让每个用户的 Bridge 一启动就判为不匹配、被永久强制降成 plan。
# 基准必须是「我们真机验证过的那个版本」：阶段 0 的 spike 与阶段 3 的适配器
# 都跑在 2.1.283 上，所以基准取它。SDK 版本更要紧：can_use_tool 的行为由它定义。
JI_ZUN = "2.1.283"
JI_ZUN_SDK = "0.2.160"
ZUI_DUO_LIU = 8  # 同一来源最多的 SSE 连接数
TI_XIAN = 1 << 20  # 请求体上限 1 MiB，超了就是异常负载
# transcript 单次返回条数上限（阶段 7 域 E）。snapshot 已经不带消息了，
# transcript 就是历史唯一的入口——**它必须有上界**，否则爆点只是从隧道
# 搬到了 HTTP 响应上。默认 50 与 `cc-connect` 的 histLimit 一致；
# 钳到 [1, ZUI_LI] 这层是本项目自己加的。
ZUI_LI = 50

# 配对页。**刻意不引外部资源**：这一页要能在断网的机器上打开。
HTML_PEI = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>LifeOS 设备配对</title></head><body>
<h1>把本机接入 LifeOS</h1>
<p>在 LifeOS 网页的「本地 Agent」页点「添加设备」，把得到的配对码粘到这里。</p>
<form method="post" action="/pair">
  <label>配对码 <input name="code" autocomplete="off" required></label>
  <label>设备名 <input name="label" value="本机"></label>
  <button type="submit">配对</button>
</form>
</body></html>
"""


class YiWu(Exception):
    """协议级错误，直接映射成 HTTP 响应。"""

    def __init__(self, a1: int, a2: str, a3: str) -> None:
        super().__init__(a3)
        self.status = a1
        self.code = a2
        self.message = a3


class BridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "LifeOSBridge/2.0"

    # 由 run.py 注入
    zong: ZongXian
    hua: HuiHua
    shen: ShenKa
    token: str
    shen_qing: ShenQing
    ri: logging.Logger | None = None   # 轮转日志，由 run.py 注入

    def handle(self) -> None:
        self.ri_shi = time.monotonic()   # 一次连接的起点
        # **对端在等响应时断开不是缺陷，是收尾。** Windows 上它表现为
        # `ConnectionAbortedError: [WinError 10053]`，从 `handle_one_request`
        # 的 socket 读里穿出来。`socketserver` 会把任何从 `handle()` 穿出的
        # 异常当「未处理」打一整段 traceback 到 stderr——于是一条正常的关闭
        # 在测试输出里长得像崩溃，而真失败就埋在这一片噪声底下。
        #
        # 这里捕的是「连接没了」这一类，不是 `except Exception`：handler 内部
        # 真正的缺陷仍然要照原样冒出来。
        try:
            super().handle()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def log_request(self, code="-", size="-") -> None:
        """自带耗时。SSE 只记建连与断连，不逐帧记——
        一条长连接跑几小时，逐帧记能把磁盘写满。"""
        if self.ri is None:
            return
        hao = (time.monotonic() - getattr(self, "ri_shi", time.monotonic())) * 1000
        self.ri.info("%s -> %s %.0fms", tuomi(self.requestline, 500), code, hao)

    def log_message(self, *a, **kw) -> None:
        """写轮转日志文件。**不写请求体**——请求体里有 toolInput 全文。

        请求行里的 query string 带 token，必须先脱敏再落盘。
        """
        if self.ri is None:
            return
        try:
            self.ri.info("%s", tuomi(" ".join(str(x) for x in a), 2000))
        except Exception:  # noqa: BLE001
            pass  # 日志失败绝不影响请求本身

    # ---------- 基础工具 ----------
    def _json(self, a1: dict, a2: int = 200) -> None:
        shu = json.dumps(a1, ensure_ascii=False).encode("utf-8")
        self.send_response(a2)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(shu)))
        self.end_headers()
        self.wfile.write(shu)

    def _cuo(self, a1: int, a2: str, a3: str) -> None:
        self._json({"error": {"code": a2, "message": a3}}, a1)

    def _chang(self) -> int:
        """content-length 长度。畸形按 0 算：读体挪到入口之后，一个坏头不该让
        原本不读体的端点从「回响应」变成「吐 traceback 再断连接」。"""
        try:
            return int(self.headers.get("content-length", "0"))
        except ValueError:
            return 0

    def _du_wan(self) -> None:
        """整个请求体读出来缓存到 `self._body`。

        POST 只有 do_POST 一个入口，所以读一次就够。没有它，_guan_bi / _zhong_duan
        / _ting_zhong 这三个从不碰 rfile 的 handler 留下的 body 字节会堆在收缓冲
        里：HTTP/1.1 keep-alive 下，服务端接着把它当下一个请求行读，回 400 再关
        连接，客户端那边就是 10053/10054。

        **超限的不读、不缓存、也不在这里抛 413。** 读体挪到入口之后，`_du_json`
        里那道 1 MiB 上限就排到了认证后面，中间这段是无上限的
        `rfile.read`：未认证的客户端在认证之前就能让服务端按它声明的大小分配
        内存（ThreadingHTTPServer 每连接一线程），1 MiB 也从内存上限退化成事后
        提醒。让 `_body` **压根不被缓存**，每条路径就自动落回修复前的老行为：
        未认证 → `_shou_quan` 的 401；已认证 → `_du_json` 的 413（它读之前就判，
        不读体）；`/pair` → `_pei_dui` 的 `_ti_zi()` 回退分支自己读（修复前就是
        它自己无上限读）。

        **这里抛 413 是错的**，别"补"上：那样未认证的超限请求从 401 变成 413，
        认证闸门被抢在后面。`_ti_zi()` 只有一个读 `self._body` 的地方，两个调用方
        都在它后面，所以「不缓存」就够，不需要额外分支。
        """
        n = self._chang()
        if n > TI_XIAN:
            return
        self._body = self.rfile.read(n)

    def _ti_zi(self) -> bytes:
        """请求体字节。入口已预读就用缓存；do_GET 是另一条入口，回退直接读 rfile。"""
        raw = getattr(self, "_body", None)
        return raw if raw is not None else self.rfile.read(self._chang())

    def _du_json(self) -> dict:
        chang = int(self.headers.get("content-length", "0"))
        if chang > TI_XIAN:  # 入口的 _du_wan 已经拦过一道，这里兜住 do_GET 回退分支
            raise YiWu(413, "too_large", "请求体过大")
        if not chang:
            return {}
        try:
            return json.loads(self._ti_zi().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise YiWu(400, "invalid_request", f"请求体不是合法 JSON：{e}") from e

    def _shou_quan(self, a1: dict) -> None:
        """token 必查；Origin 在有 Origin 时必查。"""
        try:
            auth.duanren(self.token, a1.get("token", [None])[0] or self.headers.get("x-bridge-token"))
            auth.yuanbai(self.headers.get("origin"))
        except auth.WeiQuan as e:
            raise YiWu(401 if e.code == "unauthorized" else 403, e.code, e.message) from e

    # ---------- 路由 ----------
    def do_GET(self):
        jie = urlparse(self.path)
        try:
            if jie.path == "/health":
                return self._health()
            if jie.path == "/pair":
                return self._pair()
            if jie.path == "/agents":
                self._shou_quan(parse_qs(jie.query))
                return self._agents()
            if jie.path == "/stream":
                return self._liu(parse_qs(jie.query))
            if jie.path.startswith("/sessions/") and jie.path.endswith("/transcript"):
                self._shou_quan(parse_qs(jie.query))
                return self._yuan_wen(jie.path, parse_qs(jie.query))
            raise YiWu(404, "not_found", f"没有这个端点：{jie.path}")
        except YiWu as e:
            self._cuo(e.status, e.code, e.message)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # noqa: BLE001
            self._cuo(500, "internal", f"{type(e).__name__}: {e}")

    def do_POST(self):
        jie = urlparse(self.path)
        try:
            # 任何分支与任何闸门之前把请求体读干净（见 _du_wan）。
            self._du_wan()
            # /pair 的 POST 必须在 _shou_quan 之前：用户是从本机浏览器直接打开
            # 配对页的，浏览器手里没有 Bridge token（1.3 铁律：token 绝不进浏览器）。
            # 这条路径的凭据是配对码本身 + 仅本机可达。
            if urlparse(self.path).path.rstrip("/") == "/pair":
                return self._pei_dui()
            self._shou_quan(parse_qs(jie.query))
            path = jie.path.rstrip("/")
            bu = path.strip("/").split("/")
            if path == "/sessions":
                return self._jian_hui(bu)
            if path == "/events":
                return self._chumo()
            if len(bu) == 3 and bu[0] == "sessions" and bu[2] == "messages":
                return self._fa_xiao(bu[1])
            if len(bu) == 3 and bu[0] == "sessions" and bu[2] == "interrupt":
                return self._zhong_duan(bu[1])
            if len(bu) == 3 and bu[0] == "sessions" and bu[2] == "close":
                return self._guan_bi(bu[1])
            if len(bu) == 3 and bu[0] == "sessions" and bu[2] == "mode":
                return self._gai_moshi(bu[1])
            if path == "/bridge/stop":
                return self._ting_zhong()
            if len(bu) == 2 and bu[0] == "permissions":
                return self._jue_ding(bu[1])
            if len(bu) == 2 and bu[0] == "questions":
                return self._da_wen(bu[1])
            raise YiWu(404, "not_found", f"没有这个端点：{jie.path}")
        except YiWu as e:
            self._cuo(e.status, e.code, e.message)
        except JuDuan as e:
            self._cuo(400, e.code, e.message)
        except InvalidTransition as e:
            # 会话数超限（9.4）走这条。**必须排在裸 `except Exception` 之前**，
            # 否则它被翻成 500，前端看到「服务器内部错误」而不是「会话太多了，
            # 先关一个」——用户完全不知道该做什么。
            self._cuo(409, "conflict", str(e))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # noqa: BLE001
            self._cuo(500, "internal", f"{type(e).__name__}: {e}")

    # ---------- 端点实现 ----------
    def _health(self):
        self._json({
            "ok": True,
            "pid": os.getpid(),
            "uptimeSec": round(time.monotonic() - self.server.kaishi_shi, 1),
            "version": "2.0",
            "instanceId": self.zong.ji,
        })

    def _pair(self):
        """配对页。**只允许本机访问** —— 这一页是「用户对本机 Bridge 的信任授予」
        （5.3 第 2 步），远程能打开它就等于任何人都能往这台机器挂设备。"""
        host = self.client_address[0] if self.client_address else ""
        if host not in ("127.0.0.1", "::1"):
            raise YiWu(403, "forbidden", "配对页面仅限本机访问")
        shu = HTML_PEI.encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(shu)))
        self.end_headers()
        self.wfile.write(shu)

    def _pei_dui(self):
        """配对页的表单提交。同样只允许本机。"""
        host = self.client_address[0] if self.client_address else ""
        if host not in ("127.0.0.1", "::1"):
            raise YiWu(403, "forbidden", "配对页面仅限本机访问")
        # 入口已经读干净了，这里再读 rfile 只会拿到空串。
        xing = parse_qs(self._ti_zi().decode("utf-8"))
        ma = (xing.get("code") or [""])[0]
        biao = (xing.get("label") or ["本机"])[0]
        try:
            r = pipei.pai(ma, biao, self.server.yun_wen, self.zong.ji)
        except pipei.PeiDuiShiBai as e:
            # 这两段拼的是**主服务返回的字符串**。LIFEOS_MAIN_URL 指向远端时它就是
            # 远端可控的内容，不转义等于在 127.0.0.1 源上执行任意脚本。
            wen = escape(e.message)
            shu = (f"<p>配对失败：{wen}</p><p><a href='/pair'>重试</a></p>").encode("utf-8")
            self.send_response(400)
        else:
            # 页面回「配对成功」但**不说要重启**，用户会立刻建会话、用旧 uid
            # （通常是 `local`）的空库、被迫重新登录——而这在页面上完全看不出来。
            # `fu.env` 在 `run.zhen_ben` 启动时算好就固定了（`run.py:299`），
            # 中途换目录等于让跑着的会话登录态凭空消失，所以只能重启。
            shu = ("<p>配对成功。设备 id：" + escape(r["deviceId"]) +
                   "</p><p><b>需要重启 LifeOS Bridge</b>，凭据隔离才会对这个账号"
                   "完全生效（当前进程仍在用配对前的本地目录，用户要重新登录一次）。"
                   "</p><p>可以关掉这一页了。回到 LifeOS 网页刷新即可。</p>").encode("utf-8")
            self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(shu)))
        self.end_headers()
        self.wfile.write(shu)

    def _agents(self):
        """发现本地可用 Agent。3.9 的版本门禁信息也在这里给前端。

        **`credentialsReady` 与 `available` 分开**（spec 11.2、承重 3）：
        `available` 回答的是「本机装没装 claude CLI」（`tanjian()` 的原样返回值），
        `credentialsReady` 回答的是「这个 uid 的凭据目录建出来了吗」。
        混进 `available` 会让前端把「建不出凭据目录」显示成「没装 claude」——
        两者的处置完全不同（装软件 vs 改磁盘权限），给错提示比不给提示更糟。

        **每次请求现场重跑一次 `huan_jing`**（阶段 6 必修 3）。不重试的话这个
        标志是**启动那一刻的快照**，缺陷双向：启动时磁盘满 → 用户腾完空间、
        Bridge 没重启，告警永远挂着；反过来运行中目录被删 → 标志仍为 true，
        界面一声不吭，用户照样落到空库、重新登录——正是要消灭的症状。
        不会掩盖真问题：真有问题时它重试一百遍还是 false。

        **代价可以忽略**：前端只在挂载时探测一次 + 「重新探测」按钮，没有轮询
        （`AgentsSection` 里唯一的 `setInterval` 是那行 1 秒的倒计时）；而这个
        端点本来每次就起一个 `claude --version` 子进程（`tanjian()`），多一个
        幂等的 `mkdir(exist_ok=True)` 与零到一次 icacls/chmod 不改变量级。
        """
        pingju.huan_jing(self.server.yong_hu)
        out = []
        for agentId, cls in ZHU_CE_QI.items():
            if agentId == "echo":
                continue  # 测试用适配器不对外暴露
            kai = time.perf_counter()
            try:
                xian = asyncio.run(cls().tanjian())
            except Exception as e:  # noqa: BLE001
                xian = {"available": False, "version": None, "sdkVersion": None,
                        "error": f"{type(e).__name__}: {e}"}
            probe_ms = int((time.perf_counter() - kai) * 1000)
            xian["agentId"] = agentId
            xian["label"] = cls.label
            xian["canUseTool"] = cls.fangquan()
            xian["canAskQuestion"] = cls.wenti2()
            declared_modes = getattr(cls, "MOSHI_ZI", frozenset())
            xian["moshi"] = sorted((declared_modes or MOSHI) & MOSHI)
            xian["yi_ci_xing"] = bool(getattr(cls, "yi_ci_xing", False))
            xian["xu_pei_zhuang"] = bool(getattr(cls, "xu_pei_zhuang", False))
            xian["ce_shi"] = {
                "ok": bool(xian.get("available")),
                "probeMs": probe_ms,
                "shuoming": (
                    f"已确认 {cls.label} 可用（{probe_ms} 毫秒）"
                    if xian.get("available")
                    else str(xian.get("error") or f"{cls.label} 探测没通过")
                ),
            }
            out.append(xian)
        self._json({"agents": out, "suggestedDirs": [str(self.shen.gen)],
                    "credentialsReady": pingju.JIAN_BING_CHENG_GONG,
                    "versionGate": self.server.ren_men()})

    def _jian_hui(self, a1: list[str]):
        body = self._du_json()
        agent_id = body.get("agentId", "claude-code")
        cls = ZHU_CE_QI.get(agent_id)
        if cls is None:
            raise YiWu(400, "agent_unavailable", "没有这个 agentId")
        if not cls.fangquan() and body.get("acknowledgeNoApproval") is not True:
            raise YiWu(
                400,
                "agent_unavailable",
                f"{cls.label} 没有 LifeOS 可接管的审批回路，指令会直接在本机执行。"
                "确认接受后，请显式带 acknowledgeNoApproval=true 重试。",
            )
        mode = self.shen.fang(body.get("permissionMode"), cls)
        # This baseline covers Claude CLI + claude-agent-sdk only. It must not
        # constrain unrelated harnesses such as Codex, Pi, Hermes, or Kimi.
        if cls.agentId == "claude-code" and self.server.ren_men()["mismatch"]:
            # 9.3 版本门禁：CLI 版本对不上基准时强制 plan，直到用户确认。
            # 强制 plan 而不是拒绝——会话还能建，用户看得到警告，Agent 只能读不能改。
            if "plan" not in (getattr(cls, "MOSHI_ZI", frozenset()) or MOSHI):
                raise YiWu(409, "reset_required", "版本门禁要求只读模式，但该 Agent 不支持 plan")
            mode = "plan"
        cwd = self.shen.cwd(body.get("cwd", ""))                # 闸门 3
        key = body.get("clientIdempotencyKey")
        if key:
            # **幂等键按 uid 分命名空间。** 它是客户端给的自由字符串，
            # 不分的话 B 拿 A 的键撞上来会命中 A 的会话，把 A 的 `cwd`/`title`
            # 整个吐给 B。命名空间一分，同人仍然幂等、异人各建各的。
            old = self.server.jian_quan.get(f"{self._yong()}|{key}")
            if old and self.hua.du(old):
                # 走 `_dui_hui` 而不是自己 `to_dict()`：归属校验只有那一个入口。
                return self._json({"session": self._dui_hui(old).to_dict()})
        hui = AgentSession(
            sessionId=f"s-{lingshou()}",
            agentId=agent_id,
            agentLabel=cls.label,
            cwd=cwd,
            permissionMode=mode,
            effectiveMode=mode,
            title=body.get("title", ""),
            planId=body.get("planId"),
            traceId=body.get("traceId"),
            ownerId=self._yong(),
        )
        self.hua.jian(hui)
        if key:
            self.server.jian_quan[f"{self._yong()}|{key}"] = hui.sessionId
        self.zong.fa("session_added", hui.sessionId, session=hui.to_dict())
        if self.server.lu_dao is not None:
            self.server.lu_dao.jian_hui(hui.sessionId, {
                "sessionId": hui.sessionId, "agentId": hui.agentId,
                "cwd": hui.cwd, "permissionMode": hui.effectiveMode,
            })
        self._json({"session": hui.to_dict()}, 201)

    def _fa_xiao(self, a1: str):
        self._dui_hui(a1)
        body = self._du_json()
        wen = body.get("text")
        zhi = body.get("instructions") or ([wen] if wen else [])
        if not zhi:
            raise YiWu(400, "invalid_request", "text 与 instructions 至少给一个")
        for t in zhi:
            if len(str(t)) > 4000:  # R-V1：单条指令 4000 字符上限
                raise YiWu(400, "too_large", "单条指令超过 4000 字符，请拆分")
        xiao = self.hua.tian_jia(a1, "user", "text", text=chr(10).join(str(t) for t in zhi))
        self.server.ren_wu[a1] = threading.Thread(
            target=self._pao, args=(a1, zhi), daemon=True
        )
        self.server.ren_wu[a1].start()
        self._json({"messageId": xiao.messageId, "seq": xiao.seq}, 202)

    def _pao(self, a1: str, a2: list):
        """在线程里跑 asyncio 回合编排。

        适配器必须在这里创建而不是在 HTTP 线程里：`kaishi()` 是 async，
        它要 spawn 子进程并持有 event loop。提前建好会让 `interrupt()`
        在一个不属于它的 loop 上执行。
        """
        async def zhu():
            ad = await self.server.xin_jian(a1)
            ad.cheng = self.server._cheng_bu(a1)
            self.server.shi_ying[a1] = ad
            jie = await self.hua.paichu(a1, [str(t) for t in a2], ad)
            if self.server.lu_dao is not None:
                # 3.8：整批结束才发 ended。中断与失败各走各的 kind，
                # 主服务据此决定要不要触发下一轮规划（只规划，不自动下发）。
                if jie.get("ok"):
                    self.server.lu_dao.jie_shu(a1, {
                        "batchDone": jie.get("batchDone", 0),
                        "batchTotal": jie.get("batchTotal", 0),
                    })
                else:
                    self.server.lu_dao.shi_bai(a1, {"reason": jie.get("reason", "")})

        try:
            asyncio.run(zhu())
        except InvalidTransition as e:
            self.zong.fa("error", a1, code="invalid_transition", message=str(e), recoverable=False)
        except asyncio.CancelledError:
            pass  # 用户主动中断，状态已在 paichu 里改过
        except Exception as e:  # noqa: BLE001
            self.zong.fa("error", a1, code="internal", message=f"{type(e).__name__}: {e}", recoverable=False)
            if self.server.lu_dao is not None:
                # detail 白名单只允许这三个键；想带原因就走日志，不走这个事件
                self.server.lu_dao.beng_kui(a1, {"sessionId": a1,
                                                 "exitCode": None, "signal": None})

    def _zhong_duan(self, a1: str):
        self._dui_hui(a1)
        # 顺序不能反：先标记停止，再收口挂起项。
        # 收口会让挂起的 future 立刻 resolve，Agent 线程随即恢复并检查停止标志——
        # 如果标志还没设上，它会把剩下的指令全跑完。
        self.hua.zhong_duan(a1)
        shou = self.server.shen_qing.zhong_duan(a1)
        ad = self.server.shi_ying.get(a1)
        if ad is not None:
            # 中断信号发不出去也要返回 200：挂起项已经收口了，用户的目的已达成。
            # 报 500 只会让前端以为「没中断成功」，而剩下的指令确实不会再跑。
            try:
                self.server.duo_cuo(a1, ad.zhong_duan, 5.0)
            except Exception:  # noqa: BLE001
                pass
        self._json({"ok": True, "resolved": shou})

    def _guan_bi(self, a1: str):
        self._dui_hui(a1)
        self.server._guan_yong(a1)
        self._json({"ok": True})

    def _gai_moshi(self, a1: str):
        """切换权限模式（3.5）。闸门 1 走的是同一个校验函数，不许绕过。"""
        body = self._du_json()
        mo = self.shen.fang(body.get("permissionMode"))   # 闸门 1，非法 → 400
        hui = self._dui_hui(a1)
        cls = ZHU_CE_QI.get(hui.agentId)
        mo = self.shen.fang(mo, cls)
        # The global version gate is specifically a Claude CLI/SDK contract.
        if hui.agentId == "claude-code" and self.server.ren_men()["mismatch"]:
            # 版本对不上时任何模式都不能给，强制 plan（9.3 版本门禁）
            if "plan" not in (getattr(cls, "MOSHI_ZI", frozenset()) or MOSHI):
                raise YiWu(409, "reset_required", "版本门禁要求只读模式，但该 Agent 不支持 plan")
            mo = "plan"
        ad = self.server.shi_ying.get(a1)
        if ad is None or not hasattr(ad, "gai_moshi"):
            self._json({"ok": False, "reason": "会话尚未启动 Agent，无法切换模式"}, 409)
            return
        try:
            self.server.duo_cuo(a1, lambda: ad.gai_moshi(mo), 10.0)
        except Exception as e:  # noqa: BLE001
            self._cuo(502, "internal", f"切换失败：{type(e).__name__}: {e}")
            return
        hui.permissionMode = mo
        hui.effectiveMode = mo
        hui.updatedAt = xianzai()
        self.zong.fa("state", a1, state=hui.state, lastEvent="mode_changed",
                     permissionMode=mo, effectiveMode=mo)
        self._json({"ok": True, "permissionMode": mo, "effectiveMode": mo})

    def _ting_zhong(self):
        """9.4 两段式关闭的第一段：Bridge 自己收干净再退出。"""
        n = self.server.guan_biao()
        self._json({"ok": True, "closed": n})
        # 顺序要紧：先把响应交出去，再让 serve_forever 返回。反过来写的话，
        # 进程会在 handle_one_request 把 wfile flush 出去之前退出，
        # 调用方看到的是超时——而 Bridge 其实已经停了（「点了停止却报错」）。
        threading.Thread(target=self.server.shutdown, daemon=True).start()
    def _jue_ding(self, a1: str):
        body = self._du_json()
        fen = body.get("decision")
        if fen not in ("allow", "deny"):
            raise YiWu(400, "invalid_request", "decision 必须是 allow 或 deny")
        q = self.server.shen_qing
        d = q._pending.get(a1)
        if d is None:
            # 区分「已收口过」与「从来不存在」：前者必须 409。
            # 返回 200 会让前端把卡片关掉，用户以为批准了、Agent 实际收到的是拒绝——
            # 安全性上是 deny（方向对），但 UI 在撒谎。
            guo = [x for x in q.jue_chao if x.get("requestId") == a1]
            if guo:
                # **已收口记录也要做归属校验。** `decision` 那条带 `sessionId`，
                # 据此判：跳过它的话 B 猜对一个 A 已经批过的 requestId 会拿到 409，
                # 于是「这个 id 存在」被泄露出去（spec 10.3）。
                # `deny_baseline` / `dropped_updates` 这两种旁流水不带 sessionId，
                # 查不到就照旧给 409——它们后面一定跟着带 sessionId 的 `decision`。
                zhu = next((x.get("sessionId") for x in guo if x.get("sessionId")), None)
                if zhu is not None:
                    self._dui_hui(zhu)
                raise YiWu(409, "already_resolved", "该审批请求已被收口")
            raise YiWu(404, "not_found", f"没有这个审批请求：{a1}")
        # 审批挂在会话上，归属经 `DaiJue.sessionId` 回溯——收口仍在 `_dui_hui` 一处。
        self._dui_hui(d.sessionId)
        r = q.shou(
            d,
            "user_allow" if fen == "allow" else "user_deny",
            a3=str(body.get("message") or ""),
            a4=body.get("updatedInput"),
            a5=self._jie_guize(body.get("updatedPermissions")),
        )
        if r["status"] == "input_mismatch":
            self._json({"error": {"code": "input_mismatch",
                                   "message": "提交的 updatedInput 与原始输入不一致",
                                   "expected": r["expected"], "received": r["received"]}}, 400)
            return
        self._json({"ok": True, "decision": r["decision"],
                    "autoDecided": r["decision"] != "user_allow" and r["decision"] != "user_deny",
                    "autoReason": r["autoReason"]})

    @staticmethod
    def _jie_guize(a1: Any) -> list:
        """把 JSON 的 updatedPermissions 解析成 SDK 的 PermissionUpdate。

        destination 不在这里过滤——过滤发生在收口函数里（8.2.3），
        否则「哪些被丢弃」这条审计信息就丢了。
        """
        if not a1:
            return []
        out = []
        for u in a1:
            if not isinstance(u, dict) or "type" not in u:
                raise YiWu(400, "invalid_request", "updatedPermissions 元素缺少 type")
            gui = []
            for r in u.get("rules") or []:
                gui.append(PermissionRuleValue(tool_name=r.get("toolName", ""),
                                               rule_content=r.get("ruleContent")))
            out.append(PermissionUpdate(
                type=u["type"], rules=gui or None,
                behavior=u.get("behavior"), mode=u.get("mode"),
                directories=u.get("directories"), destination=u.get("destination"),
            ))
        return out

    def _da_wen(self, a1: str):
        body = self._du_json()
        da = body.get("answers")
        if not isinstance(da, list) or not da:
            raise YiWu(400, "invalid_request", "answers 必须是非空数组")
        q = self.server.shen_qing
        d = q._wenti.get(a1)
        if d is None:
            # 与 `_jue_ding` 同口径：已收口 → 409，从来不存在 → 404。
            # **原来一律 409**：拿一个错的 questionId 会被告知「已被收口」，
            # 而用户从来没见过这个提问——提示语把人引向错误结论。
            guo = [x for x in q.wen_chao if x.get("questionId") == a1]
            if guo:
                # 已收口的提问也要做归属校验，理由同 `_jue_ding`：
                # 不查就等于告诉 B「这个 id 存在，只是答过了」（spec 10.3）。
                self._dui_hui(guo[-1]["sessionId"])
                raise YiWu(409, "already_resolved", "该提问已被收口")
            raise YiWu(404, "not_found", f"没有这个提问：{a1}")
        # 提问挂在会话上，归属经 `DaiWen.sessionId` 回溯——收口仍在 `_dui_hui` 一处。
        self._dui_hui(d.sessionId)
        r = q.da_wen(d, da)
        self._json({"ok": True, "state": r.get("state")})

    def _yuan_wen(self, a1: str, a2: dict):
        sid = unquote(a1.strip("/").split("/")[1])
        # **必须走 `_dui_hui`。** 原来自己写 `hua.du(sid) is None` 只查了存在性，
        # 于是一条跨用户读全文的路径绕过了归属过滤——而 transcript 是会话里
        # 最敏感的东西（整轮对话）。
        self._dui_hui(sid)
        from1 = self._zheng_shu(a2, "from")
        before1 = self._zheng_shu(a2, "before") or None
        # **limit 非法值按默认处理，不回 400。** 这是补拉通道：前端网络抖动
        # 重试时不该整个失败。游标（from / before）不同——那是调用方算错了，
        # 该 400 就 400。
        try:
            shu = int((a2.get("limit") or ["50"])[0])
        except ValueError:
            shu = ZUI_LI
        if shu <= 0:  # ≤0 与非整数同处置：按默认值走，不回 400
            shu = ZUI_LI
        # 钳到 [1, ZUI_LI]。**这层钳制是本项目自己加的**（cc-connect 的
        # histLimit 传正整数就照用），漏掉它等于把 snapshot 的爆点原样搬到
        # HTTP 响应上：snapshot 有界了，这条没有。
        shu = min(shu, ZUI_LI)
        if self.zong.chao_le(from1):
            # 越界：Bridge 重启过，旧游标作废。静默返回空数组会让前端以为已是最新，
            # 界面一片空白，而 Agent 那边还在继续跑。
            raise YiWu(409, "reset_required", "游标越界，需要重置")
        lie = self.hua.juan_biao(sid, from1, shu, before1)
        # **游标由服务端给，前端不许自己猜。** nextFrom 是末条 xuhao（空批次回
        # 请求的 from，别让增量追赶原地打转）；prevBefore 是首条 xuhao，向上翻时
        # 原样回传。
        tail = lie[-1].xuhao if lie else from1
        head = lie[0].xuhao if lie else None
        # **hasMore = 翻页方向上还有没给的。** 方向由调用目的决定：增量追赶
        # （给了 from、没给 before）取的是最早 N 条，缺的那些在**后面**，下一轮
        # 拿 nextFrom 接着追；其余（首屏、向上翻）取的是末尾 N 条，缺的都在
        # **前面**，前端滚到顶部时拿 prevBefore 往上翻。
        # 分不清这两种方向的话，向上翻到顶了 hasMore 仍报 true，前端就一直发
        # 空请求；反过来增量永远追不干净。
        if from1 > 0 and before1 is None:
            more = bool(self.hua.juan_biao(sid, tail, 1))
        else:
            more = head is not None and bool(self.hua.juan_biao(sid, 0, 1, head))
        self._json({"messages": [m.to_dict() for m in lie],
                    "nextFrom": tail, "prevBefore": head, "hasMore": more})

    def _zheng_shu(self, a1: dict, a2: str) -> int:
        """取一个整数查询参数，缺省 0。非整数回 400。"""
        zhi = (a1.get(a2) or ["0"])[0]
        try:
            return int(zhi)
        except ValueError as e:
            raise YiWu(400, "invalid_request", f"{a2} 必须是整数") from e

    def _chumo(self):
        """入站事件（阶段 3 决策回路用）。只登记不广播——
        广播回去会让订阅者收到自己刚发的事件，形成回环。"""
        body = self._du_json()
        if "kind" not in body:
            raise YiWu(400, "invalid_request", "缺少 kind")
        self.server.shi_jian_ji.append({**body, "recvAt": xianzai()})
        self._json({"ok": True})

    def _yong(self) -> str:
        """当前请求所属 userId。**归属校验的唯一取值口。**

        接入登录后只改这一个方法：把它换成从 cookie / session 读 uid，
        其余调用点一行不动（`lifeos/api/dangqian.py` 顶部的占位方案）。

        **不能改用 `dangqian.dang_qian_yong_hu()`**：那读的是 `LIFEOS_USER`
        环境变量，而生产里没有任何地方设它（配对的 uid 走 `runtime.json`），
        拿它当身份会去认一个与真实凭据无关的用户。见 `BridgeServer.yong_hu`
        上的同一段注释。

        `he_fa` 在这里收口：今天 uid 来自 `runtime.json`（`run.py` 已经拿它
        建过凭据目录，那时过了一遍白名单），接入登录后它来自 cookie——那是
        外部输入，校验必须在接入**之前**就位（spec 11.4、风险 8）。多校验一遍
        是幂等的，漏校验不是。
        """
        return he_fa(self.server.yong_hu)

    def _dui_hui(self, a1: str) -> AgentSession:
        """取会话并校验归属。**会话资源的唯一入口**——所有按 sid 取资源的
        路径都必须走这里，自己写一遍 `hua.du` 就是一条跨用户读路径。

        不存在与不属于当前用户**回同一个 404**（spec 10.3）：分开回 403 会
        泄露「这个 sid 是存在的」。对调用方来说两者本来就一样——他都拿不到。
        """
        hui = self.hua.du(a1)
        if hui is None or hui.ownerId != self._yong():
            raise YiWu(404, "not_found", f"没有这个会话：{a1}")
        return hui

    # ---------- SSE ----------
    def _liu(self, a1: dict):
        """建立 SSE 连接。响应头必须逐条写对，否则浏览器不触发 onmessage。"""
        self._shou_quan(a1)  # 认证必须在发响应头之前，否则无 token 也能挂上长连接
        last = a1.get("lastEventId", [None])[0]
        try:
            last_n = int(last) if last is not None else None
        except ValueError:
            raise YiWu(400, "invalid_request", "lastEventId 必须是整数") from None

        # **来源从请求头取，不写死 `"local"`。** 7.2.5 要的是「同一 userId 最多
        # 8 条 SSE」，写死 local 时它退化成「整台机器一共 8 条」：真公网形态下
        # 会误踢别的 userId 的连接，本机形态下又数不到上限。
        #
        # **按 userId 而不是按连接 id 计**，理由同上：用连接 id 的话每条连接的
        # 来源都独一无二，`shu_ling` 永远返回 1，这条限制形同虚设。
        # `or "local"` **数得到上限，只是桶名不同**——`events.shu_ling` 显式接受
        # `None`，去掉它所有本机连接的 `yuan` 会一致变成 `None`，照样落同一个桶。
        # 留着的实际理由只有日志可读：踢连接时打出来的来源是 `"local"` 而不是 `None`。
        #
        # **`or "local"` 的语义定死在这里，别当漏洞改。** 隧道形态下
        # `tunnel.py:374` 传的是 `userId`（正确）；本机形态不带这个头，于是
        # 所有本机连接挤在 `"local"` 这一个来源上。这是**可接受的**——本机本来
        # 就是单用户开发形态。
        lai = self.headers.get("x-lifeos-source") or "local"
        if self.zong.shu_ling(lai) >= ZUI_DUO_LIU:
            # 后连踢先连：老连接会走重连路径把状态补齐，踢掉它比拖住新的安全
            for d in self.zong.lie_ding():
                if d.yuan == lai:
                    d.guan = True
                    break
            else:
                raise YiWu(429, "rate_limited", "同一来源的 SSE 连接数已达上限")

        ding = self.zong.dingyue(f"d-{lingshou()}", lai)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream; charset=utf-8")
        self.send_header("cache-control", "no-cache, no-transform")
        self.send_header("x-accel-buffering", "no")  # 防反代缓冲
        # 帧长未知，必须声明 chunked。少了这一行，客户端会按「读到连接关闭为止」
        # 解析，浏览器的 EventSource 行为就不对了。
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()
        self.wfile.flush()

        # 补发（先 snapshot 再补发批次）交给写线程去写，Handler 线程一个字都不写：
        # wfile 不保证线程安全，两个线程各写半截的话，chunked 的长度前缀与载荷
        # 会交错，客户端从那一处起整个流错位。
        xie = threading.Thread(target=self._xie, args=(ding, self.zong.duibu(last_n)),
                               daemon=True)
        xie.start()
        try:
            while not ding.guan and xie.is_alive():
                xie.join(0.2)
        except (KeyboardInterrupt, BrokenPipeError, ConnectionResetError):
            pass
        finally:
            ding.guan = True
            self.zong.tuixie(ding)
        self.close_connection = True

    def _xie(self, a1: DingYue, a2: list[dict[str, Any]] | None = None):
        """专属写线程。wfile 只由本线程碰——socket 写不保证线程安全（方案 4.4）。

        a2 是补发批次（先 snapshot 再补发），第一件事就把它写出去。

        **队列里的帧必须真写出去。** 只 `get` 不写，订阅者就只拿得到连接那一刻的
        快照，此后所有实时帧被静默吞掉——症状是「界面永远停在打开页面时的样子」，
        而服务端一切正常。
        """
        for zhen in a2 or []:
            self._xie_zheng(a1, zhen)
            if a1.guan:
                return
        last = time.monotonic()
        try:
            while not a1.guan:
                try:
                    zhen = a1.que.get(timeout=0.5)
                    last = time.monotonic()
                except queue.Empty:
                    zhen = None
                if a1.chao:
                    # 关键帧投递失败：主动断开，让它走重连 + snapshot
                    break
                if zhen is not None:
                    self._xie_zheng(a1, zhen)
                if time.monotonic() - last >= XIN_ZHI:
                    # chunked 的长度前缀必须按**实际载荷字节数**算。原来这里写死
                    # 了 "1a"（26），而 ": ping\n\n" 只有 8 字节——浏览器会接着
                    # 从下一帧的头部多啃 18 字节，SSE 流从此错位，症状是间歇出现
                    # 一条「收到无法解析的帧」，而且丢的是要紧的帧。
                    tiao = b": ping\n\n"
                    self.wfile.write(f"{len(tiao):X}\r\n".encode("ascii") + tiao + b"\r\n")
                    self.wfile.flush()
                    last = time.monotonic()
        except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
            pass
        finally:
            a1.guan = True

    def _xie_zheng(self, a1: DingYue, a2: dict):
        """把一帧写进 SSE 流。event: 字段显式写，前端才能按类型 addEventListener。"""
        try:
            shu = json.dumps(a2, ensure_ascii=False).encode("utf-8")
            zhen = f"id: {a2['streamSeq']}\nevent: {a2['type']}\ndata: {shu.decode('utf-8')}\n\n".encode("utf-8")
            self.wfile.write(f"{len(zhen):X}\r\n".encode("ascii") + zhen + b"\r\n")
            self.wfile.flush()
            a1.last = a2["streamSeq"]
        except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
            a1.guan = True
        except KeyError:
            pass


class BridgeServer(ThreadingHTTPServer):
    """线程化服务器。见模块顶部——这是整个文件最容易漏的一行。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, a1, a2: ZongXian, a3: HuiHua, a4: ShenKa, a5: str,
                 a6: Any = None) -> None:
        self.zong = a2
        self.hua = a3
        self.shen = a4
        self.token = a5
        self.shen_qing = ShenQing(a3, a2, a4, SHEN_HE, a6)
        self.shi_ying: dict[str, Any] = {}   # sid -> adapter
        self.huan_qu_dic: dict[str, Any] = {}  # sid -> 适配器所在的 event loop
        self.ren_wu: dict[str, threading.Thread] = {}
        self.jian_quan: dict[str, str] = {}  # "<uid>|<clientIdempotencyKey>" -> sid
        self.shi_jian_ji: list[dict] = []     # POST /events 的入站登记
        self.kaishi_shi = time.monotonic()
        self.pids: dict[int, str] = {}        # pid -> sessionId（3.6 进程回收）
        self.ji_pids: Any = None              # 持久化回调，由 run.py 注入
        self.lu_dao: LuDao | None = None      # 决策回路出站（3.8），由 run.py 注入
        # 凭据隔离（spec 11.2）。由 run.py 在 zhen_ben 里算好注入——它要读
        # runtime.json 的 userId，那是 run.py 的活。默认 None = 不隔离。
        self.env: dict[str, str] | None = None
        # 同一个 uid 原样留一份，供 `/agents` 现场重试凭据目录（见 `_agents`）。
        # **不能改用 `dangqian.dang_qian_yong_hu()`**：那读的是 `LIFEOS_USER`
        # 环境变量，而生产里没有任何地方设它（配对的 uid 走 runtime.json），
        # 拿它重试会去建一个 `local-` 目录——给用户报一个与真实凭据无关的状态。
        self.yong_hu: str = "local"
        # 3.9 版本门禁。基准取真机验证过的版本，见模块顶部 JI_ZUN 的注释。
        self.cli_ban_ben: str | None = None
        self.sdk_ban_ben: str | None = None
        self.ji_zun_ban_ben: str = JI_ZUN
        self.ji_zun_sdk: str = JI_ZUN_SDK
        # 8.7 第二、三层的执行者
        a3.ting_shi = self._ting_zhi
        a3.guan_yong = self._guan_yong
        a3.kai_dog()
        # handler 通过类属性访问这些单例，必须在起服务前注入
        BridgeHandler.zong = a2
        BridgeHandler.hua = a3
        BridgeHandler.shen = a4
        BridgeHandler.token = a5
        BridgeHandler.shen_qing = self.shen_qing
        super().__init__(a1, BridgeHandler)

    # ---- 3.9 版本门禁 ----
    def ren_men(self) -> dict[str, Any]:
        """版本门禁的判定。CLI 与 SDK 任一对不上基准就算不匹配。

        两个都查是因为它们回答的是不同问题：CLI 对不上说明本机环境与我们验证时不同，
        SDK 对不上说明 `can_use_tool` 的契约可能变了——而整个审批机制就建立在它上面。
        """
        pi = bool(self.cli_ban_ben and self.cli_ban_ben != self.ji_zun_ban_ben)
        sdk = bool(self.sdk_ban_ben and self.sdk_ban_ben != self.ji_zun_sdk)
        return {
            "baseline": self.ji_zun_ban_ben,
            "sdkBaseline": self.ji_zun_sdk,
            "cliVersion": self.cli_ban_ben,
            "sdkVersion": self.sdk_ban_ben,
            "mismatch": pi or sdk,
            "reasons": [x for x, k in (("cli", pi), ("sdk", sdk)) if k],
            "forcedMode": "plan",
        }

    # ---- 适配器生命周期 ----
    async def xin_jian(self, a1: str) -> Any:
        """按 agentId 从注册表取适配器并建立连接。"""
        hui = self.hua.du(a1)
        cls = ZHU_CE_QI.get(hui.agentId if hui else "", EchoAdapter)
        ad = cls(self._hui_zhuan(a1))
        if hasattr(ad, "pid_hui"):
            ad.pid_hui = lambda pid, _sid=a1: self.lu_pid(pid, _sid)
        await ad.kaishi({
            "cwd": hui.cwd if hui else ".",
            "permissionMode": hui.effectiveMode if hui else "manual",
            "resume": hui.claudeSessionId if hui else None,
            # 凭据隔离（spec 11.2）。**这里是全进程唯一调 `kaishi()` 的地方**，
            # `_jian_hui` 只建 AgentSession；所以 env 必须从这里进。
            # 直接读 `self.env`（`__init__` 里有默认 None），不用 getattr——
            # 少一个「属性没挂上就静默退回共用凭据」的失败模式。
            "env": self.env,
        })
        self.huan_qu_dic[a1] = ad.loop or asyncio.get_event_loop()
        # hasattr 那道判断是多余的，作用只是让 echo 这类没有该方法的适配器也能过。
        # 曾经因为两边方法名拼写不一致，这里恒为 False，pid 一次都没记上——
        # 症状是「两段式关闭显示没有任何子进程」，看起来像根本没 spawn。
        qu_pid = getattr(ad, "qu_pid", None)
        pid = qu_pid() if qu_pid else None
        if pid:
            self.lu_pid(pid, a1)
        return ad

    def lu_pid(self, a1: int, a2: str) -> None:
        """记下子进程 pid（3.6）。Bridge 崩了以后靠它回收孤儿。"""
        # Replacing a session's previous one-shot process avoids stale pid entries.
        for old_pid, session_id in list(self.pids.items()):
            if session_id == a2 and old_pid != a1:
                self.pids.pop(old_pid, None)
        self.pids[a1] = a2
        if self.ji_pids:
            self.ji_pids(sorted(self.pids))

    def sha_pid(self, a1: int) -> bool:
        """按 pid 杀掉子进程。返回是否真的动过手。

        **这一层不能省。** 真机实测：`client.disconnect()` 在有 query 在飞时
        并不保证子进程退出，四条会话里有两条活过了两段式关闭——
        一个带着用户全部权限的 `claude` 进程留在后台继续改文件。
        9.4 的原话是「只 kill 自己 spawn 的、记了 pids[] 的 pid」，
        这里做的就是这件事：按 pid 杀，绝不按进程名。
        """
        from lifeos.bridge.run import cun_zhen, sha_si  # 延迟导入：run 会 import http

        if not cun_zhen(a1):
            self.pids.pop(a1, None)
            return False
        sha_si(a1)
        self.pids.pop(a1, None)
        if self.ji_pids:
            self.ji_pids(sorted(self.pids))
        return True

    def sha_qing_dian(self, a1: str) -> None:
        """把某个会话名下所有子进程杀干净。"""
        for pid in [x for x, sid in self.pids.items() if sid == a1]:
            self.sha_pid(pid)

    def huan_qu(self, a1: str):
        loop = self.huan_qu_dic.get(a1)
        if loop is None:
            loop = asyncio.new_event_loop()
            self.huan_qu_dic[a1] = loop
        return loop

    def duo_cuo(self, a1: str, a2: Any, a3: float = 5.0) -> Any:
        """在适配器自己的 loop 上跑一个协程并等它完成。

        HTTP 线程直接 `asyncio.run()` 会另起一个 loop——而 `interrupt()` /
        `set_permission_mode()` 都要通过那条 loop 上的流写进子进程，
        在错误的 loop 上调用要么静默无效，要么抛「loop 已关闭」。
        """
        xian = a2()  # 传进来的是协程函数，不是协程对象
        loop = self.huan_qu_dic.get(a1)
        if loop is not None and loop.is_running():
            return asyncio.run_coroutine_threadsafe(xian, loop).result(a3)
        return asyncio.run(xian)

    def _ting_zhi(self, a1: str, a2: float = 0.0) -> None:
        """停滞超时：中断 Agent。不这么做的话会话已判死而账单还在涨。"""
        ad = self.shi_ying.get(a1)
        if ad is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(ad.zhong_duan(), self.huan_qu(a1))
        except Exception:  # noqa: BLE001
            pass

    def _guan_yong(self, a1: str, a2: float = 0.0) -> None:
        ad = self.shi_ying.pop(a1, None)
        if ad is not None:
            # 顺序：先收口挂起项 → 再发中断 → 最后断开。
            # 反过来做的话 disconnect() 会在另一个任务正卡在 can_use_tool 等待时
            # 拆掉它的流，那个协程永远醒不过来。
            self.shen_qing.zhong_duan(a1)
            for cor, miaosu in ((ad.zhong_duan, 3.0), (ad.guan_bi, 5.0)):
                try:
                    # 不能对没在跑的 loop 用 run_coroutine_threadsafe：
                    # 那个 future 永远不会完成，.result() 抛超时，
                    # 而协程从此再没人 await —— 进程就泄漏了。
                    self.duo_cuo(a1, cor, miaosu)
                except Exception:  # noqa: BLE001
                    pass
        self.sha_qing_dian(a1)
        self.ren_wu.pop(a1, None)
        self.huan_qu_dic.pop(a1, None)
        self.shen_qing.zhong_duan(a1)
        # 会话马上要被摘掉，先把要报的计数取出来——detail 里给真实值
        s = self.hua.du(a1)
        self.hua.shan(a1)
        self.zong.fa("session_removed", a1)
        if self.lu_dao is not None:
            self.lu_dao.guan_hui(a1, {
                "sessionId": a1, "reason": "closed",
                "turnCount": s.turnCount if s is not None else 0,
                "batchDone": s.batchDone if s is not None else 0,
            })

    def guan_biao(self) -> int:
        """9.4 两段式关闭的第一段：把所有挂起项收口、所有会话关掉。"""
        n = 0
        for sid in list(self.shi_ying):
            n += self.shen_qing.zhong_duan(sid)
            self._guan_yong(sid)
        for sid in [s["sessionId"] for s in self.hua.kua()]:
            n += self.shen_qing.zhong_duan(sid)
            self.hua.shan(sid)
            self.zong.fa("session_removed", sid)
        # 兜底：适配器都关了还不够，剩下还活着的子进程按 pid 杀干净。
        # 漏掉这一步的后果是用户关了 Bridge，agent 还在后台改文件。
        for pid in list(self.pids):
            self.sha_pid(pid)
        self.hua.ting_zhi()
        return n

    async def _jie_shou(self, a1: str, a2: Any, a3: str) -> Any:
        """等挂起项收口，然后**把状态挪回 working**。

        这一步不能省。用户点完「允许」之后 Agent 立刻开始跑工具，但状态还挂在
        `attention` 上：界面会一直显示「等你操作」——UI 在撒谎；
        更糟的是 8.7 的停滞超时只认 `working`/`thinking`，于是「Agent 卡死 15 分钟」
        这件事永远检测不到。实测就是靠这一步才发现的真问题。
        """
        r = await a2
        try:
            self.hua.geng(a1, "working", a3)
        except (KeyError, InvalidTransition):
            # 已经中断（idle）或已经结束（ended）时不该硬掰状态
            pass
        return r

    def _hui_zhuan(self, a1: str):
        """把适配器发来的事件翻译成协议帧（6.3 的 kind 与 7.3 的帧）。"""
        def fa(a2: str, a3: dict) -> None:
            if a2 == "chunk":
                # chunk 不是真相，只是打字机效果；丢了不影响正确性。
                self.zong.fa("chunk", a1, messageId=a3.get("messageId", ""),
                             delta=a3.get("delta", ""), messageKind=a3.get("messageKind", "text"))
                self.hua.huo_dong(a1)
                return
            if a2 == "result":
                s = self.hua.du(a1)
                # 3.2：result 也落成一条消息。只发帧的话，恢复后的历史里
                # 看不到「这次跑完的结果是什么」。
                self.hua.tian_jia(a1, "system", "result",
                                  text=a3.get("resultText", ""),
                                  isError=bool(a3.get("isError")))
                self.zong.fa("result", a1,
                             subtype=a3.get("subtype", ""), durationMs=a3.get("durationMs", 0),
                             numTurns=a3.get("numTurns", 0), totalCostUsd=a3.get("totalCostUsd", 0.0),
                             isError=bool(a3.get("isError")), resultText=a3.get("resultText", ""),
                             # 这一帧本身就是「一条指令跑完了」，
                             # 而 paichu 是在收到结果之后才自增，所以这里要 +1。
                             batchDone=(s.batchDone + 1) if s else 0,
                             batchTotal=s.batchTotal if s else 0)
                # 3.8 决策回路：每条指令的 result 都要回到 LifeOS 对话上下文。
                # 断在 `hui` 层发不出去也没关系——主服务侧的落点在阶段 5 会补落盘。
                if self.lu_dao is not None:
                    self.lu_dao.jie_guo(a1, {
                        "resultText": tui_mian(a3.get("resultText", "")),
                        "isError": bool(a3.get("isError")),
                        "durationMs": a3.get("durationMs", 0),
                        "numTurns": a3.get("numTurns", 0),
                        "totalCostUsd": a3.get("totalCostUsd", 0.0),
                        "subtype": a3.get("subtype", ""),
                    })
                return
            if a2 == "error":
                msg = a3.get("message", "")
                self.hua.tian_jia(a1, "system", "error", text=msg)
                self.zong.fa("error", a1, code=a3.get("code", "internal"), message=msg,
                             recoverable=bool(a3.get("recoverable", True)))
                return
            if a2 == "session":
                s = self.hua.du(a1)
                if s is not None:
                    s.claudeSessionId = a3.get("claudeSessionId") or None
                return
            if a2 in ("text", "thinking"):
                self.hua.tian_jia(a1, "assistant", a2, a3.get("messageId") or None,
                                  text=a3.get("text", ""))
                return
            if a2 == "tool_use":
                self.hua.tian_jia(a1, "assistant", "tool_use", a3.get("messageId") or None,
                                  toolName=a3.get("toolName", ""),
                                  toolInput=a3.get("toolInput"), toolUseId=a3.get("toolUseId"))
                return
            if a2 == "tool_result":
                self.hua.tian_jia(a1, "user", "tool_result", toolUseId=a3.get("toolUseId"),
                                  toolName=a3.get("toolName") or None,
                                  text=a3.get("text", ""), isError=bool(a3.get("isError")))
                return
            if a2 in ("rate_limit", "context_reset"):
                self.hua.tian_jia(a1, "system", a2, text=a3.get("text", ""))
                return
        return fa

    def _cheng_bu(self, a1: str):
        """挂起能力：发出审批/提问后一直等到收口，把结果交回适配器。"""
        hui = self.hua.du(a1)

        async def cheng(a2: str, a3: dict):
            fu = asyncio.get_event_loop().create_future()
            if a2 == "permission":
                # 闸门 2 先跑：命中 deny 基线的调用不给用户看审批卡，直接收口。
                self.shen_qing.shibai(a3.get("toolName", ""), a1, a3.get("toolInput", {}),
                                      hui.cwd if hui else ".", fu,
                                      a3.get("toolUseId", ""))
                if fu.done():
                    return fu.result()
                self.shen_qing.jia(a1, hui.agentId if hui else "claude-code",
                                   a3.get("toolUseId", "t-unknown"),
                                   a3.get("toolName", ""), a3.get("toolInput", {}), fu,
                                   a3.get("title", ""), a3.get("suggestions"))
                if fu.done():
                    # 阶段 5：命中了重启前的历史决定。此时再 geng("attention")
                    # 会让界面闪一下「等你操作」，而用户根本没有被问到。
                    return fu.result()
                self.hua.geng(a1, "attention", "permission_requested")
                return await self._jie_shou(a1, fu, "permission_resolved")
            if a2 == "question":
                w = self.shen_qing.cha_xun(a1, a3.get("toolUseId", "t-unknown"),
                                           a3.get("questions", []), fu)
                self.hua.geng(a1, "waiting_input", "question_asked")
                return await self._jie_shou(a1, fu, "question_answered")
            return None
        return cheng
