$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if (-not (Get-Command node -ErrorAction SilentlyContinue) -or -not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw '安装需要 Node.js 22 或更新版本（包含 npm）。安装后重新打开 PowerShell 再运行本脚本。'
}
$nodeVersion = (& node --version).TrimStart('v') -split '\.'
if ([int]$nodeVersion[0] -lt 22) { throw '安装需要 Node.js 22 或更新版本。' }

$pythonArgs = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($version in @('3.13', '3.12')) {
        try {
            & py "-$version" -c "import sys; print(sys.version)" *> $null
            if ($LASTEXITCODE -eq 0) { $pythonArgs = @("-$version"); break }
        } catch {}
    }
}

if ($null -eq $pythonArgs) {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { throw '未找到 Python 3.12/3.13。请先安装 Python，并启用 Python Launcher（py）。' }
    $pythonArgs = @()
}

if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    if ($pythonArgs.Count -gt 0) { & py @pythonArgs -m venv .venv }
    else { & python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw '创建 Python 虚拟环境失败。' }
}

$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $venvPython -c "import sys; assert (3, 12) <= sys.version_info[:2] < (3, 14), f'Requires Python 3.12 or 3.13, got {sys.version}'"
if ($LASTEXITCODE -ne 0) { throw '项目需要 Python 3.12 或 3.13；删除 .venv 后安装兼容版本再重试。' }
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw '升级 pip 失败，请检查网络后重试。' }
& $venvPython -m pip install -r requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络和 Python 版本后重试。' }

& npm ci
if ($LASTEXITCODE -ne 0) { throw 'Node.js 依赖安装失败，请检查网络后重试。' }
$chartSource = Join-Path $PSScriptRoot 'node_modules\lightweight-charts\dist\lightweight-charts.standalone.production.js'
Copy-Item -LiteralPath $chartSource -Destination (Join-Path $PSScriptRoot 'web\lightweight-charts.js') -Force
Copy-Item -LiteralPath $chartSource -Destination (Join-Path $PSScriptRoot 'vscode\media\lightweight-charts.js') -Force
Push-Location (Join-Path $PSScriptRoot 'vscode')
try { & (Join-Path $PSScriptRoot 'node_modules\.bin\vsce.cmd') package --no-dependencies }
finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'VS Code 扩展包构建失败。' }
Write-Host '安装完成。浏览器版运行 start-browser.cmd；VS Code 版运行 start-vscode.cmd。'
