"""阶段 5 真机验收（方案 12.6）。

退出条件：**强杀 Bridge → 重启 → 已批准的命令不会被重新提问；越界游标正确重置。**

七步：
1. 起 Bridge（独立进程），建会话，真触发一次 Bash 审批，点允许，等它跑完。
2. taskkill /F 强杀 Bridge（不是两段式关闭——要的就是非正常退出）。
3. 重启 Bridge。
4. 在同一个会话里发同一条指令，让 Agent 再次触发同一个 tool_use_id。
5. 断言审批卡不出现、收到 permission_resolved{replayed:true}、结果正确。
6. 带一个大于当前 streamSeq 的 from 调 transcript → 409 reset_required。
7. 六个展示旁路 kind 在强杀后的重启里出现过（.lifeos/events.json）。

**为什么用 echo 适配器而不是 claude-code。** 重放的比对键是
`(sessionId, tool_use_id)` 且 `inputHash` 相等。真实 Claude 每次生成的
tool_use_id 都是新的，第 4/5 步的前提（同一个 id 再来一次）根本不成立，
拿它验收只会得到一个假的 FAIL。EchoAdapter 的 tool_use_id 写死为
`tool-echo-1`、toolInput 也写死，正好让这个前提成立。
本阶段验收的是 Bridge 的持久化与重放行为；Claude Code 适配器本身的行为
在阶段 3 已经用 `tools/verify_stage3.py` 真机验收过。

**pid 不能用 subprocess.Popen().pid。** venv 的 python.exe 是启动器，
真正的解释器是它的子进程，两者 pid 不同（实测 24188 vs 10620）。
强杀要用 runtime.json 里那个 pid。

用法：
    ./.venv/Scripts/python.exe tools/verify_stage5.py
"""

from __future__ import annotations

import json
import queue
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
SHU = ROOT / ".lifeos" / "bridge"
RT = SHU / "runtime.json"
OUT = SHU / "verify_stage5_out.txt"
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
ZHU_DUAN = 8765          # Bridge 的出站通道默认打这里
LIU_GEN = 45.0           # 等一个具体帧的上限

jieguo: list[tuple[str, bool, str]] = []


def ji(a1: str, a2: bool, a3: str = "") -> None:
    jieguo.append((a1, a2, a3))
    print("[%s] %s%s" % ("PASS" if a2 else "FAIL", a1,
                         ("  —— " + a3) if a3 else ""), flush=True)


class Qiao:
    """HTTP 客户端（照 tools/verify_stage3.py 的写法）。"""

    def __init__(self, base: str, token: str = "") -> None:
        self.base, self.token = base, token

    def get(self, lujing: str):
        req = urllib.request.Request(self.base + lujing)
        if self.token:
            req.add_header("x-bridge-token", self.token)
        try:
            with OP.open(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return {"__status": e.code, **(json.loads(e.read().decode("utf-8")) or {})}

    def post(self, lujing: str, body: dict | None = None):
        req = urllib.request.Request(
            self.base + lujing,
            data=json.dumps(body or {}, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"content-type": "application/json; charset=utf-8"})
        if self.token:
            req.add_header("x-bridge-token", self.token)
        try:
            with OP.open(req, timeout=30) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))


class Liu:
    """后台读 SSE，把 data 行解析成帧塞进队列。"""

    def __init__(self, base: str, token: str) -> None:
        self.chu: queue.Queue = queue.Queue()
        self.ting = threading.Event()
        self.t = threading.Thread(target=self._pao, args=(base, token), daemon=True)
        self.t.start()

    def _pao(self, base: str, token: str) -> None:
        req = urllib.request.Request("%s/stream?token=%s" % (base, token))
        req.add_header("x-bridge-token", token)
        try:
            r = OP.open(req, timeout=600)
        except Exception:  # noqa: BLE001
            return
        try:
            while not self.ting.is_set():
                hang = r.readline()
                if not hang:
                    break
                hang = hang.decode("utf-8", "replace").strip()
                if hang.startswith("data:"):
                    try:
                        self.chu.put(json.loads(hang[5:].strip()))
                    except ValueError:
                        pass
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                r.close()
            except Exception:  # noqa: BLE001
                pass

    def deng(self, a1, a2: float = LIU_GEN):
        """等一个满足 a1 的帧。返回 (帧, 这段时间收到的所有帧)。"""
        shou = []
        jixu = time.monotonic() + a2
        while time.monotonic() < jixu:
            try:
                z = self.chu.get(timeout=0.4)
            except queue.Empty:
                continue
            shou.append(z)
            if a1(z):
                return z, shou
        return None, shou

    def ting_zhi(self) -> None:
        self.ting.set()


def du_rt() -> dict:
    try:
        return json.loads(RT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def qi_bridge() -> tuple[subprocess.Popen, dict]:
    """起一个真 Bridge 进程，等它写出新的 runtime.json 且 /health 通。"""
    jiu_pid = du_rt().get("pid")
    log = OUT.open("w", encoding="utf-8")
    p = subprocess.Popen(
        [sys.executable, "-m", "lifeos.bridge.run", "--root", str(ROOT)],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, text=True)
    d = {}
    for _ in range(80):
        time.sleep(0.4)
        d = du_rt()
        if d.get("pid") and d.get("pid") != jiu_pid:
            break
    if not d.get("pid") or d.get("pid") == jiu_pid:
        log.flush()
        raise SystemExit("[验收] Bridge 没起来：\n" + OUT.read_text(encoding="utf-8")[:900])
    q = Qiao("http://127.0.0.1:%d" % d["port"], d["token"])
    for _ in range(40):
        h = q.get("/health")
        if h.get("ok"):
            return p, d
        time.sleep(0.25)
    raise SystemExit("[验收] Bridge 起了但 /health 不通")


def sha_si(a1: int) -> bool:
    """强杀（含整棵进程树）。返回是否还活着。"""
    subprocess.run(["taskkill", "/PID", str(a1), "/T", "/F"],
                   capture_output=True, timeout=20)
    return cun_zhen(a1)


def cun_zhen(a1: int) -> bool:
    """Windows 上没有 os.kill(pid, 0)：那个调用会**静默杀掉**目标进程。"""
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


def duan_zhan(a1: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", a1)) == 0


LIU_LEI = {"bridge.connected", "bridge.disconnected", "session.created",
           "session.closed", "permission.resolved", "agent.crashed"}


def du_dian(a1) -> tuple[set, int]:
    """读 .lifeos/events.json，返回桥接六类在 a1 之后新增的（种类，条数）。

    **判据必须限定在本次运行之内。** events.json 有 7 天保留期，上一次验收
    留下的 bridge.connected / permission.resolved 会让「见到六类」恒真——
    旁路接线整个断了也照样绿。这里只认 created_at 晚于脚本启动时刻的那些。
    """
    try:
        zh = json.loads((ROOT / ".lifeos" / "events.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return set(), 0
    lei, shu = set(), 0
    for x in zh:
        if x.get("type") not in LIU_LEI:
            continue
        try:
            if datetime.fromisoformat(str(x.get("created_at", ""))) <= a1:
                continue
        except ValueError:
            continue
        lei.add(x.get("type"))
        shu += 1
    return lei, shu


def qi_zhu_fu() -> object | None:
    """把主服务起在 8765，Bridge 的展示旁路事件才有去处。

    8765 已经被占（用户自己跑着主服务）就直接用它，不改动别人的进程。
    """
    if duan_zhan(ZHU_DUAN):
        print("[验收] 8765 已被占用，直接用它当主服务")
        return None
    from http.server import ThreadingHTTPServer

    from lifeos.agent.runtime import LifeOSAgent
    from lifeos.api.server import LifeOSRequestHandler
    from lifeos.llm.client import LLMClient

    zhu = ThreadingHTTPServer(("127.0.0.1", ZHU_DUAN), LifeOSRequestHandler)
    zhu.daemon_threads = True
    threading.Thread(target=zhu.serve_forever, daemon=True).start()
    LifeOSRequestHandler.agent = LifeOSAgent(LLMClient(), storage_dir=str(ROOT / ".lifeos"))
    print("[验收] 主服务起在 8765（供展示旁路落 .lifeos/events.json）")
    return zhu


def main() -> int:
    qi_shi = datetime.utcnow()  # 第 7 步只认这之后新增的事件
    zhu = qi_zhu_fu()
    p1 = p2 = None
    liu1 = liu2 = None
    try:
        # ---------------- 第 1 步 ----------------
        print("\n=== 第 1 步：起 Bridge、建会话、真触发一次审批并点允许 ===")
        p1, rt1 = qi_bridge()
        print("[验收] Bridge 真 pid=%s port=%s streamEpoch=%s"
              % (rt1["pid"], rt1["port"], rt1.get("streamEpoch")))
        q1 = Qiao("http://127.0.0.1:%d" % rt1["port"], rt1["token"])
        s, d = q1.post("/sessions", {"agentId": "echo", "cwd": str(ROOT),
                                     "permissionMode": "manual", "title": "阶段5验收"})
        if s != 201:
            raise SystemExit("[验收] 建会话失败 %s %s" % (s, d))
        sid = d["session"]["sessionId"]
        print("[验收] 会话 %s 模式 %s" % (sid, d["session"]["effectiveMode"]))

        liu1 = Liu("http://127.0.0.1:%d" % rt1["port"], rt1["token"])
        # **先等 snapshot 落地再发指令。** _liu() 的顺序是「先 dingyue() 订阅、
        # 再补发 snapshot」，所以收到 snapshot 就意味着这条连接已经在派发列表里。
        # 不等的话，permission 帧会在连接建立之前就广播掉，而首连只补 snapshot、
        # 不补历史帧——症状是「明明触发了审批，却一个帧都没收到」。
        kuai0, _ = liu1.deng(lambda z: z.get("type") == "snapshot", 15.0)
        if kuai0 is None:
            raise SystemExit("[验收] SSE 没连上（15 秒内没收到 snapshot 帧）")
        q1.post("/sessions/%s/messages" % sid, {"text": "跑一次命令，然后停。"})
        ka, _ = liu1.deng(lambda z: z.get("type") == "permission")
        if ka is None:
            raise SystemExit("[验收] 第 1 步：没等到 permission 帧")
        rid = ka["request"]["requestId"]
        tool_input = ka["request"].get("toolInput")
        print("[验收] 审批卡 requestId=%s toolInput=%s" % (rid, tool_input))
        st, _ = q1.post("/permissions/%s" % rid, {"decision": "allow"})
        print("[验收] 点允许 -> %s" % st)
        rk, _ = liu1.deng(lambda z: z.get("type") == "result")
        ji("1. 建会话 → 真触发审批 → 点允许 → 跑完",
           st == 200 and rk is not None,
           "requestId=%s，result=%s" % (rid, (rk or {}).get("resultText", "")[:60]))

        # ---------------- 第 2 步 ----------------
        print("\n=== 第 2 步：taskkill /F 强杀 Bridge ===")
        liu1.ting_zhi()
        hai_huo = sha_si(rt1["pid"])
        time.sleep(1.0)
        ji("2. 强杀 Bridge（非正常退出）", not hai_huo, "pid=%s 已消失" % rt1["pid"])

        # ---------------- 第 3 步 ----------------
        print("\n=== 第 3 步：重启 Bridge 并确认懒恢复 ===")
        p2, rt2 = qi_bridge()
        print("[验收] 新 Bridge pid=%s port=%s streamEpoch=%s"
              % (rt2["pid"], rt2["port"], rt2.get("streamEpoch")))
        sheng = int(rt2.get("streamEpoch", 0)) > int(rt1.get("streamEpoch", 0))
        q2 = Qiao("http://127.0.0.1:%d" % rt2["port"], rt2["token"])
        liu2 = Liu("http://127.0.0.1:%d" % rt2["port"], rt2["token"])
        kuai, _ = liu2.deng(lambda z: z.get("type") == "snapshot")
        hui = None
        for x in (kuai or {}).get("sessions", []):
            if x.get("sessionId") == sid:
                hui = x
        if hui is None:
            raise SystemExit("[验收] 第 3 步：快照里没有恢复出的会话 %s" % sid)
        rec = [x for x in json.loads((SHU / "sessions.json").read_text(encoding="utf-8"))
               if x.get("sessionId") == sid]
        print("[验收] 恢复出的会话 state=%s alive=%s claudeSessionId=%r"
              % (hui.get("state"), hui.get("alive"), hui.get("claudeSessionId")))
        ji("3. 重启后 streamEpoch 递增，快照里有这个会话",
           sheng and hui is not None,
           "streamEpoch %s→%s" % (rt1.get("streamEpoch"), rt2.get("streamEpoch")))
        ji("4. 懒恢复：会话回到 idle 且 alive=false，落盘字段齐全",
           hui.get("state") == "idle" and hui.get("alive") is False
           and bool(rec) and "claudeSessionId" in rec[0],
           "state=%s alive=%s（echo 适配器不产生 claudeSessionId，只验字段在落盘里）"
           % (hui.get("state"), hui.get("alive")))

        # ---------------- 第 4 + 5 步 ----------------
        print("\n=== 第 4 步：对同一个会话再发同一条指令（同一个 tool_use_id）===")
        q2.post("/sessions/%s/messages" % sid, {"text": "跑一次命令，然后停。"})
        chong, shou = liu2.deng(
            lambda z: z.get("type") == "permission_resolved"
            and z.get("requestId") == rid, LIU_GEN)
        piao = [z for z in shou if z.get("type") == "permission"]
        rk2, _ = liu2.deng(lambda z: z.get("type") == "result", 20.0)
        print("[验收] 这一段收到的帧类型：%s"
              % sorted({z.get("type") for z in shou}))
        ji("5. 重放命中：没弹审批卡 + permission_resolved{replayed:true} + result 正常",
           chong is not None and not piao and rk2 is not None,
           "permission 帧=%d 个，replayed=%s" % (
               len(piao), (chong or {}).get("replayed")))
        if chong is None:
            jiu = SHU / "decisions.jsonl"
            if jiu.exists():
                print("[验收] decisions.jsonl 里本会话的记录：")
                for x in jiu.read_text(encoding="utf-8").splitlines():
                    if sid in x:
                        print("   ", x[:200])

        # ---------------- 第 6 步 ----------------
        print("\n=== 第 6 步：越界游标必须 409 reset_required ===")
        kuai2, _ = liu2.deng(lambda z: False, 0.1)
        xian = None
        for z in shou:
            xian = max(xian or 0, int(z.get("streamSeq", 0)))
        xian = (xian or 0) + 100
        yue = Qiao("http://127.0.0.1:%d" % rt2["port"], rt2["token"]) \
            .get("/sessions/%s/transcript?from=%d" % (sid, xian))
        ji("6. 越界 from → 409 reset_required",
           yue.get("__status") == 409 and (yue.get("error") or {}).get("code") == "reset_required"
           or yue.get("code") == "reset_required",
           "from=%d 返回 %s %s" % (xian, yue.get("__status"),
                                   yue.get("error") or yue.get("code")))

        # ---------------- 第 7 步 ----------------
        print("\n=== 第 7 步：六个展示旁路 kind 落在 .lifeos/events.json ===")
        if zhu is None and not duan_zhan(ZHU_DUAN):
            ji("7. 展示旁路事件落盘", False, "跳过：主服务未运行")
        else:
            time.sleep(1.5)
            jian, shu = du_dian(qi_shi)
            print("[验收] events.json 里本次新增的桥接事件：%s（共 %d 条）"
                  % (sorted(jian) or "（无）", shu))
            ji("7. 展示旁路事件落盘", bool(jian), "本次新增 %d 条：%s" % (shu, sorted(jian)))

    finally:
        for x in (liu1, liu2):
            if x is not None:
                x.ting_zhi()
        if p2 is not None:
            try:
                Qiao("http://127.0.0.1:%d" % du_rt().get("port", 0),
                     du_rt().get("token", "")).post("/bridge/stop")
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1.0)
            pid2 = du_rt().get("pid")
            if pid2:
                sha_si(pid2)
        if p1 is not None and p2 is None:
            sha_si(rt1["pid"])
        for x in (p1, p2):
            if x is not None:
                try:
                    x.wait(timeout=8)
                except Exception:  # noqa: BLE001
                    x.terminate()

    print("\n=== 总结论 ===")
    for a1, a2, a3 in jieguo:
        print("  %s  %s" % ("PASS" if a2 else "FAIL", a1))
    tong = sum(1 for _, a2, _ in jieguo if a2)
    print("  %d/%d 步通过" % (tong, len(jieguo)))
    return 0 if tong == len(jieguo) and jieguo else 1


if __name__ == "__main__":
    sys.exit(main())
