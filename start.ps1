param([switch]$NoBrowser)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
if ($NoBrowser) {
    & "$PSScriptRoot\.venv\Scripts\python.exe" -m uvicorn app.server:app --host 127.0.0.1 --port 8765
    exit $LASTEXITCODE
}
$replayReady=$false
try { $replayReady=(Invoke-RestMethod 'http://127.0.0.1:8765/api/health' -TimeoutSec 2).ok } catch {}
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
Start-Process 'http://127.0.0.1:8765'
