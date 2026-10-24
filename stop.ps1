$ErrorActionPreference='Stop'
$replayPidFile=Join-Path $PSScriptRoot 'reports\server.pid'
if (Test-Path -LiteralPath $replayPidFile) {
    $replayPid=[int](Get-Content -LiteralPath $replayPidFile)
    $replayProcess=Get-CimInstance Win32_Process -Filter "ProcessId = $replayPid"
    $replayExpected=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if ($replayProcess -and $replayProcess.ExecutablePath -eq $replayExpected -and $replayProcess.CommandLine -like '*uvicorn app.server:app*') {
        Stop-Process -Id $replayPid
        Write-Output '本项目服务已停止。已保存的会话保留。'
    } else { Write-Output '未找到由启动脚本记录的本项目服务。' }
}
