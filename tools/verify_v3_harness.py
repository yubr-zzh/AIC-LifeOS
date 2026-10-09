"""v3.0 统一真机验收脚本（L-D）。`python tools/verify_v3_harness.py --agent codex`

**它补的是什么缺口**：v3.0 任务 1–4 全程没有 L-D。codex 的任务 3 提交自己
写的是「L-B/L-C 两层验收」，而任务表把 L-D 也列在任务 3 里，进度表照抄打了个 ✅。
后果是 codex 的**审批往返 / 仲裁收口 / pid 回收在真实 Bridge 里一次都没跑过**——
那三样恰好是 `ZiChengAdapter` 与 `http._cheng_bu` / `arbiter.shou` / `sha_qing_dian`
的接合处，单测（mock 掉 `cheng`）与 L-C（真适配器、假 Bridge）都抓不到。

**它不做什么**（方案 §6.1 的分级）：
- 不验协议翻译（那是 L-B，`tests/test_<名>_fan_yi.py`）
- 不替代 L-C（本脚本不 spawn 裸适配器，走的是完整 HTTP 链路）
- **不验多适配器并发、畸形帧、断连边缘**——本轮从简。

## 判据落在哪里

每条断言都落在「实现对与错真的会读出不同值」的量上：

| 断言 | 两种实现的分岔 |
|---|---|
| `/agents` 里有这个 agentId 且 `available` | 注册表漏加 / `ZHI_LING` 拼错 |
| `moshi` 非空且 ⊆ 全局白名单 | 写越界值 ⇒ 用户选下去必然 400 |
| 建会话 201 且 `agentId` 回显 | `ZHU_CE_QI.get` 落空 ⇒ 静默变 EchoAdapter |
| 无回路 harness 不带知情同意 → 400 `agent_unavailable` | 闸门 0 没在岗 ⇒ 全程零审批静默放行 |
| SSE 里出现 `result` 且 `isError` 为假 | **回合边界判错**（最常见假绿）⇒ 挂到看门狗 |
| `result.resultText` 非空 | 翻译层把正文丢了但边界仍收口 |
| `state` 终态是 `ended` | `paichu` 的收尾没跑到 |
| 审批：`permission_resolved` 带 `decision` | 仲裁没收口 ⇒ future 永远醒不过来 |
| 审批：收口后回合仍能走到 `result` | 决定回得去但 Agent 侧没收口 |
| 关闭后 `runtime.json` 的 `pids` 空 | **pid 没被回收** ⇒ 关了 Bridge agent 还在改文件 |
| 关闭后那个 pid 真不在了 | 只清了字典没杀进程 |

**不 sleep 固定时长**：本机实测 `sleep(2.0)` 在 Windows 上必然 flake。
全部改成「等某个条件成立，超时报错并把实际序列打出来」。

## 隔离

`--root` 给临时目录 ⇒ `runtime.json` / 会话 / 决定流水都不进真目录。
**但 `pingju.PINGJU_GEN` 认 `Path.home()` 而不认 `--root`**（`pingju.py:36`），
所以子进程的 `USERPROFILE` 与 `HOME` 一并指到临时目录——不隔离就会在
`~/.lifeos-bridge/users/` 真实凭据根下建目录。

⚠ **cwd 必须是项目根，不能是 `--root`。** 那里没有 `lifeos` 包 ⇒
`python -m lifeos.bridge.run` 直接 ModuleNotFoundError（`verify_stage7.py`
的 `qi_bridge` docstring 记了这个坑）。`--root` 是命令行参数，与进程 cwd 无关。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

# 复用 verify_stage7 的进程/端口助手——**不复用会踩 Windows 的两个死穴**：
# `os.kill(pid, 0)` 在 Windows 上会静默杀掉目标进程；`taskkill` 不带 `/T`
# 会留下带用户全部权限的孤儿。
from verify_stage7 import cun_zhen, duan_kong, sha_si  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
YUAN = "http://127.0.0.1:5173"   # 反代来源白名单里的一项（`auth.yuanbai`）
DK = 8790                       # Bridge 起始端口。与 8766（dev 默认）分开
SHAO = 240.0                    # 等一回合的上限。真实模型几秒到几十秒

jieguo: list[tuple[str, bool, str]] = []


def ji(a1: str, a2: bool, a3: str = "") -> None:
    """记一条断言。"""
    jieguo.append((a1, a2, a3))
    print("[%s] %s%s" % ("PASS" if a2 else "FAIL", a1,
                         ("  —— " + a3) if a3 else ""), flush=True)


def bao(a1: str, a2: str = "") -> None:
    """打印一行现场信息（不是断言）。"""
    print("[验收] %s%s" % (a1, ("：" + a2) if a2 else ""), flush=True)


# ---------- Bridge 进程的起与停 ----------

def du_rt(a1: Path) -> dict:
    """读 runtime.json。读不到/读坏一律按空对象。"""
    p = a1 / ".lifeos" / "bridge" / "runtime.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def zhao_duan(a1: int) -> int:
    """从 `a1` 起找一个能绑的端口。

    **必须在起 Bridge 之前占住再放掉**：直接让 `run.zhao_kong` 去找，
    它与本脚本的探测之间有竞态（两个进程都判空闲，然后都绑上）。
    """
    for duan in range(a1, a1 + 40):
        if duan_kong(duan):
            return duan
    raise SystemExit("[验收] %d 起往上 40 个端口全被占" % a1)


def qi_bridge(a1: Path, a2: Path, a3: int) -> tuple[subprocess.Popen, dict]:
    """起一个真 Bridge 进程（另一个进程树），等它写出新的 runtime.json 且 /health 通。

    `a1` 是 `--root`，`a2` 是临时家目录，`a3` 是显式起始端口。

    **显式端口是必须的**：`run.zhao_kong` 在 Windows 上设了 `SO_REUSEADDR`
    ——那个选项恰恰允许第二个 socket 绑同一地址（`verify_stage7.py` 的
    `qi_bridge` docstring 记了这个坑）。
    """
    rt = a1 / ".lifeos" / "bridge" / "runtime.json"
    jiu_qian = du_rt(a1).get("pid")
    # 日志目录**必须先建**：`run.py` 要等自己走到 `zhu_ri()` 才建它，
    # 而它建之前 stdout 已经被这里重定向进这个文件 ⇒ 谁也不会建这个目录。
    (a1 / ".lifeos" / "bridge").mkdir(parents=True, exist_ok=True)
    log = (a1 / ".lifeos" / "bridge" / "verify_v3.log").open("a", encoding="utf-8")
    # ⚠⚠ **不要重定向 HOME / USERPROFILE。**
    # 第一版为了隔离凭据根，把这两个都指到临时目录 —— 结果 codex 去了临时目录
    # 找 `~/.codex/config.toml`，找不到就退回默认 provider ⇒ 回合一路
    # `Reconnecting... waiting for network`。**症状完全像代码缺陷**（适配器
    # 挂死、回合不收口），而真因是验收脚本自己改了用户的 CLI 配置环境。
    # 对照证据：项目的 `tests/test_codex_lc_ji_cheng.py` 不重定向 HOME，
    # 同一套参数 5 passed / 46 秒跑通。
    #
    # 隔离改用 `LIFEOS_BING_JIA`（见下方 pingju 段的说明）：只让 LifeOS 的
    # 凭据根落到临时目录，不动 CLI 自己的配置目录。
    huan = dict(os.environ)
    huan.pop("LIFEOS_USER", None)
    huan["LIFEOS_BING_JIA"] = str(a2)
    p = subprocess.Popen(
        [sys.executable, "-m", "lifeos.bridge.run", "--root", str(a1),
         "--port", str(a3)],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, env=huan, text=True)
    xian: dict = {}
    for _ in range(150):
        time.sleep(0.4)
        if p.poll() is not None:
            log.flush()
            raise SystemExit("[验收] Bridge 起来又退出（%s）：\n%s"
                             % (p.returncode, _wei_kou(a1)))
        xian = du_rt(a1)
        # **pid 必须变**：只判「有 pid」的话，上一次那次的落盘会被当成本次的。
        if xian.get("pid") and xian.get("port") and xian["pid"] != jiu_qian:
            break
        xian = {}
    if not xian.get("pid") or xian.get("pid") == jiu_qian:
        raise SystemExit("[验收] Bridge 没起来（pid 仍是旧的 %s）：\n%s"
                         % (jiu_qian, _wei_kou(a1)))
    for _ in range(60):
        try:
            with OP.open(urllib.request.Request(
                    "http://127.0.0.1:%d/health" % int(xian["port"])), timeout=3) as r:
                if json.loads(r.read().decode("utf-8")).get("ok"):
                    return p, xian
        except Exception:  # noqa: BLE001
            time.sleep(0.25)
    raise SystemExit("[验收] Bridge 起了但 /health 不通（pid=%s port=%s）：\n%s"
                     % (xian.get("pid"), xian.get("port"), _wei_kou(a1)))


def _wei_kou(a1: Path) -> str:
    p = a1 / ".lifeos" / "bridge" / "verify_v3.log"
    try:
        return p.read_text(encoding="utf-8")[-1500:]
    except OSError:
        return "(没有日志)"


def ting_bridge(a1: Path, a2: subprocess.Popen) -> None:
    """先 `POST /bridge/stop`（让适配器走正常关闭路径），再按 pid 兜底杀。"""
    yun = du_rt(a1)
    duan = int(yun.get("port") or 0)
    if duan:
        try:
            Zhi("http://127.0.0.1:%d" % duan, str(yun.get("token") or "")).post(
                "/bridge/stop")
            time.sleep(1.5)
        except Exception:  # noqa: BLE001
            pass
    pid = int(yun.get("pid") or 0)
    if pid:
        sha_si(pid)
    try:
        a2.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


# ---------- HTTP 客户端 ----------

class Zhi:
    """Bridge 本机端口的客户端。

    **令牌走 `x-bridge-token` 头**，不是 `Authorization`（`http.py:193`
    的 `auth.duanren`）。写成 Authorization 会 401，而 401 在脚本里
    是要区分「归属挡住」与「头写错了」的东西。
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
        with self._kai(a1) as r:
            try:
                return r.status, json.loads(r.read().decode("utf-8"))
            except ValueError:
                return r.status, {}

    def post(self, a1: str, a2: dict | None = None) -> tuple[int, dict]:
        with self._kai(a1, "POST", a2 or {}) as r:
            try:
                return r.status, json.loads(r.read().decode("utf-8"))
            except ValueError:
                return r.status, {}


class Liu:
    """SSE 订阅。把所有帧收进 `self.zhen`，供断言按类型筛。

    **后台线程 + 无锁 list.append**：CPython 的 list.append 是原子的，
    而 SSE 写线程在 Bridge 进程里、这里只读，不存在「读一半」的中间态。
    """

    def __init__(self, a1: int, a2: str, a3: int) -> None:
        self.zhen: list[dict] = []
        self.die = threading.Event()
        self.lei: list[Exception] = []
        req = urllib.request.Request("http://127.0.0.1:%d/stream" % a1)
        req.add_header("Origin", YUAN)
        req.add_header("x-bridge-token", a2)
        req.add_header("x-lifeos-source", "verify-v3")
        self.lei_sou = OP.open(req, timeout=a3)
        self.chi = threading.Thread(target=self._du, daemon=True)
        self.chi.start()

    def _du(self) -> None:
        try:
            while not self.die.is_set():
                hang = self.lei_sou.readline()
                if not hang:
                    break
                hang = hang.decode("utf-8", "replace").strip()
                if hang.startswith("data:"):
                    try:
                        self.zhen.append(json.loads(hang[5:].strip()))
                    except ValueError:
                        continue
        except Exception as e:  # noqa: BLE001
            self.lei.append(e)

    def dai(self, a1: str, a2: float, a3: str | None = None) -> dict | None:
        """等一帧 `type == a1`。`a3` 给定时额外要求该帧的 sid 或 requestId 匹配。

        **超时把实际见到的类型序列打出来**——「等到超时」四个字不带现场的话，
        排查的人只能重跑一遍。
        """
        zhong = time.monotonic() + a2
        while time.monotonic() < zhong:
            for z in self.zhen:
                if z.get("type") != a1:
                    continue
                if a3 and str(z.get("sessionId") or "") != a3 and \
                        str((z.get("request") or {}).get("requestId") or "") != a3:
                    continue
                return z
            time.sleep(0.15)
        bao("等 `%s` 超时" % a1, "实际见到的帧类型：%s"
            % " → ".join(str(z.get("type")) for z in self.zhen[-14:]))
        return None

    def guan(self) -> None:
        self.die.set()
        try:
            self.lei_sou.close()
        except Exception:  # noqa: BLE001
            pass


def lei_ming(a1: list[dict], a2: str) -> list[dict]:
    return [z for z in a1 if z.get("type") == a2]


# ---------- 各步 ----------

def bu_1_tan_ce(z: Zhi, a1: str) -> dict | None:
    """第 1 步：`/agents` 上报。返回那一行，没有就 None。"""
    st, w = z.get("/agents")
    if st != 200:
        ji("/agents 返回 200", False, "实际 %s" % st)
        return None
    ji("/agents 返回 200", True)
    for x in (w.get("agents") or []):
        if x.get("agentId") == a1:
            bao("能力上报", json.dumps(
                {k: x.get(k) for k in ("agentId", "label", "available", "version",
                                       "fangquan", "wenti2", "moshi", "yi_ci_xing",
                                       "dui_hui_id", "xu_pei_zhuang")},
                ensure_ascii=False))
            return x
    ji("/agents 里有 " + a1, False,
       "只报了：%s" % [x.get("agentId") for x in (w.get("agents") or [])])
    return None


def bu_2_jian_hui(z: Zhi, a1: str, a2: str, a3: bool) -> str:
    """第 2 步：建会话。返回 sid，失败返回空串。

    **cwd 必须在信任根内**：`planner_guard.ShenKa._moren()` 是
    「项目根 + 用户主目录」，本脚本用项目根。

    **闸门 0（2026-10-06 起）**：`fangquan()=False` 的 harness 建会话时，
    后端要求 `acknowledgeNoApproval` 严格为 True，否则 400
    `agent_unavailable`。所以这步分两段——没有审批回路的 harness 先
    **不带同意**发一次，断言闸门 0 真把它拦下了，再带同意重建；
    有回路的 harness 不带这个键（带了等于替用户说一句他没说过的话）。
    """
    ti = {"agentId": a1, "cwd": str(ROOT),
          "permissionMode": "manual", "title": a2}
    if not a3:
        st0, w0 = z.post("/sessions", dict(ti))
        ji("无回路 harness 不带知情同意 → 400 agent_unavailable",
           st0 == 400 and (w0.get("error") or {}).get("code") == "agent_unavailable",
           "实际 %s %s" % (st0, json.dumps(w0, ensure_ascii=False)[:160]))
        ti["acknowledgeNoApproval"] = True
    st, w = z.post("/sessions", ti)
    if st != 201:
        ji("建会话返回 201", False, "%s %s" % (st, json.dumps(w, ensure_ascii=False)[:200]))
        return ""
    hui = w.get("session") or {}
    ji("建会话返回 201", True, "sid=%s" % hui.get("sessionId"))
    ji("会话回显 agentId", hui.get("agentId") == a1,
       "实际 %r" % hui.get("agentId"))
    # **不能建在 echo 上**：`ZHU_CE_QI.get` 落空时 `xin_jian` 静默用
    # EchoAdapter（`http.py:932`），会话照样 201、界面照样显示 agentId，
    # 而真机跑的是假适配器。回显 agentId 是唯一能分开的地方。
    return str(hui.get("sessionId") or "")


def bu_3_fa_yi_tiao(z: Zhi, liu_: Liu, a1: str, a2: str, a3: str) -> dict | None:
    """第 3 步：发一条真指令，等到回合结束。返回 result 帧。

    ⚠ **指令要短、要确定**，否则断言没法判对错。用「只回两个字」把
    模型的自由发挥压到最小——本脚本断言的是**回合收口**，不是回答质量。
    """
    st, w = z.post("/sessions/%s/messages" % a1, {"text": a2})
    if st != 202:
        ji("发指令返回 202", False, "%s %s" % (st, json.dumps(w, ensure_ascii=False)[:200]))
        return None
    ji("发指令返回 202", True, "messageId=%s" % (w.get("messageId") or ""))
    jie = liu_.dai("result", a3, a1)
    if jie is None:
        # **超时必须把 error 帧打出来**：回合没收口的原因九成在 error 帧里，
        # 只说「等超时」的话排查的人只能重跑一遍。这里只打最近几条。
        cuo = lei_ming(liu_.zhen, "error")[-4:]
        ji("SSE 收到 result 帧", False,
           "回合没在 %.0fs 内收口；最近的 error 帧：%s"
           % (a3, json.dumps(cuo, ensure_ascii=False)[:400]))
        return None
    ji("SSE 收到 result 帧", True)
    if jie.get("isError"):
        # **错误回合必须把 error 帧一起打出来**：result 的 resultText 可能是空的
        # （错误原因走 error 帧那条通道，不走 result），只报 result 的话
        # 只能看到「失败了」而看不到「为什么」。第一版就栽在这。
        cuo = lei_ming(liu_.zhen, "error")[-3:]
        ji("result 不是错误回合", False,
           "isError=%r subtype=%r resultText=%r ｜ 最近的 error 帧：%s"
           % (jie.get("isError"), jie.get("subtype"),
              str(jie.get("resultText") or "")[:80],
              json.dumps(cuo, ensure_ascii=False)[:360]))
    else:
        ji("result 不是错误回合", True,
           "subtype=%r resultText=%r"
           % (jie.get("subtype"), str(jie.get("resultText") or "")[:80]))
    wen = str(jie.get("resultText") or "")
    ji("resultText 非空", bool(wen.strip()), "长度 %d" % len(wen))
    ji("batchDone 已自增", int(jie.get("batchDone") or 0) >= 1,
       "batchDone=%s batchTotal=%s" % (jie.get("batchDone"), jie.get("batchTotal")))
    return jie


def bu_4_ze_bu(liu_: Liu, a1: str = "", a2: float = 20.0) -> None:
    """第 4 步：状态终态是 `ended`。

    `paichu` 的收尾写 `ended`（`session.py:365`），而 `idle` 是每条指令
    **之间**的中间态。判「出现过 ended」而不是「最后一个是 ended」——
    判后者的话，中断后的 `idle` 会把它判成失败。
    ⚠ **第一版写成「见到任意 state 帧就 break」，于是永远只看第一帧
    `thinking(batch_start)`，把一个收口完全正常的回合判成 FAIL。**
    判据落在了「有没有帧出现」而不是「收口状态到没到」——两种实现读出来
    一样 ⇒ 假红。本脚本自己踩了一遍。
    """
    zhong = time.monotonic() + a2
    while time.monotonic() < zhong:
        zhuang = [(str(z.get("state")), str(z.get("lastEvent")))
                  for z in lei_ming(liu_.zhen, "state")
                  if not a1 or str(z.get("sessionId")) == a1]
        if any(s == "ended" for s, _ in zhuang):
            break
        time.sleep(0.2)
    bao("状态迁移", " → ".join("%s(%s)" % x for x in zhuang))
    ji("状态迁移里出现过 ended", any(s == "ended" for s, _ in zhuang),
       "实际 %s" % zhuang)


def bu_5_shen_qing(liu_: Liu, z: Zhi, a1: str, a2: bool, a3: float = 30.0) -> str:
    """第 5 步：审批往返。返回 'allow' / 'deny' / 'none'（没触发审批）。

    **只在 harness 声明有权限回路时跑**（`fangquan()`），否则断言的是
    一个兑现不了的东西——这与 `MOSHI_ZI` 写错的后果同类。

    ⚠ **没有审批被触发时如实报 'none'，不算失败**：模型自己决定要不要
    请求审批，发一条「只回一个字」的指令很可能一次工具都不调。
    那种情况下本步只验「回合仍然收口」，审批链路由 codex 的 L-C
    与单测覆盖。但**触发了就必须走完**，不许看到卡片就当过了。
    """
    if not a2:
        bao("审批往返", "该 harness 声明 fangquan=False，本步跳过")
        return "none"
    # 审批帧可能在第 3 步之前就已经来过（挂起时回合还没收口）。
    shen = lei_ming(liu_.zhen, "permission")
    if not shen:
        bao("审批往返", "这一轮没有触发审批（模型没调工具）")
        ji("无审批时回合仍收口", bool(lei_ming(liu_.zhen, "result")),
           "回合没走到 result")
        return "none"
    x = shen[-1]
    qing = x.get("request") or {}
    rid = str(qing.get("requestId") or "")
    bao("审批请求", "requestId=%s tool=%s"
        % (rid, qing.get("toolName")))
    ji("审批帧带 requestId", bool(rid))
    ji("审批帧带 toolName", bool(qing.get("toolName")), repr(qing.get("toolName")))
    ji("审批时状态是 attention",
       any(s == "attention" for s, _ in
           [(str(y.get("state")), "") for y in lei_ming(liu_.zhen, "state")]),
       "闸门外的状态迁移里没有 attention")
    st, w = z.post("/permissions/%s" % rid, {"decision": "allow"})
    ji("批允许返回 200", st == 200,
       "%s %s" % (st, json.dumps(w, ensure_ascii=False)[:160]))
    ji("决定回的是 user_allow", str(w.get("decision") or "") == "user_allow",
       "实际 %r" % w.get("decision"))
    ji("不是自动决定", w.get("autoDecided") is False, repr(w.get("autoDecided")))
    # 二次提交必须 409：返回 200 会让前端把卡片关掉，用户以为批准了、
    # Agent 实际收到的是拒绝——UI 在撒谎。
    st2, _ = z.post("/permissions/%s" % rid, {"decision": "deny"})
    ji("同 requestId 二次提交 409", st2 == 409, "实际 %s" % st2)
    shou = liu_.dai("permission_resolved", a3)
    if shou is None:
        ji("SSE 收到 permission_resolved", False, "仲裁没收口")
        return "allow"
    ji("SSE 收到 permission_resolved", True,
       "decision=%s" % shou.get("decision"))
    ji("permission_resolved 的决定是 user_allow",
       str(shou.get("decision") or "") == "user_allow",
       "实际 %r" % shou.get("decision"))
    # **收口后回合必须还能走到 result**：这是「决定回得去」与
    # 「Agent 侧真收到并继续跑」的分岔点。只判前者的话，
    # 一个把决定丢掉但照样 resolve future 的实现照样全绿。
    jie = liu_.dai("result", a3, a1)
    if jie is not None:
        ji("审批后回合仍收口", not jie.get("isError"),
           str(jie.get("resultText") or "")[:120])
    else:
        ji("审批后回合仍收口", False, "收口之后没有 result 帧")
    return "allow"


def bu_6_zhong_duan(z: Zhi, liu_: Liu, a1: str) -> None:
    """第 6 步：中断。

    ⚠ **端点返回 200 不是「中断成功」的证据**——`_zhong_duan` 里写死了
    「中断信号发不出去也要返回 200」（挂起项已收口，用户目的已达成）。
    真正的判据是**会话状态离开 `thinking`**：发一条长一点的指令再立刻中断，
    如果实现没真把信号送到适配器，状态会一直挂在 thinking 直到看门狗。
    """
    z.post("/sessions/%s/messages" % a1,
           {"text": "数一遍 1 到 20，每个一行，不要有别的。"})
    time.sleep(1.5)      # 给它起来的时间；不 sleep 的话中断会打在 kaishi 之前
    st, w = z.post("/sessions/%s/interrupt" % a1)
    ji("中断返回 200", st == 200,
       "%s %s" % (st, json.dumps(w, ensure_ascii=False)[:160]))
    zhong = time.monotonic() + 25
    while time.monotonic() < zhong:
        zhuang = [str(z2.get("state")) for z2 in lei_ming(liu_.zhen, "state")]
        if zhuang and zhuang[-1] != "thinking":
            break
        time.sleep(0.25)
    zhuang = [(str(z2.get("state")), str(z2.get("lastEvent")))
              for z2 in lei_ming(liu_.zhen, "state")]
    bao("中断后的状态序列", " → ".join("%s(%s)" % x for x in zhuang[-6:]))
    ji("中断后会话离开 thinking",
       bool(zhuang) and zhuang[-1][0] != "thinking",
       "末尾仍是 %s" % (str(zhuang[-1]) if zhuang else "（没收到 state 帧）"))


def bu_7_guan_bi(z: Zhi, a1: Path, a2: str, a3: subprocess.Popen) -> None:
    """第 7 步：关闭 + **pid 真的被回收**（这一条是 L-D 独有的）。

    判据不是「适配器说关了」而是**操作系统层面那个进程还在不在**。
    真机实测过：`disconnect()` 在有请求在飞时不保证子进程退出，
    四条会话里有两条活过了两段式关闭——一个带着用户全部权限的
    `claude` 进程留在后台继续改文件（`http.py` 的 `sha_pid` docstring）。

    **pid 会被系统很快复用**，所以只查「现在不在」在「本来就没起来过」的
    实现上也成立——所以先记关之前的存活列表，只对**当时真活着的**那些断言。

    ⚠ **2026-10-06 起一次性进程的 pid 也在册了**（`_qi_chi_cheng` 后经
    `pid_hui` 回调上报，`http.xin_jian` 注入），本步对 kimi/opencode/hermes
    不再是空断言——跑这三家时看到「关闭前 runtime.json 的 pids」非空，
    读作「回调链真的在工作」，别当成异常。
    """
    yun = du_rt(a1)
    pids = [int(x.get("pid")) for x in (yun.get("pids") or []) if x.get("pid")]
    huo = [p for p in pids if cun_zhen(p)]
    bao("关闭前 runtime.json 的 pids", "%s（其中活着的 %s）" % (pids, huo))
    st, _ = z.post("/sessions/%s/close" % a2)
    ji("关闭会话返回 200", st == 200, "实际 %s" % st)
    time.sleep(2.0)
    # ⚠ **判据是「没有活着的 pid」，不是「pids 为空」。**
    # 空列表在「有并发 spawn 时」会假红：`_pao` 每条指令各开一个线程，
    # 各自 `xin_jian()` → 各 spawn 一个适配器 → 各注册一个 pid。中断那步
    # 刚发的指令若还在起适配器，关闭的 `sha_qing_dian` 扫完它才落盘 ⇒ 列表
    # 里留下一个**已经死掉的**条目（实测 claude-code 跑出过 pids=[33828,38060]，
    # 关完剩一个死条目）。而残留的死条目无害——下次启动 `run.sao_bing`
    # 会照 `pids` 清一遍。真正的危害是**活着的孤儿进程**（带用户全部权限
    # 在后台改文件），那才是要判的量。
    pi = [int(x.get("pid")) for x in (du_rt(a1).get("pids") or []) if x.get("pid")]
    huo2 = [x for x in pi if cun_zhen(x)]
    ji("关闭后 runtime.json 里没有活着的 pid", not huo2,
       "还活着的 %s（死条目 %s 无害，下次启动 sao_bing 会清）"
       % (huo2, [x for x in pi if x not in huo2]))
    for pid in huo:
        # **文案与判据必须一致**：写 `ji(…, not cun_zhen(pid), "还活着")`
        # 会打成 `[PASS] 子进程 31388 真被杀了 —— 还活着`，读的人得反过来
        # 才知道自己看到的是好消息。失败时的说明单独给。
        ji("子进程 %d 已不在（关闭前活着）" % pid, not cun_zhen(pid),
           "它还活着" if cun_zhen(pid) else "")
    # 再验两段式关闭的第一段：停 Bridge 后 pids 也得空。
    ting_bridge(a1, a3)
    zui = [int(x.get("pid")) for x in (du_rt(a1).get("pids") or []) if x.get("pid")]
    huo3 = [x for x in zui if cun_zhen(x)]
    ji("停 Bridge 后没有活着的孤儿进程", not huo3,
       "还活着的 %s（死条目 %s 由下次启动的 sao_bing 清）"
       % (huo3, [x for x in zui if x not in huo3]))


def main() -> int:
    d = argparse.ArgumentParser(prog="verify_v3_harness")
    d.add_argument("--agent", required=True, help="agentId，如 codex / claude-code")
    d.add_argument("--cwd", default=str(ROOT), help="会话 cwd（必须在信任根内）")
    d.add_argument("--keep", action="store_true", help="跑完不删临时目录")
    d.add_argument("--timeout", type=float, default=SHAO, help="等一回合的秒数")
    args = d.parse_args()

    gen = Path(tempfile.mkdtemp(prefix="lifeos-v3-"))
    jia = gen / "jia"           # 临时家目录，隔离凭据根
    jia.mkdir(parents=True, exist_ok=True)
    duan = zhao_duan(DK)
    bao("临时 root", str(gen))
    bao("Bridge 起始端口", str(duan))

    # 先在**本进程**里 import 注册表拿能力契约：断言「声明了什么」，
    # 不依赖 Bridge 起来（起来之前 `/agents` 也报不了）。
    from lifeos.bridge.adapters import ZHU_CE_QI
    from lifeos.bridge.models import MOSHI

    cls = ZHU_CE_QI.get(args.agent)
    if cls is None:
        print("[验收] 注册表里没有 %s，现有：%s"
              % (args.agent, sorted(ZHU_CE_QI)), flush=True)
        return 2

    p, yun = qi_bridge(gen, jia, duan)
    z = Zhi("http://127.0.0.1:%d" % int(yun["port"]), str(yun.get("token") or ""))
    bao("Bridge 起来了", "pid=%s port=%s" % (yun.get("pid"), yun.get("port")))

    global liu
    liu = Liu(int(yun["port"]), str(yun.get("token") or ""), args.timeout + 60)
    sid = ""
    try:
        # ---- 能力契约（进程内，先于 HTTP 判）----
        zi = getattr(cls, "MOSHI_ZI", frozenset())
        bao("类属性", "MOSHI_ZI=%s dui_hui_id=%s yi_ci_xing=%s fangquan=%s wenti2=%s"
            % (sorted(zi) or "(空=退回全局)", cls.dui_hui_id, cls.yi_ci_xing,
               cls.fangquan(), cls.wenti2()))
        ji("MOSHI_ZI 不越界（⊆ 全局白名单）", not zi or zi <= set(MOSHI),
           "越界值 %s" % sorted(zi - set(MOSHI)))
        ji("声明了 ZHI_LING（ZiChengAdapter 系）",
           bool(getattr(cls, "ZHI_LING", None)) or args.agent == "claude-code",
           "ZHI_LING=%r" % getattr(cls, "ZHI_LING", None))

        xian = bu_1_tan_ce(z, args.agent)
        if xian is not None:
            ji("上报 available=true", bool(xian.get("available")),
               "ce_shi=%s" % json.dumps(xian.get("ce_shi"), ensure_ascii=False)[:160])
            ji("上报的 moshi 非空", bool(xian.get("moshi")),
               "空数组会让前端的模式下拉框全空")
            ji("上报的 moshi ⊆ 全局白名单",
               set(xian.get("moshi") or []) <= set(MOSHI), str(xian.get("moshi")))
            ji("上报的 fangquan 与类属性一致",
               bool(xian.get("fangquan")) == bool(cls.fangquan()),
               "上报 %r / 类属性 %r" % (xian.get("fangquan"), cls.fangquan()))

        sid = bu_2_jian_hui(z, args.agent, "verify-v3", bool(cls.fangquan()))
        if sid:
            bu_3_fa_yi_tiao(z, liu, sid, "只回答两个字：收到", args.timeout)
            bu_4_ze_bu(liu, sid)
            bu_5_shen_qing(liu, z, sid, bool(cls.fangquan()))
            bu_6_zhong_duan(z, liu, sid)
            bu_7_guan_bi(z, gen, sid, p)
    finally:
        try:
            liu.guan()
        except Exception:  # noqa: BLE001
            pass
        if not sid:
            # 第 7 步没跑到（前面就断了）才需要在这里收尾
            ting_bridge(gen, p)
        if not args.keep:
            shutil.rmtree(gen, ignore_errors=True)
        else:
            bao("临时目录保留在", str(gen))

    # ---- 汇总 ----
    huan = [x for x in jieguo if not x[1]]
    print("\n===== L-D 验收汇总（%s）=====" % args.agent)
    print("断言 %d 条，通过 %d，失败 %d"
          % (len(jieguo), len(jieguo) - len(huan), len(huan)))
    for ti, _, chu in huan:
        print("  FAIL %s%s" % (ti, ("  —— " + chu) if chu else ""))
    if huan:
        print("\n结果：FAIL")
        return 1
    print("\n结果：全部通过")
    print("⚠ 通过 ≠ 已验证：协议翻译（L-B）在 tests/test_<名>_fan_yi.py，"
          "裸适配器回合（L-C）在 tests/test_<名>_lc_ji_cheng.py。"
          "本脚本只覆盖 HTTP 链路这一层。")
    return 0


if __name__ == "__main__":
    sys.exit(main())