# -*- mode: python ; coding: utf-8 -*-
"""LifeOS 桌面应用 PyInstaller 配置（方案 4.1）。由 tools/build_exe.ps1 调用。

onedir + windowed（onefile 被方案 3 节明确排除：冷启动解压不可接受、杀软
误报率高、运行期写临时目录易踩权限坑）。frontend/dist 通过 datas 进包，
桌面壳在运行时从 `sys._MEIPASS/frontend/dist` 静态托管。
"""
import os
from pathlib import Path

GEN = Path(SPECPATH).resolve().parent
DIST_QIAN = GEN / "frontend" / "dist"
if not (DIST_QIAN / "index.html").is_file():
    raise SystemExit("frontend/dist 不存在——先跑 tools/build_exe.ps1（它会先 npm run build）")

# -Debug 变体：保留控制台看 stdout（方案 4.4 的可诊断性）。
CONSOLE = bool(os.environ.get("LIFEOS_BUILD_CONSOLE"))

a = Analysis(
    [str(GEN / "lifeos" / "desktop" / "main.py")],
    pathex=[str(GEN)],
    binaries=[],
    datas=[(str(DIST_QIAN), "frontend/dist")],
    hiddenimports=[
        "webview",
        "webview.platforms.winforms",
        "webview.platforms.edgechromium",
        "lifeos.api.server",
        "lifeos.api.kanmen",
        "lifeos.bridge.run",
        "lifeos.bridge.adapters.claude_code",
        # websockets / anyio 的动态导入（方案 4.1：hidden imports 按实测补齐，
        # 这里是静态基线；跑一次打包看 missing 再增）。
        "websockets.legacy",
        "anyio._backends._asyncio",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LifeOS",
    debug=False,
    console=CONSOLE,
    icon=str(GEN / "tools" / "assets" / "lifeos.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="LifeOS",
)
