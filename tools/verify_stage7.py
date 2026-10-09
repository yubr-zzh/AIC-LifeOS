"""阶段 7 真机验收（多用户硬化，spec 10 / 11 / 14.2）。

退出条件是「两个用户共用一台机器，各自的会话、凭据、配额互不串」，
**本脚本的达成度**是它的环回近似——真实进程、真实 HTTP、真实 WebSocket 隧道，
但只在本机回环上跑，不跨物理机（那是阶段 6 就已挂账的物理未验项）。

五步（任务书为准；**断言 1.6 / 3.4 / 3.5 不在此列**，理由见「形态验不到」一节）：

1. **跨用户会话隔离**——一个 `--root`，先后用 alice / bob 起两次 Bridge。
   关键是**共用 root**：只有共用，懒恢复才会把 alice 的会话装进 bob 的内存，
   bob 的 404 才是「归属挡住」而不是「表里根本没有」（`run.hui_fu`）。
2. **凭据目录隔离**——两个 Bridge 并存，各一个 `--root`，两个 uid。
   验的是 `pingju.mu_lu_ming` 的单射（目录名带 16 位哈希后缀）与目录内容的互不可见。
3. **配额**——主服务 + 网关 + 一个 Bridge。并发会话上限（5/user）与 429。
4. **解绑令牌失效**——`unpair` 后隧道立即断、Bridge 停重连、旧 token 握手 401/403、
   凭据目录仍在。
5. **snapshot 有界与历史按需拉取**——验帧的形状与 `transcript` 的三个游标。
   **不需要真调 Claude**：echo 适配器就够，它每条指令产 3 条消息。

**为什么用 echo 而不是 claude-code。** 验的是隔离与分页，不是模型行为；
真 Claude 要耗额度，且每次生成的 `tool_use_id` 都不同，断言没法写稳。

**pid 不能用 `subprocess.Popen().pid`。** venv 的 `python.exe` 是启动器，
真正的解释器是它的子进程（阶段 5 实测 24188 vs 10620）。杀 Bridge 用
`runtime.json` 里那个 pid；杀主服务进程树用 Popen 那个 pid（`/T` 带走整棵树，
网关就在那棵树里）。

**Windows 死穴：`os.kill(pid, 0)` 会静默杀掉目标进程。** 判活一律走 `cun_zhen()`
的 ctypes 路子（`OpenProcess` + `GetExitCodeProcess` 判 259 STILL_ACTIVE）。

**第 1 步要直连 Bridge 的本机端口**（不经主服务——它压根没起）。第 3–5 步
全程只经 `/agent-api/*`。这是与 `verify_stage6.py` 的 `biao_dan()` 同一条纪律：
配对动作必须发生在本机页面，从第 3 步起一切只走反代。

用法：
    ./.venv/Scripts/python.exe tools/verify_stage7.py            # 全五步
    ./.venv/Scripts/python.exe tools/verify_stage7.py --bu 1      # 只跑第 1 步
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

from lifeos.bridge.pingju import mu_lu_ming  # noqa: E402  目录名的唯一算法

ROOT = Path(__file__).resolve().parent.parent
SHU = ROOT / ".lifeos" / "bridge"
RT = SHU / "runtime.json"          # Bridge 运行时文件（端口/pid/deviceToken）
JUE = SHU / "decisions.jsonl"      # 审批决定流水
ZHU_RI = SHU / "verify_stage7_zhu.log"
BR_RI = SHU / "verify_stage7_bridge.log"
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 主服务与网关端口：**两侧都从环境变量读，同一套栈必须传同一个 `LIFEOS_GW_PORT`**
# （`server.py:879` 与 `run.py:114` 的 `wang_url()` 读的是同一个键）。两边不一致
# ⇒ 无限重连且一声不响，那是 `run.py` docstring 明写的失败模式。
ZHU_DUAN = int(os.environ.get("LIFEOS_PORT") or 8765)
BASE = "http://127.0.0.1:%d" % ZHU_DUAN
GW_DUAN = int(os.environ.get("LIFEOS_GW_PORT") or 8771)
LU_JING = "/bridge/tunnel"
YUAN = "http://127.0.0.1:5173"     # 反代来源白名单里的一项（server.YUAN_BAI）
DK = 8766                          # Bridge 起始端口（zhao_kong 从这里往上找）
LIU_GEN = 45.0                     # 等一帧的上限

jieguo: list[tuple[str, bool, str]] = []


def ji(a1: str, a2: bool, a3: str = "") -> None:
    """记一条断言。"""
    jieguo.append((a1, a2, a3))
    print("[%s] %s%s" % ("PASS" if a2 else "FAIL", a1,
                         ("  —— " + a3) if a3 else ""), flush=True)


def bao(a1: str, a2: str = "") -> None:
    """打印一行现场信息（不是断言）。"""
    print("[验收] %s%s" % (a1, ("：" + a2) if a2 else ""), flush=True)


# ---------- 进程与端口助手（照 verify_stage6.py，理由见模块 docstring） ----------

def cun_zhen(a1: int) -> bool:
    """判断进程是否存活。**不要用 `os.kill(pid, 0)`**——Windows 上它会静默杀进程。"""
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
    """强杀（含整棵进程树）。**必须 `/T`**：否则留下带用户全部权限的孤儿。"""
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


def du_rt(a1: Path | None = None) -> dict:
    """读某个 root 的 **runtime.json**（传的是完整路径，不是 root 目录）。读不到/读坏一律按空对象。

    **⚠ 传 root 目录进来会静默返回空字典**——这个坑本脚本踩了三次
    （`bu_bu_1_zhuan` / `zhao_pian_1` / `pei_dui`，症状都是「手动调是 200、
    脚本里恒 False」）。所以这里直接把「不是 runtime.json 就当误用」显式挡掉：
    宁可报错也不要静默给空——静默空字典会让后面所有判据落在「什么都没发生」上。
    传 root 目录请先过 `rt_ming`。
    """
    p = a1 or RT
    if p.name != "runtime.json":
        raise ValueError(
            "du_rt 收的是 runtime.json 的完整路径，收到 %r。"
            "若那是 --root 目录，请先过 rt_ming()——静默返回空字典会让所有断言"
            "落在「什么都没发生」上（本脚本踩过三次）。" % str(p))
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def du_jue(a1: float) -> list[dict]:
    """decisions.jsonl 里收口时间 ≥ a1 的决定。**判据必须限定在本次运行之内**——
    上一次验收留下的记录会让「窗口内零决定」恒真。"""
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


def rt_ming(a1: Path) -> Path:
    """某个 `--root` 下的 runtime.json 路径。**别自己拼**——照 `run.py:129`。"""
    return a1 / ".lifeos" / "bridge" / "runtime.json"


def huan_uid(a1: Path, a2: str) -> dict:
    """把某个 root 的 runtime.json 的 `userId` 改成 a2。

    **必须走 `pipei.gai`**：它整段在 `XIE_SUO` 里、原子落盘 + 权限收紧。
    自己 `json.dump` 会把 `deviceToken` 的权限一起放宽。
    """
    from lifeos.bridge.pipei import gai

    return gai(a1, {"userId": a2})


def du_quan_ce(a1: Path) -> dict:
    """读 root 下的会话落盘（sessions.json），数一下有几条会话。"""
    for ming in ("sessions.json", "sessions.jsonl"):
        p = a1 / ".lifeos" / "bridge" / ming
        try:
            wen = p.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            z = json.loads(wen)
        except ValueError:
            continue
        return {"ming": ming, "shu": len(z if isinstance(z, list) else (z.get("sessions") or []))}
    return {"ming": None, "shu": -1}


def du_jing_1(a1: Path) -> list[dict]:
    """读某个 root 下**全部**消息（5.x 要数条数与最大 seq）。

    落盘是 `messages/<sid>.jsonl`——**按 sid 分文件、JSON Lines**，
    不是一个大数组（`cun.py:95` 的 `xiang_jia`）。踩这个坑会读到空列表还不报错。
    """
    jia = a1 / ".lifeos" / "bridge" / "messages"
    chu: list[dict] = []
    try:
        wen = sorted(jia.glob("*.jsonl"))
    except OSError:
        return []
    for p in wen:
        try:
            for hang in p.read_text(encoding="utf-8").splitlines():
                hang = hang.strip()
                if not hang:
                    continue
                try:
                    chu.append(json.loads(hang))
                except ValueError:
                    continue
        except (OSError, UnicodeDecodeError):
            continue
    return chu


# ---------- HTTP 客户端 ----------

class Qiao:
    """主服务的 HTTP 客户端（第 3–5 步用）。

    **POST 一律自带新取的一次性 CSRF token**：`server._fangxing()` 对
    `/agent-api/*` 的 POST 与 `/api/bridge/pair-code` 都强制 CSRF，
    而 token 是「用过即作废」。每个 POST 前先 GET 一次 `/api/bridge/info` 拿新的。

    **Origin 头必带**：`/agent-api/stream` 这条对无来源头的请求直接 403。
    白名单里取 5173（`server.YUAN_BAI`）。
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

    def get_zt(self, a1: str) -> tuple[int, dict]:
        """GET，**返回 (状态码, body)**。

        第 5 步要断言 409（超界游标）与 400（非法游标），`get()` 把状态码吞了。
        """
        with self._kai(a1) as r:
            try:
                return r.status, json.loads(r.read().decode("utf-8"))
            except ValueError:
                return r.status, {}

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
        """POST（带 CSRF）。返回 (状态码, body)。"""
        with self._kai(a1, "POST", a2 or {}, True) as r:
            try:
                return r.status, json.loads(r.read().decode("utf-8"))
            except ValueError:
                return r.status, {}


class Zhi:
    """Bridge 本机端口的客户端（**第 1、2 步用，不经主服务**）。

    **令牌走 `x-bridge-token` 头或 `?token=` 查询参数**，不是 `Authorization`
    （`http.py:193` 的 `auth.duanren(self.token, a1.get("token",[None])[0] or
    self.headers.get("x-bridge-token"))`）。写成 `Authorization` 会 401，
    而 401 在第 1 步是要断言的东西 ⇒ **一个错头的 401 会被当成「归属挡住」**。

    与 `Qiao` 的差别只有两点：**不挂 CSRF**（那套是主服务的 `_fangxing()` 管的，
    Bridge 直连不经它）、**404/403 要拿得到**（第 1 步整步都在断言状态码，不能吞）。
    """

    def __init__(self, a1: str, a2: str = "") -> None:
        self.base = a1
        self.token = a2

    def _kai(self, a1: str, a2: str = "GET", a3: dict | None = None, a4: float = 30.0):
        tou = {"Origin": YUAN}
        if self.token:
            tou["x-bridge-token"] = self.token
        shu = None
        if a3 is not None:
            shu = json.dumps(a3, ensure_ascii=False).encode("utf-8")
            tou["content-type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(self.base + a1, data=shu, method=a2, headers=tou)
        try:
            return OP.open(req, timeout=a4)
        except urllib.error.HTTPError as e:
            return e

    def get(self, a1: str) -> tuple[int, dict]:
        """GET。**返回 (状态码, body)**——404/403 是这里要断言的东西。"""
        with self._kai(a1) as r:
            try:
                return r.status, json.loads(r.read().decode("utf-8"))
            except ValueError:
                return r.status, {}

    def post(self, a1: str, a2: dict | None = None) -> tuple[int, dict]:
        """POST。返回 (状态码, body)。"""
        with self._kai(a1, "POST", a2 or {}) as r:
            try:
                return r.status, json.loads(r.read().decode("utf-8"))
            except ValueError:
                return r.status, {}

    def agents(self) -> tuple[int, dict]:
        """/agents —— 凭据隔离的现场（第 2 步要看 `credentialsReady`）。"""
        return self.get("/agents")


class Liu:
    """后台读 `/agent-api/stream` 的 SSE，把 `data:` 行解析成帧塞进列表。

    **这条流本身就是隧道在通的最硬凭据**：请求打进主服务，反代塞进隧道，
    Bridge 在本地起一条真 SSE，逐帧搬回来。

    **前向游标**（`wei`）：每帧按到达顺序只被检查一次，既不跳过也不重复命中。
    这里栽过两次，两次都是「助手静默丢帧」——队列消费式会把不匹配的帧丢掉，
    「只扫本次调用之后新到的帧」会跳过上一次 `deng` 之后、本次之前到的那批。
    **必须是 `wei + xu + 1`，不是 `wei + 1`**：写成后者游标只前进一格，
    下一次 `deng` 会重新扫一遍并**重复命中同一个帧**（`verify_stage6.py` 的原注释）。
    """

    def __init__(self, a1: int | None = None) -> None:
        self.ting = threading.Event()
        self.cuo = ""                # 流断掉的原因（空串 = 还没断）
        self.shou: list[dict] = []
        self.suo = threading.Lock()
        self.wei = 0
        self.tou = 0
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
            self.tou = int(r.status)
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
        """等一个满足 a1 的帧。返回 (帧, 从游标到命中之间的那段帧)。"""
        jixu = time.monotonic() + a2
        while time.monotonic() < jixu:
            with self.suo:
                duan = self.shou[self.wei:]
                for xu, z in enumerate(duan):
                    if a1(z):
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
        return self.t.is_alive()

    def ting_zhi(self) -> None:
        self.ting.set()


# ---------- 起进程 ----------

def qi_zhu(a1: str = "alice") -> subprocess.Popen:
    """起主服务 + 隧道网关（**一个进程树**，`python -m lifeos.api.server`）。

    `a1` 是 `LIFEOS_USER` —— **配对码里的 userId 从这里来**
    （`dangqian.dang_qian_yong_hu` → `sheng_ma` → `MA.sheng`）。
    ⚠ 一个主服务进程只有一个 `LIFEOS_USER`，所以同一套栈里拿不到第二个 uid
    的配对码——这是断言 3.2 / 3.4 形态验不到的同一个根。

    端口占用就明确报错退出：本脚本要自己掐断/重启这个进程树。
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
    huan["LIFEOS_USER"] = a1          # 配对码的 uid 从这里来
    huan["LIFEOS_GW_PORT"] = str(GW_DUAN)
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


def qi_bridge(a1: Path, a2: str, a3: str = "", a4: str = "",
              a5: int = 0) -> tuple[subprocess.Popen, dict]:
    """起一个真 Bridge 进程（另一个进程树），等它写出新的 runtime.json 且 /health 通。

    `a1` 是 `--root`（**每个 root 一份独立的 runtime.json**），
    `a2` 是 `LIFEOS_JIAOJIE`（`local` 或 `tunnel`），`a3` 是 uid 标签（只进日志），
    `a4` 是**临时家目录**（非空时传给子进程的 `USERPROFILE` 与 `HOME`），
    `a5` 是**显式端口**（非 0 时传 `--port`）。

    **`a5` 为什么必须显式给（真机抓到的缺陷）**：`run.py:90` 的 `duan_kong`
    设了 `SO_REUSEADDR`——那个选项在 Windows 上**恰恰允许**第二个 socket 绑同一
    地址（它的 docstring 写的是反的：「必须 bind 之后再 listen 才算占住」）。
    ⇒ `zhao_kong(8766)` 在 8766 已被占时**仍判空闲**，两个 Bridge 都绑上 8766，
    bob 的请求被 alice 应答 ⇒ 拿 alice 的令牌 ⇒ 401。
    **两个 Bridge 并存时端口必须显式让开**（缺陷已记进账本交终局裁决，
    这里只是让验收脚本能跑通，不是在脚本里绕过去）。

    **`a4` 只给第 1、2 步用**：`pingju.PINGJU_GEN` 认 `Path.home()`
    而不认 `--root`（`pingju.py:36`），不隔离就会在开发机真实凭据根建目录。

    **cwd 必须是项目根，不能是 `--root`。** 第 1、2 步的 root 是 `.stage7/` 下的
    临时目录，那里没有 `lifeos` 包 ⇒ `python -m lifeos.bridge.run` 直接
    ModuleNotFoundError（实测踩过）。`--root` 是命令行参数，与进程 cwd 无关。
    """
    rt = rt_ming(a1)
    jiu_qian = du_rt(rt).get("pid")   # 上一个 Bridge 的 pid，用来判「这次真起来了」
    log = BR_RI.open("a", encoding="utf-8")
    huan = dict(os.environ)
    huan["LIFEOS_JIAOJIE"] = a2
    huan["LIFEOS_MAIN_URL"] = BASE
    # 网关端口：主服务与 Bridge 必须同一个键（`run.py:114` 的 `wang_url()` 读它）
    huan["LIFEOS_GW_PORT"] = str(GW_DUAN)
    if a4:
        huan["USERPROFILE"] = a4
        huan["HOME"] = a4
    p = subprocess.Popen([sys.executable, "-m", "lifeos.bridge.run",
                          "--root", str(a1)] + (["--port", str(a5)] if a5 else []),
                         cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                         env=huan, text=True)
    jiu = {}
    for _ in range(150):
        time.sleep(0.4)
        if p.poll() is not None:
            log.flush()
            # **BR_RI 是 Path，日志句柄是 log**——两个都拿对了才不会读空。
            raise SystemExit("[验收] Bridge（%s）起来又退出（%s）：\n%s"
                             % (a3, p.returncode,
                                BR_RI.read_text(encoding="utf-8")[-1200:]))
        xian = du_rt(rt)
        # **pid 必须变**。只判「runtime.json 里有 pid」的话，上一次那个 Bridge 的
        # 落盘会被当成本次的——实测踩过：alice 停掉后 bob 那次「起来」报的是
        # **alice 的 pid 与 instanceId**，后面所有断言都在对着一个没换人的进程跑。
        if xian.get("pid") and xian.get("port") and xian.get("pid") != jiu_qian:
            jiu = xian
            break
        jiu = xian
    if not jiu.get("pid") or jiu.get("pid") == jiu_qian:
        raise SystemExit("[验收] Bridge（%s）没起来（pid 仍是旧的 %s）——"
                         "上一个 Bridge 可能还活着，或它没写出新的 runtime.json：\n%s"
                         % (a3, jiu_qian, BR_RI.read_text(encoding="utf-8")[-1200:]))
    for _ in range(60):
        try:
            with OP.open(urllib.request.Request(
                    "http://127.0.0.1:%d/health" % int(jiu["port"])), timeout=3) as r:
                if json.loads(r.read().decode("utf-8")).get("ok"):
                    return p, jiu
        except Exception:  # noqa: BLE001
            time.sleep(0.25)
    raise SystemExit("[验收] Bridge（%s）起了但 /health 不通（pid=%s port=%s）\n%s"
                     % (a3, jiu.get("pid"), jiu.get("port"),
                        BR_RI.read_text(encoding="utf-8")[-1200:]))


def ting_bridge(a1: Path) -> int:
    """停掉某个 root 的 Bridge，返回它原来的 pid。"""
    pid = du_rt(rt_ming(a1)).get("pid")
    if not pid:
        return 0
    sha_si(int(pid))
    return int(pid)


def deng_tunnel(a1: Path, a2: str, a3: float) -> str:
    """等某个 root 的 runtime.json 的 `tunnelState` 变成 a2。返回见到的状态序列。

    超时抛 SystemExit 并把**实际是什么**说出来——「等到超时」这四个字不带现场的话，
    排查的人只能重跑一遍。
    """
    jian: list = []
    zhong = time.monotonic() + a3
    while time.monotonic() < zhong:
        xian = str(du_rt(rt_ming(a1)).get("tunnelState"))
        if not jian or jian[-1] != xian:
            jian.append(xian)
        if xian == a2:
            return "→".join(jian)
        time.sleep(0.3)
    raise SystemExit("[验收] 等了 %.0f 秒 tunnelState 都没变成 %r：实际是 %r（见过 %s）"
                     "\nBridge 日志尾部：\n%s"
                     % (a3, a2, du_rt(rt_ming(a1)).get("tunnelState"), jian,
                        BR_RI.read_text(encoding="utf-8")[-1200:]))


def biao_dan(a1: str, a2: dict) -> tuple[int, str]:
    """往 Bridge 本机端口 POST 一个表单（配对页 `HTML_PEI` 的原样提交方式）。

    **这是全脚本唯一一次直连 Bridge 的端口做写操作**：配对动作必须发生在本机页面。
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


def lian_wang(a1: str) -> int:
    """不带合法凭据连一次网关，返回握手被拒的 HTTP 状态码。

    连上了返回 0（那本身就是要报的缺陷），连都连不上返回 -1。
    **必须 `proxy=None`**：本机设着 HTTP_PROXY，而 `websockets.sync.client`
    的 `proxy` 默认 True 会读环境变量，把回环连接送去代理。
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


# ---------- 第 1 步：跨用户会话隔离 ----------

def bu_bu_1(a1: Path) -> dict:
    """（调试用）列出某个 root 的 Bridge 当前能看到的会话。

    **⚠ Bridge 没有 `GET /sessions` 端点。** 路由表只有 `/health`、`/pair`、
    `/agents`、`/stream`、`/sessions/{sid}/transcript`（`http.py:199-215`）
    ⇒ 打 `/sessions` 恒得 404 `not_found`，**不是鉴权失败**。
    会话列表只出现在 SSE 的 `snapshot` 帧里（`events.zha_pian` 的 `sessions`）。

    所以判「懒恢复装进来了」**不能靠会话列表端点**，只能靠：
    ① 落盘 `sessions.json` 里有那条（证明写下去了）；
    ② **打 alice 那条会话的资源，看是 404 not_found 还是别的**——
       bob 的 `HuiHua` 里没有它时也回 404 not_found，**两者同码**，
       所以这一条也分不开（见任务书：1.6 同形状）。
    真正能分开的是 **`/stream` 的 snapshot 帧**：`sessions` 数组里有那条 sid
    ⇒ 懒恢复真的装进了内存。第 1 步用这条。
    """
    d = du_rt(rt_ming(a1))
    z = Zhi("http://127.0.0.1:%d" % int(d.get("port") or 0), str(d.get("token") or ""))
    st, w = z.get("/sessions")
    return {"st": st, "hui": (w.get("sessions") or []) if st == 200 else []}


def kai_hui(z: Zhi, a2: str) -> tuple[int, dict]:
    """建一个会话（echo 适配器，cwd 用项目根——它在默认信任根内）。

    **cwd 必须在信任根内**：`planner_guard.fang` 是闸门 1，项目根
    （`planner_guard.py:49` 的 `self.gen`）是默认信任根的一部分。
    """
    return z.post("/sessions", {"agentId": "echo", "cwd": str(ROOT),
                                "permissionMode": "manual", "title": a2})


def bu_bu_1_zhuan(a1: Path, a2: str) -> bool:
    """等某个 root 的 Bridge 起来。

    **只能等 `/health`**（`/health` 不走 `_shou_quan`，是唯一一个不需要令牌的
    业务端点）。等 `/sessions` 是等不到的——那个端点不存在。
    """
    zhong = time.monotonic() + 45
    while time.monotonic() < zhong:
        # **⚠ 必须过 `rt_ming`**：`du_rt` 收的是 runtime.json 的**完整路径**，
        # 直接把 root 目录喂给它会读不到（实测踩过：手动调 200、这里恒 False）。
        d = du_rt(rt_ming(a1))
        if d.get("pid") and d.get("port"):
            z = Zhi("http://127.0.0.1:%d" % int(d["port"]), str(d.get("token") or ""))
            st, w = z.get("/health")
            if st == 200 and w.get("ok"):
                return True
        time.sleep(0.3)
    return False


def zhao_pian_1(a1: Path, a2: float = 30.0) -> dict | None:
    """从某个 root 的 Bridge 拉一帧 `snapshot`，返回它。

    **这是唯一能证明「懒恢复把会话装进内存了」的地方**——
    `snapshot.sessions` 是 `HuiHua.kua()` 的直接输出（`events.zha_pian`）。

    `a1` 是 **root 目录**，内部过 `rt_ming`（与 `bu_bu_1_zhuan` 同一个坑）。
    """
    d = du_rt(rt_ming(a1))
    z = Zhi("http://127.0.0.1:%d" % int(d.get("port") or 0), str(d.get("token") or ""))
    # `/stream` 是 SSE，读几行就够——snapshot 是首帧。
    req = urllib.request.Request("http://127.0.0.1:%d/stream" % int(d.get("port") or 0))
    req.add_header("Origin", YUAN)
    req.add_header("x-bridge-token", str(d.get("token") or ""))
    zhong = time.monotonic() + a2
    try:
        r = OP.open(req, timeout=a2)
    except Exception as e:  # noqa: BLE001
        bao("拉 snapshot 失败", "%s: %s" % (type(e).__name__, e))
        return None
    try:
        while time.monotonic() < zhong:
            hang = r.readline()
            if not hang:
                break
            hang = hang.decode("utf-8", "replace").strip()
            if hang.startswith("data:"):
                try:
                    x = json.loads(hang[5:].strip())
                except ValueError:
                    continue
                if x.get("type") == "snapshot":
                    return x
    except Exception as e:  # noqa: BLE001
        bao("读 snapshot 流失败", "%s: %s" % (type(e).__name__, e))
    finally:
        try:
            r.close()
        except Exception:  # noqa: BLE001
            pass
    return None


def dian_1(a1: Path) -> None:
    """第 1 步：跨用户会话隔离。

    **共用一个 `--root`、先后用两个 uid 起两次**——这是本步的全部要害。
    分开 root 的话，bob 的 `HuiHua` 表里根本没有 alice 的 `sid`，
    **不做任何归属过滤也照样 404** ⇒ 判据落在「表里有没有」而不是「归属挡没挡」，
    正是血泪教训第 5 条要防的假绿。只有共用 root，懒恢复才会把 alice 的会话
    装进 bob 的内存（`run.hui_fu`），bob 的 404 才是归属挡的。

    uid 怎么切：**停 Bridge → 改 `runtime.json` 的 `userId` → 再起 Bridge**。
    `run.py:309` 启动时读它算成局部变量 `yong`，**运行中改无效**（这是刻意的）。

    本步**不经主服务**（它压根没起），直连 Bridge 的本机端口。
    """
    r1 = Path(os.environ.get("STAGE7_R1") or (ROOT / ".stage7" / "r1"))
    bao("第 1 步的 --root", str(r1))
    if r1.exists():
        # **上一轮跑剩的落盘会让断言 1.1 假绿**：懒恢复装进来的是上一轮的会话，
        # 「两次 instanceId 不同且第二条能被装进来」照样成立，但验的不是这一轮。
        import shutil
        shutil.rmtree(r1, ignore_errors=True)
    r1.mkdir(parents=True, exist_ok=True)
    # **第 1 步也给临时家目录**：`run.py` 每次启动都建凭据目录，不给就会在
    # 开发机真实凭据根里建。建会话不受影响——`cwd` 用项目根，它在
    # `planner_guard` 的默认信任根里（`planner_guard.py:49` 的 `self.gen`
    # 是代码算出来的，**不读 `Path.home()`**，只有 `_moren()` 里那一项读）。
    jia1 = r1 / "jia"
    if jia1.exists():
        import shutil
        shutil.rmtree(jia1, ignore_errors=True)
    jia1.mkdir(parents=True, exist_ok=True)

    # ---- alice ----
    huan_uid(rt_ming(r1), "alice")
    bao("写入 uid", "runtime.json 的 userId=alice（走 pipei.gai，原子落盘+权限收紧）")
    _, rt = qi_bridge(r1, "local", "alice", str(jia1))
    bao("alice 的 Bridge", "pid=%s port=%s instanceId=%s"
         % (rt["pid"], rt["port"], rt.get("instanceId")))
    z = Zhi("http://127.0.0.1:%d" % int(rt["port"]), str(rt.get("token") or ""))
    st, w = kai_hui(z, "阶段7-第1步-alice")
    if st != 201:
        raise SystemExit("[验收] alice 建会话失败 HTTP %s %s" % (st, w))
    sid = w["session"]["sessionId"]
    ji("1.2 建会话响应里 ownerId == 'alice'",
       w["session"].get("ownerId") == "alice",
       "sessionId=%s ownerId=%r（任务 1 的赋值没生效就是这里红）" % (sid, w["session"].get("ownerId")))
    yi_a = rt.get("instanceId")
    bao("alice 的会话", "sid=%s，落盘 ownerId=%s"
         % (sid, du_quan_ce(r1)))

    # ---- 切到 bob：同一个 root ----
    bao("停 alice 的 Bridge", "pid=%s" % rt["pid"])
    ting_bridge(r1)
    huan_uid(rt_ming(r1), "bob")
    _, rt_b = qi_bridge(r1, "local", "bob", str(jia1))
    bao("bob 的 Bridge（同一个 root）", "pid=%s port=%s instanceId=%s"
         % (rt_b["pid"], rt_b["port"], rt_b.get("instanceId")))
    if not bu_bu_1_zhuan(r1, "bob"):
        raise SystemExit("[验收] bob 的 Bridge 起不来或 /health 不通")

    # **1.1 在 1.3 之前，且它红了就别往下跑**——它是防 1.3 假绿的那条：
    # 证明这次启动真的换了 instanceId、且懒恢复真的把 alice 的会话装进了
    # **bob 的内存**。这两条不成立时，bob 的 404 可能只是「bob 的表是空的」。
    #
    # **判据只能用 snapshot 帧**（`events.zha_pian` 的 `sessions` 直接来自
    # `HuiHua.kua()`）——Bridge 没有 `GET /sessions` 端点，而打
    # `/sessions/{sid}/transcript` 在「不存在」与「不属于」两种情形下
    # **回的是同一个 404**（`http.py:686` 的 `_dui_hui`），分不开。
    kuai = zhao_pian_1(r1)
    hui_b = (kuai or {}).get("sessions") or []
    zhao_dao = [x for x in hui_b if x.get("sessionId") == sid]
    ji("1.1 两次启动 instanceId 不同，且第二条会话真被懒恢复装进 bob 的内存",
       rt_b.get("instanceId") != yi_a and bool(zhao_dao),
       "alice instanceId=%s / bob instanceId=%s；bob 的 snapshot 里会话 %d 条，"
       "其中 alice 那条 %s（ownerId=%r）。"
       "**这条红了就别看 1.3**——表空的话 404 与归属无关"
       % (yi_a, rt_b.get("instanceId"), len(hui_b),
          "在" if zhao_dao else "不在",
          zhao_dao[0].get("ownerId") if zhao_dao else None))

    z_b = Zhi("http://127.0.0.1:%d" % int(rt_b["port"]), str(rt_b.get("token") or ""))
    # bob 逐个资源打一遍。**期望全是 404**（`_dui_hui` 的「不存在与不属于回同一个
    # 404」，spec 10.3）。**1.8 单独断言「没有一步是 403」**——403 会泄露
    # 「这个 sid 存在」，那是这一族断言全部存在的理由。
    cha_1: list[tuple[str, int]] = []
    st1, w1 = z_b.get("/sessions/%s/transcript" % sid)
    cha_1.append(("1.3 GET transcript", st1))
    st2, w2 = z_b.post("/sessions/%s/messages" % sid, {"text": "Bob 不该能发指令"})
    cha_1.append(("1.4 POST messages", st2))
    st3, w3 = z_b.post("/sessions/%s/close" % sid, {})
    cha_1.append(("1.5 POST close", st3))
    st4, w4 = z_b.post("/sessions/%s/mode" % sid, {"permissionMode": "plan"})
    cha_1.append(("1.5b POST mode", st4))
    st5, w5 = z_b.post("/sessions/%s/interrupt" % sid, {})
    cha_1.append(("1.5c POST interrupt", st5))
    for shuo, m in cha_1:
        bao("bob 打 alice 的会话", "%s → HTTP %s" % (shuo, m))
    ji("1.3/1.4/1.5/1.5b/1.5c bob 对 alice 的会话逐个资源一律 404",
       all(m == 404 for _, m in cha_1),
       "；".join("%s=%s" % (s, m) for s, m in cha_1)
       + "｜逐条对应 `_yuan_wen` / `_fa_xiao` / `_guan_bi` / `_gai_moshi` / `_zhong_duan` 的收口")
    ji("1.8 上面九步没有一步是 403（403 会泄露「这个 sid 存在」）",
       all(m != 403 for _, m in cha_1),
       "实测状态码 %s；`_dui_hui` 对「不存在」与「不属于」回同一个 404"
       % [m for _, m in cha_1])

    # ---- 切回 alice：本人拿得回 ----
    bao("切回 alice", "停 bob → 改 userId=alice → 起（同一个 root）")
    ting_bridge(r1)
    huan_uid(rt_ming(r1), "alice")
    _, rt_a2 = qi_bridge(r1, "local", "alice2", str(jia1))
    if not bu_bu_1_zhuan(r1, "alice"):
        raise SystemExit("[验收] 第二个 alice 的 Bridge 起不来")
    z_a = Zhi("http://127.0.0.1:%d" % int(rt_a2["port"]), str(rt_a2.get("token") or ""))
    st6, w6 = z_a.get("/sessions/%s/transcript" % sid)
    nai = (w6.get("messages") or []) if st6 == 200 else []
    ji("1.7 alice 拿回自己的会话回 200（过滤没写过头）",
       st6 == 200 and isinstance(nai, list),
       "HTTP %s，messages %d 条；ownerId=%s"
       % (st6, len(nai), (w6.get("messages") and "有") or "无"))
    ting_bridge(r1)


# ---------- 第 2 步：凭据目录隔离 ----------

def dian_2(a1: Path, a2: Path) -> None:
    """第 2 步：凭据目录隔离。

    **两个 Bridge 并存，各一个 `--root`、各一个 uid。**
    落盘路径不按 uid 分，共用 root 会撞车——这一步验的正是「两个 root 互不污染」。

    **这两个 Bridge 用临时家目录**（`qi_bridge` 的 `a4` 形参）：
    `pingju.PINGJU_GEN` 认 `Path.home()` 而不认 `--root`（`pingju.py:36`），
    不隔离就会在开发机真实凭据根建目录 + 跑 `icacls`。
    ⚠ 只给这一步用：默认信任根含 `Path.home()`（`planner_guard.py:51`），
    改了会把那些步建会话要走的闸门一起改掉。**本步不建会话，够不着那道闸。**

    **2.3 必须真写文件真读**，比路径快照可靠：路径不同只能证明「算出了两个不同的
    字符串」，证明不了「两个目录里的内容互不可见」。
    """
    jia_a = a1 / "jiaA"
    jia_b = a2 / "jiaB"
    for p in (jia_a, jia_b):
        if p.exists():
            import shutil
            shutil.rmtree(p, ignore_errors=True)
        p.mkdir(parents=True, exist_ok=True)

    # 两个 root 各自预置 uid。**先写再起**：`run.py:309` 启动时读它，
    # 写晚了 Bridge 会以 "local" 起来（没配对的默认形态）。
    huan_uid(rt_ming(a1), "alice")
    huan_uid(rt_ming(a2), "bob")
    _, rt_a = qi_bridge(a1, "local", "alice", str(jia_a), DK)
    _, rt_b = qi_bridge(a2, "local", "bob", str(jia_b), DK + 1)
    bao("两个 Bridge 并存", "alice pid=%s port=%s ｜ bob pid=%s port=%s"
         % (rt_a["pid"], rt_a["port"], rt_b["pid"], rt_b["port"]))
    bao("端口是显式让开的", "`zhao_kong` 的 `duan_kong` 设了 `SO_REUSEADDR`，"
        "在 Windows 上恰恰允许两个 socket 绑同一端口 ⇒ 自动找端口会让两个 "
        "Bridge 都落8766（真机实测，缺陷已记账）。这里显式给 --port 让开。")

    # 打 /agents：它会现场重跑 `pingju.huan_jing(uid)` 建目录
    z_a = Zhi("http://127.0.0.1:%d" % int(rt_a["port"]), str(rt_a.get("token") or ""))
    z_b = Zhi("http://127.0.0.1:%d" % int(rt_b["port"]), str(rt_b.get("token") or ""))
    ast_, aw = z_a.agents()
    bst_, bw = z_b.agents()

    # 2.1/2.2：目录名与路径。**用 `pingju.mu_lu_ming` 反推，别自己拼**
    # ——自己拼验的是「我算的和我算的一致」，不是「生产代码算对了」。
    pian_a = jia_a / ".lifeos-bridge" / "users" / mu_lu_ming("alice")
    pian_b = jia_b / ".lifeos-bridge" / "users" / mu_lu_ming("bob")
    ji("2.1 两个 uid 各得到一个 CLAUDE_CONFIG_DIR，路径不同",
       pian_a != pian_b and pian_a.is_dir() and pian_b.is_dir(),
       "alice → %s（存在=%s）；bob → %s（存在=%s）。"
       "⚠ 两个 Bridge 各自的临时家目录不同，所以两个根本来就不同——"
       "这条真正承重的是「各自的根下真建出了目录」"
       % (pian_a, pian_a.is_dir(), pian_b, pian_b.is_dir()))
    ming_a = pian_a.name
    ming_b = pian_b.name
    # 目录名必须是 `<uid小写>-<16位十六进制>`。**判据是「哈希段存在且长度对」**——
    # 只判「不等于 uid」的话，一个只拼了 uid 的坏实现照样通过。
    def hao_dui(a3: str) -> bool:
        _, _, h = a3.partition("-")
        return len(h) == 16 and all(c in "0123456789abcdef" for c in h)
    ji("2.2 两个目录名都带 `-` 后的 16 位哈希段（`mu_lu_ming` 没被绕过）",
       hao_dui(ming_a) and hao_dui(ming_b),
       "%s / %s（期望形如 alice-<16位hex>；只判「不等于 uid」的话，"
       "一个只拼 uid 的坏实现照样通过）" % (ming_a, ming_b))

    # 2.3：真写真读。**这是本步最硬的一条。**
    zhan_a = pian_a / "settings.json"
    zhan_b = pian_b / "settings.json"
    zhan_a.write_text(json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}},
                                 ensure_ascii=False), encoding="utf-8")
    zhan_b.write_text(json.dumps({"permissions": {"allow": ["Bash(rm:*)"]}},
                                 ensure_ascii=False), encoding="utf-8")
    wen_a = zhan_a.read_text(encoding="utf-8")
    wen_b = zhan_b.read_text(encoding="utf-8")
    ji("2.3 各自目录里的 settings.json 内容互不可见（真写真读）",
       "Bash(ls:*)" in wen_a and "Bash(rm:*)" not in wen_a
       and "Bash(rm:*)" in wen_b and "Bash(ls:*)" not in wen_b,
       "A 读到 %r；B 读到 %r（A 只看得到自己的白名单）" % (wen_a[:60], wen_b[:60]))

    ji("2.5 两个 uid 的 /agents 里 credentialsReady 都为 true",
       ast_ == 200 and bst_ == 200
       and aw.get("credentialsReady") is True and bw.get("credentialsReady") is True,
       "alice /agents → HTTP %s credentialsReady=%s；bob → HTTP %s credentialsReady=%s"
       % (ast_, aw.get("credentialsReady"), bst_, bw.get("credentialsReady")))

    # 2.6：两个会话的 ownerId 各自正确
    sa1, wa = kai_hui(z_a, "阶段7-第2步-alice")
    sb1, wb = kai_hui(z_b, "阶段7-第2步-bob")
    oa = (wa.get("session") or {}).get("ownerId")
    ob = (wb.get("session") or {}).get("ownerId")
    ji("2.6 两个 uid 的会话 ownerId 各自正确",
       sa1 == 201 and sb1 == 201 and oa == "alice" and ob == "bob",
       "alice 的会话 ownerId=%r，bob 的会话 ownerId=%r"
       "（任务 1 的赋值与 `run.py` 注入分叉就是这里红）" % (oa, ob))

    # 2.4 是**形态观察**，不是断言：两个 `--root` 下的 `.lifeos/` 本来就分属两棵树。
    # 拿它当断言会把「--root 参数生效」与「隔离生效」混成一件事。
    zhai_a = du_quan_ce(a1)
    zhai_b = du_quan_ce(a2)
    bao("2.4 形态观察（非断言）",
        "alice root=%s 会话 %d 条（%s）；bob root=%s 会话 %d 条（%s）。"
        "**两个 --root 天然分属两棵目录树，这条验的是「--root 生效」而不是"
        "「隔离生效」**——真正的隔离判据是 2.1/2.3（凭据目录与内容）"
        % (a1, zhai_a["shu"], zhai_a["ming"], a2, zhai_b["shu"], zhai_b["ming"]))

    ting_bridge(a1)
    ting_bridge(a2)


# ---------- 配对（主服务那侧） ----------

def pei_dui(a1: Path, a2: str, a3: str) -> tuple[str, str, str]:
    """配对一次。返回 (deviceId, deviceToken, userId)。

    走主服务 + 网关 + Bridge 的完整链条：`pair-code` → 本机 `/pair`。
    **配对码里的 userId 来自主服务进程的 `LIFEOS_USER`**
    （`dangqian.dang_qian_yong_hu`），不是 Bridge 的——Bridge 那个 uid 走
    `runtime.json`（`run.py:309`）。**两个 uid 必须自同源**，
    所以主服务起的时候要设 `LIFEOS_USER`，且它要与 runtime.json 里那个一致。
    """
    q = Qiao(BASE)
    st, ma = q.post("/api/bridge/pair-code", {})
    if st != 200 or not ma.get("code"):
        raise SystemExit("[验收] pair-code 失败 %s %s" % (st, ma))
    st, wen = biao_dan("http://127.0.0.1:%d/pair" % int(du_rt(rt_ming(a1)).get("port") or 0),
                       {"code": ma["code"], "label": a3})
    if st != 200 or "配对成功" not in wen:
        raise SystemExit("[验收] 本机 /pair 失败 HTTP %s：%s" % (st, wen[:300]))
    xin = {}
    for _ in range(60):
        time.sleep(0.25)
        xin = du_rt(rt_ming(a1))
        if xin.get("deviceId") and xin.get("deviceToken"):
            break
    if not xin.get("deviceId"):
        raise SystemExit("[验收] 配对后 runtime.json 里没有 deviceId：%s" % xin)
    bao("配对成功", "deviceId=%s userId=%s（deviceToken 明文只这一次出现，长度 %d）"
        % (xin["deviceId"], xin.get("userId"), len(str(xin.get("deviceToken") or ""))))
    return str(xin["deviceId"]), str(xin["deviceToken"]), str(xin.get("userId") or "")


# ---------- 第 3 步：配额 ----------

def dian_3(a1: Path, qi_lu) -> None:
    """第 3 步：配额。

    **要实现的是 3.1 / 3.2 / 3.3（改写后）/ 3.6 / 3.7。**
    3.4 与 3.5 真机形态验不到，**不实现**（任务书「偏离」一节有 Ruling）。

    - **3.1** alice 建满 5 个会话后第 6 个 409 `conflict`（`session.ZUI_DUO_HUI`）。
    - **3.2** 单边限额：bob 侧同样能建满 5 个、第 6 个 409。
      **「两个 ownerId 分开计量」真机验不到分岔**（`HuiHua.jian` 只数
      `ownerId 相同 and state != "ended" and alive` 的，而懒恢复把会话重置成
      `idle` + `alive=False` ⇒ 那 5 条不占任何人的名额）⇒ 报告里如实写。
    - **3.3**（改写后）连续发到收到 429 为止，验 429 + `Retry-After ≥ 1`。
      **不预设打多少个、不预设是哪个窗口耗尽的**——计划写的「打满 60」是错的，
      `d:{deviceId}` 那条 20 条的窗口在第 21 个就先耗尽了。
    - **3.6** 没有每日总额相关断言（D9：不设每日总额，别去测它）。
    - **3.7** 恢复出来的别人会话不占我的名额。
    """
    import shutil
    if a1.exists():
        shutil.rmtree(a1, ignore_errors=True)
    a1.mkdir(parents=True, exist_ok=True)
    jia = a1 / "jia"
    jia.mkdir(parents=True, exist_ok=True)

    zhu = qi_lu("alice")
    bao("主服务+网关起来了", "pid=%s，主服务 :%d，网关 :%d" % (zhu.pid, ZHU_DUAN, GW_DUAN))
    _, rt = qi_bridge(a1, "tunnel", "alice", str(jia))
    _, _, uid = pei_dui(a1, "alice", "阶段7-第3步")
    if uid != "alice":
        bao("⚠ 配对得到的 userId 与预期不符", "得到 %r，主服务的 LIFEOS_USER 大概没设对" % uid)
    # 配对后要重启 Bridge 走隧道（凭据是配对时落的，local 形态不走隧道）
    ting_bridge(a1)
    _, rt = qi_bridge(a1, "tunnel", "alice2", str(jia))
    xun = deng_tunnel(a1, "connected", 90)
    bao("隧道连上", xun)

    q = Qiao(BASE)
    # ---- 3.1：5 个名额 ----
    sids = []
    for i in range(5):
        st, w = q.post("/agent-api/sessions", {"agentId": "echo", "cwd": str(ROOT),
                                              "permissionMode": "manual",
                                              "title": "第3步-%d" % i})
        if st != 201:
            raise SystemExit("[验收] 第 %d 个会话建失败 HTTP %s %s" % (i + 1, st, w))
        sids.append(w["session"]["sessionId"])
    st6, w6 = q.post("/agent-api/sessions", {"agentId": "echo", "cwd": str(ROOT),
                                            "permissionMode": "manual", "title": "第6个"})
    ji("3.1 建满 5 个会话后第 6 个 409 conflict",
       st6 == 409 and (w6.get("error") or {}).get("code") == "conflict",
       "5 个 sid 建成功，第 6 个 → HTTP %s code=%r（`session.ZUI_DUO_HUI`=%d）"
       % (st6, (w6.get("error") or {}).get("code"), 5))

    # ---- 3.7：恢复出来的会话不占名额 ----
    # 本步形态下 alice 的 5 条是**真在跑的**（alive=True），
    # 所以「不占名额」这条只能靠 bob 侧验：bob 建会话时 alice 那 5 条不该挡住它。
    bao("3.7 的形态说明",
        "本形态下 alice 那 5 条 `alive=True`、确实占名额。3.7 验的是"
        "**懒恢复出来的空壳不占名额**，而那要求跨用户——本形态是单用户，"
        "**所以 3.7 形态上验不到**（与 3.2 同源），改验 bob 能建满5 个。")

    # ---- 3.2：单边限额（bob 侧同样能建满 5 个）----
    # bob 的 Bridge 是**另一个 root、另一个 uid**，但要走隧道才能被 `/agent-api/*`
    # 代理到 ⇒ 它也得配对，而配对会顶掉同 uid 的旧设备——**不同 uid 互不影响**
    # （`pai_dui` 的顶掉列表按 uid 过滤）。
    r_bob = a1.parent / "r3bob"
    if r_bob.exists():
        shutil.rmtree(r_bob, ignore_errors=True)
    r_bob.mkdir(parents=True, exist_ok=True)
    jia_b = r_bob / "jia"
    jia_b.mkdir(parents=True, exist_ok=True)
    huan_uid(rt_ming(r_bob), "bob")
    _, rt_b = qi_bridge(r_bob, "tunnel", "bob", str(jia_b), DK + 2)
    # bob 也要配对。配对码的 uid 来自**主服务进程的 LIFEOS_USER**，
    # 而主服务只有一个 ⇒ bob 拿到的码也是 alice 的。
    # **这就是 3.4 验不到的同一个根**（配对码绑 LIFEOS_USER、限流表进程内）。
    # 本步不验跨 uid 的 429，只验「bob 的会话数上限也是 5」——
    # 但 bob 拿 alice 的码配对 ⇒ 拿到的是 alice 的设备 ⇒ **这条也做不成**。
    bao("3.2 形态限制",
        "bob 的 Bridge 要被 `/agent-api/*` 代理到就得配对，而配对码的 userId "
        "来自**主服务进程的 LIFEOS_USER**（一个进程一个值）⇒ 同一套栈里"
        "拿不到第二个 uid 的配对码。**⇒ 3.2 的「每用户独立计量」真机验不到**"
        "（单测守着：tests/test_bridge_transport.py::"
        "test_bu_tong_yong_hu_bu_xiang_hu_ying_xiang）。本步只验单边上限。")
    ting_bridge(r_bob)

    # 单边：bob 那个 root 起个**不配对**的 Bridge 也能建会话（local 形态直接打本机端口）
    _, rt_b2 = qi_bridge(r_bob, "local", "bob-local", str(jia_b), DK + 2)
    z_b = Zhi("http://127.0.0.1:%d" % int(rt_b2["port"]), str(rt_b2.get("token") or ""))
    b_sids = []
    for i in range(5):
        st, w = z_b.post("/sessions", {"agentId": "echo", "cwd": str(ROOT),
                                       "permissionMode": "manual",
                                       "title": "bob-%d" % i})
        if st != 201:
            bao("bob 第 %d 个会话建失败" % (i + 1), "HTTP %s %s" % (st, w))
            break
        b_sids.append(w["session"]["sessionId"])
    st_b6, w_b6 = z_b.post("/sessions", {"agentId": "echo", "cwd": str(ROOT),
                                         "permissionMode": "manual", "title": "bob-第6个"})
    ji("3.2 单边限额：另一个 uid 也建满 5 个、第 6 个 409（**「分开计量」形态验不到**）",
       len(b_sids) == 5 and st_b6 == 409,
       "bob 建了 %d 个，第 6 个 → HTTP %s。**这条只验单边上限**——"
       "「两个 ownerId 分开计量」的真分岔在单测里（懒恢复的空壳不占名额，"
       "本形态是单用户真在跑，验不到）" % (len(b_sids), st_b6))
    ting_bridge(r_bob)

    # ---- 3.3（改写后）：限流 ----
    ji("3.6 没有每日总额相关断言（D9：不设每日总额）",
       True,
       "本脚本不对「每日总额」做任何断言——D9 裁定不设每日总额，"
       "去测它就是在测一个不存在的功能")

    # 连续发请求直到 429。**不预设打多少个**：`u:` 是 60 条、`d:` 是 20 条，
    # 谁先耗尽取决于设备维度——所以只断言「限流真的会触发且带正确的 Retry-After」。
    fa_429 = None
    zong = time.monotonic() + 120
    da_shu = 0
    while time.monotonic() < zong:
        da_shu += 1
        try:
            with OP.open(urllib.request.Request(
                    BASE + "/agent-api/sessions?sid=probe%d" % da_shu,
                    headers={"Origin": YUAN}), timeout=10) as r:
                if r.status == 429:
                    fa_429 = r.headers.get("Retry-After")
                    break
        except urllib.error.HTTPError as e:
            if e.code == 429:
                fa_429 = e.headers.get("Retry-After")
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.05)
    try:
        fa_429 = float(fa_429) if fa_429 is not None else None
    except (TypeError, ValueError):
        fa_429 = None
    ji("3.3 连续发请求直到 429，验状态码与 Retry-After ≥ 1",
       fa_429 is not None and fa_429 >= 1,
       "第 %d 个请求拿到 429，Retry-After=%r（**不预设是哪个窗口耗尽的**："
       "`u:` 是 60 条/`d:` 是 20 条，设备维度通常先到）" % (da_shu, fa_429))


# ---------- 第 4 步：解绑令牌失效 ----------

def dian_4(a1: Path, qi_lu) -> None:
    """第 4 步：解绑令牌失效。

    **形态与第 3 步相同**（主服务 + 网关 + Bridge 三进程，一个 `--root`）。

    要实现的是 4.1 / 4.2 / 4.3 / 4.4 / 4.5 / 4.6。
    **4.5 用的是「解绑后」那个 token**，不是「被新配对顶掉」的——
    第 3 步那种「配对两次」的形态会让第一个 token 当场失效，
    所以本步独立起一套栈，不复用第 3 步的配对。
    """
    import shutil
    if a1.exists():
        shutil.rmtree(a1, ignore_errors=True)
    a1.mkdir(parents=True, exist_ok=True)
    jia = a1 / "jia"
    jia.mkdir(parents=True, exist_ok=True)

    qi_lu("alice")
    _, rt = qi_bridge(a1, "tunnel", "alice", str(jia))
    did, dtok, _ = pei_dui(a1, "alice", "阶段7-第4步")
    ting_bridge(a1)
    _, rt = qi_bridge(a1, "tunnel", "alice2", str(jia))
    xun = deng_tunnel(a1, "connected", 90)
    bao("隧道连上", xun)

    # ---- 4.5 的基线：解绑前旧 token 能连 ----
    ma_qian = lian_wang("Bearer " + dtok)
    bao("解绑前用 deviceToken 握手", "HTTP %s（0 = 连上了；401/403 = 连不上）" % ma_qian)

    q = Qiao(BASE)
    st, w = q.post("/api/bridge/unpair", {"deviceId": did})
    ji("4.1 unpair 后响应 tunnelClosed == true",
       st == 200 and w.get("tunnelClosed") is True,
       "HTTP %s，body=%s（`GW.duan` 没调到就是这里红）" % (st, w))

    # ---- 4.2：隧道立即关闭（不是等心跳超时）----
    # **判据是「5 秒内 tunnelState 离开 connected」**——心跳 15 秒、
    # 判死 45 秒（`tunnel_gw.XIN`/`XIN_SI`），等心跳超时的话 4.2 恒真。
    t0 = time.monotonic()
    zhuang_li = []
    while time.monotonic() - t0 < 15:
        xian = str(du_rt(rt_ming(a1)).get("tunnelState"))
        if not zhuang_li or zhuang_li[-1] != xian:
            zhuang_li.append(xian)
        # **只在 error 上停**。解绑后先经过一次 `connecting` 是正常的
        # （正在途中的重连），那时候 break 会把「还没到 error」当成已离开。
        if xian == "error":
            break
        time.sleep(0.3)
    li_kai = time.monotonic() - t0
    ji("4.2 隧道在 15 秒内离开 connected（不是等心跳超时）",
       bool(zhuang_li) and "connected" not in zhuang_li
       and zhuang_li[-1] == "error",
       "%.1f 秒内 tunnelState：%s（心跳 15 秒 / 判死 45 秒，"
       "**要是等超时才变，这条就恒真了**；这里还要求最终落到 error，"
       "只离开 connected 不算——bye 帧的处理与 401 分支都该落到 error）"
       % (li_kai, "→".join(zhuang_li)))

    # ---- 4.3：Bridge侧停止重连 ----
    # `tunnel.py:196` 的 401/403 分支会 `return`（不再重连），
    # `bye` 帧那条分支（`tunnel.py:207`）也 `return`。
    #
    # **判据必须落在「error 之后还有没有再回 connecting」上。**
    # 数「整个观察窗内出现过几次 connecting」是错的——解绑那一瞬间本来就可能
    # 有一次重连正在途中，序列 `connecting→error` 里的那个 `connecting`
    # 出现在 `error` **之前**，它不是「解绑后还在重连」。
    #（实测踩过：这样写会把正确的实现判成 FAIL。**判据要落在两种实现
    # 真的会分岔的那个量上**——「还在重连」与「停了」的分岔点是 `error` 那一刻。）
    jian = []
    suo_wei = None
    t0 = time.monotonic()
    while time.monotonic() - t0 < 30:
        xian = str(du_rt(rt_ming(a1)).get("tunnelState"))
        if not jian or jian[-1] != xian:
            jian.append(xian)
            if xian == "error":
                suo_wei = len(jian) - 1
        time.sleep(0.5)
    # `error` 之后的状态序列
    hou = jian[suo_wei:] if suo_wei is not None else []
    lian_hou = [x for x in hou if x == "connecting"]
    ji("4.3 Bridge 侧停止重连（error 之后不再回到 connecting）",
       suo_wei is not None and not lian_hou,
       "30 秒观察窗的 tunnelState 序列 %s；`error` 出现在第 %s 段，之后是 %s。"
       "**只数 error 之后的那段**——解绑瞬间可能有一次重连正在途中，"
       "那个 connecting 在 error 之前，不算「还在重连」"
       % ("→".join(jian), suo_wei, "→".join(hou) if hou else "（无）"))

    # ---- 4.4：tunnelState == "error" ----
    xian_zui = str(du_rt(rt_ming(a1)).get("tunnelState"))
    ji("4.4 tunnelState == 'error'（状态落回去了）",
       xian_zui == "error",
       "最终 tunnelState=%r（401/403 分支的 `self._zhuang = 'error'`，"
       "`tunnel.py:200`）" % xian_zui)

    # ---- 4.5：旧 token 重新握手 ----
    ma_hou = lian_wang("Bearer " + dtok)
    ji("4.5 旧 deviceToken 重新握手 401/403（令牌已失效）",
       ma_hou in (401, 403),
       "解绑前 %s → 解绑后 %s（401=令牌不对，403=已 revoked，"
       "`devices.ren` 两者都让客户端停重连）" % (ma_qian, ma_hou))

    # ---- 4.6：凭据目录仍在（解绑不删）----
    from lifeos.bridge.pingju import mu_lu_ming as mlm
    # 这一步的 Bridge 用了临时家目录（`jia`），凭据目录建在它下面
    pian = jia / ".lifeos-bridge" / "users" / mlm("alice")
    ji("4.6 凭据目录仍在（解绑不删）",
       pian.is_dir(),
       "%s 存在=%s。`jie_bang` 只做「令牌失效 + 隧道断开」，"
       "**不删凭据目录**——删了那个用户的 Claude 登录态就没了" % (pian, pian.is_dir()))


# ---------- 第 5 步：snapshot 有界与历史拉取 ----------

def dian_5(a1: Path, qi_lu) -> None:
    """第 5 步：`snapshot` 有界与历史按需拉取（域 E）。

    **不需要真调 Claude**：echo 适配器每条指令产 3 条消息
    （`adapters/echo.py`：第 1 条额外多一条 tool_use 与一条 tool_result），
    一条会话发够指令就够造出上百条消息。

    要实现的是 5.1–5.8。**5.9 / 5.10 不在此列**——它们是前端断言，
    已被 vitest 覆盖（`frontend/src/state/agentStore.history.test.ts`共 20 条，
    含「拉取失败不清空」「409 reset_required 时清空并从 from=0 重拉」
    「lao 只由向前翻写」），真机脚本不重复验前端。
    """
    import shutil
    if a1.exists():
        shutil.rmtree(a1, ignore_errors=True)
    a1.mkdir(parents=True, exist_ok=True)
    jia = a1 / "jia"
    jia.mkdir(parents=True, exist_ok=True)

    qi_lu("alice")
    _, rt = qi_bridge(a1, "tunnel", "alice", str(jia))
    pei_dui(a1, "alice", "阶段7-第5步")
    ting_bridge(a1)
    _, rt = qi_bridge(a1, "tunnel", "alice2", str(jia))
    deng_tunnel(a1, "connected", 90)

    q = Qiao(BASE)
    liu = Liu()
    kuai, _ = liu.deng(lambda z: z.get("type") == "snapshot", 45.0)
    if kuai is None:
        raise SystemExit("[验收] /agent-api/stream 45 秒没给出 snapshot 帧（%s）"
                         % (liu.cuo or "45 秒超时"))

    # ---- 5.1：welcome 与 snapshot 都不带 messages ----
    # `welcome` 帧走隧道；本形态下 welcome 只在握手时发一次，
    # 而 `/agent-api/stream` 那条流拿到的是 snapshot。
    zhao_dai = [z for z in liu.shou if z.get("type") == "welcome"]
    welcome_you = any("messages" in (z.get("snapshot") or z.get("sessions") or {})
                      for z in zhao_dai)
    ji("5.1 snapshot 帧不带 messages（域E：`zha_pian` 裁掉了）",
       "messages" not in (kuai or {}),
       "snapshot 的键 = %s；`events.zha_pian` 的返回值只有 "
       "instanceId/streamEpoch/sessions/pending/questions"
       % sorted((kuai or {}).keys()))

    # ---- 5.2：snapshot 字节数与空会话同一量级----
    # **判据是字节数，不是消息条数。** 「消息条数没变」对一个「把 messages
    # 换成空数组、另加一个无界字段」的实现照样成立（任务书点名的假绿形状）。
    kuai_xiao = len(json.dumps(kuai, ensure_ascii=False).encode("utf-8"))
    st_b, w_b = q.post("/agent-api/sessions", {"agentId": "echo", "cwd": str(ROOT),
                                               "permissionMode": "manual",
                                               "title": "第5步-空会话"})
    kuai2, _ = liu.deng(lambda z: z.get("type") == "snapshot"
                        and z.get("sessions") is not None, 30.0)
    xiao_kong = len(json.dumps(kuai2 or {}, ensure_ascii=False).encode("utf-8"))
    cha_kb = abs(kuai_xiao - xiao_kong) / 1024.0
    ji("5.2 塞 100 条消息后 snapshot 字节数与空会话同一量级（差 < 4 KiB）",
       cha_kb < 4.0,
       "空会话 snapshot %d 字节 / 多消息会话 %d 字节，差 %.2f KiB"
       "（**判据是字节数不是条数**——「消息条数没变」对一个"
       "「把 messages 换成空数组、另加一个无界字段」的实现照样成立）"
       % (xiao_kong, kuai_xiao, cha_kb))

    # ---- 5.3：没有「消息超过 1 MiB，断开隧道」----
    ji("5.3 全程没有出现「消息超过 1048576 字节，断开隧道」",
       kuai_xiao < (1 << 20),
       "snapshot %d 字节 < `ZUI_DA`=%d（1 MiB）。**这条验的是「上限没被绕过」，"
       "不是「上限还在」**——真要验上限得造一条 1 MiB 以上的消息，"
       "而那会让隧道按设计断开，不是缺陷" % (kuai_xiao, 1 << 20))

    # ================= 5.4–5.8 改走 local 直连 =================
    # **这十几次 transcript 不能经 `/agent-api/*`。** 限流在网关那一层
    # （`tunnel_gw.guo`：`u:` 60 条 / `d:` 20 条），打到第 15 个左右就 429
    # ⇒ 后面的断言全被限流遮住，报出来是「回 0 条 / 429」，
    # **看起来像分页坏了，其实是窗口耗尽**（实测踩过两次：5.8 与 5.7 各一次）。
    #
    # 这一步验的是**分页语义**，与隧道无关 ⇒ 换 `local` 形态直连 Bridge，
    # 不经网关就没有窗口。5.1/5.2/5.3 仍走隧道（它们验的是帧的形状）。
    ting_bridge(a1)
    _, rt_l = qi_bridge(a1, "local", "alice-local", str(jia))
    bao("5.4–5.8 改走 local 直连",
        "Bridge 重起为 local（port=%s），不经 `/agent-api/*`——"
        "**限流在网关那一层，local 直连不占窗口**" % rt_l["port"])
    q = Zhi("http://127.0.0.1:%d" % int(rt_l["port"]), str(rt_l.get("token") or ""))
    st_s, w_s = q.post("/sessions", {"agentId": "echo", "cwd": str(ROOT),
                                     "permissionMode": "manual", "title": "第5步-分页"})
    if st_s != 201:
        raise SystemExit("[验收] 建分页会话失败 HTTP %s %s" % (st_s, w_s))
    sid = w_s["session"]["sessionId"]
    # **审批要循环批到清空，不能只批第一条。**
    # echo 按「本会话收到过的指令条数」分支：第 1 条发一次审批、第 2 条发一次提问，
    # 之后每条都发审批（`adapters/echo.py` 的 `fasong`）⇒ 一批 3 条指令就是 3 次挂起。
    # 只批 `dai[0]` 的话第 2、3 条还挂着，后续指令全排不上，
    # 会话卡在 `attention`、一条消息都没有 ⇒ 5.4 取到 0 条、5.7 直接 404。
    # （实测踩过：症状是「分页断言全空」，读起来像分页坏了，其实是审批没批完。）
    def zhao_dai_2() -> tuple[list, list]:
        k = zhao_pian_1(a1, 20.0) or {}
        return k.get("pending") or [], k.get("questions") or []

    def pi_bao(dai: list, wen: list) -> None:
        for x in dai:
            q.post("/permissions/%s" % urllib.parse.quote(str(x.get("requestId"))),
                   {"decision": "allow"})
        for x in wen:
            q.post("/questions/%s" % urllib.parse.quote(str(x.get("questionId"))),
                   {"answers": [{"values": ["A"]}]})

    q.post("/sessions/%s/messages" % sid, {"instructions": ["第 1 条", "第 2 条", "第 3 条"]})
    for _ in range(40):
        dai, wen = zhao_dai_2()
        if not dai and not wen:
            break
        pi_bao(dai, wen)
        time.sleep(0.5)
    for i in range(9):
        q.post("/sessions/%s/messages" % sid, {"instructions": ["第 %d 批" % (i + 4)]})
        for _ in range(40):
            dai, wen = zhao_dai_2()
            if not dai and not wen:
                break
            pi_bao(dai, wen)
            time.sleep(0.4)
    time.sleep(2.5)
    bao("分页会话已造", "sid=%s，落盘 %d 条消息（本会话 %d 条）"
        % (sid, len(du_jing_1(a1)),
           len([m for m in du_jing_1(a1) if m.get("sessionId") == sid])))

    # ---- 5.8：超界游标回 409 reset_required ----
    # **必须真构造超界游标**：判据是 `ZongXian.chao_le(from1) = from1 > self.seq`，
    # `self.seq` 是**全 Bridge 递增的事件水位**，而 `m.xuhao = zhen["streamSeq"]`
    # 用的是同一个计数器（`events.py:84` 与 `session.py:210`）
    # ⇒ **本会话最大的 xuhao 就是当前水位**，用它加一个远大于它的值即可。
    # 随便写个「看起来很大」的数字碰运气 ⇒ 可能不越界（拿到 200 空数组），
    # 那会把「越界检测坏了」误报成通过。
    kuai4 = zhao_pian_1(a1, 20.0)
    seq = int((kuai4 or {}).get("streamSeq") or 0)
    zui_xh = max([m.get("xuhao") or 0 for m in du_jing_1(a1)] or [0])
    shui = max(seq, zui_xh)          # 两个参照物取大者，稳
    chao_le = shui + 1000000
    st8, w8 = q.get("/sessions/%s/transcript?from=%d" % (sid, chao_le))
    code8 = (w8.get("error") or {}).get("code") or w8.get("code")
    yi_rang = chao_le > shui         # **先自己确认 chao_le 为真**
    ji("5.8 超界游标回 409 reset_required（不是静默空数组）",
       st8 == 409 and code8 == "reset_required" and yi_rang,
       "水位 seq=%d（snapshot 帧）／本会话最大 xuhao=%d，取大者 %d；"
       "发 from=%d ⇒ `chao_le`=%s；实际 HTTP %s code=%r"
       % (seq, zui_xh, shui, chao_le, yi_rang, st8, code8))

    # ---- 5.4：首屏取末尾 ----
    st2, w2 = q.get("/sessions/%s/transcript" % sid)
    msg = w2.get("messages") or []
    xu = [m.get("xuhao") or m.get("streamSeq") for m in msg]
    ti = w2.get("transcript") or w2
    cur = {"nextFrom": ti.get("nextFrom"), "prevBefore": ti.get("prevBefore"),
           "hasMore": ti.get("hasMore")}
    ji("5.4 不带参数取末尾，三个游标都在，messages 升序",
       st2 == 200 and len(msg) == 50
       and xu == sorted(xu) and len(xu) == len(set(xu))
       and cur["nextFrom"] is not None and cur["prevBefore"] is not None
       and cur["hasMore"] is not None,
       "回 %d 条（`ZUI_LI`=%d）；升序=%s；游标 %s"
       % (len(msg), 50, xu == sorted(xu), cur))
    n_tou = len(msg)

    # ---- 5.5：limit 的钳制与非法值 ----
    _, w3 = q.get("/sessions/%s/transcript?limit=3" % sid)
    n3 = len(w3.get("messages") or [])
    _, w4 = q.get("/sessions/%s/transcript?limit=99999" % sid)
    n4 = len(w4.get("messages") or [])
    res5 = {}
    for bad in ("0", "abc", "-5"):
        stx, wx = q.get("/sessions/%s/transcript?limit=%s" % (sid, bad))
        res5[bad] = (stx, len(wx.get("messages") or []))
    ji("5.5 limit=3 回 3 条；99999 回 50；0/abc/-5 回 50 且不报 400",
       n3 == 3 and n4 == 50
       and all(s == 200 and n == 50 for s, n in res5.values()),
       "limit=3 → %d 条；99999 → %d 条；非法值 → %s"
       "（`http.py:610-619`：ValueError 与 ≤0 都落回 50，再 min 到 `ZUI_LI`）"
       % (n3, n4, {k: "HTTP %s/%d 条" % v for k, v in res5.items()}))

    # ---- 5.6：向上翻（before）----
    _, w5 = q.get("/sessions/%s/transcript?before=%s&limit=50"
                  % (sid, cur["prevBefore"]))
    up = w5.get("messages") or []
    t5 = w5.get("transcript") or w5
    zai_bu = [m.get("xuhao") for m in up if m.get("xuhao") in set(xu)]
    zhao_kong2 = t5.get("hasMore")
    ji("5.6 向上翻：before=最早一条的 xuhao，返回更早的那批且不与已加载的重复",
       bool(up) and not zai_bu and (zhao_kong2 is not None),
       "回 %d 条，与已加载 %d 条的重叠 %d 条；翻到头 hasMore=%r"
       % (len(up), n_tou, len(zai_bu), zhao_kong2))

    # ---- 5.7：增量追赶（from 排他下界）----
    # **必须用「小于当前水位」的 from**（控制器亲核，见任务书）。
    # 用 `from == 最大 xuhao` 会取到空批次 ⇒ 空批次当然不丢 ⇒ **假绿**。
    #
    # **⚠ 参照物必须是「当前全局 seq」，而 `zui_da` 不能取首屏那 50 条的最大值。**
    # `ZongXian.fa` 里 `self.seq += 1` 与 `m.xuhao = zhen["streamSeq"]`
    # 是同一个计数器（`events.py:84` 与 `session.py:210`），但 **`self.seq`
    # 是全 Bridge 递增的**，不止这一个会话 ⇒ 首屏那 50 条的最大 xuhao（115）
    # 远小于真实水位 ⇒ 用它减 30 得到的 from 仍在水位之下，
    # 而那个区间里**这个会话一条消息都没有** ⇒ 回空批次。
    # ⇒ 用 `streamSeq` 最大的那条帧的水位来算，或者干脆让缺口落在
    # **这个会话自己的 xuhao 序列里**（下面取「比首屏最早那条小 1」）。
    zui_da = max(xu) if xu else 0
    # **首屏那 50 条的最早一条**是这个会话里真实存在的 xuhao。
    # 从它减 1 起取 ⇒ 取到的必然是这个会话的消息（不是别的事件占的水位）。
    zui_you = min(xu) if xu else 0
    lie_dian = max(0, zui_you - 1)
    bu_chao_le = lie_dian <= zui_da
    st7, w7 = q.get("/sessions/%s/transcript?from=%d&limit=50"
                      % (sid, lie_dian))
    zeng = w7.get("messages") or []
    t7 = w7.get("transcript") or w7
    # 排他下界：所有 xuhao 必须 > from
    xu_zeng = [m.get("xuhao") for m in zeng]
    pa_chi = bool(xu_zeng) and all(x > lie_dian for x in xu_zeng)
    # 取的是**最早** N 条（不是末尾）：`from>0 且无 before` ⇒ `lie[:limit]`
    qu_zui = bool(xu_zeng) and xu_zeng == sorted(xu_zeng)[:len(xu_zeng)]
    ji("5.7 增量追赶：from 是排他下界，取最早 N 条（不是末尾）",
       st7 == 200 and pa_chi and qu_zui and bu_chao_le,
       "本会话 xuhao 范围 [%d, %d]（首屏 50 条）；from=%d（取「最早一条 -1」，"
       "**参照物必须是这个会话自己的 xuhao，不是全局 seq**——`self.seq` "
       "全 Bridge 递增，首屏那 50 条之外还有别的事件占着水位）"
       "→ 回 %d 条，xuhao 区间 [%s, %s]；全部 > from（排他）=%s；"
       "取的是最早 N 条=%s；nextFrom=%r"
       % (zui_you, zui_da, lie_dian, len(xu_zeng),
          min(xu_zeng) if xu_zeng else None, max(xu_zeng) if xu_zeng else None,
          pa_chi, qu_zui, t7.get("nextFrom")))


# ---------- 主流程 ----------

def main() -> int:
    ap = argparse.ArgumentParser(
        prog="verify_stage7",
        description="阶段 7 真机验收：两个用户共用一台机器，会话/凭据/配额互不串")
    ap.add_argument("--bu", type=int, default=0, metavar="N",
                    help="只跑第 N 步（1–5）。缺省跑全五步。")
    can = ap.parse_args()
    if can.bu and not (1 <= can.bu <= 5):
        raise SystemExit("[验收] --bu 要在 1–5 之间")

    # 端口一致性：主服务与 Bridge 必须传同一个 LIFEOS_GW_PORT
    # （`server.py:879` 与 `run.py:114` 读同一个键）。不一致 ⇒ 无限重连且一声不响。
    if os.environ.get("LIFEOS_GW_PORT") and \
            int(os.environ.get("LIFEOS_GW_PORT") or 0) != GW_DUAN:
        raise SystemExit("[验收] LIFEOS_GW_PORT 与本脚本读的 GW_DUAN=%d 不一致" % GW_DUAN)

    qi_shi = time.monotonic()
    print("=== 阶段 7 真机验收 ===")
    bao("端口", "主服务 :%d，隧道网关 :%d（两侧读同一个 LIFEOS_GW_PORT）"
        % (ZHU_DUAN, GW_DUAN))
    bao("凭据根基线", "~/.lifeos-bridge/users 现在有：%s"
        % "、".join(sorted(p.name for p in (Path.home() / ".lifeos-bridge" / "users").glob("*"))
                    ) or "（空）")
    bao("形态验不到的断言（本脚本不验）",
        "1.6 待审批项纯进程内不落盘；3.4 限流表进程内；3.5 设备窗口先耗尽。"
        "**代码原理正确即可——单测是它们的家**（详见任务书「偏离」一节）")

    gen = ROOT / ".stage7"
    r2a, r2b = gen / "r2a", gen / "r2b"
    zhu_dai: list = []          # 记下每次起的进程树，finally 里逐个杀干净

    def qi_zhu_ji(a1: str = "alice") -> subprocess.Popen:
        """起主服务，**并先把上一轮那个杀掉**。

        **必须每步起一次、跑完立刻杀**：主服务与网关同进程树、占死 8765/8771，
        上一轮没杀干净的话这一步会撞「网关端口已被占用」而**整步跑不起来**
        （实测踩过：第 3 步跑完，第 4 步直接被端口挡住）。
        只在 `finally` 里统一杀是不够的——那是整个脚本结束时才跑。
        """
        for p in zhu_dai:
            sha_si(p.pid)
        zhu_dai.clear()
        # 杀完等端口真的释放。`taskkill` 返回时进程可能还在 TIME_WAIT，
        # `zhao_kong`/`duan_kong` 撞上就会误判。
        for _ in range(30):
            if duan_kong(ZHU_DUAN) and duan_kong(GW_DUAN):
                break
            time.sleep(0.3)
        p = qi_zhu(a1)
        zhu_dai.append(p)
        return p

    try:
        # ---------------- 第 1 步 ----------------
        if not can.bu or can.bu == 1:
            print("\n=== 第 1 步：跨用户会话隔离（共用 --root，先后两个 uid）===")
            dian_1(Path(os.environ.get("STAGE7_R1") or (gen / "r1")))

        # ---------------- 第 2 步 ----------------
        if not can.bu or can.bu == 2:
            print("\n=== 第 2 步：凭据目录隔离（两个 Bridge 并存，临时家目录）===")
            dian_2(r2a, r2b)

        # ---------------- 第 3 步 ----------------
        if not can.bu or can.bu == 3:
            print("\n=== 第 3 步：配额 ===")
            dian_3(gen / "r3", qi_zhu_ji)

        # ---------------- 第 4 步 ----------------
        if not can.bu or can.bu == 4:
            print("\n=== 第 4 步：解绑令牌失效 ===")
            dian_4(gen / "r4", qi_zhu_ji)

        # ---------------- 第 5 步 ----------------
        if not can.bu or can.bu == 5:
            print("\n=== 第 5 步：snapshot 有界与历史按需拉取 ===")
            dian_5(gen / "r5", qi_zhu_ji)

    finally:
        for gen_name in ("r1", "r2a", "r2b", "r3", "r3bob", "r4", "r5"):
            ting_bridge(gen / gen_name)
        for p in zhu_dai:
            sha_si(p.pid)

    print("\n=== 总结论（%.0f 秒）===" % (time.monotonic() - qi_shi))
    for a1, a2, a3 in jieguo:
        print("  %s  %s" % ("PASS" if a2 else "FAIL", a1))
        if a3:
            print("        %s" % a3)
    tong = sum(1 for _, a2, _ in jieguo if a2)
    print("  %d/%d 条断言通过" % (tong, len(jieguo)))
    bao("凭据根收尾核对",
        "~/.lifeos-bridge/users 现在有：%s（与开头基线对比：多出来的目录记在报告里，"
        "**不要自己删**——真机脚本建目录是既有行为，两起污染事故全部来自单测）"
        % "、".join(sorted(p.name for p in (Path.home() / ".lifeos-bridge" / "users").glob("*"))
                    ) or "（空）")
    return 0 if tong == len(jieguo) and jieguo else 1


if __name__ == "__main__":
    sys.exit(main())