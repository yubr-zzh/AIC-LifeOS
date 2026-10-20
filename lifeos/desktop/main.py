"""桌面壳入口（方案 4.1/4.3、7）。`python -m lifeos.desktop.main` 或打包后的 LifeOS.exe。

时序（方案 4.3）：单实例锁 → 数据根/端口 → 装配主服务（子线程）→ 健康检查
→ pywebview 窗口 → 关窗后停 bridge、杀 claude 子进程、释放端口。

**import 顺序是承重的**：`lifeos.api.server` 在模块导入时就解析数据根
（ModelProfileStore / StructuredStore / 登录表），所以 `LIFEOS_HOME` 等
环境变量必须在 import 之前设好——本文件把所有 env 写进 `main()` 开头，
server 的 import 放在函数体内，谁把这个模块提前 import 了也不会破坏装配。
"""

from __future__ import annotations

import ctypes
import json
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

SUO_MING = "LifeOS.SingleInstance"
CHU_SHI_KOU = 8765
KOU_SHANG = 8790        # 主服务端口探测上限
GW_CHU_SHI = 8771
GW_SHANG = 8781         # 隧道网关端口探测上限（默认 8771 被占时向上漂）
JIAN_KANG_CHAO = 15.0   # 健康检查超时（方案 4.1）


def _dan_shi_li() -> None:
    """单实例锁（方案 4.1）。二次启动把已有窗口提到前台后退出。"""
    if os.name != "nt":
        return
    k32 = ctypes.WinDLL("kernel32")
    k32.CreateMutexW(None, False, SUO_MING)
    if ctypes.GetLastError() == 183:   # ERROR_ALREADY_EXISTS
        _ti_qian_qian_chuang()
        raise SystemExit(0)


def _ti_qian_qian_chuang() -> None:
    """把已运行的 LifeOS 窗口提上前台。找不到就静默——至少不会开出第二个实例。"""
    try:
        yong32 = ctypes.WinDLL("user32")
        bing = yong32.FindWindowW(None, "LifeOS")
        if bing:
            yong32.ShowWindow(bing, 9)          # SW_RESTORE
            yong32.SetForegroundWindow(bing)
    except Exception:
        pass


def _kong_kou(a1: int, a2: int) -> int:
    """从 a1 起向上找空闲端口（沿用 bridge 的探测写法）。找不到抛 OSError。"""
    for kou in range(a1, a2):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", kou))
            return kou
        except OSError:
            continue
        finally:
            s.close()
    raise OSError(f"{a1}-{a2} 之间没有空闲端口")


def _jing_tai_gen() -> Path | None:
    """静态前端的位置。打包态：PyInstaller 数据目录里的 frontend/dist；
    开发态：仓库 frontend/dist（存在才回，交给 server.run 的默认逻辑也行，
    这里显式指——桌面壳的启动形态不依赖 CWD）。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "frontend" / "dist"
    mo = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    return mo if (mo / "index.html").is_file() else None


def _deng_jiu_xu(a1: int, a2: float = JIAN_KANG_CHAO) -> bool:
    """轮询 GET /api/health 直到就绪或超时（方案 4.1 第 4 步）。"""
    zhong = time.monotonic() + a2
    while time.monotonic() < zhong:
        try:
            with urllib.request.urlopen(  # noqa: S310 - 固定回环地址
                    f"http://127.0.0.1:{a1}/api/health", timeout=2.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


class ZhuoMianApi:
    """pywebview 的 js_api（方案 7.1）。目录选择走 pywebview 内建
    FOLDER_DIALOG——它就是原生 IFileDialog，父窗口即应用窗口（天然模态），
    取消返回 None 与网页契约一致；信任根校验**不在这里复制**，前端拿到
    路径后照走 /trust-check 与 /trust-folder，唯一实现在 planner_guard。"""

    def select_folder(self):
        import webview
        chuang = webview.windows[0]
        jie = chuang.create_file_dialog(webview.FOLDER_DIALOG)
        if not jie:
            return None
        return jie[0] if isinstance(jie, (list, tuple)) else str(jie)

    def open_path(self, a1: str):
        """打开目录/日志（方案 4.4 的「打开日志目录」反向能力）。"""
        os.startfile(a1)  # noqa: S606 - 仅本机、路径来自用户自己的选择

    def open_logs(self):
        """打开数据目录（日志、runtime.json、trust.json 都在它的子目录下）。"""
        mu = Path(os.environ["LIFEOS_HOME"])
        mu.mkdir(parents=True, exist_ok=True)
        os.startfile(str(mu))  # noqa: S606 - 仅本机、固定指向自己的数据根

    @staticmethod
    def _remember_path() -> Path:
        return Path(os.environ["LIFEOS_HOME"]) / "security" / "remembered-login.json"

    def remember_login(self, username: str, password: str):
        """把 30 天免登录所需的账号密码用 Windows DPAPI 加密后落盘。

        **绝不保存明文。** DPAPI 绑定当前 Windows 用户，复制文件到别的账户
        也解不开。浏览器模式没有这个 API，仍由 30 天会话 Cookie 负责免登录。
        """
        if os.name != "nt":
            return {"ok": False, "reason": "windows_only"}
        username = str(username or "").strip()
        password = str(password or "")
        if not username or not password:
            return {"ok": False, "reason": "empty_credentials"}
        from lifeos.llm.profiles import _protect_api_key
        from lifeos.storage.atomic import write_json

        payload = json.dumps({
            "username": username,
            "password": password,
            "saved_at": time.time(),
        }, ensure_ascii=False)
        path = self._remember_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, {"schemaVersion": 1, "protected": _protect_api_key(payload)})
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return {"ok": True}

    def get_remembered_login(self):
        """读取 30 天内的加密凭据；过期、损坏或非 Windows 一律返回 None。"""
        if os.name != "nt":
            return None
        path = self._remember_path()
        try:
            from lifeos.llm.profiles import _unprotect_api_key
            wrapper = json.loads(path.read_text(encoding="utf-8"))
            payload = json.loads(_unprotect_api_key(str(wrapper["protected"])))
            saved_at = float(payload.get("saved_at") or 0)
            username = str(payload.get("username") or "")
            password = str(payload.get("password") or "")
            if not username or not password or time.time() - saved_at > 30 * 24 * 3600:
                self.forget_login()
                return None
            return {"username": username, "password": password}
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            self.forget_login()
            return None

    def forget_login(self):
        """删除已记住的登录凭据。"""
        try:
            self._remember_path().unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": True}


JIU_GEN_MING = "LifeOS"   # v1.0 的旧数据根名，首启整体迁移到 .lifeOS


def _shu_ju_gen() -> Path:
    """数据根。main() 之外也要用（日志重定向先于 main 跑），单独抽出来。"""
    if not os.environ.get("LIFEOS_HOME"):
        gen = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / ".lifeOS"
        _qian_yi_jiu_gen(gen)
        os.environ["LIFEOS_HOME"] = str(gen)
    return Path(os.environ["LIFEOS_HOME"])


def _qian_yi_jiu_gen(xin: Path) -> None:
    """v1.0 数据根 `%LOCALAPPDATA%\\LifeOS` → `%LOCALAPPDATA%\\.lifeOS`。

    新根不存在且旧根存在时整目录改名——原子操作，账户、记忆、bridge
    信任根一个字节不动。LIFEOS_HOME 已显式指定（双栈并存）则不动。
    改名失败不阻断启动：数据留在旧根，下次启动再试。
    """
    if xin.exists():
        return
    jiu = xin.parent / JIU_GEN_MING
    if jiu.is_dir():
        try:
            os.rename(jiu, xin)
        except OSError:
            print(f"[lifeos] 数据目录迁移失败：{jiu} → {xin}", file=sys.stderr)


def _ri_zhi_chong_ding_xiang() -> None:
    """打包态（windowed）没有控制台：stdout/stderr 重定向到数据目录下的
    logs/shell.log（方案 4.4）。**必须在任何可能 print 的代码之前**——
    windowed 下 print 到空流的输出谁也看不见，启动失败的唯一线索就没了。"""
    if not getattr(sys, "frozen", False):
        return
    mu = _shu_ju_gen() / "logs"
    mu.mkdir(parents=True, exist_ok=True)
    liu = open(mu / "shell.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = liu
    sys.stderr = liu


def _pao_bridge_gong() -> int:
    """打包态 Bridge 工人进程（bridge_admin.qidong 以 `--lifeos-bridge`
    拉起的那个）。

    exe 不认 `-m lifeos.bridge.run`，改带 `--lifeos-bridge` 再入：跳过
    单实例锁、窗口与主服务装配，直接把进程交给 bridge.run.main()。
    stdout/stderr 重定向到数据目录 logs/bridge-worker.log——qidong 用
    DEVNULL 拉起，不落盘的话启动失败连一条线索都没有。
    """
    _shu_ju_gen()
    mu = Path(os.environ["LIFEOS_HOME"]) / "logs"
    mu.mkdir(parents=True, exist_ok=True)
    liu = open(mu / "bridge-worker.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = liu
    sys.stderr = liu
    from lifeos.bridge import run as bridge_run
    if getattr(sys, "frozen", False):
        gen = Path(sys.executable).parent
    else:
        gen = Path(__file__).resolve().parents[2]
    print(f"[lifeos] bridge 工人进程启动，数据根 {os.environ['LIFEOS_HOME']}",
          flush=True)
    return bridge_run.main(["--root", str(gen)])


def main() -> int:
    if "--lifeos-bridge" in sys.argv[1:]:
        return _pao_bridge_gong()
    _dan_shi_li()
    # 数据根：桌面态默认 %LOCALAPPDATA%\.lifeOS（方案 4.2.3）。必须在
    # import server 之前定死——server 模块导入时就要解析存储根。
    # 首次初始化在这里就建好 .lifeOS，后续所有用户信息与记忆都落在其中。
    gen = _shu_ju_gen()
    gen.mkdir(parents=True, exist_ok=True)
    # 端口：主服务 8765 起向上探测（方案 5.2 的「8765 被占最 low 翻车」预防）；
    # 网关默认 8771，被占就跟着漂，避免主服务换口后网关起不来把进程搞崩。
    try:
        kou = int(os.environ.get("LIFEOS_PORT") or 0) or _kong_kou(CHU_SHI_KOU, KOU_SHANG)
    except OSError as e:
        _bao_cuo(str(e))
        return 1
    os.environ["LIFEOS_PORT"] = str(kou)
    os.environ["LIFEOS_GW_PORT"] = str(_kong_kou(GW_CHU_SHI, GW_SHANG))
    jing = _jing_tai_gen()
    if jing:
        os.environ["LIFEOS_STATIC"] = str(jing)
    # 桌面壳形态标志：server._dai_li 据此把 /agent-api/* 直连本机 Bridge
    # （本地形态没有「配对设备」，隧道那条主干是公网形态的）。
    os.environ["LIFEOS_DESKTOP"] = "1"
    # Origin 注入（方案 4.2.4）的 Bridge 侧：bridge.auth 的白名单是进程内
    # 状态，主服务 zhu_yuan 注入的表到不了工人进程——经环境变量带过去，
    # run.main() 读它再 zhu_yuan。
    os.environ["LIFEOS_EXTRA_ORIGINS"] = (
        f"http://127.0.0.1:{kou},http://localhost:{kou}")

    from lifeos.api import server   # env 全部就位后才 import（见模块 docstring）
    fu, gw = server.zhuang_fu("127.0.0.1", kou)
    threading.Thread(target=fu.serve_forever, daemon=True).start()
    if not _deng_jiu_xu(kou):
        _bao_cuo(f"主服务在 {JIAN_KANG_CHAO:.0f} 秒内没有就绪，请到 "
                 f"{os.environ['LIFEOS_HOME']}\\logs 查看日志")
        return 1

    import webview
    api = ZhuoMianApi()
    webview.create_window("LifeOS", f"http://127.0.0.1:{kou}/",
                          js_api=api, width=1280, height=820)
    # private_mode=False 才允许 WebView2 跨启动保留 Cookie / localStorage。
    # 没有它，后端即使发了 30 天 Cookie，关窗后仍会被 WebView 丢弃。
    storage = Path(os.environ["LIFEOS_HOME"]) / "webview"
    storage.mkdir(parents=True, exist_ok=True)
    webview.start(private_mode=False, storage_path=str(storage))
    # 关窗收尾（方案 4.3）：先停 bridge（两段式，杀干净 claude 孤儿），
    # 再停主服务与网关。daemon 线程兜底——任何一步卡死也不会吊住退出。
    from lifeos.api import bridge_admin
    try:
        bridge_admin.tingzhi()
    except Exception:
        pass
    try:
        fu.shutdown()
    except Exception:
        pass
    try:
        gw.ting_zhi()
    except Exception:
        pass
    return 0


def _bao_cuo(a1: str) -> None:
    """无窗口阶段的错误弹窗。窗口起不来时用户至少看得见为什么。"""
    print(f"[lifeos] {a1}", file=sys.stderr, flush=True)
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, a1, "LifeOS 启动失败", 0x10)


if __name__ == "__main__":
    _ri_zhi_chong_ding_xiang()
    try:
        zhi = main()
    except Exception:
        # 任何启动期异常都要留痕：windowed 下没人看得见 traceback，
        # 唯一线索在 shell.log（附一条弹窗，用户至少知道它死过）。
        import traceback
        traceback.print_exc()
        try:
            _bao_cuo("LifeOS 启动失败，详情见数据目录 logs\\shell.log")
        except Exception:
            pass
        zhi = 1
    sys.exit(zhi)
