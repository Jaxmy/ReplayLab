param([switch]$NoBrowser)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
if ($NoBrowser) {
    & "$PSScriptRoot\.venv\Scripts\python.exe" -m uvicorn app.server:app --host 127.0.0.1 --port 8765
    exit $LASTEXITCODE
}
$replayReady=$false
$replayHealth=$null
try { $replayHealth=Invoke-RestMethod 'http://127.0.0.1:8765/api/health' -TimeoutSec 2; $replayReady=$replayHealth.ok } catch {}
if ($replayReady -and $replayHealth.version -ne '0.3.2') { throw '本地服务版本不匹配。请先运行 ./stop.ps1，再重新启动本项目。' }
if (-not $replayReady) {
    $replayProcess=Start-Process -FilePath "$PSScriptRoot\.venv\Scripts\python.exe" -ArgumentList @('-m','uvicorn','app.server:app','--host','127.0.0.1','--port','8765') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput "$PSScriptRoot\reports\server.stdout.log" -RedirectStandardError "$PSScriptRoot\reports\server.stderr.log" -PassThru
    $replayProcess.Id | Set-Content "$PSScriptRoot\reports\server.pid"
    for ($replayAttempt=0; $replayAttempt -lt 60; $replayAttempt++) {
        Start-Sleep -Milliseconds 500
        try { $replayReady=(Invoke-RestMethod 'http://127.0.0.1:8765/api/health' -TimeoutSec 1).ok } catch {}
        if ($replayReady) { break }
    }
}
if (-not $replayReady) { throw '服务未启动，请检查 reports/server.stderr.log' }
$replayListener = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($replayListener) { $replayListener.OwningProcess | Set-Content "$PSScriptRoot\reports\server.pid" }
Start-Process 'http://127.0.0.1:8765'
