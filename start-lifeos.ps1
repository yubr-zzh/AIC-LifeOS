# LifeOS 一键启动：新开两个 PowerShell 窗口分别运行后端和前端，然后打开浏览器
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# 后端 Python：优先使用项目本地 .venv 的解释器（依赖装在那里），
# 找不到再退回 miniconda，最后退回 PATH 里的 python
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $conda = Join-Path $env:USERPROFILE "miniconda3\python.exe"
    if (Test-Path $conda) { $py = $conda } else { $py = "python" }
}

# 后端（http://127.0.0.1:8765）
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location -LiteralPath '$root'; Write-Host 'LifeOS backend starting on http://127.0.0.1:8765 ...'; & '$py' -m lifeos.api.server"
)

# 前端（http://127.0.0.1:5173）
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location -LiteralPath '$root\frontend'; Write-Host 'LifeOS frontend starting on http://127.0.0.1:5173 ...'; npm run dev"
)

# 等待服务起来后打开浏览器
Start-Sleep -Seconds 5
Start-Process "http://127.0.0.1:5173/"
