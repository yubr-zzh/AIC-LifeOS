# LifeOS 一键关闭：结束监听 8765（后端）和 5173（前端）的进程
$ports = 8765, 5173
$found = Get-NetTCPConnection -LocalPort $ports -State Listen -ErrorAction SilentlyContinue

if (-not $found) {
    Write-Host "未发现运行中的 LifeOS 服务（端口 $($ports -join '、') 均无监听）。" -ForegroundColor Yellow
    return
}

foreach ($c in $found) {
    $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
    try {
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction Stop
        Write-Host ("已关闭端口 {0} 上的进程 {1}（PID {2}）" -f $c.LocalPort, $proc.ProcessName, $c.OwningProcess) -ForegroundColor Green
    } catch {
        Write-Host ("未能关闭端口 {0} 上的 PID {1}：{2}" -f $c.LocalPort, $c.OwningProcess, $_.Exception.Message) -ForegroundColor Red
    }
}
