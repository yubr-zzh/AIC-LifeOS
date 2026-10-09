"""阶段 6 真机验收（方案 12.7 / spec 14.2）。

退出条件原文是「从另一台机器访问公网域名，完整走通一次委派往返（含权限审批）」；
**本阶段的达成度**是它的环回近似——**两个独立进程树，全程只经 WebSocket 隧道通信，
不碰 `runtime.json` 里的端口**：

    ┌─── 进程树 A：python -m lifeos.api.server ───────────────────────┐
    │   8765 主服务（/agent-api/* 反代） + 8771 隧道网关（同进程另线程）│
    └──────────────────────────────────────────────────────────────────┘
              ↑ 只有这一条 /agent-api/* 通道 ↑↓ ws://127.0.0.1:8771/bridge/tunnel
    ┌─── 进程树 B：python -m lifeos.bridge.run ───────────────────────┐
    │   8766-8770 Bridge 自己的 HTTP 服务（配对那一趟用过，之后再不碰）  │
    └──────────────────────────────────────────────────────────────────┘

七步（spec 14.2 为准）：

0. **负向断言**（并进第 1 步）：不带合法配对码直连隧道网关 → 必须 401。
1. 起主服务 + 网关（进程树 A），起 Bridge（进程树 B，先 `LIFEOS_JIAOJIE=local`）。
2. `POST /api/bridge/pair-code` → 本机 `POST /pair` → runtime.json 出现
   `deviceId` / `deviceToken`。
3. 重启 Bridge（`LIFEOS_JIAOJIE=tunnel`）→ `tunnelState=connected`，
   snapshot 的 `instanceId` / `streamEpoch` 与 runtime.json 一致。
4. **只经 `/agent-api/*`**：建会话 → 发指令 → 断言指令真的抵达 Agent。
5. 经 `/agent-api/permissions/{rid}` 点允许 → Agent 继续跑完（第一条 `result`）；
   再发一条触发提问 → 经 `/agent-api/questions/{qid}` 作答 → 第二条 `result`。
6. 再造一个会话让它挂着一条审批 → **掐断网关**（杀掉进程树 A）→ 观察 N 秒 →
   断言窗口内零审批决定、Bridge 全程活着。**为什么观察 540 秒，见 `guan_cha()`。**
7. 重启网关 → 重连成功（`device_status{connected}`、snapshot 的 `instanceId` 未变）
   → 断线期间挂着的那条审批**还能点允许并跑完** → 同一个 `deviceToken` 开第二条
   隧道把第一条顶掉。

**为什么用 echo 适配器而不是 claude-code。** 本脚本验的是隧道与反代，不是模型行为；
真 Claude 要耗额度，且每次生成的 `tool_use_id` 都不同，断言没法写稳。echo 的第 1 条
指令固定发一次 Bash 审批（`toolUseId=tool-echo-1`）、第 2 条固定发一次提问，
正好把「审批往返」和「提问往返」两条路都走一遍。

**第 6 步为什么必须用第二个会话。** echo 的 `fasong()` 按本会话收到过的指令条数分支
（`adapters/echo.py`：第 1 条发审批、第 2 条发提问，之后什么都不发），**一个会话只能
保护一条审批**。而第 5 步已经用掉了会话 A 的那一次。所以第 6 步要保护的那条挂起审批
来自新建的会话 B —— 这不是多余的步骤，是 echo 的行为决定的。

**pid 不能用 `subprocess.Popen().pid`。** venv 的 `python.exe` 是启动器，真正的解释器
是它的子进程，两者 pid 不同（阶段 5 实测 24188 vs 10620）。杀 Bridge 要用
runtime.json 里那个 pid，杀主服务进程树要用 Popen 那个 pid（`/T` 带走整棵树，
网关就在那棵树里）。

**Windows 死穴：`os.kill(pid, 0)` 会静默杀掉目标进程。** 判活一律走 `cun_zhen()`
的 ctypes 路子（`OpenProcess` + `GetExitCodeProcess` 判 259 STILL_ACTIVE）。

用法：
    ./.venv/Scripts/python.exe tools/verify_stage6.py              # 全七步
    ./.venv/Scripts/python.exe tools/verify_stage6.py --guan 5     # 第 6 步只看 5 秒

⚠ **当前（2026-09-29）本机跑会在第 3 步停下**：`lifeos/bridge/tunnel.py::_liu` 的
`a2.read(4096)` 在 chunked 响应上会等满 4096 字节才返回，安静会话下一帧都搬不回来
（首帧 snapshot 与审批卡永远不出现）。一次性请求那条路是好的，整条委派往返走得通，
坏的只是实时推送。细节与修复方向见任务 11 报告的第 3 节。**脚本本身没有为此放宽任何断言。**
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
SHU = ROOT / ".lifeos" / "bridge"
RT = SHU / "runtime.json"                # Bridge 的运行时文件（端口/pid/deviceToken）
JUE = SHU / "decisions.jsonl"            # 审批决定流水：每次收口追加一条
ZHU_RI = SHU / "verify_stage6_zhu.log"   # 主服务+网关进程的 stdout/stderr
BR_RI = SHU / "verify_stage6_bridge.log"  # Bridge 进程的 stdout/stderr
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 主服务端口：**从环境变量读，8765 只作默认**（照 `server.py:749` 的口径，
# 阶段 7 要在同一台机器上跑两套栈）。配对时 Bridge 靠 LIFEOS_MAIN_URL 找到它。
ZHU_DUAN = int(os.environ.get("LIFEOS_PORT") or 8765)
BASE = "http://127.0.0.1:%d" % ZHU_DUAN
# 隧道网关端口：**钉死 8771，不读 LIFEOS_GW_PORT**。`server.py:754` 认那个变量，
# 但 `tunnel.py:47` 的出站地址是写死的默认值，而 `run.py` 组 cfg 时**不传 url 键**
# ⇒ Bridge 只会连 8771。两边今天无法分别配置（要改就是改 lifeos/，本脚本不许改实现）。
# 所以这里识别到有人设了别的值就明确报错退出，而不是让第 3 步对着一个永远连不上
# 的地址超时——那种失败的现场（连不上、无日志、无状态码）什么都看不出来。
GW_DUAN = 8771
LU_JING = "/bridge/tunnel"          # 网关的 WS 路径（tunnel_gw.LU_JING）
YUAN = "http://127.0.0.1:5173"      # 反代来源白名单里的一项（server.YUAN_BAI）
GUAN = 540.0                        # 第 6 步观察窗口默认秒数
LIU_GEN = 45.0                      # 等一个具体帧的上限

jieguo: list[tuple[str, bool, str]] = []


def ji(a1: str, a2: bool, a3: str = "") -> None:
    """记一条断言。与 verify_stage5.py 同一形状。"""
    jieguo.append((a1, a2, a3))
    print("[%s] %s%s" % ("PASS" if a2 else "FAIL", a1,
                         ("  —— " + a3) if a3 else ""), flush=True)


def bao(a1: str, a2: str = "") -> None:
    """打印一行现场信息（不是断言）。"""
    print("[验收] %s%s" % (a1, ("：" + a2) if a2 else ""), flush=True)


# ---------- 进程与端口助手 ----------

def cun_zhen(a1: int) -> bool:
    """判断进程是否存活。

    **不要用 `os.kill(pid, 0)`。** Windows 上 CPython 对 sig 既不是
    CTRL_C_EVENT/CTRL_BREAK_EVENT 的值一律走 TerminateProcess(handle, 0)——
    也就是说 `os.kill(pid, 0)` 不是抛异常，而是**静默杀掉那个进程**。
    """
    if a1 <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        P = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
        k = ctypes.windll.kernel32
        h = k.OpenProcess(P, False, a1)
        if not h:
            return False
        try:
            ma = ctypes.c_ulong()
            if not k.GetExitCodeProcess(h, ctypes.byref(ma)):
                return False
            return ma.value == 259  # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(a1, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def sha_si(a1: int) -> bool:
    """强杀（含整棵进程树）。返回是否还活着。

    **必须 `/T`**：Bridge 与主服务都会 spawn 真子进程（claude / websockets 的
    服务线程不带进程，但 Bridge 的 Agent 子进程是进程），只杀父进程会留下带着
    用户全部权限的孤儿。
    """
    if a1 <= 0 or not cun_zhen(a1):
        return False
    subprocess.run(["taskkill", "/PID", str(a1), "/T", "/F"],
                   capture_output=True, timeout=30)
    for _ in range(60):
        if not cun_zhen(a1):
            return False
        time.sleep(0.2)
    return cun_zhen(a1)


def duan_kong(a1: int) -> bool:
    """端口是否可绑（bind 之后还要 listen，Windows 上只 bind 测不出被占）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", a1))
            s.listen(1)
            return True
        except OSError:
            return False


def du_rt() -> dict:
    try:
        return json.loads(RT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 读不到/读坏一律按空对象，调用方自己判断
        return {}


def du_jue(a1: float) -> list[dict]:
    """decisions.jsonl 里收口时间 ≥ a1 的决定。

    **判据必须限定在本次运行之内。** decisions.jsonl 有保留期，上一次验收留下的
    记录会让「窗口内零决定」恒真——收口整个断了也照样绿。这里只认 `at` 晚于调用方
    给的那个时刻的。
    """
    try:
        wen = JUE.read_text(encoding="utf-8")
    except OSError:
        return []
    chu = []
    for hang in wen.splitlines():
        hang = hang.strip()
        if not hang:
            continue
        try:
            x = json.loads(hang)
        except ValueError:
            continue
        try:
            at = float(x.get("at") or 0)
        except (TypeError, ValueError):
            continue
        if at >= a1:
            chu.append(x)
    return chu


# ---------- HTTP 客户端 ----------

class Qiao:
    """主服务的 HTTP 客户端。

    **POST 一律自带新取的一次性 CSRF token**：`server._fangxing()` 对
    `/agent-api/*` 的 POST 与 `/api/bridge/pair-code` 都强制 CSRF，而
    `bridge_admin.yong_ma()` 是「用过即作废」。所以每个 POST 前先 GET 一次
    `/api/bridge/info` 拿新 token（那个端点只读、不轮换）。

    **Origin 头必带**：`_pan_yuan()` 判「是不是浏览器来源」，`/stream` 这条对
    无来源头的请求直接 403。白名单里取 5173（`server.YUAN_BAI`）。
    """

    def __init__(self, a1: str) -> None:
        self.base = a1

    def _kai(self, a1: str, a2: str = "GET", a3: dict | None = None,
             a4: bool = False, a5: float = 30.0):
        tou = {"Origin": YUAN}
        if a4:
            ma = self.ma()
            if not ma:
                raise SystemExit("[验收] 拿不到 CSRF token，主服务没起来？")
            tou["X-LifeOS-CSRF"] = ma
        shu = None
        if a3 is not None:
            shu = json.dumps(a3, ensure_ascii=False).encode("utf-8")
            tou["content-type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(self.base + a1, data=shu, method=a2, headers=tou)
        try:
            return OP.open(req, timeout=a5)
        except urllib.error.HTTPError as e:
            return e

    def get(self, a1: str) -> dict:
        with self._kai(a1) as r:
            return json.loads(r.read().decode("utf-8"))

    def ma(self) -> str:
        """取一个还没用过的一次性 CSRF token。"""
        try:
            with self._kai("/api/bridge/info") as r:
                return str(json.loads(r.read().decode("utf-8")).get("csrf") or "")
        except Exception as e:  # noqa: BLE001
            bao("GET /api/bridge/info 失败", "%s: %s" % (type(e).__name__, e))
            return ""

    def get_ma(self, a1: str) -> dict:
        """带 CSRF 的 GET（`/api/bridge/devices` 这类管控端点要）。"""
        with self._kai(a1, "GET", None, True) as r:
            return json.loads(r.read().decode("utf-8"))

    def post(self, a1: str, a2: dict | None = None) -> tuple[int, dict]:
        """POST（带 CSRF）。返回 (状态码, 解析后的 body)。"""
        with self._kai(a1, "POST", a2 or {}, True) as r:
            try:
                return r.status, json.loads(r.read().decode("utf-8"))
            except ValueError:
                return r.status, {}


class Liu:
    """后台读 `/agent-api/stream` 的 SSE，把 `data:` 行解析成帧塞进队列。

    **这条流本身就是隧道在通的最硬凭据**：请求打进主服务，主服务反代塞进隧道，
    Bridge 在本地起一条真 SSE，逐帧搬回来。所以第 3/7 步都用它当见证。

    `a2`（`last_seq`）非空时带 `?lastEventId=`，用 Bridge 的重放缓冲把断线期间的
    帧补回来（前端 `agentClient.ts` 的同一手法）。第 7 步要靠这段补发作两件事：
    拿到 `device_status{connected}` 帧、以及一份**重连之后**的新 snapshot。
    """

    def __init__(self, a1: int | None = None) -> None:
        self.ting = threading.Event()
        self.cuo = ""                # 流断掉的原因（空串 = 还没断）
        self.shou: list[dict] = []   # 到目前为止收到的全部帧
        self.suo = threading.Lock()
        self.wei = 0                 # 前向游标：已检查到第几帧
        self.tou = 0                 # 建流的 HTTP 状态码
        lu = BASE + "/agent-api/stream"
        if a1 is not None:
            lu += "?lastEventId=%d" % a1
        req = urllib.request.Request(lu)
        req.add_header("Origin", YUAN)
        self.t = threading.Thread(target=self._pao, args=(req,), daemon=True)
        self.t.start()

    def _pao(self, a1) -> None:
        try:
            r = OP.open(a1, timeout=180)
            self.tou = int(r.status)   # 建流的 HTTP 状态码（403=来源头不对）
        except Exception as e:  # noqa: BLE001
            self.cuo = "建流失败：%s: %s" % (type(e).__name__, e)
            return
        try:
            while not self.ting.is_set():
                hang = r.readline()
                if not hang:
                    break   # 服务端关了流（正常结束）
                hang = hang.decode("utf-8", "replace").strip()
                if hang.startswith("data:"):
                    try:
                        z = json.loads(hang[5:].strip())
                    except ValueError:
                        continue
                    with self.suo:
                        self.shou.append(z)
        except Exception as e:  # noqa: BLE001
            self.cuo = "读流中断：%s: %s" % (type(e).__name__, e)
        finally:
            try:
                r.close()
            except Exception:  # noqa: BLE001
                pass

    def deng(self, a1, a2: float = LIU_GEN) -> tuple[dict | None, list[dict]]:
        """等一个满足 a1 的帧。返回 (帧, 从游标到命中之间的那段帧)。

        **前向游标**（`wei`）：每帧按到达顺序只被检查一次。既不许跳过，
        也不许重复命中同一个帧。

        这里栽过两次，两次都是「助手静默丢帧」，形状相同：
        - 队列消费式：不匹配的帧取出来就丢了。第 5 步等提问的那 30 秒里
          真正到来的权限卡被吞掉，之后再等它永远等不到。
        - 「只扫本次调用之后新到的帧」：权限帧在上一次 `deng` 之后、本次
          `deng` 开始之前就到了，于是被整体跳过，白等 30 秒后报 None，
          而现场里明明有那一帧（2026-09-29 实测，失败消息里看得见）。

        本脚本的用法是严格按序等（permission → resolved → result → question →
        resolved → result），所以前向游标正是对的语义。
        """
        jixu = time.monotonic() + a2
        while time.monotonic() < jixu:
            with self.suo:
                duan = self.shou[self.wei:]
                for xu, z in enumerate(duan):
                    if a1(z):
                        # **必须是 wei + xu + 1，不是 wei + 1。** 写成 wei + 1 时
                        # 游标只前进一格，下一次 deng 会把中间这些帧重新扫一遍、
                        # **重复命中同一个帧**——第 5 步的 `jie2 is not None` 就是
                        # 这样绿的，而它拿到的是 result#1。断言过了，验的是同一帧。
                        self.wei = self.wei + xu + 1
                        return z, duan
                self.wei = len(self.shou)
            if self.cuo:
                return None, self.shou[-6:]
            time.sleep(0.02)
        return None, self.shou[-6:]

    def xian_chang(self, a1: int = 12) -> str:
        """最近 a1 帧的一句话摘要，给失败消息带现场用。"""
        with self.suo:
            zu = self.shou[-a1:]
        return "；".join("%s/%s" % (z.get("type"), (z.get("sessionId") or "")[:12])
                        for z in zu) or "（一帧都没收到）"

    def huo(self) -> bool:
        """这条流还活着吗（读线程还在跑）。"""
        return self.t.is_alive()

    def ting_zhi(self) -> None:
        self.ting.set()


# ---------- 隧道握手（负向断言与第二条隧道） ----------

def lian_wang(a1: str) -> int:
    """不带合法凭据连一次网关，返回握手被拒的 HTTP 状态码。

    连上了返回 0（那本身就是要报的缺陷），连都连不上返回 -1。
    **必须 `proxy=None`**：本机设着 HTTP_PROXY，而 `websockets.sync.client`
    的 `proxy` 默认 True 会读环境变量，把回环连接送去代理（`tunnel.py` 踩过同一个坑）。
    """
    from websockets.exceptions import InvalidStatus
    from websockets.sync.client import connect

    tou = {"X-Protocol-Version": "1"}
    if a1:
        tou["Authorization"] = a1
    try:
        with connect("ws://127.0.0.1:%d%s" % (GW_DUAN, LU_JING),
                     additional_headers=tou, proxy=None, open_timeout=10):
            return 0
    except InvalidStatus as e:
        return int(e.response.status_code)
    except Exception as e:  # noqa: BLE001
        bao("连网关失败", "%s: %s" % (type(e).__name__, e))
        return -1


def kai_lang(a1: str, a2: int) -> tuple[object | None, str]:
    """用同一个 deviceToken 开第二条隧道。返回 (连接, 失败原因)。"""
    from websockets.exceptions import InvalidStatus
    from websockets.sync.client import connect

    try:
        k = connect("ws://127.0.0.1:%d%s" % (GW_DUAN, LU_JING),
                    additional_headers={"Authorization": "Bearer " + a1,
                                        "X-Protocol-Version": "1",
                                        "X-Instance-Id": "verify-stage6-rogue"},
                    proxy=None, open_timeout=10)
    except InvalidStatus as e:
        return None, "握手被拒 HTTP %s" % e.response.status_code
    except Exception as e:  # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)
    # hello 的两个整数字段校过格式（`tunnel_gw._zheng`），瞎填会被网关断开。
    k.send(json.dumps({"t": "hello", "instanceId": "verify-stage6-rogue",
                       "streamEpoch": int(a2), "version": "2.0",
                       "cliVersion": "verify_stage6", "sessions": 0}))
    return k, ""


def yao_ren(a1: object) -> list[str]:
    """挂在第二条隧道上，直到被网关关掉。返回它观察到的结局描述。"""
    ji = []
    try:
        while True:
            wen = a1.recv(timeout=20)
            ji.append("收到：%s" % str(wen)[:80])
    except Exception as e:  # noqa: BLE001
        ji.append("连接结束：%s" % type(e).__name__)
    return ji


# ---------- 起进程 ----------

def qi_zhu() -> subprocess.Popen:
    """起主服务 + 隧道网关（**一个进程树**，`python -m lifeos.api.server`）。

    端口占用就明确报错退出：第 6 步要真掐断这个进程，第 7 步要真把它拉起来，
    借用别人正在跑的进程做不了这两件事——那种「看起来跑过去了」的验收正是本脚本
    要消灭的东西。
    """
    if not duan_kong(ZHU_DUAN):
        raise SystemExit(
            "[验收] 主服务端口 %d 已被占用。本脚本要自己掐断/重启这个进程树，"
            "不能借用别人的进程——请先停掉占用 %d 的东西再跑。" % (ZHU_DUAN, ZHU_DUAN))
    if not duan_kong(GW_DUAN):
        raise SystemExit("[验收] 隧道网关端口 %d 已被占用，先停掉它再跑。" % GW_DUAN)
    log = ZHU_RI.open("w", encoding="utf-8")
    huan = dict(os.environ)
    huan["LIFEOS_ROOT"] = str(ROOT)   # devices.json 的落点要确定，别跟着 cwd 漂
    p = subprocess.Popen([sys.executable, "-m", "lifeos.api.server"],
                         cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                         env=huan, text=True)
    qi = time.monotonic()
    while time.monotonic() - qi < 90:
        if p.poll() is not None:
            raise SystemExit("[验收] 主服务起来了又退出（%s）：\n%s"
                             % (p.returncode, ZHU_RI.read_text(encoding="utf-8")[:1200]))
        time.sleep(0.4)
        try:
            with OP.open(urllib.request.Request(BASE + "/api/bridge/info"),
                         timeout=3) as r:
                if r.status == 200:
                    return p
        except urllib.error.HTTPError:
            return p   # 回了错误码也算起来了（端口在服务）
        except Exception:  # noqa: BLE001
            continue
    raise SystemExit("[验收] 主服务 90 秒没起来：\n%s"
                     % ZHU_RI.read_text(encoding="utf-8")[:1200])


def qi_bridge(a1: str) -> tuple[subprocess.Popen, dict]:
    """起一个真 Bridge 进程（另一个进程树），等它写出新的 runtime.json 且 /health 通。

    `a1` 是 `LIFEOS_JIAOJIE` 的取值：`local`（阶段 1–5 的原样形态）或 `tunnel`。
    `LIFEOS_MAIN_URL` 必须指到这次的主服务端口——配对时 Bridge 要把配对码送到那里
    换凭据（`pipei.CLOUD` 在 import 时读一次环境变量）。
    """
    jiu = du_rt().get("pid")
    log = BR_RI.open("w" if a1 == "local" else "a", encoding="utf-8")
    huan = dict(os.environ)
    huan["LIFEOS_JIAOJIE"] = a1
    huan["LIFEOS_MAIN_URL"] = BASE
    p = subprocess.Popen([sys.executable, "-m", "lifeos.bridge.run",
                          "--root", str(ROOT)],
                         cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                         env=huan, text=True)
    d: dict = {}
    for _ in range(120):
        time.sleep(0.4)
        d = du_rt()
        if d.get("pid") and d.get("pid") != jiu:
            break
    if not d.get("pid") or d.get("pid") == jiu:
        log.flush()
        raise SystemExit("[验收] Bridge 没起来：\n%s"
                         % BR_RI.read_text(encoding="utf-8")[:1200])
    for _ in range(60):
        try:
            with OP.open(urllib.request.Request(
                    "http://127.0.0.1:%d/health" % int(d["port"])), timeout=3) as r:
                if json.loads(r.read().decode("utf-8")).get("ok"):
                    return p, d
        except Exception:  # noqa: BLE001
            time.sleep(0.25)
    raise SystemExit("[验收] Bridge 起了但 /health 不通（pid=%s port=%s）\n%s"
                     % (d.get("pid"), d.get("port"),
                        BR_RI.read_text(encoding="utf-8")[:1200]))


def biao_dan(a1: str, a2: dict) -> tuple[int, str]:
    """往 Bridge 本机端口 POST 一个表单（配对页 `HTML_PEI` 的原样提交方式）。

    **这是全脚本唯一一次直连 Bridge 的端口**：配对动作必须发生在本机页面（5.3），
    从第 3 步起一切只走 `/agent-api/*`。
    """
    shu = urllib.parse.urlencode(a2).encode("utf-8")
    req = urllib.request.Request(
        a1, data=shu, method="POST",
        headers={"content-type": "application/x-www-form-urlencoded; charset=utf-8"})
    try:
        with OP.open(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def deng_tunnel(a1: str, a2: float) -> str:
    """等 runtime.json 的 `tunnelState` 变成 a1。返回见过的状态序列。

    超时抛 SystemExit 并把**实际是什么**说出来——「等到超时」这四个字不带现场的
    话，排查的人只能重跑一遍。
    """
    jian: list = []
    zhong = time.monotonic() + a2
    while time.monotonic() < zhong:
        xian = str(du_rt().get("tunnelState"))
        if not jian or jian[-1] != xian:
            jian.append(xian)
        if xian == a1:
            return "→".join(jian)
        time.sleep(0.3)
    raise SystemExit("[验收] 等了 %.0f 秒 tunnelState 都没变成 %r：实际是 %r"
                     "（见过 %s）。Bridge 日志：\n%s"
                     % (a2, a1, du_rt().get("tunnelState"), jian,
                        BR_RI.read_text(encoding="utf-8")[-1200:]))


def deng_duan(a2: float) -> str:
    """等 `tunnelState` 离开 connected。返回见到的状态序列；没离开返回 ""。

    **这一步是第 6 步不是空转的凭据**：不证明隧道真的断了，那 540 秒就只是睡了
    一觉，什么也没验。
    """
    jian: list = []
    zhong = time.monotonic() + a2
    while time.monotonic() < zhong:
        xian = str(du_rt().get("tunnelState"))
        if not jian or jian[-1] != xian:
            jian.append(xian)
        if xian and xian != "connected":
            return "→".join(jian)
        time.sleep(0.3)
    return ""


def guan_cha(a1: float, a2: int, a3: float) -> tuple[bool, list, list]:
    """第 6 步的观察窗口。返回 (Bridge 全程活着吗, 见到的 tunnelState 序列, 窗口内新增的决定)。

    **为什么默认 540 秒，而不是原任务书写的那 90 秒。** 真实机制是这样：

    - `arbiter.py:40` `SHEN_HE = 600.0`；`:221` `threading.Timer(self.shi_ji, self._chao_shi)`
      ——审批超时定时器**起在 Bridge 进程内**，掐断网关动不了它；
    - 隧道断开只走 `tunnel.py:138` `_bao_zt("连接中断，正在重连")`，**不调
      `session.zhong_duan()`**（那条只由用户中断与停滞超时触发，见 `arbiter.zhong_duan`）。

    ⇒ 90 秒的窗口里 600 秒的超时压根没到，断言「没有 auto_deny」自然成立——
    **那是一句空断言**，把断线误触的那条路径整根跳过也照样绿。

    **本条不变式是「断线本身不得提前否决一个用户回来还能批准的审批」。** 若真存在
    那条误触路径（`zhong_duan()` 是同步调用，不是定时器），它会在**毫秒级**触发；
    540 秒对它有五个数量级的余量。要证明的是「没有这条路径」，不是「撑满 600 秒」。

    **540 而不是 600，且不算放水**：600 − 540 = 60 秒，留给第 7 步「重启网关 →
    等 Bridge 退避重连（上限约 36 秒）→ 补帧 → 点允许」，让被保护的那条审批在自己的
    10 分钟超时之前还有得救。跑更长的窗口会观察到 `auto_deny(timeout)`——那是审批
    自己的超时，不是断线误触，脚本会在失败信息里把 `autoReason` 点出来。
    """
    huo = True
    zhuan: list = []
    jue: list = []
    kai = time.monotonic()
    ci = 0
    while time.monotonic() - kai < a1:
        if not cun_zhen(a2):
            huo = False
        xian = str(du_rt().get("tunnelState"))
        if not zhuan or zhuan[-1] != xian:
            zhuan.append(xian)
        jue = du_jue(a3)
        if jue:
            break   # 有决定了就不用再等，直接让断言去报
        ci += 1
        if ci % 12 == 1:
            bao("观察中 %.0f/%.0f 秒", "tunnelState=%s，decisions.jsonl 无新增，Bridge pid=%s %s"
                 % (xian, a2, "活着" if cun_zhen(a2) else "已消失"))
        time.sleep(5.0)
    return huo, zhuan, jue


def zhen_duan(a1: Liu) -> None:
    """stream 首帧没到时的现场排查。**只打印、不作断言**——它是给下一个跑的人看的。

    这一步把「请求路径」与「帧推送路径」分开问：一次性请求还通而帧一个都不来，
    问题就锁定在长响应的搬运上（`tunnel.py` 的 `_liu`），不用从头猜。
    """
    bao("此刻 tunnelState / 建流状态码",
        "%s / %s（403 = 来源头不对，200 = 反代接了）"
        % (du_rt().get("tunnelState"), a1.tou or "没建起来"))
    try:
        with OP.open(urllib.request.Request(BASE + "/agent-api/health"),
                     timeout=20) as r:
            bao("一次性请求经隧道还通吗", "GET /agent-api/health → %s %s"
                 % (r.status, r.read().decode("utf-8", "replace")[:160]))
    except urllib.error.HTTPError as e:
        bao("一次性请求经隧道", "HTTP %s %s"
             % (e.code, e.read().decode("utf-8", "replace")[:160]))
    except Exception as e:  # noqa: BLE001
        bao("一次性请求经隧道", "也挂了：%s: %s" % (type(e).__name__, e))
    bao("零帧时先看的两个地方",
        "① 路由目标对不对（第 2 步那道闸，下面会查）；"
        "② 逐帧转出是否退化（曾因 _liu 用 read(4096) 攒批而静默失效，"
        "现已由 test_tunnel_client.py::test_liu_zhen_zhu_kuai_bu_neng_zan_pi 守着，"
        "它不含时长阈值：攒批会让帧数从 0 直接跳到 3，中间态观测不到）")


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="verify_stage6",
        description="阶段 6 真机验收：两个独立进程树，全程只经 WebSocket 隧道走通一次委派往返")
    ap.add_argument("--guan", type=float, default=GUAN, metavar="秒",
                    help="第 6 步掐断网关后的观察时长，默认 %(default)s 秒。"
                         "⚠ 跑到或超过 600 秒会观察到审批自己的 10 分钟超时"
                         "（autoReason=timeout），第 6 步会如实报红——那是超时本身，"
                         "不是断线误触")
    can = ap.parse_args()
    guan = can.guan
    if guan <= 0:
        raise SystemExit("[验收] --guan 要是个正数")
    if os.environ.get("LIFEOS_GW_PORT") and \
            int(os.environ.get("LIFEOS_GW_PORT") or 0) != GW_DUAN:
        raise SystemExit(
            "[验收] LIFEOS_GW_PORT=%s，但 Bridge 的出站地址写死 8771（run.py 组 cfg 时"
            "不传 url 键）。两边今天无法分别配置，请去掉这个变量再跑。"
            % os.environ.get("LIFEOS_GW_PORT"))
    if guan >= 590:
        bao("⚠ --guan=%.0f 已接近或超过审批超时 600 秒，第 6 步很可能如实报出 "
            "auto_deny(timeout)" % guan)

    q = Qiao(BASE)
    zhu: subprocess.Popen | None = None
    br: subprocess.Popen | None = None
    liu1: Liu | None = None
    liu2: Liu | None = None
    rt: dict = {}
    lang = None
    qi_shi = time.monotonic()
    try:
        # ---------------- 第 1 步 ----------------
        print("\n=== 第 1 步：起主服务+网关、起 Bridge；未配对直连网关必须 401 ===")
        zhu = qi_zhu()
        bao("主服务+网关起来了", "进程树 A pid=%s，主服务 :%d，隧道网关 :%d"
             % (zhu.pid, ZHU_DUAN, GW_DUAN))
        br, rt = qi_bridge("local")
        bao("Bridge 起来了", "进程树 B pid=%s port=%s instanceId=%s（LIFEOS_JIAOJIE=local）"
             % (rt["pid"], rt["port"], rt.get("instanceId")))
        # 负向断言：三种「没有合法配对码」的形态都必须 401
        # （tunnel_gw._shou_men：无 Authorization 头 → 401；token 不对 → 401；解绑 → 403）
        fu = [("不带 Authorization 头", lian_wang("")),
              ("形状合法但设备不存在", lian_wang("dt_dev-" + "0" * 12 + "_" + "0" * 64)),
              ("根本不是 token 形状", lian_wang("garbage"))]
        for shuo, ma_zhuang in fu:
            bao("未配对连网关：%s" % shuo, "HTTP %s" % ma_zhuang)
        ji("1. 两个进程树起来，且未配对连网关 401（三种坏凭据）",
           zhu.poll() is None and cun_zhen(int(rt["pid"]))
           and all(m == 401 for _, m in fu),
           "；".join("%s→%s" % (s, m) for s, m in fu))

        # ---------------- 第 2 步 ----------------
        print("\n=== 第 2 步：配对（pair-code → 本机 /pair）===")
        st, ma = q.post("/api/bridge/pair-code", {})
        if st != 200 or not ma.get("code"):
            raise SystemExit("[验收] pair-code 失败 %s %s" % (st, ma))
        bao("拿到配对码", "%s（过期时间 %s）" % (ma["code"], ma.get("expiresAt")))
        st, wen = biao_dan("http://127.0.0.1:%d/pair" % int(rt["port"]),
                           {"code": ma["code"], "label": "阶段6验收"})
        if st != 200 or "配对成功" not in wen:
            raise SystemExit("[验收] 本机 /pair 失败 HTTP %s：%s"
                             % (st, wen[:300]))
        xin: dict = {}
        for _ in range(40):
            time.sleep(0.25)
            xin = du_rt()
            if xin.get("deviceId") and xin.get("deviceToken"):
                break
        ji("2. 配对成功，runtime.json 有 deviceId 与 deviceToken",
           bool(xin.get("deviceId")) and bool(xin.get("deviceToken"))
           and str(xin.get("deviceId", "")).startswith("dev-")
           and len(str(xin.get("deviceId", ""))) == 16,
           "deviceId=%s userId=%s（deviceToken 明文只在这一处出现，长度 %d）"
           % (xin.get("deviceId"), xin.get("userId"), len(str(xin.get("deviceToken") or ""))))
        # 路由目标必须是刚刚配的那台。**这条现在有实现保证**：新配对会顶掉同账号
        # 的旧设备（`bridge_admin.pai_dui`），所以跑第二次不该再留下别的活动设备。
        # 闸留着是因为它同时能抓住**别的**成因——例如手工配过第二台、或将来顶掉
        # 逻辑被回退。真出现了，它会说出期望与实际，让人去清理而不是看到全线 502
        # 再去猜。（老版本在这里靠开头解绑全部设备绕过，那会毁掉这台机器上真配过
        # 的设备；实现修好后那一步纯属多余，已移除。）
        mu_di = [x for x in (q.get_ma("/api/bridge/devices").get("devices") or [])
                 if not x.get("revoked")]
        bao("反代的路由目标", ";".join("%s（%s）" % (x.get("deviceId"), x.get("label"))
                                      for x in mu_di) or "（空）")
        if len(mu_di) != 1 or mu_di[0].get("deviceId") != xin.get("deviceId"):
            raise SystemExit(
                "[验收] 未解绑设备不是本脚本刚配的那一台（期望 %s，实际 %s）——"
                "网关会把 /agent-api/* 发给别的设备。清掉多余的设备再跑。"
                % (xin.get("deviceId"), [x.get("deviceId") for x in mu_di]))

        # ---------------- 第 3 步 ----------------
        print("\n=== 第 3 步：重启 Bridge 走隧道（LIFEOS_JIAOJIE=tunnel）===")
        bao("先杀掉 local 形态的 Bridge", "pid=%s" % rt["pid"])
        sha_si(int(rt["pid"]))
        time.sleep(1.0)
        br, rt = qi_bridge("tunnel")
        bao("Bridge 重启", "pid=%s port=%s streamEpoch=%s"
             % (rt["pid"], rt["port"], rt.get("streamEpoch")))
        xun = deng_tunnel("connected", 90)
        bao("tunnelState", xun)
        liu1 = Liu()
        kuai, _ = liu1.deng(lambda z: z.get("type") == "snapshot", 45.0)
        if kuai is None:
            zhen_duan(liu1)
            raise SystemExit(
                "[验收] /agent-api/stream 45 秒没给出 snapshot 帧（%s）。"
                "首帧是 device_status{offline} 就说明隧道没通；请求通而没帧，"
                "看上一条诊断。" % (liu1.cuo or "45 秒超时"))
        bao("stream 首帧", "type=%s instanceId=%s streamEpoch=%s 会话数=%s"
             % (kuai.get("type"), kuai.get("instanceId"), kuai.get("streamEpoch"),
                len(kuai.get("sessions") or [])))
        ji("3. 隧道连上：tunnelState=connected，且 snapshot 的 instanceId/streamEpoch "
           "与 runtime.json 一致",
           kuai.get("instanceId") == rt.get("instanceId")
           and int(kuai.get("streamEpoch") or 0) == int(rt.get("streamEpoch") or -1),
           "tunnelState=%s；snapshot.instanceId=%s / runtime.json=%s；"
           "streamEpoch %s / %s（网关侧 hello 的 instanceId 没有任何端点暴露得出来，"
           "而这条 snapshot 是握手成功之后才搬得回来的，它就是见证）"
           % (du_rt().get("tunnelState"), kuai.get("instanceId"), rt.get("instanceId"),
              kuai.get("streamEpoch"), rt.get("streamEpoch")))
        bao("此后只经 /agent-api/*", "Bridge 端口 %s 从这一步起不再直连" % rt["port"])

        # ---------------- 第 4 步 ----------------
        print("\n=== 第 4 步：只经 /agent-api 建会话、发指令 ===")
        st1, d = q.post("/agent-api/sessions", {"agentId": "echo", "cwd": str(ROOT),
                                                "permissionMode": "manual",
                                                "title": "阶段6验收A"})
        if st1 != 201:
            raise SystemExit("[验收] 经 /agent-api 建会话失败 HTTP %s %s" % (st1, d))
        sid = d["session"]["sessionId"]
        # **两条指令必须在同一批里发。** `http.py::_pao` 每批消息都新建一个适配器
        # 实例（`xin_jian()` 里 `cls(...)`），而 echo 适配器是靠实例上的
        # `len(self.liao) == 2` 才发提问的。分两批发，第二批看到的是 `len == 1`，
        # 于是它**又发一次权限请求**而不是提问——2026-09-29 实测：提问帧永远不来，
        # 之后 `/questions/None` 拿到 409，看起来像提问收口坏了，其实是夹具用错。
        # 同一批发就没这个问题：批次循环对同一个实例连调两次 `fasong()`。
        st2, d2 = q.post("/agent-api/sessions/%s/messages" % sid,
                         {"instructions": ["跑一次命令，然后停。", "接下来做什么？"]})
        # echo 的第 1 条指令会 await 审批，所以此刻只有 message(tool_use) 与 permission
        # 两帧，**result 必然晚于点允许之后**——那是第 5 步的事。
        gong, _ = liu1.deng(lambda z: z.get("type") == "message"
                            and z.get("sessionId") == sid
                            and (z.get("message") or {}).get("kind") == "tool_use", 30.0)
        shen, _ = liu1.deng(lambda z: z.get("type") == "permission"
                            and z.get("sessionId") == sid, 30.0)
        rid = (shen or {}).get("request", {}).get("requestId")
        ji("4. 只经 /agent-api/* 建起会话，且指令真的抵达 Agent 并触发审批",
           st1 == 201 and st2 == 202 and gong is not None and shen is not None
           and bool(rid),
           "sessionId=%s（effectiveMode=%s）requestId=%s toolInput=%s｜"
           "流活着=%s 断因=%r｜最近帧：%s"
           % (sid, d["session"].get("effectiveMode"), rid,
              (shen or {}).get("request", {}).get("toolInput"),
              liu1.huo(), liu1.cuo, liu1.xian_chang()))

        # ---------------- 第 5 步 ----------------
        print("\n=== 第 5 步：经 /agent-api/permissions 点允许，Agent 继续跑完 ===")
        st3, d3 = q.post("/agent-api/permissions/%s" % urllib.parse.quote(str(rid)),
                         {"decision": "allow"})
        jie, _ = liu1.deng(lambda z: z.get("type") == "permission_resolved"
                           and z.get("sessionId") == sid, 30.0)
        jie1, _ = liu1.deng(lambda z: z.get("type") == "result"
                            and z.get("sessionId") == sid, 30.0)
        # 提问帧：第二条指令发的（它在第 4 步那同一批里，此刻才轮到它执行）
        wen, _ = liu1.deng(lambda z: z.get("type") == "question"
                           and z.get("sessionId") == sid, 30.0)
        qid = (wen or {}).get("question", {}).get("questionId")
        st5, _ = q.post("/agent-api/questions/%s" % urllib.parse.quote(str(qid)),
                        {"answers": [{"values": ["A"]}]})
        jie2, _ = liu1.deng(lambda z: z.get("type") == "result"
                            and z.get("sessionId") == sid, 30.0)
        ji("5. 点允许 → Agent 继续并跑完；提问经 /agent-api 收口后拿到第二条 result",
           st3 == 200 and st5 == 200
           and d3.get("decision") == "user_allow"
           and jie is not None and jie1 is not None
           and wen is not None and jie2 is not None
           # **两条 result 不许是同一帧**：游标写错时第二次会重复命中 result#1，
           # 而 `jie2 is not None` 照样成立。streamSeq 每帧唯一，正好当判据。
           and jie1.get("streamSeq") != jie2.get("streamSeq")
           and (jie or {}).get("decision") == "user_allow"
           and (jie or {}).get("autoDecided") is False,
           "permissions→%s decision=%s；result#1=%r；question=%s；"
           "questions→%s；result#2=%r｜最近帧：%s"
           % (st3, d3.get("decision"), (jie1 or {}).get("resultText"),
              qid, st5, (jie2 or {}).get("resultText"), liu1.xian_chang()))
        # **这里不关 liu1**：它的自然终点就是第 6 步掐断网关那一刻，那一下断流
        # 本身也是「窗口里没有任何帧进来」的一部分凭据。

        # ---------------- 第 6 步 ----------------
        print("\n=== 第 6 步：再造一个挂起审批，掐断网关后观察 %.0f 秒 ===" % guan)
        # echo 一个会话只发一次审批，第 5 步用掉了会话 A 的那一次 ⇒ 第 6 步要保护的
        # 挂起项只能来自新会话。**这条指令越靠近掐断越好**：审批超时是 600 秒，
        # 窗口 540 秒 + 第 7 步的重连要一起挤进剩下的 60 秒里。
        st6, db = q.post("/agent-api/sessions", {"agentId": "echo", "cwd": str(ROOT),
                                                 "permissionMode": "manual",
                                                 "title": "阶段6验收B"})
        if st6 != 201:
            raise SystemExit("[验收] 建会话 B 失败 HTTP %s %s" % (st6, db))
        sbd = db["session"]["sessionId"]
        st7, _ = q.post("/agent-api/sessions/%s/messages" % sbd,
                        {"text": "跑一次命令，然后停。"})
        shenb, _ = liu1.deng(lambda z: z.get("type") == "permission"
                             and z.get("sessionId") == sbd, 30.0)
        rdb = (shenb or {}).get("request", {}).get("requestId")
        if st7 != 202 or not rdb:
            raise SystemExit(
                "[验收] 会话 B 的指令没触发审批：messages→%s，permission 帧=%s｜"
                "流活着=%s 断因=%r｜最近帧：%s"
                % (st7, shenb, liu1.huo(), liu1.cuo, liu1.xian_chang()))
        bao("会话 B 挂着一条审批", "sessionId=%s requestId=%s（此刻才掐，"
             "600 秒超时从这一刻起算）" % (sbd, rdb))
        # 观察基线：**掐断之前**所有已收口的决定都不算窗口内的
        ji_suan = time.time()
        bao("掐断网关", "taskkill /T /F pid=%s（主服务与隧道网关同一进程树）"
             % zhu.pid)
        hai_huo = sha_si(int(zhu.pid))
        time.sleep(1.0)
        duan = deng_duan(60.0)
        bao("隧道是否真的断了", "tunnelState %s；主服务进程还在吗：%s"
             % (duan or "（60 秒内没离开 connected）", hai_huo))
        if not duan:
            raise SystemExit("[验收] 掐断后 tunnelState 一直没离开 connected——"
                             "观测窗口会变成空转，先查网关是不是真被杀掉了")
        huo, zhuan, jue = guan_cha(guan, int(rt["pid"]), ji_suan)
        print("[验收] 窗口 %.0f 秒结束：tunnelState 序列 %s" % (guan, zhuan))
        if jue:
            for x in jue:
                bao("⚠ 窗口内竟然有收口", "requestId=%s decision=%s autoReason=%s"
                     % (x.get("requestId"), x.get("decision"), x.get("autoReason")))
        zi = [x.get("pid") for x in (rt.get("pids") or [])]
        zi_huo = [x for x in zi if isinstance(x, int) and cun_zhen(x)]
        ji("6. 掐断网关后观察 %.0f 秒：隧道确实断开、窗口内零审批决定、Bridge 全程活着"
           % guan,
           bool(duan) and huo and not jue and len(zi_huo) == len(zi),
           "tunnelState %s；decisions.jsonl 在窗口内新增 %d 条；Bridge pid=%s 活着=%s；"
           "runtime.json 登记的子进程 %d 个全活（echo 不起子进程，这条今天恒真，"
           "claude-code 形态下它才承重）"
           % (duan, len(jue), rt["pid"], huo, len(zi)))

        # ---------------- 第 7 步 ----------------
        print("\n=== 第 7 步：重启网关 → 重连 → 挂起的审批还能批 → 第二条隧道顶掉第一条 ===")
        bao("重启主服务进程树", "")
        zhu = qi_zhu()
        bao("主服务+网关回来了", "新 pid=%s" % zhu.pid)
        xun = deng_tunnel("connected", 120.0)
        bao("Bridge 重连", "tunnelState %s（退避上限 30 秒，最多等这么久）" % xun)
        # 用重放缓冲把断线期间的帧补回来：前端 agentClient.ts 的同一手法。
        xian = max([int(z.get("streamSeq") or 0) for z in liu1.shou] or [0])
        liu2 = Liu(xian)
        kuai2, _ = liu2.deng(lambda z: z.get("type") == "snapshot", 40.0)
        if kuai2 is None:
            raise SystemExit("[验收] 重连后 stream 没给出 snapshot（%s）"
                             % (liu2.cuo or "40 秒超时"))
        zt = [z for z in liu2.shou if z.get("type") == "device_status"]
        lian_zt = [z for z in zt if z.get("state") == "connected"]
        hui_b = [x for x in (kuai2.get("sessions") or []) if x.get("sessionId") == sbd]
        dai = [x for x in (kuai2.get("pending") or [])
               if x.get("requestId") == rdb]
        bao("重连后的 snapshot", "instanceId=%s；会话 B state=%s pendingPermissions=%s；"
             "重放里的 device_status 帧 %s" % (
                 kuai2.get("instanceId"),
                 (hui_b[0].get("state") if hui_b else "（没有这个会话）"),
                 (hui_b[0].get("pendingPermissions") if hui_b else None),
                 [(z.get("state"), z.get("streamSeq")) for z in zt]))
        st8, d8 = q.post("/agent-api/permissions/%s" % urllib.parse.quote(str(rdb)),
                         {"decision": "allow"})
        jie3, _ = liu2.deng(lambda z: z.get("type") == "result"
                            and z.get("sessionId") == sbd, 40.0)
        bao("断线期间挂着的审批还能批", "permissions→%s decision=%s，result=%r"
             % (st8, d8.get("decision"), (jie3 or {}).get("resultText")))
        # 第二条隧道：同一个 deviceToken 再来一次握手，网关应当后连踢先连
        lang, cuo = kai_lang(str(du_rt().get("deviceToken") or ""),
                             int(du_rt().get("streamEpoch") or 0))
        if lang is None:
            raise SystemExit("[验收] 开第二条隧道失败：%s" % cuo)
        yao = threading.Thread(target=yao_ren, args=(lang,), daemon=True)
        yao.start()
        duan_liu = False
        zhong = time.monotonic() + 25.0
        while time.monotonic() < zhong:
            if not liu2.huo():
                duan_liu = True
                break
            time.sleep(0.2)
        yao.join(timeout=10.0)
        ji("7. 重启网关后重连成功、挂起的审批还能批、第二条隧道把第一条顶掉",
           kuai2.get("instanceId") == rt.get("instanceId")
           and bool(lian_zt) and bool(hui_b)
           and hui_b[0].get("state") == "attention"
           and bool(dai) and st8 == 200 and jie3 is not None and duan_liu,
           "snapshot.instanceId=%s（与断线前一致）；device_status{connected} %d 帧"
           "（streamSeq=%s）；断线期间会话 B 仍 %s、pending 里还有 %s；"
           "同一个 deviceToken 点允许 → %s，result=%r；"
           "跑在第一条隧道上的 /agent-api/stream 随即断流（%s）"
           % (kuai2.get("instanceId"), len(lian_zt),
              [z.get("streamSeq") for z in lian_zt],
              hui_b[0].get("state") if hui_b else "?",
              [x.get("requestId") for x in dai], st8,
              (jie3 or {}).get("resultText"), liu2.cuo or "读线程已退出"))

    finally:
        for x in (liu1, liu2):
            if x is not None:
                x.ting_zhi()
        if lang is not None:
            try:
                lang.close()
            except Exception:  # noqa: BLE001
                pass
        pid = du_rt().get("pid")
        if pid:
            sha_si(int(pid))
        if br is not None:
            try:
                br.wait(timeout=10)
            except Exception:  # noqa: BLE001
                br.terminate()
        if zhu is not None:
            sha_si(int(zhu.pid))
            try:
                zhu.wait(timeout=10)
            except Exception:  # noqa: BLE001
                zhu.terminate()

    print("\n=== 总结论（%.0f 秒）===" % (time.monotonic() - qi_shi))
    for a1, a2, a3 in jieguo:
        print("  %s  %s" % ("PASS" if a2 else "FAIL", a1))
        if a3:
            print("        %s" % a3)
    tong = sum(1 for _, a2, _ in jieguo if a2)
    print("  %d/%d 步通过" % (tong, len(jieguo)))
    return 0 if tong == len(jieguo) and jieguo else 1


if __name__ == "__main__":
    sys.exit(main())
