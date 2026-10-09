"""隧道网关：浏览器请求 ↔ 用户机器上的 Bridge（方案 15.3、spec 第 6 章）。

**网关不做业务判断**（15.3.2）：不解析帧内容、不改写 `id:`、不缓存 `permission` 帧。
它只做三件事——认出设备、把请求塞进隧道、把响应和帧搬回去。

四个实测确认过的坑，写在这里免得再踩：

1. **`connect()` 必须传 `proxy=None`。** 本机设着 `HTTP_PROXY`，而
   `websockets.sync.client.connect` 的 `proxy` 默认 `True`，会读环境变量。
   `localbus.py` 已经踩过同一个坑。
2. **`ServerConnection.handshake` 是方法不是属性。** handler 里拿不到握手请求，
   要在 `process_request` 里把设备记录挂到连接对象上（该类没有 `__slots__`）。
3. **`send()` 不保证线程安全。** 一条隧道上有接收循环线程 + N 个请求线程，
   与阶段 1 的 `wfile` 是同一条教训：所有 `send` 过同一把锁。
4. **拒绝握手要在 `process_request` 里回 `Response`**，让客户端看到 HTTP 状态码。
   接受了再关，客户端看到的是普通断开——那会让 `tunnel.py` 把「令牌已失效」
   误判成网络抖动，无限重连（spec 6.5 专门要防这个）。
"""

from __future__ import annotations

import heapq
import json
import logging
import queue
import secrets
import threading
import time
from collections import deque
from typing import Any

from websockets.datastructures import Headers
from websockets.http11 import Response
from websockets.sync.server import Server, serve

from lifeos.api.devices import SheBiao
from lifeos.api.xie_yi import XieYiCuoWu, he_hao, jie_ying, zhi_qiu
from lifeos.bridge.models import xianzai

XIYI = "1"
ZUI_DA = 1 << 20  # L2 隧道单条消息上限 1 MiB（spec 6.6）
XIN = 15.0        # 心跳间隔（15.3.3）
XIN_SI = 45.0     # 判死：连续 3 次无响应（15.3.3）
LU_JING = "/bridge/tunnel"
DENG = 30.0     # 一次请求等响应的上限（秒）
DENG_LI = 64    # 一条隧道上同时挂着的在途请求上限

# 15.4 的速率限额。**审批类单独一条窗口**——不与总量共用，否则用户连着批 30 个
# 操作后第 31 个审批会被限流，而那是最不该被限的一类请求。
MEI_YONG_HU = 60.0   # 每用户 60 请求 / 60 秒
MEI_SHE_BEI = 20.0   # 每设备 20 请求 / 60 秒
MEI_SHEN_PI = 30.0   # 审批类 30 请求 / 60 秒（只在 /permissions* 与 /questions* 上计）
CHUANG_KOU = 60.0    # 滑窗宽度（秒）
SAO_JIAN = 64        # 全表清扫的触发间隔（次）。**记次数不记时间**：清扫得能在
# 测试那 200 次调用里被跨过，而那只是毫秒级的事；按时间触发的话它永远扫不到，
# 「早就没人再访问的 uid」的键就此永久残留。每次调用都全表扫则是另一个性能坑
# （几十万键 × 每请求一次）。


class XianLiu:
    """进程内滑动窗口限流。每主体一个时间戳 deque。

    `ponytail:` 进程内、单机。接入多实例部署时换成 Redis 或共享计数器——
    现在多实例还不在范围内（1.4：一台设备对一个账号）。

    **超限的请求不占名额。** 半条命的是这一点：被打回的请求如果照样进窗口，
    一直打被限的请求就能让自己的窗口永远不恢复——从「被限流」变成「自己
    把自己锁死」，那是拒绝服务而不是限流。

    **回收按过期时间索引，不做全表扫描（阶段六收口 07 域，方案 A）。**
    `_dui` 是按「这个键最早会在什么时候空」排的最小堆，每项是
    `(guo_qi, xu_hao, k)`。只弹已到期的堆顶，代价与**已过期的键数**成正比，
    与表大小无关。原实现每 `SAO_JIAN` 次请求持全表锁 O(表大小) 扫一遍，
    实测 40 万键时锁持有中位 **237.61 ms**（`.scratch/liang_sao.py`，
    2026-10-02），而同期一次正常请求的锁持有时间是 0.001 ms——那个表里
    随便哪条请求都有四分之一秒进不去，扫出来的键却全是早就过期的。

    **`xu_hao` 是版本号，不是可有可无的装饰。** 一个键被回收之后同一 uid 又
    回来时，堆里那条陈旧项的 `guo_qi` 会比新窗口的**更早到期**——按时间
    弹堆就会在新窗口刚建立的那一刻把它连根拔掉，于是「刚被限流过的 uid」
    立刻获得一份空窗口，反复重连即绕过限流。版本号让回收能认出「这条项
    说的已经不是当前这个键了」，跳过而不是删除。
    """

    def __init__(self) -> None:
        self.suo = threading.RLock()
        self.biao: dict[str, deque[float]] = {}
        self.count = 0
        # 索引：`(guo_qi, xu_hao, k)`。**堆里可能有陈旧项**——回收时核对
        # 版本号跳过它们，而不是立刻删。删除要在堆内做一次 O(n) 查找，
        # 换来的只是几个字节，不值。
        self._dui: list[tuple[float, int, str]] = []
        # 每个键**当前**那条索引项的版本号。与键同生共死：键被回收时一并摘掉。
        self._hao: dict[str, int] = {}
        self._xu_hao = 0

    def _ji_suan_guo_qi(self, a1: str) -> float | None:
        """这个键最早在什么时候空掉。**读的是队首，不是队尾。**

        窗口是先进先出：裁剪时从队首弹，所以「这个键什么时候不再占名额」
        取决于**最早那次请求**什么时候滑出窗口。取队尾的话索引永远算晚，
        键会一直留在表里——把原来那个「只增不删」的问题原样留在索引上。
        """
        q = self.biao.get(a1)
        return (q[0] + CHUANG_KOU) if q else None

    def _suan_lei_suo(self, a1: str) -> None:
        """重算这个键的到期时刻并挂进堆，**同一键只留一条有效项**。

        **先撤销旧项再压新的。** 直接压的话每次请求都往堆里加一条，50 次请求
        就堆 50 条——索引自己变成第二个只增不删的表，把本域要消掉的问题搬了
        个地方。撤销是 O(len(堆)) 的一次 `remove`；堆在实践中很短（每个活跃
        键一条），换来的是「索引长度 ≈ 活跃键数」这个可验证的性质。
        """
        yuan = self._hao.pop(a1, None)
        guo = self._ji_suan_guo_qi(a1)
        if yuan is not None and guo is not None:
            try:
                self._dui.remove((guo, yuan, a1))
            except ValueError:
                pass          # 旧项早被回收弹走了，直接压新项即可
        if guo is None:
            return               # 窗口空了，这个键不该有索引项
        self._xu_hao += 1
        self._hao[a1] = self._xu_hao
        heapq.heappush(self._dui, (guo, self._xu_hao, a1))

    def sao(self, a1: float) -> None:
        """按过期时间回收已空窗口的键。**调用方必须已持 `self.suo`。**

        只弹已到期的堆顶，**不做全表扫描**。逐键判空、不是「无请求时整表
        清空」：后者会让一个安静用户的窗口被别人的请求顺手打掉，限流就变成
        了可被邻座操纵的开关。

        **堆顶没到期就直接收工**——堆按 `guo_qi` 排序，剩下的项只会更晚，
        全都不该动。这是本域的全部意义：代价跟着「已过期键数」走，不跟着
        「表大小」走。

        **弹出后必须核对版本号。** 键被回收又重建之后，堆里那条旧项的到期
        时刻比新窗口更早（它记的是上一代窗口的队首），不核对就会在新窗口
        刚建立时把它连根拔掉——限流因此可被反复重连绕过。
        """
        while self._dui and self._dui[0][0] <= a1:
            _, hao, k = heapq.heappop(self._dui)
            if self._hao.get(k, -1) != hao:
                continue                    # 陈旧项：这条说的已经不是当前键了
            q = self.biao.get(k)
            if q is None:
                self._hao.pop(k, None)
                continue                    # 键早已被回收，索引项跟着走
            # 到期时刻是**当初建索引时**算的；期间窗口又推进过的话它会晚于
            # 真实到期点，于是这里再裁一次，把真正过期的弹掉。
            while q and a1 - q[0] >= CHUANG_KOU:
                q.popleft()
            if q:
                # 窗口还剩东西但索引项已经出队（理论上不该发生，窗口每次
                # 追加都会重算并压新项）——重新挂回去，别让它变成永久残留。
                self._xu_hao += 1
                self._hao[k] = self._xu_hao
                heapq.heappush(self._dui, (q[0] + CHUANG_KOU, self._xu_hao, k))
                break
            self.biao.pop(k, None)
            self._hao.pop(k, None)

    def guo(self, a1: str, a2: str, a3: str) -> float | None:
        """(userId, deviceId, path) → 超限返回 Retry-After 秒数，否则 None。"""
        lu = a3.split("?", 1)[0]
        shen_pi = lu.startswith("/permissions") or lu.startswith("/questions")
        xian = [(f"u:{a1}", MEI_YONG_HU), (f"d:{a2}", MEI_SHE_BEI)]
        if shen_pi:
            xian.append((f"p:{a1}", MEI_SHEN_PI))
        now = time.monotonic()
        with self.suo:
            self.count += 1
            if self.count >= SAO_JIAN:
                self.count = 0
                self.sao(now)
            cha = None
            for k, shang in xian:
                q = self.biao.setdefault(k, deque())
                while q and now - q[0] >= CHUANG_KOU:
                    q.popleft()
                if len(q) >= shang:
                    cha = max(1.0, CHUANG_KOU - (now - q[0]))
                    break
            if cha is None:
                # 三条窗口**检查完再统一记**。边检查边记的话，第二个键超限时
                # 第一个键已经记上了——那一下请求没被放行却占了名额，窗口比
                # 它真实的请求量满得更早。
                for k, _ in xian:
                    self.biao[k].append(now)
                    self._suan_lei_suo(k)
            # 窗口空了就回收键，**两条出口都要走这里**：超限时上面提前 break，
            # 而它已经把前面的键裁过了，被裁空的键落在 break 之后没人收。
            # `.get` 不是 `[]`：break 之后的键压根没建过。
            for k, _ in xian:
                if not self.biao.get(k):
                    self.biao.pop(k, None)
                    self._hao.pop(k, None)
            if cha is not None:
                return cha
        return None


def zhen(a1: str, **a2: Any) -> str:
    """打包一条隧道消息。"""
    return json.dumps({"t": a1, **a2}, ensure_ascii=False)


def jie(a1: str) -> dict[str, Any] | None:
    """解包。不是合法消息一律返回 None（调用方负责关掉连接）。"""
    try:
        x = json.loads(a1)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(x, dict) or not isinstance(x.get("t"), str):
        return None
    return x


def he_cheng_zhen(a1: str, a2: str, a3: str | None) -> dict[str, Any]:
    """网关合成的 `device_status` 帧（spec 9.4）。

    **`streamSeq` 恒为 0 且不带 `id:`。** `ZongXian.seq` 从 0 起、`fa()` 先自增，
    所以首帧的 streamSeq 是 1，**0 是空号**。合成帧不在 Bridge 的序号空间里，
    给它编任何号都会与真实序号冲突或制造空洞。前端据此识别：
    `streamSeq === 0` 的帧不走单调丢弃规则、也不更新游标。
    """
    return {"type": "device_status", "sessionId": None, "streamSeq": 0,
            "deviceId": a1, "state": a2, "since": xianzai(), "error": a3}


def xie_zhen(a1: dict[str, Any]) -> str:
    """把一帧写成 SSE 线上格式。**合成帧不写 `id:`**（见 `he_cheng_zhen`）。

    真帧照常带 `id:`——前端靠它接 `Last-Event-ID` 续传（7.2.2），漏了整个续传失效。
    """
    shu = json.dumps(a1, ensure_ascii=False)
    tou = "" if a1.get("streamSeq") == 0 and a1["type"] == "device_status" \
        else f"id: {a1['streamSeq']}\n"
    return f"{tou}event: {a1['type']}\ndata: {shu}\n\n"


class WuDui(Exception):
    """没有可用隧道，或等待响应超时。上层映射成 502 agent_unavailable。"""

    def __init__(self, a1: str, a2: str) -> None:
        super().__init__(a2)
        self.code = a1
        self.message = a2


class Dui:
    """一条隧道。一个设备同时只有一条（15.3.1）。"""

    def __init__(self, a1: str, a2: str, a3: Any) -> None:
        self.deviceId = a1
        self.userId = a2
        self.lian = a3
        self.instanceId = ""
        self.streamEpoch = 0
        self.cliVersion = ""
        self.sessions = 0
        self.guan_shi = int(time.time() * 1000)
        self.sheng = True
        # send() 不保证线程安全（见模块顶部第 3 条）
        self._fa_suo = threading.Lock()
        self._guan_suo = threading.Lock()
        # requestId → 该请求的响应/帧队列。`qing` 和 `kai_liu` 共用这套表。
        self.deng: dict[str, queue.Queue] = {}

    def fa_wen(self, a1: dict[str, Any] | str) -> bool:
        """线程安全地发一条消息。返回是否发出去了（连接已死返回 False）。

        a1 是消息本身（dict）或已经 `zhen()` 好的正文（str）。**两者都要收**：
        传 str 进来再 `json.dumps` 一次会把它变成「一个 JSON 字符串」发出去，
        对端 `jie()` 得到 None 就当非法消息断开——这就是欢迎帧曾被拒的原因。

        **超限就断开，绝不截断**（9.5、spec 6.6）：被截断的 frame 会让前端
        收到半个 JSON，行为不可预测；断开则走重连 + snapshot，状态能自愈。
        """
        shu = a1 if isinstance(a1, str) else json.dumps(a1, ensure_ascii=False)
        if len(shu.encode("utf-8")) > ZUI_DA:
            self.guan()
            return False
        with self._fa_suo:
            try:
                self.lian.send(shu)
                return True
            except Exception:  # noqa: BLE001 - 连接已断的各种异常
                self.sheng = False
                return False

    def guan(self) -> None:
        with self._guan_suo:
            self.sheng = False
            kan = getattr(self, "_kan", None)
            if kan is not None:
                kan.wait(10)     # 只在测试里被设上，用来造「关不掉」的形状
            try:
                self.lian.close()
            except Exception:  # noqa: BLE001
                pass


class Liu:
    """一个在途的长响应。帧按到达顺序取出，收到 close 或隧道断开时返回 None。"""

    def __init__(self, a1: "TunnelGw", a2: str, a3: str,
                 a4: queue.Queue) -> None:
        self.gw = a1
        self.deviceId = a2
        self.rid = a3
        self.ku = a4
        self._guan = False

    def zhen(self, a1: float = 60.0) -> dict[str, Any] | None:
        """取下一帧。返回 None 表示流结束。"""
        try:
            x = self.ku.get(timeout=a1)
        except queue.Empty:
            return None
        if x.get("t") == "__end__":
            return None
        return x.get("frame")

    def guan(self) -> None:
        """让 Bridge 关掉对应的那条本地 HTTP 长连接（spec 6.3）。幂等。"""
        if self._guan:
            return
        self._guan = True
        d = self.gw.ren_wu(self.deviceId)
        if d is not None:
            d.fa_wen(zhen("close", id=self.rid, why="client_gone"))
        self.gw._zhai(self.deviceId, self.rid)

    def __enter__(self) -> "Liu":
        return self

    def __exit__(self, *a: Any) -> None:
        self.guan()


class TunnelGw:
    """隧道网关。跑在主服务进程内，监听独立端口（spec 5.1）。"""

    def __init__(self, a1: SheBiao, a2: str = "127.0.0.1", a3: int = 8771,
                 a4: logging.Logger | None = None) -> None:
        self.biao = a1
        self.host = a2
        self.port = a3
        self.ri = a4 or logging.getLogger("bridge.gw")
        self.suo = threading.RLock()
        self.dui: dict[str, Dui] = {}
        # 关闭诊断用的登记表。**handler 线程不是 daemon**（websockets 库明说
        # 不能），它们各自跑在一条隧道上；关闭要能证明「没有活动对象了」，
        # 就得有一份能回答「现在还剩什么」的账，而不是靠 sleep 猜。
        self._ting_lei = threading.Event()   # 已发起关闭：不再接受新握手
        # **自己登记 handler 线程，不靠线程名数。** websockets 库给连接线程
        # 起的是默认名（`Thread-N`），按名字前缀统计既不可靠也会误伤；而且
        # 「数线程」本身就是在回答一个该由注册表回答的问题。
        self._chu_li: set[int] = set()        # 正在跑 _lai 的线程 ident
        self._guan_kan_le: threading.Event | None = None  # 测试用的关门卡
        self.fu: Server | None = None
        self.tiao: threading.Thread | None = None
        self.xian = XianLiu()

    # ---------- 生命周期 ----------
    def qi_dong(self) -> None:
        # S13/Q6：DEBUG 下 websockets 库会把收到的每个请求头都打进日志
        # （server.py 的 `logger.debug("< %s: %s")`），其中就有
        # `Authorization: Bearer <deviceToken 原文>`。「token 绝不进日志」是硬要求，
        # 不能只靠「别把日志级别调高」维持——在这里钉住它。
        logging.getLogger("websockets.server").setLevel(logging.INFO)
        self.fu = serve(
            self._lai, self.host, self.port,
            process_request=self._shou_men,
            ping_interval=XIN, ping_timeout=XIN_SI,
            max_size=ZUI_DA,
            # 踢人时 `close()` 要等对端完成关闭握手，上限就是这个值（默认 10s）。
            # 旧隧道若停在半开 TCP（主机重启、断网——恰好是最需要「断开→重连 +
            # snapshot」自愈的场景），新连接的 welcome 会被拖满整个上限，而这期间
            # 表已经认它是活跃的；Bridge 等不到 welcome 会再连一条，又撞同一堵墙。
            # 压到 2s，别让一次踢人阻塞十秒。
            close_timeout=2,
            # 关掉 permessage-deflate：消息是 JSON，压缩收益有限，
            # 而它会给每条消息加一次压缩/解压，且让「超大消息」的判定
            # 发生在压缩之前（max_size 判的是解压后的大小）——少一个变量。
            compression=None,
        )
        self.tiao = threading.Thread(target=self.fu.serve_forever,
                                     name="tunnel-gw", daemon=True)
        self.tiao.start()
        self.ri.info("隧道网关监听 ws://%s:%s%s", self.host, self.duan_kou(), LU_JING)

    def duan_kou(self) -> int:
        """实际监听端口。测试传 `port=0` 时必需。"""
        if self.fu is None:
            return self.port
        return int(self.fu.socket.getsockname()[1])

    def ting_zhi(self, chao: float = 5.0, wan_cheng: bool = False,
                 _ce_lun: bool = True) -> dict[str, Any] | None:
        """关闭网关。**返回诊断信息就代表「关闭已完成」，返回 None 是老语义。**

        原来的实现是 `join(timeout=5)` 之后直接把句柄置 `None`——无论线程
        退没退出，调用方拿到的都是「关好了」。真实故障恰恰是连接处理线程
        带着旧连接活过关闭：换实例重启会留下持有旧 `TunnelGw` 的孤儿线程。

        所以分成两个语义：

        - **已发起**：`_ting_lei` 置位 → `process_request` 起手就拒，不再接受
          新握手。这一步是立即的。
        - **已完成**：accept 循环退出、每条隧道都从表里摘掉、handler 线程真的
          不在了、在途表空。达不到就返回 `guan_bi_wan_cheng=False` 的诊断，
          **不假装成功**。

        `chao` 是等完成的超时；超时了照样返回诊断，里面带着当时还活着的
        线程名与在途 request id——「关不掉」这个结论必须配得上排查线索。
        """
        # 先停监听（不再收新的），再把活隧道全部收掉。**只关端口是不够的**：
        # 连接处理线程是**非 daemon**（库明说不能 daemon），会带着旧连接活过
        # ting_zhi()，拖住进程退出；换实例重启还会留下持有旧 TunnelGw 的孤儿线程。
        # 阶段 3 吃过同一个形状的亏（`client.disconnect()` 拦不住子进程，
        # 两个 claude 进程活过了 `/bridge/stop`）。
        self._ting_lei.set()
        if self.fu is not None:
            self.fu.shutdown()
            self.fu = None
        # 锁内取快照、锁外逐条关：`guan()` 会阻塞（等对端关闭握手），不能持锁调。
        with self.suo:
            huo = list(self.dui.values())
            self.dui.clear()
        for d in huo:
            d.guan()
        if self.tiao is not None:
            # **join 之后不置 None**：`is_alive()` 是「它到底退没退」的判据，
            # 置成 None 就把这个证据自己抹掉了。
            self.tiao.join(timeout=chao)
        if not wan_cheng:
            # 老调用方（`run.py` 之外的脚本、既有测试）要的仍是「发起即返回」。
            if self.tiao is not None and not self.tiao.is_alive():
                self.tiao = None
            return None
        return self._deng_dai_wan_cheng(chao, _ce_lun)

    def _deng_dai_wan_cheng(self, chao: float, ce_lun: bool) -> dict[str, Any]:
        """轮询到「真的没有活动对象」为止，返回诊断。

        **轮询循环自己写，不 import `tests/gong_ju.py`。** 那一版把测试助手
        从生产代码里 import 进来，pytest 下能跑（`tests/` 在 `sys.path` 里），
        可真机启动立刻炸：`ModuleNotFoundError: No module named 'gong_ju'`。
        症状出现在 05 域之后的第一次真机验收启动主服务时，而 pytest 全绿——
        又一次「单测全绿、真机一条都不通」。生产代码不得依赖测试目录。
        """
        if not ce_lun:
            return self.guan_bi_diagnostic()
        # `time.monotonic` 取一次存住：`jia_shi` 会临时改掉它，别被一起冻住。
        zhen_kao = time.monotonic()
        sui = zhen_kao + chao
        while True:
            if self.guan_bi_wan_cheng_ma():
                break
            if time.monotonic() >= sui:
                break               # 超时不抛：诊断由下面统一返回，已带足信息
            time.sleep(0.01)
        zhen = self.guan_bi_diagnostic()
        if zhen["guan_bi_wan_cheng"]:
            if self.tiao is not None and not self.tiao.is_alive():
                self.tiao = None
        return zhen

    def guan_bi_wan_cheng_ma(self) -> bool:
        """完成判据。**每一项都要真的成立**，不许「大概关了」。"""
        if self.fu is not None:
            return False                      # accept 循环还在
        if self.tiao is not None and self.tiao.is_alive():
            return False
        if self._huo_lian_zhong():
            return False
        with self.suo:
            if self.dui:
                return False
            if any(d.deng for d in self.dui.values()):
                return False
        return True

    def _huo_lian_zhong(self) -> int:
        """还活着的隧道连接处理线程数（自己登记的，不是数 `threading.enumerate`）。"""
        with self.suo:
            huo = set(self._chu_li)
        # 线程可能已经退出但还没摘掉登记（finally 与这里之间那一瞬），
        # 顺着 ident 核一遍活。
        return sum(1 for t in threading.enumerate() if t.ident in huo)

    def guan_bi_diagnostic(self) -> dict[str, Any]:
        """**关闭诊断**：回答「现在还剩什么没关掉」。"""
        with self.suo:
            xian = [t.name for t in threading.enumerate() if t.ident in set(self._chu_li)]
            lian = sorted(self.dui.keys())
            deng = sorted(r for d in self.dui.values() for r in d.deng)
        return {
            "guan_bi_wan_cheng": self.guan_bi_wan_cheng_ma(),
            "ting_lei": self._ting_lei.is_set(),
            "huo_lian_zhong": len(lian),
            "huo_xian_cheng": len(xian),
            "xian_cheng_ming": xian,
            "zai_tu_deng": len(deng),
            "zai_tu_id": deng,
            "ting_zhi_lei_xian_cheng": (self.tiao.name if (self.tiao
                                                           and self.tiao.is_alive())
                                        else None),
            "shuo_ming": "guan_bi_wan_cheng 为假时，huo_lian_zhong / huo_xian_cheng / "
                         "zai_tu_deng 就是还没关掉的东西",
        }

    def _zai_dian(self, a1: str) -> dict[str, queue.Queue]:
        """某设备当前的在途请求表。**只给诊断与测试看**，别拿它当业务接口。"""
        with self.suo:
            d = self.dui.get(a1)
            return dict(d.deng) if d is not None else {}

    # ---------- 查表 ----------
    def ren_wu(self, a1: str) -> Dui | None:
        with self.suo:
            d = self.dui.get(a1)
            return d if (d is not None and d.sheng) else None

    def zhuang_tai(self, a1: str) -> str:
        return "connected" if self.ren_wu(a1) is not None else "offline"

    def duan(self, a1: str) -> None:
        """主动断开某设备的隧道（任务 4 的 unpair 用，7.4）。"""
        d = self.ren_wu(a1)
        if d is not None:
            d.fa_wen(zhen("bye", reason="unpaired"))
            d.guan()

    # ---------- 限流（15.4） ----------
    def xian_liu(self, a1: str, a2: str, a3: str) -> float | None:
        """(userId, deviceId, path) → 超限返回 Retry-After 秒数，否则 None。

        **在网关这一层执行**（spec 10.1 的分层原则）：网关是入口，且它已经按
        deviceId/userId 建了索引。Bridge 那边的会话数与 SSE 连接数是数据所在
        的一层，限速不归它管。
        """
        return self.xian.guo(a1, a2, a3)

    # ---------- 请求转发 ----------
    def _zhai(self, a1: str, a2: str) -> None:
        """摘掉一个在途请求。必须在 finally 里调，否则队列永久泄漏。"""
        with self.suo:
            d = self.dui.get(a1)
            if d is not None:
                d.deng.pop(a2, None)

    def _song(self, a1: Dui, a2: dict[str, Any], a3: float,
              a4: bool) -> tuple[str, queue.Queue]:
        """发一个 request 并返回 (rid, 队列)。a4=True 表示这是长响应。

        「重查 `sheng` + 判在途上限 + 插入」三件事**一起**放在 `self.suo` 里：那是
        与 `_lai` 的 finally（同锁内「置 sheng + 唤醒 + clear」）互斥的唯一手段。
        调用方 `ren_wu()` 放行到插入之间隔着一次会放开 GIL 的 `secrets.token_hex()`
        （内部走 `os.urandom`），两处不持同一把锁就会出现「插进一张已经 clear 过的
        表」——那条队列永远等不到唤醒，只能挂到自己的超时。

        **`fa_wen` 必须留在锁外**：它内部要拿 `_fa_suo`，`lian.send()` 还可能阻塞，
        拖进锁里等于把一条发不出去的消息变成全设备请求一起排队。

        **出口只走 `zhi_qiu` 一条路**（spec 6.2 的契约层），它造出来的 request
        必然合法。放在持锁之前、动表之前：`zhi_qiu` 抛 `XieYiCuoWu` 说明调用方
        （反代）组错了请求，那是编程错误——**让它炸出声**，不伪装成 502，也不能
        在表里留下一条刚插进去就得回滚的队列。
        """
        rid = "r-" + secrets.token_hex(4)
        wen = zhi_qiu(rid, a2)
        ku: queue.Queue = queue.Queue(maxsize=DENG_LI)
        with self.suo:
            if not a1.sheng:
                raise WuDui("agent_unavailable", "隧道已断开")
            if len(a1.deng) >= DENG_LI:
                raise WuDui("agent_unavailable", "设备上在途请求过多")
            a1.deng[rid] = ku
        if not a1.fa_wen(wen):
            self._zhai(a1.deviceId, rid)
            raise WuDui("agent_unavailable", "隧道已断开")
        return rid, ku

    def _deng_hui(self, a1: Dui, a2: str, a3: queue.Queue,
                  a4: float) -> dict[str, Any]:
        """等一条 response，归一化成 `qing` 的返回形状（{status, headers, body, b64}）。

        **任何失败都在这里变成 `WuDui` 并摘掉队列**：超时、不是 response 帧、
        Bridge 回的字段不合契约。漏出去的非 `WuDui` 异常上层接不住（任务 8 写
        的是 `except WuDui`，会回 500 而不是约定的 502）；不摘队列则每条吃掉
        `DENG_LI` 里的一个名额，攒满后整台设备被自己的 Bridge 拖死到重连为止。

        字段校验走 `xie_yi.jie_ying`——不在这一处各写一套 `int()/dict()/str()/
        bool()`。它抛 `XieYiCuoWu`，翻成 `WuDui` 时把原因记进日志：502 的对外
        文案保持「设备响应不合法」不变，排障要的那一句在日志里。

        **这里回 502，与 `_fen_fa` 对畸形 id「断开隧道」的处置不矛盾，别统一。**
        两者的语境不同：坏字段只说明**这一条 HTTP 请求拿不到干净响应**，隧道本身
        还可信；畸形 id 说明**对端发了一个我们不可能发出的 id**，是两端实现不一致、
        整条隧道不可信。往这边统一（坏字段也拆隧道）＝一次坏响应变成用户可见的
        重连 + snapshot；往那边统一（畸形 id 也回 502）＝写着「隧道不可信」的消息
        被当成一次普通请求失败放过，下一个请求照样往这条隧道上送。

        摘队列用「成功标志 + finally」而不是无条件 finally：`kai_liu` **成功**时不能
        摘——帧还要从同一条队列里取，摘的时机在 `Liu.guan()`。
        """
        cheng = False
        try:
            try:
                x = a3.get(timeout=a4)
            except queue.Empty:
                raise WuDui("agent_unavailable", "设备无响应") from None
            if x.get("t") != "response":
                raise WuDui("agent_unavailable", "设备侧连接中断")
            try:
                y = jie_ying(x)
            except XieYiCuoWu as e:
                self.ri.warning("设备 %s 的 response 不合契约：%s", a1.deviceId, e.message)
                raise WuDui("agent_unavailable", "设备响应不合法") from None
            cheng = True
            return {"status": y.status, "headers": y.headers,
                    "body": y.body, "b64": y.b64}
        finally:
            if not cheng:
                self._zhai(a1.deviceId, a2)

    def qing(self, a1: str, a2: dict[str, Any], a3: float = DENG) -> dict[str, Any]:
        """一次性请求。返回 {status, headers, body, b64}；失败抛 WuDui。"""
        d = self.ren_wu(a1)
        if d is None:
            raise WuDui("agent_unavailable", "设备不在线")
        rid, ku = self._song(d, a2, a3, False)
        try:
            return self._deng_hui(d, rid, ku, a3)
        finally:
            # 一次性请求成功也摘（失败时 `_deng_hui` 已摘过，重复摘是幂等的）。
            self._zhai(d.deviceId, rid)

    def kai_liu(self, a1: str, a2: dict[str, Any],
                a3: float = DENG) -> tuple[dict[str, Any], Liu]:
        """长响应（SSE）。返回 (响应头, 流句柄)。

        **头之后队列不能摘** —— 帧还要从同一条队列里取。摘的时机在 `Liu.guan()`。
        """
        d = self.ren_wu(a1)
        if d is None:
            raise WuDui("agent_unavailable", "设备不在线")
        rid, ku = self._song(d, a2, a3, True)
        tou = self._deng_hui(d, rid, ku, a3)
        return ({"status": tou["status"], "headers": tou["headers"]},
                Liu(self, a1, rid, ku))

    # ---------- 握手 ----------
    def _shou_men(self, a1: Any, a2: Any) -> Response | None:
        """握手校验。**必须在 process_request 里回状态码**，理由见模块顶部第 4 条。"""
        if a2.path.split("?", 1)[0] != LU_JING:
            return Response(404, "Not Found", Headers({"content-type": "text/plain"}), b"no such path")
        if a2.headers.get("x-protocol-version") != XIYI:
            return Response(400, "Bad Request", Headers({"content-type": "text/plain"}),
                            b"protocol version")
        ma = a2.headers.get("authorization") or ""
        if not ma.lower().startswith("bearer "):
            return Response(401, "Unauthorized", Headers({"content-type": "text/plain"}), b"no token")
        ji, yuan = self.biao.ren(ma[7:].strip())
        if ji is None:
            # 401 = 令牌不对；403 = 设备已解绑。两者对客户端是同一件事
            # （都停止重连），但分开回便于排障。
            ma_zhuang = 403 if yuan == "revoked" else 401
            return Response(ma_zhuang, "Forbidden" if yuan == "revoked" else "Unauthorized",
                            Headers({"content-type": "text/plain"}), b"rejected")
        if self._ting_lei.is_set():
            # 已发起关闭：不再接受新握手。**这是「完成」的第一项**——端口还在
            # accept 循环的关闭过程中，一个新连接能挤进来建一条没人管的隧道。
            return Response(503, "Service Unavailable",
                            Headers({"content-type": "text/plain"}), b"shutting down")
        # 把设备记录挂到连接对象上给 handler 用（handshake 是方法，取不到请求）。
        a1.she_bei = ji
        a1.qing_qiu = a2
        return None

    def _lai(self, a1: Any) -> None:
        """一条隧道的生命周期。跑在 websockets 自己的线程里。"""
        # 登记自己：关闭诊断要能回答「还有几条隧道在跑」，而这个答案只能
        # 由真正跑着 `_lai` 的线程自己交出来（`finally` 里摘掉）。
        with self.suo:
            self._chu_li.add(threading.get_ident())
        try:
            self._lai_nei(a1)
        finally:
            with self.suo:
                self._chu_li.discard(threading.get_ident())

    def _lai_nei(self, a1: Any) -> None:
        ji = getattr(a1, "she_bei", None)
        if ji is None:
            a1.close()
            return
        d = Dui(ji["deviceId"], ji["userId"], a1)
        # 后连踢先连：换表与标记旧的在**同一把锁**内完成，否则并发握手时
        # 两条都可能活下来。旧连接不能在锁内 close()（可能阻塞），
        # 只标 sheng=False，让它的接收循环自己退出。
        jiu = None
        gua = False
        with self.suo:
            jiu = self.dui.get(d.deviceId)
            self.dui[d.deviceId] = d
            # **装表之后必须再读一次活的 `revoked`。** 握手校验与装表之间没有任何
            # 锁能互斥：`jie()` 只拿 `SheBiao.suo`，`duan()` 又是解绑之后才跑。所以
            # 「校验放行 → 解绑 → duan(表里还没有这条) → 装表」这条交错真实存在，
            # 落进去的设备会带着一条永久隧道，还会被下面的 `jian_shi()` 刷新
            # lastSeenAt（前端于是显示一台早已失效的设备刚刚还在线）。
            # 复查必须落在**装表之后、同一个 `self.suo` 内**：只有这样，从装表到
            # 「是否放弃」的判断之间才没有可被 `jie()` 插进来的缝。装表前复查只是把
            # 停顿挪了个位置，缝还在（`_xie()` 里的 icacls 与 `os.replace` 会释放
            # GIL，字节码级的原子性挡不住它）。`ji` 是 `SheBiao.she` 里的活对象引用，
            # 这里读到的就是当下真实的标志。
            if ji.get("revoked"):
                # `is d` 是必要的：别把后来者那条表项撞掉。
                if self.dui.get(d.deviceId) is d:
                    self.dui.pop(d.deviceId, None)
                gua = True
        if jiu is not None:
            jiu.sheng = False
            jiu.guan()
        if gua:
            # 放弃路径不进 try：此时 `d.deng` 还是空的（一个请求都还没发出去），
            # 没有等待方需要唤醒，也绝不能给已解绑设备发 welcome。
            a1.close()
            return
        try:
            self.biao.jian_shi(d.deviceId)
            if not d.fa_wen(zhen("welcome", deviceId=d.deviceId, userId=d.userId)):
                return
            self._shou_huan(d)
        except Exception as e:  # noqa: BLE001 - 一条隧道的异常不能拖垮网关
            self.ri.warning("隧道 %s 异常退出：%s", d.deviceId, type(e).__name__)
        finally:
            # 置 sheng + 唤醒 + clear 必须与 `_song` 的「重查 + 插入」互斥（同一把
            # `self.suo`）。两处各写各的话，请求线程可能在 `ren_wu()` 放行之后、插入
            # 之前被 `clear()` 抢先，留下一条永远收不到唤醒的队列。
            # `put_nowait` 永不阻塞，所以持锁期间不会碰到 `_fa_suo`／`send()`——
            # 「持锁会把阻塞的 send 拖进拆隧道路径」是把 deng 表的锁和发送锁混了。
            with self.suo:
                d.sheng = False
                # **必须唤醒所有等待方。** 不唤醒的话，正在等审批响应的那个 HTTP
                # 线程会一直挂在 queue.get 上，直到自己的超时——而它的超时是 30 秒，
                # 期间浏览器在转圈、Bridge 侧那条请求也永远不会被清理。
                # 写在 finally（不是 except）：`ting_zhi()` 从另一个线程关隧道走的
                # 就是 except 分支，只写 except 会漏掉那条路径。
                for ku in list(d.deng.values()):
                    try:
                        ku.put_nowait({"t": "__end__"})
                    except queue.Full:
                        pass
                d.deng.clear()
                if self.dui.get(d.deviceId) is d:
                    self.dui.pop(d.deviceId, None)

    def _shou_huan(self, a1: Dui) -> None:
        """接收循环。"""
        while a1.sheng:
            try:
                wen = a1.lian.recv(timeout=1.0)
            except TimeoutError:
                continue
            except Exception:  # noqa: BLE001
                break
            x = jie(wen)
            if x is None:
                self.ri.warning("隧道 %s 发来无法解析的消息，断开", a1.deviceId)
                break
            if not self._fen_fa(a1, x):
                break

    def _zheng(self, a1: Dui, a2: dict[str, Any], a3: str) -> int | None:
        """取 `hello` 里的一个整数字段。不合法返回 None（已记 warning，调用方断开）。

        `hello` 的两个整数字段（`streamEpoch` / `sessions`）共用它——那个
        `int(x.get(k) or 0)` 的写法正是 `xie_yi.py` 要消灭的东西，别抄第三遍。

        **只在解析处校一次**：不校的话 `"abc"` 抛出的 ValueError 会穿过 `_fen_fa`，
        被 `_lai` 的兜底 except 记成一句笼统的「隧道异常退出」，排障时不知道是哪个
        字段坏。`instanceId` / `version` / `cliVersion` 是 `str(x.get(k) or "")`，
        取到什么都是 str，没有这个形状，不进这里。
        """
        try:
            return int(a2.get(a3) or 0)
        except (TypeError, ValueError):
            self.ri.warning("隧道 %s 的 hello.%s 不是数字，断开", a1.deviceId, a3)
            return None

    def _yan_hao(self, a1: Dui, a2: str, a3: dict[str, Any]) -> str | None:
        """取一条消息的 `requestId`。畸形返回 None（已记 warning，调用方断开）。

        **只管「畸形」，不管「查不到表」**（Ruling 2b，两者处置相反）：

        | 情形 | 处置 |
        |---|---|
        | id 不合 `^r-[0-9a-f]{8}$` | warning + 断开——对端发了一个我们不可能
          发出的 id，是两端实现不一致 |
        | id 合法但 `deng` 里没有 | **静默忽略**——请求超时后 `_zhai` 已摘表，
          迟到的 frame 无处可去，这是正常路径 |

        把第二种也当错误断开，会把「一次普通超时」升级成「整条隧道拆掉重建」：
        前端看到的是无谓的重连 + snapshot，代价远大于收益。
        """
        rid = a3.get("id")
        if not he_hao(rid):
            self.ri.warning("隧道 %s 的 %s 带着畸形 id %r，断开",
                            a1.deviceId, a2, rid)
            return None
        return rid

    def _fen_fa(self, a1: Dui, a2: dict[str, Any]) -> bool:
        """按消息类型分发。返回 False 表示对端不合契约，调用方断开接收循环。

        畸形 id 与坏载荷在这里**断开隧道**，而 `_deng_hui` 把坏字段翻成 502——
        两回事，别「统一」：这里的语境是「这条隧道不可信」（对端发了一个我们
        不可能发出的 id，或 frame 根本不是对象），那一次 HTTP 请求失败不该
        连带拆掉隧道。
        """
        lei = a2.get("t")
        if lei == "hello":
            # `hello` 的两个整数字段走同一个助手。**入站字段的取值必须在解析处
            # 被校验**（spec 第 19 章那条不变式）：`"abc"` 会让 `int()` 抛
            # ValueError 冲出 `_fen_fa`，被 `_lai` 的兜底 except 记成一句笼统的
            # 「隧道异常退出」——症状一样（隧道莫名断、日志难读），两个字段都要校。
            qi = self._zheng(a1, a2, "streamEpoch")
            zhan = self._zheng(a1, a2, "sessions")
            if qi is None or zhan is None:
                return False
            a1.instanceId = str(a2.get("instanceId") or "")
            a1.streamEpoch = qi
            a1.cliVersion = str(a2.get("cliVersion") or "")
            a1.sessions = zhan
            return True
        if lei == "response":
            rid = self._yan_hao(a1, lei, a2)
            if rid is None:
                return False
            ku = a1.deng.get(rid)
            if ku is not None:
                try:
                    ku.put_nowait(a2)
                except queue.Full:
                    pass
            return True
        if lei == "frame":
            rid = self._yan_hao(a1, lei, a2)
            if rid is None:
                return False
            nei = a2.get("frame")
            # **只校信封键，不校帧内容。** 15.3.2「网关不解析帧内容」禁的是解析/
            # 改写帧的**业务 payload**；`type` / `streamSeq` 是 SSE 的信封键，
            # `xie_zhen` 必须能用它们写出合法的 `event:` 与 `id:` 行。所以这里校
            # 的是「这帧写得出去吗」，不是「这帧说了什么」——**别为了「不改内容」
            # 的字面把它删掉**：缺 `type` 的 frame 会让 `xie_zhen` KeyError，而那条
            # 路（server.py 的 `_dai_liu`）只 except `WuDui`，异常会逃出去，
            # 前端连 offline 帧都拿不到。
            if not isinstance(nei, dict):
                self.ri.warning("隧道 %s 的 frame 不是对象，断开", a1.deviceId)
                return False
            if not isinstance(nei.get("type"), str) or "streamSeq" not in nei:
                self.ri.warning("隧道 %s 的 frame 缺信封键（type/streamSeq），断开",
                                a1.deviceId)
                return False
            ku = a1.deng.get(rid)
            if ku is not None:
                try:
                    ku.put_nowait({"t": "frame", "frame": a2["frame"]})
                except queue.Full:
                    # 帧队列满说明消费端卡住了。丢帧是安全的：前端会走
                    # 重连 + snapshot 补齐（7.2.4）；阻塞则会拖死整条隧道。
                    pass
            return True
        if lei == "close":
            # **close 是双向的。** 网关 → Bridge：浏览器走了，关掉那条本地连接。
            # Bridge → 网关：这条流自己结束了，别再等。同一个类型表达
            # 「这个 requestId 结束了」，两个方向的含义对称。
            rid = self._yan_hao(a1, lei, a2)
            if rid is None:
                return False
            ku = a1.deng.get(rid)
            if ku is not None:
                try:
                    ku.put_nowait({"t": "__end__"})
                except queue.Full:
                    pass
            return True
        self.ri.warning("隧道 %s 发来未知消息类型 %r", a1.deviceId, lei)
        return True
