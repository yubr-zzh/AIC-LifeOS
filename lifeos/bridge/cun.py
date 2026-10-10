"""阶段 5 的落盘层（方案 5.1、5.2、5.5、10.7）。

三类文件，一个 owner：

| 文件 | 形态 | 写入方式 |
|---|---|---|
| sessions.json | JSON 数组 | 原子全量重写 |
| decisions.jsonl | JSON Lines | 追加一行 |
| messages/<sid>.jsonl | JSON Lines | 追加一行 |

三条硬规则，动之前先读懂：

1. **读失败绝不让 Bridge 起不来。** 文件不存在、JSON 坏掉、某一行坏掉，
   一律按空 / 跳过该行处理，并写日志说清丢了什么。
2. **写必须原子。** sessions.json 走 storage/atomic.write_json()（它已处理
   Windows 上索引器短暂锁住文件的重试）。jsonl 是追加模式下的单行 write，
   在 Windows 与 POSIX 上对小于管道缓冲的短行都是原子的，够用。
3. **每个写操作持自己的 RLock。** 与 HuiHua 的锁粒度一致，不引入更粗的全局锁。
"""

from __future__ import annotations

import json
import locale
import logging
import os
import re
import subprocess
import threading
from pathlib import Path

from lifeos.storage.atomic import write_json

# 4.5：决定记录条数告警阈值。超了只告警，**绝不自动删**——
# 这一层是 R3 的安全冗余，删一条就等于对某个已批准操作失去重放保护。
JUE_JING = 10_000

# 4.4：text 读取时只保留最近这么多条（10.7 的上限）。
# 只发生在读取时：追加路径上做裁剪会让「截断」与「损坏」无法区分。
WEN_ZUI = 200

# sid 直接拼进 messages/<sid>.jsonl 的路径。它来自 URL 与落盘文件，不是可信输入。
HE_FA = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def shou_quan(a1: Path) -> None:
    """把文件权限收紧到当前用户。失败只告警，不阻断。"""
    try:
        if os.name == "posix":
            a1.chmod(0o600)
            return
        # Windows：用 icacls 断继承 + 只给当前用户读写。
        # 没有走 ctypes 调 SetNamedSecurityInfoW——那要自己取 token 里的 SID
        # 再拼 EXPLICIT_ACCESS，约五十行难以在本机验证的 ctypes；icacls 是
        # Windows 自带的同一操作，一行说完，失败还能看到原因。
        user = os.environ.get("USERNAME") or ""
        if not user:
            return
        # 权限串是 `用户名:M`，**不是 `用户名:(M)`**。后者在本机返回 87（参数无效），
        # 而这里的设计是「失败只告警」——症状是权限从来没被收紧过，
        # 而日志里除了一行 warning 什么都看不出来。
        #
        # **必须是 M（修改），不能只给 RW。** icacls 的 M 含文件自身的 DELETE；
        # 只给 RW 时 os.replace 覆盖这个文件会 WinError 5，而 write_json 走的正是
        # 「写临时文件 + 改名覆盖」。生产目录 .lifeos/bridge 的 ACL 是 user:M
        # （Modify **不含** FILE_DELETE_CHILD，那一位只有 F 才有），
        # 所以子文件删不掉时没有退路：runtime.json 每次启动都要重写，
        # Bridge 第二次启动就再也起不来（PermissionError 直接抛穿）；
        # sessions.json 走同一条路，被这里上层的 except OSError 吞掉，
        # 变成「会话落盘静默失效」——一个崩溃，一个不吭声，根因是同一个。
        r = subprocess.run(
            ["icacls", str(a1), "/inheritance:r", "/grant:r", f"{user}:M"],
            capture_output=True, timeout=10, check=False,
            # Bridge 无控制台（DETACHED_PROCESS 拉起），不补此标志就闪窗。
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if r.returncode != 0:
            # icacls 在中文 Windows 上输出 GBK，按 UTF-8 解出来是乱码；
            # 而这条告警的全部价值就是让人看懂为什么没收紧。
            yin = locale.getpreferredencoding(False)
            logging.getLogger("bridge.cun").warning(
                "没能收紧 %s 的权限：%s", a1.name,
                r.stderr.decode(yin, "replace").strip()[:120])
    except (OSError, subprocess.SubprocessError) as e:
        logging.getLogger("bridge.cun").warning("收紧 %s 的权限失败：%s", a1, e)


class Cun:
    """Bridge 的持久化 owner。线程安全；所有异常对内降级、对外记日志。"""

    def __init__(self, a1: Path, a2: logging.Logger | None = None) -> None:
        self.gen = Path(a1)
        self.ri = a2 or logging.getLogger("bridge.cun")
        self.suo = threading.RLock()
        self.hui_wen = self.gen / "sessions.json"
        self.jue_wen = self.gen / "decisions.jsonl"
        self.xiang_jia = self.gen / "messages"
        self.jue_zong = -1  # -1 = 还没数过，第一次追加时惰性数一次
        # 已经收紧过权限的文件。icacls 是一个子进程，每次追加都调一次是不可接受的：
        # 一份一万行的 decisions.jsonl 会拉起一万个进程。
        self._yi: set[Path] = set()

    def _shou(self, a1: Path) -> None:
        """每个文件每个进程只收紧一次权限。失败由 shou_quan 自己告警。"""
        if a1 in self._yi:
            return
        self._yi.add(a1)
        shou_quan(a1)

    # ---- 会话元数据 ----
    def xie_hui(self, a1: list[dict]) -> None:
        """全量重写 sessions.json。KB 级，比「数组合并删除」便宜，且天然原子。

        持锁是必要的：两个线程同时写会各自读到「当时」的状态，
        先写的那个反而可能后落盘，把新的覆盖成旧的。文件本身不会坏
        （write_json 用的是 uuid 临时名 + os.replace），坏的是内容。
        """
        with self.suo:
            try:
                self.gen.mkdir(parents=True, exist_ok=True)
                write_json(self.hui_wen, a1)
                self._shou(self.hui_wen)
            except OSError as e:
                self.ri.warning("sessions.json 写入失败：%s", e)

    def du_hui(self) -> list[dict]:
        try:
            shu = json.loads(self.hui_wen.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            self.ri.warning("sessions.json 读不了，按空处理（会话历史丢失）：%s", e)
            return []
        if not isinstance(shu, list):
            self.ri.warning("sessions.json 不是数组，按空处理")
            return []
        return [x for x in shu if isinstance(x, dict)]

    # ---- 审批决定 ----
    def jue_cun(self, a1: dict) -> None:
        with self.suo:
            try:
                self.gen.mkdir(parents=True, exist_ok=True)
                if self.jue_zong < 0:   # 惰性数一次。放在写之前，写在之后会多算一条
                    self.jue_zong = len(self._du_hang(self.jue_wen))
                with self.jue_wen.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(a1, ensure_ascii=False, default=str) + "\n")
                self._shou(self.jue_wen)
            except OSError as e:
                self.ri.warning("decisions.jsonl 追加失败（这条决定将无法重放）：%s", e)
                return
            self.jue_zong += 1
            if self.jue_zong > JUE_JING:
                # 文案里把阈值一并说出来：只说「已有 10001 条」，看日志的人
                # 得回去翻代码才知道多少算多。
                self.ri.warning(
                    "decisions.jsonl 已有 %d 条（告警阈值 %d），请人工归档；本层不自动删除",
                    self.jue_zong, JUE_JING)

    def jue_qu(self, a1: str | None = None, a2: str | None = None) -> list[dict]:
        """查历史决定。两个参数都给 None = 全量。"""
        return [x for x in self._du_hang(self.jue_wen)
                if (a1 is None or x.get("sessionId") == a1)
                and (a2 is None or x.get("requestId") == a2)]

    # ---- 消息 ----
    def xiang_cun(self, a1: dict) -> None:
        sid = str(a1.get("sessionId") or "")
        if not HE_FA.match(sid):
            self.ri.warning("会话 id 不合法，拒绝落盘这条消息：%r", sid[:40])
            return
        with self.suo:
            try:
                self.xiang_jia.mkdir(parents=True, exist_ok=True)
                p = self.xiang_jia / f"{sid}.jsonl"
                with p.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(a1, ensure_ascii=False, default=str) + "\n")
                self._shou(p)
            except OSError as e:
                self.ri.warning("%s 的消息追加失败：%s", sid, e)

    def xiang_qu(self, a1: str, a2: int = WEN_ZUI) -> list[dict]:
        if not HE_FA.match(a1 or ""):
            return []
        return self._zhui_wen(self._du_hang(self.xiang_jia / f"{a1}.jsonl"), a2)

    def _zhui_wen(self, a1: list[dict], a2: int) -> list[dict]:
        """text 只留最近 a2 条。其他 kind 一条不裁。"""
        wei = [i for i, x in enumerate(a1) if x.get("kind") == "text"]
        if len(wei) <= a2:
            return a1
        shan = set(wei[: len(wei) - a2])
        self.ri.info("消息历史里的 text 超了 %d 条，读取时裁掉最早的 %d 条",
                     a2, len(shan))
        return [x for i, x in enumerate(a1) if i not in shan]

    # ---- 读取的公共降级 ----
    def _du_hang(self, a1: Path) -> list[dict]:
        try:
            wen = a1.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except (OSError, UnicodeDecodeError) as e:
            self.ri.warning("%s 读不了，按空处理：%s", a1.name, e)
            return []
        out: list[dict] = []
        huai = 0
        for hang in wen.splitlines():
            hang = hang.strip()
            if not hang:
                continue
            try:
                ji = json.loads(hang)
            except json.JSONDecodeError:
                huai += 1
                continue
            if isinstance(ji, dict):
                out.append(ji)
        if huai:
            self.ri.warning("%s 有 %d 行解析不了，已跳过（这些数据丢了）", a1.name, huai)
        return out
