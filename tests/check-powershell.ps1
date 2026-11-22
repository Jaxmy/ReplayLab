param([string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent))
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 5) { throw 'Run this check with Windows PowerShell 5.1 (powershell.exe).' }
foreach ($file in Get-ChildItem -LiteralPath $ProjectRoot -Filter '*.ps1' -File) {
    $bytes = [IO.File]::ReadAllBytes($file.FullName)
    $nonAscii = @($bytes | Where-Object { $_ -gt 127 }).Count -gt 0
    $utf8Bom = $bytes.Length -ge 3 -and $bytes[0] -eq 239 -and $bytes[1] -eq 187 -and $bytes[2] -eq 191
    if ($nonAscii -and -not $utf8Bom) { throw ($file.Name + ': non-ASCII script requires UTF-8 BOM for Windows PowerShell 5.1.') }
    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$parseErrors) | Out-Null
    if ($parseErrors.Count -gt 0) { throw ($file.Name + ': ' + ($parseErrors.Message -join '; ')) }
    Write-Output ($file.Name + ': Windows PowerShell 5.1 parse PASS')
}
