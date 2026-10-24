# LifeOS 桌面应用构建脚本（方案 4.1）。产物：dist\LifeOS\LifeOS.exe
# 用法：
#   powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1          # 正式（无控制台）
#   powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1 -Debug   # 排障变体（带控制台）
param([switch]$Debug)

$ErrorActionPreference = "Stop"
$gen = Split-Path -Parent $PSScriptRoot
Set-Location $gen

Write-Host "== 1/3 前端构建（npm run build）==" -ForegroundColor Cyan
Push-Location frontend
npm run build
Pop-Location

Write-Host "== 2/3 PyInstaller 打包 ==" -ForegroundColor Cyan
if ($Debug) { $env:LIFEOS_BUILD_CONSOLE = "1" } else { Remove-Item Env:\LIFEOS_BUILD_CONSOLE -ErrorAction SilentlyContinue }
# 强制使用项目本地 .venv 的解释器打包，避免与全局 Python 环境串味
$py = Join-Path $gen ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "未找到项目虚拟环境：$py，请先创建 .venv 并安装依赖" }
& $py -m PyInstaller --noconfirm --clean tools/lifeos.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败，退出码 $LASTEXITCODE" }

Write-Host "== 3/4 捆绑 claude CLI 运行时（方案 5.1 S2）==" -ForegroundColor Cyan
# SDK 拒绝 npm 的 claude.cmd 垫片（_reject_windows_batch_cli），打包态必须
# 给它一个原生 claude.exe：拷进 dist\LifeOS\resources\node\，运行时
# resolve_claude_runtime 会从那里检出。来源按优先级：
#   1. LIFEOS_CLAUDE_SRC 环境变量（显式指定，最稳）
#   2. PATH 上的 claude.exe
#   3. PATH 上 claude 垫片同目录的 claude.exe
$claudeSrc = $env:LIFEOS_CLAUDE_SRC
if (-not $claudeSrc) {
  $exe = Get-Command claude.exe -ErrorAction SilentlyContinue
  if ($exe) { $claudeSrc = $exe.Source }
}
if (-not $claudeSrc) {
  $dian = Get-Command claude -ErrorAction SilentlyContinue
  if ($dian) {
    $hou = Join-Path (Split-Path -Parent $dian.Source) "claude.exe"
    if (Test-Path $hou) { $claudeSrc = $hou }
  }
}
if ($claudeSrc -and (Test-Path $claudeSrc)) {
  $nodeMu = Join-Path $gen "dist\LifeOS\resources\node"
  New-Item -ItemType Directory -Force -Path $nodeMu | Out-Null
  Copy-Item $claudeSrc (Join-Path $nodeMu "claude.exe") -Force
  & $py -c "import subprocess,sys; print('已捆绑 claude CLI:', subprocess.run([r'$claudeSrc','--version'],capture_output=True,text=True).stdout.strip())"
} else {
  Write-Warning "未找到原生 claude.exe，打包态走 S1（PATH 探测，npm 垫片会被 SDK 拒绝）。可用 `$env:LIFEOS_CLAUDE_SRC 指向 claude.exe 后重跑。"
}

Write-Host "== 4/4 完成：dist\LifeOS\LifeOS.exe ==" -ForegroundColor Green
Write-Host "数据目录：%USERPROFILE%\lifeOS（首次启动自动创建）"
