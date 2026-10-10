"""凭据隔离（spec 11.2、方案 15.5）。

`~/.claude/credentials.json` 与 `settings.json` 是**每个操作系统用户一份**。
多人共用一台机器时所有人共用一份凭据——而**任何一个人点一次「总是允许」
会永久扩大全局白名单**（8.2.3 为此设限，但凭据共用时那条还不够：
白名单本身就写在这份共用的 settings 里，撤不回来）。

所以每个 LifeOS 用户一个 `CLAUDE_CONFIG_DIR`。

**目录建不出来时只告警，不让 Bridge 起不来**：11.2 明确点了这条。
但要注意「建不出来」和「收紧失败」是**两回事**，别混成一句「退回共用凭据」：
- 建不出来 → 路径返回一个**建不出来的目录**，CLI 会自己把它建出来，
  于是用户落到一个**空的**凭据库，要重新登录。**不是共用凭据。**
- 收紧失败 → 目录是好的，只是 ACL 没收紧（别人可能读得到），
  凭据仍然隔离，只是没锁死。

⚠️ **Windows 上隔离的不是主凭据本身**（阶段 6 修复轮 2，承重 5）：
Claude Code CLI 在 Windows 上把 OAuth 凭据放在 **Windows 凭据管理器**里，
`CLAUDE_CONFIG_DIR` 只承载 `settings.json` / 项目记录 / 权限白名单。
所以本模块在 Windows 上分的是「**白名单 + 项目记录**」，**不是登录态**——
11.2 引用的 15.5 风险（点一次「总是允许」永久扩大白名单）确实被挡住了，
但「各自登录各自的 Claude 账号」这个更直观的预期在 Windows 上不成立。
POSIX 上凭据本来就在 `~/.claude` 下，那才是完整的隔离。
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
from pathlib import Path

from lifeos.api.dangqian import he_fa

PINGJU_GEN = Path.home() / ".lifeos-bridge" / "users"

# POSIX 目录权限。spec 11.2 定 700：**这个目录里是凭据**，组与其他用户
# 一位都不能进。文件是 600（`cun.shou_quan`），目录没有 600 可选。
JIAO_SE = 0o700

# Windows 上 icacls 的超时。收紧失败要尽快放弃——它在这里只影响凭据目录，
# 不能因为一个卡住的 icacls 把 Bridge 启动拖住（同 11.2 的「只告警」）。
SHI_XIAN = 10

# sha256 取前 16 位（64 bit）。碰撞概率 ~2^-32，uid 是人给的名字不是随机数，
# 这个量级足够——真撞了也只是两个用户共用一个**空**目录，不是跨用户读凭据。
# 与 clawd 的 `digestCodexTurnId` 同一个取值。
HAO_CHANG = 16

# 告警用的 logger。**必须是 `bridge.pingju` 而不是 root**：`run.py` 只给
# `bridge.access` 装 RotatingFileHandler，root logger 全程没有 handler，
# 而 Bridge 是被 `bridge_admin.qidong` 用 `stdout/stderr=DEVNULL` 拉起来的
# （DETACHED_PROCESS）——挂在 root 上就等于把这条唯一的告警丢进 DEVNULL。
# `jie_shang` 让它跟着 `bridge.access` 走，`zhu_ri()` 装完 handler 之后
# 自动就有地方落了（阶段 6 修复轮 2，承重 3）。
_LOG = logging.getLogger("bridge.pingju")

# 这次启动的凭据目录建出来了吗。`/agents` 据此回 `credentialsReady`（11.2 明文）。
# **默认 True**：没跑过 `huan_jing` 时（单测直接 new BridgeServer）不该报故障。
JIAN_BING_CHENG_GONG = True


def jie_shang() -> None:
    """把 `bridge.pingju` 挂到 `bridge.access` 的 handler 上。

    幂等判据精确到「handler 是同一个」：只看 `handlers` 非空是错的——
    pytest 的 `LogCaptureHandler`、主服务的日志框架都可能先挂过。
    """
    _LOG.setLevel(logging.INFO)
    for h in logging.getLogger("bridge.access").handlers:
        if h not in _LOG.handlers:
            _LOG.addHandler(h)


def mu_lu_ming(a1: str) -> str:
    """uid → 目录名。**目录名不再等于 uid**（阶段 6 修复轮 2，承重 1）。

    白名单只挡得住**字符集**，挡不住 **Windows 的路径语义**，而那才是真正
    把两个合法 uid 折叠到同一个目录的东西（控制器已真机复现）：

    | uid 形态      | Windows 的行为                          | 后果                     |
    |---------------|-----------------------------------------|--------------------------|
    | 末尾的点被剥  | `alice` / `alice.` / `alice..` 同一目录 | 目录建了、文件写不进去  |
    | 大小写不敏感  | `alice` 与 `Alice` 同一目录              | A 读得到 B 的 credentials |

    **两条都不是 `he_fa` 能挡的**——`alice.` 与 `Alice` 都是完全合法的 uid。
    唯一的修法是让目录名**不再等于 uid**：加一个从 uid 派生的哈希后缀，
    同一 uid 永远得到同一目录，不同 uid 一定不同目录（sha256 前 64 bit）。
    思路与 clawd 的 `digestCodexTurnId` / `buildDisplaySessionTag` 相同：
    原始 id 只在内存里用，进文件系统的一律是它的哈希。

    **可读前缀保留**（`alice-2bd806c97f0e00af`）：排障时一眼看出这是谁的目录。
    但前缀只是**装饰**——它由 uid 直接拼出，所以大小写与末尾点的问题依然存在，
    真正保证单射的是后半段哈希。因此前缀一律转小写，
    且哈希之前**已经**过了 `he_fa`，字符集是 `[A-Za-z0-9_.-]`，不引入新字符。
    """
    return f"{a1.lower()}-{hashlib.sha256(a1.encode('utf-8')).hexdigest()[:HAO_CHANG]}"


def huan_jing(a1: str) -> dict[str, str]:
    """userId → 传给 SDK 的环境变量增量。目录不存在就建；失败只告警。

    `a1` 是 userId。**先过 `he_fa` 白名单再拼路径**：uid 会成为目录名的一部分，
    而接入登录后它来自 cookie（那时是外部输入）。`../` 能让凭据目录落到
    预期之外的位置——风险 8。`he_fa` 抛 `YongHuFeiFa`，让调用方决定怎么办，
    本函数不吞：uid 非法不是「降级」场景，是配置/输入错了。

    目录名走 `mu_lu_ming`（带哈希），那是承重 1 的单射保证。哈希之后 uid
    已经是「内存里的一个字符串」，不再参与路径语义。
    """
    global JIAN_BING_CHENG_GONG
    uid = he_fa(a1)
    p = PINGJU_GEN / mu_lu_ming(uid)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except (OSError, subprocess.SubprocessError) as e:
        JIAN_BING_CHENG_GONG = False
        _LOG.warning(
            "凭据目录 %s 没能建出来：%s。这个 uid 会落到一个**空的**凭据库"
            "——用户需要重新登录一次。8.2.3 的限制仍然生效。",
            p, e)
    else:
        JIAN_BING_CHENG_GONG = True
        # 收紧**必须**在 mkdir 的 try 之外（阶段 6 必修 1）。放进去的话 POSIX 的
        # `chmod` 抛 `OSError` 会被同一个 except 吃掉，把「目录是好的、只是没锁死」
        # 误标成「建不出来」——`/agents` 于是回 `credentialsReady: false`，前端弹出
        # 「凭据目录建不出来，你需要重新登录一次…请检查磁盘空间」，三处全假：
        # 目录建出来了、不用重新登录、chmod 失败通常是文件系统不支持 POSIX 权限
        # （NTFS-3g / FAT32 / 容器 volume / WSL 的 /mnt/c），与磁盘空间无关。
        # 空库只可能由 mkdir 失败引起，所以收紧失败时这个标志必须仍是 True。
        try:
            _shou_quan(p)
        except (OSError, subprocess.SubprocessError) as e:
            # 这里**必须吞掉**：收紧失败不该让 Bridge 起不来（11.2）。Windows
            # 分支自己已经只告警不抛了，POSIX 原来靠外层那个 except 兜——
            # 现在自己兜住，两条平台行为一致。
            _LOG.warning(
                "没能收紧凭据目录 %s 的权限：%s（目录是好的、凭据仍隔离，只是没锁死）",
                p.name, e)
    return {"CLAUDE_CONFIG_DIR": str(p)}


def _shou_quan(a1: Path) -> None:
    """把目录权限收紧到只有本人。

    **给 `M` 不给 `RW`**——与 `cun.shou_quan`、`devices._xie` 同一个理由：
    icacls 的 M 含文件自身的 DELETE 位，只给 RW 时覆盖/删除会 WinError 5。
    这里的目标是目录，比文件多一个 `(OI)(CI)`：**继承标志，缺了它
    Claude Code 自己写进去的 credentials.json 就是宽松权限，收紧等于白做。**
    icacls 返回非 0 时**只告警不抛**：本函数只影响权限，抛出去会让整个
    Bridge 起不来，而症状是静默失效（见 11.2「不让 Bridge 起不来」）。
    与 `cun.shou_quan` 同一条策略。

    **失败的后果与「建不出来」不同**：目录是好的、凭据仍然隔离，只是没锁死。
    文案刻意分开——混成「退回共用凭据」会把排障带偏。
    """
    if os.name == "posix":
        a1.chmod(JIAO_SE)
        return
    user = os.environ.get("USERNAME") or ""
    if not user:
        # 身份不明时**不发 icacls**：用空用户名去改 ACL 会把目录锁死。
        # 静默跳过（与 `cun.shou_quan` 同款判断）。这条不能算「收紧失败」——
        # 根本没试过，与 icacls 返回非 0 不是一回事。
        return
    r = subprocess.run(
        ["icacls", str(a1), "/inheritance:r", "/grant:r", f"{user}:(OI)(CI)M"],
        capture_output=True, timeout=SHI_XIAN, check=False,
        # Bridge 无控制台（DETACHED_PROCESS 拉起），不补此标志就闪窗。
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        # icacls 在中文 Windows 上输出 GBK，按 UTF-8 解出来是乱码；
        # 而这条告警的全部价值就是让人看懂为什么没收紧。
        import locale
        _LOG.warning(
            "没能收紧凭据目录 %s 的权限：%s（凭据仍隔离，只是没锁死）", a1.name,
            r.stderr.decode(locale.getpreferredencoding(False), "replace").strip()[:120])
