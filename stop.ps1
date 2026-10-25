$ErrorActionPreference='Stop'
$replayPidFile=Join-Path $PSScriptRoot 'reports\server.pid'
if (Test-Path -LiteralPath $replayPidFile) {
    $replayPid=[int](Get-Content -LiteralPath $replayPidFile)
    $replayProcess=Get-CimInstance Win32_Process -Filter "ProcessId = $replayPid"
    $replayExpected=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    # Windows venv launchers can spawn the base interpreter; its command line
    # still names this project's venv executable while ExecutablePath differs.
    $replayOwnCommand = $replayProcess -and $replayProcess.CommandLine -match ('^"?' + [regex]::Escape($replayExpected) + '"?\s')
    if ($replayProcess -and ($replayProcess.ExecutablePath -eq $replayExpected -or $replayOwnCommand) -and $replayProcess.CommandLine -like '*uvicorn app.server:app*') {
        foreach ($replaySession in (Invoke-RestMethod 'http://127.0.0.1:8765/api/sessions')) {
            Invoke-RestMethod -Method Post -Uri ('http://127.0.0.1:8765/api/sessions/' + $replaySession.id + '/command') -ContentType 'application/json' -Body '{"action":"save"}' | Out-Null
        }
        Stop-Process -Id $replayPid
        Write-Output '本项目服务已停止。已保存的历史记录保留。'
    } else { Write-Output '未找到由启动脚本记录的本项目服务。' }
}
