"""Bridge 进程入口：端口发现、运行时文件、孤儿清理（方案 5.1、5.2、12.2 任务 1.2/1.6）。

启动四步的顺序不可调换：**先杀孤儿，再探端口**。反过来做的话，
Bridge 被强杀或断电后残留的 `claude` 子进程就永远带着用户全部权限留在后台继续改文件。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import socket
import sys
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from lifeos.bridge import auth, jiaojie, pipei, pingju
from lifeos.bridge.cun import Cun, shou_quan
from lifeos.bridge.events import ZongXian
from lifeos.bridge.http import BridgeHandler, BridgeServer
from lifeos.bridge.localbus import LuDao
from lifeos.bridge.models import AgentMessage, AgentSession, guo_lu1, xianzai
from lifeos.bridge.planner_guard import ShenKa
from lifeos.bridge.session import HuiHua

DK = 8766  # 起始端口
DK_CI = 8770  # 结束端口

SHI_JU = ".lifeos"
WEN_JIA = "bridge/runtime.json"


def cun_zhen(a1: int) -> bool:
    """判断进程是否存活。

    **不要用 `os.kill(pid, 0)`。** Windows 上 CPython 对 sig 既不是
    CTRL_C_EVENT/CTRL_BREAK_EVENT 的值一律走 TerminateProcess(handle, 0)——
    也就是说 `os.kill(pid, 0)` 不是抛异常，而是**静默杀掉那个进程**。
    """
    if a1 <= 0:
        return False
    if sys.platform == "win32":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        shou = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, a1)
        if not shou:
            return False
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(shou, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(shou)
    try:
        os.kill(a1, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 存在但不属于我们
    return True


def sha_si(a1: int) -> None:
    """杀进程树：先子后父。Windows 用 taskkill /T /F。"""
    if not cun_zhen(a1):
        return
    if sys.platform == "win32":
        os.system(f'taskkill /PID {a1} /T /F >nul 2>&1')
    else:
        try:
            os.killpg(os.getpgid(a1), 9)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(a1, 9)
            except OSError:
                pass
    for _ in range(50):
        if not cun_zhen(a1):
            return
        time.sleep(0.1)


def duan_kong(a1: int) -> bool:
    """端口是否空闲。

    **不要设 `SO_REUSEADDR`。** 它在 Windows 上恰恰**允许**另一个 socket
    绑到同一地址，于是「探测端口空闲」永远返回真 ⇒ `zhao_kong` 挑中一个
    已经被占的端口 ⇒ 两个 Bridge 进程绑同一个端口，后者抢占，
    **请求被错误的那个进程应答**（真机实测：`netstat` 显示两个 pid 都在
    8766 上 LISTENING，bob 的请求拿到了 alice 的令牌、401）。

    原注释写的是「Windows 的 SO_REUSEADDR 允许多个 socket 绑同一地址，
    只 bind 不 listen 是测不出端口被占的」——**前半句是对的，后半句的结论错**：
    设了它之后连 `listen` 也测不出来了。bind + listen 仍然需要（不 listen
    时内核不检查冲突），但**前提是不许设那个选项**。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", a1))
            s.listen(1)
            return True
        except OSError:
            return False


def zhao_kong(a1: int) -> int:
    """从起始端口往上找一个空闲的（方案 5.1：依次尝试 8766–8770）。

    `a1` 是**起始端口**，不是固定端口——`--port` 传别的值时从那里起找，
    这样「让开端口」是能做的（`zhen_ben` 原先把 `a2` 丢了，永远从 DK 起找，
    `--port` 是个哑参数）。
    """
    for duan in range(a1, a1 + 5):
        if duan_kong(duan):
            return duan
    raise SystemExit(f"{a1}-{a1 + 4} 都被占用了，先释放端口再启动 Bridge")


def wang_url() -> str:
    """网关出站地址。与 `api/server.py:754` 读**同一个** `LIFEOS_GW_PORT`。

    抽成函数是为了让它可被测：要守的不变式是「两端同源」，而把它写死在
    cfg 字典里就没法在不启动整个 Bridge 的前提下断言。

    原来这个键压根不存在，`tunnel.py:64` 永远走写死的 8771。运营者按 spec
    第 106 行的承诺设了 `LIFEOS_GW_PORT`，服务端换了端口、Bridge 还打 8771
    ⇒ 无限重连且**一声不响**。spec 第 106 行把它与「禁止硬编码 8766」并列为
    同一条铁律。
    """
    return "ws://127.0.0.1:%d/bridge/tunnel" % int(
        os.environ.get("LIFEOS_GW_PORT") or 8771)


def wen_jia_ming(a1: Path) -> Path:
    return a1 / SHI_JU / WEN_JIA


def duan_runtime(a1: Path) -> dict[str, Any]:
    p = wen_jia_ming(a1)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def xie_runtime(a1: Path, a2: dict[str, Any]) -> None:
    """启动初始化：把 Bridge 的权威快照整份写进 runtime.json。

    **原实现是绕过锁的整份 `write_json`，现已删除。** 它是本进程第二个
    runtime 写入口：不过 `XIE_SUO`、不合并盘上已有的键。症状不是立刻可见的
    ——启动初始化与一次配对撞上时，落盘的是「未配对」那一份，用户配对刚做完
    就被退回未配对状态，而日志里什么都没有。

    现在它走 `pipei.gai_quan`：**同一把锁、同一个落盘实现**，只是「不保留
    盘上旧键」这一条语义不同，而那条语义只对启动初始化成立（见 `zao_yun`
    为什么只放 Bridge 权威的键）。合并语义的场合一律用 `pipei.gai`。
    """
    pipei.gai_quan(wen_jia_ming(a1), a2)


def bao_xie(a1: Path, a2: dict[str, Any], a3: list[int] | None, a4: bool) -> None:
    """把 Bridge 进程自己那几个键写回 runtime.json。`a2` 是内存里那份，`a3` 是新子进程 pid 列表。

    **runtime.json 是多写者文件。** 配对（`pipei.pai`）写 deviceId/deviceToken/userId，
    隧道路径（阶段 7）写 tunnelState——这些键的权威在别人手里，不在 `a2` 里。
    整份覆盖会把它们抹成启动时的值：配对成功后只要 Agent spawn 过一次子进程
    （`a3` 非空这条路），或用户正常关了 Bridge（`a4=True` 那条），
    凭据就没了，Bridge 退回未配对。所以先读盘、再叠上 `a2`，`a2` 赢。

    读与写整段在 `pipei.XIE_SUO` 里。**改 `a2` 也在锁内**：`a2` 是 `zhen_ben` 闭包里
    共享的那一份，两个 HTTP 线程各改各的再各写一次，仍然是丢写。
    """
    with pipei.XIE_SUO:
        if a3 is not None:
            a2["pids"] = [{"pid": x} for x in a3]
        a2["cleanExit"] = a4
        pipei.gai(wen_jia_ming(a1), a2)


def zao_yun(a1: dict[str, Any], a2: int, a3: str, a4: str, a5: int,
            a6: str | None, a7: str | None) -> dict[str, Any]:
    """zhen_ben 启动时那份 runtime.json 快照。参数依次是
    (上次盘上的内容, 端口, token, instanceId, streamEpoch, SDK 版本, CLI 版本)。

    **只放 Bridge 进程权威的键。** deviceId/deviceToken/userId 归配对（`pipei.pai`），
    tunnelState 归隧道（阶段 7）——把它们放进来，就等于让启动值每次回写都盖掉对方，
    见 `bao_xie` 的说明。`tests/test_pair_page.py` 有一条 `assertNotIn` 盯着这件事。
    """
    return {
        "schemaVersion": 2,
        "port": a2,
        "token": a3,
        "pid": os.getpid(),
        "pids": [],
        "owner": "lifeos-bridge",
        "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sdkVersion": a6,
        "cliVersion": a7,
        "instanceId": a4,
        "streamEpoch": a5,
        "cleanExit": False,   # 9.4 第二段：异常退出时下次启动要提示上次有未结束的会话
        "orphans": a1.get("pids", []) if a1.get("cleanExit") is False else [],
    }


def zhu_ri(a1: Path) -> logging.Logger:
    """装配轮转日志。10.7 要求「至少要能回答 Bridge 卡住了怎么排查」——
    阶段 1 把访问日志整条禁掉，那满足了「不打 token」，但丢了可观测性。

    **只记请求行，不记请求体。** 请求体里有 toolInput 全文，
    那正是 8.8 防 prompt injection 要保护的输入。
    """
    ri = logging.getLogger("bridge.access")
    ri.setLevel(logging.INFO)
    ri.propagate = False
    p = a1 / SHI_JU / "bridge" / "bridge.log"
    # 幂等判据必须精确到「指向同一个文件的、自己建的那个 handler」。
    # 只看 `ri.handlers` 是否非空是错的：任何宿主进程都可能给这个 logger
    # 挂过自己的 handler（pytest 的 LogCaptureHandler、主服务的日志框架），
    # 那时这里会提前返回，RotatingFileHandler 从未建立，bridge.log 根本
    # 不存在——而症状是「一条日志都没有」，看起来像日志级别配错了。
    mubiao = os.path.abspath(str(p))
    for h in ri.handlers:
        if isinstance(h, RotatingFileHandler) and h.baseFilename == mubiao:
            return ri
    p.parent.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(p, maxBytes=5 * 1024 * 1024, backupCount=3,
                            encoding="utf-8")
    h.setFormatter(logging.Formatter(
        "%(asctime)s %(threadName)s %(levelname)s %(message)s"))
    ri.addHandler(h)
    shou_quan(p)
    return ri


def sao_bing(a1: dict[str, Any]) -> int:
    """第二步：杀 pids[] 里的孤儿，返回清掉的数量。"""
    sha = 0
    for x in a1.get("pids", []) or []:
        pid = x.get("pid") if isinstance(x, dict) else x
        if not isinstance(pid, int):
            continue
        if cun_zhen(pid):
            sha_si(pid)
            sha += 1
    return sha


def hui_fu(a1: Path, hua: HuiHua, cun: Cun, a2: str | None = None) -> dict[str, int]:
    """懒恢复：把落盘的会话、消息灌回内存。**不拉起任何 claude 进程。**

    Bridge 启动不 resume：用户在那个会话里发第一条指令时，
    _pao() → xin_jian() 才会带着 resume=claudeSessionId 起进程。
    提前拉起的话，一次重启就等于替用户点了「继续」。

    `a2` 是运行时 uid，给了就做归属迁移（见下面那段注释），**不给（None）
    一条都不迁**——阶段 5 的既有测试就是靠这个形状保持原行为的，所以它是
    可选形参而不是必填。
    """
    xiang = 0
    qian_yi = 0
    for rec in cun.du_hui():
        try:
            s = AgentSession(**guo_lu1(AgentSession, rec))
        except TypeError:
            continue
        # 归属迁移：把「ownerId 还是 local」的落盘会话改判给 `a2`。
        #
        # 为什么需要：ownerId 字段自阶段 1 就在 models.py，而 to_dict() 是
        # asdict 全字段 ⇒ 阶段 1–5 落盘的会话全部带 ownerId="local"；而
        # runtime.json 的 userId 是阶段 6（a113408）才引入的。于是「先未配对
        # 跑了一段、后来配对」的用户，恢复出来的会话 ownerId 仍是 "local"，
        # 与运行时 uid 不匹配 ⇒ http._dui_hui 对它们一律 404，连 close 都不给，
        # 用户只能干等 1800 秒闲置看门狗。未配对装机不受影响（"local"=="local"）。
        #
        # 判据是 `== "local"` 而不是无条件覆盖：无条件覆盖会把已配对用户
        # （ownerId 已经是 alice 的会话）在换 uid 时误判给新主人，而
        # 「本次提交之前所有落盘会话的 ownerId 都是 local」这条推断才是
        # 迁移成立的全部依据。a2 为 None 时不迁，等于今天的行为。
        #
        # **改判而不是在恢复时过滤**：跨用户 404 是访问时（_dui_hui）判的，
        # 恢复时丢掉别人的会话只会让「表里根本没这条」，那条断言就成了假绿。
        if a2 is not None and s.ownerId == "local":
            s.ownerId = a2
            qian_yi += 1
        # 重启后没有活的 claude 子进程，不能假装它在跑
        s.state = "idle"
        s.alive = False
        s.pendingPermissions = []
        s.pendingQuestions = []
        # **必须重置 updatedAt**：落盘值可能是昨天的，而 8.7 的闲置看门狗
        # 一启动就会判它超时并把会话摘掉——用户重连看到会话凭空消失。
        s.updatedAt = xianzai()
        lie = []
        for m in cun.xiang_qu(s.sessionId):
            try:
                lie.append(AgentMessage(**guo_lu1(AgentMessage, m)))
            except TypeError:
                continue
        xiang += len(lie)
        hua.hui_fu(s, lie)
    # **迁移的那部分回写 sessions.json**：判据是 `== "local"`，所以重迁第二次
    # 一条都不匹配 ⇒ 幂等，回写只有第一次有意义。
    #
    # **不回写的真实代价不是「每次启动重迁一次」**（那无害，迁移只改内存、
    # 每次都从同一份落盘重来）。代价是**换绑会把会话漂给下一个人**：
    # alice 配对期间产生的会话（老 `local` 会话也一并被迁成 alice）在盘上
    # 仍写 `local`，用户换绑到 bob 后，bob 启动时把它们全迁给自己
    # ⇒ alice 的会话出现在 bob 的列表里，跨用户隔离从磁盘这一侧整个漏掉。
    #
    # **只在真的迁了会话时才写**，且放在循环外：Cun.xie_hui 是全量重写
    # （KB 级），一条都不迁时写它纯属白干，而恢复失败不该拖慢启动。
    # **失败不该阻断启动**：xie_hui 内部自己 try/except 降级并记日志，
    # 这里不额外包一层——多包一层只会把「回写失败」这件事藏得更深。
    #
    # **只在真的迁了会话时才写**，且放在循环外：Cun.xie_hui 是全量重写
    # （KB 级），一条都不迁时写它纯属白干，而恢复失败不该拖慢启动。
    # **失败不该阻断启动**：xie_hui 内部自己 try/except 降级并记日志，
    # 这里不额外包一层——多包一层只会把「回写失败」这件事藏得更深。
    if qian_yi:
        cun.xie_hui(hua.kua())
    return {"sessions": len(hua._map), "messages": xiang,
            "decisions": len(cun.jue_qu()), "migrated": qian_yi}


def zhen_ben(a1: Path, a2: int) -> tuple[BridgeServer, dict[str, Any]]:
    """起 Bridge。四步：读运行时文件 → 清孤儿 → 探端口 → 写运行时文件。

    `a2` 是**起始端口**（`--port` 的取值），从它往上找空闲端口。
    **它原先完全没被使用**——`main()` 把它传进来，这一步却写死了 `zhao_kong(DK)`，
    于是 `--port` 是个哑参数，传什么都没用。真机验收第2 步要两个 Bridge 并存
    （验凭据目录隔离），而那唯一的手段就是让开端口 ⇒ 没有它这一步跑不起来。
    """
    # 1. 读
    jiu = duan_runtime(a1)
    # uid 在 `hui_fu` 之前就要算出来：它有三处消费（懒恢复的归属迁移、
    # `fu.env` 的凭据目录、`fu.yong_hu`），三处必须同源——分叉了不会有人报错，
    # 现象是「凭据是 alice 的、归属是 bob 的」，两条护栏各自都绿。
    # 收敛成一个局部变量是从根上消掉分叉，而不是靠三处各写一遍一样的表达式。
    yong = str(jiu.get("userId") or "local")
    # 2. 清孤儿（必须在探端口之前）
    sao = sao_bing(jiu)
    if sao:
        print(f"[bridge] 回收了 {sao} 个残留的 Agent 子进程")
    if jiu.get("pid") and cun_zhen(jiu["pid"]) and jiu["pid"] != os.getpid():
        sha_si(jiu["pid"])  # 上一次 Bridge 还活着，先让位
    # 3. 探端口。**从 `a2` 起**，不是从 DK 起——`--port` 就是为多实例准备的
    duan = zhao_kong(a2 if a2 > 0 else DK)
    # 4. 决定与记录
    token = auth.shengcheng()
    zong = ZongXian(uuid.uuid4().hex[:8], int(jiu.get("streamEpoch", -1)) + 1)
    hua = HuiHua(zong)
    zong.zhan = hua
    ri = zhu_ri(a1)
    # 凭据隔离的告警必须跟着 `bridge.access` 的 handler 落盘（承重 3）。
    # **紧跟 zhu_ri()**：handler 是它装的，顺序反了就没有可挂的地方。
    # 不挂的后果很隐蔽——Bridge 是被 `bridge_admin.qidong` 用
    # `stdout/stderr=DEVNULL` 拉起来的（DETACHED_PROCESS），
    # 「这个 uid 落到空凭据库、要重新登录」的唯一告警会直接进 DEVNULL，
    # 谁都看不见，用户看到的只是「怎么又要登录一次」。
    pingju.jie_shang()
    cun = Cun(a1 / SHI_JU / "bridge", logging.getLogger("bridge.cun"))
    hua.cun = cun
    # 懒恢复。必须在 BridgeServer 起看门狗之前灌完，且 sessions 的
    # updatedAt 已被重置，否则恢复出来的会话会被闲置超时立刻关掉。
    hui = hui_fu(a1, hua, cun, yong)
    if hui["sessions"]:
        print(f"[bridge] 恢复了 {hui['sessions']} 个会话、{hui['messages']} 条消息、"
              f"{hui['decisions']} 条审批决定（不自动拉起 Agent，等你发指令）", flush=True)
    cli = _ban_ben("claude-code")
    sdk = _ban_ben("claude-agent-sdk")
    fu = BridgeServer(("127.0.0.1", duan), zong, hua, ShenKa(), token, cun)
    BridgeHandler.ri = ri
    fu.cli_ban_ben = cli                       # 3.9 版本门禁
    fu.sdk_ban_ben = sdk
    fu.gen = a1                  # 项目根。配对页定位 runtime.json 用的是 yun_wen，这个留给阶段 7
    fu.yun_wen = wen_jia_ming(a1)
    # 凭据隔离（spec 11.2）。**在构造任何适配器之前算好**——`xin_jian()`
    # 是唯一调 `kaishi()` 的地方，它只认 `self.env`。
    #
    # uid 来自 runtime.json 的 `userId`（`pipei.pai` 配对成功时写的）。**没配对
    # 时是 "local"**：未配对的 Bridge 也要能用，这是单人开发的默认形态。
    # 配对后 uid 变了要重启 Bridge 才生效——这不是缺陷：跑着的会话本来就
    # 已经按旧 uid 开了凭据目录，中途换目录等于让同一个会话的登录态凭空消失。
    #
    # 隔离**默认关**（改动三，2026-10-10）：`env=None` 时 SDK 逐字继承本进程的
    # os.environ，凭据走 `~/.claude`，harness 与用户自己开的终端同形。
    # `huan_jing` 也整个不调——隔离开着时才建每用户目录，关着时一个字节
    # 都不该落在 `~/.lifeos-bridge/users/` 下。`LIFEOS_GELI=1` 才回到旧形态。
    fu.env = pingju.huan_jing(yong) if pingju.gel() else None
    # uid 原样留一份给 `/agents` 现场重试凭据目录（阶段 6 必修 3）。
    # 必须与上面**同一个** uid：那里拿不到 runtime.json，只能用注入的值。
    fu.yong_hu = yong
    lu_dao = LuDao(jiu.get("mainServiceUrl"))  # 3.8 决策回路出站
    fu.lu_dao = lu_dao
    # ShenQing 也要发展示旁路（permission.resolved），与 HuiHua.cun 同一套路：
    # 构造之后再赋值，避免把出站通道塞进它的构造参数。
    fu.shen_qing.lu_dao = lu_dao

    yun = zao_yun(jiu, duan, token, zong.ji, zong.shui, sdk, cli)

    def bao(a2: list[int] | None = None, a3: bool = False) -> None:
        bao_xie(a1, yun, a2, a3)

    fu.ji_pids = lambda a2: bao(a2)   # 每次 spawn 子进程都落盘，Bridge 被强杀也回收得掉
    bao([], False)
    fu.guan_biao_hou = lambda: bao(None, True)
    # 7.7.2 展示旁路：Bridge 启动完成
    lu_dao.lian_jie({"instanceId": zong.ji, "port": duan,
                     "cliVersion": cli, "sdkVersion": sdk})
    # 进入方式。默认 local（与阶段 1–5 完全一致）；tunnel 由任务 7 注册。
    jie_ming = os.environ.get("LIFEOS_JIAOJIE", "local")
    if jie_ming == "tunnel":
        # 导入即注册进 jiaojie.ZHU_CE。**只在真的要隧道时导入**：local 路径
        # 不该因为多一个模块（websockets）而起不来。
        from lifeos.bridge import tunnel  # noqa: F401
    jie = jiaojie.xuan(jie_ming, fu, {
        "deviceToken": jiu.get("deviceToken", ""),
        "instanceId": zong.ji, "port": duan, "token": token,
        "zong": zong, "root": a1,
        # SSE 连接数的来源（spec 10.1、7.2.5）。**与上面算凭据目录用的是同一个
        # 值**（同一个局部变量），别写成独立的读取：cfg 里少了这个键，
        # `_da` 就会永远发 `local`，「每 userId 8 条」在公网形态下形同虚设，
        # 而那条限制看起来还在。
        "userId": yong,
        # 隧道状态要落回 runtime.json（`bridge_admin.xinxi()` 读的就是它），
        # 而落盘路径在这里已经算好了，直接给它，别让 tunnel.py 凭 root 猜。
        "yun_wen": fu.yun_wen, "cliVersion": cli,
        # 隧道客户端要打哪儿。**必须由 wang_url() 算，不能在内联写默认值**：
        # 与主服务的监听端口同源，见那个函数的说明。
        "url": wang_url(),
    })
    fu.jiao_jie = jie
    jie.qi_dong()
    return fu, {"port": duan, "token": token}


def _ban_ben(a1: str) -> str | None:
    """读版本号。先查 python 包元数据，再退回执行 CLI。"""
    import importlib.metadata as md

    try:
        return md.version(a1)
    except md.PackageNotFoundError:
        pass
    if a1 == "claude-code":
        import re
        import subprocess

        try:
            out = subprocess.run(
                ["claude", "--version"], capture_output=True, text=True, timeout=10,
                # Bridge 无控制台（DETACHED_PROCESS 拉起），不补此标志就闪窗。
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        m = re.search(r"(\d+\.\d+\.\d+)", out)
        return m.group(1) if m else None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(prog="lifeos.bridge.run")
    parser.add_argument("--root", default=".", help="项目根目录，用于定位 .lifeos")
    parser.add_argument("--port", type=int, default=DK)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    fu, xin = zhen_ben(root, args.port)
    print(f"[bridge] 监听 http://127.0.0.1:{xin['port']}  pid={os.getpid()}", flush=True)
    try:
        fu.serve_forever()
    except KeyboardInterrupt:
        print("\n[bridge] 收到中断，正在关闭")
    finally:
        # 9.4 两段式关闭的第一段：先收干净（挂起项、会话、子进程），
        # 再释放端口。顺序反了会留下一个带用户全部权限的孤儿 claude。
        try:
            fu.guan_biao()
        except Exception as e:  # noqa: BLE001
            print(f"[bridge] 关闭时出错：{e}")
        fu.guan_biao_hou()
        # 7.7.2 展示旁路：Bridge 正在关闭。关闭路径上不能再抛异常，
        # 取不到 lu_dao 就跳过。
        _lu = getattr(fu, "lu_dao", None)
        if _lu is not None:
            try:
                _lu.duan_kai({"reason": "两段式关闭",
                              "uptimeSec": round(time.monotonic() - fu.kaishi_shi, 1)})
            except Exception:  # noqa: BLE001
                pass
        fu.shutdown()
        fu.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
