"""三道不可绕过的闸门（方案 8.3）。

闸门 1：permissionMode 白名单 —— 非法值 400 拒绝，绝不静默降级。
闸门 2：Bridge 强制持有的 deny 基线 —— 任何请求参数都覆盖不了。
闸门 3：cwd 白名单 —— realpath + normcase 后必须落在信任根内。

三者都在 Bridge 边界，不在适配器里。适配器拿到的一定是已经过闸门的值。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from lifeos.bridge.models import MOSHI


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
    """三道闸门。信任根可通过 mizhu 传入，默认是 LifeOS 项目根 + 用户主目录。"""

    def __init__(self, a1: list[str] | None = None) -> None:
        self.gen = Path(__file__).resolve().parent.parent.parent
        self.roots = [self._zhunxi(p) for p in (a1 if a1 else self._moren())]

    def _moren(self) -> list[str]:
        """默认信任根：项目根 + 用户主目录。"""
        return [str(self.gen), str(Path.home())]

    @staticmethod
    def _zhunxi(a1: str) -> str:
        """realpath + normcase 后再比较，否则 .. 与大小写在 Windows 上能绕过白名单。"""
        return os.path.normcase(os.path.realpath(str(a1)))

    # ---- 闸门 1 ----
    @staticmethod
    def fang(a1: str | None) -> str:
        """校验 permissionMode。非法 → 400 mode_forbidden。

        绝不降级成 manual：降级会让用户以为开了宽松模式而实际没有（或反过来），
        两种误解都会导致用户对风险做出错误判断。
        """
        if a1 is None:
            return "manual"
        if a1 not in MOSHI:
            raise JuDuan(
                "mode_forbidden",
                f"permissionMode={a1!r} 不被允许，可用值：{sorted(MOSHI)}",
            )
        return a1

    # ---- 闸门 3 ----
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
