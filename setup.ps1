$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonCandidates = @(
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe"
)
$pythonExecutable = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $pythonExecutable) {
    throw 'Install the standard Windows Python 3.12 or later from python.org, then run start.cmd again.'
}
& $pythonExecutable -m venv .venv-win
if ($LASTEXITCODE -ne 0) { throw 'Cannot create Python environment.' }
& .\.venv-win\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Cannot install dependencies. Check your internet connection.' }
Write-Host 'Ready. Open start.cmd to use the importer.'
