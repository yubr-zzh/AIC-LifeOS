"""出站隧道客户端（方案 9.5 的 tunnel.py；spec 6.2–6.6、7.3）。

**它是一个适配器，不是第二套业务逻辑。** Bridge 照常跑自己的 127.0.0.1 HTTP
服务，本模块只做「WS 消息 ↔ 本地 HTTP 调用」的搬运：收到 `request` 就真发一次
本机 HTTP，把结果或帧搬回 WS。所以 `http.py` 一行不改，阶段 1–5 的行为
按构造保持一致。

三个实测确认过、必须照做的细节见任务描述。
"""

from __future__ import annotations

import base64
import json
import logging
import random
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from lifeos.api.tunnel_gw import jie
from lifeos.api.xie_yi import XieYiCuoWu, he_hao, jie_qiu
from lifeos.bridge import jiaojie, pipei
from lifeos.bridge.models import xianzai

XIN = 15.0        # 心跳间隔，与 SSE 心跳同值（15.3.3、15.4）
XIN_SI = 45.0     # 判死：连续 3 次无响应（15.3.3）
ZUI_DA = 1 << 20  # L2 隧道消息上限（spec 6.6）
TUI_BI = 30.0     # 退避上限（15.3.3）
def _zhu_du(a1: Any, a2: int) -> bytes:
    """从响应流里读**至多一块**，不攒满 a2 字节。

    SSE 是 chunked，一帧一个 chunk。`http.client.HTTPResponse.read(amt)` 会
    **攒满 amt 字节才返回**，安静会话下首帧（snapshot、审批卡）会被压到流结束
    或攒够 4 KiB 才动——不报错，帧只是不来。真机验收第 3 步就是死在这里。
    `read1` 最多做一次底层 recv，正是要的语义。

    `urllib.error.HTTPError` **没有** `read1`（它的 MRO 里没有 `addinfourl`，
    实测 `hasattr(HTTPError, "read1") is False`），而 `_da()` 的异常分支返回的
    正是它。那种响应体本来就小，退回 `read` 不改变行为；若直接换成 `read1`，
    这里会抛 `AttributeError` 并被 `_liu` 的 `except Exception` 吞掉，
    **等于用一个静默失效换另一个静默失效**。
    """
    return (getattr(a1, "read1", None) or a1.read)(a2)


# 不下隧道的 hop-by-hop 头（spec 6.2）
BU_TIAO = {"connection", "transfer-encoding", "upgrade", "keep-alive",
           "proxy-authenticate", "proxy-authorization", "te", "trailer"}


class SuiDao(jiaojie.JiaoJie):
    """出站隧道。`qi_dong()` 起一个后台线程跑重连循环。"""

    def __init__(self, a1: Any, a2: dict[str, Any]) -> None:
        self.fu = a1
        self.cfg = a2
        self.ri = logging.getLogger("bridge.tunnel")
        # 默认值只是给「cfg 里没放 url 键」的调用方兜底（测试桩、外部脚本）。
        # 生产入口 `run.py` 会按 `LIFEOS_GW_PORT` 算出这个键——**两端必须同源**，
        # 否则运营者改了端口、Bridge 还打 8771，症状是无限重连且不报错。
        self.url = str(a2.get("url") or "ws://127.0.0.1:8771/bridge/tunnel")
        self._zhuang = "connecting"
        self._ting = threading.Event()
        self.tiao: threading.Thread | None = None
        self.k: Any = None
        self._fa_suo = threading.Lock()
        self._liu_suo = threading.Lock()
        self._liu_biao: dict[str, Any] = {}   # requestId → 本地长响应对象
        self._ci = 0
        self._lian_shang = threading.Event()
        self._jie_bang = False
        # 上一次已发布的语义状态 `(state, error)`。**空元组表示「尚未发布过」**，
        # 于是新实例的第一次发布与停止时的最终状态都天然放行——`ting_zhi()`
        # 里不需要、也不该另开一条「强制发布」的旁路，那条旁路迟早会漏掉
        # 某个退出路径。
        self._fa_bu_guo: tuple[str, str | None] = ("", None)

    # ---------- 接口 ----------
    def zhuang_tai(self) -> str:
        return self._zhuang

    def chong_lian_ci(self) -> int:
        return self._ci

    def deng_dao(self, a1: float = 5.0) -> bool:
        return self._lian_shang.wait(a1)

    def qi_dong(self) -> None:
        if not self.cfg.get("deviceToken"):
            # 没配对就没有令牌，重连一万次也不会成功。**直接进 error 并说清原因**，
            # 不静默重试——那会让用户看到「一直在连接」却不知道要去配对。
            self._zhuang = "error"
            self.ri.warning("还没有配对（runtime.json 里没有 deviceToken），隧道不启动")
            self._bao_zt("尚未配对，请打开本机 /pair 页面粘贴配对码")
            self._lian_shang.set()  # error 也是 deng_dao() 要等的那个「有结论」
            return
        # DEBUG 级下 `websockets.client` 会把**每一个请求头**打进日志
        # （client.py 的 `logger.debug("> %s: %s")`），其中就有
        # `Authorization: Bearer <deviceToken 原文>`。「token 绝不进日志」是硬要求，
        # 不能只靠「别把日志级别调高」维持——在这里钉住它。
        # 与 tunnel_gw.py 里对 `websockets.server` 的那条处理是同一件事的两端。
        logging.getLogger("websockets.client").setLevel(logging.INFO)
        self.tiao = threading.Thread(target=self._huan, name="tunnel", daemon=True)
        self.tiao.start()

    def ting_zhi(self, chao: float = 5.0, wan_cheng: bool = False) -> dict[str, Any] | None:
        """停止隧道。**`wan_cheng=True` 时返回诊断，代表「关闭已完成」。**

        原来只有「已发起」：置停止标志、关流、join(timeout=5)、句柄置 `None`。
        无论重连线程退没退出都返回 None，调用方只能「关完就当关了」。而重连
        循环里 `_lian()` 最长可以阻塞在退避等待上——`join` 超时之后那个线程
        照样活着，下一轮醒来还会再发一次连接尝试。

        返回的诊断回答「还剩什么」：重连线程在不在、在途响应句柄清没清、
        连接关没关。达不到完成条件就 `guan_bi_wan_cheng=False`，**不假装成功**。
        """
        self._ting.set()
        self._guan_liu_quan_bu()
        if self.k is not None:
            try:
                self.k.close()
            except Exception:  # noqa: BLE001
                pass
        if self.tiao is not None:
            # **join 之后不置 None**：`is_alive()` 是「它到底退没退」的判据，
            # 置成 None 就把这个证据自己抹掉了。
            self.tiao.join(timeout=chao)
            if not self.tiao.is_alive():
                self.tiao = None
        if not wan_cheng:
            return None
        return self.guan_bi_diagnostic()

    def guan_bi_diagnostic(self) -> dict[str, Any]:
        """**关闭诊断**：回答「现在还剩什么没关掉」。"""
        tiao = self.tiao
        return {
            "guan_bi_wan_cheng": self.guan_bi_wan_cheng_ma(),
            "ting_lei": self._ting.is_set(),
            "chong_lian_ci": self._ci,
            "tiao_huo_zhe": tiao is not None and tiao.is_alive(),
            "zai_tu_chi_bing": len(self._liu_biao),
            "lian_yi_guan": self.k is None,
            "shuo_ming": "guan_bi_wan_cheng 为假时，tiao_huo_zhe / zai_tu_chi_bing "
                         "就是还没关掉的东西",
        }

    def guan_bi_wan_cheng_ma(self) -> bool:
        """完成判据。**每一项都要真的成立**：重连线程退出、在途响应句柄清空、
        连接已关。三项缺一都不算关完。"""
        if self.tiao is not None and self.tiao.is_alive():
            return False
        with self._liu_suo:
            if self._liu_biao:
                return False
        return self.k is None

    # ---------- 重连循环 ----------
    def _huan(self) -> None:
        bei = 1.0
        # **首帧必发，之后每轮开头不再发。** 开头那句 `connecting`/无错与结尾
        # 那句 `connecting`/有错是**同一次重连尝试的两半**：一帧说"在连"，一帧
        # 说"没连上"。每轮都发这对，UI 就在"连接中"和"连接失败"之间来回闪，
        # 而这两帧的 `error` 不同，`_bao_zt` 的去重（键是 `(state, error)`）
        # 按设计也留不住它们。
        #
        # 阶段六真机验收 540 秒里记到 42 帧 `connecting`（streamSeq 34–75）
        # 就是这个交替模式。**当时记成「内容完全相同」是不准确的**——
        # `tools/verify_stage6.py` 只采了 `state` 不采 `error`，`error` 其实
        # 一帧 `None` 一帧"连接中断，正在重连"。只改去重键治不了它。
        #
        # 只发首帧之后，四种状态转换路径一条不少：connecting→connected（连上）、
        # connected→connecting（断开，带原因）、connecting→error（握手被拒）、
        # connecting→error（被解绑）。断线重连的"每次尝试"不再是事件。
        first = True
        while not self._ting.is_set():
            self._zhuang = "connecting"
            if first:
                self._bao_zt()
                first = False
            # **重置只能在这一轮尝试开始时做。** 放在 `_lian` 连接开头的话，
            # 上一次连接里收到的 bye 会被下一次连接开头这句抹掉，标志活不过
            # `_lian` 的返回，下面那个判断就成了永远走不到的死代码。
            self._jie_bang = False
            try:
                self._lian()
                bei = 1.0
            except InvalidStatus as e:
                ma = e.response.status_code
                if ma in (401, 403):
                    # **令牌失效或设备已解绑 → 停止重连**（spec 6.5）。不区分的话
                    # 解绑之后每 30 秒被拒一次，日志刷屏而用户看不出原因。
                    self._zhuang = "error"
                    self._bao_zt(f"网关拒绝握手（HTTP {ma}）：令牌已失效或设备已解绑")
                    self.ri.warning("隧道握手被拒 HTTP %s，停止重连（需要重新配对）", ma)
                    self._lian_shang.set()  # error 也是 deng_dao() 要等的那个「有结论」
                    return
                self.ri.warning("隧道握手被拒 HTTP %s，稍后重试", ma)
            except Exception as e:  # noqa: BLE001
                self.ri.info("隧道断开：%s", type(e).__name__)
            if self._jie_bang:
                # 网关说我们被解绑了。令牌已经失效，再连只会一直被拒。
                # **必须判在 try 之外**：`bye` 帧的处理是 `k.close()`，接收循环
                # 里的 recv 随即抛 ConnectionClosed 直接穿出 `_lian`，正常返回
                # 路径与异常路径都会到这里；判在 `_lian` 内部的话这段永远到不了。
                self._zhuang = "error"
                self._bao_zt("设备已被解绑，停止重连；重新配对后再启动")
                self._lian_shang.set()  # error 也是 deng_dao() 要等的那个「有结论」
                return
            if self._ting.is_set():
                break
            self._ci += 1
            self._zhuang = "connecting"
            self._bao_zt("连接中断，正在重连")
            # 退避 1s→30s，带抖动（15.3.3：避免服务重启后所有 Bridge 同时重连）
            shui = bei * (0.8 + 0.4 * random.random())
            self._ting.wait(shui)
            bei = min(bei * 2, TUI_BI)

    def _lian(self) -> None:
        # **整段包在 try 里**：断线是常态，而 `k.close()`（bye 帧）、握手失败、
        # 非法消息都会让控制流在 `with` 里就穿出去。收尾那两句写在 `with` 之后
        # 而不是 finally 里的话，异常路径上它们一次都不跑 —— `self.k` 继续指着
        # 已关闭的连接，在途请求线程对着它 send，异常被 `_fa` 静默吞掉；
        # `_lian_shang` 也永久置位，`deng_dao()` 在断线期间照样返回 True。
        try:
            self._lian_nei()
        finally:
            self.k = None
            self._lian_shang.clear()

    def _lian_nei(self) -> None:
        with connect(
            self.url,
            additional_headers={
                "Authorization": f"Bearer {self.cfg['deviceToken']}",
                "X-Protocol-Version": "1",
                "X-Instance-Id": str(self.cfg.get("instanceId") or ""),
            },
            # **必须显式关掉代理。** 本机设着 HTTP_PROXY，websockets 默认
            # proxy=True 会读它，把回环连接送去代理。localbus.py 踩过同一个坑。
            proxy=None,
            ping_interval=XIN, ping_timeout=XIN_SI, max_size=ZUI_DA,
            compression=None, open_timeout=10, close_timeout=5,
        ) as k:
            self.k = k
            k.send(json.dumps({
                "t": "hello", "instanceId": str(self.cfg.get("instanceId") or ""),
                "streamEpoch": int(getattr(self.cfg.get("zong"), "shui", 0)),
                "version": "2.0", "cliVersion": str(self.cfg.get("cliVersion") or ""),
                "sessions": int(getattr(self.cfg.get("zong"), "zhan", None)
                                and len(self.cfg["zong"].zhan._map) or 0),
            }, ensure_ascii=False))
            self._zhuang = "connected"
            self._bao_zt()
            self._lian_shang.set()
            while not self._ting.is_set():
                try:
                    wen = k.recv(timeout=1.0)
                except TimeoutError:
                    continue
                # **入口校验与网关共用同一份**（原来是这里手抄的一份
                # `isinstance(x, dict)` + `x.get("t") is str`）：两处各写一份，
                # 下次改协议版本就要找两个地方。信封过后再过契约层。
                x = jie(wen)
                if x is None:
                    self.ri.warning("网关发来无法解析的消息，断开")
                    break
                if not self._he_fa(x):
                    break
                self._fen(x)

    def _he_fa(self, a1: dict[str, Any]) -> bool:
        """契约层校验（与网关共用 `xie_yi`）。不合法返回 False，调用方断开隧道。

        协议版本已在握手用 `X-Protocol-Version` 卡过，走到这里还不合法说明两端
        实现不一致——凑合工作比断开贵（Ruling 2）。`welcome` / `bye` 不在
        spec 6.2 的四类消息里，本层不管，照旧透传。
        """
        lei = a1.get("t")
        try:
            if lei == "request":
                jie_qiu(a1)
            elif lei == "close" and not he_hao(a1.get("id")):
                raise XieYiCuoWu("bad_id", "close 的 id 不是 r- 加 8 位 hex")
        except XieYiCuoWu as e:
            self.ri.warning("网关发来的 %s 不合契约（%s：%s），断开隧道",
                            lei, e.code, e.message)
            return False
        return True

    # ---------- 消息分发 ----------
    def _fen(self, a1: dict[str, Any]) -> None:
        lei = a1.get("t")
        if lei == "request":
            threading.Thread(target=self._qing, args=(a1,), daemon=True).start()
            return
        if lei == "close":
            # `_he_fa` 已保证入站 close 的 id 合格式，这里不再兜底成空串——
            # 兜底只会把「协议不一致」藏成「本地找不到那条流」。
            self._guan_ben_di(a1["id"])
            return
        if lei == "bye":
            # 网关主动告别（解绑）。标记后由重连循环收尾。
            self._jie_bang = True
            if self.k is not None:
                try:
                    self.k.close()
                except Exception:  # noqa: BLE001
                    pass
            return

    # ---------- 转发一次请求 ----------
    def _qing(self, a1: dict[str, Any]) -> None:
        rid = str(a1.get("id") or "")
        try:
            r = self._da(a1)
        except Exception as e:  # noqa: BLE001
            self._fa({"t": "response", "id": rid, "status": 502,
                      "headers": {"content-type": "application/json; charset=utf-8"},
                      "body": json.dumps({"error": {
                          "code": "agent_unavailable",
                          "message": f"Bridge 本地服务不可达：{type(e).__name__}"}},
                          ensure_ascii=False),
                      "b64": False})
            return
        try:
            tou = {k.lower(): v for k, v in r.headers.items()}
            if str(tou.get("content-type") or "").startswith("text/event-stream"):
                self._fa({"t": "response", "id": rid, "status": int(r.status),
                          "headers": tou, "body": "", "b64": False})
                self._liu(rid, r)
            else:
                self._fa_xiang(rid, int(r.status), tou, r.read())
        except Exception as e:  # noqa: BLE001
            self.ri.info("转发 %s 失败：%s", rid, type(e).__name__)
        finally:
            try:
                r.close()
            except Exception:  # noqa: BLE001
                pass

    def _da(self, a1: dict[str, Any]) -> Any:
        """调本地 HTTP 服务。返回响应对象（4xx/5xx 也是有效响应，要原样搬回去）。

        **契约校验不在这里。** 入口在 `_lian_nei`（`jie(wen)` + `_he_fa()`）：
        `_da` 只被 `_fen` 派发到达，`_fen` 只被 `_lian_nei` 调用，所以能到这里的
        `a1` 一定已经过完契约层。下面这些 `.get` 兜底是留给「被直接调」的，
        **别再往上加一层校验**——同一层里重复防御只会多出一个要跟着同步改的地方。
        """
        lu = str(a1.get("path") or "/")
        cx = str(a1.get("query") or "")
        url = f"http://127.0.0.1:{self.cfg['port']}{lu}" + (f"?{cx}" if cx else "")
        tou = {k: v for k, v in (a1.get("headers") or {}).items()
               if k.lower() not in BU_TIAO and k.lower() != "host"}
        # 回环调用的凭据。**隧道客户端持有 token** —— 本地服务照样要过
        # auth.duanren（S1/S2 的防线一字不松）。/stream 也认 header，
        # 所以不需要往 query 里塞 token。
        tou["x-bridge-token"] = str(self.cfg.get("token") or "")
        # **SSE 连接数的来源（spec 10.1、7.2.5 的「每 userId 8 条」）。**
        # 浏览器自己不会发这个头，全仓库只有这里能补——它在中间，恰好知道
        # 这个 userId。不补的话 `http.py:_liu` 只能落回 `local`，那条上限
        # 在公网形态下永远数不到（同一条 Bridge 后面挂着多个用户的浏览器）。
        #
        # **用 cfg 里的 userId 覆盖前端带来的同名头。** 来源只用来数连接，
        # 让前端自己声明「我是哪个用户」等于把它变成一个能被随便绕过的配额：
        # 开 8 条再换个名字就又有了 8 条。
        tou["x-lifeos-source"] = str(self.cfg.get("userId") or "local")
        shen = a1.get("body")
        shu = shen.encode("utf-8") if isinstance(shen, str) else None
        req = urllib.request.Request(
            url, data=shu, method=str(a1.get("method") or "GET").upper(), headers=tou)
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            return op.open(req, timeout=300)
        except urllib.error.HTTPError as e:
            return e

    def _liu(self, a1: str, a2: Any) -> None:
        """读本地 SSE 流，逐帧转发。登记句柄以便 close 时能立刻关掉。"""
        with self._liu_suo:
            self._liu_biao[a1] = a2
        try:
            huan = b""
            while not self._ting.is_set():
                kuai = _zhu_du(a2, 4096)
                if not kuai:
                    break
                huan += kuai
                while b"\n\n" in huan:
                    yi, huan = huan.split(b"\n\n", 1)
                    self._fa_zhen(a1, yi)
        except Exception:  # noqa: BLE001 - 连接被关掉就是结束了
            pass
        finally:
            with self._liu_suo:
                zi_ji = self._liu_biao.pop(a1, None)
            if zi_ji is not None:
                # 流自然结束：告诉网关「这个 requestId 结束了」，别让它等到 60 秒超时。
                # close 是双向的，含义对称（见计划任务 3 的说明）。
                self._fa({"t": "close", "id": a1, "why": "stream_ended"})

    def _fa_zhen(self, a1: str, a2: bytes) -> None:
        """把一条本地 SSE 块转成一帧转发出去。**帧内容不改写**（15.3.2）。"""
        shu = a2.decode("utf-8", "replace")
        ju = [ln for ln in shu.split("\n") if ln.startswith("data:")]
        if not ju:
            return  # 心跳注释（`: ping`）或空块
        try:
            f = json.loads("".join(ln[5:].lstrip() for ln in ju))
        except json.JSONDecodeError:
            return
        self._fa({"t": "frame", "id": a1, "frame": f})

    def _fa_xiang(self, a1: str, a2: int, a3: dict[str, str], a4: bytes) -> None:
        try:
            wen = a4.decode("utf-8")
            b64 = False
        except UnicodeDecodeError:
            wen = base64.b64encode(a4).decode("ascii")
            b64 = True
        self._fa({"t": "response", "id": a1, "status": a2, "headers": a3,
                  "body": wen, "b64": b64})

    def _guan_ben_di(self, a1: str) -> None:
        with self._liu_suo:
            r = self._liu_biao.pop(a1, None)
        if r is not None:
            try:
                r.close()
            except Exception:  # noqa: BLE001
                pass

    def _guan_liu_quan_bu(self) -> None:
        with self._liu_suo:
            quan = list(self._liu_biao.values())
            self._liu_biao.clear()
        for r in quan:
            try:
                r.close()
            except Exception:  # noqa: BLE001
                pass

    # ---------- 出站 ----------
    def _fa(self, a1: dict[str, Any]) -> None:
        """发一条消息。**send 不保证线程安全**（与阶段 1 的 wfile 同一条教训）。"""
        k = self.k
        if k is None:
            return
        shu = json.dumps(a1, ensure_ascii=False)
        if len(shu.encode("utf-8")) > ZUI_DA:
            # 超限**断开而不是截断**（9.5、spec 6.6）：截断的 frame 会让前端
            # 收到半个 JSON，行为不可预测；断开则走重连 + snapshot，能自愈。
            self.ri.warning("隧道消息超过 %d 字节，断开隧道", ZUI_DA)
            try:
                k.close()
            except Exception:  # noqa: BLE001
                pass
            return
        with self._fa_suo:
            try:
                k.send(shu)
            except Exception:  # noqa: BLE001
                pass

    def _bao_zt(self, a1: str = "") -> None:
        """把隧道状态写进事件总线，前端靠它显示「设备离线」（spec 9.4）。

        **同语义不重复发。** 去重键是 `(state, error)` 二元组：两者都没变就
        直接返回——不写事件、不占 `streamSeq`、不重新求 `since`。

        为什么非去不可：`_huan` 每轮开头结尾各调一次，退避最长 30 秒。阶段六
        真机验收在 540 秒里观察到 42 条重复的 `connecting`——它们一路占着
        `streamSeq`、挤进重放缓冲、推给每个订阅者。**去重只能在源头做**：
        帧一旦发出去就已经污染了那三处，前端过滤只是把症状藏起来。

        `error` 必须在键里：「connecting」从「无错」变成「连接中断，正在重连」
        是语义变化（用户看到的是不同的提示），从「原因甲」变成「原因乙」同理。
        省掉它，这两种情况都会被静默吞掉。

        去重只在进程内有效：新实例的第一次发布、停止时的最终状态都照发——
        缓存为空即视为「尚未发布过」，所以这两个出口天然不会被吃掉。
        """
        cuo = (self._zhuang, a1 or None)
        if cuo == self._fa_bu_guo:
            return
        self._fa_bu_guo = cuo
        zong = self.cfg.get("zong")
        if zong is not None:
            try:
                zong.fa("device_status", None, deviceId=str(self.cfg.get("deviceId") or ""),
                        state=self._zhuang, since=xianzai(), error=a1 or None)
            except Exception:  # noqa: BLE001
                pass
        self._xie_yun()

    def _xie_yun(self) -> None:
        """把隧道状态落到 runtime.json（`bridge_admin.xinxi()` 读的就是它）。

        **必须走 `pipei.gai`，不能用自己的一套读-改-写**：runtime.json 是多写者
        文件，配对、`bao_xie` 记子进程、这里三路都写它。各写各的读-改-写，
        两个 HTTP 线程同时 spawn 时会各读到一份旧值、后写的把先写的 pids 抹掉，
        留下一个下次启动也回收不掉的孤儿 `claude`。锁只有 `pipei.XIE_SUO` 一把，
        这里另上一把仍然是两个临界区。

        cfg 里没有 `yun_wen`（测试直接造 SuiDao 时就是）就不写：宁可不落盘，
        也不能凭 `root` 猜出一个路径去覆盖别人机器上的 runtime.json。
        """
        wen = self.cfg.get("yun_wen")
        if not wen:
            return
        try:
            p = Path(wen)
            if pipei.du(p).get("tunnelState") == self._zhuang:
                return  # 没变就不落盘：shou_quan 在 Windows 上要起 icacls 子进程
            pipei.gai(p, {"tunnelState": self._zhuang})
        except Exception:  # noqa: BLE001
            # 落盘是辅助手段。这里抛出去会掀掉重连线程，整条隧道静默停摆，
            # 比「runtime.json 上少一个 tunnelState」坏得多。
            pass


jiaojie.zhu_ce("tunnel", SuiDao)
