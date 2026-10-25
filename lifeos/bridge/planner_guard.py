"""三道不可绕过的闸门（方案 8.3）。

闸门 1：permissionMode 白名单 —— 非法值 400 拒绝，绝不静默降级。
闸门 2：Bridge 强制持有的 deny 基线 —— 任何请求参数都覆盖不了。
闸门 3：cwd 白名单 —— realpath + normcase 后必须落在信任根内。

三者都在 Bridge 边界，不在适配器里。适配器拿到的一定是已经过闸门的值。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from lifeos.bridge.models import MOSHI
from lifeos.gen import gen_mulu


class JuDuan(Exception):
    """闸门拒绝。code 直接进 HTTP 响应体。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# 闸门 2 的 deny 基线。方向与 v1.0 相反：allow 由 SDK 与用户规则决定，
# deny 由 Bridge 强制持有——这是唯一在所有模式下都绕不过去的机制。
JUE = {
    "format", "diskpart", "shutdown", "halt", "poweroff",
    "mkfs", "fdisk", "dd",
}
# 这些是「命令首词」黑名单里需要额外带参数才危险的，单独判断。
WEIXIAN = {"reg": {"delete"}, "bcdedit": {"delete"}, "cipher": {"w"}, "takeown": set()}

# 凭据目录：整个目录禁读写，而不是只禁其中某个文件。
MIMI = [".ssh", ".aws", ".gnupg", ".kube", ".docker"]
MIMI_WEN = [".credentials.json", ".claude.json", "id_rsa", "id_ed25519"]


class ShenKa:
    """三道闸门。信任根可通过 mizhu 传入，默认是 LifeOS 项目根 + 用户主目录。

    默认根可被环境变量 `LIFEOS_XINREN_GEN` 覆盖（分号分隔多个根）；再叠加
    `trust.json` 里用户在网页上点过「信任此目录」确认的目录（改动二，2026-10-10）。
    """

    def __init__(self, a1: list[str] | None = None) -> None:
        self.gen = Path(__file__).resolve().parent.parent.parent
        self.roots = [self._zhunxi(p) for p in (a1 if a1 else self._moren())]

    def _moren(self) -> list[str]:
        """默认信任根：项目根 + 用户主目录，可被 LIFEOS_XINREN_GEN 覆盖。

        **覆盖是整体替换，不是追加**——设了这个变量还想要原有两个根，就把它
        们一起写进变量里。trust.json 的追加根永远生效（用户确认过的选择，
        不该被环境变量悄悄抹掉）。
        """
        huan = (os.environ.get("LIFEOS_XINREN_GEN") or "").strip()
        if huan:
            gen = [x.strip() for x in huan.split(";") if x.strip()]
        else:
            gen = [str(self.gen), str(Path.home())]
        return gen + self._xie_ding()

    @property
    def xinren_wen(self) -> Path:
        """用户确认过的额外信任根落在当前 LifeOS 数据根下。"""
        return gen_mulu() / "bridge" / "trust.json"

    def _xie_ding(self) -> list[str]:
        """读 trust.json 的追加根。读失败按空处理——与 cun 同一条纪律：
        这个文件坏了不能让 Bridge 起不来，代价只是用户重新确认一次。"""
        try:
            shu = json.loads(self.xinren_wen.read_text(encoding="utf-8"))
            gen = shu.get("roots") if isinstance(shu, dict) else None
            if isinstance(gen, list):
                return [str(p) for p in gen if isinstance(p, str) and p.strip()]
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return []

    def jia_xinren(self, a1: str) -> str:
        """把一个目录追加为信任根（`/trust-folder` 端点背后）。

        热更新 `self.roots`（Handler 与 Server 共享同一个实例），再原子写盘，
        下次启动由 `_moren()` 灌回来。返回规范化后的路径。
        """
        lu = self._zhunxi(a1)
        if not os.path.isdir(lu):
            raise JuDuan("cwd_forbidden", f"目录不存在：{lu}")
        if lu in self.roots:
            return lu
        self.roots.append(lu)
        xian = self._xie_ding()
        if lu not in (self._zhunxi(p) for p in xian):
            xian.append(lu)
        self.xinren_wen.parent.mkdir(parents=True, exist_ok=True)
        from lifeos.storage.atomic import write_json
        write_json(self.xinren_wen, {"roots": xian})
        return lu

    @staticmethod
    def _zhunxi(a1: str) -> str:
        """realpath + normcase 后再比较，否则 .. 与大小写在 Windows 上能绕过白名单。"""
        return os.path.normcase(os.path.realpath(str(a1)))

    # ---- 闸门 1 ----
    @staticmethod
    def fang(a1: str | None, a2: Any = None) -> str:
        """校验 permissionMode。非法 → 400 mode_forbidden。

        绝不降级成 manual：降级会让用户以为开了宽松模式而实际没有（或反过来），
        两种误解都会导致用户对风险做出错误判断。
        """
        supported = getattr(a2, "MOSHI_ZI", frozenset()) if a2 is not None else frozenset()
        if a1 is None:
            a1 = "manual"
        elif a1 not in MOSHI:
            raise JuDuan(
                "mode_forbidden",
                f"permissionMode={a1!r} 不被允许，可用值：{sorted(MOSHI)}",
            )
        if supported and a1 not in supported:
            raise JuDuan(
                "mode_forbidden",
                f"Agent {getattr(a2, 'agentId', '?')!r} 不支持 permissionMode={a1!r}，"
                f"它支持：{sorted(supported)}",
            )
        return a1

    # ---- 闸门 3 ----
    def han(self, a1: str) -> bool:
        """目录是否已在信任根内（不抛异常，`/pick-folder` 用它出 `inTrustRoot`）。"""
        try:
            lu = self._zhunxi(a1)
        except (OSError, ValueError):
            return False
        return any(lu == g or lu.startswith(g + os.sep) for g in self.roots)

    def cwd(self, a1: str) -> str:
        """校验工作目录。越界 → 400 cwd_forbidden。返回规范化后的绝对路径。"""
        if not a1 or not str(a1).strip():
            raise JuDuan("cwd_forbidden", "cwd 不能为空")
        try:
            lu = self._zhunxi(a1)
        except (OSError, ValueError) as e:
            raise JuDuan("cwd_forbidden", f"cwd 无法解析：{e}") from e
        if not os.path.isdir(lu):
            raise JuDuan("cwd_forbidden", f"目录不存在：{lu}")
        for gen in self.roots:
            if lu == gen or lu.startswith(gen + os.sep):
                return lu
        raise JuDuan("cwd_forbidden", f"{lu} 不在信任根内：{self.roots}")

    # ---- 闸门 2 ----
    def shibai(self, a1: str, a2: dict, a3: str) -> str | None:
        """检查一次工具调用是否命中 deny 基线。返回拒绝原因，通过则返回 None。

        任何请求参数都覆盖不了这个结果——包括 permissionMode。
        """
        if a1 in ("Write", "Edit", "NotebookEdit", "MultiEdit"):
            for k in ("file_path", "path", "notebook_path"):
                v = a2.get(k)
                if isinstance(v, str) and v.strip():
                    r = self._wenjian(v, a3)
                    if r:
                        return r
            return None
        if a1 in ("Read", "Glob", "Grep"):
            for k in ("path", "file_path"):
                v = a2.get(k)
                if isinstance(v, str) and v.strip():
                    r = self._wenjian(v, a3, xie=False)
                    if r:
                        return r
            return None
        if a1 in ("Bash", "PowerShell"):
            return self._shell(str(a2.get("command") or a2.get("script") or ""))
        return None

    def _wenjian(self, a1: str, a2: str, xie: bool = True) -> str | None:
        """检查单个文件路径是否触碰凭据目录或越出 cwd。"""
        lu = self._zhunxi(a1)
        for gen in self.roots:
            if lu == gen or lu.startswith(gen + os.sep):
                break
        else:
            # 允许写 cwd 及其子目录；cwd 本身由闸门 3 保证在信任根内
            gen = self._zhunxi(a2)
            if lu != gen and not lu.startswith(gen + os.sep):
                return f"{xie and '写' or '读'} cwd 之外的绝对路径被拒绝：{lu}"
        for m in MIMI:
            if f"{os.sep}{m}" in lu or lu.endswith(m):
                return f"凭据目录被拒绝：{m}"
        for w in MIMI_WEN:
            if lu.endswith(w):
                return f"凭据文件被拒绝：{w}"
        return None

    @staticmethod
    def _shell(a1: str) -> str | None:
        """检查 shell 命令。按分隔符切段后只看每段首词，避免 `echo format` 这类误报。"""
        if not a1.strip():
            return None
        for duan in re.split(r"[;&|]|\n|&&|\|\|", a1):
            ci = duan.strip().strip('"\'`')
            if not ci:
                continue
            # 跳过前导的 env 赋值与 cd 之类
            while True:
                parts = ci.split()
                if len(parts) >= 2 and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", parts[0]):
                    parts = parts[1:]
                    continue
                break
            if not parts:
                continue
            shou = os.path.basename(parts[0]).lower()
            if shou in JUE:
                return f"危险命令被拒绝：{shou}"
            if shou in WEIXIAN and (WEIXIAN[shou] & {p.lower() for p in parts[1:]}):
                return f"危险命令被拒绝：{shou}"
            if shou == "chmod" and "777" in parts[1:]:
                return "chmod 777 被拒绝"
            if shou == "chown" and ("-R" in parts[1:] or "--recursive" in parts[1:]):
                return "递归 chown 被拒绝"
        for m in MIMI:
            if m in a1:
                return f"命令触碰凭据目录被拒绝：{m}"
        for w in MIMI_WEN:
            if w in a1:
                return f"命令触碰凭据文件被拒绝：{w}"
        return None
